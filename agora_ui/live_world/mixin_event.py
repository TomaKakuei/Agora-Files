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







class EventMixin:
    def _response_event(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        room_id: str,
        actor_agent_id: str,
        target_agent_id: str,
        action_text: str,
        response_text: str,
        payload: dict[str, Any],
    ) -> None:
        conn.execute(
            "INSERT INTO events(session_id, room_id, agent_id, target_agent_id, event_type, action_text, response_text, processed, created_at, processed_at, payload_json) VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (
                session_id,
                room_id,
                actor_agent_id,
                target_agent_id,
                "agent_response",
                action_text,
                response_text,
                _now_iso(),
                _now_iso(),
                _json_dump(payload),
            ),
        )

    def _client_action_id_column_present(self, conn: sqlite3.Connection) -> bool:
        rows = conn.execute("PRAGMA table_info(events)").fetchall()
        return any(str(row["name"]) == "client_action_id" for row in rows)

    def _find_existing_client_action_event(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        client_action_id: str,
    ) -> sqlite3.Row | None:
        normalized = str(client_action_id or "").strip()
        if not normalized:
            return None
        if not self._client_action_id_column_present(conn):
            return None
        return conn.execute(
            """
            SELECT *
              FROM events
             WHERE session_id = ?
               AND client_action_id = ?
             ORDER BY event_id DESC
             LIMIT 1
            """,
            (session_id, normalized),
        ).fetchone()

    def _note_latest_event(self, event_id: int) -> None:
        with self._snapshot_cache_lock:
            if self._hot_world_snapshot is not None:
                self._hot_world_snapshot["latest_event_id"] = max(int(self._hot_world_snapshot.get("latest_event_id", 0)), int(event_id))
                self._hot_world_snapshot["updated_at"] = _now_iso()

    def _apply_assign_task_action(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        actor_agent_id: str,
        target_agent_id: str,
        event_id: int,
        action_text: str,
        kind: str,
        client_action_id: str = "",
        destination_room_id: str = "",
        destination_coordinates: dict[str, Any] | None = None,
    ) -> None:
        actor = self._agent_row(conn, actor_agent_id)
        if actor is None:
            return
        room_id = str(actor["room_id"])
        target = self._resolve_target_agent(conn, room_id=room_id, actor_agent_id=actor_agent_id, target_agent_id=target_agent_id)
        if target is None:
            response = "No nearby agent is available for that task."
            conn.execute(
                "UPDATE events SET processed = 1, processed_at = ?, response_text = ? WHERE event_id = ?",
                (_now_iso(), response, event_id),
            )
            self._response_event(
                conn,
                session_id=session_id,
                room_id=room_id,
                actor_agent_id=actor_agent_id,
                target_agent_id=target_agent_id,
                action_text=action_text or response,
                response_text=response,
                payload={"kind": "task_assign", "task_status": "failed_unavailable", "task_kind": kind, "client_action_id": client_action_id},
            )
            return
        target_state = self._ensure_agent_state_defaults(str(target["agent_id"]), _json_load(str(target["state_json"]), {}))
        target_room_name = str(self.context.room_lookup.get(destination_room_id, {}).get("name", destination_room_id))
        if kind == "follow_agent":
            response = f"{str(target['display_name'])} starts following {str(actor['display_name'])}."
            task = {
                "task_id": f"task_{secrets.token_hex(6)}",
                "kind": "follow_agent",
                "status": "active",
                "requested_by_agent_id": actor_agent_id,
                "target_agent_id": actor_agent_id,
                "target_room_id": "",
                "target_coordinates": self._agent_coordinates(actor),
                "follow_radius": 1,
                "offer_id": "",
                "item_id": "",
                "quantity": 1,
                "created_at": _now_iso(),
                "completed_at": "",
                "note": "follow_human_request",
            }
        else:
            goal_coordinates = _coord_payload(destination_coordinates or {}, fallback=self._agent_coordinates(target))
            response = f"{str(target['display_name'])} heads toward {target_room_name or 'the requested location'}."
            task = {
                "task_id": f"task_{secrets.token_hex(6)}",
                "kind": "move_to_room" if destination_room_id else "move_to_coordinate",
                "status": "active",
                "requested_by_agent_id": actor_agent_id,
                "target_agent_id": "",
                "target_room_id": destination_room_id,
                "target_coordinates": goal_coordinates,
                "follow_radius": 1,
                "offer_id": "",
                "item_id": "",
                "quantity": 1,
                "created_at": _now_iso(),
                "completed_at": "",
                "note": "move_request_from_human",
            }
        self._set_active_task(target_state, task)
        self._save_agent_state(conn, agent_row=target, state=target_state, current_focus=response, mainline_summary=response)
        conn.execute(
            "UPDATE events SET processed = 1, processed_at = ?, response_text = ?, payload_json = ? WHERE event_id = ?",
            (_now_iso(), response, _json_dump({"kind": "task_assign", "task_id": task["task_id"], "task_kind": task["kind"], "task_status": "accepted", "client_action_id": client_action_id}), event_id),
        )
        self._response_event(
            conn,
            session_id=session_id,
            room_id=room_id,
            actor_agent_id=str(target["agent_id"]),
            target_agent_id=actor_agent_id,
            action_text=action_text or response,
            response_text=response,
            payload={"kind": "task_assign", "task_id": task["task_id"], "task_kind": task["kind"], "task_status": "accepted", "client_action_id": client_action_id},
        )

    def _handle_submit_action_command(self, command: LiveCoordinatorCommand) -> dict[str, Any]:
        session_id = str(command.session_id or "").strip()
        payload = dict(command.payload or {})
        response_since = 0
        action_type = str(payload.get("action_type", "message")).strip() or "message"
        action_text = str(payload.get("action_text", "")).strip()
        direction = str(payload.get("direction", "")).strip().lower()
        target_agent_id = str(payload.get("target_agent_id", "")).strip()
        item_id = str(payload.get("item_id", "")).strip()
        return_item_id = str(payload.get("return_item_id", "")).strip()
        offer_id = str(payload.get("offer_id", "")).strip()
        destination_room_id = str(payload.get("destination_room_id", payload.get("room_id", ""))).strip()
        destination_coordinates = payload.get("coordinates", {}) if isinstance(payload.get("coordinates", {}), dict) else {}
        quantity = max(1, _safe_int(payload.get("quantity", 1), 1))
        client_action_id = str(payload.get("client_action_id", "")).strip()
        ai_job_payload: dict[str, Any] | None = None
        async_ack_only = action_type in LIVE_ACCEPTED_ACTION_TYPES
        with self._write_transaction() as conn:
            session = self._session_row(conn, session_id)
            if session is None or str(session["status"]) != "active":
                raise FileNotFoundError(f"session not found: {session_id}")
            self._reap_expired_sessions(conn, _now_ts())
            session = self._session_row(conn, session_id)
            if session is None or str(session["status"]) != "active":
                raise FileNotFoundError(f"session not found: {session_id}")
            agent = self._agent_row(conn, str(session["claimed_agent_id"]))
            if agent is None:
                raise RuntimeError("claimed agent missing from live state")
            response_since = int(session["last_state_index"])
            existing_event = self._find_existing_client_action_event(
                conn,
                session_id=session_id,
                client_action_id=client_action_id,
            )
            if existing_event is not None:
                existing_payload = _json_load(str(existing_event["payload_json"] or ""), {})
                existing_pending = int(existing_event["processed"] or 0) == 0 or str(existing_payload.get("message_status", "")).strip() == "pending"
                if existing_pending:
                    snapshot = self._peek_hot_world_snapshot_meta() or {}
                    return {
                        "status": "accepted",
                        "state": None,
                        "latest_event_id": max(
                            int(snapshot.get("latest_event_id", 0) or 0),
                            int(existing_event["event_id"] or 0),
                        ),
                        "world_revision": int(snapshot.get("world_revision", self._world_revision) or self._world_revision),
                        "action": {
                            "event_id": int(existing_event["event_id"] or 0),
                            "action_type": action_type,
                            "client_action_id": client_action_id,
                            "pending": True,
                            "deduped": True,
                        },
                    }
                state = self._build_state_payload(conn, session_id=session_id, since=response_since)
                conn.execute("UPDATE sessions SET last_state_index = ? WHERE session_id = ?", (int(state["latest_event_id"]), session_id))
                self._flush_dirty_heartbeats(conn, force=False)
                conn.commit()
                return {
                    "status": "ok",
                    "state": state,
                    "latest_event_id": int((state or {}).get("latest_event_id", 0)),
                    "world_revision": int(state.get("world_revision", self._world_revision) or self._world_revision),
                    "action": {
                        "event_id": int(existing_event["event_id"] or 0),
                        "action_type": action_type,
                        "client_action_id": client_action_id,
                        "pending": False,
                        "deduped": True,
                    },
                }
            event_payload = dict(payload)
            if client_action_id:
                event_payload["client_action_id"] = client_action_id
            if action_type == "message":
                event_payload["message_status"] = "pending"
            cursor = conn.execute(
                """
                INSERT INTO events(
                    session_id, client_action_id, room_id, agent_id, target_agent_id,
                    event_type, action_text, response_text, processed, created_at, payload_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)
                """,
                (
                    session_id,
                    client_action_id,
                    str(session["room_id"]),
                    str(agent["agent_id"]),
                    target_agent_id,
                    "human_action",
                    action_text,
                    0 if action_type == "message" else 0,
                    _now_iso(),
                    _json_dump(event_payload),
                ),
            )
            event_id = int(cursor.lastrowid or 0)
            if action_type == "move" or direction in {"up", "down", "left", "right"}:
                self._apply_move(conn, session_id=session_id, agent_id=str(agent["agent_id"]), direction=direction or action_type, event_id=event_id)
            elif action_type == "use_item":
                self._apply_use_item_action(
                    conn,
                    session_id=session_id,
                    actor_agent_id=str(agent["agent_id"]),
                    target_agent_id=target_agent_id,
                    item_id=item_id,
                    quantity=quantity,
                    action_text=action_text,
                    event_id=event_id,
                    payload=dict(payload),
                )
            elif action_type == "trade_item":
                self._apply_trade_action(
                    conn,
                    session_id=session_id,
                    actor_agent_id=str(agent["agent_id"]),
                    target_agent_id=target_agent_id,
                    item_id=item_id,
                    return_item_id=return_item_id,
                    quantity=quantity,
                    action_text=action_text,
                    event_id=event_id,
                    payload=dict(payload),
                )
            elif action_type == "request_trade_quote":
                self._apply_trade_quote_request(
                    conn,
                    session_id=session_id,
                    actor_agent_id=str(agent["agent_id"]),
                    target_agent_id=target_agent_id,
                    item_id=item_id,
                    return_item_id=return_item_id,
                    quantity=quantity,
                    action_text=action_text,
                    event_id=event_id,
                    client_action_id=client_action_id,
                )
            elif action_type == "accept_trade_quote":
                self._apply_accept_trade_quote(
                    conn,
                    session_id=session_id,
                    actor_agent_id=str(agent["agent_id"]),
                    offer_id=offer_id,
                    event_id=event_id,
                    action_text=action_text,
                )
            elif action_type == "reject_trade_quote":
                self._apply_reject_trade_quote(
                    conn,
                    session_id=session_id,
                    actor_agent_id=str(agent["agent_id"]),
                    offer_id=offer_id,
                    event_id=event_id,
                    action_text=action_text,
                )
            elif action_type == "assign_follow_task":
                self._apply_assign_task_action(
                    conn,
                    session_id=session_id,
                    actor_agent_id=str(agent["agent_id"]),
                    target_agent_id=target_agent_id,
                    event_id=event_id,
                    action_text=action_text,
                    kind="follow_agent",
                    client_action_id=client_action_id,
                )
            elif action_type == "assign_move_task":
                self._apply_assign_task_action(
                    conn,
                    session_id=session_id,
                    actor_agent_id=str(agent["agent_id"]),
                    target_agent_id=target_agent_id,
                    event_id=event_id,
                    action_text=action_text,
                    kind="move_to_room" if destination_room_id else "move_to_coordinate",
                    client_action_id=client_action_id,
                    destination_room_id=destination_room_id,
                    destination_coordinates=destination_coordinates,
                )
            else:
                # Message actions are accepted quickly here and completed later by the AI broker.
                ai_job_payload = {
                    "session_id": session_id,
                    "actor_agent_id": str(agent["agent_id"]),
                    "target_agent_id": target_agent_id,
                    "action_text": action_text,
                    "event_id": event_id,
                    "client_action_id": client_action_id,
                }
            self._touch_world_revision()
            if ai_job_payload is not None or async_ack_only:
                self._note_latest_event(event_id)
                snapshot = self._peek_hot_world_snapshot_meta() or {}
                ack_latest_event_id = max(int(snapshot.get("latest_event_id", 0) or 0), int(event_id))
                state = None
            else:
                self._refresh_hot_world_snapshot(conn)
                state = self._build_state_payload(conn, session_id=session_id, since=response_since)
                conn.execute("UPDATE sessions SET last_state_index = ? WHERE session_id = ?", (int(state["latest_event_id"]), session_id))
            self._flush_dirty_heartbeats(conn, force=False)
            conn.commit()
        if ai_job_payload is not None:
            self._dispatch_ai_broker_job(ai_job_payload)
        return {
            "status": "accepted" if (ai_job_payload is not None or async_ack_only) else "ok",
            "state": state,
            "latest_event_id": int(ack_latest_event_id) if (ai_job_payload is not None or async_ack_only) else int((state or {}).get("latest_event_id", 0)),
            "world_revision": int(self._world_revision),
            "action": {
                "event_id": event_id,
                "action_type": action_type,
                "client_action_id": client_action_id,
                "pending": ai_job_payload is not None or async_ack_only,
            },
        }

    def submit_action(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        action_type = str(payload.get("action_type", "message")).strip() or "message"
        if action_type in LIVE_ACCEPTED_ACTION_TYPES:
            self.ensure_runtime_workers()
            with self._write_transaction() as conn:
                session = self._session_row(conn, session_id)
                if session is None or str(session["status"]) != "active":
                    raise FileNotFoundError(f"session not found: {session_id}")
            snapshot = self._peek_hot_world_snapshot_meta() or {}
            client_action_id = str(payload.get("client_action_id", "")).strip()
            if action_type == "move":
                target_queue = self._coordinator_move_queue
            elif action_type in LIVE_TRADE_QUEUE_ACTION_TYPES:
                # Trade quotes stay inside the single-writer coordinator, but their own queue
                # keeps the request/response flow from timing out behind other live actions.
                target_queue = self._coordinator_trade_queue
            elif action_type in LIVE_TASK_QUEUE_ACTION_TYPES:
                # Move-task assignment still runs through the single writer, but a dedicated queue
                # keeps coordinator backlog visible to the UI instead of blocking the HTTP request.
                target_queue = self._coordinator_task_queue
            else:
                target_queue = self._coordinator_async_queue
            target_queue.put(
                LiveCoordinatorCommand(
                    command="submit_action",
                    session_id=session_id,
                    payload=dict(payload),
                    wait_for_completion=False,
                    timeout_seconds=LIVE_ACTION_ACCEPT_TIMEOUT_SECONDS,
                )
            )
            return {
                "status": "accepted",
                "state": None,
                "latest_event_id": int(snapshot.get("latest_event_id", 0) or 0),
                "world_revision": int(snapshot.get("world_revision", self._world_revision) or self._world_revision),
                "action": {
                    "event_id": 0,
                    "action_type": action_type,
                    "client_action_id": client_action_id,
                    "pending": True,
                    "queued": True,
                },
            }
        return self._run_coordinator_command(
            LiveCoordinatorCommand(
                command="submit_action",
                session_id=session_id,
                payload=dict(payload),
                wait_for_completion=(action_type != "message"),
                timeout_seconds=LIVE_ACTION_SYNC_TIMEOUT_SECONDS if action_type != "message" else LIVE_ACTION_ACCEPT_TIMEOUT_SECONDS,
            )
        )

    def _resolve_room_action_target(
        self,
        conn: sqlite3.Connection,
        *,
        room_id: str,
        actor_agent_id: str,
        target_agent_id: str,
    ) -> sqlite3.Row | None:
        target = self._agent_row(conn, target_agent_id) if target_agent_id else None
        if target is not None and str(target["room_id"]) == room_id and str(target["agent_id"]) != actor_agent_id:
            return target
        nearby = [
            row
            for row in conn.execute("SELECT * FROM agents WHERE room_id = ? AND agent_id != ? ORDER BY agent_id", (room_id, actor_agent_id)).fetchall()
        ]
        return nearby[0] if nearby else None

    def _apply_room_action_no_target(
        self,
        conn: sqlite3.Connection,
        *,
        actor: sqlite3.Row,
        action_text: str,
        room_name: str,
        event_id: int,
        client_action_id: str = "",
    ) -> None:
        actor_agent_id = str(actor["agent_id"])
        response = f"{str(actor['display_name'])} waits in {room_name}; nobody else is nearby."
        actor_state = self._ensure_agent_state_defaults(actor_agent_id, _json_load(str(actor["state_json"]), {}))
        self._save_agent_state(conn, agent_row=actor, state=actor_state, current_focus=action_text or response, mainline_summary=response)
        extra_payload = {
            "response_source": "room_idle",
            "actor_focus": action_text or response,
            "target_focus": response,
            "message_status": "completed",
        }
        if client_action_id:
            extra_payload["client_action_id"] = client_action_id
        merged_payload = _merge_event_payload_json(conn, event_id, extra_payload)
        conn.execute(
            "UPDATE events SET processed = 1, processed_at = ?, response_text = ?, payload_json = ? WHERE event_id = ?",
            (_now_iso(), response, merged_payload, event_id),
        )

    def _persist_room_action_reply(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        actor: sqlite3.Row,
        target: sqlite3.Row,
        room_id: str,
        room_name: str,
        action_text: str,
        event_id: int,
        reply: LiveAgentReply,
        client_action_id: str = "",
        ai_error: str = "",
    ) -> None:
        actor_agent_id = str(actor["agent_id"])
        actor_state = self._ensure_agent_state_defaults(actor_agent_id, _json_load(str(actor["state_json"]), {}))
        target_state = self._ensure_agent_state_defaults(str(target["agent_id"]), _json_load(str(target["state_json"]), {}))
        actor_state["last_ai_actor_focus"] = reply.actor_focus
        actor_state["last_ai_target_focus"] = reply.target_focus
        actor_state["last_ai_response_text"] = reply.response_text
        actor_state["last_ai_response_at"] = _now_iso()
        target_state["last_ai_actor_focus"] = reply.actor_focus
        target_state["last_ai_target_focus"] = reply.target_focus
        target_state["last_ai_response_text"] = reply.response_text
        target_state["last_ai_response_at"] = _now_iso()
        self._save_agent_state(
            conn,
            agent_row=actor,
            state=actor_state,
            current_focus=reply.actor_focus,
            mainline_summary=reply.response_text,
        )
        self._save_agent_state(
            conn,
            agent_row=target,
            state=target_state,
            current_focus=reply.target_focus,
            mainline_summary=reply.response_text,
        )
        route_result = self._apply_live_route_selection(
            conn,
            session_id=session_id,
            actor=actor,
            target=target,
            room_id=room_id,
            route_selection=reply.route_selection or {},
            base_response_text=reply.response_text,
        )
        tool_result = self._apply_agent_tool_call(
            conn,
            session_id=session_id,
            actor=actor,
            target=target,
            room_id=room_id,
            tool_call=reply.tool_call or {},
            base_response_text=reply.response_text,
        )
        response_payload = {
            "actor": actor_agent_id,
            "target": str(target["agent_id"]),
            "room_name": room_name,
            "provider": "google_ai_studio",
            "response_source": reply.response_source,
            "model": reply.model,
            "latency_ms": reply.latency_ms,
            "actor_focus": reply.actor_focus,
            "target_focus": reply.target_focus,
            "message_status": "completed",
        }
        if client_action_id:
            response_payload["client_action_id"] = client_action_id
        if reply.route_selection is not None:
            response_payload["route_selection"] = dict(reply.route_selection)
        if route_result is not None:
            response_payload["route_result"] = dict(route_result)
        if reply.tool_call is not None:
            response_payload["tool_call"] = dict(reply.tool_call)
        if tool_result is not None:
            response_payload["tool_result"] = dict(tool_result)
        if ai_error:
            response_payload["ai_error"] = _trim_text(ai_error, 320)
        self._response_event(
            conn,
            session_id=session_id,
            room_id=room_id,
            actor_agent_id=actor_agent_id,
            target_agent_id=str(target["agent_id"]),
            action_text=action_text,
            response_text=reply.response_text,
            payload=response_payload,
        )
        merged_payload = _merge_event_payload_json(conn, event_id, response_payload)
        conn.execute(
            "UPDATE events SET processed = 1, processed_at = ?, response_text = ?, payload_json = ? WHERE event_id = ?",
            (_now_iso(), reply.response_text, merged_payload, event_id),
        )

    def _process_room_action(
        self,
        *,
        session_id: str,
        actor_agent_id: str,
        target_agent_id: str,
        action_text: str,
        event_id: int,
    ) -> None:
        with self._write_transaction() as conn:
            actor = self._agent_row(conn, actor_agent_id)
            if actor is None:
                return
            room_id = str(actor["room_id"])
            room = self.context.room_lookup.get(room_id, {})
            room_name = str(room.get("name", room_id))
            target = self._resolve_room_action_target(
                conn,
                room_id=room_id,
                actor_agent_id=actor_agent_id,
                target_agent_id=target_agent_id,
            )
            if target is None:
                self._apply_room_action_no_target(
                    conn,
                    actor=actor,
                    action_text=action_text,
                    room_name=room_name,
                    event_id=event_id,
                )
                conn.commit()
                return
            reply = self._compose_live_ai_response(
                conn=conn,
                room_id=room_id,
                room_name=room_name,
                actor=actor,
                target=target,
                action_text=action_text,
            )

        with self._write_transaction() as conn:
            session = self._session_row(conn, session_id)
            if session is None or str(session["status"]) != "active":
                raise FileNotFoundError(f"session not found: {session_id}")
            actor = self._agent_row(conn, actor_agent_id)
            if actor is None:
                raise RuntimeError("claimed agent missing from live state")
            room_id = str(actor["room_id"])
            room = self.context.room_lookup.get(room_id, {})
            room_name = str(room.get("name", room_id))
            target = self._resolve_room_action_target(
                conn,
                room_id=room_id,
                actor_agent_id=actor_agent_id,
                target_agent_id=target_agent_id,
            )
            if target is None:
                self._apply_room_action_no_target(
                    conn,
                    actor=actor,
                    action_text=action_text,
                    room_name=room_name,
                    event_id=event_id,
                )
                conn.commit()
                return
            self._persist_room_action_reply(
                conn,
                session_id=session_id,
                actor=actor,
                target=target,
                room_id=room_id,
                room_name=room_name,
                action_text=action_text,
                event_id=event_id,
                reply=reply,
            )
            conn.commit()

    def _recent_room_events_for_prompt(self, conn: sqlite3.Connection, room_id: str) -> list[dict[str, str]]:
        rows = conn.execute(
            """
            SELECT event_type, agent_id, target_agent_id, action_text, response_text, created_at
              FROM events
             WHERE room_id = ?
             ORDER BY event_id DESC
             LIMIT 4
            """,
            (room_id,),
        ).fetchall()
        events: list[dict[str, str]] = []
        for row in reversed(rows):
            events.append(
                {
                    "type": str(row["event_type"] or ""),
                    "actor": str(row["agent_id"] or ""),
                    "target": str(row["target_agent_id"] or ""),
                    "action": str(row["action_text"] or "")[:180],
                    "response": str(row["response_text"] or "")[:220],
                    "at": str(row["created_at"] or ""),
                }
            )
        return events



