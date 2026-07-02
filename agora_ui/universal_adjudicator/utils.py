from __future__ import annotations

from typing import Any, Dict, List

from agora_ui.adjudicator_schemas import (
    ActionIntentSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    RelationshipVectorSpec,
)
from .geometry import _coord_key


def _clamp_relationship(value: int) -> int:
    return max(0, min(100, int(value)))


def _ensure_relationship(
    state: AgentStateBundleSpec,
    source_agent_id: str,
    target_agent_id: str,
) -> RelationshipVectorSpec:
    state.relationship_tensor.setdefault(source_agent_id, {})
    vector = state.relationship_tensor[source_agent_id].get(target_agent_id)
    if vector is None:
        vector = RelationshipVectorSpec()
        state.relationship_tensor[source_agent_id][target_agent_id] = vector
    return vector


def _adjust_relationship(
    *,
    state: AgentStateBundleSpec,
    mutations: dict[str, Any],
    source_agent_id: str,
    target_agent_id: str,
    trust_delta: int = 0,
    affection_delta: int = 0,
    influence_fear_delta: int = 0,
    reason: str,
) -> None:
    if source_agent_id == target_agent_id:
        return
    vector = _ensure_relationship(state, source_agent_id, target_agent_id)
    before = vector.model_dump()
    vector.trust = _clamp_relationship(vector.trust + trust_delta)
    vector.affection = _clamp_relationship(vector.affection + affection_delta)
    vector.influence_fear = _clamp_relationship(vector.influence_fear + influence_fear_delta)
    after = vector.model_dump()
    if before == after:
        return
    mutations["relationship_tensor_updates"].append(
        {
            "source_agent_id": source_agent_id,
            "target_agent_id": target_agent_id,
            "before": before,
            "after": after,
            "reason": reason,
        }
    )


def _same_coordinate(a: AgentRuntimeProfileSpec, b: AgentRuntimeProfileSpec) -> bool:
    return _coord_key(a.coordinates) == _coord_key(b.coordinates)


def _visible_agent_ids(
    agents: Dict[str, AgentRuntimeProfileSpec],
    room_id: str,
    coordinate: Any,
) -> List[str]:
    coord_key = _coord_key(coordinate)
    return sorted(
        agent.agent_id
        for agent in agents.values()
        if agent.room_id == room_id or _coord_key(agent.coordinates) == coord_key
    )


def _add_broadcast(
    *,
    broadcasts: list[dict[str, Any]],
    agents: Dict[str, AgentRuntimeProfileSpec],
    room_id: str,
    coordinate: Any,
    message: str,
    intent_id: str,
) -> None:
    broadcasts.append(
        {
            "intent_id": intent_id,
            "room_id": room_id,
            "coordinate": coordinate.model_dump(),
            "visible_to_agent_ids": _visible_agent_ids(agents, room_id, coordinate),
            "message": message,
        }
    )


def _add_action_result(
    mutations: dict[str, Any],
    *,
    intent: ActionIntentSpec,
    status: str,
    context: str,
    reason: str,
) -> None:
    mutations["action_results"].append(
        {
            "intent_id": intent.intent_id,
            "agent_id": intent.agent_id,
            "call": intent.call,
            "status": status,
            "context": context,
            "reason": reason,
        }
    )


def _is_aggressive_action(action: str) -> bool:
    return action.strip().lower() in {"attack", "hack", "threaten", "sabotage"}


def _bounded_relationship_delta(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        return 0
    return max(-20, min(20, parsed))


def _apply_model_relationship_adjustments(
    *,
    state: AgentStateBundleSpec,
    mutations: dict[str, Any],
    intent: ActionIntentSpec,
    allowed_agent_ids: set[str],
) -> bool:
    mode = str(intent.metadata.get("relationship_adjustments_mode", "")).strip().lower()
    raw_adjustments = intent.metadata.get("relationship_adjustments")
    if mode != "model" and not isinstance(raw_adjustments, list):
        return False
    if not isinstance(raw_adjustments, list):
        raw_adjustments = []
    for raw in raw_adjustments:
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("source_agent_id", "")).strip()
        target_id = str(raw.get("target_agent_id", "")).strip()
        if (
            source_id not in allowed_agent_ids
            or target_id not in allowed_agent_ids
            or source_id == target_id
        ):
            continue
        _adjust_relationship(
            state=state,
            mutations=mutations,
            source_agent_id=source_id,
            target_agent_id=target_id,
            trust_delta=_bounded_relationship_delta(raw.get("trust_delta", 0)),
            affection_delta=_bounded_relationship_delta(raw.get("affection_delta", 0)),
            influence_fear_delta=_bounded_relationship_delta(raw.get("influence_fear_delta", 0)),
            reason=f"model relationship judgement: {str(raw.get('reason', ''))[:160]}",
        )
    return True


def _rule_update(
    *,
    timestep_index: int,
    intent: ActionIntentSpec,
    module: str,
    rule_type: str,
    description: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "rule_update": {
            "rule_id": f"discovered_{timestep_index}_{intent.intent_id}",
            "source_intent_id": intent.intent_id,
            "module": module,
            "rule_type": rule_type,
            "description": description,
            "payload": payload,
            "created_in_timestep": timestep_index,
            "permanence": "append_to_World_Rules.json",
        }
    }


def _append_rule_if_wrap(
    *,
    world_rules: Any,
    rule_appendices: list[dict[str, Any]],
    rule_payload: dict[str, Any],
) -> bool:
    if world_rules.world_mode != "LLM_Wrap":
        return False
    rule_appendices.append(rule_payload)
    world_rules.discovered_rules.append(rule_payload)
    return True
