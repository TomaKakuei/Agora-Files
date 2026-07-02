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







class RealtimeMixin:
    def _prime_realtime_session(self, *, session_id: str, agent_id: str, room_id: str) -> None:
        normalized_session_id = str(session_id or "").strip()
        normalized_agent_id = str(agent_id or "").strip()
        normalized_room_id = str(room_id or "").strip()
        if not normalized_session_id or not normalized_agent_id:
            return
        with self._realtime_state_lock:
            self._hot_session_agents[normalized_session_id] = normalized_agent_id
            self._hot_session_rooms[normalized_session_id] = normalized_room_id
            self._realtime_input_queues.setdefault(normalized_session_id, deque())

    def _drop_realtime_session(self, *, session_id: str, agent_id: str = "") -> None:
        normalized_session_id = str(session_id or "").strip()
        normalized_agent_id = str(agent_id or "").strip()
        if not normalized_session_id:
            return
        with self._realtime_state_lock:
            self._hot_session_agents.pop(normalized_session_id, None)
            self._hot_session_rooms.pop(normalized_session_id, None)
            self._dirty_hot_session_ids.discard(normalized_session_id)
            self._realtime_input_queues.pop(normalized_session_id, None)
            if normalized_agent_id:
                state = self._hot_agent_states.get(normalized_agent_id)
                if state is not None:
                    state["claimed_by_session_id"] = ""
                    state["control_mode"] = "idle"
                    state["animation"] = f"idle_{str(state.get('facing', 'down') or 'down')}"
                    state["updated_at"] = _now_iso()
                    self._dirty_hot_agent_ids.add(normalized_agent_id)

    def touch_realtime_session(self, session_id: str) -> None:
        heartbeat_iso = _now_iso()
        self._set_cached_heartbeat(session_id, heartbeat_iso, dirty=True)

    def enqueue_realtime_input(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise FileNotFoundError("session_id is required")
        direction = str(payload.get("direction", payload.get("action_type", ""))).strip().lower()
        if direction.startswith("move_"):
            direction = direction.replace("move_", "", 1)
        if direction not in {"up", "down", "left", "right"}:
            raise ValueError(f"unsupported realtime input direction: {direction}")
        input_seq = max(0, _safe_int(payload.get("input_seq", payload.get("sequence", 0)), 0))
        client_time_ms = max(0, _safe_int(payload.get("client_time_ms", payload.get("sent_at_ms", 0)), 0))
        with self._realtime_state_lock:
            agent_id = str(self._hot_session_agents.get(normalized_session_id, "")).strip()
            if not agent_id:
                raise FileNotFoundError(f"session not ready for realtime input: {normalized_session_id}")
            input_queue = self._realtime_input_queues.setdefault(normalized_session_id, deque())
            input_queue.append(
                {
                    "direction": direction,
                    "input_seq": input_seq,
                    "client_time_ms": client_time_ms,
                    "queued_at_ms": int(round(time.time() * 1000.0)),
                }
            )
            while len(input_queue) > LIVE_REALTIME_MAX_BUFFERED_INPUTS:
                input_queue.popleft()
            queue_depth = len(input_queue)
        self.touch_realtime_session(normalized_session_id)
        return {
            "status": "queued",
            "session_id": normalized_session_id,
            "agent_id": agent_id,
            "input_seq": input_seq,
            "queue_depth": queue_depth,
        }

    def process_realtime_tick(self, *, now: float | None = None) -> dict[str, Any] | None:
        current_now = float(now if now is not None else _now_ts())
        changed_by_agent: dict[str, dict[str, Any]] = {}
        with self._realtime_state_lock:
            session_pairs = list(self._hot_session_agents.items())
            for session_id, agent_id in session_pairs:
                agent_state = self._hot_agent_states.get(agent_id)
                if agent_state is None:
                    continue
                input_queue = self._realtime_input_queues.get(session_id)
                if not input_queue:
                    continue
                processed = 0
                while input_queue and processed < LIVE_REALTIME_MAX_INPUTS_PER_TICK:
                    queued = dict(input_queue.popleft())
                    direction = str(queued.get("direction", "")).strip().lower()
                    vectors = {
                        "up": (0, -1),
                        "down": (0, 1),
                        "left": (-1, 0),
                        "right": (1, 0),
                    }
                    dx, dy = vectors.get(direction, (0, 0))
                    current_position = {
                        "x": _safe_int(agent_state.get("x", 0)),
                        "y": _safe_int(agent_state.get("y", 0)),
                        "z": _safe_int(agent_state.get("z", 0)),
                    }
                    if _disable_world_geometry_collision(self.context.config):
                        next_destination = _resolve_unblocked_destination(
                            rooms=self.context.room_lookup,
                            room_tile_index=self.context.room_tile_index,
                            current_room_id=str(agent_state.get("room_id", "")),
                            current_position=current_position,
                            direction=direction,
                        )
                    else:
                        next_destination = _resolve_wall_hop_destination(
                            rooms=self.context.room_lookup,
                            room_tile_index=self.context.room_tile_index,
                            outer_wall_tile_index=self.context.outer_wall_tile_index,
                            inner_wall_tile_index=self.context.inner_wall_tile_index,
                            current_room_id=str(agent_state.get("room_id", "")),
                            current_position=current_position,
                            direction=direction,
                        )
                    now_iso = _now_iso()
                    input_seq = max(0, _safe_int(queued.get("input_seq", 0), 0))
                    agent_state["facing"] = direction or str(agent_state.get("facing", "down") or "down")
                    agent_state["last_input_seq"] = input_seq
                    agent_state["updated_at"] = now_iso
                    if next_destination:
                        next_room_id, next_position = next_destination
                        agent_state["room_id"] = next_room_id
                        agent_state["x"] = next_position["x"]
                        agent_state["y"] = next_position["y"]
                        agent_state["z"] = next_position["z"]
                        agent_state["animation"] = f"walk_{direction}"
                        agent_state["control_mode"] = "human"
                        agent_state["claimed_by_session_id"] = session_id
                        self._dirty_hot_agent_ids.add(agent_id)
                        if str(self._hot_session_rooms.get(session_id, "")) != next_room_id:
                            self._hot_session_rooms[session_id] = next_room_id
                            self._dirty_hot_session_ids.add(session_id)
                        changed_by_agent[agent_id] = self._realtime_move_delta(
                            state=agent_state,
                            session_id=session_id,
                            input_seq=input_seq,
                            direction=direction,
                            accepted=True,
                            now_iso=now_iso,
                        )
                    else:
                        agent_state["animation"] = f"idle_{direction}"
                        changed_by_agent[agent_id] = self._realtime_move_delta(
                            state=agent_state,
                            session_id=session_id,
                            input_seq=input_seq,
                            direction=direction,
                            accepted=False,
                            now_iso=now_iso,
                        )
                    processed += 1
        if not changed_by_agent:
            return None
        with self._realtime_state_lock:
            self._realtime_tick_index += 1
            tick_index = int(self._realtime_tick_index)
        world_revision = self._touch_world_revision()
        return {
            "type": "state_delta",
            "access_code": self.access_code,
            "tick": tick_index,
            "world_revision": world_revision,
            "server_time_ms": int(round(current_now * 1000.0)),
            "agents": list(changed_by_agent.values()),
        }

    def _queue_ws_completion_broadcast(self, session_id: str, client_action_id: str) -> None:
        if not session_id:
            return
        try:
            with self._write_transaction() as conn:
                session_row = conn.execute("SELECT status FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
                if session_row and str(session_row["status"]) == "active":
                    state = self._build_state_payload(conn, session_id=session_id)
                    broadcast_payload = {
                        "type": "action_result",
                        "access_code": self.access_code,
                        "session_id": session_id,
                        "client_action_id": client_action_id,
                        "state": state,
                    }
                    self._pending_broadcasts.put(broadcast_payload)
        except Exception as exc:
            print(f"[COORDINATOR_BROADCAST_PREP_ERROR] {exc}")



