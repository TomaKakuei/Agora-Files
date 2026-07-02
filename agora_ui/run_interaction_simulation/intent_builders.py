from __future__ import annotations
import json
import random
import re
import time
import traceback
from collections import deque
from typing import Any
from ..adjudicator_schemas import AgentRuntimeProfileSpec, AgentStateBundleSpec, GridPosition
from ..vertex_json_client import VertexJsonClient
from .intent_schemas import *

def _build_custom_intent(
    *,
    round_index: int,
    serial: int,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    route: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action = str(route.get("action", "Chat"))
    status_effect = str(route.get("status_effect", action.lower()))
    duration = int(route.get("duration_steps", 1))
    payload = {
        "intent_id": f"r{round_index:03d}_{serial:04d}_{actor.agent_id}_{action}",
        "agent_id": actor.agent_id,
        "call": "Custom",
        "intent_text": f"{actor.display_name} uses {action} with {target.display_name}.",
        "target_agent_id": target.agent_id,
        "action": action,
        "metadata": {
            "route_id": str(route.get("route_id", "")),
            "story_verb": str(route.get("story_verb", action)),
            "status_effect": status_effect,
            "duration_steps": duration,
            **(metadata or {}),
        },
    }
    return payload


def _build_trade_intents(
    *,
    round_index: int,
    serial: int,
    buyer: AgentRuntimeProfileSpec,
    seller: AgentRuntimeProfileSpec,
    route: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    item = _find_inventory_item(seller, config)
    currency_id = str(config.get("economy", {}).get("currency_item_id", "gold"))
    story_verb = str(route.get("story_verb", "traded with"))
    if item is None:
        return [
            {
                "intent_id": f"r{round_index:03d}_{serial:04d}_{buyer.agent_id}_trade_unavailable",
                "agent_id": buyer.agent_id,
                "call": "Custom",
                "intent_text": f"{buyer.display_name} checks for supplies with {seller.display_name}, but nothing is available to trade.",
                "target_agent_id": seller.agent_id,
                "action": "Chat",
                "metadata": {
                    "route_id": str(route.get("route_id", "")),
                    "story_verb": "found nothing to trade with",
                    "phase": "trade_rejected",
                    "trade_rejected": True,
                    "trade_rejection_reason": "seller_has_no_tradeable_item",
                },
            }
        ]
    price = max(1, _catalog_price(config, item.item_id))
    if _item_quantity(buyer, currency_id) < price:
        return [
            {
                "intent_id": f"r{round_index:03d}_{serial:04d}_{buyer.agent_id}_trade_rejected",
                "agent_id": buyer.agent_id,
                "call": "Custom",
                "intent_text": f"{buyer.display_name} refuses the trade with {seller.display_name} after checking available {currency_id}.",
                "target_agent_id": seller.agent_id,
                "action": "Chat",
                "metadata": {
                    "route_id": str(route.get("route_id", "")),
                    "story_verb": "declined trade with",
                    "trade_item_id": item.item_id,
                    "price": price,
                    "phase": "trade_rejected",
                    "trade_rejected": True,
                    "trade_rejection_reason": "insufficient_funds",
                    "currency_item_id": currency_id,
                    "buyer_currency_quantity": _item_quantity(buyer, currency_id),
                },
            }
        ]
    return [
        {
            "intent_id": f"r{round_index:03d}_{serial:04d}_{buyer.agent_id}_pay",
            "agent_id": buyer.agent_id,
            "call": "Item",
            "intent_text": f"{buyer.display_name} pays {price} {currency_id} to {seller.display_name}.",
            "target_agent_id": seller.agent_id,
            "operation": "Give",
            "item_id": currency_id,
            "quantity": price,
            "metadata": {
                "route_id": str(route.get("route_id", "")),
                "story_verb": story_verb,
                "trade_item_id": item.item_id,
                "price": price,
                "phase": "currency_payment",
            },
        },
        {
            "intent_id": f"r{round_index:03d}_{serial:04d}_{seller.agent_id}_sell",
            "agent_id": seller.agent_id,
            "call": "Item",
            "intent_text": f"{seller.display_name} gives {item.item_id} to {buyer.display_name}.",
            "target_agent_id": buyer.agent_id,
            "operation": "Give",
            "item_id": item.item_id,
            "quantity": 1,
            "metadata": {
                "route_id": str(route.get("route_id", "")),
                "story_verb": story_verb,
                "trade_item_id": item.item_id,
                "price": price,
                "phase": "item_delivery",
            },
        },
    ]


def _rooms_by_distance(
    actor: AgentRuntimeProfileSpec,
    config: dict[str, Any],
    *,
    target_coordinates: GridPosition | None = None,
) -> list[dict[str, Any]]:
    max_steps = int(config.get("space", {}).get("movement", {}).get("max_steps_per_timestep", 1))
    rooms = [dict(room) for room in config.get("space", {}).get("rooms", [])]
    candidates = []
    for room in rooms:
        cells = _room_cells_from_config(room)
        if not cells:
            continue
        dist = min(_distance(actor.coordinates, coord) for coord in cells)
        if 0 < dist <= max_steps:
            toward = min(_distance(coord, target_coordinates) for coord in cells) if target_coordinates is not None else dist
            candidates.append((toward, dist, room))
    candidates.sort(key=lambda item: (item[0], item[1], str(item[2].get("room_id", ""))))
    return [room for _, _, room in candidates]


def _reachable_positions_from_config(
    start: GridPosition,
    config: dict[str, Any],
    *,
    max_steps: int,
) -> list[tuple[GridPosition, int]]:
    walkable = _walkable_cells_from_config(config)
    if not walkable:
        return []
    start_key = _coord_key(start)
    if start_key not in walkable:
        return []
    deltas = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]
    if bool(config.get("space", {}).get("movement", {}).get("allow_diagonal", False)):
        deltas.extend([(1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0)])
    frontier: deque[tuple[tuple[int, int, int], int]] = deque([(start_key, 0)])
    visited = {start_key}
    reachable: list[tuple[GridPosition, int]] = []
    while frontier:
        current, distance = frontier.popleft()
        if distance >= max_steps:
            continue
        for dx, dy, dz in deltas:
            neighbor = (current[0] + dx, current[1] + dy, current[2] + dz)
            if neighbor in visited or neighbor not in walkable:
                continue
            visited.add(neighbor)
            next_distance = distance + 1
            frontier.append((neighbor, next_distance))
            reachable.append((GridPosition(x=neighbor[0], y=neighbor[1], z=neighbor[2]), next_distance))
    return reachable


def _build_move_intent(
    *,
    rng: random.Random,
    round_index: int,
    serial: int,
    actor: AgentRuntimeProfileSpec,
    route: dict[str, Any],
    config: dict[str, Any],
    target_agent: AgentRuntimeProfileSpec | None = None,
) -> dict[str, Any] | None:
    target_coordinates = target_agent.coordinates if target_agent is not None else None
    target_room = _room_by_id(config, target_agent.room_id) if target_agent is not None and target_agent.room_id else None
    movement = config.get("space", {}).get("movement", {})
    max_steps = max(1, int(movement.get("max_steps_per_timestep", 1)))
    destination = None
    destination_room_id = ""
    destination_name = "room"
    target_room_id = str(target_room.get("room_id", "")) if target_room is not None else ""
    target_room_name = str(target_room.get("name", target_room_id or "room")) if target_room is not None else "room"
    target_room_cells = {_coord_key(cell) for cell in _room_cells_from_config(target_room)} if target_room is not None else set()
    reachable_steps = _reachable_positions_from_config(actor.coordinates, config, max_steps=max_steps)
    if reachable_steps:
        if target_coordinates is not None:
            target_key = _coord_key(target_coordinates)

            def _move_rank(item: tuple[GridPosition, int]) -> tuple[int, int, int, int, int, int, int]:
                cell, distance = item
                cell_key = _coord_key(cell)
                in_target_room = 0 if cell_key in target_room_cells else 1
                reaches_target = 0 if cell_key == target_key else 1
                walk_to_target = _walkable_distance_config(cell, target_coordinates, config)
                if walk_to_target is None:
                    walk_to_target = 10**9
                linear_to_target = _distance(cell, target_coordinates)
                leaves_current_cell = 0 if cell_key != _coord_key(actor.coordinates) else 1
                return (
                    in_target_room,
                    reaches_target,
                    walk_to_target,
                    linear_to_target,
                    distance,
                    leaves_current_cell,
                    cell.x * 1000 + cell.y,
                )

            best_cell, _ = min(reachable_steps, key=_move_rank)
            destination = best_cell.model_copy(deep=True)
            if _coord_key(destination) in target_room_cells and target_room_id:
                destination_room_id = target_room_id
                destination_name = target_room_name
            else:
                destination_room_id = _room_id_for_coordinate_config(config, destination) or actor.room_id or target_room_id
                destination_name = target_room_name if target_room_id else str(destination_room_id or "room")
        else:
            def _generic_rank(item: tuple[GridPosition, int]) -> tuple[int, int, int, int, int]:
                cell, distance = item
                room_id = _room_id_for_coordinate_config(config, cell) or ""
                stays_in_room = 0 if room_id and room_id != actor.room_id else 1
                return (stays_in_room, distance, cell.x, cell.y, cell.z)

            best_cell, _ = min(reachable_steps, key=_generic_rank)
            destination = best_cell.model_copy(deep=True)
            destination_room_id = _room_id_for_coordinate_config(config, destination) or actor.room_id
            destination_name = str(destination_room_id or "room")
    if destination is None and target_room is not None:
        path = _path_to_target_room(actor.coordinates, target_room, config)
        if len(path) >= 2:
            destination = path[min(max_steps, len(path) - 1)].model_copy(deep=True)
            destination_room_id = target_room_id if _coord_key(destination) in target_room_cells else (_room_id_for_coordinate_config(config, destination) or target_room_id)
            destination_name = target_room_name
    if destination is None:
        candidates = _rooms_by_distance(actor, config, target_coordinates=target_coordinates)
        if candidates:
            room = candidates[rng.randrange(len(candidates))]
            destination = _spawn_coordinate_for_room(room, serial)
            destination_room_id = str(room.get("room_id", ""))
            destination_name = str(room.get("name", room.get("room_id", "room")))
    if destination is None and actor.room_id:
        actor_room = _room_by_id(config, actor.room_id)
        if actor_room is not None:
            current_room_cells = [
                cell for cell in _room_cells_from_config(actor_room)
                if _coord_key(cell) != _coord_key(actor.coordinates)
            ]
            if current_room_cells:
                current_room_cells.sort(key=lambda cell: (_distance(cell, target_coordinates) if target_coordinates is not None else 0, cell.x, cell.y, cell.z))
                destination = current_room_cells[0].model_copy(deep=True)
                destination_room_id = actor.room_id
                destination_name = str(actor_room.get("name", actor.room_id or "room"))
    if destination is None:
        return None
    return {
        "intent_id": f"r{round_index:03d}_{serial:04d}_{actor.agent_id}_move",
        "agent_id": actor.agent_id,
        "call": "Move",
        "intent_text": f"{actor.display_name} moves toward {destination_name}.",
        "target_coordinates": destination.model_dump(),
        "metadata": {
            "route_id": str(route.get("route_id", "")),
            "story_verb": str(route.get("story_verb", "moved")),
            "target_room_id": destination_room_id,
            "approach_target_agent_id": str(target_agent.agent_id) if target_agent is not None else "",
        },
    }


def _build_image_intent(
    *,
    round_index: int,
    serial: int,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    route: dict[str, Any],
    image_prompt: str,
    image_record: dict[str, Any],
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job_id = str(image_record.get("job_id", ""))
    return {
        "intent_id": f"r{round_index:03d}_{serial:04d}_{actor.agent_id}_Image",
        "agent_id": actor.agent_id,
        "call": "Image",
        "intent_text": f"{actor.display_name} requests a still image artifact for {route.get('route_id', 'image')}.",
        "target_agent_id": target.agent_id,
        "operation": "create",
        "api_prompt": image_prompt,
        "metadata": {
            "route_id": str(route.get("route_id", "")),
            "story_verb": str(route.get("story_verb", "created an image artifact with")),
            "image_reason": reason,
            "image_job_id": job_id,
            "image_path": str(image_record.get("image_path", "")),
            "image_mime_type": str(image_record.get("image_mime_type", "")),
            "image_source": str(image_record.get("backend", image_record.get("status", ""))),
            **(metadata or {}),
        },
    }


def _first_image_route(config: dict[str, Any]) -> dict[str, Any] | None:
    for route in config.get("actions", {}).get("ordinary_routes", []) or []:
        if isinstance(route, dict) and str(route.get("kind", "")) == "image":
            return dict(route)
    return None


def _first_move_route(config: dict[str, Any]) -> dict[str, Any] | None:
    for route in config.get("actions", {}).get("ordinary_routes", []) or []:
        if isinstance(route, dict) and str(route.get("kind", "")) == "move":
            return dict(route)
    return None


def _route_lookup(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {}
    for group in ("ordinary_routes", "cinematic_routes"):
        for route in config.get("actions", {}).get(group, []) or []:
            if isinstance(route, dict) and route.get("route_id"):
                routes[str(route["route_id"])] = dict(route)
    return routes


def _fallback_request_for_quota(
    request: dict[str, Any],
    *,
    config: dict[str, Any],
    exhausted_kind: str,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
) -> dict[str, Any]:
    preferred_kinds = ("custom", "item_trade", "move")
    ordinary_routes = [
        dict(route)
        for route in config.get("actions", {}).get("ordinary_routes", []) or []
        if isinstance(route, dict)
    ]
    fallback_route: dict[str, Any] | None = None
    for preferred_kind in preferred_kinds:
        for route in ordinary_routes:
            if str(route.get("kind", "")) == preferred_kind:
                fallback_route = route
                break
        if fallback_route is not None:
            break
    if fallback_route is None:
        fallback_route = {"route_id": "quota_fallback_chat", "kind": "custom", "action": "Chat", "story_verb": "spoke with"}
    reason_prefix = f"{exhausted_kind}_quota_exhausted"
    original_route = str(request.get("route_id", fallback_route.get("route_id", ""))).strip()
    original_kind = str(request.get("kind", exhausted_kind)).strip() or exhausted_kind
    original_reason = str(request.get("reason", "")).strip()
    merged_reason = (
        f"{reason_prefix}: downgraded {actor.agent_id}->{target.agent_id} from {original_kind}:{original_route} "
        f"to {fallback_route.get('kind', 'custom')}:{fallback_route.get('route_id', 'fallback')}"
    )
    if original_reason:
        merged_reason = f"{merged_reason}. Original reason: {original_reason}"
    return {
        **fallback_route,
        "reason": merged_reason[:300],
        "fallback_reason": reason_prefix,
        "fallback_from_kind": original_kind,
        "fallback_from_route_id": original_route,
    }

