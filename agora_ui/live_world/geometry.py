from __future__ import annotations
import calendar
import contextlib
import copy
import hashlib
import json
import os
import queue
import secrets
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from ..adjudicator_schemas import AgentRuntimeProfileSpec
from ..package_db import materialize_world_package
from ..world_definition import default_wallet_payload
from ..world_definition import legacy_currency_inventory_entry
from ..world_definition import sync_world_definition_into_config

from .utils import _load_json, _safe_int





def _room_tile_key(x: int, y: int, z: int = 0) -> str:
    return f"{int(x)},{int(y)},{int(z)}"


def _coord_payload(value: Any, *, fallback: dict[str, int] | None = None) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    base = fallback or {"x": 0, "y": 0, "z": 0}
    return {
        "x": _safe_int(source.get("x", base.get("x", 0))),
        "y": _safe_int(source.get("y", base.get("y", 0))),
        "z": _safe_int(source.get("z", base.get("z", 0))),
    }


def _coord_distance(left: dict[str, Any], right: dict[str, Any]) -> int:
    return (
        abs(_safe_int(left.get("x", 0)) - _safe_int(right.get("x", 0)))
        + abs(_safe_int(left.get("y", 0)) - _safe_int(right.get("y", 0)))
        + abs(_safe_int(left.get("z", 0)) - _safe_int(right.get("z", 0)))
    )


def _resolve_map_grid_path(workspace: Path) -> Path:
    for relative in (
        "scenario/map_grid.json",
        "run_inputs/scenario/map_grid.json",
    ):
        candidate = workspace / relative
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("map_grid.json not found in materialized package")


def _load_room_list(workspace: Path) -> list[dict[str, Any]]:
    map_grid_path = _resolve_map_grid_path(workspace)
    payload = _load_json(map_grid_path)
    rooms = payload.get("rooms", []) if isinstance(payload, dict) else []
    return [dict(room) for room in rooms if isinstance(room, dict)]


def _room_bounds(room: dict[str, Any], default_width: int = 6, default_height: int = 4) -> tuple[int, int, int, int]:
    tiles = [tile for tile in room.get("footprint_tiles", []) if isinstance(tile, dict)]
    if tiles:
        xs = [_safe_int(tile.get("x", 0)) for tile in tiles]
        ys = [_safe_int(tile.get("y", 0)) for tile in tiles]
        return min(xs), min(ys), max(xs), max(ys)
    x = _safe_int(room.get("x", 0))
    y = _safe_int(room.get("y", 0))
    width = max(1, _safe_int(room.get("width_tiles", default_width), default_width))
    height = max(1, _safe_int(room.get("height_tiles", default_height), default_height))
    return x, y, x + width - 1, y + height - 1


def _room_tiles(room: dict[str, Any]) -> list[dict[str, int]]:
    tiles = [tile for tile in room.get("footprint_tiles", []) if isinstance(tile, dict)]
    if tiles:
        return [
            {
                "x": _safe_int(tile.get("x", 0)),
                "y": _safe_int(tile.get("y", 0)),
                "z": _safe_int(tile.get("z", 0)),
            }
            for tile in tiles
        ]
    min_x, min_y, max_x, max_y = _room_bounds(room)
    result: list[dict[str, int]] = []
    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            result.append({"x": x, "y": y, "z": 0})
    return result


def _room_tile_index(rooms: list[dict[str, Any]]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for room in rooms:
        room_id = str(room.get("room_id", "")).strip()
        if not room_id:
            continue
        for tile in _room_tiles(room):
            key = _room_tile_key(tile["x"], tile["y"], tile["z"])
            index.setdefault(key, set()).add(room_id)
    return index


def _room_door_tile_keys(room: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    doorways = room.get("doorways", []) if isinstance(room.get("doorways", []), list) else []
    for doorway in doorways:
        if not isinstance(doorway, dict):
            continue
        position = doorway.get("position", {})
        keys.add(_room_tile_key(_safe_int(position.get("x", 0)), _safe_int(position.get("y", 0)), _safe_int(position.get("z", 0))))
    return keys


def _room_wall_indexes(
    rooms: list[dict[str, Any]],
    room_tile_index: dict[str, set[str]],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    outer_index: dict[str, set[str]] = {}
    inner_index: dict[str, set[str]] = {}
    directions = ((-1, 0), (1, 0), (0, -1), (0, 1))
    for room in rooms:
        room_id = str(room.get("room_id", "")).strip()
        if not room_id:
            continue
        door_tile_keys = _room_door_tile_keys(room)
        for tile in _room_tiles(room):
            key = _room_tile_key(tile["x"], tile["y"], tile["z"])
            if key in door_tile_keys:
                continue
            touches_boundary = False
            touches_outer_boundary = False
            touches_shared_boundary = False
            for dx, dy in directions:
                neighbor_key = _room_tile_key(tile["x"] + dx, tile["y"] + dy, tile["z"])
                neighbor_rooms = room_tile_index.get(neighbor_key, set())
                if room_id in neighbor_rooms:
                    continue
                touches_boundary = True
                if neighbor_rooms:
                    touches_shared_boundary = True
                else:
                    touches_outer_boundary = True
            if not touches_boundary:
                continue
            if touches_outer_boundary:
                outer_index.setdefault(room_id, set()).add(key)
            elif touches_shared_boundary:
                inner_index.setdefault(room_id, set()).add(key)
    return outer_index, inner_index


def _room_walk_path(room: dict[str, Any], agent_id: str) -> list[dict[str, int]]:
    tiles = _room_tiles(room)
    if not tiles:
        return []
    tiles = sorted(tiles, key=lambda item: (item["y"], item["x"], item["z"]))
    offset = int(hashlib.sha256(f"{room.get('room_id', '')}:{agent_id}".encode("utf-8")).hexdigest()[:8], 16)
    if tiles:
        offset %= len(tiles)
        tiles = tiles[offset:] + tiles[:offset]
    return tiles


def _resolve_room_transition(
    *,
    rooms: dict[str, dict[str, Any]],
    room_tile_index: dict[str, set[str]],
    current_room_id: str,
    current_position: dict[str, Any],
    next_position: dict[str, Any],
) -> str:
    next_key = _room_tile_key(_safe_int(next_position.get("x", 0)), _safe_int(next_position.get("y", 0)), _safe_int(next_position.get("z", 0)))
    target_room_ids = room_tile_index.get(next_key, set())
    if not target_room_ids:
        return ""
    if current_room_id in target_room_ids:
        return current_room_id
    current_room = rooms.get(current_room_id)
    if current_room is None:
        return next(iter(target_room_ids), "")
    current_doors = [door for door in current_room.get("doorways", []) if isinstance(door, dict)]
    for room_id in target_room_ids:
        if room_id == current_room_id:
            return room_id
        target_room = rooms.get(room_id)
        if target_room is None:
            continue
        target_doors = [door for door in target_room.get("doorways", []) if isinstance(door, dict)]
        for source_doors, linked_room_id in ((current_doors, room_id), (target_doors, current_room_id)):
            for doorway in source_doors:
                if str(doorway.get("connects_to_room_id", "")).strip() != linked_room_id:
                    continue
                doorway_pos = doorway.get("position", {})
                distance = abs(_safe_int(doorway_pos.get("x", 0)) - _safe_int(current_position.get("x", 0))) + abs(
                    _safe_int(doorway_pos.get("y", 0)) - _safe_int(current_position.get("y", 0))
                )
                if distance <= 2:
                    return room_id if linked_room_id == room_id else current_room_id
    return ""


def _tile_has_wall_kind(tile_key: str, room_ids: set[str], wall_index: dict[str, set[str]]) -> bool:
    return any(tile_key in wall_index.get(room_id, set()) for room_id in room_ids)


def _preferred_room_id_for_tile(
    *,
    rooms: dict[str, dict[str, Any]],
    room_tile_index: dict[str, set[str]],
    current_room_id: str,
    current_position: dict[str, Any],
    target_position: dict[str, Any],
    allow_boundary_bypass: bool,
) -> str:
    resolved = _resolve_room_transition(
        rooms=rooms,
        room_tile_index=room_tile_index,
        current_room_id=current_room_id,
        current_position=current_position,
        next_position=target_position,
    )
    if resolved:
        return resolved
    if not allow_boundary_bypass:
        return ""
    tile_key = _room_tile_key(_safe_int(target_position.get("x", 0)), _safe_int(target_position.get("y", 0)), _safe_int(target_position.get("z", 0)))
    target_room_ids = sorted(room_tile_index.get(tile_key, set()))
    non_current = [room_id for room_id in target_room_ids if room_id != current_room_id]
    if non_current:
        return non_current[0]
    return target_room_ids[0] if target_room_ids else ""


def _resolve_wall_hop_destination(
    *,
    rooms: dict[str, dict[str, Any]],
    room_tile_index: dict[str, set[str]],
    outer_wall_tile_index: dict[str, set[str]],
    inner_wall_tile_index: dict[str, set[str]],
    current_room_id: str,
    current_position: dict[str, Any],
    direction: str,
    max_hop_tiles: int = 4,
) -> tuple[str, dict[str, int]] | None:
    vectors = {
        "up": (0, -1),
        "down": (0, 1),
        "left": (-1, 0),
        "right": (1, 0),
        "move_up": (0, -1),
        "move_down": (0, 1),
        "move_left": (-1, 0),
        "move_right": (1, 0),
    }
    delta = vectors.get(str(direction or "").strip().lower())
    if not delta:
        return None
    dx, dy = delta
    encountered_inner_wall = False
    hop_limit = max(1, _safe_int(max_hop_tiles, 4))
    for step in range(1, hop_limit + 1):
        probe = {
            "x": _safe_int(current_position.get("x", 0)) + (dx * step),
            "y": _safe_int(current_position.get("y", 0)) + (dy * step),
            "z": _safe_int(current_position.get("z", 0)),
        }
        probe_key = _room_tile_key(probe["x"], probe["y"], probe["z"])
        target_room_ids = room_tile_index.get(probe_key, set())
        if not target_room_ids:
            return None
        is_inner_wall = _tile_has_wall_kind(probe_key, target_room_ids, inner_wall_tile_index)
        is_outer_wall = _tile_has_wall_kind(probe_key, target_room_ids, outer_wall_tile_index)
        if is_outer_wall and not is_inner_wall:
            return None
        if is_inner_wall:
            encountered_inner_wall = True
            continue
        landing_room_id = _preferred_room_id_for_tile(
            rooms=rooms,
            room_tile_index=room_tile_index,
            current_room_id=current_room_id,
            current_position=current_position,
            target_position=probe,
            allow_boundary_bypass=encountered_inner_wall or step > 1,
        )
        if not landing_room_id:
            return None
        return landing_room_id, probe
    return None


def _disable_world_geometry_collision(config: dict[str, Any]) -> bool:
    frontend = config.get("pixel_asset_pipeline", {}).get("frontend", {})
    if not isinstance(frontend, dict):
        return False
    pov = frontend.get("pov_local_modules", {})
    if not isinstance(pov, dict):
        return False
    movement = pov.get("movement", {})
    if not isinstance(movement, dict):
        return False
    collision = movement.get("collision", {})
    if not isinstance(collision, dict):
        return False
    return collision.get("disable_world_geometry") is True


def _resolve_unblocked_destination(
    *,
    rooms: dict[str, dict[str, Any]],
    room_tile_index: dict[str, set[str]],
    current_room_id: str,
    current_position: dict[str, Any],
    direction: str,
) -> tuple[str, dict[str, int]] | None:
    vectors = {
        "up": (0, -1),
        "down": (0, 1),
        "left": (-1, 0),
        "right": (1, 0),
        "move_up": (0, -1),
        "move_down": (0, 1),
        "move_left": (-1, 0),
        "move_right": (1, 0),
    }
    delta = vectors.get(str(direction or "").strip().lower())
    if not delta:
        return None
    dx, dy = delta
    probe = {
        "x": _safe_int(current_position.get("x", 0)) + dx,
        "y": _safe_int(current_position.get("y", 0)) + dy,
        "z": _safe_int(current_position.get("z", 0)),
    }
    landing_room_id = _preferred_room_id_for_tile(
        rooms=rooms,
        room_tile_index=room_tile_index,
        current_room_id=current_room_id,
        current_position=current_position,
        target_position=probe,
        allow_boundary_bypass=True,
    )
    if not landing_room_id:
        return None
    return landing_room_id, probe

__all__ = ['_room_tile_key', '_coord_payload', '_coord_distance', '_resolve_map_grid_path', '_load_room_list', '_room_bounds', '_room_tiles', '_room_tile_index', '_room_door_tile_keys', '_room_wall_indexes', '_room_walk_path', '_resolve_room_transition', '_tile_has_wall_kind', '_preferred_room_id_for_tile', '_resolve_wall_hop_destination', '_disable_world_geometry_collision', '_resolve_unblocked_destination']
