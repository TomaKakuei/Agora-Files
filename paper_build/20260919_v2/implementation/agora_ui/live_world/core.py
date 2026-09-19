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
from ..package_db import ensure_materialized_world_package
from ..world_definition import default_wallet_payload
from ..world_definition import legacy_currency_inventory_entry
from ..world_definition import sync_world_definition_into_config

from .schemas import LiveCoordinatorCommand, PixelWorldContext
from .geometry import _load_room_list, _room_tile_index, _room_wall_indexes
from .agents import _resolve_agent_seed_payloads
from .utils import _session_timeout_seconds, _roam_step_seconds



LIVE_SCHEMA_VERSION = 4
DEFAULT_SESSION_TIMEOUT_SECONDS = 1800.0
DEFAULT_ROAM_STEP_SECONDS = 4.0
DEFAULT_HEARTBEAT_SECONDS = 5.0
LOCAL_LIVE_ENV_FILENAMES = (".agora_ui_live.local.env", ".env.local")
GLOBAL_LIVE_ENV_PATHS = (Path.home() / ".config" / "agora_ui_runtime.env",)
LIVE_TICK_INTERVAL_SECONDS = 0.75
LIVE_COORDINATOR_POLL_SECONDS = 0.1
LIVE_ACTION_SYNC_TIMEOUT_SECONDS = 20.0
LIVE_ACTION_ACCEPT_TIMEOUT_SECONDS = 5.0
LIVE_AI_BROKER_WORKERS = 2
LIVE_HEARTBEAT_FLUSH_SECONDS = 8.0
LIVE_HEARTBEAT_FLUSH_BATCH = 12
LIVE_REALTIME_TICK_SECONDS = 0.05
LIVE_REALTIME_TICK_MS = int(LIVE_REALTIME_TICK_SECONDS * 1000)
LIVE_REALTIME_FLUSH_SECONDS = 1.0
LIVE_REALTIME_MAX_BUFFERED_INPUTS = 12
LIVE_REALTIME_MAX_INPUTS_PER_TICK = 1
LIVE_ASYNC_ACTION_TYPES = frozenset({"message", "move"})
LIVE_TRADE_QUEUE_ACTION_TYPES = frozenset({"request_trade_quote"})
LIVE_TASK_QUEUE_ACTION_TYPES = frozenset({"assign_move_task"})
LIVE_ACCEPTED_ACTION_TYPES = LIVE_ASYNC_ACTION_TYPES | LIVE_TRADE_QUEUE_ACTION_TYPES | LIVE_TASK_QUEUE_ACTION_TYPES
_LIVE_STORE_REGISTRY: dict[tuple[str, str], "PixelLiveStore"] = {}
_LIVE_AI_BROKER_QUEUE: queue.Queue[tuple["PixelLiveStore", dict[str, Any]]] = queue.Queue()
_LIVE_AI_BROKER_THREADS: list[threading.Thread] = []
_LIVE_AI_BROKER_LOCK = threading.Lock()
_thread_local = threading.local()


def _ensure_live_ai_broker_threads() -> None:
    with _LIVE_AI_BROKER_LOCK:
        alive_threads = [thread for thread in _LIVE_AI_BROKER_THREADS if thread.is_alive()]
        _LIVE_AI_BROKER_THREADS[:] = alive_threads
        while len(_LIVE_AI_BROKER_THREADS) < LIVE_AI_BROKER_WORKERS:
            worker_index = len(_LIVE_AI_BROKER_THREADS)
            thread = threading.Thread(
                target=_live_ai_broker_loop,
                name=f"pixel-live-ai-{worker_index}",
                daemon=True,
            )
            thread.start()
            _LIVE_AI_BROKER_THREADS.append(thread)


def _live_ai_broker_loop() -> None:
    while True:
        store, payload = _LIVE_AI_BROKER_QUEUE.get()
        if store is None:
            break
        try:
            completion_payload = store._run_ai_broker_job(payload)
        except Exception as exc:
            completion_payload = {
                **payload,
                "completion_kind": "error",
                "error": str(exc),
            }
        finally:
            store._coordinator_queue.put(
                LiveCoordinatorCommand(
                    command="ai_completion",
                    payload=completion_payload,
                    wait_for_completion=False,
                    timeout_seconds=LIVE_ACTION_ACCEPT_TIMEOUT_SECONDS,
                )
            )
            with store._inflight_ai_jobs_lock:
                store._inflight_ai_jobs = max(0, store._inflight_ai_jobs - 1)


def _load_local_live_env(package_root: Path) -> None:
    env_paths = [Path(package_root).resolve() / name for name in LOCAL_LIVE_ENV_FILENAMES]
    env_paths.extend(GLOBAL_LIVE_ENV_PATHS)
    for env_path in env_paths:
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
                if not line or "=" not in line:
                    continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and value and key not in os.environ:
                os.environ[key] = value


def _normalize_live_model_name(model_name: str) -> str:
    text = str(model_name or "").strip()
    if "-think-" in text:
        text = text.split("-think-")[0].strip()
    if text == "gemini-3.1-flash-lite":
        return "gemini-3.1-flash-lite"
    return text


def _load_vertex_json_client_class():
    from ..run_interaction_simulation import VertexJsonClient

    return VertexJsonClient


def _live_ready_assets_path(root: Path) -> Path:
    resolved_root = Path(root).resolve()
    candidate_bases = [
        resolved_root / "assets" / "generated" / "events",
        resolved_root / "frontend" / "assets" / "generated" / "events",
    ]
    for base in candidate_bases:
        curated = base / "live_ready_assets.json"
        if curated.is_file():
            return curated
        bootstrap = base / "bootstrap_assets.json"
        if bootstrap.is_file():
            return bootstrap
    return candidate_bases[0] / "bootstrap_assets.json"


def _resolve_export_dir(package_root: Path, access_code: str) -> Path:
    return (package_root / "output" / "package_exports" / access_code).resolve()


@lru_cache(maxsize=32)
def load_pixel_world_context(package_root_str: str, access_code: str) -> PixelWorldContext:
    package_root = Path(package_root_str).resolve()
    normalized = str(access_code or "").strip()
    export_dir = _resolve_export_dir(package_root, normalized)
    package_db = export_dir / "world_package.db"
    if not package_db.is_file():
        raise FileNotFoundError(f"package not found: {normalized}")

    workspace = export_dir / "materialized"
    from macro_ui.build_macro_ui import load_world_config_from_access_code

    workspace = ensure_materialized_world_package(package_db, output_dir=workspace)
    config, metadata = load_world_config_from_access_code(package_root, normalized, materialize_dir=workspace)
    config = sync_world_definition_into_config(config)
    rooms = _load_room_list(workspace)
    room_lookup = {str(room.get("room_id", "")).strip(): room for room in rooms if str(room.get("room_id", "")).strip()}
    room_tile_index = _room_tile_index(rooms)
    outer_wall_tile_index, inner_wall_tile_index = _room_wall_indexes(rooms, room_tile_index)
    agent_seed_payloads = _resolve_agent_seed_payloads(workspace)
    live_db_path = export_dir / "live_state.db"
    return PixelWorldContext(
        package_root=package_root,
        access_code=normalized,
        export_dir=export_dir,
        package_db=package_db,
        workspace=workspace,
        config=config,
        metadata=dict(metadata),
        rooms=rooms,
        room_lookup=room_lookup,
        room_tile_index=room_tile_index,
        outer_wall_tile_index=outer_wall_tile_index,
        inner_wall_tile_index=inner_wall_tile_index,
        agent_seed_payloads=agent_seed_payloads,
        live_db_path=live_db_path,
        session_timeout_seconds=_session_timeout_seconds(config),
        roam_step_seconds=_roam_step_seconds(config),
    )


def iter_registered_live_stores() -> list[PixelLiveStore]:
    return list(_LIVE_STORE_REGISTRY.values())


def shutdown_registered_live_stores() -> None:
    stores = list(_LIVE_STORE_REGISTRY.values())
    for store in stores:
        try:
            store.wait_for_background_idle(timeout_seconds=1.0)
        except Exception:
            continue
    for store in stores:
        try:
            store.shutdown_runtime_workers()
        except Exception:
            continue
    with _LIVE_AI_BROKER_LOCK:
        threads = list(_LIVE_AI_BROKER_THREADS)
        for _ in range(len(threads)):
            _LIVE_AI_BROKER_QUEUE.put((None, {}))
        _LIVE_AI_BROKER_THREADS.clear()
    for thread in threads:
        try:
            thread.join(timeout=1.0)
        except Exception:
            continue
    _LIVE_STORE_REGISTRY.clear()
    get_pixel_live_store.cache_clear()


@lru_cache(maxsize=32)
def get_pixel_live_store(package_root_str: str, access_code: str) -> PixelLiveStore:
    from .store import PixelLiveStore
    return PixelLiveStore(Path(package_root_str), access_code)

__all__ = ['LIVE_SCHEMA_VERSION', 'DEFAULT_SESSION_TIMEOUT_SECONDS', 'DEFAULT_ROAM_STEP_SECONDS', 'DEFAULT_HEARTBEAT_SECONDS', 'LOCAL_LIVE_ENV_FILENAMES', 'GLOBAL_LIVE_ENV_PATHS', 'LIVE_TICK_INTERVAL_SECONDS', 'LIVE_COORDINATOR_POLL_SECONDS', 'LIVE_ACTION_SYNC_TIMEOUT_SECONDS', 'LIVE_ACTION_ACCEPT_TIMEOUT_SECONDS', 'LIVE_AI_BROKER_WORKERS', 'LIVE_HEARTBEAT_FLUSH_SECONDS', 'LIVE_HEARTBEAT_FLUSH_BATCH', 'LIVE_REALTIME_TICK_SECONDS', 'LIVE_REALTIME_TICK_MS', 'LIVE_REALTIME_FLUSH_SECONDS', 'LIVE_REALTIME_MAX_BUFFERED_INPUTS', 'LIVE_REALTIME_MAX_INPUTS_PER_TICK', 'LIVE_ASYNC_ACTION_TYPES', 'LIVE_TRADE_QUEUE_ACTION_TYPES', 'LIVE_TASK_QUEUE_ACTION_TYPES', 'LIVE_ACCEPTED_ACTION_TYPES', '_LIVE_STORE_REGISTRY', '_LIVE_AI_BROKER_QUEUE', '_LIVE_AI_BROKER_THREADS', '_LIVE_AI_BROKER_LOCK', '_thread_local', '_ensure_live_ai_broker_threads', '_live_ai_broker_loop', '_load_local_live_env', '_normalize_live_model_name', '_load_vertex_json_client_class', '_live_ready_assets_path', '_resolve_export_dir', 'load_pixel_world_context', 'iter_registered_live_stores', 'shutdown_registered_live_stores', 'get_pixel_live_store']
