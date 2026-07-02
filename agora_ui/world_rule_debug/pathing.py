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

def _position_in_shape(position: GridPosition, shape: GridShape) -> bool:
    return (
        0 <= position.x < shape.x
        and 0 <= position.y < shape.y
        and 0 <= position.z < shape.z
    )

def _manhattan_distance(a: GridPosition, b: GridPosition) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y) + abs(a.z - b.z)

def _build_room_adjacency(
    rooms_by_id: Dict[str, CompiledRoomSpec],
) -> RoomAdjacency:
    """Build room-to-room edges for sparse topologies."""

    adjacency: RoomAdjacency = {
        room_id: [] for room_id in rooms_by_id
    }
    items = list(rooms_by_id.values())
    for room in items:
        for other in items:
            if room.room_id == other.room_id:
                continue
            if _manhattan_distance(room.coordinate, other.coordinate) != 1:
                continue
            if other.coordinate.x != room.coordinate.x:
                axis = "x"
            elif other.coordinate.y != room.coordinate.y:
                axis = "y"
            else:
                axis = "z"
            adjacency[room.room_id].append(
                (other.room_id, other.coordinate.model_copy(deep=True), axis)
            )
    return adjacency

def _expand_neighbors(
    *,
    room_id: str,
    position: GridPosition,
    policy: MovementPolicy,
    shape: GridShape,
    rooms_by_coord: Dict[CoordKey, CompiledRoomSpec],
    room_adjacency: RoomAdjacency,
    occupancy_without_self: Counter,
    max_agents_per_room: int,
    axis_usage: Dict[str, int],
) -> List[Tuple[str, GridPosition, str]]:
    """Return one-step legal moves after applying axis and occupancy limits."""

    neighbors: List[Tuple[str, GridPosition, str]] = []
    axis_limits = {
        "x": policy.axis_step_budget.x,
        "y": policy.axis_step_budget.y,
        "z": policy.axis_step_budget.z,
    }

    if policy.basis == "grid":
        deltas = {
            "x": ((1, 0, 0), (-1, 0, 0)),
            "y": ((0, 1, 0), (0, -1, 0)),
            "z": ((0, 0, 1), (0, 0, -1)),
        }
        for axis, moves in deltas.items():
            if axis_usage.get(axis, 0) >= axis_limits[axis]:
                continue
            for dx, dy, dz in moves:
                next_x = position.x + dx
                next_y = position.y + dy
                next_z = position.z + dz
                if min(next_x, next_y, next_z) < 0:
                    continue
                candidate = GridPosition(x=next_x, y=next_y, z=next_z)
                if not _position_in_shape(candidate, shape):
                    continue
                room = rooms_by_coord.get(_coord_key(candidate))
                if room is None:
                    continue
                if occupancy_without_self[room.room_id] >= max_agents_per_room:
                    continue
                neighbors.append((room.room_id, candidate, axis))
        return neighbors

    for next_room_id, next_coordinate, axis in room_adjacency.get(room_id, []):
        if axis_usage.get(axis, 0) >= axis_limits[axis]:
            continue
        if occupancy_without_self[next_room_id] >= max_agents_per_room:
            continue
        neighbors.append(
            (
                next_room_id,
                next_coordinate.model_copy(deep=True),
                axis,
            )
        )
    return neighbors

def _enumerate_reachable_targets(
    *,
    start_room_id: str,
    start_position: GridPosition,
    policy: MovementPolicy,
    shape: GridShape,
    rooms_by_id: Dict[str, CompiledRoomSpec],
    rooms_by_coord: Dict[CoordKey, CompiledRoomSpec],
    room_adjacency: RoomAdjacency,
    occupancy_without_self: Counter,
    max_agents_per_room: int,
) -> List[ReachableTarget]:
    """Breadth-first search over legal movement states for one agent."""

    if policy.max_steps <= 0:
        return []

    queue = deque(
        [
            (
                start_room_id,
                start_position.model_copy(deep=True),
                0,
                {"x": 0, "y": 0, "z": 0},
                [start_room_id],
            )
        ]
    )
    seen: set[Tuple[str, int, int, int, int]] = set()
    seen.add((start_room_id, 0, 0, 0, 0))
    best_by_room: Dict[str, ReachableTarget] = {}

    while queue:
        room_id, position, steps_used, axis_usage, path_room_ids = queue.popleft()

        if steps_used >= policy.min_steps and room_id != start_room_id:
            current_target = best_by_room.get(room_id)
            if current_target is None or steps_used < current_target.steps:
                room = rooms_by_id[room_id]
                best_by_room[room_id] = ReachableTarget(
                    room_id=room_id,
                    room_name=room.name,
                    coordinate=room.coordinate.model_copy(deep=True),
                    steps=steps_used,
                    path_room_ids=list(path_room_ids),
                    axis_usage=dict(axis_usage),
                )

        if steps_used >= policy.max_steps:
            continue

        neighbors = _expand_neighbors(
            room_id=room_id,
            position=position,
            policy=policy,
            shape=shape,
            rooms_by_coord=rooms_by_coord,
            room_adjacency=room_adjacency,
            occupancy_without_self=occupancy_without_self,
            max_agents_per_room=max_agents_per_room,
            axis_usage=axis_usage,
        )
        for next_room_id, next_position, axis in neighbors:
            next_axis_usage = dict(axis_usage)
            next_axis_usage[axis] = next_axis_usage.get(axis, 0) + 1
            state_key = (
                next_room_id,
                steps_used + 1,
                next_axis_usage.get("x", 0),
                next_axis_usage.get("y", 0),
                next_axis_usage.get("z", 0),
            )
            if state_key in seen:
                continue
            seen.add(state_key)
            queue.append(
                (
                    next_room_id,
                    next_position.model_copy(deep=True),
                    steps_used + 1,
                    next_axis_usage,
                    [*path_room_ids, next_room_id],
                )
            )

    results = list(best_by_room.values())
    results.sort(key=lambda item: (item.steps, item.room_id))
    return results
