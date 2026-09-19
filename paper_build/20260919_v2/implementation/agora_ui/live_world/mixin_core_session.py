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







class CoreSessionMixin:
    def _set_cached_heartbeat(self, session_id: str, heartbeat_iso: str, *, dirty: bool) -> None:
        normalized = str(session_id or "").strip()
        if not normalized:
            return
        with self._snapshot_cache_lock:
            self._session_heartbeat_cache[normalized] = str(heartbeat_iso or "").strip()
            if dirty:
                self._dirty_heartbeat_sessions.add(normalized)

    def _drop_cached_session(self, session_id: str) -> None:
        normalized = str(session_id or "").strip()
        if not normalized:
            return
        with self._snapshot_cache_lock:
            self._session_heartbeat_cache.pop(normalized, None)
            self._dirty_heartbeat_sessions.discard(normalized)

    def _cached_heartbeat(self, session_id: str, fallback: str = "") -> str:
        normalized = str(session_id or "").strip()
        with self._snapshot_cache_lock:
            return str(self._session_heartbeat_cache.get(normalized, fallback or "") or fallback or "")

    def realtime_session_bootstrap(self, session_id: str) -> dict[str, Any]:
        self.ensure_initialized()
        with self._write_transaction() as conn:
            session = self._session_row(conn, session_id)
            if session is None or str(session["status"]) != "active":
                raise FileNotFoundError(f"session not found: {session_id}")
            agent = self._agent_row(conn, str(session["claimed_agent_id"]))
            if agent is None:
                raise RuntimeError("claimed agent missing from live state")
            hot_state = self._prime_hot_agent_state(
                agent,
                claimed_by_session_id=str(session_id),
                control_mode="human",
            )
            self._prime_realtime_session(
                session_id=session_id,
                agent_id=str(agent["agent_id"]),
                room_id=str(hot_state.get("room_id", agent["room_id"])),
            )
            state = self._build_state_payload(conn, session_id=session_id, since=0)
        self.touch_realtime_session(session_id)
        return {
            "session_id": session_id,
            "claimed_agent_id": str(agent["agent_id"]),
            "tick_interval_ms": LIVE_REALTIME_TICK_MS,
            "flush_interval_ms": int(LIVE_REALTIME_FLUSH_SECONDS * 1000),
            "state": state,
        }

    def flush_hot_spatial_state(self, *, force: bool = False) -> int:
        current_now = _now_ts()
        dirty_agent_ids: set[str] = set()
        dirty_session_ids: set[str] = set()
        with self._realtime_state_lock:
            if (
                not force
                and not self._dirty_hot_agent_ids
                and not self._dirty_hot_session_ids
            ):
                return 0
            if not force and current_now - float(self._last_realtime_flush_at or 0.0) < LIVE_REALTIME_FLUSH_SECONDS:
                return 0
            dirty_agent_ids = set(self._dirty_hot_agent_ids)
            dirty_session_ids = set(self._dirty_hot_session_ids)
            agent_rows = [
                (
                    str(state.get("room_id", "")),
                    _safe_int(state.get("x", 0)),
                    _safe_int(state.get("y", 0)),
                    _safe_int(state.get("z", 0)),
                    str(state.get("control_mode", "human") or "human"),
                    str(state.get("updated_at", _now_iso()) or _now_iso()),
                    agent_id,
                )
                for agent_id, state in self._hot_agent_states.items()
                if agent_id in dirty_agent_ids
            ]
            session_rows = [
                (
                    str(self._hot_session_rooms.get(session_id, "")),
                    self._cached_heartbeat(session_id, _now_iso()),
                    session_id,
                )
                for session_id in dirty_session_ids
                if str(self._hot_session_rooms.get(session_id, "")).strip()
            ]
            self._dirty_hot_agent_ids.clear()
            self._dirty_hot_session_ids.clear()
            self._last_realtime_flush_at = current_now
        if not agent_rows and not session_rows:
            return 0
        try:
            with self._write_transaction() as conn:
                if agent_rows:
                    conn.executemany(
                        """
                        UPDATE agents
                           SET room_id = ?, x = ?, y = ?, z = ?, control_mode = ?, last_updated_at = ?
                         WHERE agent_id = ?
                        """,
                        agent_rows,
                    )
                if session_rows:
                    conn.executemany(
                        "UPDATE sessions SET room_id = ?, last_heartbeat_at = ? WHERE session_id = ? AND status = 'active'",
                        session_rows,
                    )
                    self._update_room_states(conn, current_now)
                self._refresh_hot_world_snapshot(conn, now=current_now)
                self._flush_dirty_heartbeats(conn, force=False)
                conn.commit()
        except Exception:
            with self._realtime_state_lock:
                self._dirty_hot_agent_ids.update(dirty_agent_ids)
                self._dirty_hot_session_ids.update(dirty_session_ids)
            raise
        return len(agent_rows) + len(session_rows)

    def _flush_dirty_heartbeats(self, conn: sqlite3.Connection, *, force: bool = False) -> int:
        now = _now_ts()
        with self._snapshot_cache_lock:
            if not self._dirty_heartbeat_sessions:
                return 0
            if (
                not force
                and len(self._dirty_heartbeat_sessions) < LIVE_HEARTBEAT_FLUSH_BATCH
                and now - float(self._last_heartbeat_flush_at or 0.0) < LIVE_HEARTBEAT_FLUSH_SECONDS
            ):
                return 0
            session_ids = list(self._dirty_heartbeat_sessions)
            heartbeat_values = {session_id: self._session_heartbeat_cache.get(session_id, "") for session_id in session_ids}
            self._dirty_heartbeat_sessions.clear()
            self._last_heartbeat_flush_at = now
        for session_id in session_ids:
            conn.execute(
                "UPDATE sessions SET last_heartbeat_at = ? WHERE session_id = ? AND status = 'active'",
                (heartbeat_values.get(session_id, "") or _now_iso(), session_id),
            )
        return len(session_ids)

    def _reap_expired_sessions(self, conn: sqlite3.Connection, now: float) -> None:
        timeout = self.context.session_timeout_seconds
        rows = conn.execute("SELECT * FROM sessions WHERE status = 'active'").fetchall()
        for row in rows:
            last_heartbeat = self._cached_heartbeat(str(row["session_id"]), str(row["last_heartbeat_at"] or ""))
            last_value = _iso_to_ts(last_heartbeat, now)
            if now - last_value <= timeout:
                continue
            self._release_session_row(conn, row, reason="timeout")

    def _update_room_states(self, conn: sqlite3.Connection, now: float) -> None:
        active_sessions = conn.execute(
            "SELECT room_id, COUNT(*) AS count FROM sessions WHERE status = 'active' GROUP BY room_id"
        ).fetchall()
        room_counts = {str(row["room_id"]): int(row["count"]) for row in active_sessions}
        
        existing_rows = {
            str(row["room_id"]): row 
            for row in conn.execute("SELECT * FROM rooms").fetchall()
        }
        
        agent_counts = {
            str(row["room_id"]): int(row["count"])
            for row in conn.execute("SELECT room_id, COUNT(*) AS count FROM agents GROUP BY room_id").fetchall()
            if row["room_id"]
        }
        
        for room_id, room in self.context.room_lookup.items():
            human_count = room_counts.get(room_id, 0)
            active = 1 if human_count > 0 else 0
            current = existing_rows.get(room_id)
            
            active_agent_count = agent_counts.get(room_id, 0) if active else 0
            
            if current is None:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO rooms(
                        room_id, room_name, human_count, active_agent_count, active,
                        activation_generation, last_active_at, updated_at, state_json
                    ) VALUES(?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        room_id,
                        str(room.get("name", room_id)),
                        human_count,
                        active_agent_count,
                        active,
                        _now_iso() if active else "",
                        _now_iso(),
                        _json_dump(room),
                    ),
                )
                continue
                
            prev_active = int(current["active"])
            prev_human_count = int(current["human_count"])
            prev_active_agent_count = int(current["active_agent_count"])
            
            activation_generation = int(current["activation_generation"])
            if active != prev_active:
                activation_generation += 1
                
            last_active_at = str(current["last_active_at"])
            if active and not last_active_at:
                last_active_at = _now_iso()
                
            room_state = self._room_state_json(current, room)
            state_json_str = _json_dump(room_state)
            
            if (
                human_count != prev_human_count or
                active_agent_count != prev_active_agent_count or
                active != prev_active or
                activation_generation != int(current["activation_generation"]) or
                last_active_at != str(current["last_active_at"]) or
                state_json_str != str(current["state_json"])
            ):
                conn.execute(
                    """
                    UPDATE rooms
                       SET human_count = ?,
                           active_agent_count = ?,
                           active = ?,
                           activation_generation = ?,
                           last_active_at = ?,
                           updated_at = ?,
                           state_json = ?
                     WHERE room_id = ?
                    """,
                    (
                        human_count,
                        active_agent_count,
                        active,
                        activation_generation,
                        last_active_at,
                        _now_iso(),
                        state_json_str,
                        room_id,
                    ),
                )

    def _session_row(self, conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()

    def _advance_active_rooms(self, conn: sqlite3.Connection, now: float, *, preferred_session_id: str = "") -> None:
        active_room_ids = {
            str(row["room_id"]).strip()
            for row in conn.execute("SELECT room_id FROM rooms WHERE active = 1 ORDER BY room_id").fetchall()
            if str(row["room_id"]).strip()
        }
        active_room_ids.update(self._task_room_ids(conn))
        for room_id in sorted(active_room_ids):
            room_row = conn.execute("SELECT * FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
            if room_row is None:
                continue
            room = self.context.room_lookup.get(room_id, {})
            room_state = self._room_state_json(room_row, room)
            last_tick_at = _iso_to_ts(room_state.get("last_live_tick_at", ""), 0.0)
            if now - last_tick_at >= self.context.roam_step_seconds:
                self._advance_room_agents(conn, room_id=room_id, room=room)
                room_state["last_live_tick_at"] = _now_iso()
                room_state["live_tick_counter"] = _safe_int(room_state.get("live_tick_counter", 0), 0) + 1
            chatter_interval = max(15.0, self.context.roam_step_seconds * 4.0)
            last_chatter_at = _iso_to_ts(room_state.get("last_room_chatter_at", ""), 0.0)
            if now - last_chatter_at >= chatter_interval:
                if self._emit_room_chatter(conn, room_id=room_id, room=room, preferred_session_id=preferred_session_id):
                    room_state["last_room_chatter_at"] = _now_iso()
            conn.execute(
                "UPDATE rooms SET updated_at = ?, state_json = ? WHERE room_id = ?",
                (_now_iso(), _json_dump(room_state), room_id),
            )

    def _closest_room_goal(self, row: sqlite3.Row, target_room_id: str) -> dict[str, int] | None:
        room = self.context.room_lookup.get(target_room_id)
        if room is None:
            return None
        current = self._agent_coordinates(row)
        candidates = [_coord_payload(tile) for tile in _room_tiles(room)]
        if not candidates:
            return None
        best_path: list[dict[str, int]] = []
        for candidate in candidates:
            path = self._walkable_path(start=current, goal=candidate, blocked_keys=set())
            if not path:
                continue
            if not best_path or len(path) < len(best_path):
                best_path = path
        if best_path:
            return best_path[-1]
        return min(candidates, key=lambda tile: _coord_distance(current, tile))

    def _emit_room_chatter(self, conn: sqlite3.Connection, *, room_id: str, room: dict[str, Any], preferred_session_id: str = "") -> bool:
        room_name = str(room.get("name", room_id))
        rows = conn.execute(
            "SELECT * FROM agents WHERE room_id = ? ORDER BY claimed_by_session_id DESC, agent_id",
            (room_id,),
        ).fetchall()
        if len(rows) < 2:
            return False
        preferred_session = self._session_row(conn, preferred_session_id) if preferred_session_id else None
        speaker = next((row for row in rows if not str(row["claimed_by_session_id"]).strip()), rows[0])
        listener = None
        if preferred_session is not None and str(preferred_session["room_id"]) == room_id:
            listener = self._agent_row(conn, str(preferred_session["claimed_agent_id"]))
        if listener is None or str(listener["agent_id"]) == str(speaker["agent_id"]):
            listener = next((row for row in rows if str(row["agent_id"]) != str(speaker["agent_id"])), None)
        if listener is None:
            return False
        decor_tags = [str(tag).strip() for tag in room.get("visual", {}).get("decor_tags", []) if str(tag).strip()]
        decor_copy = decor_tags[0].replace("_", " ") if decor_tags else "the room"
        response = f"{str(speaker['display_name'])} checks {decor_copy} with {str(listener['display_name'])} in {room_name}."
        speaker_state = self._ensure_agent_state_defaults(str(speaker["agent_id"]), _json_load(str(speaker["state_json"]), {}))
        listener_state = self._ensure_agent_state_defaults(str(listener["agent_id"]), _json_load(str(listener["state_json"]), {}))
        self._save_agent_state(conn, agent_row=speaker, state=speaker_state, current_focus=response, mainline_summary=response)
        self._save_agent_state(conn, agent_row=listener, state=listener_state, current_focus=response, mainline_summary=response)
        session_row = preferred_session if preferred_session is not None and str(preferred_session["room_id"]) == room_id else conn.execute(
            "SELECT * FROM sessions WHERE room_id = ? AND status = 'active' ORDER BY created_at LIMIT 1",
            (room_id,),
        ).fetchone()
        session_id = str(session_row["session_id"]) if session_row is not None else preferred_session_id
        self._response_event(
            conn,
            session_id=session_id,
            room_id=room_id,
            actor_agent_id=str(speaker["agent_id"]),
            target_agent_id=str(listener["agent_id"]),
            action_text=response,
            response_text=response,
            payload={"room_id": room_id, "room_name": room_name, "kind": "room_chatter"},
        )
        return True

    def _session_payload(self, conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
        row = self._session_row(conn, session_id)
        if row is None:
            return None
        with self._realtime_state_lock:
            hot_room_id = str(self._hot_session_rooms.get(str(session_id), "")).strip()
        return {
            "session_id": str(row["session_id"]),
            "display_name": str(row["display_name"]),
            "access_code": str(row["access_code"]),
            "claimed_agent_id": str(row["claimed_agent_id"]),
            "room_id": hot_room_id or str(row["room_id"]),
            "status": str(row["status"]),
            "speed_seconds_per_round": float(row["speed_seconds_per_round"]),
            "heartbeat_seconds": float(row["heartbeat_seconds"]),
            "created_at": str(row["created_at"]),
            "last_heartbeat_at": self._cached_heartbeat(session_id, str(row["last_heartbeat_at"] or "")),
            "last_state_index": int(row["last_state_index"]),
        }

    def state_payload(
        self,
        session_id: str,
        *,
        since: int = 0,
        compact: bool = False,
        if_world_revision: int = 0,
    ) -> dict[str, Any]:
        self.ensure_initialized()
        with self._write_transaction() as conn:
            return self._build_state_payload(
                conn,
                session_id=session_id,
                since=since,
                compact=compact,
                if_world_revision=if_world_revision,
            )

    def create_session(
        self,
        *,
        display_name: str = "Human Interactor",
        room_id: str = "",
        speed_seconds_per_round: float = 8.0,
    ) -> dict[str, Any]:
        self.ensure_initialized()
        with self._write_transaction() as conn:
            now = _now_iso()
            now_ts = _now_ts()
            self._reap_expired_sessions(conn, now_ts)
            self._update_room_states(conn, now_ts)
            preferred_room = str(room_id).strip()
            candidates = self._available_agents(conn, preferred_room=preferred_room)
            if not candidates:
                raise RuntimeError("world full: no unclaimed agent is available")
            chosen = candidates[secrets.randbelow(len(candidates))]
            session_id = secrets.token_hex(8)
            heartbeat_seconds = max(DEFAULT_HEARTBEAT_SECONDS, _safe_float(speed_seconds_per_round, 8.0))
            conn.execute(
                """
                INSERT INTO sessions(
                    session_id, display_name, access_code, claimed_agent_id, room_id,
                    status, speed_seconds_per_round, heartbeat_seconds,
                    created_at, last_heartbeat_at, last_state_index
                ) VALUES(?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, 0)
                """,
                (
                    session_id,
                    str(display_name).strip() or str(chosen["display_name"]),
                    self.access_code,
                    str(chosen["agent_id"]),
                    str(chosen["room_id"]),
                    float(speed_seconds_per_round),
                    heartbeat_seconds,
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE agents SET claimed_by_session_id = ?, control_mode = 'human', last_updated_at = ? WHERE agent_id = ?",
                (session_id, now, str(chosen["agent_id"])),
            )
            chosen_agent_row = self._agent_row(conn, str(chosen["agent_id"]))
            if chosen_agent_row is None:
                raise RuntimeError("claimed agent missing immediately after session assignment")
            self._update_room_states(conn, now_ts)
            self._set_cached_heartbeat(session_id, now, dirty=False)
            self._prime_hot_agent_state(
                chosen_agent_row,
                claimed_by_session_id=session_id,
                control_mode="human",
            )
            self._prime_realtime_session(
                session_id=session_id,
                agent_id=str(chosen["agent_id"]),
                room_id=str(chosen["room_id"]),
            )
            self._touch_world_revision()
            self._refresh_hot_world_snapshot(conn, now=now_ts)
            conn.commit()
            payload = self._build_state_payload(conn, session_id=session_id, since=0)
            conn.execute("UPDATE sessions SET last_state_index = ? WHERE session_id = ?", (int(payload["latest_event_id"]), session_id))
            conn.commit()
            return payload

    def heartbeat(self, session_id: str) -> dict[str, Any]:
        self.ensure_initialized()
        refreshed: dict[str, Any] | None = None
        with self._write_transaction() as conn:
            session = self._session_row(conn, session_id)
            if session is None or str(session["status"]) != "active":
                raise FileNotFoundError(f"session not found: {session_id}")
            refreshed = self._session_payload(conn, session_id)
        heartbeat_iso = _now_iso()
        self._set_cached_heartbeat(session_id, heartbeat_iso, dirty=True)
        if isinstance(refreshed, dict):
            refreshed["last_heartbeat_at"] = heartbeat_iso
        return {
            "status": "ok",
            "session": refreshed or {},
            "updated_at": heartbeat_iso,
        }

    def release_session(self, session_id: str) -> dict[str, Any]:
        self.ensure_initialized()
        with self._write_transaction() as conn:
            session = self._session_row(conn, session_id)
            if session is None:
                raise FileNotFoundError(f"session not found: {session_id}")
            self._release_session_row(conn, session, reason="released")
            self._update_room_states(conn, _now_ts())
            self._touch_world_revision()
            self._refresh_hot_world_snapshot(conn)
            conn.commit()
            return {"status": "ok", "session_id": session_id}

    def _release_session_row(self, conn: sqlite3.Connection, session: sqlite3.Row, *, reason: str) -> None:
        session_id = str(session["session_id"])
        agent_id = str(session["claimed_agent_id"])
        self._drop_cached_session(session_id)
        self._drop_realtime_session(session_id=session_id, agent_id=agent_id)
        conn.execute(
            "UPDATE sessions SET status = ?, last_heartbeat_at = ?, room_id = room_id WHERE session_id = ?",
            (f"released:{reason}", _now_iso(), session_id),
        )
        agent_row = self._agent_row(conn, agent_id)
        if agent_row is not None and str(agent_row["claimed_by_session_id"]) == session_id:
            conn.execute(
                "UPDATE agents SET claimed_by_session_id = '', control_mode = 'idle', last_updated_at = ? WHERE agent_id = ?",
                (_now_iso(), agent_id),
            )
        conn.execute("UPDATE rooms SET updated_at = ? WHERE room_id = ?", (_now_iso(), str(session["room_id"])))

