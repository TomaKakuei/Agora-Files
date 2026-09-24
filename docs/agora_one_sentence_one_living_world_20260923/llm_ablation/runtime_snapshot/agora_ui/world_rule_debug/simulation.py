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
from .pathing import _build_room_adjacency
from .decision import _plan_decision_for_agent

def _ordered_active_agents(compiled: CompiledWorldSpec) -> List[CompiledWorldAgent]:
    active_agents = [item for item in compiled.agents if item.active]
    if compiled.world.turn_order == "agent_id":
        return sorted(active_agents, key=lambda item: item.agent_id)
    return active_agents

def _build_snapshot_payload(
    *,
    compiled: CompiledWorldSpec,
    runtime_rooms: Dict[str, str],
    runtime_positions: Dict[str, GridPosition],
    round_index: int,
    clock_time: str,
) -> Dict[str, Any]:
    return {
        "round_index": round_index,
        "clock_time": clock_time,
        "agents": [
            {
                "agent_id": agent.agent_id,
                "room_id": runtime_rooms[agent.agent_id],
                "coordinate": runtime_positions[agent.agent_id].model_dump(),
                "active": agent.active,
            }
            for agent in compiled.agents
        ],
    }

def _trace_from_idle_agent(
    *,
    compiled: CompiledWorldSpec,
    agent: CompiledWorldAgent,
    round_index: int,
    clock_time: str,
    current_room_id: str,
    current_position: GridPosition,
    reason: str,
    note: str,
    status: str,
) -> WorldRuleTraceRecord:
    return WorldRuleTraceRecord(
        round_index=round_index,
        clock_time=clock_time,
        agent_id=agent.agent_id,
        active=agent.active,
        movement_mode=compiled.world.movement_mode,
        decision_backend=compiled.control.decision.backend,
        decision_status=status,
        decision_reason=reason,
        basis=agent.movement_policy.basis,
        steps_requested=0,
        steps_executed=0,
        blocked_steps=0,
        start_room_id=current_room_id,
        end_room_id=current_room_id,
        requested_target_room_id=None,
        start_coordinate=current_position.model_copy(deep=True),
        end_coordinate=current_position.model_copy(deep=True),
        visited_room_ids=[current_room_id],
        note=note,
    )

def _idle_status_from_decision(decision: MovementDecision) -> str:
    if decision.decision_status in {"idle", "blocked"}:
        return decision.decision_status
    return "idle"

def _trace_from_decision_result(
    *,
    compiled: CompiledWorldSpec,
    agent: CompiledWorldAgent,
    round_index: int,
    clock_time: str,
    decision: MovementDecision,
    decision_status: str,
    start_room_id: str,
    start_position: GridPosition,
    end_room_id: str,
    end_position: GridPosition,
    steps_executed: int,
    blocked_steps: int,
    visited_room_ids: List[str],
    note: str,
) -> WorldRuleTraceRecord:
    """Create the trace row emitted for a planner decision."""

    return WorldRuleTraceRecord(
        round_index=round_index,
        clock_time=clock_time,
        agent_id=agent.agent_id,
        active=True,
        movement_mode=compiled.world.movement_mode,
        decision_backend=decision.decision_backend,
        decision_status=decision_status,
        decision_reason=decision.decision_reason,
        basis=agent.movement_policy.basis,
        steps_requested=decision.requested_steps,
        steps_executed=steps_executed,
        blocked_steps=blocked_steps,
        start_room_id=start_room_id,
        end_room_id=end_room_id,
        requested_target_room_id=decision.requested_target_room_id,
        start_coordinate=start_position.model_copy(deep=True),
        end_coordinate=end_position.model_copy(deep=True),
        visited_room_ids=visited_room_ids,
        note=note,
    )

def _trace_from_unmoved_decision(
    *,
    compiled: CompiledWorldSpec,
    agent: CompiledWorldAgent,
    round_index: int,
    clock_time: str,
    decision: MovementDecision,
    start_room_id: str,
    start_position: GridPosition,
    decision_status: str,
    note: str,
) -> WorldRuleTraceRecord:
    return _trace_from_decision_result(
        compiled=compiled,
        agent=agent,
        round_index=round_index,
        clock_time=clock_time,
        decision=decision,
        decision_status=decision_status,
        start_room_id=start_room_id,
        start_position=start_position,
        end_room_id=start_room_id,
        end_position=start_position,
        steps_executed=0,
        blocked_steps=decision.requested_steps,
        visited_room_ids=[start_room_id],
        note=note,
    )

def _trace_from_move_decision(
    *,
    compiled: CompiledWorldSpec,
    agent: CompiledWorldAgent,
    round_index: int,
    clock_time: str,
    decision: MovementDecision,
    start_room_id: str,
    start_position: GridPosition,
    target_room_id: str,
    end_position: GridPosition,
) -> WorldRuleTraceRecord:
    return _trace_from_decision_result(
        compiled=compiled,
        agent=agent,
        round_index=round_index,
        clock_time=clock_time,
        decision=decision,
        decision_status="moved",
        start_room_id=start_room_id,
        start_position=start_position,
        end_room_id=target_room_id,
        end_position=end_position,
        steps_executed=decision.requested_steps,
        blocked_steps=0,
        visited_room_ids=list(decision.path_room_ids or [start_room_id, target_room_id]),
        note=decision.note,
    )

def _build_initial_runtime_state(
    compiled: CompiledWorldSpec,
) -> Tuple[RuntimeRooms, RuntimePositions]:
    runtime_positions = {
        agent.agent_id: agent.initial_coordinate.model_copy(deep=True)
        for agent in compiled.agents
    }
    runtime_rooms = {
        agent.agent_id: agent.initial_room_id
        for agent in compiled.agents
    }
    return runtime_rooms, runtime_positions

def _resolved_decision_concurrency(
    compiled: CompiledWorldSpec,
    active_agents: List[CompiledWorldAgent],
) -> int:
    resolved_concurrency = compiled.control.decision.concurrency_limit
    if resolved_concurrency <= 0:
        return max(1, min(10, len(active_agents) or 1))
    return resolved_concurrency

def _select_single_round_agent(
    active_agents: List[CompiledWorldAgent],
    round_index: int,
) -> Optional[CompiledWorldAgent]:
    if not active_agents:
        return None
    return active_agents[(round_index - 1) % len(active_agents)]

async def _plan_single_round_decision(
    *,
    compiled: CompiledWorldSpec,
    selected_agent: Optional[CompiledWorldAgent],
    round_index: int,
    clock_time: str,
    runtime_rooms: RuntimeRooms,
    runtime_positions: RuntimePositions,
    occupancy_snapshot: Counter,
    rooms_by_id: Dict[str, CompiledRoomSpec],
    rooms_by_coord: Dict[CoordKey, CompiledRoomSpec],
    room_adjacency: RoomAdjacency,
    async_client: Optional[AsyncFlexClient],
    rng: random.Random,
) -> Optional[MovementDecision]:
    if selected_agent is None:
        return None
    return await _plan_decision_for_agent(
        compiled=compiled,
        agent=selected_agent,
        round_index=round_index,
        clock_time=clock_time,
        current_room_id=runtime_rooms[selected_agent.agent_id],
        current_position=runtime_positions[selected_agent.agent_id],
        occupancy_snapshot=occupancy_snapshot,
        rooms_by_id=rooms_by_id,
        rooms_by_coord=rooms_by_coord,
        room_adjacency=room_adjacency,
        async_client=async_client,
        rng=rng,
    )

def _settle_single_round(
    *,
    compiled: CompiledWorldSpec,
    round_index: int,
    clock_time: str,
    runtime_rooms: RuntimeRooms,
    runtime_positions: RuntimePositions,
    selected_agent: Optional[CompiledWorldAgent],
    decision: Optional[MovementDecision],
) -> Tuple[List[WorldRuleTraceRecord], Dict[str, Any]]:
    traces: List[WorldRuleTraceRecord] = []

    for agent in compiled.agents:
        current_room_id = runtime_rooms[agent.agent_id]
        current_position = runtime_positions[agent.agent_id].model_copy(deep=True)
        if not agent.active:
            traces.append(
                _trace_from_idle_agent(
                    compiled=compiled,
                    agent=agent,
                    round_index=round_index,
                    clock_time=clock_time,
                    current_room_id=current_room_id,
                    current_position=current_position,
                    reason="inactive_agent",
                    note="inactive_agent",
                    status="inactive",
                )
            )
            continue

        if selected_agent is None or agent.agent_id != selected_agent.agent_id:
            traces.append(
                _trace_from_idle_agent(
                    compiled=compiled,
                    agent=agent,
                    round_index=round_index,
                    clock_time=clock_time,
                    current_room_id=current_room_id,
                    current_position=current_position,
                    reason="waiting_turn",
                    note="waiting_turn",
                    status="idle",
                )
            )
            continue

        assert decision is not None
        if decision.requested_action == "move" and decision.requested_target_room_id:
            target_room_id = decision.requested_target_room_id
            runtime_rooms[agent.agent_id] = target_room_id
            if decision.target_coordinate is not None:
                runtime_positions[agent.agent_id] = (
                    decision.target_coordinate.model_copy(deep=True)
                )
            traces.append(
                _trace_from_move_decision(
                    compiled=compiled,
                    agent=agent,
                    round_index=round_index,
                    clock_time=clock_time,
                    decision=decision,
                    start_room_id=current_room_id,
                    start_position=current_position,
                    target_room_id=target_room_id,
                    end_position=runtime_positions[agent.agent_id],
                )
            )
            continue

        traces.append(
            _trace_from_unmoved_decision(
                compiled=compiled,
                agent=agent,
                round_index=round_index,
                clock_time=clock_time,
                decision=decision,
                start_room_id=current_room_id,
                start_position=current_position,
                decision_status=_idle_status_from_decision(decision),
                note=decision.note or "selected_agent_idle",
            )
        )

    summary = {
        "round_index": round_index,
        "clock_time_before": clock_time,
        "movement_mode": compiled.world.movement_mode,
        "decision_backend": compiled.control.decision.backend,
        "selected_agent_id": selected_agent.agent_id if selected_agent is not None else "",
    }
    return traces, summary

async def _plan_multi_round_decisions(
    *,
    compiled: CompiledWorldSpec,
    round_index: int,
    clock_time: str,
    runtime_rooms: RuntimeRooms,
    runtime_positions: RuntimePositions,
    active_agents: List[CompiledWorldAgent],
    occupancy_snapshot: Counter,
    rooms_by_id: Dict[str, CompiledRoomSpec],
    rooms_by_coord: Dict[CoordKey, CompiledRoomSpec],
    room_adjacency: RoomAdjacency,
    async_client: Optional[AsyncFlexClient],
    rng: random.Random,
) -> Dict[str, MovementDecision]:
    decision_tasks = [
        _plan_decision_for_agent(
            compiled=compiled,
            agent=agent,
            round_index=round_index,
            clock_time=clock_time,
            current_room_id=runtime_rooms[agent.agent_id],
            current_position=runtime_positions[agent.agent_id],
            occupancy_snapshot=occupancy_snapshot,
            rooms_by_id=rooms_by_id,
            rooms_by_coord=rooms_by_coord,
            room_adjacency=room_adjacency,
            async_client=async_client,
            rng=rng,
        )
        for agent in active_agents
    ]
    decision_results = (
        await asyncio.gather(*decision_tasks)
        if decision_tasks
        else []
    )
    decisions: Dict[str, MovementDecision] = {}
    for agent, result in zip(active_agents, decision_results):
        decisions[result.agent_id] = result
    return decisions

def _settle_multi_round(
    *,
    compiled: CompiledWorldSpec,
    round_index: int,
    clock_time: str,
    runtime_rooms: RuntimeRooms,
    runtime_positions: RuntimePositions,
    active_agents: List[CompiledWorldAgent],
    decisions: Dict[str, MovementDecision],
) -> Tuple[List[WorldRuleTraceRecord], Dict[str, Any]]:
    """Apply same-snapshot movement decisions in deterministic agent_id order."""

    occupancy = Counter(runtime_rooms.values())
    traces: List[WorldRuleTraceRecord] = []
    moved_agents: List[str] = []
    idle_agents: List[str] = []
    resolution_order = sorted(active_agents, key=lambda item: item.agent_id)

    for agent in compiled.agents:
        if not agent.active:
            traces.append(
                _trace_from_idle_agent(
                    compiled=compiled,
                    agent=agent,
                    round_index=round_index,
                    clock_time=clock_time,
                    current_room_id=runtime_rooms[agent.agent_id],
                    current_position=runtime_positions[agent.agent_id],
                    reason="inactive_agent",
                    note="inactive_agent",
                    status="inactive",
                )
            )

    capacity = compiled.world.occupancy_policy.max_agents_per_room
    for agent in resolution_order:
        decision = decisions[agent.agent_id]
        start_room_id = runtime_rooms[agent.agent_id]
        start_position = runtime_positions[agent.agent_id].model_copy(deep=True)

        if decision.requested_action != "move" or not decision.requested_target_room_id:
            idle_agents.append(agent.agent_id)
            traces.append(
                _trace_from_unmoved_decision(
                    compiled=compiled,
                    agent=agent,
                    round_index=round_index,
                    clock_time=clock_time,
                    decision=decision,
                    start_room_id=start_room_id,
                    start_position=start_position,
                    decision_status=_idle_status_from_decision(decision),
                    note=decision.note or "idle_after_decision",
                )
            )
            continue

        target_room_id = decision.requested_target_room_id
        if occupancy[target_room_id] >= capacity:
            idle_agents.append(agent.agent_id)
            traces.append(
                _trace_from_unmoved_decision(
                    compiled=compiled,
                    agent=agent,
                    round_index=round_index,
                    clock_time=clock_time,
                    decision=decision,
                    decision_status="conflict_lost",
                    start_room_id=start_room_id,
                    start_position=start_position,
                    note="target occupied during conflict resolution",
                )
            )
            continue

        occupancy[start_room_id] -= 1
        if occupancy[start_room_id] <= 0:
            occupancy.pop(start_room_id, None)
        occupancy[target_room_id] += 1
        runtime_rooms[agent.agent_id] = target_room_id
        runtime_positions[agent.agent_id] = (
            decision.target_coordinate.model_copy(deep=True)
            if decision.target_coordinate is not None
            else runtime_positions[agent.agent_id]
        )
        moved_agents.append(agent.agent_id)
        traces.append(
            _trace_from_move_decision(
                compiled=compiled,
                agent=agent,
                round_index=round_index,
                clock_time=clock_time,
                decision=decision,
                start_room_id=start_room_id,
                start_position=start_position,
                target_room_id=target_room_id,
                end_position=runtime_positions[agent.agent_id],
            )
        )

    summary = {
        "round_index": round_index,
        "clock_time_before": clock_time,
        "movement_mode": compiled.world.movement_mode,
        "decision_backend": compiled.control.decision.backend,
        "resolved_agent_count": len(active_agents),
        "resolution_order": [item.agent_id for item in resolution_order],
        "moved_agents": moved_agents,
        "idle_agents": idle_agents,
    }
    return traces, summary

async def _simulate_world(
    compiled: CompiledWorldSpec,
) -> Tuple[List[WorldRuleTraceRecord], List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """Run the compiled world and collect trace, summary, and snapshot payloads."""

    rng = random.Random(compiled.control.seed)
    rooms_by_id = {room.room_id: room for room in compiled.rooms}
    rooms_by_coord = {_coord_key(room.coordinate): room for room in compiled.rooms}
    room_adjacency = _build_room_adjacency(rooms_by_id)

    runtime_rooms, runtime_positions = _build_initial_runtime_state(compiled)
    active_agents = _ordered_active_agents(compiled)

    async_client: Optional[AsyncFlexClient] = None
    if compiled.control.decision.backend == "flex":
        async_client = AsyncFlexClient(
            api_url=compiled.control.decision.flex_api_url,
            concurrency_limit=_resolved_decision_concurrency(compiled, active_agents),
        )

    traces: List[WorldRuleTraceRecord] = []
    snapshots: List[Dict[str, Any]] = []
    round_summaries: List[Dict[str, Any]] = []
    current_clock_minutes = _time_to_minutes(compiled.control.clock.initial_time)

    try:
        snapshots.append(
            _build_snapshot_payload(
                compiled=compiled,
                runtime_rooms=runtime_rooms,
                runtime_positions=runtime_positions,
                round_index=0,
                clock_time=_minutes_to_time(current_clock_minutes),
            )
        )
        for round_index in range(1, compiled.control.rounds + 1):
            clock_time_before = _minutes_to_time(current_clock_minutes)
            occupancy_snapshot = Counter(runtime_rooms.values())

            if compiled.world.movement_mode == "single":
                selected_agent = _select_single_round_agent(active_agents, round_index)
                decision = await _plan_single_round_decision(
                    compiled=compiled,
                    selected_agent=selected_agent,
                    round_index=round_index,
                    clock_time=clock_time_before,
                    runtime_rooms=runtime_rooms,
                    runtime_positions=runtime_positions,
                    occupancy_snapshot=occupancy_snapshot,
                    rooms_by_id=rooms_by_id,
                    rooms_by_coord=rooms_by_coord,
                    room_adjacency=room_adjacency,
                    async_client=async_client,
                    rng=rng,
                )
                round_traces, round_summary = _settle_single_round(
                    compiled=compiled,
                    round_index=round_index,
                    clock_time=clock_time_before,
                    runtime_rooms=runtime_rooms,
                    runtime_positions=runtime_positions,
                    selected_agent=selected_agent,
                    decision=decision,
                )
                traces.extend(round_traces)
            else:
                decisions = await _plan_multi_round_decisions(
                    compiled=compiled,
                    round_index=round_index,
                    clock_time=clock_time_before,
                    runtime_rooms=runtime_rooms,
                    runtime_positions=runtime_positions,
                    active_agents=active_agents,
                    occupancy_snapshot=occupancy_snapshot,
                    rooms_by_id=rooms_by_id,
                    rooms_by_coord=rooms_by_coord,
                    room_adjacency=room_adjacency,
                    async_client=async_client,
                    rng=rng,
                )
                round_traces, round_summary = _settle_multi_round(
                    compiled=compiled,
                    round_index=round_index,
                    clock_time=clock_time_before,
                    runtime_rooms=runtime_rooms,
                    runtime_positions=runtime_positions,
                    active_agents=active_agents,
                    decisions=decisions,
                )
                traces.extend(round_traces)

            current_clock_minutes += compiled.control.clock.step_minutes
            clock_time_after = _minutes_to_time(current_clock_minutes)
            round_summary["clock_time_after"] = clock_time_after
            round_summary["active_agent_count"] = len(active_agents)
            round_summaries.append(round_summary)
            snapshots.append(
                _build_snapshot_payload(
                    compiled=compiled,
                    runtime_rooms=runtime_rooms,
                    runtime_positions=runtime_positions,
                    round_index=round_index,
                    clock_time=clock_time_after,
                )
            )
    finally:
        if async_client is not None:
            async_client.close()

    return traces, snapshots, round_summaries, _minutes_to_time(current_clock_minutes)
