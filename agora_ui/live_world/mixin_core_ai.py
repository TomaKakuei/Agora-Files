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







class CoreAIMixin:
    def _dispatch_ai_broker_job(self, payload: dict[str, Any]) -> None:
        _ensure_live_ai_broker_threads()
        with self._inflight_ai_jobs_lock:
            self._inflight_ai_jobs += 1
        _LIVE_AI_BROKER_QUEUE.put((self, dict(payload)))

    def _barter_request_decision(
        self,
        *,
        buyer_state: dict[str, Any],
        seller_state: dict[str, Any],
        requested_item_id: str,
        offered_item_id: str,
        quantity: int,
    ) -> tuple[bool, str]:
        debug_log = []
        debug_log.append(f"DEBUG: Barter decision started. Buyer: {buyer_state.get('agent_id')} offering {offered_item_id}. Seller: {seller_state.get('agent_id')} requested {requested_item_id} x{quantity}")
        normalized_requested = str(requested_item_id or "").strip()
        normalized_offered = str(offered_item_id or "").strip()
        if not normalized_requested or not normalized_offered:
            debug_log.append("DEBUG: Barter missing item id.")
            with open("/tmp/debug_barter.txt", "a") as f: f.write("\\n".join(debug_log) + "\\n")
            return False, "Barter requests need both a requested item and an offered item."
        if self._item_is_currency(normalized_requested, seller_state) or self._item_is_currency(normalized_offered, buyer_state):
            debug_log.append("DEBUG: Barter item is currency.")
            with open("/tmp/debug_barter.txt", "a") as f: f.write("\\n".join(debug_log) + "\\n")
            return False, "Currency-priced items skip barter review and settle directly."
        requested_entry = self._inventory_entry(seller_state, normalized_requested)
        offered_entry = self._inventory_entry(buyer_state, normalized_offered)
        resolved_quantity = max(1, quantity)
        if requested_entry is None or _safe_int(requested_entry.get("quantity", 0), 0) < resolved_quantity:
            debug_log.append(f"DEBUG: Seller lacks {normalized_requested}. Has: {requested_entry}")
            with open("/tmp/debug_barter.txt", "a") as f: f.write("\\n".join(debug_log) + "\\n")
            return False, f"The seller no longer has enough {normalized_requested}."
        if offered_entry is None or _safe_int(offered_entry.get("quantity", 0), 0) < resolved_quantity:
            debug_log.append(f"DEBUG: Buyer lacks {normalized_offered}. Has: {offered_entry}")
            with open("/tmp/debug_barter.txt", "a") as f: f.write("\\n".join(debug_log) + "\\n")
            return False, f"The buyer does not have enough {normalized_offered} to offer."
        requested_price = self._agent_item_price(seller_state, normalized_requested)
        offered_price = self._agent_item_price(buyer_state, normalized_offered)
        debug_log.append(f"DEBUG: Requested Price: {requested_price}, Offered Price: {offered_price}")
        if requested_price <= 0 and offered_price <= 0:
            debug_log.append("DEBUG: Both prices <= 0.")
            with open("/tmp/debug_barter.txt", "a") as f: f.write("\\n".join(debug_log) + "\\n")
            return False, f"The seller refuses the barter because there is no agreed value anchor for {normalized_requested}."
        requested_value = max(1, requested_price) * resolved_quantity
        offered_value = max(1, offered_price) * resolved_quantity
        if offered_value < requested_value:
            debug_log.append(f"DEBUG: Offered value ({offered_value}) < Requested value ({requested_value})")
            with open("/tmp/debug_barter.txt", "a") as f: f.write("\\n".join(debug_log) + "\\n")
            return False, f"The seller refuses the barter because {normalized_offered} is not enough for {normalized_requested}."
        debug_log.append("DEBUG: Barter approved.")
        with open("/tmp/debug_barter.txt", "a") as f: f.write("\\n".join(debug_log) + "\\n")
        return True, ""

    def _fallback_live_reply(self, *, room_name: str, actor_name: str, target_name: str, action_text: str, error_text: str = "") -> LiveAgentReply:
        response_text = self._compose_response(
            room_name=room_name,
            actor_name=actor_name,
            target_name=target_name,
            action_text=action_text,
        )
        target_focus = response_text
        actor_focus = f"{actor_name} waits for {target_name}'s next move in {room_name}."
        if error_text:
            target_focus = _trim_text(f"{target_focus} ({error_text})", 320)
        return LiveAgentReply(
            response_text=response_text[:720],
            actor_focus=actor_focus[:320],
            target_focus=target_focus[:320],
            response_source="ai_broker_fallback",
            model="fallback",
            latency_ms=1,
        )

    def _compose_live_ai_response_resilient(
        self,
        *,
        room_id: str,
        room_name: str,
        actor: dict[str, Any] | sqlite3.Row,
        target: dict[str, Any] | sqlite3.Row,
        action_text: str,
        route_catalog: list[dict[str, Any]],
        recent_room_events: list[dict[str, str]],
        on_chunk = None,
    ) -> tuple[LiveAgentReply, str]:
        started_at = time.perf_counter()
        last_error = ""
        for attempt_index in range(2):
            try:
                reply = self._compose_live_ai_response(
                    room_id=room_id,
                    room_name=room_name,
                    actor=actor,
                    target=target,
                    action_text=action_text,
                    route_catalog=route_catalog,
                    recent_room_events=recent_room_events,
                    on_chunk=on_chunk,
                )
                return reply, last_error
            except Exception as exc:
                last_error = str(exc)
                if attempt_index == 0:
                    time.sleep(0.15)
                    continue
        fallback = self._fallback_live_reply(
            room_name=room_name,
            actor_name=str(actor["display_name"]),
            target_name=str(target["display_name"]),
            action_text=action_text,
            error_text=last_error,
        )
        elapsed_ms = max(1, int(round((time.perf_counter() - started_at) * 1000.0)))
        return LiveAgentReply(
            response_text=fallback.response_text,
            actor_focus=fallback.actor_focus,
            target_focus=fallback.target_focus,
            response_source=fallback.response_source,
            model=fallback.model,
            latency_ms=elapsed_ms,
            route_selection=None,
            tool_call=None,
        ), last_error

    def _serialize_live_reply(self, reply: LiveAgentReply) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "response_text": reply.response_text,
            "actor_focus": reply.actor_focus,
            "target_focus": reply.target_focus,
            "response_source": reply.response_source,
            "model": reply.model,
            "latency_ms": int(reply.latency_ms),
        }
        if reply.route_selection is not None:
            payload["route_selection"] = dict(reply.route_selection)
        if reply.tool_call is not None:
            payload["tool_call"] = dict(reply.tool_call)
        return payload

    def _deserialize_live_reply(self, payload: dict[str, Any]) -> LiveAgentReply:
        return LiveAgentReply(
            response_text=str(payload.get("response_text", "")).strip(),
            actor_focus=str(payload.get("actor_focus", "")).strip(),
            target_focus=str(payload.get("target_focus", "")).strip(),
            response_source=str(payload.get("response_source", "")).strip() or "ai_broker_fallback",
            model=str(payload.get("model", "")).strip() or "fallback",
            latency_ms=max(1, _safe_int(payload.get("latency_ms", 1), 1)),
            route_selection=dict(payload.get("route_selection", {})) if isinstance(payload.get("route_selection"), dict) else None,
            tool_call=dict(payload.get("tool_call", {})) if isinstance(payload.get("tool_call"), dict) else None,
        )

    def _run_ai_broker_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id", "")).strip()
        actor_agent_id = str(payload.get("actor_agent_id", "")).strip()
        target_agent_id = str(payload.get("target_agent_id", "")).strip()
        action_text = str(payload.get("action_text", "")).strip()
        event_id = max(0, _safe_int(payload.get("event_id", 0), 0))
        client_action_id = str(payload.get("client_action_id", "")).strip()
        with self._write_transaction() as conn:
            session = self._session_row(conn, session_id)
            actor = self._agent_row(conn, actor_agent_id)
            if session is None or actor is None:
                return {
                    **payload,
                    "completion_kind": "cancelled",
                    "event_id": event_id,
                    "client_action_id": client_action_id,
                    "error": "session or actor no longer available",
                }
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
                return {
                    **payload,
                    "completion_kind": "no_target",
                    "room_id": room_id,
                    "room_name": room_name,
                    "event_id": event_id,
                    "client_action_id": client_action_id,
                }
            actor_dict = dict(actor)
            target_dict = dict(target)
            route_catalog = [
                {
                    "route_id": str(route.get("route_id", "")),
                    "kind": str(route.get("kind", "")),
                    "action": str(route.get("action", "")),
                    "status_effect": str(route.get("status_effect", "")),
                    "story_verb": str(route.get("story_verb", "")),
                    "selection_guidance": str(route.get("selection_guidance", ""))[:180],
                }
                for route in self._live_executable_routes(conn)
            ]
            recent_room_events = self._recent_room_events_for_prompt(conn, room_id)
            
            self._pending_broadcasts.put({
                "type": "ai_thinking",
                "client_action_id": client_action_id,
                "target_agent_id": target_agent_id,
                "actor_agent_id": actor_agent_id,
                "session_id": session_id,
            })
            
            def on_chunk(chunk_text: str) -> None:
                self._pending_broadcasts.put({
                    "type": "ai_stream_chunk",
                    "chunk": chunk_text,
                    "client_action_id": client_action_id,
                    "target_agent_id": target_agent_id,
                    "actor_agent_id": actor_agent_id,
                    "session_id": session_id,
                })

        reply, last_error = self._compose_live_ai_response_resilient(
            room_id=room_id,
            room_name=room_name,
            actor=actor_dict,
            target=target_dict,
            action_text=action_text,
            route_catalog=route_catalog,
            recent_room_events=recent_room_events,
            on_chunk=on_chunk,
        )
        return {
            **payload,
            "completion_kind": "reply",
            "room_id": room_id,
            "room_name": room_name,
            "event_id": event_id,
            "client_action_id": client_action_id,
            "resolved_target_agent_id": str(target["agent_id"]),
            "reply": self._serialize_live_reply(reply),
            "ai_error": last_error,
        }

    def _handle_ai_completion_command(self, command: LiveCoordinatorCommand) -> None:
        payload = dict(command.payload or {})
        event_id = max(0, _safe_int(payload.get("event_id", 0), 0))
        if event_id <= 0:
            return
        session_id = str(payload.get("session_id", "")).strip()
        actor_agent_id = str(payload.get("actor_agent_id", "")).strip()
        target_agent_id = str(payload.get("target_agent_id", "")).strip()
        action_text = str(payload.get("action_text", "")).strip()
        client_action_id = str(payload.get("client_action_id", "")).strip()
        completion_kind = str(payload.get("completion_kind", "")).strip()
        with self._write_transaction() as conn:
            event_row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
            if event_row is None or int(event_row["processed"] or 0) == 1:
                return
            session = self._session_row(conn, session_id)
            actor = self._agent_row(conn, actor_agent_id)
            if session is None or actor is None or str(session["status"]) != "active":
                merged_payload = _merge_event_payload_json(
                    conn,
                    event_id,
                    {
                        "client_action_id": client_action_id,
                        "message_status": "cancelled",
                    },
                )
                conn.execute(
                    "UPDATE events SET processed = 1, processed_at = ?, response_text = ?, payload_json = ? WHERE event_id = ?",
                    (_now_iso(), "The live reply expired before it could complete.", merged_payload, event_id),
                )
                self._touch_world_revision()
                self._refresh_hot_world_snapshot(conn)
                conn.commit()
                self._queue_ws_completion_broadcast(session_id, client_action_id)
                return
            room_id = str(actor["room_id"])
            room = self.context.room_lookup.get(room_id, {})
            room_name = str(room.get("name", room_id))
            if completion_kind == "no_target":
                self._apply_room_action_no_target(
                    conn,
                    actor=actor,
                    action_text=action_text,
                    room_name=room_name,
                    event_id=event_id,
                    client_action_id=client_action_id,
                )
                self._touch_world_revision()
                self._refresh_hot_world_snapshot(conn)
                conn.commit()
                self._queue_ws_completion_broadcast(session_id, client_action_id)
                return
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
                    client_action_id=client_action_id,
                )
                self._touch_world_revision()
                self._refresh_hot_world_snapshot(conn)
                conn.commit()
                self._queue_ws_completion_broadcast(session_id, client_action_id)
                return
            reply = self._deserialize_live_reply(dict(payload.get("reply", {})) if isinstance(payload.get("reply"), dict) else {})
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
                client_action_id=client_action_id,
                ai_error=str(payload.get("ai_error", "")).strip(),
            )
            self._touch_world_revision()
            self._refresh_hot_world_snapshot(conn)
            self._flush_dirty_heartbeats(conn, force=False)
            conn.commit()
            self._queue_ws_completion_broadcast(session_id, client_action_id)

    def _handle_heartbeat_command(self, command: LiveCoordinatorCommand) -> dict[str, Any]:
        session_id = str(command.session_id or "").strip()
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

    def _live_ai_enabled(self) -> bool:
        live_config = self.context.config.get("human_interaction", {})
        if isinstance(live_config, dict) and live_config.get("live_ai_enabled") is False:
            return False
        return bool(os.environ.get("AGORA_AISTUDIO_API_KEY") or os.environ.get("GOOGLE_API_KEY"))

    def _live_ai_config(self) -> dict[str, Any]:
        config = json.loads(json.dumps(self.context.config))
        runtime = config.get("runtime", {}) if isinstance(config.get("runtime"), dict) else {}
        vertex_api = dict(config.get("vertex_api", {})) if isinstance(config.get("vertex_api"), dict) else {}
        api_key_env = "AGORA_AISTUDIO_API_KEY" if os.environ.get("AGORA_AISTUDIO_API_KEY") else "GOOGLE_API_KEY"
        model = _normalize_live_model_name(
            str(
                vertex_api.get("live_model")
                or vertex_api.get("model")
                or runtime.get("vertex_model")
                or "gemini-3.1-flash-lite"
            )
        )
        vertex_api.update(
            {
                "backend": "ai_studio",
                "api_key_env": api_key_env,
                "endpoint_base": "https://generativelanguage.googleapis.com/v1beta",
                "method": "generateContent",
                "model": model,
                "temperature": float(vertex_api.get("live_temperature", 0.72)),
                "max_output_tokens": int(vertex_api.get("live_max_output_tokens", 1024)),
                "thinking_level": str(vertex_api.get("live_thinking_level", "low")),
                "thinking_budget": int(vertex_api.get("live_thinking_budget", 0)),
                "timeout_seconds": int(vertex_api.get("live_timeout_seconds", 6)),
                "retry": {
                    "max_attempts": int(vertex_api.get("live_retry_max_attempts", 1)),
                    "initial_sleep_seconds": 0.4,
                    "max_sleep_seconds": 1.0,
                    "backoff_multiplier": 1.0,
                    "status_codes": [408, 429, 500, 502, 503, 504],
                },
                "stages": {
                    **(vertex_api.get("stages", {}) if isinstance(vertex_api.get("stages"), dict) else {}),
                    "live_agent_response": {
                        "model": model,
                        "temperature": float(vertex_api.get("live_temperature", 0.72)),
                        "max_output_tokens": int(vertex_api.get("live_max_output_tokens", 1024)),
                        "thinking_budget": int(vertex_api.get("live_thinking_budget", 0)),
                    },
                },
            }
        )
        config["vertex_api"] = vertex_api
        return config

    def _live_ai_retry_config(self, base_config: dict[str, Any]) -> dict[str, Any]:
        retry_config = json.loads(json.dumps(base_config))
        vertex_api = retry_config.get("vertex_api", {}) if isinstance(retry_config.get("vertex_api"), dict) else {}
        fallback_tokens = max(384, _safe_int(vertex_api.get("max_output_tokens", 1024), 1024))
        vertex_api["temperature"] = min(0.45, _safe_float(vertex_api.get("temperature", 0.72), 0.72))
        vertex_api["max_output_tokens"] = fallback_tokens
        stages = vertex_api.get("stages", {}) if isinstance(vertex_api.get("stages"), dict) else {}
        live_stage = stages.get("live_agent_response", {}) if isinstance(stages.get("live_agent_response"), dict) else {}
        live_stage["temperature"] = min(0.45, _safe_float(live_stage.get("temperature", vertex_api["temperature"]), vertex_api["temperature"]))
        live_stage["max_output_tokens"] = fallback_tokens
        stages["live_agent_response"] = live_stage
        vertex_api["stages"] = stages
        retry_config["vertex_api"] = vertex_api
        return retry_config

    def _compose_live_ai_response(
        self,
        *,
        room_id: str,
        room_name: str,
        actor: dict[str, Any] | sqlite3.Row,
        target: dict[str, Any] | sqlite3.Row,
        action_text: str,
        route_catalog: list[dict[str, Any]],
        recent_room_events: list[dict[str, str]],
        on_chunk = None,
    ) -> LiveAgentReply:
        actor_name = str(actor["display_name"])
        target_name = str(target["display_name"])
        if not self._live_ai_enabled():
            raise RuntimeError("Live AI Studio is not configured for real-time message replies.")
        live_config = self._live_ai_config()
        model = str(live_config.get("vertex_api", {}).get("model", ""))
        actor_state = self._ensure_agent_state_defaults(str(actor["agent_id"]), _json_load(str(actor["state_json"]), {}))
        target_state = self._ensure_agent_state_defaults(str(target["agent_id"]), _json_load(str(target["state_json"]), {}))
        # route_catalog is already populated
        tool_inventory: list[dict[str, Any]] = []
        for entry in target_state.get("inventory", []) or []:
            if not isinstance(entry, dict):
                continue
            item_id = str(entry.get("item_id", "")).strip()
            quantity = max(0, _safe_int(entry.get("quantity", 0), 0))
            if not item_id or quantity <= 0:
                continue
            tool_inventory.append(
                {
                    "item_id": item_id,
                    "name": str(entry.get("name") or self._item_meta(item_id).get("name") or item_id),
                    "quantity": quantity,
                    "quoted_unit_price_minor": self._agent_item_price(target_state, item_id),
                    "quoted_unit_price_gold": self._agent_item_price(target_state, item_id),
                }
            )
        current_room = self.context.room_lookup.get(room_id, {})
        adjacent_room_ids = {room_id}
        for doorway in current_room.get("doorways", []) or []:
            if isinstance(doorway, dict):
                adj_id = str(doorway.get("target_room_id") or doorway.get("connects_to_room_id") or "").strip()
                if adj_id:
                    adjacent_room_ids.add(adj_id)

        room_options = [
            {
                "room_id": candidate_room_id,
                "room_name": str(candidate_room.get("name", candidate_room_id)),
            }
            for candidate_room_id, candidate_room in sorted(self.context.room_lookup.items())
            if candidate_room_id and candidate_room_id in adjacent_room_ids
        ]
        schema = {
            "response_text": "one concise in-character reply from the target agent, 1-3 sentences",
            "target_focus": "short present-tense focus update for target",
            "actor_focus": "short present-tense focus update for actor",
            "route_selection": {
                "route_id": "existing route_id from available_routes, or 'none'",
                "kind": "custom|item_trade|move|none",
                "reason": "very short explanation for the chosen route",
                "item_id": "required only when route kind=item_trade and a concrete item is being quoted",
                "quantity": "integer, default 1, mainly for item_trade",
                "target_room_id": "required only when route kind=move",
            },
            "tool_call": {
                "tool_name": "one of: none, follow_me, quote_item_for_price",
                "target_room_id": "leave blank",
                "item_id": "required for quote_item_for_price, otherwise leave blank",
                "quantity": "integer, default 1",
                "reason": "very short explanation for the triggered tool",
            },
        }
        system_instruction = (
            "You run one live in-world response for a Phaser multiplayer room. "
            "Answer as the target agent only. Do not quote or repeat the human message. "
            "Continue the scene with a concrete reaction, question, decision, or next step. "
            "Keep continuity with recent events and avoid generic customer-support phrasing. "
            "Choose behavior from the DB-backed available_routes list whenever possible. "
            "Use route_selection for ordinary route behavior like moving, trading, or custom social actions. "
            "Only use tool_call.follow_me when the human clearly asks the target to stay close and follow them. "
            "Use tool_call.quote_item_for_price only when the target is ready to directly quote and settle a priced item sale. "
            "If no route is appropriate, return route_selection.route_id='none'."
        )
        prompt = {
            "room": {"room_id": room_id, "room_name": room_name},
            "actor": {
                "agent_id": str(actor["agent_id"]),
                "display_name": actor_name,
                "current_focus": str(actor["current_focus"] or ""),
                "mainline_summary": str(actor["mainline_summary"] or ""),
                "recent_live_routes": actor_state.get("recent_live_routes", []),
            },
            "target": {
                "agent_id": str(target["agent_id"]),
                "display_name": target_name,
                "current_focus": str(target["current_focus"] or ""),
                "mainline_summary": str(target["mainline_summary"] or ""),
                "recent_live_routes": target_state.get("recent_live_routes", []),
            },
            "human_action_text": str(action_text or "")[:500],
            "recent_room_events": recent_room_events,
            "available_routes": route_catalog,
            "available_tool_calls": {"follow_me": "target agent starts following the actor/human"},
            "tool_context": {
                "target_inventory": tool_inventory[:18],
                "room_options": room_options[:80],
                "currency_item_id": self._currency_item_id(),
            },
            "contract": (
                "Return JSON. response_text must not contain the human_action_text verbatim. "
                "route_selection.route_id must be one of available_routes or 'none'. "
                "tool_call must stay empty/none unless the human explicitly asks the target to follow."
            ),
        }
        started = time.perf_counter()
        generated: dict[str, Any] | None = None
        response = ""
        last_error: Exception | None = None
        client_class = _load_vertex_json_client_class()
        attempt_configs = [live_config, self._live_ai_retry_config(live_config)]
        action_text_clean = str(action_text or "").strip()
        for config_index, attempt_config in enumerate(attempt_configs):
            try:
                client = client_class(attempt_config)
                generator = client.stream_generate_compact_json_field(
                    system_instruction=system_instruction,
                    prompt=json.dumps(prompt, ensure_ascii=False),
                    schema=schema,
                    stage="live_agent_response",
                    stream_field="response_text",
                )
                candidate = None
                for chunk_text, is_done, final_json in generator:
                    if on_chunk is not None:
                        on_chunk(chunk_text)
                    if is_done and final_json is not None:
                        candidate = final_json
                if candidate is None:
                    raise RuntimeError("AI Studio live reply did not return valid JSON.")
                candidate_response = str(candidate.get("response_text", "")).strip()
                if not candidate_response:
                    raise RuntimeError("AI Studio live reply returned an empty response.")
                if action_text_clean and action_text_clean in candidate_response:
                    raise RuntimeError("AI Studio live reply echoed the human action text.")
                generated = candidate
                response = candidate_response
                break
            except Exception as exc:
                last_error = exc
                if config_index + 1 >= len(attempt_configs):
                    raise RuntimeError(f"AI Studio live reply failed: {exc}") from exc
        if generated is None:
            raise RuntimeError(f"AI Studio live reply failed: {last_error}")
        latency_ms = max(1, int(round((time.perf_counter() - started) * 1000.0)))
        actor_focus = str(generated.get("actor_focus", "")).strip() or f"{actor_name} waits for {target_name}'s answer in {room_name}."
        target_focus = str(generated.get("target_focus", "")).strip() or response
        # For route_selection parsing we don't strictly need conn except to check if route_id is valid.
        # But wait, self._normalize_route_selection requires conn!
        # Let's run self._normalize_route_selection on the result without conn, or use a read-only one.
        with contextlib.closing(sqlite3.connect(self.live_db_path)) as temp_conn:
            temp_conn.row_factory = sqlite3.Row
            route_selection = self._normalize_route_selection(temp_conn, generated.get("route_selection"))
            
        tool_call = self._normalize_tool_call(generated.get("tool_call"))
        return LiveAgentReply(
            response_text=response[:720],
            actor_focus=actor_focus[:320],
            target_focus=target_focus[:320],
            response_source="ai_studio",
            model=model,
            latency_ms=latency_ms,
            route_selection=route_selection,
            tool_call=tool_call,
        )

    def _compose_response(self, *, room_name: str, actor_name: str, target_name: str, action_text: str) -> str:
        text = action_text.strip()
        if not text:
            return f"{target_name} watches the room and waits for a clearer opening."
        if text.endswith("?"):
            return f"{target_name} answers with a concrete next step for {actor_name} in {room_name}."
        return f"{target_name} reacts to {actor_name}'s move and shifts the conversation forward in {room_name}."

__all__ = ['CoreAIMixin']
