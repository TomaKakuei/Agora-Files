from __future__ import annotations
import argparse
import base64
import hashlib
import json
import math
import mimetypes
import os
import random
import shutil
import subprocess
import sys
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, deque
from datetime import datetime
from pathlib import Path
from typing import Any
from PIL import Image
from ..adjudicator_schemas import (
    AgentIntentBatchSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    InventoryItemSpec,
    RelationshipVectorSpec,
)
from ..flex_api import first_json_value_from_text
from ..foundation_schemas import GridPosition
from ..package_db import is_world_package_db, materialize_world_package
from ..jsonc_utils import dump_json, load_jsonc_path
from ..universal_adjudicator import core as adjudicator
from ..extra_world_functions import (
    extra_world_functions_config,
    recent_global_world_events,
    run_extra_world_functions,
)
from ..world_definition import default_wallet_payload
from ..world_definition import legacy_currency_inventory_entry
from ..world_definition import sync_world_definition_into_config
from ..agent_factory import (
    SafeDict,
    _format,
    _room_spawn_cells,
    _spawn_coordinate_for_room,
    _runner_config,
    _world_label,
    _domain_label,
    _story_filename,
    _run_name,
    _agent_id_prefix,
    _image_generation_config,
    _inventory_item,
    _currency_item,
    _starting_wallet_range,
    _role_sequence,
    _room_for_agent,
    _room_by_id,
    _main_character_specs,
    _main_character_ids,
    _force_cinematic_agent_ids,
    _main_character_payload,
    _variation_token,
    _display_name_for_agent,
    _build_agent_payloads,
    _vertex_agent_profile_payloads,
    _inventory_generation_config,
    _merge_inventory_items,
    _vertex_initial_inventory_payloads,
)
from ..vertex_json_client import VertexJsonClient
from ..vertex_image_client import VertexSDKImageClient





def _coord_key(position: GridPosition | dict[str, Any]) -> tuple[int, int, int]:
    if isinstance(position, GridPosition):
        return (position.x, position.y, position.z)
    return (int(position.get("x", 0)), int(position.get("y", 0)), int(position.get("z", 0)))


def _distance(a: GridPosition, b: GridPosition) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y) + abs(a.z - b.z)


def _room_cells_from_config(room: dict[str, Any]) -> list[GridPosition]:
    explicit = room.get("footprint_tiles", [])
    cells: list[GridPosition] = []
    if isinstance(explicit, list) and explicit:
        for item in explicit:
            if isinstance(item, dict):
                cells.append(
                    GridPosition(
                        x=int(item.get("x", room.get("x", 0))),
                        y=int(item.get("y", room.get("y", 0))),
                        z=int(item.get("z", room.get("z", 0))),
                    )
                )
    else:
        width_tiles = max(1, int(room.get("width_tiles", 1)))
        height_tiles = max(1, int(room.get("height_tiles", 1)))
        base_x = int(room.get("x", 0))
        base_y = int(room.get("y", 0))
        base_z = int(room.get("z", 0))
        for dx in range(width_tiles):
            for dy in range(height_tiles):
                cells.append(GridPosition(x=base_x + dx, y=base_y + dy, z=base_z))
    for doorway in room.get("doorways", []) or []:
        if not isinstance(doorway, dict):
            continue
        position = doorway.get("position", doorway)
        if not isinstance(position, dict):
            continue
        candidate = GridPosition(
            x=int(position.get("x", room.get("x", 0))),
            y=int(position.get("y", room.get("y", 0))),
            z=int(position.get("z", room.get("z", 0))),
        )
        if _coord_key(candidate) not in {_coord_key(item) for item in cells}:
            cells.append(candidate)
    return cells


def _walkable_cells_from_config(config: dict[str, Any]) -> set[tuple[int, int, int]]:
    cells: set[tuple[int, int, int]] = set()
    for room in config.get("space", {}).get("rooms", []) or []:
        if isinstance(room, dict):
            cells.update(_coord_key(cell) for cell in _room_cells_from_config(room))
    return cells


def _walkable_distance_config(
    start: GridPosition,
    target: GridPosition,
    config: dict[str, Any],
    *,
    max_steps: int | None = None,
) -> int | None:
    walkable = _walkable_cells_from_config(config)
    if not walkable:
        distance = _distance(start, target)
        return distance if max_steps is None or distance <= max_steps else None
    start_key = _coord_key(start)
    target_key = _coord_key(target)
    if start_key == target_key:
        return 0
    if start_key not in walkable or target_key not in walkable:
        return None
    deltas = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]
    if bool(config.get("space", {}).get("movement", {}).get("allow_diagonal", False)):
        deltas.extend([(1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0)])
    frontier: deque[tuple[tuple[int, int, int], int]] = deque([(start_key, 0)])
    visited = {start_key}
    step_cap = max_steps if max_steps is not None else max(1, len(walkable))
    while frontier:
        current, distance = frontier.popleft()
        if distance >= step_cap:
            continue
        for dx, dy, dz in deltas:
            neighbor = (current[0] + dx, current[1] + dy, current[2] + dz)
            if neighbor == target_key:
                if neighbor in walkable:
                    return distance + 1
                continue
            if neighbor in visited or neighbor not in walkable:
                continue
            visited.add(neighbor)
            frontier.append((neighbor, distance + 1))
    return None


def _path_to_target_room(
    start: GridPosition,
    target_room: dict[str, Any],
    config: dict[str, Any],
) -> list[GridPosition]:
    walkable = _walkable_cells_from_config(config)
    room_targets = {_coord_key(cell) for cell in _room_cells_from_config(target_room)}
    if not walkable or not room_targets:
        return []
    start_key = _coord_key(start)
    if start_key in room_targets:
        return [start.model_copy(deep=True)]
    deltas = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]
    if bool(config.get("space", {}).get("movement", {}).get("allow_diagonal", False)):
        deltas.extend([(1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0)])
    frontier: deque[tuple[int, int, int]] = deque([start_key])
    parents: dict[tuple[int, int, int], tuple[int, int, int] | None] = {start_key: None}
    found: tuple[int, int, int] | None = None
    while frontier:
        current = frontier.popleft()
        if current in room_targets:
            found = current
            break
        for dx, dy, dz in deltas:
            neighbor = (current[0] + dx, current[1] + dy, current[2] + dz)
            if neighbor in parents or neighbor not in walkable:
                continue
            parents[neighbor] = current
            frontier.append(neighbor)
    if found is None:
        return []
    keys: list[tuple[int, int, int]] = []
    cursor: tuple[int, int, int] | None = found
    while cursor is not None:
        keys.append(cursor)
        cursor = parents.get(cursor)
    keys.reverse()
    return [GridPosition(x=x, y=y, z=z) for x, y, z in keys]


def _room_id_for_coordinate_config(config: dict[str, Any], coordinate: GridPosition) -> str:
    key = _coord_key(coordinate)
    for room in config.get("space", {}).get("rooms", []) or []:
        if not isinstance(room, dict):
            continue
        if key in {_coord_key(cell) for cell in _room_cells_from_config(room)}:
            return str(room.get("room_id", ""))
    return ""


def _resolved_grid_shape(config: dict[str, Any]) -> dict[str, int]:
    provided = dict(config.get("space", {}).get("grid_shape", {}))
    max_x = int(provided.get("x", 1) or 1)
    max_y = int(provided.get("y", 1) or 1)
    max_z = int(provided.get("z", 1) or 1)
    for room in config.get("space", {}).get("rooms", []) or []:
        if not isinstance(room, dict):
            continue
        for cell in _room_cells_from_config(room):
            max_x = max(max_x, cell.x + 1)
            max_y = max(max_y, cell.y + 1)
            max_z = max(max_z, cell.z + 1)
    return {"x": max_x, "y": max_y, "z": max_z}

__all__ = ['_coord_key', '_distance', '_room_cells_from_config', '_walkable_cells_from_config', '_walkable_distance_config', '_path_to_target_room', '_room_id_for_coordinate_config', '_resolved_grid_shape']
