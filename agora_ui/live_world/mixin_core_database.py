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







class CoreDatabaseMixin:
    def _connect(self) -> sqlite3.Connection:
        self.live_db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.live_db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextlib.contextmanager
    def _write_transaction(self):
        """Context manager for explicit write-locked SQLite transactions."""
        conn = self._connect()
        conn.isolation_level = "IMMEDIATE"
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def ensure_initialized(self) -> None:
        with self._write_transaction() as conn:
            self._create_schema(conn)
            if not self._is_seeded(conn):
                self._seed(conn)
                self._invalidate_static_caches()

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                access_code TEXT NOT NULL,
                claimed_agent_id TEXT NOT NULL,
                room_id TEXT NOT NULL,
                status TEXT NOT NULL,
                speed_seconds_per_round REAL NOT NULL,
                heartbeat_seconds REAL NOT NULL,
                created_at TEXT NOT NULL,
                last_heartbeat_at TEXT NOT NULL,
                last_state_index INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                room_id TEXT NOT NULL,
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                z INTEGER NOT NULL,
                main_character INTEGER NOT NULL DEFAULT 0,
                control_mode TEXT NOT NULL,
                claimed_by_session_id TEXT NOT NULL DEFAULT '',
                current_focus TEXT NOT NULL DEFAULT '',
                mainline_summary TEXT NOT NULL DEFAULT '',
                roam_index INTEGER NOT NULL DEFAULT 0,
                last_updated_at TEXT NOT NULL,
                state_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY,
                room_name TEXT NOT NULL,
                human_count INTEGER NOT NULL DEFAULT 0,
                active_agent_count INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 0,
                activation_generation INTEGER NOT NULL DEFAULT 0,
                last_active_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                state_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS roaming_plans (
                room_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                path_json TEXT NOT NULL,
                offset_index INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (room_id, agent_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                client_action_id TEXT NOT NULL DEFAULT '',
                room_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                target_agent_id TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL,
                action_text TEXT NOT NULL DEFAULT '',
                response_text TEXT NOT NULL DEFAULT '',
                processed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                processed_at TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT ''
            )
            """
        )
        if not self._client_action_id_column_present(conn):
            conn.execute("ALTER TABLE events ADD COLUMN client_action_id TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS route_catalog (
                route_id TEXT PRIMARY KEY,
                route_group TEXT NOT NULL,
                kind TEXT NOT NULL,
                action TEXT NOT NULL DEFAULT '',
                status_effect TEXT NOT NULL DEFAULT '',
                duration_steps INTEGER NOT NULL DEFAULT 1,
                weight INTEGER NOT NULL DEFAULT 0,
                story_verb TEXT NOT NULL DEFAULT '',
                selection_guidance TEXT NOT NULL DEFAULT '',
                route_json TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_status_room ON sessions(status, room_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_room_id ON agents(room_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_claimed_by_session_id ON agents(claimed_by_session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_session_event_id ON events(session_id, event_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_room_event_id ON events(room_id, event_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_session_client_action_id ON events(session_id, client_action_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_route_catalog_group_weight_route ON route_catalog(route_group, weight, route_id)")

    def _is_seeded(self, conn: sqlite3.Connection) -> bool:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            return False
        if str(row[0]) != str(LIVE_SCHEMA_VERSION):
            return False
        count_row = conn.execute("SELECT COUNT(*) AS count FROM agents").fetchone()
        return int(count_row["count"] if count_row is not None else 0) > 0

    def _seed(self, conn: sqlite3.Connection) -> None:
        now = _now_iso()
        meta = {
            "schema_version": str(LIVE_SCHEMA_VERSION),
            "package_root": str(self.context.package_root),
            "package_db": str(self.context.package_db),
            "access_code": self.access_code,
            "world_id": str(self.context.config.get("scenario_meta", {}).get("world_id", "")),
            "world_name": str(self.context.config.get("scenario_meta", {}).get("world_name", "")),
            "asset_base_url": str(self.context.metadata.get("asset_base_url", "")),
            "world_config_url": str(self.context.metadata.get("world_config_url", "")),
            "map_grid_url": str(self.context.metadata.get("map_grid_url", "")),
            "session_timeout_seconds": str(self.context.session_timeout_seconds),
            "roam_step_seconds": str(self.context.roam_step_seconds),
            "created_at": now,
        }
        conn.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", list(meta.items()))

        for room in self.context.rooms:
            room_id = str(room.get("room_id", "")).strip()
            if not room_id:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO rooms(
                    room_id, room_name, human_count, active_agent_count, active,
                    activation_generation, last_active_at, updated_at, state_json
                ) VALUES(?, ?, 0, 0, 0, 0, '', ?, ?)
                """,
                (
                    room_id,
                    str(room.get("name", room_id)),
                    now,
                    _json_dump(room),
                ),
            )

        for route_group in ("ordinary_routes", "cinematic_routes"):
            for route in self.context.config.get("actions", {}).get(route_group, []) or []:
                if not isinstance(route, dict):
                    continue
                route_id = str(route.get("route_id", "")).strip()
                kind = str(route.get("kind", "")).strip()
                if not route_id or not kind:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO route_catalog(
                        route_id, route_group, kind, action, status_effect,
                        duration_steps, weight, story_verb, selection_guidance,
                        route_json, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        route_id,
                        route_group,
                        kind,
                        str(route.get("action", "")).strip(),
                        str(route.get("status_effect", "")).strip(),
                        max(1, _safe_int(route.get("duration_steps", 1), 1)),
                        max(0, _safe_int(route.get("weight", 0), 0)),
                        str(route.get("story_verb", "")).strip(),
                        str(route.get("selection_guidance", "")).strip(),
                        _json_dump(route),
                        now,
                    ),
                )

        for agent in self.context.agent_seed_payloads:
            agent_id = str(agent.get("agent_id", "")).strip()
            if not agent_id:
                continue
            room_id = str(agent.get("room_id", "")).strip()
            coords = agent.get("coordinates", {})
            state_json = self._ensure_agent_state_defaults(agent_id, dict(agent))
            conn.execute(
                """
                INSERT OR REPLACE INTO agents(
                    agent_id, display_name, room_id, x, y, z,
                    main_character, control_mode, claimed_by_session_id,
                    current_focus, mainline_summary, roam_index,
                    last_updated_at, state_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 'idle', '', ?, ?, 0, ?, ?)
                """,
                (
                    agent_id,
                    str(agent.get("display_name", agent_id)),
                    room_id,
                    _safe_int(coords.get("x", 0)),
                    _safe_int(coords.get("y", 0)),
                    _safe_int(coords.get("z", 0)),
                    1 if bool(agent.get("public_state", {}).get("main_character", False)) else 0,
                    str(agent.get("current_focus", "")),
                    str(agent.get("mainline_summary", "")),
                    now,
                    _json_dump(state_json),
                ),
            )
            self._seed_roaming_plan(conn, agent_id=agent_id, room_id=room_id)

        conn.commit()

    def _seed_roaming_plan(self, conn: sqlite3.Connection, *, agent_id: str, room_id: str) -> None:
        room = self.context.room_lookup.get(room_id)
        if room is None:
            conn.execute(
                "INSERT OR REPLACE INTO roaming_plans(room_id, agent_id, path_json, offset_index, updated_at) VALUES(?, ?, ?, 0, ?)",
                (room_id, agent_id, "[]", _now_iso()),
            )
            return
        path = _room_walk_path(room, agent_id)
        offset = 0
        if path:
            offset = int(hashlib.sha256(f"{agent_id}:{room_id}".encode("utf-8")).hexdigest()[:6], 16) % len(path)
        conn.execute(
            """
            INSERT OR REPLACE INTO roaming_plans(room_id, agent_id, path_json, offset_index, updated_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (room_id, agent_id, _json_dump(path), offset, _now_iso()),
        )

    def _room_state_json(self, row: sqlite3.Row | None, room: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = _json_load(str(row["state_json"]) if row is not None else "", {})
        if not isinstance(payload, dict):
            payload = {}
        if isinstance(room, dict):
            payload = {**payload, **room}
        return payload

