from __future__ import annotations
import argparse
import asyncio
import json
import random
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ..flex_client import AsyncFlexClient
from ..foundation_schemas import (
    CompiledRoomSpec,
    CompiledWorldAgent,
    CompiledWorldSpec,
    GridPosition,
    GridShape,
    MovementPolicy,
    RoomSpec,
    WorldAgentSpec,
    WorldAgentsSpec,
    WorldControlSpec,
    WorldRuleDebugManifest,
    WorldRuleTraceRecord,
    WorldSpec,
)
from ..jsonc_utils import dump_json, load_jsonc_path

from .core import *
from .pathing import _enumerate_reachable_targets

def _heuristic_decision(
    rng: random.Random,
    agent: CompiledWorldAgent,
    candidates: List[ReachableTarget],
) -> MovementDecision:
    if not candidates:
        return MovementDecision(
            agent_id=agent.agent_id,
            decision_backend="heuristic",
            requested_action="idle",
            decision_status="blocked",
            decision_reason="no reachable target under current policy",
            note="no_candidates",
        )
    chosen = rng.choice(candidates)
    return MovementDecision(
        agent_id=agent.agent_id,
        decision_backend="heuristic",
        requested_action="move",
        decision_status="proposed",
        decision_reason="heuristic_choice",
        requested_target_room_id=chosen.room_id,
        target_coordinate=chosen.coordinate.model_copy(deep=True),
        requested_steps=chosen.steps,
        path_room_ids=list(chosen.path_room_ids),
    )

def _build_decision_prompt(
    *,
    compiled: CompiledWorldSpec,
    agent: CompiledWorldAgent,
    round_index: int,
    clock_time: str,
    current_room_id: str,
    current_position: GridPosition,
    candidates: List[ReachableTarget],
) -> str:
    candidate_payload = [
        {
            "room_id": item.room_id,
            "room_name": item.room_name,
            "coordinate": item.coordinate.model_dump(),
            "steps": item.steps,
            "path_room_ids": item.path_room_ids,
            "axis_usage": item.axis_usage,
        }
        for item in candidates
    ]
    return (
        "Decide one movement action for this agent.\n"
        f"world_id: {compiled.world.world_id}\n"
        f"movement_mode: {compiled.world.movement_mode}\n"
        f"round_index: {round_index}\n"
        f"clock_time: {clock_time}\n"
        f"world_summary: {compiled.world.world_summary}\n"
        f"world_rules: {compiled.world.world_rules}\n"
        f"agent_id: {agent.agent_id}\n"
        f"display_name: {agent.display_name}\n"
        f"current_room_id: {current_room_id}\n"
        f"current_coordinate: {current_position.model_dump()}\n"
        f"movement_policy: {agent.movement_policy.model_dump()}\n"
        f"candidate_targets: {json.dumps(candidate_payload, ensure_ascii=False)}\n\n"
        "Return JSON only with keys:\n"
        '{"action":"move|idle","target_room_id":"string","reason":"string"}\n'
        "Rules:\n"
        "- `action` must be `move` or `idle`.\n"
        "- If `action` is `move`, `target_room_id` must be exactly one room_id from candidate_targets.\n"
        "- If `action` is `idle`, set `target_room_id` to an empty string.\n"
        "- Keep `reason` short and concrete.\n"
    )

async def _flex_decision(
    client: AsyncFlexClient,
    *,
    compiled: CompiledWorldSpec,
    agent: CompiledWorldAgent,
    round_index: int,
    clock_time: str,
    current_room_id: str,
    current_position: GridPosition,
    candidates: List[ReachableTarget],
) -> MovementDecision:
    if not candidates:
        return MovementDecision(
            agent_id=agent.agent_id,
            decision_backend="flex",
            requested_action="idle",
            decision_status="blocked",
            decision_reason="no reachable target under current policy",
            note="no_candidates",
        )

    schema_hint = {
        "action": "move|idle",
        "target_room_id": "string",
        "reason": "string",
    }
    prompt = _build_decision_prompt(
        compiled=compiled,
        agent=agent,
        round_index=round_index,
        clock_time=clock_time,
        current_room_id=current_room_id,
        current_position=current_position,
        candidates=candidates,
    )
    payload = await client.generate_json(
        prompt=prompt,
        system_instruction=(
            "You are a strict movement planner for a simulated world. "
            "Return JSON only with no markdown fences."
        ),
        model=compiled.control.decision.model or None,
        temperature=compiled.control.decision.temperature,
        max_output_tokens=compiled.control.decision.max_output_tokens,
        thinking_level=compiled.control.decision.thinking_level,
        response_schema=schema_hint,
        timeout_seconds=compiled.control.decision.request_timeout_seconds,
    )

    action = str(payload.get("action", "")).strip().lower()
    target_room_id = str(payload.get("target_room_id", "")).strip()
    reason = str(payload.get("reason", "")).strip() or "flex_planner"
    candidate_by_room = {item.room_id: item for item in candidates}
    if action != "move":
        return MovementDecision(
            agent_id=agent.agent_id,
            decision_backend="flex",
            requested_action="idle",
            decision_status="idle",
            decision_reason=reason or "planner_idle",
            note="model_idle",
        )
    chosen = candidate_by_room.get(target_room_id)
    if chosen is None:
        raise ValueError(f"invalid target_room_id '{target_room_id}' for {agent.agent_id}")
    return MovementDecision(
        agent_id=agent.agent_id,
        decision_backend="flex",
        requested_action="move",
        decision_status="proposed",
        decision_reason=reason,
        requested_target_room_id=chosen.room_id,
        target_coordinate=chosen.coordinate.model_copy(deep=True),
        requested_steps=chosen.steps,
        path_room_ids=list(chosen.path_room_ids),
    )

async def _plan_decision_for_agent(
    *,
    compiled: CompiledWorldSpec,
    agent: CompiledWorldAgent,
    round_index: int,
    clock_time: str,
    current_room_id: str,
    current_position: GridPosition,
    occupancy_snapshot: Counter,
    rooms_by_id: Dict[str, CompiledRoomSpec],
    rooms_by_coord: Dict[CoordKey, CompiledRoomSpec],
    room_adjacency: RoomAdjacency,
    async_client: Optional[AsyncFlexClient],
    rng: random.Random,
) -> MovementDecision:
    occupancy_without_self = Counter(occupancy_snapshot)
    occupancy_without_self[current_room_id] -= 1
    if occupancy_without_self[current_room_id] <= 0:
        occupancy_without_self.pop(current_room_id, None)

    candidates = _enumerate_reachable_targets(
        start_room_id=current_room_id,
        start_position=current_position,
        policy=agent.movement_policy,
        shape=compiled.world.topology.grid_shape,
        rooms_by_id=rooms_by_id,
        rooms_by_coord=rooms_by_coord,
        room_adjacency=room_adjacency,
        occupancy_without_self=occupancy_without_self,
        max_agents_per_room=compiled.world.occupancy_policy.max_agents_per_room,
    )

    if compiled.control.decision.backend == "flex":
        if async_client is None:
            raise RuntimeError("flex backend selected but AsyncFlexClient is not available")
        return await _flex_decision(
            async_client,
            compiled=compiled,
            agent=agent,
            round_index=round_index,
            clock_time=clock_time,
            current_room_id=current_room_id,
            current_position=current_position,
            candidates=candidates,
        )

    return _heuristic_decision(rng, agent, candidates)
