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







class AgentMixin:
    def _live_ready_agent_ids(self) -> frozenset[str]:
        path = _live_ready_assets_path(self.context.workspace)
        source_key = (
            str(path.resolve()),
            int(path.stat().st_mtime_ns) if path.is_file() else -1,
        )
        if self._cached_live_ready_agent_ids is not None and self._cached_live_ready_source_key == source_key:
            return self._cached_live_ready_agent_ids
        if not path.is_file():
            self._cached_live_ready_agent_ids = frozenset()
            self._cached_live_ready_source_key = source_key
            return self._cached_live_ready_agent_ids
        try:
            payload = _load_json(path)
        except Exception:
            self._cached_live_ready_agent_ids = frozenset()
            self._cached_live_ready_source_key = source_key
            return self._cached_live_ready_agent_ids
        assets = payload.get("assets", []) if isinstance(payload, dict) else []
        self._cached_live_ready_agent_ids = frozenset(
            str(entry.get("id", "")).strip()
            for entry in assets
            if isinstance(entry, dict) and str(entry.get("id", "")).strip()
        )
        self._cached_live_ready_source_key = source_key
        return self._cached_live_ready_agent_ids

    def _main_character_config(self, agent_id: str) -> dict[str, Any]:
        for record in self.context.config.get("main_characters", []) or []:
            if isinstance(record, dict) and str(record.get("agent_id", "")).strip() == str(agent_id).strip():
                return record
        return {}

    def _normalize_active_task(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        task_id = str(value.get("task_id", "")).strip()
        kind = str(value.get("kind", "")).strip()
        status = str(value.get("status", "active")).strip() or "active"
        if not task_id or not kind or status not in {"active", "completed", "failed", "cancelled"}:
            return None
        target_coordinates = value.get("target_coordinates") if isinstance(value.get("target_coordinates"), dict) else {}
        return {
            "task_id": task_id,
            "kind": kind,
            "status": status,
            "requested_by_agent_id": str(value.get("requested_by_agent_id", "")).strip(),
            "target_agent_id": str(value.get("target_agent_id", "")).strip(),
            "target_room_id": str(value.get("target_room_id", "")).strip(),
            "target_coordinates": _coord_payload(target_coordinates),
            "follow_radius": max(1, _safe_int(value.get("follow_radius", 1), 1)),
            "offer_id": str(value.get("offer_id", "")).strip(),
            "item_id": str(value.get("item_id", "")).strip(),
            "quantity": max(1, _safe_int(value.get("quantity", 1), 1)),
            "created_at": str(value.get("created_at", "")).strip(),
            "completed_at": str(value.get("completed_at", "")).strip(),
            "note": _trim_text(value.get("note", ""), 240),
        }

    def _ensure_agent_state_defaults(self, agent_id: str, state: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(state or {})
        main_config = self._main_character_config(agent_id)
        inventory = normalized.get("inventory")
        if not isinstance(inventory, list):
            inventory = main_config.get("inventory", []) if isinstance(main_config.get("inventory", []), list) else []
        normalized["inventory"] = self._normalize_inventory(inventory)
        public_state = normalized.get("public_state", {}) if isinstance(normalized.get("public_state", {}), dict) else {}
        normalized["public_state"] = public_state
        normalized["wallet"] = self._wallet(normalized)
        normalized["property_library"] = [dict(item) for item in normalized.get("property_library", []) if isinstance(item, dict)]
        normalized["knowledge_assets"] = [dict(item) for item in normalized.get("knowledge_assets", []) if isinstance(item, dict)]
        item_prices = public_state.get("item_prices", {}) if isinstance(public_state.get("item_prices", {}), dict) else {}
        derived_prices = {
            entry["item_id"]: self._agent_item_price({"inventory": normalized["inventory"], "public_state": {"item_prices": item_prices}}, entry["item_id"])
            for entry in normalized["inventory"]
            if isinstance(entry, dict) and str(entry.get("item_id", "")).strip()
        }
        public_state["item_prices"] = {
            **{str(key).strip(): max(0, _safe_int(value, 0)) for key, value in item_prices.items() if str(key).strip()},
            **derived_prices,
        }
        normalized["pending_trade_offers"] = self._normalize_trade_offers(normalized.get("pending_trade_offers", []), agent_id=agent_id)
        normalized["active_task"] = self._normalize_active_task(normalized.get("active_task"))
        normalized["recent_live_routes"] = self._normalize_recent_live_routes(normalized.get("recent_live_routes", []))
        if "wallet" not in normalized and main_config:
            normalized["wallet"] = default_wallet_payload(
                max(0, _safe_int(main_config.get("currency_quantity", 0), 0)),
                config=self.context.config,
            )
        normalized["currency_quantity"] = self._wallet_amount_minor(normalized)
        self._sync_currency_inventory(normalized)
        return normalized

    def _save_agent_state(
        self,
        conn: sqlite3.Connection,
        *,
        agent_row: sqlite3.Row,
        state: dict[str, Any],
        current_focus: str | None = None,
        mainline_summary: str | None = None,
    ) -> None:
        normalized = self._ensure_agent_state_defaults(str(agent_row["agent_id"]), state)
        focus_value = str(current_focus if current_focus is not None else normalized.get("current_focus", agent_row["current_focus"]))
        summary_value = str(mainline_summary if mainline_summary is not None else normalized.get("mainline_summary", agent_row["mainline_summary"]))
        normalized["current_focus"] = focus_value
        normalized["mainline_summary"] = summary_value
        
        if str(agent_row["agent_id"]) == "main_character":
            import sys
            has_probe = "quote_probe_item" in str(normalized)
            print(f"SAVING main_character: has_probe={has_probe}", file=sys.stderr)
            print(f"SAVING PROBE ITEM TO {conn} FOR {agent_row['agent_id']}!!!", file=sys.stderr)
            
        self._update_agent_state(conn, str(agent_row["agent_id"]), {
            "current_focus": focus_value,
            "mainline_summary": summary_value,
            "state_json": _json_dump(normalized),
        })

    def _agent_coordinates(self, agent_row: sqlite3.Row) -> dict[str, int]:
        return {
            "x": _safe_int(agent_row["x"]),
            "y": _safe_int(agent_row["y"]),
            "z": _safe_int(agent_row["z"]),
        }

    def _active_session_id_for_agent(self, conn: sqlite3.Connection, agent_id: str) -> str:
        row = conn.execute(
            """
            SELECT session_id
              FROM sessions
             WHERE claimed_agent_id = ? AND status = 'active'
             ORDER BY created_at DESC
             LIMIT 1
            """,
            (agent_id,),
        ).fetchone()
        return str(row["session_id"]).strip() if row is not None else ""

    def _set_active_task(self, state: dict[str, Any], task: dict[str, Any] | None) -> None:
        state["active_task"] = self._normalize_active_task(task)

    def _update_agent_state(self, conn: sqlite3.Connection, agent_id: str, updates: dict[str, Any]) -> None:
        """Centralized helper for updating agent state columns safely."""
        if not updates:
            return
        
        set_clauses = []
        params = []
        for k, v in updates.items():
            set_clauses.append(f"{k} = ?")
            params.append(v)
            
        set_clauses.append("last_updated_at = ?")
        params.append(_now_iso())
        params.append(agent_id)
        
        query = f"UPDATE agents SET {', '.join(set_clauses)} WHERE agent_id = ?"
        conn.execute(query, tuple(params))

    def _prime_hot_agent_state(self, agent_row: sqlite3.Row, *, claimed_by_session_id: str = "", control_mode: str = "") -> dict[str, Any]:
        agent_id = str(agent_row["agent_id"])
        state = {
            "agent_id": agent_id,
            "display_name": str(agent_row["display_name"]),
            "room_id": str(agent_row["room_id"]),
            "x": _safe_int(agent_row["x"]),
            "y": _safe_int(agent_row["y"]),
            "z": _safe_int(agent_row["z"]),
            "facing": "down",
            "animation": "idle_down",
            "control_mode": str(control_mode or agent_row["control_mode"] or "idle"),
            "claimed_by_session_id": str(claimed_by_session_id or agent_row["claimed_by_session_id"] or ""),
            "updated_at": _now_iso(),
            "last_input_seq": 0,
        }
        with self._realtime_state_lock:
            existing = self._hot_agent_states.get(agent_id)
            if existing:
                merged = {**existing, **state}
                self._hot_agent_states[agent_id] = merged
                return dict(merged)
            self._hot_agent_states[agent_id] = state
            return dict(state)

    def _hot_agent_state(self, agent_id: str) -> dict[str, Any] | None:
        normalized = str(agent_id or "").strip()
        if not normalized:
            return None
        with self._realtime_state_lock:
            state = self._hot_agent_states.get(normalized)
            return dict(state) if state is not None else None

    def _active_agent_count(self, conn: sqlite3.Connection, room_id: str, room_active: bool) -> int:
        if not room_active:
            return 0
        row = conn.execute("SELECT COUNT(*) AS count FROM agents WHERE room_id = ?", (room_id,)).fetchone()
        return int(row["count"] if row is not None else 0)

    def _agent_row(self, conn: sqlite3.Connection, agent_id: str) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()

    def _agent_payload(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        now: float,
        *,
        room_active_by_id: dict[str, bool] | None = None,
        roaming_plan_by_key: dict[tuple[str, str], sqlite3.Row] | None = None,
        agent_updated_at_seconds: dict[str, float] | None = None,
        live_ready_agent_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        state = _json_load(str(row["state_json"]), {})
        if not isinstance(state, dict):
            state = {}
        state = self._ensure_agent_state_defaults(str(row["agent_id"]), state)
        room_id = str(row["room_id"])
        agent_id = str(row["agent_id"])
        room = self.context.room_lookup.get(room_id, {})
        if room_active_by_id is not None:
            room_active = bool(room_active_by_id.get(room_id, False))
        else:
            room_row = conn.execute("SELECT active FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
            room_active = bool(int(room_row["active"])) if room_row is not None else False
        if roaming_plan_by_key is not None:
            roam_path_row = roaming_plan_by_key.get((room_id, agent_id))
        else:
            roam_path_row = conn.execute(
                "SELECT path_json, offset_index FROM roaming_plans WHERE room_id = ? AND agent_id = ?",
                (room_id, agent_id),
            ).fetchone()
        path = _json_load(str(roam_path_row["path_json"]) if roam_path_row else "[]", [])
        offset_index = _safe_int(roam_path_row["offset_index"] if roam_path_row else 0)
        coords = {
            "x": _safe_int(row["x"]),
            "y": _safe_int(row["y"]),
            "z": _safe_int(row["z"]),
        }
        hot_state = self._hot_agent_state(agent_id)
        if hot_state is not None:
            room_id = str(hot_state.get("room_id", room_id) or room_id)
            coords = {
                "x": _safe_int(hot_state.get("x", coords["x"])),
                "y": _safe_int(hot_state.get("y", coords["y"])),
                "z": _safe_int(hot_state.get("z", coords["z"])),
            }
            room = self.context.room_lookup.get(room_id, room)
            if room_active_by_id is not None:
                room_active = bool(room_active_by_id.get(room_id, room_active))
            else:
                room_row = conn.execute("SELECT active FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
                room_active = bool(int(room_row["active"])) if room_row is not None else False
        live_motion_mode = "active" if room_active else "roam"
        if hot_state is None and not room_active and path:
            created_at_seconds = (
                float(agent_updated_at_seconds.get(agent_id, now))
                if agent_updated_at_seconds is not None
                else self._agent_created_at_seconds(conn, agent_id)
            )
            preview_step = max(1, int((now - created_at_seconds) / self.context.roam_step_seconds))
            point = path[(offset_index + preview_step) % len(path)]
            coords = {"x": _safe_int(point.get("x", 0)), "y": _safe_int(point.get("y", 0)), "z": _safe_int(point.get("z", 0))}
        public_state = state.get("public_state", {}) if isinstance(state.get("public_state", {}), dict) else {}
        runtime_memory = public_state.get("runtime_memory", {}) if isinstance(public_state, dict) else {}
        current_focus = str(row["current_focus"] or runtime_memory.get("current_focus", "") or state.get("current_focus", ""))
        mainline_summary = str(row["mainline_summary"] or runtime_memory.get("mainline_summary", "") or state.get("mainline_summary", ""))
        live_ready = agent_id in live_ready_agent_ids if live_ready_agent_ids is not None else agent_id in self._live_ready_agent_ids()
        return {
            **state,
            "agent_id": agent_id,
            "display_name": str(row["display_name"]),
            "room_id": room_id,
            "coordinates": coords,
            "main_character": bool(_safe_int(row["main_character"])),
            "current_focus": current_focus,
            "mainline_summary": mainline_summary,
            "claimed_by_session_id": str((hot_state or {}).get("claimed_by_session_id", row["claimed_by_session_id"])),
            "control_mode": str((hot_state or {}).get("control_mode", row["control_mode"])),
            "facing": str((hot_state or {}).get("facing", "down")),
            "animation": str((hot_state or {}).get("animation", "idle_down")),
            "last_input_seq": max(0, _safe_int((hot_state or {}).get("last_input_seq", 0), 0)),
            "inventory": self._normalize_inventory(state.get("inventory", [])),
            "wallet": dict(state.get("wallet", {})) if isinstance(state.get("wallet", {}), dict) else default_wallet_payload(max(0, _safe_int(state.get("currency_quantity", 0), 0)), config=self.context.config),
            "currency_quantity": max(0, _safe_int(state.get("currency_quantity", 0), 0)),
            "currency_item_id": self._currency_item_id(),
            "currency_symbol": self._currency_symbol(),
            "item_prices": dict(state.get("public_state", {}).get("item_prices", {})) if isinstance(state.get("public_state", {}).get("item_prices", {}), dict) else {},
            "property_library": [dict(item) for item in state.get("property_library", []) if isinstance(item, dict)],
            "knowledge_assets": [dict(item) for item in state.get("knowledge_assets", []) if isinstance(item, dict)],
            "pending_trade_offers": list(state.get("pending_trade_offers", [])) if isinstance(state.get("pending_trade_offers", []), list) else [],
            "active_task": dict(state.get("active_task", {})) if isinstance(state.get("active_task", {}), dict) else None,
            "recent_live_routes": list(state.get("recent_live_routes", [])) if isinstance(state.get("recent_live_routes", []), list) else [],
            "live_motion_mode": live_motion_mode,
            "live_room_active": room_active,
            "live_ready": live_ready,
            "live_preview_path": path,
            "room_name": str(room.get("name", room_id)),
        }

    def _agent_created_at_seconds(self, conn: sqlite3.Connection, agent_id: str) -> float:
        row = conn.execute("SELECT last_updated_at FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        if row is None:
            return _now_ts()
        return _iso_to_ts(row["last_updated_at"], _now_ts())

    def _task_room_ids(self, conn: sqlite3.Connection) -> set[str]:
        room_ids: set[str] = set()
        for row in conn.execute("SELECT agent_id, room_id, state_json FROM agents").fetchall():
            state = self._ensure_agent_state_defaults(str(row["agent_id"]), _json_load(str(row["state_json"]), {}))
            task = state.get("active_task")
            if isinstance(task, dict) and str(task.get("status", "")) == "active":
                room_id = str(row["room_id"]).strip()
                if room_id:
                    room_ids.add(room_id)
        return room_ids

    def _complete_task(
        self,
        conn: sqlite3.Connection,
        *,
        agent_row: sqlite3.Row,
        state: dict[str, Any],
        task: dict[str, Any],
        status: str,
        response_text: str,
        session_id: str = "",
        target_agent_id: str = "",
    ) -> None:
        updated_task = dict(task)
        updated_task["status"] = status
        updated_task["completed_at"] = _now_iso()
        state["active_task"] = updated_task if status == "failed" else None
        self._save_agent_state(
            conn,
            agent_row=agent_row,
            state=state,
            current_focus=response_text,
            mainline_summary=response_text,
        )
        resolved_session_id = session_id or self._active_session_id_for_agent(conn, str(agent_row["agent_id"]))
        if resolved_session_id:
            self._response_event(
                conn,
                session_id=resolved_session_id,
                room_id=str(agent_row["room_id"]),
                actor_agent_id=str(agent_row["agent_id"]),
                target_agent_id=target_agent_id,
                action_text=response_text,
                response_text=response_text,
                payload={"kind": "task_update", "task_id": str(task.get("task_id", "")), "task_status": status},
            )

    def _advance_agent_task(self, conn: sqlite3.Connection, *, agent_row: sqlite3.Row, state: dict[str, Any]) -> bool:
        task = state.get("active_task")
        if not isinstance(task, dict) or str(task.get("status", "")) != "active":
            return False
        agent_id = str(agent_row["agent_id"])
        agent_name = str(agent_row["display_name"])
        current_position = self._agent_coordinates(agent_row)
        session_id = self._active_session_id_for_agent(conn, str(task.get("requested_by_agent_id", "")))
        if str(task.get("kind", "")) == "follow_agent":
            target = self._agent_row(conn, str(task.get("target_agent_id", "")))
            if target is None:
                self._complete_task(
                    conn,
                    agent_row=agent_row,
                    state=state,
                    task=task,
                    status="failed",
                    response_text=f"{agent_name} loses track of the follow target.",
                    session_id=session_id,
                )
                return True
            target_position = self._agent_coordinates(target)
            if str(target["room_id"]) == str(agent_row["room_id"]) and _coord_distance(current_position, target_position) <= max(1, _safe_int(task.get("follow_radius", 1), 1)):
                response_text = f"{agent_name} keeps pace with {str(target['display_name'])}."
                self._save_agent_state(conn, agent_row=agent_row, state=state, current_focus=response_text, mainline_summary=response_text)
                return True
            path = self._walkable_path(start=current_position, goal=target_position, blocked_keys=set())
            if len(path) >= 2 and self._move_agent_to_position(conn, agent_row=agent_row, next_position=path[1], control_mode="task_follow"):
                response_text = f"{agent_name} moves to keep following {str(target['display_name'])}."
                self._save_agent_state(conn, agent_row=agent_row, state=state, current_focus=response_text, mainline_summary=response_text)
                return True
            self._save_agent_state(conn, agent_row=agent_row, state=state, current_focus=f"{agent_name} is trying to follow {str(target['display_name'])}.")
            return True
        if str(task.get("kind", "")) == "move_to_room":
            target_room_id = str(task.get("target_room_id", "")).strip()
            target_room = self.context.room_lookup.get(target_room_id, {})
            if target_room_id and str(agent_row["room_id"]) == target_room_id:
                self._complete_task(
                    conn,
                    agent_row=agent_row,
                    state=state,
                    task=task,
                    status="completed",
                    response_text=f"{agent_name} reaches {str(target_room.get('name', target_room_id))}.",
                    session_id=session_id,
                )
                return True
            goal = self._closest_room_goal(agent_row, target_room_id) if target_room_id else None
            if goal is None:
                self._complete_task(
                    conn,
                    agent_row=agent_row,
                    state=state,
                    task=task,
                    status="failed",
                    response_text=f"{agent_name} cannot find a route to the requested room.",
                    session_id=session_id,
                )
                return True
            path = self._walkable_path(start=current_position, goal=goal, blocked_keys=set())
            if len(path) >= 2 and self._move_agent_to_position(conn, agent_row=agent_row, next_position=path[1], control_mode="task_move"):
                response_text = f"{agent_name} heads toward {str(target_room.get('name', target_room_id))}."
                self._save_agent_state(conn, agent_row=agent_row, state=state, current_focus=response_text, mainline_summary=response_text)
                return True
            self._save_agent_state(conn, agent_row=agent_row, state=state, current_focus=f"{agent_name} is trying to reach {str(target_room.get('name', target_room_id))}.")
            return True
        if str(task.get("kind", "")) == "move_to_coordinate":
            goal = _coord_payload(task.get("target_coordinates", {}), fallback=current_position)
            if _coord_distance(current_position, goal) == 0:
                self._complete_task(
                    conn,
                    agent_row=agent_row,
                    state=state,
                    task=task,
                    status="completed",
                    response_text=f"{agent_name} arrives at the requested location.",
                    session_id=session_id,
                )
                return True
            path = self._walkable_path(start=current_position, goal=goal, blocked_keys=set())
            if len(path) >= 2 and self._move_agent_to_position(conn, agent_row=agent_row, next_position=path[1], control_mode="task_move"):
                response_text = f"{agent_name} moves toward the requested location."
                self._save_agent_state(conn, agent_row=agent_row, state=state, current_focus=response_text, mainline_summary=response_text)
                return True
            self._save_agent_state(conn, agent_row=agent_row, state=state, current_focus=f"{agent_name} is trying to reach the requested location.")
            return True
        if str(task.get("kind", "")) == "deliver_trade_offer":
            buyer = self._agent_row(conn, str(task.get("target_agent_id", "")))
            if buyer is None:
                self._complete_task(
                    conn,
                    agent_row=agent_row,
                    state=state,
                    task=task,
                    status="failed",
                    response_text=f"{agent_name} cannot find the buyer anymore.",
                    session_id=session_id,
                )
                return True
            buyer_position = self._agent_coordinates(buyer)
            if str(buyer["room_id"]) == str(agent_row["room_id"]) and _coord_distance(current_position, buyer_position) <= 1:
                success, response_text = self._execute_trade_offer(
                    conn,
                    buyer_row=buyer,
                    seller_row=agent_row,
                    offer_id=str(task.get("offer_id", "")),
                    session_id=self._active_session_id_for_agent(conn, str(buyer["agent_id"])),
                )
                refreshed_agent_row = self._agent_row(conn, agent_id)
                refreshed_state = self._ensure_agent_state_defaults(
                    agent_id,
                    _json_load(str(refreshed_agent_row["state_json"]), {}),
                ) if refreshed_agent_row is not None else state
                self._complete_task(
                    conn,
                    agent_row=refreshed_agent_row or agent_row,
                    state=refreshed_state,
                    task=task,
                    status="completed" if success else "failed",
                    response_text=response_text,
                    session_id=self._active_session_id_for_agent(conn, str(buyer["agent_id"])),
                    target_agent_id=str(buyer["agent_id"]),
                )
                return True
            path = self._walkable_path(start=current_position, goal=buyer_position, blocked_keys=set())
            if len(path) >= 2 and self._move_agent_to_position(conn, agent_row=agent_row, next_position=path[1], control_mode="task_trade"):
                response_text = f"{agent_name} moves toward {str(buyer['display_name'])} to finish the trade."
                self._save_agent_state(conn, agent_row=agent_row, state=state, current_focus=response_text, mainline_summary=response_text)
                return True
            self._save_agent_state(conn, agent_row=agent_row, state=state, current_focus=f"{agent_name} is trying to reach {str(buyer['display_name'])} for the trade.")
            return True
        self._complete_task(
            conn,
            agent_row=agent_row,
            state=state,
            task=task,
            status="failed",
            response_text=f"{agent_name} drops an unsupported task type.",
            session_id=session_id,
        )
        return True

    def _advance_room_agents(self, conn: sqlite3.Connection, *, room_id: str, room: dict[str, Any]) -> None:
        rows = conn.execute("SELECT agent_id FROM agents WHERE room_id = ? ORDER BY agent_id", (room_id,)).fetchall()
        room_name = str(room.get("name", room_id))
        for entry in rows:
            row = self._agent_row(conn, str(entry["agent_id"]))
            if row is None or str(row["room_id"]) != room_id:
                continue
            if str(row["claimed_by_session_id"]).strip():
                continue
            state = self._ensure_agent_state_defaults(str(row["agent_id"]), _json_load(str(row["state_json"]), {}))
            if self._advance_agent_task(conn, agent_row=row, state=state):
                continue
            roam_row = conn.execute(
                "SELECT path_json, offset_index FROM roaming_plans WHERE room_id = ? AND agent_id = ?",
                (room_id, str(row["agent_id"])),
            ).fetchone()
            path = _json_load(str(roam_row["path_json"]) if roam_row is not None else "[]", [])
            if not isinstance(path, list) or not path:
                continue
            current_key = _room_tile_key(_safe_int(row["x"]), _safe_int(row["y"]), _safe_int(row["z"]))
            current_index = next(
                (
                    index for index, point in enumerate(path)
                    if _room_tile_key(_safe_int(point.get("x", 0)), _safe_int(point.get("y", 0)), _safe_int(point.get("z", 0))) == current_key
                ),
                _safe_int(roam_row["offset_index"] if roam_row is not None else 0, 0) % len(path),
            )
            next_index = current_index
            next_point = path[current_index]
            for step in range(1, len(path) + 1):
                candidate_index = (current_index + step) % len(path)
                candidate = path[candidate_index]
                candidate_key = _room_tile_key(
                    _safe_int(candidate.get("x", 0)),
                    _safe_int(candidate.get("y", 0)),
                    _safe_int(candidate.get("z", 0)),
                )
                if candidate_key == current_key or candidate_key:
                    next_index = candidate_index
                    next_point = candidate
                    break
            conn.execute(
                """
                UPDATE agents
                   SET x = ?, y = ?, z = ?, control_mode = ?, last_updated_at = ?
                 WHERE agent_id = ?
                """,
                (
                    _safe_int(next_point.get("x", 0)),
                    _safe_int(next_point.get("y", 0)),
                    _safe_int(next_point.get("z", 0)),
                    "active_room",
                    _now_iso(),
                    str(row["agent_id"]),
                ),
            )
            conn.execute(
                "UPDATE roaming_plans SET offset_index = ?, updated_at = ? WHERE room_id = ? AND agent_id = ?",
                (next_index, _now_iso(), room_id, str(row["agent_id"])),
            )
            summary = str(row["mainline_summary"]).strip() or f"{str(row['display_name'])} keeps moving through {room_name} while the room is live."
            focus = f"{str(row['display_name'])} patrols {room_name}."
            self._save_agent_state(conn, agent_row=row, state=state, current_focus=focus, mainline_summary=summary)

    def _available_agents(self, conn: sqlite3.Connection, *, preferred_room: str = "") -> list[dict[str, Any]]:
        excluded_agent_id = str(self.context.config.get("human_interaction", {}).get("runtime_human_agent_id", "")).strip()
        live_ready_ids = self._live_ready_agent_ids()
        rows = conn.execute(
            "SELECT agent_id, display_name, room_id FROM agents WHERE claimed_by_session_id = '' ORDER BY agent_id"
        ).fetchall()
        payload = [
            {
                "agent_id": str(row["agent_id"]),
                "display_name": str(row["display_name"]),
                "room_id": str(row["room_id"]),
            }
            for row in rows
            if (
                str(row["agent_id"]).strip()
                and str(row["agent_id"]).strip() != excluded_agent_id
                and (not live_ready_ids or str(row["agent_id"]).strip() in live_ready_ids)
            )
        ]
        if preferred_room:
            preferred = [item for item in payload if item["room_id"] == preferred_room]
            if preferred:
                return preferred
        return payload

    def _resolve_target_agent(self, conn: sqlite3.Connection, *, room_id: str, actor_agent_id: str, target_agent_id: str) -> sqlite3.Row | None:
        if target_agent_id:
            target = self._agent_row(conn, target_agent_id)
            if target is not None and str(target["room_id"]) == room_id and str(target["agent_id"]) != actor_agent_id:
                return target
        nearby = conn.execute(
            "SELECT * FROM agents WHERE room_id = ? AND agent_id != ? ORDER BY agent_id",
            (room_id, actor_agent_id),
        ).fetchall()
        return nearby[0] if nearby else None

    def _apply_agent_tool_call(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        actor: sqlite3.Row,
        target: sqlite3.Row,
        room_id: str,
        tool_call: dict[str, Any],
        base_response_text: str,
    ) -> dict[str, Any] | None:
        normalized = self._normalize_tool_call(tool_call)
        if normalized is None:
            return None
        actor = self._agent_row(conn, str(actor["agent_id"])) or actor
        target = self._agent_row(conn, str(target["agent_id"])) or target
        tool_name = str(normalized["tool_name"])
        if tool_name == "follow_me":
            target_state = self._ensure_agent_state_defaults(str(target["agent_id"]), _json_load(str(target["state_json"]), {}))
            self._set_active_task(
                target_state,
                {
                    "task_id": f"task_{secrets.token_hex(6)}",
                    "kind": "follow_agent",
                    "status": "active",
                    "requested_by_agent_id": str(actor["agent_id"]),
                    "target_agent_id": str(actor["agent_id"]),
                    "target_room_id": "",
                    "target_coordinates": self._agent_coordinates(actor),
                    "follow_radius": 1,
                    "offer_id": "",
                    "item_id": "",
                    "quantity": 1,
                    "created_at": _now_iso(),
                    "completed_at": "",
                    "note": normalized.get("reason", "") or "ai_tool_follow_me",
                },
            )
            response = f"{str(target['display_name'])} starts following {str(actor['display_name'])}."
            self._save_agent_state(conn, agent_row=target, state=target_state, current_focus=response, mainline_summary=base_response_text)
            self._response_event(
                conn,
                session_id=session_id,
                room_id=room_id,
                actor_agent_id=str(target["agent_id"]),
                target_agent_id=str(actor["agent_id"]),
                action_text=response,
                response_text=response,
                payload={"kind": "agent_tool_call", "tool_name": tool_name},
            )
            return {"tool_name": tool_name, "response_text": response}
        if tool_name == "go_to_room":
            target_room_id = str(normalized.get("target_room_id", "")).strip()
            if not target_room_id or target_room_id not in self.context.room_lookup:
                return None
            target_state = self._ensure_agent_state_defaults(str(target["agent_id"]), _json_load(str(target["state_json"]), {}))
            self._set_active_task(
                target_state,
                {
                    "task_id": f"task_{secrets.token_hex(6)}",
                    "kind": "move_to_room",
                    "status": "active",
                    "requested_by_agent_id": str(actor["agent_id"]),
                    "target_agent_id": "",
                    "target_room_id": target_room_id,
                    "target_coordinates": self._agent_coordinates(target),
                    "follow_radius": 1,
                    "offer_id": "",
                    "item_id": "",
                    "quantity": 1,
                    "created_at": _now_iso(),
                    "completed_at": "",
                    "note": normalized.get("reason", "") or "ai_tool_go_to_room",
                },
            )
            room_name = str(self.context.room_lookup.get(target_room_id, {}).get("name", target_room_id))
            response = f"{str(target['display_name'])} heads toward {room_name}."
            self._save_agent_state(conn, agent_row=target, state=target_state, current_focus=response, mainline_summary=base_response_text)
            self._response_event(
                conn,
                session_id=session_id,
                room_id=room_id,
                actor_agent_id=str(target["agent_id"]),
                target_agent_id=str(actor["agent_id"]),
                action_text=response,
                response_text=response,
                payload={"kind": "agent_tool_call", "tool_name": tool_name, "target_room_id": target_room_id},
            )
            return {"tool_name": tool_name, "response_text": response, "target_room_id": target_room_id}
        if tool_name == "quote_item_for_price":
            buyer_state = self._ensure_agent_state_defaults(str(actor["agent_id"]), _json_load(str(actor["state_json"]), {}))
            seller_state = self._ensure_agent_state_defaults(str(target["agent_id"]), _json_load(str(target["state_json"]), {}))
            item_id = str(normalized.get("item_id", "")).strip()
            quantity = max(1, _safe_int(normalized.get("quantity", 1), 1))
            seller_item = self._inventory_entry(seller_state, item_id)
            if seller_item is None or _safe_int(seller_item.get("quantity", 0), 0) < quantity:
                return None
            if not self._should_direct_settle_priced_trade(seller_state, item_id):
                return None
            offer = self._issue_trade_quote(
                conn,
                buyer=actor,
                seller=target,
                buyer_state=buyer_state,
                seller_state=seller_state,
                item_id=item_id,
                quantity=quantity,
                note=normalized.get("reason", "") or "ai_tool_quote_item_for_price",
                base_response_text=base_response_text,
            )
            if offer is None:
                return None
            success, response_text = self._execute_trade_offer(
                conn,
                buyer_row=actor,
                seller_row=target,
                offer_id=str(offer.get("offer_id", "")),
                session_id=session_id,
            )
            if not success:
                return {"tool_name": tool_name, "response_text": response_text, "offer_id": str(offer.get("offer_id", "")), "status": "failed_direct_purchase"}
            self._response_event(
                conn,
                session_id=session_id,
                room_id=room_id,
                actor_agent_id=str(target["agent_id"]),
                target_agent_id=str(actor["agent_id"]),
                action_text=response_text,
                response_text=response_text,
                payload={"kind": "agent_tool_call", "tool_name": tool_name, "offer_id": offer["offer_id"], "status": "completed_direct_purchase"},
            )
            return {"tool_name": tool_name, "response_text": response_text, "offer_id": offer["offer_id"], "status": "completed_direct_purchase"}
        return None



