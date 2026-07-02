from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .adjudicator_schemas import (
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    InventoryItemSpec,
    RelationshipVectorSpec,
)
from .foundation_schemas import GridPosition
from .jsonc_utils import dump_json
from .world_definition import default_wallet_payload
from .vertex_json_client import VertexJsonClient


class SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _format(template: str, values: dict[str, Any]) -> str:
    return str(template or "").format_map(SafeDict({k: str(v) for k, v in values.items()}))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _clean_property_asset(item: dict) -> dict[str, Any]:
    cleaned = {}
    if "knowledge_id" in item and "asset_name" not in item:
        cleaned["asset_name"] = str(item["knowledge_id"])
    else:
        cleaned["asset_name"] = str(item.get("asset_name", ""))
        
    if "topic" in item and "asset_type" not in item:
        cleaned["asset_type"] = str(item["topic"])
    else:
        cleaned["asset_type"] = str(item.get("asset_type", ""))
        
    if "description" in item:
        cleaned["description"] = str(item["description"])
    elif "summary" in item:
        cleaned["description"] = str(item["summary"])
    else:
        cleaned["description"] = str(item.get("description", ""))
        
    cleaned["story_use"] = str(item.get("story_use", ""))
    cleaned["metadata"] = dict(item.get("metadata", {}))
    return cleaned


def _clean_knowledge_asset(item: dict) -> dict[str, Any]:
    cleaned = {}
    if "asset_name" in item and "knowledge_id" not in item:
        cleaned["knowledge_id"] = str(item["asset_name"])
    else:
        cleaned["knowledge_id"] = str(item.get("knowledge_id", ""))
        
    if "asset_type" in item and "topic" not in item:
        cleaned["topic"] = str(item["asset_type"])
    else:
        cleaned["topic"] = str(item.get("topic", ""))
        
    if "summary" in item:
        cleaned["summary"] = str(item["summary"])
    elif "description" in item:
        cleaned["summary"] = str(item["description"])
    else:
        cleaned["summary"] = str(item.get("summary", ""))
        
    cleaned["confidence"] = int(_safe_int(item.get("confidence"), 80))
    cleaned["metadata"] = dict(item.get("metadata", {}))
    return cleaned


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _room_cells_from_config(room: dict[str, Any]) -> list[GridPosition]:
    explicit = [
        GridPosition.model_validate(tile)
        for tile in room.get("footprint_tiles", [])
        if isinstance(tile, dict)
    ]
    if explicit:
        return explicit
    width = max(1, int(room.get("width_tiles", 1) or 1))
    height = max(1, int(room.get("height_tiles", 1) or 1))
    origin_x = int(room.get("x") if "x" in room else room.get("coordinates", {}).get("x", 0))
    origin_y = int(room.get("y") if "y" in room else room.get("coordinates", {}).get("y", 0))
    origin_z = int(room.get("z") if "z" in room else room.get("coordinates", {}).get("z", 0))
    cells: list[GridPosition] = []
    for dx in range(width):
        for dy in range(height):
            cells.append(GridPosition(x=origin_x + dx, y=origin_y + dy, z=origin_z))
    return cells


def _room_spawn_cells(room: dict[str, Any]) -> list[GridPosition]:
    cells = _room_cells_from_config(room)
    obstacles = {
        (int(item.get("x", 0)), int(item.get("y", 0)), int(item.get("z", 0)))
        for item in room.get("obstacles", [])
        if isinstance(item, dict)
    }
    candidates = [
        cell
        for cell in cells
        if (cell.x, cell.y, cell.z) not in obstacles
    ]
    return candidates or cells


def _spawn_coordinate_for_room(room: dict[str, Any], index_zero: int = 0) -> GridPosition:
    candidates = _room_spawn_cells(room)
    return candidates[index_zero % len(candidates)]


def _runner_config(config: dict[str, Any]) -> dict[str, Any]:
    runner = config.get("runner", {})
    return runner if isinstance(runner, dict) else {}


def _world_label(config: dict[str, Any]) -> str:
    meta = config.get("scenario_meta", {})
    return str(
        _runner_config(config).get("world_label")
        or meta.get("world_name")
        or meta.get("world_id")
        or "simulation world"
    )


def _domain_label(config: dict[str, Any]) -> str:
    meta = config.get("scenario_meta", {})
    return str(
        _runner_config(config).get("domain_label")
        or meta.get("world_name")
        or meta.get("world_id")
        or "simulation world"
    )


def _story_filename(config: dict[str, Any]) -> str:
    return str(_runner_config(config).get("story_filename", "story.jsonl")).strip() or "story.jsonl"


def _run_name(config: dict[str, Any]) -> str:
    return str(_runner_config(config).get("run_name", "agora_simulation_run")).strip() or "agora_simulation_run"


def _agent_id_prefix(config: dict[str, Any]) -> str:
    return str(_runner_config(config).get("agent_id_prefix", "agent")).strip() or "agent"


def _image_generation_config(config: dict[str, Any]) -> dict[str, Any]:
    image_generation = config.get("image_generation", {})
    return image_generation if isinstance(image_generation, dict) else {}


def _catalog_by_id(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog = config.get("item_catalog", config.get("agent_generation", {}).get("item_catalog", []))
    if not isinstance(catalog, list) or not catalog:
        catalog = config.get("economy", {}).get("item_catalog", [])
    if not isinstance(catalog, list):
        return {}
    mapped: dict[str, dict[str, Any]] = {}
    for item in catalog:
        if isinstance(item, dict):
            item_id = str(item.get("item_id", "")).strip()
            if item_id:
                mapped[item_id] = dict(item)
    return mapped


def _inventory_item(
    catalog: dict[str, dict[str, Any]],
    item_id: str,
    quantity: int,
    *,
    raw_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_item = raw_item or {}
    spec = catalog.get(item_id, {})
    metadata = dict(spec.get("metadata", {}))
    metadata.update(dict(raw_item.get("metadata", {})))
    item_type = str(spec.get("item_type", raw_item.get("item_type", "general"))).strip() or "general"
    description = str(spec.get("description", raw_item.get("description", f"A {item_id} inside the world."))).strip()
    return {
        "item_id": item_id,
        "name": str(raw_item.get("name", spec.get("name", ""))).strip(),
        "quantity": int(quantity),
        "mass": float(spec.get("mass", raw_item.get("mass", 0.1))),
        "description": description,
        "image_path": str(spec.get("image_path", raw_item.get("image_path", ""))).strip(),
        "image_prompt": str(spec.get("image_prompt", raw_item.get("image_prompt", ""))).strip(),
        "condition": str(raw_item.get("condition", "mint")).strip() or "mint",
        "authenticity_state": str(raw_item.get("authenticity_state", "genuine")).strip() or "genuine",
        "trade_state": str(raw_item.get("trade_state", "free")).strip() or "free",
        "asking_price_minor": int(raw_item.get("asking_price_minor", spec.get("price", 0))),
        "metadata": metadata,
    }


def _currency_item(config: dict[str, Any], quantity: int) -> dict[str, Any]:
    currency_id = str(config.get("economy", {}).get("currency_item_id", "currency") or "currency")
    return {
        "item_id": currency_id,
        "quantity": int(quantity),
        "mass": 0.0,
        "description": "Circulating currency tokens used in the scenario local market.",
        "image_path": "",
        "image_prompt": "",
        "condition": "genuine",
        "authenticity_state": "genuine",
        "trade_state": "free",
        "asking_price_minor": 1,
        "metadata": {
            "currency": True,
            "currency_symbol": str(config.get("economy", {}).get("currency_symbol", "")),
            "name": str(config.get("economy", {}).get("currency_name", "Local Currency")),
        },
    }


def _starting_wallet_range(config: dict[str, Any]) -> tuple[int, int]:
    economy = config.get("economy", {})
    if not isinstance(economy, dict):
        return 1000, 10000
    min_val = int(economy.get("starting_wallet_minor_min", 1000))
    max_val = int(economy.get("starting_wallet_minor_max", 10000))
    return min_val, max(min_val, max_val)


def _role_sequence(config: dict[str, Any]) -> list[dict[str, Any]]:
    roles = config.get("agent_generation", {}).get("role_groups", [])
    result: list[dict[str, Any]] = []
    for role in roles:
        if not isinstance(role, dict):
            continue
        result.extend([role] * int(role.get("count", 0)))
    expected = max(0, int(config.get("runtime", {}).get("agent_count", len(result))) - len(_main_character_specs(config)))
    if len(result) != expected:
        raise ValueError(f"role count total {len(result)} does not match non-main runtime.agent_count {expected}")
    return result


def _room_for_agent(config: dict[str, Any], index_zero: int) -> dict[str, Any]:
    rooms = [dict(room) for room in config.get("space", {}).get("rooms", []) if isinstance(room, dict)]
    if not rooms:
        raise ValueError("space.rooms must not be empty")
    return rooms[index_zero % len(rooms)]


def _room_by_id(config: dict[str, Any], room_id: str, *, default_index: int = 0) -> dict[str, Any]:
    rooms = [dict(room) for room in config.get("space", {}).get("rooms", []) if isinstance(room, dict)]
    for room in rooms:
        if str(room.get("room_id", "")) == str(room_id):
            return room
    return _room_for_agent(config, default_index)


def _main_character_specs(config: dict[str, Any]) -> list[dict[str, Any]]:
    value = config.get("main_characters", config.get("agent_generation", {}).get("main_characters", []))
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict) and bool(item.get("enabled", True))]


def _main_character_ids(config: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for spec in _main_character_specs(config):
        if not bool(spec.get("always_activate", True)):
            continue
        agent_id = str(spec.get("agent_id", "")).strip()
        if agent_id and agent_id not in result:
            result.append(agent_id)
    result.extend(
        str(item).strip()
        for item in config.get("activation", {}).get("always_activate_agent_ids", [])
        if str(item).strip()
    )
    deduped: list[str] = []
    for agent_id in result:
        if agent_id not in deduped:
            deduped.append(agent_id)
    return deduped


def _force_cinematic_agent_ids(config: dict[str, Any]) -> list[str]:
    longlive = config.get("longlive", {})
    if not isinstance(longlive, dict):
        longlive = {}
    result: list[str] = []
    if bool(longlive.get("force_cinematic_for_main_characters", False)):
        result.extend(_main_character_ids(config))
    for key in ("force_cinematic_agent_ids", "always_cinematic_agent_ids"):
        values = longlive.get(key, [])
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            result.extend(str(item).strip() for item in values if str(item).strip())
    deduped: list[str] = []
    for agent_id in result:
        if agent_id and agent_id not in deduped:
            deduped.append(agent_id)
    return deduped


def _main_character_payload(config: dict[str, Any], spec: dict[str, Any], index_zero: int) -> dict[str, Any]:
    catalog = _catalog_by_id(config)
    agent_id = str(spec.get("agent_id", "")).strip() or f"{_agent_id_prefix(config)}_main_{index_zero + 1:02d}"
    room = _room_by_id(config, str(spec.get("home_room_id", spec.get("room_id", ""))), default_index=index_zero)
    gender = str(spec.get("gender_presentation", spec.get("gender", "unspecified")))
    display_name = str(spec.get("display_name", agent_id))
    role_id = str(spec.get("role_id", "main_character"))
    role_name = str(spec.get("role_name", "Main Character"))
    spawn = _spawn_coordinate_for_room(room, index_zero)
    inventory: list[dict[str, Any]] = []
    currency_quantity = _safe_int(spec.get("currency_quantity", spec.get("starting_currency", 12000)), 12000)
    wallet = default_wallet_payload(currency_quantity, config=config)
    inventory.append(_currency_item(config, currency_quantity))
    for item in spec.get("inventory", []) or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id", "")).strip()
        if item_id:
            inventory.append(_inventory_item(catalog, item_id, _safe_int(item.get("quantity", 1), 1), raw_item=item))
    return {
        "agent_id": agent_id,
        "agent_number": int(spec.get("agent_number", index_zero + 1) or index_zero + 1),
        "display_name": display_name,
        "gender_presentation": gender,
        "appearance_prompt": str(spec.get("appearance_prompt", "")),
        "core_values": [str(item) for item in spec.get("core_values", [])],
        "wallet": wallet,
        "inventory": inventory,
        "property_library": [_clean_property_asset(item) for item in spec.get("property_library", []) if isinstance(item, dict)],
        "knowledge_assets": [_clean_knowledge_asset(item) for item in spec.get("knowledge_assets", []) if isinstance(item, dict)],
        "coordinates": spawn.model_dump(),
        "room_id": str(room.get("room_id", "")),
        "status_effects": [],
        "public_state": {
            "role_id": role_id,
            "role_name": role_name,
            "home_room_id": str(room.get("room_id", "")),
            "main_character": True,
            "main_character_archetype": str(spec.get("archetype", role_name)),
            "agent_number": int(spec.get("agent_number", index_zero + 1) or index_zero + 1),
            "activity_directive": str(spec.get("activity_directive", "")),
            "always_activate": bool(spec.get("always_activate", True)),
            "item_prices": {
                item_id: int(item_spec.get("price", 0))
                for item_id, item_spec in catalog.items()
            },
        },
        "private_notes": str(spec.get("private_notes", f"Main character in {_world_label(config)}: {role_name}.")),
    }


def _variation_token(config: dict[str, Any], key: str, index_zero: int) -> str:
    variation = config.get("agent_generation", {}).get("visual_variation", {})
    if not isinstance(variation, dict):
        return ""
    values = variation.get(key, [])
    if isinstance(values, str):
        values = [values]
    pool = [str(item).strip() for item in values if str(item).strip()]
    if not pool:
        return ""
    
    # Deterministic seeding based on world definition seed parameters and agent index
    world_def = config.get("world_definition", {})
    world_seed = world_def.get("world_definition_seed", {})
    seed_str = str(world_seed.get("world_seed_string", "")) or str(world_seed.get("world_seed", "default_seed"))
    world_id = str(world_seed.get("world_id", "world"))
    seed_phrase = f"{world_id}_{seed_str}_{index_zero}_{key}"
    
    import random
    rng = random.Random(seed_phrase)
    return rng.choice(pool)


def _display_name_for_agent(
    config: dict[str, Any],
    *,
    idx: int,
    used_names: set[str],
) -> str:
    agent_generation = config.get("agent_generation", {})
    if not isinstance(agent_generation, dict):
        agent_generation = {}
    name_mode = str(agent_generation.get("name_mode", "legacy_pair")).strip() or "legacy_pair"
    include_index = bool(agent_generation.get("name_include_index", name_mode == "legacy_pair"))
    given_names = [str(item).strip() for item in agent_generation.get("given_names", []) if str(item).strip()]
    family_names = [str(item).strip() for item in agent_generation.get("family_names", []) if str(item).strip()]
    if name_mode != "legacy_pair" and given_names and family_names:
        combo_index = idx - 1
        given_name = given_names[combo_index % len(given_names)]
        family_name = family_names[(combo_index // max(1, len(given_names))) % len(family_names)]
        candidate = f"{given_name} {family_name}".strip()
    else:
        prefixes = [str(item).strip() for item in agent_generation.get("name_prefixes", ["Agent"]) if str(item).strip()]
        suffixes = [str(item).strip() for item in agent_generation.get("name_suffixes", ["Member"]) if str(item).strip()]
        prefix = prefixes[(idx - 1) % len(prefixes)]
        suffix = suffixes[((idx - 1) // max(1, len(prefixes))) % len(suffixes)]
        candidate = f"{prefix} {suffix}".strip()
    if include_index:
        candidate = f"{candidate} {idx:03d}".strip()
    if candidate in used_names:
        candidate = f"{candidate} {idx:03d}".strip()
    used_names.add(candidate)
    return candidate


def _build_agent_payloads(config: dict[str, Any]) -> list[dict[str, Any]]:
    rng = random.Random(int(config.get("runtime", {}).get("seed", 42)))
    catalog = _catalog_by_id(config)
    min_wallet_minor, max_wallet_minor = _starting_wallet_range(config)
    agent_prefix = _agent_id_prefix(config)
    role_items = _role_sequence(config)
    payloads: list[dict[str, Any]] = []
    used_names = {
        str(spec.get("display_name", "")).strip()
        for spec in _main_character_specs(config)
        if str(spec.get("display_name", "")).strip()
    }

    for idx, role in enumerate(role_items, start=1):
        room = _room_by_id(config, str(role.get("home_room_id", "")), default_index=idx - 1)
        agent_id = f"{agent_prefix}_{idx:03d}"
        display_name = _display_name_for_agent(config, idx=idx, used_names=used_names)
        spawn = _spawn_coordinate_for_room(room, idx - 1)
        gender_options = [str(x) for x in role.get("gender_options", []) if str(x).strip()]
        gender = gender_options[(idx - 1) % len(gender_options)] if gender_options else "unspecified"
        appearance = _format(
            str(role.get("appearance_template", "")),
            {
                "display_name": display_name,
                "role_name": role.get("role_name", ""),
                "gender_presentation": gender,
                "age_band": _variation_token(config, "age_bands", idx - 1),
                "skin_tone": _variation_token(config, "skin_tones", idx - 1),
                "hair_color": _variation_token(config, "hair_colors", idx - 1),
                "hair_style": _variation_token(config, "hair_styles", idx - 1),
                "body_type": _variation_token(config, "body_types", idx - 1),
                "signature_accessory": _variation_token(config, "signature_accessories", idx - 1),
                "silhouette_trait": _variation_token(config, "silhouette_traits", idx - 1),
            },
        )
        wallet_amount = rng.randint(min_wallet_minor, max_wallet_minor)
        inventory = [_currency_item(config, wallet_amount)]
        
        role_inventory_pool = [item for item in role.get("inventory", []) or [] if isinstance(item, dict) and str(item.get("item_id", "")).strip()]
        
        # Sample items to prevent all agents in a role group from being identical clones
        if len(role_inventory_pool) <= 5:
            sampled_items = role_inventory_pool
        else:
            sample_size = rng.randint(5, min(10, len(role_inventory_pool)))
            sorted_pool = sorted(role_inventory_pool, key=lambda x: str(x.get("item_id", "")))
            sampled_items = rng.sample(sorted_pool, sample_size)
            
        for item in sampled_items:
            item_id = str(item.get("item_id", "")).strip()
            inventory.append(_inventory_item(catalog, item_id, _safe_int(item.get("quantity", 1), 1), raw_item=item))

        payloads.append(
            {
                "agent_id": agent_id,
                "agent_number": idx,
                "display_name": display_name,
                "gender_presentation": gender,
                "appearance_prompt": appearance,
                "core_values": [str(x) for x in role.get("core_values", [])],
                "wallet": default_wallet_payload(wallet_amount, config=config),
                "inventory": inventory,
                "property_library": [dict(item) for item in role.get("property_library", []) if isinstance(item, dict)],
                "knowledge_assets": [dict(item) for item in role.get("knowledge_assets", []) if isinstance(item, dict)],
                "coordinates": spawn.model_dump(),
                "room_id": str(room.get("room_id", "")),
                "status_effects": [],
                "public_state": {
                    "role_id": str(role.get("role_id", "")),
                    "role_name": str(role.get("role_name", "")),
                    "home_room_id": str(room.get("room_id", "")),
                    "agent_number": idx,
                    "activity_directive": str(role.get("activity_directive", "")),
                    "wallet_currency_code": default_wallet_payload(wallet_amount, config=config)["currency_code"],
                    "item_prices": {
                        item_id: int(spec.get("price", 0))
                        for item_id, spec in catalog.items()
                    },
                },
                "private_notes": (
                    f"Acts as {role.get('role_name', 'member')} in {_world_label(config)} and prioritizes "
                    + ", ".join(str(x) for x in role.get("core_values", []))
                    + (f". Directive: {role.get('activity_directive', '')}" if str(role.get("activity_directive", "")).strip() else ".")
                ),
            }
        )

    for main_index, spec in enumerate(_main_character_specs(config), start=len(payloads)):
        payloads.append(_main_character_payload(config, spec, main_index))

    expected_total = int(config.get("runtime", {}).get("agent_count", len(payloads)))
    if len(payloads) != expected_total:
        raise ValueError(f"built {len(payloads)} agents but runtime.agent_count is {expected_total}")
    return payloads


def _vertex_agent_profile_payloads(
    client: VertexJsonClient,
    config: dict[str, Any],
    base_payloads: list[dict[str, Any]],
    *,
    profile_cache_dir: Path | None = None,
    live_agents_dir: Path | None = None,
) -> list[dict[str, Any]]:
    schema = {
        "display_name": "string, <= 32 chars",
        "gender_presentation": "string, <= 24 chars",
        "appearance_prompt": "string, <= 260 chars, video prompt only",
        "private_notes": "string, <= 120 chars",
        "personality_tags": ["1-4 short strings"],
        "core_values": ["1-3 short strings"],
        "inventory_item_ids": ["1-4 item_ids from catalog to equip the agent"],
    }
    catalog = _catalog_by_id(config)
    world_context = {
        "scenario_meta": config.get("scenario_meta", {}),
        "space": config.get("space", {}),
        "economy": config.get("economy", {}),
        "agent_generation_policy": {
            "distribution": config.get("agent_generation", {}).get("distribution", ""),
            "role_groups": config.get("agent_generation", {}).get("role_groups", []),
            "profile_diversity_policy": config.get("agent_generation", {}).get("profile_diversity_policy", ""),
        },
        "item_catalog": list(catalog.keys()),
    }
    generated_payloads: list[dict[str, Any]] = []
    if profile_cache_dir is not None:
        profile_cache_dir.mkdir(parents=True, exist_ok=True)
    if live_agents_dir is not None:
        live_agents_dir.mkdir(parents=True, exist_ok=True)
    for base in base_payloads:
        ordinal = len(generated_payloads) + 1
        if ordinal == 1 or ordinal % 10 == 0 or ordinal == len(base_payloads):
            print(f"[PROFILE_API] generating {ordinal}/{len(base_payloads)}", flush=True)
        public_state = dict(base.get("public_state", {}))
        is_main_character = bool(public_state.get("main_character", False))
        stage = "main_character_generation" if is_main_character else "agent_profile_generation"
        extra_instruction = ""
        if is_main_character:
            extra_instruction = (
                "This is a main character. Make the profile vivid, protagonist-grade, and aligned with "
                f"the activity directive: {public_state.get('activity_directive', '')}. "
                "Do not make them passive.\n"
            )
        seed_data = config.get("world_definition", {}).get("world_definition_seed", {})
        world_locale = str(seed_data.get("locale", "zh_CN") or "zh_CN").strip()
        world_tone = str(seed_data.get("tone", "") or "").strip()
        prompt = (
            f"Generate compact concrete agent profile parameters for this fixed JSON world: {_world_label(config)}.\n"
            "Do not alter agent_id, room_id, coordinates, or core world rules.\n"
            + extra_instruction
            + f"The world locale is '{world_locale}', and the tone is '{world_tone}'. Create an extremely authentic, unique, flavor-rich, and culturally fitting `display_name` that perfectly matches the character's role and background in this specific locale (e.g., if locale is 'zh_CN', use realistic Chinese names or market nicknames like '张掌柜', '马老板', '赵胖子', '王铁嘴' instead of generic or Westernized placeholders like 'Agent 001' or 'Shopkeeper'). Do not use generic placeholder names.\n"
            + "Select 1 to 4 appropriate `inventory_item_ids` from the item_catalog to equip the agent for their role.\n"
            + "The appearance and gender presentation must fit the role, core values, and any existing description.\n"
            "The appearance_prompt is for video generation only; do not write a discussion prompt.\n"
            f"Use this world tone and vocabulary when helpful: {_domain_label(config)}.\n"
            + (
                f"Maintain strong cross-cast diversity: {str(config.get('agent_generation', {}).get('profile_diversity_policy', '')).strip()}\n"
                if str(config.get("agent_generation", {}).get("profile_diversity_policy", "")).strip()
                else ""
            )
            +
            "Return minified JSON only. Keep every string within its schema length. Do not add line breaks inside values.\n"
            f"world_context: {_json_dumps(world_context)}\n"
            f"base_agent: {_json_dumps(base)}"
        )
        generated = client.generate_compact_json(
            system_instruction="You generate strict JSON agent profile parameters for a fixed simulation world.",
            prompt=prompt,
            schema=schema,
            stage=stage,
        )
        api_source = "vertex_api"
        time.sleep(1.2)
        payload = dict(base)
        for key in ("display_name", "gender_presentation", "appearance_prompt", "private_notes"):
            value = str(generated.get(key, "")).strip()
            if value:
                payload[key] = value
        values = generated.get("core_values")
        if isinstance(values, list) and values:
            payload["core_values"] = [str(item) for item in values if str(item).strip()][:5]
        
        inventory_ids = generated.get("inventory_item_ids")
        if isinstance(inventory_ids, list) and inventory_ids:
            new_inventory = list(payload.get("inventory", []))
            existing_ids = {str(item.get("item_id", "")).strip() for item in new_inventory if isinstance(item, dict)}
            for item_id in inventory_ids:
                item_id_str = str(item_id).strip()
                if item_id_str in catalog and item_id_str not in existing_ids:
                    new_inventory.append(_inventory_item(catalog, item_id_str, 1))
            if new_inventory:
                payload["inventory"] = new_inventory

        public_state["api_profile_source"] = api_source
        public_state["api_profile_stage"] = stage
        tags = generated.get("personality_tags")
        if isinstance(tags, list):
            public_state["personality_tags"] = [str(item) for item in tags if str(item).strip()][:8]
        payload["public_state"] = public_state
        AgentRuntimeProfileSpec.model_validate(payload)
        agent_id = str(payload["agent_id"])
        if live_agents_dir is not None:
            dump_json(live_agents_dir / f"{agent_id}.json", payload)
        if profile_cache_dir is not None:
            dump_json(
                profile_cache_dir / f"{agent_id}.json",
                {
                    "agent_id": agent_id,
                    "generated_at": _now_iso(),
                    "source": "vertex_api",
                    "base_agent": base,
                    "api_profile": generated,
                    "runtime_agent": payload,
                },
            )
            _append_jsonl(
                profile_cache_dir / "profile_generation_index.jsonl",
                {
                    "agent_id": agent_id,
                    "ordinal": ordinal,
                    "status": "written",
                    "runtime_agent_path": str(live_agents_dir / f"{agent_id}.json") if live_agents_dir is not None else "",
                    "cache_path": str(profile_cache_dir / f"{agent_id}.json"),
                },
            )
        generated_payloads.append(payload)
    return generated_payloads


def _inventory_generation_config(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("inventory_generation", config.get("agent_generation", {}).get("inventory_generation", {}))
    return value if isinstance(value, dict) else {}


def _merge_inventory_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in items:
        try:
            item = InventoryItemSpec.model_validate(raw).model_dump()
        except Exception:
            continue
        item_id = str(item.get("item_id", "")).strip()
        if not item_id:
            continue
        if item_id not in merged:
            merged[item_id] = item
            order.append(item_id)
        else:
            merged[item_id]["quantity"] = int(merged[item_id].get("quantity", 0)) + int(item.get("quantity", 0))
            for key in ("description", "image_path", "image_prompt"):
                if not merged[item_id].get(key) and item.get(key):
                    merged[item_id][key] = item[key]
            metadata = dict(merged[item_id].get("metadata", {}))
            metadata.update(dict(item.get("metadata", {})))
            merged[item_id]["metadata"] = metadata
    return [merged[item_id] for item_id in order if int(merged[item_id].get("quantity", 0)) > 0]


def _vertex_initial_inventory_payloads(
    client: VertexJsonClient,
    config: dict[str, Any],
    payloads: list[dict[str, Any]],
    *,
    inventory_cache_dir: Path | None = None,
    live_agents_dir: Path | None = None,
) -> list[dict[str, Any]]:
    inv_config = _inventory_generation_config(config)
    if not bool(inv_config.get("enabled", False)):
        return payloads
    catalog = _catalog_by_id(config)
    allowed_item_ids = [
        str(item_id)
        for item_id in inv_config.get("allowed_item_ids", list(catalog.keys()))
        if str(item_id) in catalog
    ]
    if not allowed_item_ids:
        return payloads
    # Dynamic Universal scale up for dense inventories (e.g. up to 30 distinct items, up to 50 quantity per item)
    max_items = max(30, _safe_int(inv_config.get("max_distinct_items_per_agent", 30), 30))
    max_quantity = max(50, _safe_int(inv_config.get("max_quantity_per_item", 50), 50))
    preserve_existing = bool(inv_config.get("preserve_existing_inventory", True))
    schema = {
        "inventory_items": [
            {
                "item_id": "string, must be one of allowed_item_ids",
                "quantity": f"integer from 1 to {max_quantity}",
                "reason": "string, <= 100 chars, why this agent owns it",
            }
        ],
        "property_library": [
            {
                "asset_name": "string, <= 40 chars",
                "asset_type": "string, e.g. gear, document, token, debt, heirloom",
                "description": "string, <= 160 chars",
                "story_use": "string, <= 120 chars",
            }
        ],
        "knowledge_assets": [
            {
                "knowledge_id": "string, <= 40 chars",
                "topic": "string, <= 40 chars",
                "summary": "string, <= 160 chars",
                "confidence": "integer from 0 to 100",
            }
        ],
        "private_inventory_notes": "string, <= 180 chars",
    }
    context = {
        "scenario_meta": config.get("scenario_meta", {}),
        "domain_label": _domain_label(config),
        "economy": config.get("economy", {}),
        "inventory_generation": inv_config,
        "allowed_item_ids": allowed_item_ids,
        "allowed_catalog": {item_id: catalog[item_id] for item_id in allowed_item_ids},
    }
    if inventory_cache_dir is not None:
        inventory_cache_dir.mkdir(parents=True, exist_ok=True)
    generated_payloads: list[dict[str, Any]] = []
    for index, base in enumerate(payloads, start=1):
        if index == 1 or index % 10 == 0 or index == len(payloads):
            print(f"[INVENTORY_API] generating {index}/{len(payloads)}", flush=True)
        prompt = (
            "Generate a role-appropriate initial property library and actionable inventory items for this simulation agent.\n"
            "Use only allowed_item_ids for inventory_items. Do not invent item_id values. "
            f"Return at most {max_items} distinct inventory_items and quantities no larger than {max_quantity}. "
            "Scale the inventory density based on the agent's role group and activity: A merchant, stall owner, or trader should have a VERY DENSE, diverse stock of goods (20 to 40 distinct items, with quantities ranging from 5 to 100 items depending on value to simulate real trade volume). EVERYONE in this world should carry a diverse set of items, so even a standard civilian, coordinator, or traveler must have at least 8 to 15 distinct items.\n"
            "The property_library may describe non-actionable possessions, debts, rumors, titles, or heirlooms as text.\n"
            "Keep it consistent with the agent's role, personality, main-character directive when present, and the fixed JSON world.\n"
            f"context: {_json_dumps(context)}\n"
            f"agent: {_json_dumps(base)}"
        )
        try:
            generated = client.generate_json(
                system_instruction="You generate strict JSON initial inventory/property libraries for a fixed simulation world.",
                prompt=prompt,
                schema=schema,
                stage="initial_inventory_generation",
            )
            api_source = "vertex_api"
            time.sleep(1.2)
        except Exception as exc:
            print(f"[INVENTORY_FALLBACK] agent={base.get('agent_id')} error={exc}. Skipping inventory enrichment.", flush=True)
            generated = {}
            api_source = "fallback_base"
        new_items: list[dict[str, Any]] = []
        for raw in generated.get("inventory_items", []) if isinstance(generated.get("inventory_items", []), list) else []:
            if not isinstance(raw, dict):
                continue
            item_id = str(raw.get("item_id", "")).strip()
            if item_id not in catalog or item_id not in allowed_item_ids:
                continue
            quantity = max(1, min(max_quantity, _safe_int(raw.get("quantity", 1), 1)))
            item = _inventory_item(catalog, item_id, quantity)
            metadata = dict(item.get("metadata", {}))
            metadata["inventory_generation_reason"] = str(raw.get("reason", ""))[:120]
            item["metadata"] = metadata
            new_items.append(item)
            if len(new_items) >= max_items:
                break
        payload = dict(base)
        existing = list(payload.get("inventory", [])) if preserve_existing else []
        payload["inventory"] = _merge_inventory_items(existing + new_items)
        payload["property_library"] = [_clean_property_asset(item) for item in generated.get("property_library", []) if isinstance(item, dict)][:8]
        payload["knowledge_assets"] = [_clean_knowledge_asset(item) for item in generated.get("knowledge_assets", []) if isinstance(item, dict)][:8]
        public_state = dict(payload.get("public_state", {}))
        property_library = generated.get("property_library", [])
        if isinstance(property_library, list):
            public_state["property_library"] = [_clean_property_asset(item) for item in property_library if isinstance(item, dict)][:8]
        public_state["inventory_generation_source"] = api_source
        payload["public_state"] = public_state
        note = str(generated.get("private_inventory_notes", "")).strip()
        if note:
            payload["private_notes"] = (str(payload.get("private_notes", "")) + " Inventory: " + note)[:500]
        AgentRuntimeProfileSpec.model_validate(payload)
        generated_payloads.append(payload)
        agent_id = str(payload["agent_id"])
        if live_agents_dir is not None:
            dump_json(live_agents_dir / f"{agent_id}.json", payload)
        if inventory_cache_dir is not None:
            dump_json(
                inventory_cache_dir / f"{agent_id}.json",
                {
                    "agent_id": agent_id,
                    "generated_at": _now_iso(),
                    "source": "vertex_api",
                    "api_inventory": generated,
                    "runtime_agent": payload,
                },
            )
    return generated_payloads
