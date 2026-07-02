#!/usr/bin/env python3
"""JSON-driven extra world-function event generation.

This module is intentionally generic: scenario-specific task chains, random
events, hooks, route preferences, and activation parameters must come from the
scenario JSON. The runner only stores the returned event records as world
memory for later routing prompts.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Protocol


class JsonGenerator(Protocol):
    def generate_json(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema: dict[str, Any],
        stage: str,
    ) -> dict[str, Any]:
        ...


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def extra_world_functions_config(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("extra_world_functions", {})
    return value if isinstance(value, dict) else {}


def recent_global_world_events(state: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in getattr(state, "localized_visual_state", {}).get("global", [])[-limit:]
        if isinstance(item, dict)
    ]


def _store_extra_world_event(state: Any, event: dict[str, Any]) -> None:
    room_id = str(event.get("room_id", "")).strip()
    keys = ["global"]
    if room_id:
        keys.append(room_id)
    coordinate = event.get("coordinate", {})
    if isinstance(coordinate, dict) and {"x", "y", "z"}.issubset(coordinate):
        keys.append(
            f"{_safe_int(coordinate.get('x'))},{_safe_int(coordinate.get('y'))},{_safe_int(coordinate.get('z'))}"
        )
    localized = getattr(state, "localized_visual_state", {})
    for key in keys:
        localized.setdefault(key, []).append(dict(event))
        max_events = 80 if key == "global" else 40
        localized[key] = localized[key][-max_events:]


def run_extra_world_functions(
    *,
    client: JsonGenerator | None,
    config: dict[str, Any],
    state: Any,
    round_index: int,
    run_dir: Path,
    rng: random.Random,
) -> list[dict[str, Any]]:
    ewf = extra_world_functions_config(config)
    if not bool(ewf.get("enabled", False)) or client is None:
        return []
    functions = [
        dict(item)
        for item in ewf.get("functions", [])
        if isinstance(item, dict) and bool(item.get("enabled", True))
    ]
    if not functions:
        return []

    rooms = [dict(room) for room in config.get("space", {}).get("rooms", []) if isinstance(room, dict)]
    room_by_id = {str(room.get("room_id", "")): room for room in rooms}
    stage_name = str(ewf.get("stage", "extra_world_functions"))
    max_events_per_round = max(1, _safe_int(ewf.get("max_events_per_round", 6), 6))
    available_routes = [
        str(route.get("route_id", ""))
        for group in ("ordinary_routes", "cinematic_routes")
        for route in config.get("actions", {}).get(group, []) or []
        if isinstance(route, dict) and str(route.get("route_id", "")).strip()
    ]

    generated_events: list[dict[str, Any]] = []
    for function_spec in functions:
        activation_probability = float(
            function_spec.get("activation_probability", ewf.get("activation_probability", 1.0))
        )
        if rng.random() > activation_probability:
            continue
        max_events = max(1, _safe_int(function_spec.get("max_events", ewf.get("max_events_per_function", 2)), 2))
        schema = {
            "events": [
                {
                    "event_id": "string, stable short id",
                    "title": "string, <= 80 chars",
                    "description": "string, <= 240 chars",
                    "room_id": "string, must be one of available room_id values",
                    "event_type": "string, e.g. quest_chain, random_event, rumor, hazard, discovery",
                    "status_tags": ["short strings"],
                    "preferred_routes": ["route_id strings from available routes"],
                    "main_character_hooks": ["agent_id strings that should care, optional"],
                    "expires_after_rounds": "integer, 1-5",
                }
            ],
            "world_function_notes": "string, <= 200 chars",
        }
        context = {
            "round_index": round_index,
            "world": config.get("scenario_meta", {}),
            "domain_label": config.get("runner", {}).get("domain_label", ""),
            "function_spec": function_spec,
            "available_rooms": rooms,
            "available_routes": available_routes,
            "main_characters": [
                {
                    "agent_id": agent.agent_id,
                    "display_name": agent.display_name,
                    "role": agent.public_state.get("role_name", ""),
                    "directive": agent.public_state.get("activity_directive", ""),
                    "room_id": agent.room_id,
                    "status_effects": [item.model_dump() for item in agent.status_effects[-4:]],
                }
                for agent in getattr(state, "agents", [])
                if bool(agent.public_state.get("main_character", False))
            ],
            "recent_global_events": recent_global_world_events(state),
        }
        prompt = (
            "Generate this round's extra world-function outputs for a JSON-defined simulation. "
            "Do not adjudicate actions and do not invent new code functions. Produce only compact event records "
            "that the router can use as world memory. Keep events actionable and compatible with available_routes.\n"
            f"context: {_json_dumps(context)}"
        )
        try:
            generated = client.generate_json(
                system_instruction="You generate strict JSON extra world-function event records for a fixed simulation world.",
                prompt=prompt,
                schema=schema,
                stage=stage_name,
            )
        except Exception as exc:
            event = {
                "event_id": f"r{round_index:03d}_{function_spec.get('function_id', 'extra')}_error",
                "title": "Extra world function failed",
                "description": str(exc)[:240],
                "room_id": "",
                "event_type": "diagnostic",
                "status_tags": ["extra_world_function_error"],
                "preferred_routes": [],
                "main_character_hooks": [],
                "expires_after_rounds": 1,
                "round_index": round_index,
                "function_id": str(function_spec.get("function_id", "")),
                "source": "vertex_api_error",
            }
            generated_events.append(event)
            _store_extra_world_event(state, event)
            continue

        raw_events = generated.get("events", [])
        if not isinstance(raw_events, list):
            raw_events = []
        for raw in raw_events[:max_events]:
            if not isinstance(raw, dict):
                continue
            room_id = str(raw.get("room_id", "")).strip()
            room = room_by_id.get(room_id) or (rooms[0] if rooms else {})
            coordinate = {
                "x": _safe_int(room.get("x", 0)),
                "y": _safe_int(room.get("y", 0)),
                "z": _safe_int(room.get("z", 0)),
            }
            preferred_routes = [
                str(route_id)
                for route_id in raw.get("preferred_routes", [])
                if str(route_id) in available_routes
            ][:8]
            event = {
                "event_id": str(raw.get("event_id", f"r{round_index:03d}_{len(generated_events)+1:02d}"))[:80],
                "title": str(raw.get("title", ""))[:120],
                "description": str(raw.get("description", ""))[:360],
                "room_id": str(room.get("room_id", room_id)),
                "coordinate": coordinate,
                "event_type": str(raw.get("event_type", function_spec.get("function_id", "extra_world_event")))[:80],
                "status_tags": [str(item)[:48] for item in raw.get("status_tags", []) if str(item).strip()][:8],
                "preferred_routes": preferred_routes,
                "main_character_hooks": [str(item) for item in raw.get("main_character_hooks", []) if str(item).strip()][:6],
                "expires_after_rounds": max(1, min(5, _safe_int(raw.get("expires_after_rounds", 2), 2))),
                "round_index": round_index,
                "function_id": str(function_spec.get("function_id", "")),
                "source": "vertex_api",
            }
            generated_events.append(event)
            _store_extra_world_event(state, event)
            if len(generated_events) >= max_events_per_round:
                break
        if len(generated_events) >= max_events_per_round:
            break

    for event in generated_events:
        _append_jsonl(run_dir / "extra_world_functions.jsonl", event)
    return generated_events
