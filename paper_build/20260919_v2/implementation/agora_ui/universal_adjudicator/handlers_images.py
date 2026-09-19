from __future__ import annotations

from typing import Any, Dict

from agora_ui.adjudicator_schemas import (
    ActionIntentSpec,
    AdjudicatorControlSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    WorldRulesSpec,
)
from .geometry import _coord_text
from .utils import (
    _add_action_result,
    _add_broadcast,
    _rule_update,
    _append_rule_if_wrap,
)


def _handle_image(
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
    if not world_rules.image_rules.enabled:
        _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Image_Disabled", reason="image rules are disabled")
        return

    operation = (intent.operation or intent.metadata.get("operation") or "create").strip().lower()
    if operation not in {item.lower() for item in world_rules.image_rules.allowed_operations}:
        rule_payload = _rule_update(
            timestep_index=control.timestep_index,
            intent=intent,
            module="Image",
            rule_type="image_operation",
            description=f"Undefined image operation '{operation}' is plausible and now mutates localized visual state.",
            payload={"operation": operation, "scope": "current_coordinate"},
        )
        if not _append_rule_if_wrap(world_rules=world_rules, rule_appendices=rule_appendices, rule_payload=rule_payload):
            _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Undefined_Image_Rule", reason="image operation is not defined in Fixed mode")
            return

    coord_key = _coord_text(actor.coordinates)
    visual_event = {
        "intent_id": intent.intent_id,
        "agent_id": actor.agent_id,
        "operation": operation,
        "api_prompt": intent.api_prompt or intent.intent_text,
        "coordinate": actor.coordinates.model_dump(),
        "room_id": actor.room_id,
        "image_path": str(intent.metadata.get("image_path", "")),
        "image_mime_type": str(intent.metadata.get("image_mime_type", "")),
        "image_source": str(intent.metadata.get("image_source", "")),
        "image_job_id": str(intent.metadata.get("image_job_id", "")),
    }
    state.localized_visual_state.setdefault(coord_key, []).append(visual_event)
    mutations["visual_state_updates"].append(visual_event)
    _add_action_result(mutations, intent=intent, status="success", context="Action_Succeeded", reason="localized visual state updated")
    _add_broadcast(
        broadcasts=broadcasts,
        agents=agents,
        room_id=actor.room_id,
        coordinate=actor.coordinates,
        message=f"{actor.display_name or actor.agent_id} changed the local visual state via {operation}.",
        intent_id=intent.intent_id,
    )
