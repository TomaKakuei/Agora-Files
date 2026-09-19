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







class CoreSnapshotMixin:
    def _build_hot_world_snapshot(self, conn: sqlite3.Connection, *, now: float | None = None) -> dict[str, Any]:
        current_now = float(now if now is not None else _now_ts())
        room_rows = conn.execute("SELECT * FROM rooms ORDER BY room_id").fetchall()
        room_active_by_id = {
            str(row["room_id"]): bool(int(row["active"]))
            for row in room_rows
            if str(row["room_id"]).strip()
        }
        roaming_rows = conn.execute(
            "SELECT room_id, agent_id, path_json, offset_index FROM roaming_plans"
        ).fetchall()
        roaming_plan_by_key = {
            (str(row["room_id"]), str(row["agent_id"])): row
            for row in roaming_rows
            if str(row["room_id"]).strip() and str(row["agent_id"]).strip()
        }
        agent_rows = conn.execute("SELECT * FROM agents ORDER BY agent_id").fetchall()
        agent_updated_at_seconds = {
            str(row["agent_id"]): _iso_to_ts(row["last_updated_at"], current_now)
            for row in agent_rows
            if str(row["agent_id"]).strip()
        }
        live_ready_agent_ids = sorted(self._live_ready_agent_ids())
        live_ready_agent_id_set = set(live_ready_agent_ids)
        rooms = [
            self._room_payload(conn, str(row["room_id"]), row=row)
            for row in room_rows
        ]
        agents = [
            self._agent_payload(
                conn,
                row,
                current_now,
                room_active_by_id=room_active_by_id,
                roaming_plan_by_key=roaming_plan_by_key,
                agent_updated_at_seconds=agent_updated_at_seconds,
                live_ready_agent_ids=live_ready_agent_id_set,
            )
            for row in agent_rows
        ]
        latest_event_row = conn.execute("SELECT COALESCE(MAX(event_id), 0) AS max_event_id FROM events").fetchone()
        latest_event_id = int(latest_event_row["max_event_id"] if latest_event_row is not None else 0)
        available_routes = self._live_executable_routes(conn)
        with self._snapshot_cache_lock:
            world_revision = int(self._world_revision)
        return {
            "updated_at": _now_iso(),
            "rooms": rooms,
            "agents": agents,
            "available_routes": available_routes,
            "latest_event_id": latest_event_id,
            "live_ready_agent_ids": live_ready_agent_ids,
            "live_ready_count": len(live_ready_agent_ids),
            "world_name": str(self.context.config.get("scenario_meta", {}).get("world_name", "")),
            "world_id": str(self.context.config.get("scenario_meta", {}).get("world_id", "")),
            "asset_base_url": str(self.context.metadata.get("asset_base_url", "")),
            "map_grid_url": str(self.context.metadata.get("map_grid_url", "")),
            "world_config_url": str(self.context.metadata.get("world_config_url", "")),
            "asset_feed_url": str(self.context.metadata.get("asset_base_url", "")) + "events/latest.json",
            "bootstrap_feed_url": str(self.context.metadata.get("asset_base_url", "")) + "events/bootstrap_assets.json",
            "world_revision": world_revision,
            "poll_interval_ms": 1200,
        }

    def _publish_hot_world_snapshot(self, snapshot: dict[str, Any]) -> None:
        payload = snapshot
        meta_payload = {
            "access_code": self.access_code,
            "world_revision": int(payload.get("world_revision", 0)),
            "latest_event_id": int(payload.get("latest_event_id", 0)),
            "updated_at": str(payload.get("updated_at", "")),
            "room_count": len(payload.get("rooms", []) or []),
            "agent_count": len(payload.get("agents", []) or []),
        }
        self._published_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_suffix = f".{os.getpid()}.{threading.get_ident()}.tmp"
        snapshot_tmp = self._published_snapshot_path.with_name(f"{self._published_snapshot_path.name}{tmp_suffix}")
        meta_tmp = self._published_snapshot_meta_path.with_name(f"{self._published_snapshot_meta_path.name}{tmp_suffix}")
        snapshot_tmp.write_text(_json_dump(payload), encoding="utf-8")
        meta_tmp.write_text(_json_dump(meta_payload), encoding="utf-8")
        snapshot_tmp.replace(self._published_snapshot_path)
        meta_tmp.replace(self._published_snapshot_meta_path)

    def _snapshot_meta_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "updated_at": str(snapshot.get("updated_at", "")),
            "latest_event_id": int(snapshot.get("latest_event_id", 0) or 0),
            "world_revision": int(snapshot.get("world_revision", 0) or 0),
            "poll_interval_ms": int(snapshot.get("poll_interval_ms", 1200) or 1200),
        }

    def _load_published_hot_world_snapshot(self) -> dict[str, Any] | None:
        if not self._published_snapshot_path.is_file():
            return None
        try:
            payload = _json_load(self._published_snapshot_path.read_text(encoding="utf-8"), {})
        except Exception:
            return None
        return dict(payload) if isinstance(payload, dict) else None

    def _load_published_hot_world_snapshot_meta(self) -> dict[str, Any] | None:
        if not self._published_snapshot_meta_path.is_file():
            return None
        try:
            payload = _json_load(self._published_snapshot_meta_path.read_text(encoding="utf-8"), {})
        except Exception:
            return None
        return dict(payload) if isinstance(payload, dict) else None

    def _peek_hot_world_snapshot_meta(self) -> dict[str, Any] | None:
        with self._snapshot_cache_lock:
            snapshot = self._hot_world_snapshot
            dirty = self._snapshot_cache_dirty
            current_revision = int(self._world_revision)
            if snapshot is not None and not dirty:
                return self._snapshot_meta_payload(snapshot)
        published = self._load_published_hot_world_snapshot_meta()
        if published is None:
            return None
        published_revision = int(published.get("world_revision", 0) or 0)
        if published_revision < current_revision:
            return None
        return {
            "updated_at": str(published.get("updated_at", "")),
            "latest_event_id": int(published.get("latest_event_id", 0) or 0),
            "world_revision": published_revision,
            "poll_interval_ms": int(published.get("poll_interval_ms", 1200) or 1200),
        }

    def _refresh_hot_world_snapshot(self, conn: sqlite3.Connection, *, now: float | None = None) -> dict[str, Any]:
        snapshot = self._build_hot_world_snapshot(conn, now=now)
        with self._snapshot_cache_lock:
            prev_revision = self._hot_world_snapshot.get("world_revision", 0) if self._hot_world_snapshot else 0
            self._hot_world_snapshot = snapshot
            self._snapshot_cache_dirty = False
            current_revision = snapshot.get("world_revision", 0)
        if current_revision != prev_revision or prev_revision == 0:
            self._publish_hot_world_snapshot(snapshot)
        return snapshot

    def _get_hot_world_snapshot(self) -> dict[str, Any] | None:
        with self._snapshot_cache_lock:
            snapshot = self._hot_world_snapshot
            dirty = self._snapshot_cache_dirty
            current_revision = int(self._world_revision)
            if snapshot is not None and not dirty:
                return self._clone_payload(snapshot)
        published = self._load_published_hot_world_snapshot()
        if published is None:
            return None
        published_revision = int(published.get("world_revision", 0) or 0)
        if published_revision < current_revision:
            return None
        with self._snapshot_cache_lock:
            self._hot_world_snapshot = dict(published)
            self._snapshot_cache_dirty = False
            self._world_revision = max(int(self._world_revision), published_revision)
        return self._clone_payload(published)

    def _room_payload(self, conn: sqlite3.Connection, room_id: str, *, row: sqlite3.Row | None = None) -> dict[str, Any]:
        if row is None:
            row = conn.execute("SELECT * FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
        if row is None:
            room = self.context.room_lookup.get(room_id, {})
            return {
                "room_id": room_id,
                "name": str(room.get("name", room_id)),
                "human_count": 0,
                "active_agent_count": 0,
                "active": False,
                "activation_generation": 0,
                "last_active_at": "",
            }
        room = self.context.room_lookup.get(room_id, {})
        payload = _json_load(str(row["state_json"]), {})
        if not isinstance(payload, dict):
            payload = {}
        return {
            **payload,
            "room_id": room_id,
            "name": str(row["room_name"] or room.get("name", room_id)),
            "human_count": int(row["human_count"]),
            "active_agent_count": int(row["active_agent_count"]),
            "active": bool(int(row["active"])),
            "activation_generation": int(row["activation_generation"]),
            "last_active_at": str(row["last_active_at"]),
        }

    def _build_state_payload(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        since: int = 0,
        compact: bool = False,
        if_world_revision: int = 0,
    ) -> dict[str, Any]:
        session = self._session_payload(conn, session_id)
        if session is None or str(session.get("status", "")) != "active":
            raise FileNotFoundError(f"session not found: {session_id}")
        current_since = max(0, int(since))
        requested_revision = max(0, int(if_world_revision))
        snapshot_meta = self._peek_hot_world_snapshot_meta()
        if snapshot_meta is None:
            snapshot = self._refresh_hot_world_snapshot(conn)
            snapshot_meta = self._snapshot_meta_payload(snapshot)
        else:
            snapshot = None
        latest_event_id = int(snapshot_meta.get("latest_event_id", 0))
        world_revision = int(snapshot_meta.get("world_revision", 0))
        if compact and requested_revision and requested_revision == world_revision and current_since >= latest_event_id:
            return {
                "status": "ok",
                "mode": "compact",
                "unchanged": True,
                "access_code": self.access_code,
                "updated_at": str(snapshot_meta.get("updated_at", _now_iso())),
                "session": session,
                "events": [],
                "latest_event_id": latest_event_id,
                "world_revision": world_revision,
                "poll_interval_ms": int(snapshot_meta.get("poll_interval_ms", 1200) or 1200),
                "realtime": {
                    "enabled": True,
                    "transport": "websocket",
                    "tick_interval_ms": LIVE_REALTIME_TICK_MS,
                    "flush_interval_ms": int(LIVE_REALTIME_FLUSH_SECONDS * 1000),
                },
            }
        if snapshot is None:
            snapshot = self._get_hot_world_snapshot()
        if snapshot is None:
            snapshot = self._refresh_hot_world_snapshot(conn)
        room_id = str(session["room_id"])
        snapshot_rooms = snapshot.get("rooms", [])
        snapshot_agents = snapshot.get("agents", [])
        room = next((entry for entry in snapshot_rooms if str(entry.get("room_id", "")) == room_id), None)
        if room is not None:
            room = self._clone_payload(room)
        rooms = self._clone_payload(snapshot.get("rooms", []))
        agents = self._clone_payload(snapshot.get("agents", []))
        if room is None:
            room = self._room_payload(conn, room_id)
        session_events = [
            dict(row)
            for row in conn.execute(
                """
                SELECT event_id, session_id, room_id, agent_id, target_agent_id,
                       event_type, action_text, response_text, processed,
                       created_at, processed_at, payload_json
                  FROM events
                 WHERE event_id > ?
                   AND (
                     session_id = ?
                     OR (room_id = ? AND created_at >= ?)
                   )
                 ORDER BY event_id
                """,
                (
                    int(since),
                    session_id,
                    room_id,
                    str(session.get("created_at", "")),
                ),
            ).fetchall()
        ]
        active_room_agents = [agent for agent in agents if str(agent.get("room_id", "")) == room_id]
        if compact:
            compact_agents = self._clone_payload(active_room_agents)
            return {
                "status": "ok",
                "mode": "compact",
                "unchanged": False,
                "access_code": self.access_code,
                "updated_at": str(snapshot.get("updated_at", _now_iso())),
                "session": session,
                "room": room,
                "agents": compact_agents,
                "active_room_agents": compact_agents,
                "available_routes": self._clone_payload(snapshot.get("available_routes", [])),
                "events": session_events,
                "latest_event_id": latest_event_id,
                "world_name": str(snapshot.get("world_name", "")),
                "world_id": str(snapshot.get("world_id", "")),
                "asset_base_url": str(snapshot.get("asset_base_url", "")),
                "map_grid_url": str(snapshot.get("map_grid_url", "")),
                "world_config_url": str(snapshot.get("world_config_url", "")),
                "asset_feed_url": str(snapshot.get("asset_feed_url", "")),
                "bootstrap_feed_url": str(snapshot.get("bootstrap_feed_url", "")),
                "world_revision": world_revision,
                "poll_interval_ms": int(snapshot.get("poll_interval_ms", 1200) or 1200),
                "realtime": {
                    "enabled": True,
                    "transport": "websocket",
                    "tick_interval_ms": LIVE_REALTIME_TICK_MS,
                    "flush_interval_ms": int(LIVE_REALTIME_FLUSH_SECONDS * 1000),
                },
            }
        return {
            "status": "ok",
            "access_code": self.access_code,
            "updated_at": str(snapshot.get("updated_at", _now_iso())),
            "session": session,
            "room": room,
            "rooms": rooms,
            "agents": agents,
            "active_room_agents": active_room_agents,
            "available_routes": self._clone_payload(snapshot.get("available_routes", [])),
            "events": session_events,
            "latest_event_id": latest_event_id,
            "world_name": str(snapshot.get("world_name", "")),
            "world_id": str(snapshot.get("world_id", "")),
            "asset_base_url": str(snapshot.get("asset_base_url", "")),
            "map_grid_url": str(snapshot.get("map_grid_url", "")),
            "world_config_url": str(snapshot.get("world_config_url", "")),
            "asset_feed_url": str(snapshot.get("asset_feed_url", "")),
            "bootstrap_feed_url": str(snapshot.get("bootstrap_feed_url", "")),
            "live_ready_agent_ids": self._clone_payload(snapshot.get("live_ready_agent_ids", [])),
            "live_ready_count": int(snapshot.get("live_ready_count", 0)),
            "world_revision": world_revision,
            "poll_interval_ms": int(snapshot.get("poll_interval_ms", 1200) or 1200),
            "realtime": {
                "enabled": True,
                "transport": "websocket",
                "tick_interval_ms": LIVE_REALTIME_TICK_MS,
                "flush_interval_ms": int(LIVE_REALTIME_FLUSH_SECONDS * 1000),
            },
            "mode": "full",
            "unchanged": False,
        }

