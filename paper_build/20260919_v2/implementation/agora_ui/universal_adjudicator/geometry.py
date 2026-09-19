from __future__ import annotations

from collections import deque
from typing import List

from agora_ui.adjudicator_schemas import WorldRulesSpec
from agora_ui.foundation_schemas import GridPosition, RoomSpec


def _coord_key(position: GridPosition) -> tuple[int, int, int]:
    return (position.x, position.y, position.z)


def _coord_text(position: GridPosition) -> str:
    return f"{position.x},{position.y},{position.z}"


def _room_cells(room: RoomSpec) -> list[GridPosition]:
    if room.footprint_tiles:
        cells = [cell.model_copy(deep=True) for cell in room.footprint_tiles]
    else:
        cells = [
            GridPosition(x=room.x + dx, y=room.y + dy, z=room.z)
            for dx in range(max(1, int(room.width_tiles)))
            for dy in range(max(1, int(room.height_tiles)))
        ]
    for doorway in room.doorways:
        if _coord_key(doorway.position) not in {_coord_key(cell) for cell in cells}:
            cells.append(doorway.position.model_copy(deep=True))
    return cells


def _walkable_cells(world_rules: WorldRulesSpec) -> set[tuple[int, int, int]]:
    cells: set[tuple[int, int, int]] = set()
    for room in world_rules.topology.rooms:
        cells.update(_coord_key(cell) for cell in _room_cells(room))
    return cells


def _position_in_shape(position: GridPosition, world_rules: WorldRulesSpec) -> bool:
    shape = world_rules.topology.grid_shape
    in_bounds = (
        0 <= position.x < shape.x
        and 0 <= position.y < shape.y
        and 0 <= position.z < shape.z
    )
    if not in_bounds:
        return False
    walkable = _walkable_cells(world_rules)
    if walkable:
        return _coord_key(position) in walkable
    return True


def _manhattan_distance(a: GridPosition, b: GridPosition) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y) + abs(a.z - b.z)


def _room_for_position(position: GridPosition, rooms: List[RoomSpec]) -> str:
    key = _coord_key(position)
    for room in rooms:
        if key in {_coord_key(cell) for cell in _room_cells(room)}:
            return room.room_id or room.name or f"coord_{_coord_text(position)}"
    return f"coord_{_coord_text(position)}"


def _walkable_distance(
    start: GridPosition,
    target: GridPosition,
    world_rules: WorldRulesSpec,
    *,
    max_steps: int,
) -> int | None:
    start_key = _coord_key(start)
    target_key = _coord_key(target)
    if start_key == target_key:
        return 0
    walkable = _walkable_cells(world_rules)
    if not walkable:
        distance = _manhattan_distance(start, target)
        return distance if distance <= max_steps else None
    if start_key not in walkable or target_key not in walkable:
        return None
    deltas = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]
    if world_rules.movement.allow_diagonal:
        deltas.extend([(1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0)])
    frontier: deque[tuple[tuple[int, int, int], int]] = deque([(start_key, 0)])
    visited = {start_key}
    while frontier:
        current, distance = frontier.popleft()
        if distance >= max_steps:
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
