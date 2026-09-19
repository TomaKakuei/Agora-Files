from __future__ import annotations
import calendar
import contextlib
import copy
import hashlib
import json
import os
import queue
import secrets
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from ..adjudicator_schemas import AgentRuntimeProfileSpec
from ..package_db import materialize_world_package
from ..world_definition import default_wallet_payload
from ..world_definition import legacy_currency_inventory_entry
from ..world_definition import sync_world_definition_into_config

from .core import *

from .utils import *

from .geometry import *

from .schemas import *







class CoreBaseMixin:
    def __init__(self, package_root: Path, access_code: str) -> None:
        self.package_root = Path(package_root).resolve()
        _load_local_live_env(self.package_root)
        self.access_code = str(access_code or "").strip()
        self.context = load_pixel_world_context(str(self.package_root), self.access_code)
        self._advance_lock = threading.Lock()
        self._last_advanced_at = 0.0
        self._coordinator_queue: queue.Queue[LiveCoordinatorCommand] = queue.Queue()
        self._coordinator_move_queue: queue.Queue[LiveCoordinatorCommand] = queue.Queue()
        self._coordinator_trade_queue: queue.Queue[LiveCoordinatorCommand] = queue.Queue()
        self._coordinator_task_queue: queue.Queue[LiveCoordinatorCommand] = queue.Queue()
        self._coordinator_async_queue: queue.Queue[LiveCoordinatorCommand] = queue.Queue()
        self._coordinator_stop = threading.Event()
        self._coordinator_thread: threading.Thread | None = None
        self._coordinator_thread_lock = threading.Lock()
        self._inflight_ai_jobs = 0
        self._inflight_ai_jobs_lock = threading.Lock()
        self._snapshot_cache_lock = threading.Lock()
        self._snapshot_cache_dirty = True
        self._hot_world_snapshot: dict[str, Any] | None = None
        self._world_revision = 0
        self._published_snapshot_path = self.context.export_dir / "live_snapshot.json"
        self._published_snapshot_meta_path = self.context.export_dir / "live_snapshot.meta.json"
        self._session_heartbeat_cache: dict[str, str] = {}
        self._dirty_heartbeat_sessions: set[str] = set()
        self._last_heartbeat_flush_at = 0.0
        self._cached_live_ready_agent_ids: frozenset[str] | None = None
        self._cached_live_ready_source_key: tuple[str, int] | None = None
        self._cached_live_route_lookup: dict[str, dict[str, Any]] | None = None
        self._cached_live_executable_routes: list[dict[str, Any]] | None = None
        self._realtime_state_lock = threading.Lock()
        self._hot_agent_states: dict[str, dict[str, Any]] = {}
        self._dirty_hot_agent_ids: set[str] = set()
        self._hot_session_agents: dict[str, str] = {}
        self._hot_session_rooms: dict[str, str] = {}
        self._dirty_hot_session_ids: set[str] = set()
        self._realtime_input_queues: dict[str, deque[dict[str, Any]]] = {}
        self._realtime_tick_index = 0
        self._last_realtime_flush_at = 0.0
        self._pending_broadcasts: queue.Queue[dict[str, Any]] = queue.Queue()
        _LIVE_STORE_REGISTRY[(str(self.package_root), self.access_code)] = self

    def _invalidate_static_caches(self) -> None:
        self._cached_live_ready_agent_ids = None
        self._cached_live_ready_source_key = None
        self._cached_live_route_lookup = None
        self._cached_live_executable_routes = None

    def _normalize_tool_call(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        tool_name = str(value.get("tool_name", "")).strip()
        if tool_name in {"", "none", "noop"}:
            return None
        if tool_name not in {"follow_me", "go_to_room", "quote_item_for_gold", "quote_item_for_currency", "quote_item_for_price"}:
            return None
        normalized_tool_name = "quote_item_for_price" if tool_name in {"quote_item_for_gold", "quote_item_for_currency", "quote_item_for_price"} else tool_name
        return {
            "tool_name": normalized_tool_name,
            "target_room_id": str(value.get("target_room_id", "")).strip(),
            "item_id": str(value.get("item_id", "")).strip(),
            "quantity": max(1, _safe_int(value.get("quantity", 1), 1)),
            "reason": _trim_text(value.get("reason", ""), 240),
        }

    def _clone_payload(self, payload: Any) -> Any:
        return json.loads(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    def _touch_world_revision(self) -> int:
        with self._snapshot_cache_lock:
            self._world_revision += 1
            self._snapshot_cache_dirty = True
            return self._world_revision

    def ensure_runtime_workers(self) -> None:
        self.ensure_initialized()
        with self._coordinator_thread_lock:
            if self._coordinator_thread is not None and self._coordinator_thread.is_alive():
                return
            self._coordinator_stop.clear()
            self._coordinator_thread = threading.Thread(
                target=self._coordinator_loop,
                name=f"pixel-live-coordinator-{self.access_code}",
                daemon=True,
            )
            self._coordinator_thread.start()

    def shutdown_runtime_workers(self) -> None:
        self._coordinator_stop.set()
        try:
            self.flush_hot_spatial_state(force=True)
        except Exception:
            pass
        with self._coordinator_thread_lock:
            thread = self._coordinator_thread
            self._coordinator_thread = None
        if thread is not None:
            thread.join(timeout=2.0)

    def wait_for_background_idle(self, timeout_seconds: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        while time.monotonic() < deadline:
            with self._inflight_ai_jobs_lock:
                inflight_ai_jobs = self._inflight_ai_jobs
            if (
                self._coordinator_queue.empty()
                and self._coordinator_move_queue.empty()
                and self._coordinator_trade_queue.empty()
                and self._coordinator_task_queue.empty()
                and self._coordinator_async_queue.empty()
                and inflight_ai_jobs <= 0
            ):
                return True
            time.sleep(0.05)
        return False

    def _run_coordinator_command(self, command: LiveCoordinatorCommand) -> dict[str, Any]:
        self.ensure_runtime_workers()
        self._coordinator_queue.put(command)
        if not command.done.wait(timeout=max(0.1, float(command.timeout_seconds))):
            raise TimeoutError(f"timed out waiting for live coordinator command: {command.command}")
        if command.error is not None:
            raise command.error
        return dict(command.response or {})

    def _coordinator_loop(self) -> None:
        self.ensure_initialized()
        while not self._coordinator_stop.is_set():
            command: LiveCoordinatorCommand | None = None
            try:
                command = self._coordinator_queue.get_nowait()
            except queue.Empty:
                try:
                    command = self._coordinator_move_queue.get_nowait()
                except queue.Empty:
                    try:
                        command = self._coordinator_trade_queue.get_nowait()
                    except queue.Empty:
                        try:
                            command = self._coordinator_task_queue.get_nowait()
                        except queue.Empty:
                            try:
                                command = self._coordinator_async_queue.get(timeout=LIVE_COORDINATOR_POLL_SECONDS)
                            except queue.Empty:
                                command = None
            if command is not None:
                try:
                    if command.command == "submit_action":
                        command.response = self._handle_submit_action_command(command)
                    elif command.command == "heartbeat":
                        command.response = self._handle_heartbeat_command(command)
                    elif command.command == "ai_completion":
                        self._handle_ai_completion_command(command)
                        command.response = {"status": "ok"}
                    else:
                        raise RuntimeError(f"unsupported live coordinator command: {command.command}")
                except Exception as exc:
                    command.error = exc
                finally:
                    command.done.set()
            now = _now_ts()
            if now - float(self._last_advanced_at or 0.0) >= LIVE_TICK_INTERVAL_SECONDS:
                with self._advance_lock:
                    if now - float(self._last_advanced_at or 0.0) >= LIVE_TICK_INTERVAL_SECONDS:
                        # The coordinator is the single writer for live ticks and task progression.
                        try:
                            with self._write_transaction() as conn:
                                self._advance_world_state(conn, now=now)
                                self._touch_world_revision()
                                self._refresh_hot_world_snapshot(conn, now=now)
                                self._flush_dirty_heartbeats(conn, force=False)
                                conn.commit()
                            self._last_advanced_at = now
                        except Exception:
                            time.sleep(0.05)
            else:
                has_dirty = False
                with self._snapshot_cache_lock:
                    if self._dirty_heartbeat_sessions:
                        now_ts = _now_ts()
                        if (
                            len(self._dirty_heartbeat_sessions) >= LIVE_HEARTBEAT_FLUSH_BATCH
                            or now_ts - float(self._last_heartbeat_flush_at or 0.0) >= LIVE_HEARTBEAT_FLUSH_SECONDS
                        ):
                            has_dirty = True
                if has_dirty:
                    try:
                        with self._write_transaction() as conn:
                            if self._flush_dirty_heartbeats(conn, force=False):
                                conn.commit()
                    except Exception:
                        time.sleep(0.02)

    def advance_world(self, *, preferred_session_id: str = "", force: bool = False) -> bool:
        self.ensure_initialized()
        now = _now_ts()
        with self._advance_lock:
            if not force and now - float(self._last_advanced_at or 0.0) < LIVE_TICK_INTERVAL_SECONDS:
                return False
            with self._write_transaction() as conn:
                self._advance_world_state(conn, now=now, preferred_session_id=preferred_session_id)
                self._touch_world_revision()
                self._refresh_hot_world_snapshot(conn, now=now)
                self._flush_dirty_heartbeats(conn, force=False)
                conn.commit()
            self._last_advanced_at = now
        return True

    def _advance_world_state(self, conn: sqlite3.Connection, *, now: float, preferred_session_id: str = "") -> None:
        self._reap_expired_sessions(conn, now)
        self._update_room_states(conn, now)
        self._advance_active_rooms(conn, now, preferred_session_id=preferred_session_id)
        self._update_room_states(conn, now)

