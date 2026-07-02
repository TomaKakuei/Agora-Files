from __future__ import annotations
from .generation_schemas import *
from .generation_prompts import _world_summary_prompt
from .critique_loop import *
from .critique_loop import _focus_profile, _synthesized_gameplay_loops, _apply_compiler_critique_to_builder_spec, _critique_compiled_world_config
import argparse
import json
import math
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import Counter
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .io_utils import *
from .manifest import *
from uuid import uuid4
from ..adjudicator_schemas import AgentRuntimeProfileSpec
from ..boundary_schemas import (
    WorldBuilderArtStatusSpec,
    WorldBuilderDraftSpec,
    WorldBuilderPublishStatusSpec,
    WorldBuilderRevisionSpec,
    WorldBuilderStructuredSummarySpec,
)
from ..vertex_json_client import VertexJsonClient
from ..package_db import (
    assess_pixel_readiness_from_root,
    ensure_materialized_world_package,
    package_contains_paths,
    pack_world_package,
    read_world_package_metadata,
    resolve_runtime_python,
    validate_pixel_ui_launch,
    validate_world_package_startup,
)
from ..run_interaction_simulation import materialize_scenario
from ..scenario_schemas import ScenarioManifestSpec
from ..world_definition import sync_world_definition_into_config
from ..world_pipeline import (




    ASSET_PROMPT_KIT_REGISTRY,
    build_world_pipeline,
    COMPONENT_KIT_REGISTRY,
    ECONOMY_POLICY_REGISTRY,
    FRONTEND_AFFORDANCE_REGISTRY,
    INVENTORY_LAYER_POLICY_REGISTRY,
    ITEM_COLLECTION_REGISTRY,
    KNOWLEDGE_POLICY_REGISTRY,
    PROPERTY_POLICY_REGISTRY,
    ROLE_ITEM_POLICY_REGISTRY,
    WORLD_PROFILE_LIBRARY,
)
STATUS_DRAFT_GENERATING = "draft_generating"
STATUS_DRAFT_READY = "draft_ready"
STATUS_DRAFT_FAILED = "draft_failed"
STATUS_REVISION_GENERATING = "revision_generating"
STATUS_ART_QUEUED = "art_queued"
STATUS_ART_RUNNING = "art_running"
STATUS_ART_FAILED = "art_failed"
STATUS_ART_TIMEOUT_SKIPPED = "art_timeout_skipped"
STATUS_QA_FAILED_RETRYING = "qa_failed_retrying"
STATUS_PUBLISH_READY = "publish_ready"
STATUS_PUBLISHED = "published"
GLOBAL_CREATOR_ENV_PATHS = (Path.home() / ".config" / "agora_ui_runtime.env",)



def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _world_creator_model(provider_type: str = "pro") -> str:
    env_model = str(os.environ.get("AGORA_WORLD_CREATOR_MODEL", "")).strip()
    if env_model:
        return env_model
    if provider_type == "lite":
        return "gemini-3.1-flash-lite"
    return "gemini-2.5-pro"


def _world_creator_timeout_seconds() -> float:
    return float(max(30, _env_int("AGORA_WORLD_CREATOR_TIMEOUT_SECONDS", 180)))


def _world_creator_max_retries() -> int:
    return max(1, _env_int("AGORA_WORLD_CREATOR_MAX_RETRIES", 2))


def _world_creator_provider(provider_type: str = "pro") -> VertexJsonClient:
    mocked = _get_mocked_fallback("_world_creator_provider", _world_creator_provider)
    if mocked is not _world_creator_provider:
        return mocked()

    from .art import _load_creator_runtime_env
    loaded_env = _load_creator_runtime_env()
    for k, v in loaded_env.items():
        if k not in os.environ:
            os.environ[k] = v

    api_key = (
        str(os.environ.get("AGORA_AISTUDIO_API_KEY", "")).strip()
        or str(os.environ.get("AGORA_GEMINI_API_KEY", "")).strip()
        or str(os.environ.get("GEMINI_API_KEY", "")).strip()
        or str(os.environ.get("GOOGLE_API_KEY", "")).strip()
    )
    if api_key and not os.environ.get("AGORA_AISTUDIO_API_KEY"):
        os.environ["AGORA_AISTUDIO_API_KEY"] = api_key

    backend = str(os.environ.get("AGORA_VERTEX_BACKEND", "ai_studio")).strip()
    config = {
        "vertex_api": {
            "backend": backend,
            "model": _world_creator_model(provider_type),
            "thinking_level": "high",
            "thinking_budget": 8192,
            "temperature": 0.2,
            "max_output_tokens": 24000,
            "timeout_seconds": int(_world_creator_timeout_seconds()),
            "api_key_env": "AGORA_AISTUDIO_API_KEY",
            "pacing_sleep_seconds": 1.0,
            "stages": {
                "world_creator_generation": {
                    "max_output_tokens": 24000,
                },
                "world_creator_text_generation": {
                    "max_output_tokens": 24000,
                }
            },
            "retry": {
                "max_attempts": _world_creator_max_retries(),
                "initial_sleep_seconds": 5.0,
                "max_sleep_seconds": 120.0,
                "backoff_multiplier": 2.0,
                "status_codes": [408, 429, 500, 502, 503, 504],
            }
        }
    }
    return VertexJsonClient(config)


def _execute_json_prompt(
    *,
    provider: VertexJsonClient,
    system_instruction: str,
    prompt: str,
    response_schema: dict[str, Any],
    temperature: float = 0.2,
    max_output_tokens: int = 4096,
    thinking_level: str = "high",
    stage: str = "world_creator_generation",
) -> dict[str, Any]:
    provider.temperature = temperature
    provider.max_output_tokens = max_output_tokens
    provider.thinking_level = thinking_level

    payload = provider.generate_json(
        system_instruction=system_instruction,
        prompt=prompt,
        schema=response_schema,
        stage=stage,
    )
    if isinstance(payload, dict):
        for key in ("builder_spec", "result", "data", "payload"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                return dict(nested)
        return dict(payload)
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        return dict(payload[0])
    raise ValueError("World builder JSON response was not an object")


def _execute_text_prompt(
    *,
    provider: VertexJsonClient,
    system_instruction: str,
    prompt: str,
    temperature: float = 0.5,
    max_output_tokens: int = 3072,
    thinking_level: str = "medium",
) -> str:
    provider.temperature = temperature
    provider.max_output_tokens = max_output_tokens
    provider.thinking_level = thinking_level

    text = provider.generate_text(
        system_instruction=system_instruction,
        prompt=prompt,
        stage="world_creator_text_generation",
    )
    if not text:
        raise ValueError("World builder text response was empty")
    return text


def _normalize_builder_spec(spec: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    world_name = _first_non_empty(spec.get("world_name"), request.get("world_name"), default="Agora Creator World")
    genre = _first_non_empty(spec.get("genre"), request.get("genre"), default="fictional persistent world")
    premise = _first_non_empty(spec.get("premise"), request.get("brief"), default="A persistent social world built from the user brief.")
    requested_agents = max(8, min(120, int(request.get("agent_count_target") or 40)))
    requested_players = max(1, min(50, int(request.get("player_count_target") or 4)))
    agent_count_target = max(8, min(120, int(spec.get("agent_count_target") or requested_agents)))
    player_count_target = max(1, min(50, int(spec.get("player_count_target") or requested_players)))
    rooms = [dict(entry) for entry in spec.get("rooms", []) if isinstance(entry, dict)]
    if not rooms:
        rooms = [
            {"name": "Commons", "biome": "social hub", "purpose": "daily coordination", "decor_tags": ["notice_board", "tables"], "archetype": "commons", "ambient_palette": "warm_lantern"},
            {"name": "Market", "biome": "trade district", "purpose": "commerce and barter", "decor_tags": ["stalls", "crates"], "archetype": "market_exchange", "ambient_palette": "cool_neon"},
            {"name": "Workshop", "biome": "craft zone", "purpose": "repair and creation", "decor_tags": ["tools", "benches"], "archetype": "workshop", "ambient_palette": "forge_fire"},
            {"name": "Archive", "biome": "knowledge chamber", "purpose": "planning and discovery", "decor_tags": ["shelves", "maps"], "archetype": "archive_ritual", "ambient_palette": "mystic_glow"},
            {"name": "Garden", "biome": "calm exterior", "purpose": "rest and reflection", "decor_tags": ["plants", "paths"], "archetype": "rest_social", "ambient_palette": "natural_sunlight"},
            {"name": "Watch Post", "biome": "edge district", "purpose": "defense and tension", "decor_tags": ["signals", "banners"], "archetype": "lookout", "ambient_palette": "harsh_floodlight"},
        ]
    normalized_rooms: list[dict[str, Any]] = []
    for index, room in enumerate(rooms):
        normalized_rooms.append(
            {
                "name": _first_non_empty(room.get("name"), default=f"Room {index + 1}"),
                "biome": _first_non_empty(room.get("biome"), default="social interior"),
                "purpose": _first_non_empty(room.get("purpose"), default="support social interaction"),
                "decor_tags": _dedupe_texts(room.get("decor_tags", []), limit=6) or ["props", "signals"],
                "activity_tags": _dedupe_texts(room.get("activity_tags", []), limit=5),
                "flux_floor_prompt": str(room.get("flux_floor_prompt", "")).strip(),
                "room_scene_prompt": str(room.get("room_scene_prompt", "")).strip(),
                "width_tiles": min(60, max(3, int(room.get("width_tiles") or 5))),
                "height_tiles": min(50, max(3, int(room.get("height_tiles") or 5))),
                "ambient_palette": str(room.get("ambient_palette", "")).strip(),
                "archetype": str(room.get("archetype", "")).strip(),
            }
        )
    main_characters = [dict(entry) for entry in spec.get("main_characters", []) if isinstance(entry, dict)]
    role_groups = [] # Completely delete regular roles/professions thing
    normalized_role_groups: list[dict[str, Any]] = []
    if not main_characters:
        main_characters = [
            {"display_name": "Ari Vale", "role_name": "Lead Organizer", "activity": "pushes the main civic storyline forward"},
            {"display_name": "Mira Sol", "role_name": "Field Explorer", "activity": "brings in discoveries and complications"},
            {"display_name": "Tovin Reed", "role_name": "Trade Broker", "activity": "turns resources into leverage and alliances"},
        ]
    normalized_main_characters: list[dict[str, Any]] = []
    for index, character in enumerate(main_characters):
        normalized_main_characters.append(
            {
                "display_name": _first_non_empty(character.get("display_name"), default=f"Main Character {index + 1}"),
                "role_name": _first_non_empty(character.get("role_name"), default=f"Lead {index + 1}"),
                "activity": _first_non_empty(character.get("activity"), default="drives a visible thread of world activity forward"),
                "home_base": _first_non_empty(character.get("home_base"), default=""),
                "arc_goal": _first_non_empty(character.get("arc_goal"), character.get("activity"), default=""),
            }
        )
    focus_profile = _focus_profile(request, spec)
    item_themes = _dedupe_texts(spec.get("item_themes", []), limit=6) or [
        "trade goods",
        "quest documents",
        "repair kits",
        "maps",
    ]
    gameplay_loops = [dict(entry) for entry in spec.get("gameplay_loops", []) if isinstance(entry, dict)]
    if not gameplay_loops:
        gameplay_loops = _synthesized_gameplay_loops(
            request=request,
            rooms=normalized_rooms,
            role_groups=normalized_role_groups,
            item_themes=item_themes,
            focus_profile=focus_profile,
        )
    normalized_loops: list[dict[str, Any]] = []
    for index, loop in enumerate(gameplay_loops):
        normalized_loops.append(
            {
                "label": _first_non_empty(loop.get("label"), default=f"Gameplay Loop {index + 1}"),
                "summary": _first_non_empty(loop.get("summary"), default="A repeatable social loop that keeps the world active."),
                "roles": _dedupe_texts(loop.get("roles", []), limit=4),
                "rooms": _dedupe_texts(loop.get("rooms", []), limit=4),
                "pressure": _first_non_empty(loop.get("pressure"), default="unfinished obligations"),
            }
        )
    player_entry_points = _dedupe_texts(spec.get("player_entry_points", []), limit=4)
    conflict_hooks = _dedupe_texts(spec.get("conflict_hooks", []), limit=4)
    custom_actions = _dedupe_texts(spec.get("custom_actions", []), limit=12)
    world_id = _slug(_first_non_empty(spec.get("world_id"), world_name))
    raw_world_seed = dict(spec.get("world_seed", {})) if isinstance(spec.get("world_seed", {}), dict) else {}
    
    item_catalog = []
    if "item_catalog" in spec and isinstance(spec["item_catalog"], list):
        for raw in spec["item_catalog"]:
            if isinstance(raw, dict) and "item_id" in raw:
                item_catalog.append(raw)

    raw_preset_id = _first_non_empty(raw_world_seed.get("preset_id"), raw_world_seed.get("profile_id"), default="civic_social_world")
    preset_id = raw_preset_id if raw_preset_id in WORLD_PROFILE_LIBRARY else "civic_social_world"
    preset = dict(WORLD_PROFILE_LIBRARY.get(preset_id, WORLD_PROFILE_LIBRARY["civic_social_world"]))
    economy_policy_id = _first_non_empty(raw_world_seed.get("policy_refs", {}).get("economy_policy_id") if isinstance(raw_world_seed.get("policy_refs", {}), dict) else "", preset.get("economy_policy_id"), default="civic_credit_v1")
    if economy_policy_id not in ECONOMY_POLICY_REGISTRY:
        economy_policy_id = str(preset.get("economy_policy_id", "civic_credit_v1"))
    item_collection_id = _first_non_empty(raw_world_seed.get("policy_refs", {}).get("item_collection_id") if isinstance(raw_world_seed.get("policy_refs", {}), dict) else "", preset.get("item_collection_id"), default="civic_social_items_v1")
    if item_collection_id not in ITEM_COLLECTION_REGISTRY:
        item_collection_id = str(preset.get("item_collection_id", "civic_social_items_v1"))
    inventory_layer_policy_id = _first_non_empty(raw_world_seed.get("policy_refs", {}).get("inventory_layer_policy_id") if isinstance(raw_world_seed.get("policy_refs", {}), dict) else "", preset.get("inventory_layer_policy_id"), default="split_four_layer_v1")
    if inventory_layer_policy_id not in INVENTORY_LAYER_POLICY_REGISTRY:
        inventory_layer_policy_id = str(preset.get("inventory_layer_policy_id", "split_four_layer_v1"))
    role_item_policy_id = _first_non_empty(raw_world_seed.get("policy_refs", {}).get("role_item_policy_id") if isinstance(raw_world_seed.get("policy_refs", {}), dict) else "", preset.get("role_item_policy_id"), default="civic_social_world_v1")
    if role_item_policy_id not in ROLE_ITEM_POLICY_REGISTRY:
        role_item_policy_id = str(preset.get("role_item_policy_id", "civic_social_world_v1"))
    property_policy_id = _first_non_empty(raw_world_seed.get("policy_refs", {}).get("property_policy_id") if isinstance(raw_world_seed.get("policy_refs", {}), dict) else "", preset.get("property_policy_id"), default="civic_social_world_v1")
    if property_policy_id not in PROPERTY_POLICY_REGISTRY:
        property_policy_id = str(preset.get("property_policy_id", "civic_social_world_v1"))
    knowledge_policy_id = _first_non_empty(raw_world_seed.get("policy_refs", {}).get("knowledge_policy_id") if isinstance(raw_world_seed.get("policy_refs", {}), dict) else "", preset.get("knowledge_policy_id"), default="civic_social_world_v1")
    if knowledge_policy_id not in KNOWLEDGE_POLICY_REGISTRY:
        knowledge_policy_id = str(preset.get("knowledge_policy_id", "civic_social_world_v1"))
    economy_policy = dict(ECONOMY_POLICY_REGISTRY.get(economy_policy_id, ECONOMY_POLICY_REGISTRY["civic_credit_v1"]))
    profile_inventory_layers = [str(item) for item in dict(INVENTORY_LAYER_POLICY_REGISTRY.get(inventory_layer_policy_id, {})).get("inventory_layers", []) if str(item).strip()] or [
        "wallet",
        "inventory",
        "property_library",
        "knowledge_assets",
    ]
    raw_starting_wallet = dict(raw_world_seed.get("starting_wallet_minor", {})) if isinstance(raw_world_seed.get("starting_wallet_minor", {}), dict) else {}
    starting_wallet_minor = {
        "min": max(0, int(raw_starting_wallet.get("min", dict(economy_policy.get("starting_wallet_minor", {})).get("min", 1800)) or 1800)),
        "max": max(
            0,
            int(
                raw_starting_wallet.get(
                    "max",
                    raw_starting_wallet.get("min", dict(economy_policy.get("starting_wallet_minor", {})).get("max", 9000)),
                )
                or 9000
            ),
        ),
    }
    world_seed = {
        "seed_version": "world_seed_v2",
        "preset_id": preset_id,
        "profile_id": preset_id,
        "locale": _first_non_empty(raw_world_seed.get("locale"), preset.get("locale"), default="en"),
        "tone": _first_non_empty(raw_world_seed.get("tone"), genre, default=genre),
        "visual_direction": _first_non_empty(raw_world_seed.get("visual_direction"), spec.get("visual_style"), default=genre),
        "currency_code": _first_non_empty(economy_policy.get("currency_code"), default="CRD"),
        "currency_symbol": _first_non_empty(economy_policy.get("currency_symbol"), default="cr"),
        "currency_minor_unit": _first_non_empty(economy_policy.get("currency_minor_unit"), default="point"),
        "currency_name": _first_non_empty(raw_world_seed.get("currency_name"), economy_policy.get("currency_name"), default="local credit"),
        "domain_label": _first_non_empty(raw_world_seed.get("domain_label"), preset.get("default_domain_label"), spec.get("economy_focus"), spec.get("premise"), default=genre),
        "starting_wallet_minor": starting_wallet_minor,
        "kit_refs": {
            "pixel_component_kit_id": _first_non_empty(raw_world_seed.get("kit_refs", {}).get("pixel_component_kit_id") if isinstance(raw_world_seed.get("kit_refs", {}), dict) else "", preset.get("pixel_component_kit_id"), default="civic_social_world_v1"),
            "frontend_affordance_id": _first_non_empty(raw_world_seed.get("kit_refs", {}).get("frontend_affordance_id") if isinstance(raw_world_seed.get("kit_refs", {}), dict) else "", preset.get("frontend_affordance_id"), default="civic_social_world_v1"),
            "asset_prompt_kit_id": _first_non_empty(raw_world_seed.get("kit_refs", {}).get("asset_prompt_kit_id") if isinstance(raw_world_seed.get("kit_refs", {}), dict) else "", preset.get("asset_prompt_kit_id"), default="civic_social_world_v1"),
        },
        "policy_refs": {
            "economy_policy_id": economy_policy_id,
            "item_collection_id": item_collection_id,
            "inventory_layer_policy_id": inventory_layer_policy_id,
            "role_item_policy_id": role_item_policy_id,
            "property_policy_id": property_policy_id,
            "knowledge_policy_id": knowledge_policy_id,
            "inventory_layers": profile_inventory_layers,
        },
    }
    return {
        "world_name": world_name,
        "world_id": world_id,
        "world_seed": world_seed,
        "genre": genre,
        "premise": premise,
        "simulation_objective": _first_non_empty(spec.get("simulation_objective"), f"Run a persistent {genre} world with {agent_count_target} agents and support {player_count_target} human players."),
        "agent_count_target": agent_count_target,
        "player_count_target": player_count_target,
        "wall_color_theme": str(spec.get("wall_color_theme", "dark_brick")),
        "economy_focus": _first_non_empty(spec.get("economy_focus"), request.get("focus"), default="balanced resource exchange"),
        "exploration_focus": _first_non_empty(spec.get("exploration_focus"), request.get("focus"), default="discover places, people, and useful leads"),
        "conflict_tone": _first_non_empty(spec.get("conflict_tone"), default="tense but playable"),
        "visual_style": _first_non_empty(spec.get("visual_style"), default=f"{genre} rendered as readable top-down pixel fantasy"),
        "rooms": normalized_rooms[:100],
        "role_groups": normalized_role_groups[:60],
        "main_characters": normalized_main_characters[:80],
        "gameplay_loops": normalized_loops[:30],
        "player_entry_points": player_entry_points[:20],
        "conflict_hooks": conflict_hooks[:20],
        "custom_actions": custom_actions[:40],
        "social_rules": [str(item).strip() for item in spec.get("social_rules", []) if str(item).strip()] or [
            "Agents should build relationships through repeated work, trade, and small favors.",
            "Conflict should generate new tasks or bargains instead of collapsing the world loop.",
        ],
        "item_themes": item_themes,
        "item_catalog": item_catalog,
    }


def _generate_summary(provider: VertexJsonClient, builder_spec: dict[str, Any], config: dict[str, Any]) -> str:
    from .generation_prompts import _world_summary_prompt as world_summary_prompt

    system_instruction = (
        "You are the world summarizer for Agora drafts. "
        "Write concise but vivid prose for a world creator who must review and approve a package before art generation."
    )
    return _execute_text_prompt(
        provider=provider,
        system_instruction=system_instruction,
        prompt=world_summary_prompt(builder_spec, config),
        temperature=0.45,
        max_output_tokens=3200,
        thinking_level="medium",
    )


def _build_revision_payload(
    *,
    package_root: Path,
    request: dict[str, Any],
    prior_context: dict[str, Any] | None,
    feedback: str,
    repair_note: str = "",
) -> tuple[dict[str, Any], dict[str, Any], str, Path, dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    from .nodes import (
        generate_planner_spec,
        generate_rooms_spec,
        generate_items_spec,
        generate_roles_spec,
        generate_hooks_spec,
        generate_materials_spec,
    )
    
    provider_pro = _world_creator_provider("pro")
    provider_lite = _world_creator_provider("lite")

    try:
        agent_count_target = int(request.get("agent_count_target") or 40)
    except Exception:
        agent_count_target = 40
    agent_count_target = max(8, min(120, agent_count_target))

    min_rooms = max(6, agent_count_target // 3)
    if "panjiayuan" in request.get("world_name", "").lower():
        min_rooms = 7
    min_items_catalog = max(15, agent_count_target // 2)
    min_merchant_items = max(15, agent_count_target // 3)

    attempts = 3
    last_error_spec = ""
    builder_spec = None
    raw_spec = {}
    
    for attempt in range(attempts):
        actual_repair_note = repair_note
        if last_error_spec:
            actual_repair_note = (repair_note + last_error_spec).strip()

        try:
            print(f"[Node Generation Attempt {attempt + 1}/{attempts}] Running Planner (Pro)...")
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_planner_spec...\n")
            planner_spec = generate_planner_spec(provider_pro, request, prior_context, feedback, actual_repair_note)
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Finished generate_planner_spec\n")
            
            print(f"[Node Generation Attempt {attempt + 1}/{attempts}] Running Rooms (Pro, target: >={min_rooms})...")
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_rooms_spec...\n")
            rooms_res = generate_rooms_spec(provider_pro, planner_spec, min_rooms)
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Finished generate_rooms_spec\n")
            rooms = rooms_res.get("rooms", [])
            wall_color_theme = rooms_res.get("wall_color_theme", "dark_brick")
            outdoor_terrain = rooms_res.get("outdoor_terrain", "dirt")
            
            print(f"[Node Generation Attempt {attempt + 1}/{attempts}] Running Materials (Pro)...")
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_materials_spec...\n")
            materials_spec = generate_materials_spec(provider_pro, planner_spec, rooms, actual_repair_note)
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Finished generate_materials_spec\n")
            
            # Map room materials by room name
            materials_by_name = {str(m.get("room_name", "")).strip().lower(): m for m in materials_spec if isinstance(m, dict)}
            for r in rooms:
                rname = str(r.get("name", "")).strip().lower()
                m = materials_by_name.get(rname)
                if m:
                    r["floor_tile"] = m.get("floor_tile", r.get("floor_tile"))
                    r["wall_tile"] = m.get("wall_tile", r.get("wall_tile"))
                    r["ambient_palette"] = m.get("ambient_palette", r.get("ambient_palette"))
                    r["visual_details"] = {
                        "showcase_shelf": bool(m.get("showcase_shelf", False)),
                        "showcase_item_colors": list(m.get("showcase_item_colors", [])),
                        "reflection_glares": bool(m.get("reflection_glares", False))
                    }
                else:
                    r["visual_details"] = {
                        "showcase_shelf": False,
                        "showcase_item_colors": [],
                        "reflection_glares": False
                    }
            
            print(f"[Node Generation Attempt {attempt + 1}/{attempts}] Running Items (Pro, target: >={min_items_catalog})...")
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_items_spec...\n")
            items = generate_items_spec(provider_pro, planner_spec, min_items_catalog)
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Finished generate_items_spec\n")
            
            print(f"[Node Generation Attempt {attempt + 1}/{attempts}] Running Roles (Pro, target merchants >={min_merchant_items})...")
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_roles_spec...\n")
            roles, main_chars = generate_roles_spec(provider_lite, planner_spec, rooms, items, agent_count_target, min_merchant_items)
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Finished generate_roles_spec\n")
            
            print(f"[Node Generation Attempt {attempt + 1}/{attempts}] Running Hooks (Pro)...")
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_hooks_spec...\n")
            hooks_spec = generate_hooks_spec(provider_pro, planner_spec, roles)
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Finished generate_hooks_spec\n")
            
            # Assemble raw spec
            raw_spec = {
                **planner_spec,
                "agent_count_target": agent_count_target,
                "wall_color_theme": wall_color_theme,
                "outdoor_terrain": outdoor_terrain,
                "rooms": rooms,
                "item_catalog": items,
                "role_groups": roles,
                "main_characters": main_chars,
                **hooks_spec
            }
            
            builder_spec = _normalize_builder_spec(raw_spec, request)
            break
            
        except Exception as e:
            import traceback
            with open("/tmp/generation_tracker.log", "a") as f:
                f.write(traceback.format_exc() + "\n")
            last_error_spec = f"Node Generation failed: {str(e)}\nPlease regenerate keeping constraints in mind."
            print(f"[Pipeline Retry {attempt + 1}/{attempts}] {last_error_spec}")

    if builder_spec is None:
        if not raw_spec:
            raise ValueError("All attempts to generate the world failed completely. Cannot continue.")
        builder_spec = _normalize_builder_spec(raw_spec, request)
    from .builder import _build_world_config_from_spec
    from .validation import _validation_workspace
    pipeline_artifacts = build_world_pipeline(builder_spec, request)
    config = _build_world_config_from_spec(package_root, builder_spec, request, pipeline_artifacts=pipeline_artifacts)
    package_db, package_validation, agent_payloads = _validation_workspace(package_root, config, finalize_agents=True, provider=provider_lite)
    critique = _critique_compiled_world_config(
        provider=provider_pro,
        request=request,
        builder_spec=builder_spec,
        config=config,
    )
    if critique.get("should_repair", False):
        repaired_builder_spec = _normalize_builder_spec(
            _apply_compiler_critique_to_builder_spec(builder_spec, critique),
            request,
        )
        repaired_pipeline_artifacts = build_world_pipeline(repaired_builder_spec, request)
        repaired_config = _build_world_config_from_spec(
            package_root,
            repaired_builder_spec,
            request,
            pipeline_artifacts=repaired_pipeline_artifacts,
        )
        repaired_package_db, repaired_validation, repaired_payloads = _validation_workspace(package_root, repaired_config, finalize_agents=True, provider=provider_lite)
        package_db.unlink(missing_ok=True)
        builder_spec = repaired_builder_spec
        config = repaired_config
        package_db = repaired_package_db
        pipeline_artifacts = repaired_pipeline_artifacts
        agent_payloads = repaired_payloads
        package_validation = {
            **repaired_validation,
            "compiler_critique_applied": True,
            "compiler_critique": critique,
        }
    else:
        package_validation = {
            **package_validation,
            "compiler_critique_applied": False,
            "compiler_critique": critique,
        }
    package_validation["pipeline_compiler_report"] = dict(pipeline_artifacts.get("compiler_report", {}))
    world_summary = _generate_summary(provider_pro, builder_spec, config)
    return builder_spec, config, world_summary, package_db, package_validation, critique, pipeline_artifacts, agent_payloads


def _generate_revision(
    *,
    package_root: Path,
    draft_id: str,
    revision_id: str,
    request: dict[str, Any],
    prior_context: dict[str, Any] | None,
    feedback: str,
) -> dict[str, Any]:
    revision_path = _revision_dir(package_root, draft_id, revision_id)
    revision_path.mkdir(parents=True, exist_ok=True)
    _write_text(revision_path / "input_brief.txt", str(request.get("brief", "")).strip())
    _write_text(revision_path / "user_feedback.txt", str(feedback or "").strip())
    last_error = ""
    for attempt in range(2):
        repair_note = last_error if attempt else ""
        try:
            builder_spec, config, world_summary, temp_package_db, package_validation, compiler_critique, pipeline_artifacts, agent_payloads = _build_revision_payload(
                package_root=package_root,
                request=request,
                prior_context=prior_context,
                feedback=feedback,
                repair_note=repair_note,
            )
            _write_json(_revision_builder_spec_path(package_root, draft_id, revision_id), builder_spec)
            _write_json(_revision_planner_path(package_root, draft_id, revision_id), pipeline_artifacts.get("planner", {}))
            _write_json(_revision_rooms_spec_path(package_root, draft_id, revision_id), pipeline_artifacts.get("rooms_spec", {}))
            _write_json(_revision_items_spec_path(package_root, draft_id, revision_id), pipeline_artifacts.get("items_spec", {}))
            _write_json(_revision_agents_spec_path(package_root, draft_id, revision_id), pipeline_artifacts.get("agents_spec", {}))
            _write_json(_revision_pixel_frontend_spec_path(package_root, draft_id, revision_id), pipeline_artifacts.get("pixel_frontend_spec", {}))
            _write_json(_revision_compiler_report_path(package_root, draft_id, revision_id), pipeline_artifacts.get("compiler_report", {}))
            _write_json(_revision_compiler_critique_path(package_root, draft_id, revision_id), compiler_critique)
            _write_json(_revision_world_config_path(package_root, draft_id, revision_id), config)
            materialize_scenario(config, _revision_scenario_dir(package_root, draft_id, revision_id), agent_payloads=agent_payloads)
            shutil.copy2(temp_package_db, _revision_package_path(package_root, draft_id, revision_id))
            temp_package_db.unlink(missing_ok=True)
            _write_text(_revision_summary_path(package_root, draft_id, revision_id), world_summary)
            from .builder import _structured_summary, _compiled_preview_from_config
            status = {
                "draft_id": draft_id,
                "revision_id": revision_id,
                "created_at": _now_iso(),
                "status": STATUS_DRAFT_READY,
                "world_name": str(config.get("scenario_meta", {}).get("world_name", "")),
                "world_id": str(config.get("scenario_meta", {}).get("world_id", "")),
                "summary_path": str(_revision_summary_path(package_root, draft_id, revision_id)),
                "package_path": str(_revision_package_path(package_root, draft_id, revision_id)),
                "world_config_path": str(_revision_world_config_path(package_root, draft_id, revision_id)),
                "scenario_dir": str(_revision_scenario_dir(package_root, draft_id, revision_id)),
                "structured_summary": _structured_summary(config),
                "compiler_critique": compiler_critique,
                "compiled_preview": _compiled_preview_from_config(config),
                "package_validation": package_validation,
                "startup_validation": dict(package_validation.get("startup_validation", {})),
                "world_summary_markdown": world_summary,
                "error": "",
            }
            _save_revision_status(package_root, draft_id, revision_id, status)
            return status
        except Exception as exc:
            import traceback
            with open("/tmp/generation_tracker.log", "a") as f:
                f.write(traceback.format_exc() + "\n")
            last_error = str(exc)
            if "Resource exhausted" in last_error or "429" in last_error:
                break
    failed_status = {
        "draft_id": draft_id,
        "revision_id": revision_id,
        "created_at": _now_iso(),
        "status": STATUS_DRAFT_FAILED,
        "world_name": str(request.get("world_name", "")),
        "world_id": _slug(str(request.get("world_name", "") or "draft_world")),
        "summary_path": "",
        "package_path": "",
        "world_config_path": "",
        "scenario_dir": "",
        "structured_summary": WorldBuilderStructuredSummarySpec().model_dump(),
        "compiler_critique": {},
        "compiled_preview": {},
        "package_validation": {},
        "startup_validation": {},
        "world_summary_markdown": "",
        "error": last_error,
    }
    _save_revision_status(package_root, draft_id, revision_id, failed_status)
    return failed_status
