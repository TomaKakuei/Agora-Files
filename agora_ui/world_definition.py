from __future__ import annotations

import copy
import json
from typing import Any

from .world_pipeline import bootstrap_registered_world_definition



DEFAULT_CURRENCY_CODE = "CNY"
DEFAULT_CURRENCY_SYMBOL = "¥"
DEFAULT_CURRENCY_MINOR_UNIT = "fen"
DEFAULT_CURRENCY_ITEM_ID = "cny_cash"


PANJIAYUAN_ITEM_TAXONOMY: list[dict[str, Any]] = [
    {
        "taxonomy_id": "currency",
        "label": "Currency",
        "description": "Cash-like tender used for settlement in the world.",
        "tags": ["money", "settlement"],
    },
    {
        "taxonomy_id": "artifact",
        "label": "Artifact",
        "description": "Tradable antiques, old collectibles, and culturally valuable objects.",
        "tags": ["antique", "collectible", "valuable"],
    },
    {
        "taxonomy_id": "replica",
        "label": "Replica",
        "description": "Copies, fakes, reconstructed pieces, and old-to-new altered goods.",
        "tags": ["forgery", "copy", "deception"],
    },
    {
        "taxonomy_id": "document",
        "label": "Document",
        "description": "Receipts, provenance notes, appraisal slips, consignment forms, and ledgers.",
        "tags": ["paperwork", "proof", "records"],
    },
    {
        "taxonomy_id": "tool",
        "label": "Tool",
        "description": "Inspection, handling, packing, and minor repair tools.",
        "tags": ["inspection", "handling", "repair"],
    },
    {
        "taxonomy_id": "consumable",
        "label": "Consumable",
        "description": "Tea, cigarettes, snacks, and everyday items consumed during work.",
        "tags": ["daily", "hospitality"],
    },
    {
        "taxonomy_id": "contact_token",
        "label": "Contact Token",
        "description": "Cards, introductions, and small markers of access to people or circles.",
        "tags": ["network", "trust", "access"],
    },
    {
        "taxonomy_id": "storage_claim",
        "label": "Storage Claim",
        "description": "Storage tickets, stash markers, and retrieval rights for goods.",
        "tags": ["storage", "claim", "logistics"],
    },
    {
        "taxonomy_id": "personal_effect",
        "label": "Personal Effect",
        "description": "Daily carry items, keepsakes, and small personal possessions.",
        "tags": ["personal", "carry"],
    },
]


PANJIAYUAN_ITEM_CATALOG: list[dict[str, Any]] = [
    {
        "item_id": "cny_cash",
        "name": "RMB Cash",
        "taxonomy_id": "currency",
        "price_minor": 1,
        "description": "Cash in renminbi, tracked in fen for exact settlement.",
        "tradeable": True,
        "needs_image": False,
        "metadata": {
            "currency": True,
            "currency_code": DEFAULT_CURRENCY_CODE,
            "currency_symbol": DEFAULT_CURRENCY_SYMBOL,
            "minor_unit": DEFAULT_CURRENCY_MINOR_UNIT,
            "name": "人民币现金",
        },
    },
    {
        "item_id": "porcelain_shard_set",
        "name": "Porcelain Shard Set",
        "taxonomy_id": "artifact",
        "price_minor": 16800,
        "description": "A wrapped batch of old porcelain fragments awaiting closer comparison.",
        "tradeable": True,
        "needs_image": True,
        "metadata": {"category": "artifact", "authenticity_risk": "medium", "name": "旧瓷片包"},
    },
    {
        "item_id": "jade_pendant",
        "name": "Jade Pendant",
        "taxonomy_id": "artifact",
        "price_minor": 38800,
        "description": "A small jade pendant with enough wear to trigger debate over age and origin.",
        "tradeable": True,
        "needs_image": True,
        "metadata": {"category": "artifact", "authenticity_risk": "high", "name": "玉坠"},
    },
    {
        "item_id": "old_photo_bundle",
        "name": "Old Photo Bundle",
        "taxonomy_id": "artifact",
        "price_minor": 7600,
        "description": "A tied stack of family and street photos with potential provenance clues.",
        "tradeable": True,
        "needs_image": True,
        "metadata": {"category": "artifact", "authenticity_risk": "low", "name": "老照片一捆"},
    },
    {
        "item_id": "high_copy_bracelet",
        "name": "High-Copy Bracelet",
        "taxonomy_id": "replica",
        "price_minor": 12400,
        "description": "A convincing reproduction bracelet meant to pass a quick look.",
        "tradeable": True,
        "needs_image": True,
        "metadata": {"category": "replica", "authenticity_risk": "extreme", "name": "高仿手串"},
    },
    {
        "item_id": "consignment_note",
        "name": "Consignment Note",
        "taxonomy_id": "document",
        "price_minor": 0,
        "description": "A handwritten consignment note linking goods to a seller and a promised split.",
        "tradeable": False,
        "needs_image": False,
        "metadata": {"category": "document", "name": "寄卖单"},
    },
    {
        "item_id": "appraisal_slip",
        "name": "Appraisal Slip",
        "taxonomy_id": "document",
        "price_minor": 0,
        "description": "A short appraisal slip capturing one expert opinion and its caveats.",
        "tradeable": False,
        "needs_image": False,
        "metadata": {"category": "document", "name": "鉴定意见单"},
    },
    {
        "item_id": "stall_ledger_copy",
        "name": "Stall Ledger Copy",
        "taxonomy_id": "document",
        "price_minor": 2800,
        "description": "A copied ledger page with dates, prices, and suspicious edits.",
        "tradeable": True,
        "needs_image": False,
        "metadata": {"category": "document", "name": "摊位账页副本"},
    },
    {
        "item_id": "loupe",
        "name": "Loupe",
        "taxonomy_id": "tool",
        "price_minor": 6800,
        "description": "A pocket loupe used for close inspection of marks, cracks, and wear.",
        "tradeable": True,
        "needs_image": False,
        "metadata": {"category": "tool", "name": "放大镜"},
    },
    {
        "item_id": "uv_flashlight",
        "name": "UV Flashlight",
        "taxonomy_id": "tool",
        "price_minor": 5200,
        "description": "A compact UV flashlight for checking repairs and suspicious surfaces.",
        "tradeable": True,
        "needs_image": False,
        "metadata": {"category": "tool", "name": "紫光手电"},
    },
    {
        "item_id": "packing_cloth",
        "name": "Packing Cloth",
        "taxonomy_id": "tool",
        "price_minor": 1600,
        "description": "Soft cloth used to wrap fragile goods after a deal closes.",
        "tradeable": True,
        "needs_image": False,
        "metadata": {"category": "tool", "name": "包货布"},
    },
    {
        "item_id": "tea_flask",
        "name": "Tea Flask",
        "taxonomy_id": "consumable",
        "price_minor": 1800,
        "description": "A cheap flask of tea used to keep a conversation going.",
        "tradeable": True,
        "needs_image": False,
        "metadata": {"category": "consumable", "name": "茶水壶"},
    },
    {
        "item_id": "cigarette_pack",
        "name": "Cigarette Pack",
        "taxonomy_id": "consumable",
        "price_minor": 2400,
        "description": "A pack of cigarettes carried for long haggles and relationship work.",
        "tradeable": True,
        "needs_image": False,
        "metadata": {"category": "consumable", "name": "香烟"},
    },
    {
        "item_id": "buyer_card",
        "name": "Buyer Contact Card",
        "taxonomy_id": "contact_token",
        "price_minor": 0,
        "description": "A direct line to a repeat buyer with specific taste and price bands.",
        "tradeable": False,
        "needs_image": False,
        "metadata": {"category": "contact_token", "name": "买家名片"},
    },
    {
        "item_id": "storage_ticket",
        "name": "Storage Ticket",
        "taxonomy_id": "storage_claim",
        "price_minor": 0,
        "description": "A claim ticket for retrieving goods from a back-room stash.",
        "tradeable": False,
        "needs_image": False,
        "metadata": {"category": "storage_claim", "name": "寄存票"},
    },
    {
        "item_id": "cloth_gloves",
        "name": "Cloth Gloves",
        "taxonomy_id": "personal_effect",
        "price_minor": 900,
        "description": "Simple gloves carried for handling dusty or delicate objects.",
        "tradeable": True,
        "needs_image": False,
        "metadata": {"category": "personal_effect", "name": "布手套"},
    },
]


def _slug(text: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(text or "")).strip("_")


def _trim(value: Any, limit: int = 240) -> str:
    return str(value or "").strip().replace("\n", " ")[:limit]


def _world_tokens(*parts: Any) -> set[str]:
    text = " ".join(str(part or "") for part in parts).lower()
    tokens = []
    current: list[str] = []
    for ch in text:
        if ch.isalnum():
            current.append(ch)
            continue
        if current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return {token for token in tokens if token}


def _deep_copy(payload: Any) -> Any:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _catalog_by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("item_id", "")).strip(): item
        for item in items
        if isinstance(item, dict) and str(item.get("item_id", "")).strip()
    }


def _split_existing_definition(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    existing_raw = config.get("world_definition", {})
    if not isinstance(existing_raw, dict):
        return {}, {}
    structured_keys = {
        "world_definition",
        "room_definitions",
        "role_definitions",
        "item_taxonomy",
        "item_catalog",
        "generation_policies",
        "prompt_policies",
        "pixel_kits",
        "frontend_affordances",
        "asset_prompt_kits",
        "validation_reports",
        "specialist_artifacts",
    }
    if structured_keys & set(existing_raw.keys()):
        nested_meta = existing_raw.get("world_definition", {})
        return (
            dict(nested_meta) if isinstance(nested_meta, dict) else {},
            dict(existing_raw),
        )
    return dict(existing_raw), {}


def _normalize_wallet_config(world_meta: dict[str, Any], economy: dict[str, Any]) -> dict[str, Any]:
    currency_code = str(
        world_meta.get("currency_code")
        or economy.get("currency_code")
        or DEFAULT_CURRENCY_CODE
    ).strip() or DEFAULT_CURRENCY_CODE
    currency_symbol = str(
        world_meta.get("currency_symbol")
        or economy.get("currency_symbol")
        or DEFAULT_CURRENCY_SYMBOL
    ).strip() or DEFAULT_CURRENCY_SYMBOL
    minor_unit = str(
        world_meta.get("currency_minor_unit")
        or economy.get("currency_minor_unit")
        or DEFAULT_CURRENCY_MINOR_UNIT
    ).strip() or DEFAULT_CURRENCY_MINOR_UNIT
    currency_item_id = str(
        world_meta.get("currency_item_id")
        or economy.get("currency_item_id")
        or DEFAULT_CURRENCY_ITEM_ID
    ).strip() or DEFAULT_CURRENCY_ITEM_ID
    legacy_range = economy.get("starting_gold", {})
    starting_wallet = world_meta.get("starting_wallet_minor") or economy.get("starting_wallet_minor", {})
    if not isinstance(starting_wallet, dict):
        starting_wallet = {}
    if not starting_wallet:
        if isinstance(legacy_range, dict) and any(key in legacy_range for key in ("min", "max")):
            starting_wallet = {
                "min": max(0, int(legacy_range.get("min", 0) or 0) * 100),
                "max": max(0, int(legacy_range.get("max", 0) or 0) * 100),
            }
        else:
            starting_wallet = {"min": 3000, "max": 14000}
    return {
        "currency_code": currency_code,
        "currency_symbol": currency_symbol,
        "currency_minor_unit": minor_unit,
        "currency_item_id": currency_item_id,
        "starting_wallet_minor": {
            "min": max(0, int(starting_wallet.get("min", 0) or 0)),
            "max": max(0, int(starting_wallet.get("max", starting_wallet.get("min", 0)) or 0)),
        },
    }


def extract_structured_world_definition(
    config: dict[str, Any],
    *,
    scenario_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenario_meta = config.get("scenario_meta", {}) if isinstance(config.get("scenario_meta", {}), dict) else {}
    runner = config.get("runner", {}) if isinstance(config.get("runner", {}), dict) else {}
    economy = config.get("economy", {}) if isinstance(config.get("economy", {}), dict) else {}
    existing, existing_structured = _split_existing_definition(config)
    scenario_world_id = str(scenario_meta.get("world_id", "")).strip()
    scenario_world_name = str(scenario_meta.get("world_name", "")).strip()
    bootstrap_structured = bootstrap_registered_world_definition(scenario_world_id, scenario_world_name)
    if bootstrap_structured:
        existing_world_id = str(existing.get("world_id", "")).strip()
        if scenario_world_id and existing_world_id and existing_world_id != scenario_world_id:
            existing = {}
            existing_structured = {}
    if not existing_structured and not bootstrap_structured:
        pass
    bootstrap_meta = bootstrap_structured.get("world_definition", {})
    if not isinstance(bootstrap_meta, dict):
        bootstrap_meta = {}
    wallet_config = _normalize_wallet_config({**dict(bootstrap_meta), **dict(existing)}, economy)
    world_definition = {
        **dict(bootstrap_meta),
        **dict(existing),
        "world_id": str(scenario_meta.get("world_id") or existing.get("world_id") or "world").strip() or "world",
        "world_name": str(scenario_meta.get("world_name") or existing.get("world_name") or "World").strip() or "World",
        "locale": str(existing.get("locale") or bootstrap_meta.get("locale") or "en").strip() or "en",
        "tone": str(existing.get("tone") or bootstrap_meta.get("tone") or runner.get("domain_label") or "simulation_world").strip() or "simulation_world",
        "visual_direction": str(existing.get("visual_direction") or bootstrap_meta.get("visual_direction") or runner.get("domain_label") or "readable_world").strip() or "readable_world",
        "source_revision": str(existing.get("source_revision") or bootstrap_meta.get("source_revision") or (scenario_manifest or {}).get("revision_id") or "compiled").strip() or "compiled",
        "gameplay_loops": [dict(item) for item in bootstrap_meta.get("gameplay_loops", []) if isinstance(item, dict)],
        "social_rules": [str(item) for item in bootstrap_meta.get("social_rules", []) if str(item).strip()],
        "player_entry_points": [str(item) for item in bootstrap_meta.get("player_entry_points", []) if str(item).strip()],
        "conflict_hooks": [str(item) for item in bootstrap_meta.get("conflict_hooks", []) if str(item).strip()],
        "custom_actions": [str(item) for item in bootstrap_meta.get("custom_actions", []) if str(item).strip()],
        "item_themes": [str(item) for item in bootstrap_meta.get("item_themes", []) if str(item).strip()],
        **wallet_config,
    }
    taxonomy = existing_structured.get("item_taxonomy", bootstrap_structured.get("item_taxonomy", existing.get("item_taxonomy")))
    if not isinstance(taxonomy, list):
        taxonomy = []
    catalog = existing_structured.get("item_catalog", bootstrap_structured.get("item_catalog", existing.get("item_catalog")))
    if not isinstance(catalog, list) or not catalog:
        catalog = economy.get("item_catalog", [])
    if not isinstance(catalog, list):
        catalog = []
    role_groups = config.get("agent_generation", {}).get("role_groups", []) if isinstance(config.get("agent_generation", {}), dict) else []
    rooms = config.get("space", {}).get("rooms", []) if isinstance(config.get("space", {}), dict) else []
    generation_policies = existing_structured.get("generation_policies", bootstrap_structured.get("generation_policies", existing.get("generation_policies")))
    if not isinstance(generation_policies, dict):
        generation_policies = {}
    prompt_policies = existing_structured.get("prompt_policies", bootstrap_structured.get("prompt_policies", existing.get("prompt_policies")))
    if not isinstance(prompt_policies, dict):
        prompt_policies = {}
    pixel_kits = existing_structured.get("pixel_kits", bootstrap_structured.get("pixel_kits", {}))
    if not isinstance(pixel_kits, dict):
        pixel_kits = {}
    frontend_affordances = existing_structured.get("frontend_affordances", bootstrap_structured.get("frontend_affordances", {}))
    if not isinstance(frontend_affordances, dict):
        frontend_affordances = {}
    asset_prompt_kits = existing_structured.get("asset_prompt_kits", bootstrap_structured.get("asset_prompt_kits", {}))
    if not isinstance(asset_prompt_kits, dict):
        asset_prompt_kits = {}
    validation_reports = existing_structured.get("validation_reports", bootstrap_structured.get("validation_reports", {}))
    if not isinstance(validation_reports, dict):
        validation_reports = {}
    specialist_artifacts = existing_structured.get("specialist_artifacts", bootstrap_structured.get("specialist_artifacts", {}))
    if not isinstance(specialist_artifacts, dict):
        specialist_artifacts = {}
    room_definitions = [
        {
            "room_id": str(room.get("room_id", "")).strip(),
            "name": str(room.get("name", "")).strip(),
            "archetype": str((room.get("metadata", {}) if isinstance(room.get("metadata", {}), dict) else {}).get("room_archetype", "")).strip(),
            "purpose": str((room.get("metadata", {}) if isinstance(room.get("metadata", {}), dict) else {}).get("purpose", "")).strip(),
            "decor_tags": list((room.get("visual", {}) if isinstance(room.get("visual", {}), dict) else {}).get("decor_tags", []) or []),
            "activity_tags": list((room.get("metadata", {}) if isinstance(room.get("metadata", {}), dict) else {}).get("activity_tags", []) or []),
            "entry_hints": [str((room.get("metadata", {}) if isinstance(room.get("metadata", {}), dict) else {}).get("player_entry_hook", "")).strip()] if str((room.get("metadata", {}) if isinstance(room.get("metadata", {}), dict) else {}).get("player_entry_hook", "")).strip() else [],
        }
        for room in rooms
        if isinstance(room, dict) and str(room.get("room_id", "")).strip()
    ]
    role_definitions = [
        {
            "role_id": str(role.get("role_id", "")).strip(),
            "role_name": str(role.get("role_name", "")).strip(),
            "count": max(0, int(role.get("count", 0) or 0)),
            "home_room_policy": str(role.get("home_room_id", "")).strip(),
            "activity": str(role.get("activity_directive", "")).strip(),
            "core_values": [str(item).strip() for item in role.get("core_values", []) if str(item).strip()],
            "appearance_policy": str(role.get("appearance_template", "")).strip(),
        }
        for role in role_groups
        if isinstance(role, dict) and str(role.get("role_id", "")).strip()
    ]
    return {
        "world_definition": world_definition,
        "room_definitions": room_definitions,
        "role_definitions": role_definitions,
        "item_taxonomy": _deep_copy(list(taxonomy)),
        "item_catalog": _deep_copy(list(catalog)),
        "generation_policies": _deep_copy(generation_policies),
        "prompt_policies": _deep_copy(prompt_policies),
        "pixel_kits": _deep_copy(pixel_kits),
        "frontend_affordances": _deep_copy(frontend_affordances),
        "asset_prompt_kits": _deep_copy(asset_prompt_kits),
        "validation_reports": _deep_copy(validation_reports),
        "specialist_artifacts": _deep_copy(specialist_artifacts),
    }


def _default_inventory_generation_policy(item_catalog: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "enabled": True,
        "stage": "initial_inventory_generation",
        "preserve_existing_inventory": True,
        "max_distinct_items_per_agent": 3,
        "max_quantity_per_item": 3,
        "allowed_item_ids": [
            str(item.get("item_id", "")).strip()
            for item in item_catalog
            if isinstance(item, dict) and str(item.get("item_id", "")).strip() and not bool(dict(item.get("metadata", {})).get("currency"))
        ],
        "policy": (
            "Generate compact role-appropriate actionable inventory only from the structured world-definition catalog. "
            "Use property_library for non-actionable assets and knowledge_assets for rumors, provenance, and appraisal context."
        ),
    }


def sync_world_definition_into_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(config)
    structured = extract_structured_world_definition(normalized)
    world_meta = structured["world_definition"]
    item_catalog = structured["item_catalog"]
    normalized["world_definition"] = structured
    normalized.setdefault("property_library", {})["item_catalog"] = _deep_copy(item_catalog)
    normalized.setdefault("economy", {})
    normalized["economy"]["currency_item_id"] = str(world_meta.get("currency_item_id", DEFAULT_CURRENCY_ITEM_ID))
    normalized["economy"]["currency_code"] = str(world_meta.get("currency_code", DEFAULT_CURRENCY_CODE))
    normalized["economy"]["currency_symbol"] = str(world_meta.get("currency_symbol", DEFAULT_CURRENCY_SYMBOL))
    normalized["economy"]["currency_minor_unit"] = str(world_meta.get("currency_minor_unit", DEFAULT_CURRENCY_MINOR_UNIT))
    normalized["economy"]["currency_name"] = str(world_meta.get("currency_name") or world_meta.get("currency_code", DEFAULT_CURRENCY_CODE))
    normalized["economy"]["starting_wallet_minor"] = dict(world_meta.get("starting_wallet_minor", {"min": 3000, "max": 14000}))
    normalized["economy"]["item_catalog"] = _deep_copy(item_catalog)
    normalized["economy"].pop("starting_gold", None)
    if not isinstance(normalized.get("inventory_generation", {}), dict):
        normalized["inventory_generation"] = {}
    normalized["inventory_generation"] = {
        **_default_inventory_generation_policy(item_catalog),
        **dict(normalized.get("inventory_generation", {})),
    }
    normalized["inventory_generation"]["allowed_item_ids"] = _default_inventory_generation_policy(item_catalog)["allowed_item_ids"]
    normalized.setdefault("runner", {})["agent_id_prefix"] = str(
        dict(structured.get("generation_policies", {})).get("agent_generation", {}).get("agent_id_prefix", "agent")
    )
    pixel_kits = structured.get("pixel_kits", {})
    if isinstance(pixel_kits, dict):
        component_library = pixel_kits.get("resolved_component_library", {})
        if isinstance(component_library, dict) and component_library:
            normalized.setdefault("pixel_asset_pipeline", {}).setdefault("map_generation", {})["component_library"] = _deep_copy(component_library)
    frontend_affordances = structured.get("frontend_affordances", {})
    if isinstance(frontend_affordances, dict):
        pov_modules = frontend_affordances.get("pov_local_modules", {})
        if isinstance(pov_modules, dict) and pov_modules:
            normalized.setdefault("pixel_asset_pipeline", {}).setdefault("frontend", {})["pov_local_modules"] = _deep_copy(pov_modules)
    asset_prompt_kits = structured.get("asset_prompt_kits", {})
    if isinstance(asset_prompt_kits, dict):
        image_generation_payload = asset_prompt_kits.get("image_generation", {})
        if isinstance(image_generation_payload, dict):
            image_generation = normalized.setdefault("image_generation", {})
            for key in ("prompt_policy", "default_prompt_template"):
                if str(image_generation_payload.get(key, "")).strip():
                    image_generation[key] = str(image_generation_payload.get(key, "")).strip()
        prompt_policy_payload = asset_prompt_kits.get("prompt_policies", {})
        if isinstance(prompt_policy_payload, dict) and prompt_policy_payload:
            normalized.setdefault("world_prompt_policies", {}).update(_deep_copy(prompt_policy_payload))
    domain_label = str(world_meta.get("domain_label") or dict(world_meta.get("policy_refs", {})).get("domain_label", "")).strip()
    if domain_label:
        normalized.setdefault("runner", {})["domain_label"] = domain_label
    return normalized


def default_wallet_payload(amount_minor: int, *, config: dict[str, Any]) -> dict[str, Any]:
    structured = extract_structured_world_definition(config)
    world_meta = structured["world_definition"]
    return {
        "currency_code": str(world_meta.get("currency_code", DEFAULT_CURRENCY_CODE)),
        "currency_symbol": str(world_meta.get("currency_symbol", DEFAULT_CURRENCY_SYMBOL)),
        "minor_unit": str(world_meta.get("currency_minor_unit", DEFAULT_CURRENCY_MINOR_UNIT)),
        "amount_minor": max(0, int(amount_minor or 0)),
    }


def legacy_currency_inventory_entry(*, config: dict[str, Any], amount_minor: int) -> dict[str, Any]:
    structured = extract_structured_world_definition(config)
    world_meta = structured["world_definition"]
    catalog = _catalog_by_id(structured["item_catalog"])
    currency_item_id = str(world_meta.get("currency_item_id", DEFAULT_CURRENCY_ITEM_ID))
    item_meta = dict(catalog.get(currency_item_id, {}))
    return {
        "item_id": currency_item_id,
        "name": str(item_meta.get("name", world_meta.get("currency_name", "civic credit"))).strip(),
        "quantity": max(0, int(amount_minor or 0)),
        "mass": 0.0,
        "description": str(item_meta.get("description") or world_meta.get("currency_code", DEFAULT_CURRENCY_CODE)),
        "image_path": str(item_meta.get("image_path", "")),
        "image_prompt": str(item_meta.get("image_prompt", "")),
        "metadata": {
            **(dict(item_meta.get("metadata", {})) if isinstance(item_meta.get("metadata", {}), dict) else {}),
            "currency": True,
            "name": str(item_meta.get("name") or world_meta.get("currency_code", DEFAULT_CURRENCY_CODE)),
            "currency_code": str(world_meta.get("currency_code", DEFAULT_CURRENCY_CODE)),
            "currency_symbol": str(world_meta.get("currency_symbol", DEFAULT_CURRENCY_SYMBOL)),
            "amount_minor": max(0, int(amount_minor or 0)),
        },
    }
