from __future__ import annotations

import json
from typing import Any


DEFAULT_CURRENCY_CODE = "CNY"
DEFAULT_CURRENCY_SYMBOL = "yuan"
DEFAULT_CURRENCY_MINOR_UNIT = "fen"
DEFAULT_CURRENCY_ITEM_ID = "cny_cash"


def _slug(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(text or "")).strip("_") or "world"


def _tokens(*parts: Any) -> set[str]:
    text = " ".join(str(part or "") for part in parts).lower()
    current: list[str] = []
    results: list[str] = []
    for ch in text:
        if ch.isalnum():
            current.append(ch)
            continue
        if current:
            results.append("".join(current))
            current = []
    if current:
        results.append("".join(current))
    return {item for item in results if item}


def _dedupe(values: list[Any], *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(text)
        if limit is not None and len(deduped) >= limit:
            break
    return deduped


def _copy(payload: Any) -> Any:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _load_registry_json(filename: str) -> Any:
    from pathlib import Path
    path = Path(__file__).parent / "data" / "registries" / filename
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to load registry file {filename}: {e}") from e


COMMON_TAXONOMY: list[dict[str, Any]] = _load_registry_json("taxonomy.json")
COMPONENT_KIT_REGISTRY: dict[str, dict[str, Any]] = _load_registry_json("component_kits.json")
FRONTEND_AFFORDANCE_REGISTRY: dict[str, dict[str, Any]] = _load_registry_json("frontend_affordances.json")
ASSET_PROMPT_KIT_REGISTRY: dict[str, dict[str, Any]] = _load_registry_json("asset_prompt_kits.json")
ECONOMY_POLICY_REGISTRY: dict[str, dict[str, Any]] = _load_registry_json("economy_policies.json")
ITEM_COLLECTION_REGISTRY: dict[str, dict[str, Any]] = _load_registry_json("item_collections.json")
INVENTORY_LAYER_POLICY_REGISTRY: dict[str, dict[str, Any]] = _load_registry_json("inventory_layer_policies.json")
ROLE_ITEM_POLICY_REGISTRY: dict[str, dict[str, Any]] = _load_registry_json("role_item_policies.json")
PROPERTY_POLICY_REGISTRY: dict[str, list[dict[str, Any]]] = _load_registry_json("property_policies.json")
KNOWLEDGE_POLICY_REGISTRY: dict[str, list[dict[str, Any]]] = _load_registry_json("knowledge_policies.json")
WORLD_PRESET_LIBRARY: dict[str, dict[str, Any]] = _load_registry_json("world_presets.json")
WORLD_PROFILE_LIBRARY = WORLD_PRESET_LIBRARY


def _trim_label(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _canonical_locale(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _resolve_registry_ref(raw_value: Any, *, registry: dict[str, Any], fallback: str) -> str:
    candidate = str(raw_value or "").strip()
    if candidate in registry:
        return candidate
    return fallback


def infer_world_profile(builder_spec: dict[str, Any], request: dict[str, Any] | None = None) -> str:
    del request
    world_seed = dict(builder_spec.get("world_seed", {})) if isinstance(builder_spec.get("world_seed", {}), dict) else {}
    preset_id = str(world_seed.get("preset_id", "")).strip()
    if preset_id in WORLD_PRESET_LIBRARY:
        return preset_id
    profile_id = str(world_seed.get("profile_id", "")).strip()
    if profile_id in WORLD_PRESET_LIBRARY:
        return profile_id
    return "civic_social_world"


def resolve_world_seed(builder_spec: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = request
    raw_seed = dict(builder_spec.get("world_seed", {})) if isinstance(builder_spec.get("world_seed", {}), dict) else {}
    preset_id = infer_world_profile(builder_spec, None)
    base_preset = _copy(WORLD_PRESET_LIBRARY[preset_id])
    raw_kit_refs = dict(raw_seed.get("kit_refs", {})) if isinstance(raw_seed.get("kit_refs", {}), dict) else {}
    raw_policy_refs = dict(raw_seed.get("policy_refs", {})) if isinstance(raw_seed.get("policy_refs", {}), dict) else {}
    economy_policy_id = _resolve_registry_ref(raw_policy_refs.get("economy_policy_id"), registry=ECONOMY_POLICY_REGISTRY, fallback=str(base_preset["economy_policy_id"]))
    item_collection_id = _resolve_registry_ref(raw_policy_refs.get("item_collection_id"), registry=ITEM_COLLECTION_REGISTRY, fallback=str(base_preset["item_collection_id"]))
    inventory_layer_policy_id = _resolve_registry_ref(raw_policy_refs.get("inventory_layer_policy_id"), registry=INVENTORY_LAYER_POLICY_REGISTRY, fallback=str(base_preset["inventory_layer_policy_id"]))
    role_item_policy_id = _resolve_registry_ref(raw_policy_refs.get("role_item_policy_id"), registry=ROLE_ITEM_POLICY_REGISTRY, fallback=str(base_preset["role_item_policy_id"]))
    property_policy_id = _resolve_registry_ref(raw_policy_refs.get("property_policy_id"), registry=PROPERTY_POLICY_REGISTRY, fallback=str(base_preset["property_policy_id"]))
    knowledge_policy_id = _resolve_registry_ref(raw_policy_refs.get("knowledge_policy_id"), registry=KNOWLEDGE_POLICY_REGISTRY, fallback=str(base_preset["knowledge_policy_id"]))
    pixel_component_kit_id = _resolve_registry_ref(raw_kit_refs.get("pixel_component_kit_id"), registry=COMPONENT_KIT_REGISTRY, fallback=str(base_preset["pixel_component_kit_id"]))
    frontend_affordance_id = _resolve_registry_ref(raw_kit_refs.get("frontend_affordance_id"), registry=FRONTEND_AFFORDANCE_REGISTRY, fallback=str(base_preset["frontend_affordance_id"]))
    asset_prompt_kit_id = _resolve_registry_ref(raw_kit_refs.get("asset_prompt_kit_id"), registry=ASSET_PROMPT_KIT_REGISTRY, fallback=str(base_preset["asset_prompt_kit_id"]))
    economy_policy = _copy(ECONOMY_POLICY_REGISTRY[economy_policy_id])
    inventory_layer_policy = _copy(INVENTORY_LAYER_POLICY_REGISTRY[inventory_layer_policy_id])
    starting_wallet_minor = dict(raw_seed.get("starting_wallet_minor", {})) if isinstance(raw_seed.get("starting_wallet_minor", {}), dict) else {}
    if not starting_wallet_minor:
        starting_wallet_minor = dict(economy_policy.get("starting_wallet_minor", {"min": 1800, "max": 9000}))
    return {
        "seed_version": "world_seed_v2",
        "preset_id": preset_id,
        "profile_id": str(base_preset.get("profile_id", preset_id)),
        "locale": _canonical_locale(raw_seed.get("locale"), str(base_preset.get("locale", "en"))),
        "tone": _trim_label(raw_seed.get("tone"), str(builder_spec.get("genre") or preset_id)),
        "visual_direction": _trim_label(raw_seed.get("visual_direction"), str(builder_spec.get("visual_style") or preset_id)),
        "currency_code": str(economy_policy.get("currency_code", DEFAULT_CURRENCY_CODE)).strip() or DEFAULT_CURRENCY_CODE,
        "currency_symbol": str(economy_policy.get("currency_symbol", DEFAULT_CURRENCY_SYMBOL)).strip() or DEFAULT_CURRENCY_SYMBOL,
        "currency_minor_unit": str(economy_policy.get("currency_minor_unit", DEFAULT_CURRENCY_MINOR_UNIT)).strip() or DEFAULT_CURRENCY_MINOR_UNIT,
        "currency_item_id": str(economy_policy.get("currency_item_id", DEFAULT_CURRENCY_ITEM_ID)).strip() or DEFAULT_CURRENCY_ITEM_ID,
        "currency_name": str(economy_policy.get("currency_name", DEFAULT_CURRENCY_CODE)).strip() or DEFAULT_CURRENCY_CODE,
        "starting_wallet_minor": {
            "min": max(0, int(starting_wallet_minor.get("min", 0) or 0)),
            "max": max(0, int(starting_wallet_minor.get("max", starting_wallet_minor.get("min", 0)) or 0)),
        },
        "domain_label": _trim_label(raw_seed.get("domain_label"), str(base_preset.get("default_domain_label", ""))),
        "kit_refs": {
            "pixel_component_kit_id": pixel_component_kit_id,
            "frontend_affordance_id": frontend_affordance_id,
            "asset_prompt_kit_id": asset_prompt_kit_id,
        },
        "policy_refs": {
            "economy_policy_id": economy_policy_id,
            "item_collection_id": item_collection_id,
            "inventory_layer_policy_id": inventory_layer_policy_id,
            "role_item_policy_id": role_item_policy_id,
            "property_policy_id": property_policy_id,
            "knowledge_policy_id": knowledge_policy_id,
            "inventory_layers": _copy(inventory_layer_policy.get("inventory_layers", [])),
            "domain_label": _trim_label(raw_seed.get("domain_label"), str(base_preset.get("default_domain_label", ""))),
        },
        "base_preset": base_preset,
    }


def _room_archetype(room_spec: dict[str, Any]) -> str:
    spec_arch = str(room_spec.get("archetype", "")).strip().lower()
    valid_archetypes = {
        "market_exchange",
        "checkpoint",
        "logistics_yard",
        "lookout",
        "workshop",
        "archive_ritual",
        "rest_social",
        "training",
        "council",
        "commons",
    }
    if spec_arch in valid_archetypes:
        return spec_arch

    token_set = _tokens(
        room_spec.get("name", ""),
        room_spec.get("purpose", ""),
        room_spec.get("biome", ""),
        room_spec.get("decor_tags", []),
        room_spec.get("activity_tags", []),
    )
    if {"market", "trade", "bazaar", "vendor", "auction", "appraise", "broker"} & token_set:
        return "market_exchange"
    if {"checkpoint", "customs", "gate", "inspection", "permit"} & token_set:
        return "checkpoint"
    if {"dock", "quay", "cargo", "warehouse", "storage", "logistics", "supply"} & token_set:
        return "logistics_yard"
    if {"signal", "tower", "lookout", "navigation", "route"} & token_set:
        return "lookout"
    if {"forge", "repair", "workshop", "maker", "smith"} & token_set:
        return "workshop"
    if {"library", "archive", "ritual", "record", "observatory"} & token_set:
        return "archive_ritual"
    if {"tavern", "inn", "rest", "tea", "social"} & token_set:
        return "rest_social"
    if {"training", "spar", "drill", "practice"} & token_set:
        return "training"
    if {"council", "hall", "forum", "strategy", "meeting", "negotiation"} & token_set:
        return "council"
    return "commons"


def _profile_room_visual(room_spec: dict[str, Any], index: int, *, component_kit_id: str) -> dict[str, Any]:
    kit_id = str(component_kit_id)
    kit = COMPONENT_KIT_REGISTRY[kit_id]
    archetype = _room_archetype(room_spec)
    surfaces = kit["surface_by_archetype"]
    floor_tile, wall_tile = tuple(surfaces.get(archetype, surfaces["commons"]))
    decor = list(kit["decor_by_archetype"].get(archetype, kit["decor_by_archetype"]["commons"]))
    palettes = ["warm_lantern", "soft_mint", "focused_blue", "clear_day", "dusty_brown", "ember_orange", "low_lantern"]

    # Prioritize generated room overrides
    floor_tile = str(room_spec.get("floor_tile", "")).strip() or floor_tile
    wall_tile = str(room_spec.get("wall_tile", "")).strip() or wall_tile
    ambient_palette = str(room_spec.get("ambient_palette", "")).strip() or palettes[index % len(palettes)]

    spec_decor = [str(t).strip() for t in room_spec.get("decor_tags", []) if str(t).strip()]
    if spec_decor:
        # Prioritize generated decor tags entirely, falling back to registry decor only if we have room
        decor_tags = _dedupe(spec_decor + decor, limit=max(4, len(spec_decor)))
    else:
        decor_tags = _dedupe(decor, limit=4)

    return {
        "archetype": archetype,
        "floor_tile": floor_tile,
        "wall_tile": wall_tile,
        "decor_tags": decor_tags,
        "ambient_palette": ambient_palette,
    }


def _item_catalog_by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("item_id", "")).strip(): item
        for item in items
        if isinstance(item, dict) and str(item.get("item_id", "")).strip()
    }


def _select_role_items(selection_policy_id: str, role_name: str, activity: str, item_catalog: list[dict[str, Any]], seed_salt: str = "") -> list[str]:
    allowed = _item_catalog_by_id(item_catalog)
    token_set = _tokens(role_name, activity)
    candidates: list[str] = []
    policy = dict(ROLE_ITEM_POLICY_REGISTRY.get(selection_policy_id, {}))
    for rule in policy.get("keyword_rules", []):
        if not isinstance(rule, dict):
            continue
        match_any = {str(value).lower() for value in rule.get("match_any", []) if str(value).strip()}
        if match_any and match_any & token_set:
            candidates.extend([str(item_id).strip() for item_id in rule.get("items", []) if str(item_id).strip()])
    deduped = [item_id for item_id in _dedupe(candidates, limit=40) if item_id in allowed]
    if deduped:
        return deduped
    fallback = [str(item_id).strip() for item_id in policy.get("fallback", []) if str(item_id).strip()]
    res = [item_id for item_id in fallback if item_id in allowed][:40]
    if res:
        return res

    # Universal Dynamic Fallback: matching keywords inside custom generated items
    dynamic_candidates = []
    for item_id, item in allowed.items():
        item_tokens = _tokens(item.get("name", ""), item.get("description", ""))
        if item_tokens & token_set:
            dynamic_candidates.append(item_id)
    dynamic_res = [item_id for item_id in _dedupe(dynamic_candidates, limit=40)]
    if dynamic_res:
        return dynamic_res

    # Absolute Fallback: use a seeded random sample so agents get varied items
    import random
    rng = random.Random(f"{role_name}_{activity}_{seed_salt}_{len(allowed)}")
    keys = list(allowed.keys())
    rng.shuffle(keys)
    return keys[:40]


def _property_templates(property_policy_id: str, role_name: str) -> list[dict[str, Any]]:
    return [
        {
            **dict(template),
            "asset_name": str(template.get("asset_name", "{role_name} asset")).format(role_name=role_name),
        }
        for template in PROPERTY_POLICY_REGISTRY.get(property_policy_id, [])
        if isinstance(template, dict)
    ]


def _knowledge_templates(knowledge_policy_id: str, role_name: str) -> list[dict[str, Any]]:
    role_slug = _slug(role_name)
    return [
        {
            **dict(template),
            "knowledge_id": str(template.get("knowledge_id", "{role_slug}_knowledge")).format(role_slug=role_slug),
        }
        for template in KNOWLEDGE_POLICY_REGISTRY.get(knowledge_policy_id, [])
        if isinstance(template, dict)
    ]


def build_world_pipeline(builder_spec: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    resolved_seed = resolve_world_seed(builder_spec, request)
    preset_id = str(resolved_seed["preset_id"])
    profile_id = str(resolved_seed["profile_id"])
    preset = dict(resolved_seed["base_preset"])
    component_kit_id = str(resolved_seed["kit_refs"]["pixel_component_kit_id"])
    frontend_affordance_id = str(resolved_seed["kit_refs"]["frontend_affordance_id"])
    asset_prompt_kit_id = str(resolved_seed["kit_refs"]["asset_prompt_kit_id"])
    item_collection_id = str(resolved_seed["policy_refs"]["item_collection_id"])
    role_item_policy_id = str(resolved_seed["policy_refs"]["role_item_policy_id"])
    property_policy_id = str(resolved_seed["policy_refs"]["property_policy_id"])
    knowledge_policy_id = str(resolved_seed["policy_refs"]["knowledge_policy_id"])
    item_collection = _copy(ITEM_COLLECTION_REGISTRY[item_collection_id])
    inventory_layers = _copy(resolved_seed["policy_refs"].get("inventory_layers", []))
    frontend_kit = _copy(FRONTEND_AFFORDANCE_REGISTRY[frontend_affordance_id])
    planner = {
        "artifact_type": "planner",
        "world_definition_seed": {
            "seed_version": str(resolved_seed.get("seed_version", "world_seed_v2")),
            "world_id": str(builder_spec.get("world_id", "world")),
            "world_name": str(builder_spec.get("world_name", "World")),
            "preset_id": preset_id,
            "locale": str(resolved_seed.get("locale", preset.get("locale", "en"))),
            "tone": str(resolved_seed.get("tone", builder_spec.get("genre") or preset.get("profile_id"))),
            "visual_direction": str(resolved_seed.get("visual_direction", builder_spec.get("visual_style", "") or preset.get("profile_id"))),
            "currency_code": str(resolved_seed.get("currency_code", DEFAULT_CURRENCY_CODE)),
            "currency_symbol": str(resolved_seed.get("currency_symbol", DEFAULT_CURRENCY_SYMBOL)),
            "currency_minor_unit": str(resolved_seed.get("currency_minor_unit", DEFAULT_CURRENCY_MINOR_UNIT)),
            "currency_item_id": str(resolved_seed.get("currency_item_id", DEFAULT_CURRENCY_ITEM_ID)),
            "currency_name": str(resolved_seed.get("currency_name", DEFAULT_CURRENCY_CODE)),
            "starting_wallet_minor": _copy(resolved_seed.get("starting_wallet_minor", {"min": 3000, "max": 14000})),
            "profile_id": profile_id,
            "domain_label": str(resolved_seed.get("domain_label", "")),
            "kit_refs": _copy(resolved_seed.get("kit_refs", {})),
            "policy_refs": _copy(resolved_seed.get("policy_refs", {})),
            "focus_tags": _dedupe([request.get("focus", ""), builder_spec.get("economy_focus", ""), builder_spec.get("exploration_focus", "")], limit=5),
        },
    }

    rooms_input = [dict(entry) for entry in builder_spec.get("rooms", []) if isinstance(entry, dict)]
    room_definitions: list[dict[str, Any]] = []
    for index, room in enumerate(rooms_input):
        visual = _profile_room_visual(room, index, component_kit_id=component_kit_id)
        room_name = str(room.get("name", f"Room {index + 1}"))
        room_definitions.append(
            {
                "room_id": _slug(f"room_{index + 1:02d}_{room_name}")[:128],
                "name": room_name,
                "archetype": visual["archetype"],
                "purpose": str(room.get("purpose", "")).strip(),
                "biome": str(room.get("biome", "")).strip(),
                "decor_tags": visual["decor_tags"],
                "activity_tags": _dedupe(room.get("activity_tags", []), limit=5),
                "entry_hints": [],
                "floor_tile": visual["floor_tile"],
                "wall_tile": visual["wall_tile"],
                "ambient_palette": visual["ambient_palette"],
                "map_kit_refs": {"pixel_component_kit_id": component_kit_id},
                "width_tiles": room.get("width_tiles"),
                "height_tiles": room.get("height_tiles"),
            }
        )
    rooms_spec = {"artifact_type": "rooms_spec", "profile_id": profile_id, "room_definitions": room_definitions}

    # Dynamic Universal item catalog support
    if "item_catalog" in builder_spec and isinstance(builder_spec["item_catalog"], list) and len(builder_spec["item_catalog"]) > 0:
        item_catalog = []
        for raw in builder_spec["item_catalog"]:
            if isinstance(raw, dict):
                item_id = str(raw.get("item_id", "")).strip()
                if item_id:
                    item_catalog.append({
                        "item_id": item_id,
                        "name": str(raw.get("name", item_id)).strip(),
                        "price": int(raw.get("price", 10)),
                        "mass": float(raw.get("mass", 0.2)),
                        "description": str(raw.get("description", "")).strip(),
                        "image_path": f"assets/items/{item_id}.png",
                        "image_prompt": str(raw.get("image_prompt", "")).strip(),
                    })
        
        # Self-healing: Ensure items required by frontend affordance kit exist in the catalog
        # so that Phaser and interaction E2E checks continue working flawlessly.
        affordance_items = list(frontend_kit.get("pov_local_modules", {}).get("item_use", {}).get("effects", {}).keys())
        existing_ids = {item["item_id"] for item in item_catalog}
        fallback_catalog_map = {str(item.get("item_id", "")).strip(): item for item in item_collection["item_catalog"] if isinstance(item, dict)}
        for item_id in affordance_items:
            item_id_str = str(item_id).strip()
            if item_id_str not in existing_ids:
                # Merge the fallback item definition into the custom catalog
                fallback_item = fallback_catalog_map.get(item_id_str)
                if fallback_item:
                    item_catalog.append(_copy(fallback_item))
                else:
                    item_catalog.append({
                        "item_id": item_id_str,
                        "name": item_id_str.replace("_", " ").title(),
                        "price": 100,
                        "mass": 0.1,
                        "description": f"A specialized {item_id_str} item required by world affordances.",
                        "image_path": f"assets/items/{item_id_str}.png",
                        "image_prompt": f"Specialized {item_id_str} icon, pixel art RPG style.",
                    })

        categories = sorted(list(set(str(item.get("category", "general")) for item in item_catalog if isinstance(item, dict))))
        item_taxonomy = {
            "categories": categories,
            "condition_states": ["pristine", "used", "tarnished"],
            "authenticity_states": ["genuine", "replica", "fake"]
        }
    else:
        item_taxonomy = _copy(item_collection["item_taxonomy"])
        item_catalog = _copy(item_collection["item_catalog"])

    item_ids = [str(item.get("item_id", "")) for item in item_catalog if isinstance(item, dict)]
    items_spec = {
        "artifact_type": "items_spec",
        "profile_id": profile_id,
        "item_taxonomy": item_taxonomy,
        "item_catalog": item_catalog,
        "wallet_policy": {
            "currency_code": str(planner["world_definition_seed"]["currency_code"]),
            "currency_symbol": str(planner["world_definition_seed"]["currency_symbol"]),
            "minor_unit": str(planner["world_definition_seed"]["currency_minor_unit"]),
            "currency_item_id": str(planner["world_definition_seed"]["currency_item_id"]),
            "starting_wallet_minor": _copy(planner["world_definition_seed"]["starting_wallet_minor"]),
        },
        "interaction_policy_refs": {
            "allowed_item_ids": [item_id for item_id in item_ids if item_id != str(planner["world_definition_seed"]["currency_item_id"])],
            "inventory_layers": _copy(inventory_layers),
        },
    }

    role_groups = [dict(entry) for entry in builder_spec.get("role_groups", []) if isinstance(entry, dict)]
    role_definitions: list[dict[str, Any]] = []
    for role in role_groups:
        role_name = str(role.get("role_name", "")).strip()
        home_hint = str(role.get("home_base", "")).strip()
        
        # 1. Starting items prioritization & fallback
        spec_starting_ids = [str(x).strip() for x in role.get("starting_item_ids", []) if str(x).strip()]
        allowed_items = _item_catalog_by_id(item_catalog)
        starting_item_ids = [item_id for item_id in spec_starting_ids if item_id in allowed_items][:40]
        if not starting_item_ids:
            starting_item_ids = _select_role_items(role_item_policy_id, role_name, str(role.get("activity", "")), item_catalog, seed_salt=f"role_{group_id}_{idx}")
            
        # 2. Property templates prioritization & fallback
        spec_prop_templates = role.get("property_templates", [])
        if spec_prop_templates and isinstance(spec_prop_templates, list):
            property_templates = []
            for item in spec_prop_templates:
                if isinstance(item, dict):
                    asset_name = str(item.get("asset_name", "{role_name} asset")).format(role_name=role_name)
                    property_templates.append({
                        "asset_name": asset_name,
                        "asset_type": str(item.get("asset_type", "general")).strip(),
                        "description": str(item.get("description", "")).strip(),
                        "story_use": str(item.get("story_use", "")).strip(),
                    })
        else:
            property_templates = _property_templates(property_policy_id, role_name)

        # 3. Knowledge templates prioritization & fallback
        spec_know_templates = role.get("knowledge_templates", [])
        if spec_know_templates and isinstance(spec_know_templates, list):
            knowledge_templates = []
            role_slug = _slug(role_name)
            for item in spec_know_templates:
                if isinstance(item, dict):
                    knowledge_id = str(item.get("knowledge_id", "{role_slug}_knowledge")).format(role_slug=role_slug)
                    knowledge_templates.append({
                        "knowledge_id": knowledge_id,
                        "topic": str(item.get("topic", "local lore")).strip(),
                        "summary": str(item.get("summary", "")).strip(),
                        "confidence": int(item.get("confidence", 60)),
                    })
        else:
            knowledge_templates = _knowledge_templates(knowledge_policy_id, role_name)

        role_definitions.append(
            {
                "role_id": _slug(role_name),
                "role_name": role_name,
                "count": max(1, int(role.get("count", 1) or 1)),
                "home_room_policy": home_hint,
                "activity": str(role.get("activity", "")).strip(),
                "core_values": _dedupe(role.get("core_values", []), limit=5),
                "appearance_policy": f"A grounded {role_name.lower()} for {builder_spec.get('world_name', 'the world')} with readable silhouette and {builder_spec.get('visual_style', 'world styling')}.",
                "starting_item_ids": starting_item_ids,
                "property_templates": property_templates,
                "knowledge_templates": knowledge_templates,
            }
        )
    main_characters = [dict(entry) for entry in builder_spec.get("main_characters", []) if isinstance(entry, dict)]
    agents_spec = {
        "artifact_type": "agents_spec",
        "profile_id": profile_id,
        "role_definitions": role_definitions,
        "main_characters": [
            {
                "agent_id": f"{_slug(str(builder_spec.get('world_id', 'world')))}_main_{index + 1:02d}",
                "display_name": str(character.get("display_name", "")).strip(),
                "role_name": str(character.get("role_name", "")).strip(),
                "activity": str(character.get("activity", "")).strip(),
                "home_base": str(character.get("home_base", "")).strip(),
                "arc_goal": str(character.get("arc_goal") or character.get("activity") or "").strip(),
                "starting_item_ids": character.get("starting_item_ids") or _select_role_items(role_item_policy_id, str(character.get("role_name", "")), str(character.get("activity", "")), item_catalog, seed_salt=str(index)),
                "inventory": character.get("inventory", []),
                "property_templates": character.get("property_templates") or _property_templates(property_policy_id, str(character.get("role_name", "main character"))),
                "knowledge_templates": character.get("knowledge_templates") or _knowledge_templates(knowledge_policy_id, str(character.get("role_name", "main character"))),
            }
            for index, character in enumerate(main_characters)
        ],
        "generation_policies": {
            "agent_generation": {
                "agent_id_prefix": "agent",
                "main_character_id_format": f"{_slug(str(builder_spec.get('world_id', 'world')))}_main_{{index:02d}}",
                "regular_agent_id_format": "agent_{index:03d}",
                "room_id_policy": "semantic_slug_only",
            },
            "inventory_generation": {
                "wallet_first": True,
                "inventory_layers": _copy(inventory_layers),
                "allowed_item_ids": [item_id for item_id in item_ids if item_id != str(planner["world_definition_seed"]["currency_item_id"])],
                "policy": "Generate actionable inventory from specialist-selected item ids only. Property and knowledge assets come from specialist templates and runtime augmentation.",
            },
            "trade_policy": {
                "settlement_backend": "wallet_minor_currency",
                "currency_display": "symbol_prefixed",
            },
        },
    }

    asset_prompt_kit = _copy(ASSET_PROMPT_KIT_REGISTRY[asset_prompt_kit_id])
    pixel_frontend_spec = {
        "artifact_type": "pixel_frontend_spec",
        "profile_id": profile_id,
        "pixel_kits": {
            "pixel_component_kit_id": component_kit_id,
            "resolved_component_library": _copy(COMPONENT_KIT_REGISTRY[component_kit_id]["component_library"]),
        },
        "frontend_affordances": {
            "frontend_affordance_id": frontend_affordance_id,
            "resolved_affordances": frontend_kit,
        },
        "asset_prompt_kits": {
            "asset_prompt_kit_id": asset_prompt_kit_id,
            "resolved_asset_prompt_kit": asset_prompt_kit,
        },
    }

    errors: list[str] = []
    room_ids = {str(room.get("room_id", "")).strip() for room in room_definitions}
    role_ids = {str(role.get("role_id", "")).strip() for role in role_definitions}
    item_id_set = {str(item.get("item_id", "")).strip() for item in item_catalog}
    if not room_ids:
        errors.append("rooms_spec.room_definitions must not be empty")
    if not role_ids and not agents_spec["main_characters"]:
        errors.append("agents_spec.role_definitions and main_characters must not both be empty")
    for role in role_definitions:
        for item_id in role.get("starting_item_ids", []):
            if str(item_id) not in item_id_set:
                errors.append(f"role starting item missing from catalog: {item_id}")
    for character in agents_spec["main_characters"]:
        for item_id in character.get("starting_item_ids", []):
            if str(item_id) not in item_id_set:
                errors.append(f"main character starting item missing from catalog: {item_id}")
    affordance_items = list(frontend_kit.get("pov_local_modules", {}).get("item_use", {}).get("effects", {}).keys())
    for item_id in affordance_items:
        if str(item_id) not in item_id_set:
            errors.append(f"frontend affordance references unknown item_id: {item_id}")

    compiler_report = {
        "artifact_type": "compiler_report",
        "preset_id": preset_id,
        "profile_id": profile_id,
        "status": "ok" if not errors else "invalid",
        "errors": errors,
        "warnings": [],
        "selected_refs": {
            "pixel_component_kit_id": component_kit_id,
            "frontend_affordance_id": frontend_affordance_id,
            "asset_prompt_kit_id": asset_prompt_kit_id,
            "item_collection_id": item_collection_id,
            "role_item_policy_id": role_item_policy_id,
            "property_policy_id": property_policy_id,
            "knowledge_policy_id": knowledge_policy_id,
        },
        "stage_reports": {
            "planner": {"ok": True},
            "rooms_spec": {"ok": bool(room_definitions)},
            "items_spec": {"ok": bool(item_catalog)},
            "agents_spec": {"ok": bool(role_definitions or agents_spec["main_characters"])},
            "pixel_frontend_spec": {"ok": True},
            "compiler": {"ok": not errors},
        },
    }
    if errors:
        raise ValueError("world pipeline validation failed: " + "; ".join(errors))

    structured = {
        "world_definition": {
            "seed_version": str(planner["world_definition_seed"].get("seed_version", "world_seed_v2")),
            "world_id": str(planner["world_definition_seed"]["world_id"]),
            "world_name": str(planner["world_definition_seed"]["world_name"]),
            "preset_id": preset_id,
            "locale": str(planner["world_definition_seed"]["locale"]),
            "tone": str(planner["world_definition_seed"]["tone"]),
            "visual_direction": str(planner["world_definition_seed"]["visual_direction"]),
            "currency_code": str(planner["world_definition_seed"]["currency_code"]),
            "currency_symbol": str(planner["world_definition_seed"]["currency_symbol"]),
            "currency_minor_unit": str(planner["world_definition_seed"]["currency_minor_unit"]),
            "currency_item_id": str(planner["world_definition_seed"]["currency_item_id"]),
            "currency_name": str(planner["world_definition_seed"].get("currency_name", planner["world_definition_seed"]["currency_code"])),
            "starting_wallet_minor": _copy(planner["world_definition_seed"]["starting_wallet_minor"]),
            "source_revision": "compiled_pipeline_v1",
            "profile_id": profile_id,
            "domain_label": str(planner["world_definition_seed"].get("domain_label", "")),
            "kit_refs": _copy(planner["world_definition_seed"]["kit_refs"]),
            "policy_refs": _copy(planner["world_definition_seed"]["policy_refs"]),
            "focus_tags": _copy(planner["world_definition_seed"]["focus_tags"]),
            "gameplay_loops": [dict(entry) for entry in builder_spec.get("gameplay_loops", []) if isinstance(entry, dict)],
            "social_rules": [str(item).strip() for item in builder_spec.get("social_rules", []) if str(item).strip()],
            "player_entry_points": [str(item).strip() for item in builder_spec.get("player_entry_points", []) if str(item).strip()],
            "conflict_hooks": [str(item).strip() for item in builder_spec.get("conflict_hooks", []) if str(item).strip()],
            "custom_actions": [str(item).strip() for item in builder_spec.get("custom_actions", []) if str(item).strip()],
            "item_themes": [str(item).strip() for item in builder_spec.get("item_themes", []) if str(item).strip()],
        },
        "room_definitions": room_definitions,
        "role_definitions": role_definitions,
        "item_taxonomy": item_taxonomy,
        "item_catalog": item_catalog,
        "generation_policies": _copy(agents_spec["generation_policies"]),
        "prompt_policies": _copy(asset_prompt_kit.get("prompt_policies", {})),
        "pixel_kits": {
            "pixel_component_kit_id": component_kit_id,
            "resolved_component_library": _copy(COMPONENT_KIT_REGISTRY[component_kit_id]["component_library"]),
        },
        "frontend_affordances": {
            "frontend_affordance_id": frontend_affordance_id,
            "pov_local_modules": _copy(frontend_kit.get("pov_local_modules", {})),
        },
        "asset_prompt_kits": {
            "asset_prompt_kit_id": asset_prompt_kit_id,
            "image_generation": _copy(asset_prompt_kit.get("image_generation", {})),
            "prompt_policies": _copy(asset_prompt_kit.get("prompt_policies", {})),
        },
        "validation_reports": {"compiler_report": compiler_report},
        "specialist_artifacts": {
            "planner": planner,
            "rooms_spec": rooms_spec,
            "items_spec": items_spec,
            "agents_spec": agents_spec,
            "pixel_frontend_spec": pixel_frontend_spec,
            "compiler_report": compiler_report,
        },
    }
    return {
        "planner": planner,
        "rooms_spec": rooms_spec,
        "items_spec": items_spec,
        "agents_spec": agents_spec,
        "pixel_frontend_spec": pixel_frontend_spec,
        "compiler_report": compiler_report,
        "structured_world_definition": structured,
    }


REGISTERED_AUTONOMOUS_WORLD_SPECS: dict[str, dict[str, Any]] = {
    "panjiayuan": {
        "world_id": "panjiayuan",
        "world_name": "Panjiayuan",
        "world_seed": {
            "seed_version": "world_seed_v2",
            "preset_id": "grounded_antique_market",
            "profile_id": "grounded_antique_market",
            "locale": "zh-CN",
            "tone": "grounded antique market",
            "visual_direction": "weathered market realism",
            "currency_code": "CNY",
            "currency_symbol": "¥",
            "currency_minor_unit": "fen",
            "currency_name": "renminbi",
            "domain_label": "antique market bargaining, appraisal disputes, rumor trade",
            "starting_wallet_minor": {"min": 3000, "max": 14000},
            "kit_refs": {
                "pixel_component_kit_id": "grounded_antique_market_v1",
                "frontend_affordance_id": "grounded_antique_market_v1",
                "asset_prompt_kit_id": "grounded_antique_market_v1",
            },
            "policy_refs": {
                "economy_policy_id": "cny_market_v1",
                "item_collection_id": "antique_market_items_v1",
                "inventory_layer_policy_id": "split_four_layer_v1",
                "role_item_policy_id": "grounded_antique_market_v1",
                "property_policy_id": "grounded_antique_market_v1",
                "knowledge_policy_id": "grounded_antique_market_v1",
                "inventory_layers": ["wallet", "inventory", "property_library", "knowledge_assets"],
            },
        },
        "genre": "realistic antique market",
        "premise": "A dense antique market of stalls, appraisers, rumors, and provenance disputes.",
        "simulation_objective": "Support bargaining, appraisal, provenance, and rumor-driven discovery.",
        "visual_style": "weathered market realism",
        "agent_count_target": 12,
        "player_count_target": 4,
        "economy_focus": "appraisal disputes and negotiated settlement",
        "exploration_focus": "rumors, provenance, and hidden goods",
        "rooms": [
            {"name": "Main Market Square", "biome": "urban market", "purpose": "open bargaining", "decor_tags": ["stalls", "tables"]},
            {"name": "Appraiser Lane", "biome": "quiet lane", "purpose": "close inspection", "decor_tags": ["lamps", "cases"]},
            {"name": "Back Storage Court", "biome": "courtyard", "purpose": "goods handoff and storage", "decor_tags": ["crates", "cloth"]},
        ],
        "role_groups": [
            {"role_name": "Stall Owner", "count": 6, "core_values": ["profit", "reputation"], "activity": "sell goods and bargain"},
            {"role_name": "Appraiser", "count": 4, "core_values": ["authenticity", "judgment"], "activity": "inspect and verify"},
            {"role_name": "Broker", "count": 2, "core_values": ["timing", "relationships"], "activity": "connect buyers and sellers"},
        ],
        "main_characters": [
            {"display_name": "Master Wei", "role_name": "Senior Appraiser", "activity": "verify disputed antiques"},
            {"display_name": "Sister Lin", "role_name": "Broker", "activity": "connect buyers and sellers"},
        ],
        "gameplay_loops": [{"label": "Bargaining", "summary": "Stalls negotiate prices and provenance.", "roles": ["Stall Owner", "Appraiser"], "rooms": ["Main Market Square"], "pressure": "price pressure"}],
        "player_entry_points": ["Enter through a noisy bargaining dispute."],
        "conflict_hooks": ["A forged provenance slip splits the market."],
        "social_rules": ["Trust changes with repeated fair dealing."],
        "item_themes": ["appraisal slip", "consignment note", "loupe", "jade pendant"],
        "custom_actions": ["Inspect", "Broker", "Appraise"],
    },
}


def bootstrap_registered_world_definition(world_id: str, world_name: str) -> dict[str, Any]:
    identity_tokens = {_slug(world_id), _slug(world_name)}
    for key, spec in REGISTERED_AUTONOMOUS_WORLD_SPECS.items():
        spec_tokens = {_slug(key), _slug(spec.get("world_id", "")), _slug(spec.get("world_name", ""))}
        if identity_tokens & spec_tokens:
            return build_world_pipeline(_copy(spec), {"brief": str(spec.get("premise", "")), "focus": str(spec.get("economy_focus", ""))})["structured_world_definition"]
    return {}
