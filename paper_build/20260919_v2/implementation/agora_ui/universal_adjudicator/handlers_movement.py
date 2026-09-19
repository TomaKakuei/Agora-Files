from __future__ import annotations

from collections import Counter
from typing import Any, Dict

from agora_ui.adjudicator_schemas import (
    ActionIntentSpec,
    AdjudicatorControlSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    WorldRulesSpec,
)
from .geometry import (
    _coord_key,
    _position_in_shape,
    _room_for_position,
    _walkable_distance,
)
from .utils import _add_action_result, _add_broadcast


def _handle_move(
    *,
    control: AdjudicatorControlSpec,
    world_rules: WorldRulesSpec,
    state: AgentStateBundleSpec,
    agents: Dict[str, AgentRuntimeProfileSpec],
    intent: ActionIntentSpec,
    broadcasts: list[dict[str, Any]],
    mutations: dict[str, Any],
) -> None:
    actor = agents.get(intent.agent_id)
    if actor is None:
        _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Unknown_Agent", reason="actor not found")
        return
    if intent.target_coordinates is None:
        _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Missing_Target", reason="Move requires target_coordinates")
        return
    target = intent.target_coordinates
    if not _position_in_shape(target, world_rules):
        _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Out_Of_Bounds", reason="target is outside topology")
        return
    distance = _walkable_distance(
        actor.coordinates,
        target,
        world_rules,
        max_steps=world_rules.movement.max_steps_per_timestep,
    )
    if distance is None:
        _add_action_result(
            mutations,
            intent=intent,
            status="failed",
            context="Action_Failed_Speed_Limit",
            reason="target exceeds movement speed limit or is blocked by the floorplan",
        )
        return
    occupancy = Counter(_coord_key(agent.coordinates) for agent in agents.values())
    if occupancy[_coord_key(target)] >= world_rules.movement.capacity_per_coordinate and _coord_key(actor.coordinates) != _coord_key(target):
        _add_action_result(mutations, intent=intent, status="failed", context="Action_Failed_Capacity_Limit", reason="target coordinate is at capacity")
        return

    start = actor.coordinates.model_copy(deep=True)
    start_room = actor.room_id
    actor.coordinates = target.model_copy(deep=True)
    actor.room_id = _room_for_position(actor.coordinates, world_rules.topology.rooms)
    mutations["coordinate_updates"].append(
        {
            "intent_id": intent.intent_id,
            "agent_id": actor.agent_id,
            "from": start.model_dump(),
            "to": actor.coordinates.model_dump(),
            "from_room_id": start_room,
            "to_room_id": actor.room_id,
        }
    )
    _add_action_result(mutations, intent=intent, status="success", context="Action_Succeeded", reason="movement validated")
    _add_broadcast(
        broadcasts=broadcasts,
        agents=agents,
        room_id=actor.room_id,
        coordinate=actor.coordinates,
        message=f"{actor.display_name or actor.agent_id} moved to {actor.room_id}.",
        intent_id=intent.intent_id,
    )
