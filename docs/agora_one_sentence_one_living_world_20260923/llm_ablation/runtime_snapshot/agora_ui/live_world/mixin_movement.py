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







class MovementMixin:
    def _route_row_payload(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        raw = dict(row)
        payload = _json_load(str(raw.get("route_json", "")), {})
        if not isinstance(payload, dict):
            payload = {}
        return {
            **payload,
            "route_id": str(raw.get("route_id", payload.get("route_id", ""))).strip(),
            "route_group": str(raw.get("route_group", payload.get("route_group", ""))).strip(),
            "kind": str(raw.get("kind", payload.get("kind", ""))).strip(),
            "action": str(raw.get("action", payload.get("action", ""))).strip(),
            "status_effect": str(raw.get("status_effect", payload.get("status_effect", ""))).strip(),
            "duration_steps": max(1, _safe_int(raw.get("duration_steps", payload.get("duration_steps", 1)), 1)),
            "weight": max(0, _safe_int(raw.get("weight", payload.get("weight", 0)), 0)),
            "story_verb": str(raw.get("story_verb", payload.get("story_verb", ""))).strip(),
            "selection_guidance": str(raw.get("selection_guidance", payload.get("selection_guidance", ""))).strip(),
        }

    def _live_route_lookup(self, conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        if self._cached_live_route_lookup is not None:
            return self._clone_payload(self._cached_live_route_lookup)
        rows = conn.execute("SELECT * FROM route_catalog ORDER BY route_group, route_id").fetchall()
        lookup = {
            str(row["route_id"]).strip(): self._route_row_payload(row)
            for row in rows
            if str(row["route_id"]).strip()
        }
        self._cached_live_route_lookup = lookup
        return self._clone_payload(lookup)

    def _live_executable_routes(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        if self._cached_live_executable_routes is not None:
            return self._clone_payload(self._cached_live_executable_routes)
        supported_kinds = {"custom", "item_trade", "move"}
        rows = conn.execute(
            "SELECT * FROM route_catalog WHERE route_group = 'ordinary_routes' ORDER BY weight DESC, route_id"
        ).fetchall()
        routes: list[dict[str, Any]] = []
        for row in rows:
            payload = self._route_row_payload(row)
            if str(payload.get("kind", "")).strip() in supported_kinds:
                routes.append(payload)
        self._cached_live_executable_routes = list(routes)
        return self._clone_payload(routes)

    def _first_live_move_route(self, conn: sqlite3.Connection) -> dict[str, Any] | None:
        for route in self._live_executable_routes(conn):
            if str(route.get("kind", "")).strip() == "move":
                return dict(route)
        return None

    def _normalize_recent_live_routes(self, value: Any) -> list[dict[str, Any]]:
        entries = value if isinstance(value, list) else []
        normalized: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            route_id = str(entry.get("route_id", "")).strip()
            kind = str(entry.get("kind", "")).strip()
            if not route_id or not kind:
                continue
            normalized.append(
                {
                    "route_id": route_id,
                    "kind": kind,
                    "action": str(entry.get("action", "")).strip(),
                    "status_effect": str(entry.get("status_effect", "")).strip(),
                    "target_agent_id": str(entry.get("target_agent_id", "")).strip(),
                    "item_id": str(entry.get("item_id", "")).strip(),
                    "quantity": max(1, _safe_int(entry.get("quantity", 1), 1)),
                    "target_room_id": str(entry.get("target_room_id", "")).strip(),
                    "created_at": str(entry.get("created_at", "")).strip(),
                    "note": _trim_text(entry.get("note", ""), 240),
                }
            )
        normalized.sort(key=lambda item: (item.get("created_at", ""), item.get("route_id", "")), reverse=True)
        return normalized[:12]

    def _append_recent_live_route(
        self,
        state: dict[str, Any],
        *,
        route: dict[str, Any],
        target_agent_id: str,
        item_id: str = "",
        quantity: int = 1,
        target_room_id: str = "",
        note: str = "",
    ) -> None:
        current = self._normalize_recent_live_routes(state.get("recent_live_routes", []))
        current.insert(
            0,
            {
                "route_id": str(route.get("route_id", "")).strip(),
                "kind": str(route.get("kind", "")).strip(),
                "action": str(route.get("action", "")).strip(),
                "status_effect": str(route.get("status_effect", "")).strip(),
                "target_agent_id": str(target_agent_id).strip(),
                "item_id": str(item_id).strip(),
                "quantity": max(1, _safe_int(quantity, 1)),
                "target_room_id": str(target_room_id).strip(),
                "created_at": _now_iso(),
                "note": _trim_text(note, 240),
            },
        )
        state["recent_live_routes"] = self._normalize_recent_live_routes(current)

    def _normalize_route_selection(self, conn: sqlite3.Connection, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        route_id = str(value.get("route_id", "")).strip()
        kind = str(value.get("kind", "")).strip()
        if route_id in {"", "none", "noop"} or kind in {"", "none", "noop"}:
            return None
        route = self._live_route_lookup(conn).get(route_id)
        if route is None:
            return None
        route_kind = str(route.get("kind", "")).strip()
        if kind != route_kind:
            kind = route_kind
        if kind not in {"custom", "item_trade", "move"}:
            return None
        return {
            "route_id": route_id,
            "kind": kind,
            "reason": _trim_text(value.get("reason", ""), 240),
            "item_id": str(value.get("item_id", "")).strip(),
            "quantity": max(1, _safe_int(value.get("quantity", 1), 1)),
            "target_room_id": str(value.get("target_room_id", "")).strip(),
        }

    def _occupied_tile_keys(self, conn: sqlite3.Connection, *, exclude_agent_id: str = "") -> set[str]:
        rows = conn.execute("SELECT agent_id, x, y, z FROM agents").fetchall()
        return {
            _room_tile_key(_safe_int(row["x"]), _safe_int(row["y"]), _safe_int(row["z"]))
            for row in rows
            if not exclude_agent_id or str(row["agent_id"]) != exclude_agent_id
        }

    def _walkable_path(
        self,
        *,
        start: dict[str, int],
        goal: dict[str, int],
        blocked_keys: set[str] | None = None,
    ) -> list[dict[str, int]]:
        start_key = _room_tile_key(start["x"], start["y"], start["z"])
        goal_key = _room_tile_key(goal["x"], goal["y"], goal["z"])
        walkable = set(self.context.room_tile_index.keys())
        if start_key not in walkable or goal_key not in walkable:
            return []
        blocked = set(blocked_keys or set())
        blocked.discard(start_key)
        blocked.discard(goal_key)
        diagonals = bool(self.context.config.get("space", {}).get("movement", {}).get("allow_diagonal", False))
        deltas = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]
        if diagonals:
            deltas.extend([(1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0)])
        frontier = [start_key]
        parents: dict[str, str | None] = {start_key: None}
        found = None
        while frontier:
            current_key = frontier.pop(0)
            if current_key == goal_key:
                found = current_key
                break
            cx, cy, cz = (_safe_int(part, 0) for part in current_key.split(","))
            for dx, dy, dz in deltas:
                neighbor = (cx + dx, cy + dy, cz + dz)
                neighbor_key = _room_tile_key(*neighbor)
                if neighbor_key in parents or neighbor_key not in walkable or neighbor_key in blocked:
                    continue
                parents[neighbor_key] = current_key
                frontier.append(neighbor_key)
        if found is None:
            return []
        keys: list[str] = []
        cursor = found
        while cursor is not None:
            keys.append(cursor)
            cursor = parents.get(cursor)
        keys.reverse()
        path: list[dict[str, int]] = []
        for key in keys:
            x_str, y_str, z_str = key.split(",")
            path.append({"x": _safe_int(x_str), "y": _safe_int(y_str), "z": _safe_int(z_str)})
        return path

    def _move_agent_to_position(
        self,
        conn: sqlite3.Connection,
        *,
        agent_row: sqlite3.Row,
        next_position: dict[str, int],
        control_mode: str,
    ) -> bool:
        current_room_id = str(agent_row["room_id"])
        current_position = self._agent_coordinates(agent_row)
        next_room_id = _resolve_room_transition(
            rooms=self.context.room_lookup,
            room_tile_index=self.context.room_tile_index,
            current_room_id=current_room_id,
            current_position=current_position,
            next_position=next_position,
        )
        if not next_room_id:
            return False
        conn.execute(
            """
            UPDATE agents
               SET room_id = ?, x = ?, y = ?, z = ?, control_mode = ?, last_updated_at = ?
             WHERE agent_id = ?
            """,
            (
                next_room_id,
                _safe_int(next_position.get("x", 0)),
                _safe_int(next_position.get("y", 0)),
                _safe_int(next_position.get("z", 0)),
                control_mode,
                _now_iso(),
                str(agent_row["agent_id"]),
            ),
        )
        claimed_session_id = str(agent_row["claimed_by_session_id"] or "").strip()
        if claimed_session_id:
            conn.execute(
                "UPDATE sessions SET room_id = ?, last_state_index = last_state_index WHERE session_id = ?",
                (next_room_id, claimed_session_id),
            )
        return True

    @property
    def live_db_path(self) -> Path:
        return self.context.live_db_path

    def _realtime_move_delta(
        self,
        *,
        state: dict[str, Any],
        session_id: str,
        input_seq: int,
        direction: str,
        accepted: bool,
        now_iso: str,
    ) -> dict[str, Any]:
        return {
            "agent_id": str(state.get("agent_id", "")),
            "room_id": str(state.get("room_id", "")),
            "coordinates": {
                "x": _safe_int(state.get("x", 0)),
                "y": _safe_int(state.get("y", 0)),
                "z": _safe_int(state.get("z", 0)),
            },
            "facing": str(state.get("facing", direction or "down")),
            "animation": str(state.get("animation", f"idle_{direction or 'down'}")),
            "control_mode": str(state.get("control_mode", "human")),
            "claimed_by_session_id": str(state.get("claimed_by_session_id", session_id)),
            "last_input_seq": max(0, int(input_seq)),
            "accepted": bool(accepted),
            "updated_at": now_iso,
        }

    def _default_route_move_room_id(self, actor_room_id: str, target_room_id: str = "") -> str:
        preferred = str(target_room_id).strip()
        if preferred and preferred in self.context.room_lookup:
            return preferred
        room = self.context.room_lookup.get(actor_room_id, {})
        for doorway in room.get("doorways", []) if isinstance(room.get("doorways", []), list) else []:
            if not isinstance(doorway, dict):
                continue
            candidate = str(doorway.get("target_room_id") or doorway.get("connects_to_room_id") or "").strip()
            if candidate and candidate in self.context.room_lookup and candidate != actor_room_id:
                return candidate
        return ""

    def _apply_live_route_selection(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        actor: sqlite3.Row,
        target: sqlite3.Row,
        room_id: str,
        route_selection: dict[str, Any],
        base_response_text: str,
    ) -> dict[str, Any] | None:
        normalized = self._normalize_route_selection(conn, route_selection)
        if normalized is None:
            return None
        actor = self._agent_row(conn, str(actor["agent_id"])) or actor
        target = self._agent_row(conn, str(target["agent_id"])) or target
        route = self._live_route_lookup(conn).get(str(normalized.get("route_id", "")), {})
        if not route:
            return None
        route_id = str(route.get("route_id", ""))
        kind = str(route.get("kind", ""))
        actor_state = self._ensure_agent_state_defaults(str(actor["agent_id"]), _json_load(str(actor["state_json"]), {}))
        target_state = self._ensure_agent_state_defaults(str(target["agent_id"]), _json_load(str(target["state_json"]), {}))
        selection_reason = normalized.get("reason", "") or f"live_route:{route_id}"
        if kind == "move":
            destination_room_id = str(normalized.get("target_room_id", "")).strip() or self._default_route_move_room_id(str(target["room_id"]))
            if not destination_room_id or destination_room_id not in self.context.room_lookup:
                return None
            room_name = str(self.context.room_lookup.get(destination_room_id, {}).get("name", destination_room_id))
            response = f"{str(target['display_name'])} heads toward {room_name}."
            self._set_active_task(
                target_state,
                {
                    "task_id": f"task_{secrets.token_hex(6)}",
                    "kind": "move_to_room",
                    "status": "active",
                    "requested_by_agent_id": str(actor["agent_id"]),
                    "target_agent_id": "",
                    "target_room_id": destination_room_id,
                    "target_coordinates": self._agent_coordinates(target),
                    "follow_radius": 1,
                    "offer_id": "",
                    "item_id": "",
                    "quantity": 1,
                    "created_at": _now_iso(),
                    "completed_at": "",
                    "note": selection_reason,
                },
            )
            self._append_recent_live_route(
                actor_state,
                route=route,
                target_agent_id=str(target["agent_id"]),
                target_room_id=destination_room_id,
                note=selection_reason,
            )
            self._append_recent_live_route(
                target_state,
                route=route,
                target_agent_id=str(actor["agent_id"]),
                target_room_id=destination_room_id,
                note=selection_reason,
            )
            self._save_agent_state(conn, agent_row=actor, state=actor_state, current_focus=str(actor["current_focus"]), mainline_summary=base_response_text)
            self._save_agent_state(conn, agent_row=target, state=target_state, current_focus=response, mainline_summary=base_response_text)
            self._response_event(
                conn,
                session_id=session_id,
                room_id=room_id,
                actor_agent_id=str(target["agent_id"]),
                target_agent_id=str(actor["agent_id"]),
                action_text=response,
                response_text=response,
                payload={"kind": "route_execution", "route_id": route_id, "status": "task_started", "target_room_id": destination_room_id},
            )
            return {"route_id": route_id, "kind": kind, "status": "task_started", "target_room_id": destination_room_id, "response_text": response}
        if kind == "item_trade":
            item_id = str(normalized.get("item_id", "")).strip()
            quantity = max(1, _safe_int(normalized.get("quantity", 1), 1))
            if not item_id:
                item_id, available_quantity = self._default_trade_route_item(target_state)
                if not item_id:
                    return None
                quantity = min(quantity, max(1, available_quantity))
            if not self._should_direct_settle_priced_trade(target_state, item_id):
                return None
            offer = self._issue_trade_quote(
                conn,
                buyer=actor,
                seller=target,
                buyer_state=actor_state,
                seller_state=target_state,
                item_id=item_id,
                quantity=quantity,
                note=f"route_selection:{route_id}",
                base_response_text=base_response_text,
            )
            if offer is None:
                return None
            self._append_recent_live_route(
                actor_state,
                route=route,
                target_agent_id=str(target["agent_id"]),
                item_id=item_id,
                quantity=quantity,
                note=selection_reason,
            )
            self._append_recent_live_route(
                target_state,
                route=route,
                target_agent_id=str(actor["agent_id"]),
                item_id=item_id,
                quantity=quantity,
                note=selection_reason,
            )
            self._save_agent_state(conn, agent_row=actor, state=actor_state, current_focus=str(actor["current_focus"]), mainline_summary=base_response_text)
            self._save_agent_state(conn, agent_row=target, state=target_state, current_focus=str(target_state.get("current_focus", "")), mainline_summary=base_response_text)
            success, response = self._execute_trade_offer(
                conn,
                buyer_row=actor,
                seller_row=target,
                offer_id=str(offer.get("offer_id", "")),
                session_id=session_id,
            )
            if not success:
                return {
                    "route_id": route_id,
                    "kind": kind,
                    "status": "failed_direct_purchase",
                    "offer_id": str(offer.get("offer_id", "")),
                    "response_text": response,
                }
            self._response_event(
                conn,
                session_id=session_id,
                room_id=room_id,
                actor_agent_id=str(target["agent_id"]),
                target_agent_id=str(actor["agent_id"]),
                action_text=response,
                response_text=response,
                payload={"kind": "route_execution", "route_id": route_id, "status": "completed_direct_purchase", "offer_id": str(offer.get("offer_id", ""))},
            )
            return {"route_id": route_id, "kind": kind, "status": "completed_direct_purchase", "offer_id": str(offer.get("offer_id", "")), "response_text": response}
        if kind == "custom":
            action_name = str(route.get("action", "")).strip()
            story_verb = str(route.get("story_verb", "")).strip() or "acts with"
            response = f"{str(target['display_name'])} {story_verb} {str(actor['display_name'])}."
            self._append_recent_live_route(
                actor_state,
                route=route,
                target_agent_id=str(target["agent_id"]),
                note=selection_reason,
            )
            self._append_recent_live_route(
                target_state,
                route=route,
                target_agent_id=str(actor["agent_id"]),
                note=selection_reason,
            )
            self._save_agent_state(conn, agent_row=actor, state=actor_state, current_focus=str(actor["current_focus"]), mainline_summary=base_response_text)
            self._save_agent_state(
                conn,
                agent_row=target,
                state=target_state,
                current_focus=f"{str(target['display_name'])} is focused on {action_name or route_id}.",
                mainline_summary=base_response_text,
            )
            self._response_event(
                conn,
                session_id=session_id,
                room_id=room_id,
                actor_agent_id=str(target["agent_id"]),
                target_agent_id=str(actor["agent_id"]),
                action_text=response,
                response_text=response,
                payload={"kind": "route_execution", "route_id": route_id, "status": "recorded", "action": action_name},
            )
            return {"route_id": route_id, "kind": kind, "status": "recorded", "action": action_name, "response_text": response}
        return None

    def _apply_move(self, conn: sqlite3.Connection, *, session_id: str, agent_id: str, direction: str, event_id: int) -> None:
        direction = direction.lower()
        vectors = {
            "up": (0, -1),
            "down": (0, 1),
            "left": (-1, 0),
            "right": (1, 0),
            "move_up": (0, -1),
            "move_down": (0, 1),
            "move_left": (-1, 0),
            "move_right": (1, 0),
        }
        if direction not in vectors:
            conn.execute(
                "UPDATE events SET processed = 1, processed_at = ?, response_text = ? WHERE event_id = ?",
                (_now_iso(), "Unrecognized movement direction.", event_id),
            )
            return
        agent = self._agent_row(conn, agent_id)
        if agent is None:
            return
        dx, dy = vectors[direction]
        current_room_id = str(agent["room_id"])
        current_position = {"x": _safe_int(agent["x"]), "y": _safe_int(agent["y"]), "z": _safe_int(agent["z"])}
        if _disable_world_geometry_collision(self.context.config):
            next_destination = _resolve_unblocked_destination(
                rooms=self.context.room_lookup,
                room_tile_index=self.context.room_tile_index,
                current_room_id=current_room_id,
                current_position=current_position,
                direction=direction,
            )
        else:
            next_destination = _resolve_wall_hop_destination(
                rooms=self.context.room_lookup,
                room_tile_index=self.context.room_tile_index,
                outer_wall_tile_index=self.context.outer_wall_tile_index,
                inner_wall_tile_index=self.context.inner_wall_tile_index,
                current_room_id=current_room_id,
                current_position=current_position,
                direction=direction,
            )
        if not next_destination:
            conn.execute(
                "UPDATE events SET processed = 1, processed_at = ?, response_text = ? WHERE event_id = ?",
                (_now_iso(), "The path is blocked.", event_id),
            )
            return
        next_room_id, next_position = next_destination
        conn.execute(
            """
            UPDATE agents
               SET room_id = ?, x = ?, y = ?, z = ?, control_mode = ?, last_updated_at = ?
             WHERE agent_id = ?
            """,
            (
                next_room_id,
                next_position["x"],
                next_position["y"],
                next_position["z"],
                "human",
                _now_iso(),
                agent_id,
            ),
        )
        conn.execute(
            "UPDATE sessions SET room_id = ?, last_state_index = last_state_index WHERE session_id = ?",
            (next_room_id, session_id),
        )
        conn.execute(
            "UPDATE events SET processed = 1, processed_at = ?, response_text = ? WHERE event_id = ?",
            (_now_iso(), f"{str(agent['display_name'])} moved {direction.replace('move_', '')}.", event_id),
        )



