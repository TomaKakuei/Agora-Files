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

def _room_sort_key(room: CompiledRoomSpec) -> Tuple[int, int, int, str]:
    return (room.coordinate.z, room.coordinate.y, room.coordinate.x, room.room_id)

def _load_world(path: Path) -> WorldSpec:
    payload = load_jsonc_path(path)
    return WorldSpec.model_validate(payload)

def _load_world_agents(path: Path) -> WorldAgentsSpec:
    payload = load_jsonc_path(path)
    return WorldAgentsSpec.model_validate(payload)

def _load_world_control(path: Path) -> WorldControlSpec:
    payload = load_jsonc_path(path)
    return WorldControlSpec.model_validate(payload)

def _build_rooms(
    world: WorldSpec,
    control: WorldControlSpec,
) -> Tuple[List[CompiledRoomSpec], GridShape, Dict[str, Any]]:
    """Resolve either an implicit full grid or an explicit sparse room list."""

    diagnostics: Dict[str, Any] = {}
    shape = world.topology.grid_shape.model_copy(deep=True)
    rooms: List[CompiledRoomSpec] = []
    coord_to_room: Dict[CoordKey, CompiledRoomSpec] = {}
    room_id_set: set[str] = set()
    prefix = str(control.default_room_name_prefix or "room").strip() or "room"

    if world.topology.topology_mode == "grid":
        overrides: Dict[CoordKey, RoomSpec] = {}
        for item in world.topology.rooms:
            overrides[(item.x, item.y, item.z)] = item

        room_index = 1
        for z in range(shape.z):
            for y in range(shape.y):
                for x in range(shape.x):
                    override = overrides.get((x, y, z))
                    room_id = (
                        str(override.room_id).strip()
                        if override is not None and str(override.room_id).strip()
                        else f"{prefix}_{room_index:03d}"
                    )
                    name = (
                        str(override.name).strip()
                        if override is not None and str(override.name).strip()
                        else f"{prefix} {room_index:03d}"
                    )
                    if room_id in room_id_set:
                        raise ValueError(f"duplicate room_id: {room_id}")
                    room = CompiledRoomSpec(
                        room_id=room_id,
                        name=name,
                        coordinate=GridPosition(x=x, y=y, z=z),
                    )
                    room_id_set.add(room_id)
                    coord_to_room[(x, y, z)] = room
                    rooms.append(room)
                    room_index += 1
        return rooms, shape, diagnostics

    raw_rooms = world.topology.rooms
    if not raw_rooms:
        raise ValueError("topology_mode='rooms' requires a non-empty rooms list")

    max_x = max(item.x for item in raw_rooms)
    max_y = max(item.y for item in raw_rooms)
    max_z = max(item.z for item in raw_rooms)
    expanded = False
    if shape.x <= max_x:
        shape.x = max_x + 1
        expanded = True
    if shape.y <= max_y:
        shape.y = max_y + 1
        expanded = True
    if shape.z <= max_z:
        shape.z = max_z + 1
        expanded = True
    if expanded:
        diagnostics["grid_shape_expanded"] = shape.model_dump()

    for index, item in enumerate(raw_rooms, start=1):
        room_id = str(item.room_id).strip() or f"{prefix}_{index:03d}"
        name = str(item.name).strip() or f"{prefix} {index:03d}"
        if room_id in room_id_set:
            raise ValueError(f"duplicate room_id: {room_id}")
        room = CompiledRoomSpec(
            room_id=room_id,
            name=name,
            coordinate=GridPosition(x=item.x, y=item.y, z=item.z),
        )
        key = _coord_key(room.coordinate)
        if key in coord_to_room:
            raise ValueError(
                f"duplicate room coordinate: ({room.coordinate.x}, {room.coordinate.y}, {room.coordinate.z})"
            )
        room_id_set.add(room_id)
        coord_to_room[key] = room
        rooms.append(room)

    rooms.sort(key=_room_sort_key)
    return rooms, shape, diagnostics

def _resolve_initial_room(
    spec: WorldAgentSpec,
    rooms_by_id: Dict[str, CompiledRoomSpec],
    rooms_by_coord: Dict[CoordKey, CompiledRoomSpec],
    room_order: List[CompiledRoomSpec],
    used_counts: Counter,
    max_agents_per_room: int,
) -> CompiledRoomSpec:
    if spec.initial_room_id:
        room = rooms_by_id.get(spec.initial_room_id)
        if room is None:
            raise ValueError(
                f"unknown initial_room_id '{spec.initial_room_id}' for agent {spec.agent_id}"
            )
        return room
    if spec.initial_coordinate is not None:
        room = rooms_by_coord.get(_coord_key(spec.initial_coordinate))
        if room is None:
            raise ValueError(
                f"unknown initial_coordinate {_coord_key(spec.initial_coordinate)} for agent {spec.agent_id}"
            )
        return room
    for room in room_order:
        if used_counts[room.room_id] < max_agents_per_room:
            return room
    raise ValueError(
        f"unable to auto-assign initial room for agent {spec.agent_id}; capacity exhausted"
    )

def _compile_world(
    world: WorldSpec,
    world_agents: WorldAgentsSpec,
    control: WorldControlSpec,
) -> Tuple[CompiledWorldSpec, Dict[str, Any]]:
    rooms, resolved_shape, diagnostics = _build_rooms(world, control)
    world.topology.grid_shape = resolved_shape
    rooms_by_id = {room.room_id: room for room in rooms}
    rooms_by_coord = {_coord_key(room.coordinate): room for room in rooms}
    room_order = sorted(rooms, key=_room_sort_key)

    declared_ids = {item.agent_id for item in world_agents.agents}
    unknown_active = sorted(set(world_agents.active_agent_ids) - declared_ids)
    unknown_inactive = sorted(set(world_agents.inactive_agent_ids) - declared_ids)
    if unknown_active or unknown_inactive:
        raise ValueError(
            "active/inactive agent lists contain unknown IDs: "
            f"active={unknown_active} inactive={unknown_inactive}"
        )

    used_counts: Counter = Counter()
    compiled_agents: List[CompiledWorldAgent] = []
    active_set = set(world_agents.active_agent_ids)
    inactive_set = set(world_agents.inactive_agent_ids)
    for spec in world_agents.agents:
        room = _resolve_initial_room(
            spec,
            rooms_by_id,
            rooms_by_coord,
            room_order,
            used_counts,
            world.occupancy_policy.max_agents_per_room,
        )
        used_counts[room.room_id] += 1
        active = spec.agent_id in active_set or spec.agent_id not in inactive_set
        compiled_agents.append(
            CompiledWorldAgent(
                agent_id=spec.agent_id,
                display_name=spec.display_name or spec.agent_id,
                active=active,
                initial_room_id=room.room_id,
                initial_coordinate=room.coordinate.model_copy(deep=True),
                movement_policy=(
                    spec.movement_policy.model_copy(deep=True)
                    if spec.movement_policy is not None
                    else control.default_movement_policy.model_copy(deep=True)
                ),
            )
        )

    diagnostics["resolved_grid_shape"] = resolved_shape.model_dump()
    diagnostics["room_count"] = len(rooms)
    diagnostics["movement_mode"] = world.movement_mode
    diagnostics["turn_order"] = world.turn_order
    diagnostics["conflict_resolution"] = world.conflict_resolution
    compiled = CompiledWorldSpec(
        world=world,
        control=control,
        rooms=rooms,
        agents=compiled_agents,
    )
    return compiled, diagnostics
