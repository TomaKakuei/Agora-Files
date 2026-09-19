from __future__ import annotations
import os
import sys
import time
import json
import subprocess
from collections import deque
from pathlib import Path
from typing import Any
from agora_ui.world_definition import default_wallet_payload
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
from agora_ui.scenario_schemas import ScenarioMapGridSpec
from .components.html_utils import _resolve_asset_path, _static_url_if_local

__all__ = [
    "_room_prompt", "_agent_prompt", "_item_prompt", "_agent_statuses",
    "_inventory_payload", "_currency_amount", "_agent_payload",
    "_room_capacity_payload", "_social_groups_payload", "_relationship_edges",
    "_agent_id_number", "_neutral_relationship_tensor", "_fallback_map_grid",
    "_item_is_important_artifact"
]

def _item_is_important_artifact(item: dict[str, Any]) -> bool:
    metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata", {}), dict) else {}
    if bool(metadata.get("important_artifact")):
        return True
    rarity = str(metadata.get("rarity", "")).strip().lower()
    category = str(metadata.get("category", "")).strip().lower()
    text = " ".join(
        part
        for part in [
            str(metadata.get("name", "")),
            str(item.get("description", "")),
            str(item.get("item_id", "")),
            category,
        ]
        if str(part).strip()
    ).lower()
    if rarity in {"rare", "epic", "legendary", "unique"}:
        return True
    if category in {"artifact", "relic", "quest_item", "quest", "heirloom"}:
        return True
    return any(token in text for token in ("artifact", "relic", "heirloom", "seal", "crystal", "map"))

def _room_prompt(config: dict[str, Any], room: dict[str, Any]) -> str:
    world = config.get("scenario_meta", {})
    room_visual = room.get("visual", {})
    decor = ", ".join(room_visual.get("decor_tags", [])) or "minimal decor"
    return (
        f"Create one clean illustrative environment image for a macro world viewer. "
        f"Setting: {world.get('world_name', 'Agora World')}. "
        f"Theme: {config.get('runner', {}).get('domain_label', 'fictional world')}. "
        f"Room: {room.get('name', room.get('room_id', 'room'))}. "
        f"Biome: {room_visual.get('biome', 'interior')}. "
        f"Floor material token: {room_visual.get('floor_tile', 'floor')}. "
        f"Wall material token: {room_visual.get('wall_tile', 'wall')}. "
        f"Decor: {decor}. Ambient palette: {room_visual.get('ambient_palette', 'balanced')}. "
        "No people in frame. No visible text. No watermark. Pixel-friendly environment illustration grounded in the active world."
    )


def _agent_prompt(config: dict[str, Any], agent: dict[str, Any], room_lookup: dict[str, dict[str, Any]]) -> str:
    room = room_lookup.get(agent.get("room_id", ""), {})
    room_visual = room.get("visual", {})
    return (
        f"Create one clean character portrait for a macro world viewer. "
        f"World: {config.get('scenario_meta', {}).get('world_name', 'Agora World')}. "
        f"Theme: {config.get('runner', {}).get('domain_label', 'fictional world')}. "
        f"Character: {agent.get('display_name', agent.get('agent_id', 'Agent'))}. "
        f"Role: {agent.get('role_name', 'Agent')}. "
        f"Appearance: {agent.get('appearance_prompt', '')}. "
        f"Current room mood: {room.get('name', agent.get('room_id', 'room'))}, biome {room_visual.get('biome', 'neutral')}, palette {room_visual.get('ambient_palette', 'balanced')}. "
        "Waist-up portrait, readable silhouette, distinct face and outfit, no text, no watermark."
    )


def _item_prompt(config: dict[str, Any], item: dict[str, Any]) -> str:
    metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata", {}), dict) else {}
    name = str(metadata.get("name") or item.get("description") or item.get("item_id") or "Item")
    description = str(item.get("description", "")).strip()
    category = str(metadata.get("category", "")).strip()
    rarity = str(metadata.get("rarity", "")).strip()
    explicit_prompt = str(item.get("image_prompt", "")).strip()
    importance = "important artifact item" if _item_is_important_artifact(item) else "inventory object"
    if explicit_prompt:
        detail = explicit_prompt
    else:
        detail = (
            f"Item name: {name}. "
            f"Category: {category or 'general item'}. "
            f"Rarity: {rarity or 'ordinary'}. "
            f"Description: {description or 'portable object used in the simulation world.'}"
        )
    return (
        "Create one clean object render for a macro world viewer. "
        f"World: {config.get('scenario_meta', {}).get('world_name', 'Agora World')}. "
        f"Theme: {config.get('runner', {}).get('domain_label', 'fictional world')}. "
        f"Render this as a {importance}. "
        f"{detail} "
        "Single item, centered, readable silhouette, no hands, no people, no text, no watermark."
    )


def _agent_statuses(agent_payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for effect in agent_payload.get("status_effects", []) or []:
        if isinstance(effect, dict):
            effect_name = str(effect.get("effect", "")).strip()
            if effect_name:
                values.append(effect_name)
    return values


def _inventory_payload(
    agent_payload: dict[str, Any],
    *,
    item_image_urls: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    image_urls = item_image_urls or {}
    for item in agent_payload.get("inventory", []) or []:
        if not isinstance(item, dict):
            continue
        image_path = _resolve_asset_path(item.get("image_path", ""))
        metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata", {}), dict) else {}
        item_id = str(item.get("item_id", ""))
        payload.append(
            {
                "item_id": item_id,
                "name": str(metadata.get("name") or item.get("description") or item.get("item_id") or "Item"),
                "quantity": int(item.get("quantity", 0) or 0),
                "mass": float(item.get("mass", 0.0) or 0.0),
                "description": str(item.get("description", "")),
                "image_path": str(item.get("image_path", "")),
                "image_prompt": str(item.get("image_prompt", "")),
                "image_url": image_urls.get(item_id, "") or _static_url_if_local(image_path),
                "important_artifact": _item_is_important_artifact(item),
                "condition": str(item.get("condition", "")),
                "authenticity_state": str(item.get("authenticity_state", "")),
                "trade_state": str(item.get("trade_state", "")),
                "asking_price_minor": int(item.get("asking_price_minor", 0) or 0),
                "metadata": metadata,
            }
        )
    return payload


def _currency_amount(agent_payload: dict[str, Any], *, config: dict[str, Any]) -> tuple[str, int, str]:
    wallet = agent_payload.get("wallet", {}) if isinstance(agent_payload.get("wallet", {}), dict) else {}
    if wallet:
        return (
            str(config.get("economy", {}).get("currency_item_id", "currency") or "currency"),
            int(wallet.get("amount_minor", 0) or 0),
            str(wallet.get("currency_symbol", config.get("economy", {}).get("currency_symbol", "")) or ""),
        )
    inventory = [item for item in agent_payload.get("inventory", []) or [] if isinstance(item, dict)]
    for item in inventory:
        metadata = item.get("metadata", {})
        if isinstance(metadata, dict) and bool(metadata.get("currency")):
            return (
                str(item.get("item_id", "currency") or "currency"),
                int(item.get("quantity", 0) or 0),
                str(metadata.get("currency_symbol", config.get("economy", {}).get("currency_symbol", "")) or ""),
            )
    for item in inventory:
        if str(item.get("item_id", "")).strip() == "gold":
            return "gold", int(item.get("quantity", 0) or 0), ""
    return (
        str(config.get("economy", {}).get("currency_item_id", "currency") or "currency"),
        0,
        str(config.get("economy", {}).get("currency_symbol", "")),
    )


def _agent_payload(
    agent: dict[str, Any],
    *,
    config: dict[str, Any],
    item_image_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    public_state = dict(agent.get("public_state", {})) if isinstance(agent.get("public_state", {}), dict) else {}
    currency_item_id, currency_amount, currency_symbol = _currency_amount(agent, config=config)
    status_effects = [dict(item) for item in agent.get("status_effects", []) if isinstance(item, dict)]
    runtime_memory = dict(public_state.get("runtime_memory", {})) if isinstance(public_state.get("runtime_memory", {}), dict) else {}
    wallet = agent.get("wallet", {}) if isinstance(agent.get("wallet", {}), dict) else default_wallet_payload(currency_amount, config=config)
    return {
        "agent_id": str(agent.get("agent_id", "")),
        "display_name": str(agent.get("display_name", "")),
        "gender_presentation": str(agent.get("gender_presentation", "")),
        "room_id": str(agent.get("room_id", "")),
        "coordinates": dict(agent.get("coordinates", {})),
        "status_effect_names": _agent_statuses(agent),
        "role_name": str(public_state.get("role_name", "")),
        "role_id": str(public_state.get("role_id", "")),
        "home_room_id": str(public_state.get("home_room_id", "")),
        "main_character": bool(public_state.get("main_character", False)),
        "appearance_prompt": str(agent.get("appearance_prompt", "")),
        "activity_directive": str(public_state.get("activity_directive", "")),
        "core_values": [str(item) for item in agent.get("core_values", []) if str(item).strip()],
        "personality_tags": [str(item) for item in public_state.get("personality_tags", []) if str(item).strip()],
        "wallet": wallet,
        "property_library": [dict(item) for item in agent.get("property_library", public_state.get("property_library", [])) if isinstance(item, dict)],
        "knowledge_assets": [dict(item) for item in agent.get("knowledge_assets", []) if isinstance(item, dict)],
        "public_state": public_state,
        "runtime_memory": runtime_memory,
        "private_notes": str(agent.get("private_notes", "")),
        "status_effects": status_effects,
        "inventory": _inventory_payload(agent, item_image_urls=item_image_urls),
        "currency_item_id": currency_item_id,
        "currency_amount": currency_amount,
        "currency_symbol": currency_symbol,
    }


def _room_capacity_payload(room: dict[str, Any], occupant_count: int, capacity_per_coordinate: int) -> dict[str, Any]:
    explicit = [dict(item) for item in room.get("footprint_tiles", []) if isinstance(item, dict)]
    if explicit:
        footprint_area = max(1, len(explicit))
    else:
        footprint_area = max(1, int(room.get("width_tiles", 1) or 1) * int(room.get("height_tiles", 1) or 1))
    capacity_estimate = max(1, footprint_area * max(1, capacity_per_coordinate))
    occupancy_density = occupant_count / max(1, capacity_estimate)
    if occupancy_density >= 1.0:
        pressure_band = "compressed"
    elif occupancy_density >= 0.7:
        pressure_band = "crowded"
    elif occupancy_density >= 0.4:
        pressure_band = "busy"
    else:
        pressure_band = "clear"
    return {
        "footprint_area": footprint_area,
        "capacity_estimate": capacity_estimate,
        "occupancy_density": round(occupancy_density, 3),
        "pressure_band": pressure_band,
    }


def _social_groups_payload(
    agents: list[dict[str, Any]],
    relationship_tensor: dict[str, dict[str, Any]],
    agent_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    adjacency: dict[str, set[str]] = {}
    for agent in agents:
        agent_id = str(agent.get("agent_id", "")).strip()
        if not agent_id:
            continue
        adjacency.setdefault(agent_id, set())
        runtime_memory = agent.get("runtime_memory", {})
        if isinstance(runtime_memory, dict):
            for other_id in runtime_memory.get("cohort_ids", []):
                other_key = str(other_id).strip()
                if other_key and other_key in agent_lookup:
                    adjacency[agent_id].add(other_key)
                    adjacency.setdefault(other_key, set()).add(agent_id)
    for source_id, targets in relationship_tensor.items():
        if source_id not in adjacency:
            continue
        for target_id, vector in (targets or {}).items():
            target_key = str(target_id).strip()
            if target_key not in adjacency or not isinstance(vector, dict):
                continue
            trust = int(vector.get("trust", 50))
            affection = int(vector.get("affection", 50))
            if trust >= 62 or affection >= 62:
                adjacency[source_id].add(target_key)
                adjacency[target_key].add(source_id)
    groups: list[dict[str, Any]] = []
    seen: set[str] = set()
    for agent_id in sorted(adjacency):
        if agent_id in seen:
            continue
        queue = deque([agent_id])
        component: list[str] = []
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            component.append(current)
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor not in seen:
                    queue.append(neighbor)
        if len(component) < 2:
            continue
        labels = [
            str(agent_lookup.get(member, {}).get("display_name", member))
            for member in component[:3]
        ]
        groups.append(
            {
                "group_id": "group_" + "_".join(component[:4]),
                "member_ids": component,
                "label": ", ".join(labels) + (f" +{len(component) - 3}" if len(component) > 3 else ""),
                "size": len(component),
            }
        )
    groups.sort(key=lambda item: (-int(item.get("size", 0)), str(item.get("group_id", ""))))
    return groups[:10]


def _relationship_edges(relationship_tensor: dict[str, dict[str, Any]], agent_lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source_id, targets in relationship_tensor.items():
        for target_id, vector in (targets or {}).items():
            if not isinstance(vector, dict) or source_id not in agent_lookup or target_id not in agent_lookup:
                continue
            pair = tuple(sorted((source_id, str(target_id))))
            if pair in seen:
                continue
            trust = int(vector.get("trust", 50))
            affection = int(vector.get("affection", 50))
            influence = int(vector.get("influence_fear", 0))
            reverse = relationship_tensor.get(target_id, {}).get(source_id, {})
            if isinstance(reverse, dict):
                trust = round((trust + int(reverse.get("trust", 50))) / 2)
                affection = round((affection + int(reverse.get("affection", 50))) / 2)
                influence = round((influence + int(reverse.get("influence_fear", 0))) / 2)
            if trust == 50 and affection == 50 and influence == 0:
                continue
            weight = trust + affection - abs(influence)
            label = f"T {trust} | A {affection} | F {influence}"
            edges.append(
                {
                    "from": source_id,
                    "to": str(target_id),
                    "trust": trust,
                    "affection": affection,
                    "influence_fear": influence,
                    "weight": weight,
                    "label": label,
                }
            )
            seen.add(pair)
    return sorted(edges, key=lambda edge: edge["weight"], reverse=True)


def _agent_id_number(agent_id: str) -> int:
    digits = "".join(ch for ch in str(agent_id) if ch.isdigit())
    if digits:
        return int(digits[-3:].lstrip("0") or "0")
    # Keep main-character style ids stable without relying on a trailing digit suffix.
    return sum(ord(ch) for ch in str(agent_id)) % 1000


def _neutral_relationship_tensor(agent_ids: list[str]) -> dict[str, dict[str, dict[str, int]]]:
    payload: dict[str, dict[str, dict[str, int]]] = {}
    for source_id in agent_ids:
        payload[source_id] = {}
        for target_id in agent_ids:
            if source_id == target_id:
                continue
            payload[source_id][target_id] = {"trust": 50, "affection": 50, "influence_fear": 0}
    return payload


def _fallback_map_grid(config: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "grid_shape": dict(config.get("space", {}).get("grid_shape", {})),
        "map_visual": dict(config.get("space", {}).get("map_visual", {})),
        "rooms": [dict(room) for room in config.get("space", {}).get("rooms", []) if isinstance(room, dict)],
        "initial_positions": {
            str(agent.get("agent_id", "")): dict(agent.get("coordinates", {}))
            for agent in agents
            if str(agent.get("agent_id", "")).strip()
        },
        "initial_room_ids": {
            str(agent.get("agent_id", "")): str(agent.get("room_id", ""))
            for agent in agents
            if str(agent.get("agent_id", "")).strip()
        },
    }

