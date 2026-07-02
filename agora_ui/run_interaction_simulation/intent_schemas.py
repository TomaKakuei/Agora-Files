from __future__ import annotations
import json
import random
import re
import time
import traceback
from collections import deque
from typing import Any
from ..adjudicator_schemas import AgentRuntimeProfileSpec, AgentStateBundleSpec, GridPosition
from ..vertex_json_client import VertexJsonClient

def _normalize_shared_action_core(
    raw: Any,
    *,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    route: dict[str, Any],
    selection_reason: str = "",
) -> dict[str, Any]:
    value = raw if isinstance(raw, dict) else {}
    route_label = _limit_text(route.get("action", "") or route.get("story_verb", "") or route.get("route_id", "interaction"), 72)
    goal = _limit_text(
        value.get("shared_action_goal", "")
        or selection_reason
        or route.get("selection_reason", "")
        or route.get("story_verb", route_label),
        160,
    )
    beats = value.get("action_beats", [])
    if isinstance(beats, str):
        beats = [beats]
    normalized_beats = [_limit_text(item, 120) for item in beats if _limit_text(item, 120)]
    if not normalized_beats:
        normalized_beats = [
            _limit_text(f"{actor.display_name} initiates {route.get('story_verb', route_label)}.", 120),
            _limit_text(f"{target.display_name} answers and continues the shared action.", 120),
        ]
    alignment = str(value.get("json_action_alignment", "")).strip().lower()
    off_json_detail = _limit_text(value.get("off_json_detail", ""), 160)
    if alignment not in {"route_only", "off_json_extension", "mixed"}:
        alignment = "off_json_extension" if off_json_detail else "route_only"
    main_character_note = _limit_text(value.get("main_character_recording_note", ""), 160)
    required_names = [
        agent.display_name
        for agent in (actor, target)
        if _is_main_character_agent(agent)
    ]
    if required_names and not main_character_note:
        main_character_note = _limit_text(
            f"Visibly record what {' and '.join(required_names[:2])} are doing in this round through the shared action.",
            160,
        )
    return {
        "shared_action_label": _limit_text(value.get("shared_action_label", "") or route_label, 80),
        "shared_action_goal": goal,
        "action_beats": normalized_beats[:4],
        "actor_role_in_action": _limit_text(
            value.get("actor_role_in_action", "") or f"{actor.display_name} leads or initiates the visible action.",
            120,
        ),
        "target_role_in_action": _limit_text(
            value.get("target_role_in_action", "") or f"{target.display_name} receives, answers, or completes the shared action.",
            120,
        ),
        "props_in_use": [
            _limit_text(item, 64)
            for item in (value.get("props_in_use", []) if isinstance(value.get("props_in_use", []), list) else [])
            if _limit_text(item, 64)
        ][:6],
        "location_focus": _limit_text(value.get("location_focus", "") or actor.room_id or target.room_id, 120),
        "why_now": _limit_text(value.get("why_now", "") or goal, 160),
        "json_action_alignment": alignment,
        "off_json_detail": off_json_detail,
        "main_character_recording_note": main_character_note,
    }


def _relationship_vector_payload(
    state: AgentStateBundleSpec,
    source_id: str,
    target_id: str,
) -> dict[str, int]:
    vector = state.relationship_tensor.get(source_id, {}).get(target_id)
    if vector is None:
        vector = RelationshipVectorSpec()
    return {
        "trust": int(vector.trust),
        "affection": int(vector.affection),
        "influence_fear": int(vector.influence_fear),
    }


def _extra_world_functions_config(config: dict[str, Any]) -> dict[str, Any]:
    return extra_world_functions_config(config)


def _recent_global_world_events(state: AgentStateBundleSpec, *, limit: int = 12) -> list[dict[str, Any]]:
    return recent_global_world_events(state, limit=limit)


def _store_extra_world_event(state: AgentStateBundleSpec, event: dict[str, Any]) -> None:
    room_id = str(event.get("room_id", "")).strip()
    keys = ["global"]
    if room_id:
        keys.append(room_id)
    coordinate = event.get("coordinate", {})
    if isinstance(coordinate, dict) and {"x", "y", "z"}.issubset(coordinate):
        keys.append(f"{int(coordinate['x'])},{int(coordinate['y'])},{int(coordinate['z'])}")
    for key in keys:
        state.localized_visual_state.setdefault(key, []).append(dict(event))
        max_events = 80 if key == "global" else 40
        state.localized_visual_state[key] = state.localized_visual_state[key][-max_events:]


def _run_extra_world_functions(
    *,
    client: VertexJsonClient | None,
    config: dict[str, Any],
    state: AgentStateBundleSpec,
    round_index: int,
    run_dir: Path,
    rng: random.Random,
) -> list[dict[str, Any]]:
    return run_extra_world_functions(
        client=client,
        config=config,
        state=state,
        round_index=round_index,
        run_dir=run_dir,
        rng=rng,
    )


def _bounded_relationship_delta(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 0
    return max(-20, min(20, parsed))


def _normalize_relationship_adjustments(
    payload: dict[str, Any],
    *,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
) -> list[dict[str, Any]]:
    raw_adjustments = payload.get("relationship_adjustments", [])
    if not isinstance(raw_adjustments, list):
        raw_adjustments = []
    allowed_pairs = {
        (actor.agent_id, target.agent_id),
        (target.agent_id, actor.agent_id),
    }
    normalized: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in raw_adjustments:
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("source_agent_id", "")).strip()
        target_id = str(raw.get("target_agent_id", "")).strip()
        pair = (source_id, target_id)
        if pair not in allowed_pairs:
            continue
        normalized[pair] = {
            "source_agent_id": source_id,
            "target_agent_id": target_id,
            "trust_delta": _bounded_relationship_delta(raw.get("trust_delta", 0)),
            "affection_delta": _bounded_relationship_delta(raw.get("affection_delta", 0)),
            "influence_fear_delta": _bounded_relationship_delta(raw.get("influence_fear_delta", 0)),
            "reason": str(raw.get("reason", "model relationship judgement"))[:180],
            "source": str(raw.get("source", "vertex_api")),
        }
    for source_id, target_id in allowed_pairs:
        normalized.setdefault(
            (source_id, target_id),
            {
                "source_agent_id": source_id,
                "target_agent_id": target_id,
                "trust_delta": 0,
                "affection_delta": 0,
                "influence_fear_delta": 0,
                "reason": "model returned no delta for this direction",
                "source": "vertex_api",
            },
        )
    return [normalized[(actor.agent_id, target.agent_id)], normalized[(target.agent_id, actor.agent_id)]]


def _vertex_relationship_metadata(
    client: VertexJsonClient,
    *,
    state: AgentStateBundleSpec,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    route: dict[str, Any],
    config: dict[str, Any],
    round_index: int,
) -> dict[str, Any]:
    schema = {
        "actor_relationship_instruction": "string, <= 160 chars, actor's subjective relationship update rationale",
        "target_relationship_instruction": "string, <= 160 chars, target's subjective relationship update rationale",
        "relationship_adjustments": [
            {
                "source_agent_id": "string, must be actor_id or target_id",
                "target_agent_id": "string, the other participant",
                "trust_delta": "integer from -20 to 20",
                "affection_delta": "integer from -20 to 20",
                "influence_fear_delta": "integer from -20 to 20",
                "reason": "string, <= 120 chars",
            }
        ],
    }
    context = {
        "round_index": round_index,
        "world": config.get("scenario_meta", {}),
        "route": route,
        "actor": {
            "agent_id": actor.agent_id,
            "display_name": actor.display_name,
            "role": actor.public_state.get("role_name", ""),
            "core_values": actor.core_values,
            "status_effects": [item.model_dump() for item in actor.status_effects[-4:]],
        },
        "target": {
            "agent_id": target.agent_id,
            "display_name": target.display_name,
            "role": target.public_state.get("role_name", ""),
            "core_values": target.core_values,
            "status_effects": [item.model_dump() for item in target.status_effects[-4:]],
        },
        "current_relationships": {
            "actor_to_target": _relationship_vector_payload(state, actor.agent_id, target.agent_id),
            "target_to_actor": _relationship_vector_payload(state, target.agent_id, actor.agent_id),
        },
    }
    prompt = (
        "Judge the relationship-state changes caused by this single two-agent interaction.\n"
        "Return delta instructions, not final absolute scores. Both participants must have one update: "
        "actor->target and target->actor.\n"
        "Use small values for routine workplace actions. Trades usually raise trust a little if fair. "
        "Warnings, disarms, escorts, restraints, or authority pressure may reduce trust or raise influence_fear "
        "for the controlled party while still increasing professional respect for the actor. "
        "Keep deltas in [-20, 20] and do not invent new agents or world rules.\n"
        f"context: {_json_dumps(context)}"
    )
    try:
        generated = client.generate_json(
            system_instruction="You output relationship tensor delta instructions as strict JSON.",
            prompt=prompt,
            schema=schema,
            stage="relationship_adjustment",
        )
        adjustments = _normalize_relationship_adjustments(generated, actor=actor, target=target)
        return {
            "relationship_adjustments_mode": "model",
            "relationship_adjustment_source": "vertex_api",
            "actor_relationship_instruction": str(generated.get("actor_relationship_instruction", ""))[:200],
            "target_relationship_instruction": str(generated.get("target_relationship_instruction", ""))[:200],
            "relationship_adjustments": adjustments,
        }
    except Exception as exc:
        return {
            "relationship_adjustments_mode": "model",
            "relationship_adjustment_source": "vertex_api_error",
            "relationship_adjustment_error": str(exc)[:240],
            "relationship_adjustments": _normalize_relationship_adjustments({}, actor=actor, target=target),
        }


def _attach_relationship_metadata_once(intents: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    if not intents or not metadata:
        return
    intents[0].setdefault("metadata", {}).update(metadata)
    for intent in intents[1:]:
        intent.setdefault("metadata", {}).update(
            {
                "relationship_adjustments_mode": "model",
                "relationship_adjustment_source": metadata.get("relationship_adjustment_source", "model"),
                "relationship_adjustments": [],
                "relationship_adjustments_shared_with": intents[0].get("intent_id", ""),
            }
        )

