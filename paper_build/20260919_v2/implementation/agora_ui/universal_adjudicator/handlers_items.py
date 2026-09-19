from __future__ import annotations

from typing import Any, Dict, List, Optional

from agora_ui.adjudicator_schemas import (
    ActionIntentSpec,
    AdjudicatorControlSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    InventoryItemSpec,
    WorldRulesSpec,
)
from .utils import (
    _add_action_result,
    _add_broadcast,
    _adjust_relationship,
    _apply_model_relationship_adjustments,
    _same_coordinate,
    _rule_update,
    _append_rule_if_wrap,
)


def _inventory_item(agent: AgentRuntimeProfileSpec, item_id: str) -> Optional[InventoryItemSpec]:
    for item in agent.inventory:
        if item.item_id == item_id:
            return item
    return None


def _remove_item(agent: AgentRuntimeProfileSpec, item_id: str, quantity: int) -> Optional[InventoryItemSpec]:
    item = _inventory_item(agent, item_id)
    if item is None or item.quantity < quantity:
        return None
    removed = item.model_copy(deep=True, update={"quantity": quantity})
    item.quantity -= quantity
    agent.inventory = [entry for entry in agent.inventory if entry.quantity > 0]
    return removed


def _add_item(agent: AgentRuntimeProfileSpec, item: InventoryItemSpec) -> None:
    existing = _inventory_item(agent, item.item_id)
    if existing is None:
        agent.inventory.append(item.model_copy(deep=True))
        return
    existing.quantity += item.quantity


def _handle_item(
    *,
    control: AdjudicatorControlSpec,
    world_rules: WorldRulesSpec,
    state: AgentStateBundleSpec,
    agents: Dict[str, AgentRuntimeProfileSpec],
    intent: ActionIntentSpec,
    broadcasts: list[dict[str, Any]],
    mutations: dict[str, Any],
    rule_appendices: list[dict[str, Any]],
) -> None:
    actor = agents.get(intent.agent_id)
    if actor is None:
        _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Unknown_Agent", reason="actor not found")
        return
    operation = (intent.operation or intent.metadata.get("operation") or "").strip().lower()
    if operation in {"give", "exchange"}:
        target = agents.get(intent.target_agent_id or "")
        if target is None:
            _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Unknown_Target", reason="Give requires target_agent_id")
            return
        if world_rules.item_rules.require_same_coordinate_for_transfer and not _same_coordinate(actor, target):
            _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Out_Of_Range", reason="item transfer requires same coordinate")
            return
        removed = _remove_item(actor, intent.item_id, intent.quantity)
        if removed is None:
            _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Item_Unavailable", reason="source inventory lacks requested item quantity")
            return
        _add_item(target, removed)
        mutations["inventory_updates"].append(
            {
                "intent_id": intent.intent_id,
                "operation": "Give",
                "from_agent_id": actor.agent_id,
                "to_agent_id": target.agent_id,
                "item": removed.model_dump(),
            }
        )
        model_owned_relationship = _apply_model_relationship_adjustments(
            state=state,
            mutations=mutations,
            intent=intent,
            allowed_agent_ids={actor.agent_id, target.agent_id},
        )
        if not model_owned_relationship:
            _adjust_relationship(
                state=state,
                mutations=mutations,
                source_agent_id=target.agent_id,
                target_agent_id=actor.agent_id,
                trust_delta=3,
                affection_delta=2,
                reason="item transfer received",
            )
        _add_action_result(mutations, intent=intent, status="success", context="Action_Succeeded", reason="item transfer completed")
        _add_broadcast(
            broadcasts=broadcasts,
            agents=agents,
            room_id=target.room_id,
            coordinate=target.coordinates,
            message=f"{actor.display_name or actor.agent_id} gave {removed.item_id} to {target.display_name or target.agent_id}.",
            intent_id=intent.intent_id,
        )
        return

    if operation == "take":
        target = agents.get(intent.target_agent_id or str(intent.metadata.get("from_agent_id", "")))
        if target is None:
            _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Unknown_Target", reason="Take requires target_agent_id or metadata.from_agent_id")
            return
        if world_rules.item_rules.require_same_coordinate_for_transfer and not _same_coordinate(actor, target):
            _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Out_Of_Range", reason="take requires same coordinate")
            return
        removed = _remove_item(target, intent.item_id, intent.quantity)
        if removed is None:
            _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Item_Unavailable", reason="target inventory lacks requested item quantity")
            return
        _add_item(actor, removed)
        mutations["inventory_updates"].append(
            {
                "intent_id": intent.intent_id,
                "operation": "Take",
                "from_agent_id": target.agent_id,
                "to_agent_id": actor.agent_id,
                "item": removed.model_dump(),
            }
        )
        model_owned_relationship = _apply_model_relationship_adjustments(
            state=state,
            mutations=mutations,
            intent=intent,
            allowed_agent_ids={actor.agent_id, target.agent_id},
        )
        if not model_owned_relationship:
            _adjust_relationship(
                state=state,
                mutations=mutations,
                source_agent_id=target.agent_id,
                target_agent_id=actor.agent_id,
                trust_delta=-8,
                influence_fear_delta=6,
                reason="item taken",
            )
        _add_action_result(mutations, intent=intent, status="success", context="Action_Succeeded", reason="item take completed")
        return

    if operation == "combine":
        input_ids = sorted(intent.target_item_ids or [intent.item_id])
        matching_rule = None
        for rule in world_rules.item_rules.combinations:
            rule_inputs = sorted(str(item) for item in rule.get("input_item_ids", []))
            if rule_inputs == input_ids:
                matching_rule = rule
                break
        if matching_rule is None:
            rule_payload = _rule_update(
                timestep_index=control.timestep_index,
                intent=intent,
                module="Item",
                rule_type="item_combination",
                description=f"Undefined item combination '{' + '.join(input_ids)}' is plausible and now yields a combined artifact.",
                payload={
                    "input_item_ids": input_ids,
                    "output_item": {
                        "item_id": "combined_" + "_".join(input_ids),
                        "quantity": 1,
                        "mass": 0.0,
                        "description": "LLM_Wrap discovered combined artifact.",
                    },
                },
            )
            if not _append_rule_if_wrap(world_rules=world_rules, rule_appendices=rule_appendices, rule_payload=rule_payload):
                _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Undefined_Item_Rule", reason="combination is not defined in Fixed mode")
                return
            matching_rule = rule_payload["rule_update"]["payload"]

        removed_items: list[InventoryItemSpec] = []
        for item_id in input_ids:
            removed = _remove_item(actor, item_id, 1)
            if removed is None:
                for restored in removed_items:
                    _add_item(actor, restored)
                _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Item_Unavailable", reason=f"missing item for combination: {item_id}")
                return
            removed_items.append(removed)
        output_item = InventoryItemSpec.model_validate(matching_rule.get("output_item", {}))
        _add_item(actor, output_item)
        mutations["inventory_updates"].append(
            {
                "intent_id": intent.intent_id,
                "operation": "Combine",
                "agent_id": actor.agent_id,
                "inputs": [item.model_dump() for item in removed_items],
                "output": output_item.model_dump(),
            }
        )
        _add_action_result(mutations, intent=intent, status="success", context="Action_Succeeded", reason="item combination completed")
        return

    _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Unknown_Item_Operation", reason=f"unsupported item operation: {operation}")
