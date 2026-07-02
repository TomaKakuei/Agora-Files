from __future__ import annotations

from typing import Any, Dict

from agora_ui.adjudicator_schemas import (
    ActionIntentSpec,
    AdjudicatorControlSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    StatusEffectSpec,
    WorldRulesSpec,
)
from agora_ui.foundation_schemas import GridPosition
from .geometry import (
    _coord_key,
    _manhattan_distance,
)
from .utils import (
    _add_action_result,
    _add_broadcast,
    _adjust_relationship,
    _apply_model_relationship_adjustments,
    _is_aggressive_action,
    _rule_update,
    _append_rule_if_wrap,
)


def _handle_custom(
    *,
    control: AdjudicatorControlSpec,
    world_rules: WorldRulesSpec,
    state: AgentStateBundleSpec,
    agents: Dict[str, AgentRuntimeProfileSpec],
    start_positions: Dict[str, GridPosition],
    moved_agent_ids: set[str],
    intent: ActionIntentSpec,
    broadcasts: list[dict[str, Any]],
    mutations: dict[str, Any],
    rule_appendices: list[dict[str, Any]],
) -> None:
    actor = agents.get(intent.agent_id)
    target = agents.get(intent.target_agent_id or "")
    if actor is None:
        _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Unknown_Agent", reason="actor not found")
        return
    if target is None:
        _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Unknown_Target", reason="Custom requires target_agent_id")
        return

    target_moved = target.agent_id in moved_agent_ids and _coord_key(start_positions[target.agent_id]) != _coord_key(target.coordinates)
    if target_moved and _manhattan_distance(actor.coordinates, target.coordinates) > world_rules.custom_action_rules.max_range_steps:
        _add_action_result(
            mutations,
            intent=intent,
            status="failed",
            context="Action_Failed_Target_Moved",
            reason="higher-priority movement moved target out of range",
        )
        return
    if _manhattan_distance(actor.coordinates, target.coordinates) > world_rules.custom_action_rules.max_range_steps:
        _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Out_Of_Range", reason="target is outside custom action range")
        return

    action = (intent.action or intent.metadata.get("action") or "Custom").strip()
    action_known = action in world_rules.custom_action_rules.allowed_actions
    if not action_known:
        rule_payload = _rule_update(
            timestep_index=control.timestep_index,
            intent=intent,
            module="Custom",
            rule_type="custom_action_status_effect",
            description=f"Undefined custom action '{action}' is plausible and now applies a bounded status effect when the target is in range.",
            payload={
                "action": action,
                "status_effect": str(intent.metadata.get("status_effect") or action.lower()),
                "duration_steps": int(intent.metadata.get("duration_steps") or world_rules.custom_action_rules.default_duration_steps),
                "max_range_steps": world_rules.custom_action_rules.max_range_steps,
            },
        )
        if not _append_rule_if_wrap(world_rules=world_rules, rule_appendices=rule_appendices, rule_payload=rule_payload):
            _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Undefined_Custom", reason="custom action is not defined in Fixed mode")
            return
        matching_rule = rule_payload["rule_update"]["payload"]

    effect = str(intent.metadata.get("status_effect") or action.lower()).strip()
    duration = int(intent.metadata.get("duration_steps") or world_rules.custom_action_rules.default_duration_steps)
    status_effect = StatusEffectSpec(
        effect=effect,
        duration_steps=max(1, duration),
        source=actor.agent_id,
        metadata={"intent_id": intent.intent_id, "action": action},
    )
    refreshed = False
    for existing in target.status_effects:
        if existing.effect != status_effect.effect or existing.source != status_effect.source:
            continue
        if str(existing.metadata.get("action", "")) != action:
            continue
        existing.duration_steps = max(existing.duration_steps, status_effect.duration_steps)
        existing.metadata.update(status_effect.metadata)
        refreshed = True
        mutations["profile_updates"].append(
            {
                "intent_id": intent.intent_id,
                "agent_id": target.agent_id,
                "status_effect_refreshed": existing.model_dump(),
            }
        )
        break
    if not refreshed:
        target.status_effects.append(status_effect)
        mutations["profile_updates"].append(
            {
                "intent_id": intent.intent_id,
                "agent_id": target.agent_id,
                "status_effect_added": status_effect.model_dump(),
            }
        )
    model_owned_relationship = _apply_model_relationship_adjustments(
        state=state,
        mutations=mutations,
        intent=intent,
        allowed_agent_ids={actor.agent_id, target.agent_id},
    )
    if model_owned_relationship:
        pass
    elif _is_aggressive_action(action):
        _adjust_relationship(
            state=state,
            mutations=mutations,
            source_agent_id=target.agent_id,
            target_agent_id=actor.agent_id,
            trust_delta=-10,
            influence_fear_delta=15,
            reason=f"aggressive custom action: {action}",
        )
    else:
        _adjust_relationship(
            state=state,
            mutations=mutations,
            source_agent_id=target.agent_id,
            target_agent_id=actor.agent_id,
            trust_delta=4,
            affection_delta=2,
            reason=f"non-aggressive custom action: {action}",
        )
    _add_action_result(mutations, intent=intent, status="success", context="Action_Succeeded", reason="custom action applied status effect")
    _add_broadcast(
        broadcasts=broadcasts,
        agents=agents,
        room_id=target.room_id,
        coordinate=target.coordinates,
        message=f"{actor.display_name or actor.agent_id} used {action} on {target.display_name or target.agent_id}.",
        intent_id=intent.intent_id,
    )
