from __future__ import annotations

from typing import Any, Dict

from agora_ui.adjudicator_schemas import (
    ActionIntentSpec,
    AdjudicatorControlSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    InventoryItemSpec,
    StatusEffectSpec,
    WorldRulesSpec,
)
from .handlers_items import _add_item, _inventory_item, _remove_item
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
    proposal = intent.metadata.get("open_action_proposal", {})
    coordinator = intent.metadata.get("coordinator_decision", {})
    coordinator_approved = (
        isinstance(proposal, dict)
        and isinstance(coordinator, dict)
        and str(coordinator.get("status", "")) == "approved"
    )
    action_known = action in world_rules.custom_action_rules.allowed_actions
    if not action_known and not coordinator_approved:
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

    if coordinator_approved:
        proposal_effects = [effect for effect in proposal.get("effects", []) if isinstance(effect, dict)]
        required: dict[tuple[str, str], int] = {}
        for proposed_effect in proposal_effects:
            kind = str(proposed_effect.get("kind", ""))
            if kind == "transfer":
                source_id = str(proposed_effect.get("source_agent_id", "") or actor.agent_id)
                item_id = str(proposed_effect.get("item_id", ""))
                key = (source_id, item_id)
                required[key] = required.get(key, 0) + max(1, int(proposed_effect.get("quantity", 1)))
            elif kind == "create_item":
                for item_id in proposed_effect.get("input_item_ids", []):
                    key = (actor.agent_id, str(item_id))
                    required[key] = required.get(key, 0) + 1
        for (source_id, item_id), quantity in required.items():
            source = agents.get(source_id)
            available = _inventory_item(source, item_id).quantity if source is not None and _inventory_item(source, item_id) is not None else 0
            if available < quantity:
                _add_action_result(
                    mutations,
                    intent=intent,
                    status="failed",
                    context="Action_Failed_Coordinator_Precondition_Changed",
                    reason=f"required inventory changed before commit: {source_id}/{item_id}",
                )
                return

        speech_messages: list[str] = []
        for proposed_effect in proposal_effects:
            kind = str(proposed_effect.get("kind", ""))
            if kind == "speech":
                content = str(proposed_effect.get("content", "")).strip()
                if content:
                    speech_messages.append(content[:500])
            elif kind == "transfer":
                source_id = str(proposed_effect.get("source_agent_id", "") or actor.agent_id)
                destination_id = str(proposed_effect.get("target_agent_id", "") or target.agent_id)
                quantity = max(1, int(proposed_effect.get("quantity", 1)))
                removed = _remove_item(agents[source_id], str(proposed_effect.get("item_id", "")), quantity)
                _add_item(agents[destination_id], removed)
                mutations["inventory_updates"].append(
                    {
                        "intent_id": intent.intent_id,
                        "operation": "CoordinatorTransfer",
                        "from_agent_id": source_id,
                        "to_agent_id": destination_id,
                        "item": removed.model_dump(),
                        "open_action": True,
                    }
                )
            elif kind == "create_item":
                consumed = []
                for item_id in proposed_effect.get("input_item_ids", []):
                    removed = _remove_item(actor, str(item_id), 1)
                    consumed.append(removed.model_dump())
                item_id = str(proposed_effect.get("item_id", "")).strip() or "created_" + intent.intent_id[-32:]
                created = InventoryItemSpec(
                    item_id=item_id,
                    name=str(proposed_effect.get("item_name", "Created Object"))[:120],
                    description=str(proposed_effect.get("item_description", ""))[:500],
                    quantity=max(1, int(proposed_effect.get("quantity", 1))),
                    metadata={
                        "created_by_agent_id": actor.agent_id,
                        "created_via_intent_id": intent.intent_id,
                        "coordinator_approved": True,
                        "consumed_inputs": consumed,
                    },
                )
                _add_item(actor, created)
                mutations["inventory_updates"].append(
                    {
                        "intent_id": intent.intent_id,
                        "operation": "CoordinatorCreate",
                        "agent_id": actor.agent_id,
                        "inputs": consumed,
                        "output": created.model_dump(),
                        "open_action": True,
                    }
                )
        intent.metadata["coordinator_committed"] = True
        intent.metadata["speech_messages"] = speech_messages

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
    speech_messages = intent.metadata.get("speech_messages", [])
    broadcast_message = (
        f'{actor.display_name or actor.agent_id} to {target.display_name or target.agent_id}: "{speech_messages[0]}"'
        if isinstance(speech_messages, list) and speech_messages
        else f"{actor.display_name or actor.agent_id} used {action} on {target.display_name or target.agent_id}."
    )
    _add_broadcast(
        broadcasts=broadcasts,
        agents=agents,
        room_id=target.room_id,
        coordinate=target.coordinates,
        message=broadcast_message,
        intent_id=intent.intent_id,
    )
