from __future__ import annotations
from .generation_schemas import *
from .generation_prompts import _world_summary_prompt
from .critique_loop import *
from .critique_loop import _focus_profile, _synthesized_gameplay_loops, _apply_compiler_critique_to_builder_spec, _critique_compiled_world_config
import argparse
import copy
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
from ..openai_responses_client import OpenAIResponsesJsonClient
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


class DecoupledGenerationExhausted(ValueError):
    """Strict generation failed after exhausting its semantic repair budget."""

    def __init__(self, message: str, *, retry_events: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.generation_node_retries = copy.deepcopy(retry_events)



def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _world_creator_model(provider_type: str = "pro") -> str:
    if provider_type == "lite":
        return (
            str(os.environ.get("AGORA_WORLD_CREATOR_LITE_MODEL", "")).strip()
            or str(os.environ.get("AGORA_WORLD_CREATOR_MODEL", "")).strip()
            or "gemini-3.1-flash-lite"
        )
    return (
        str(os.environ.get("AGORA_WORLD_CREATOR_MODEL", "")).strip()
        or "gemini-3-flash-preview"
    )


def _non_retryable_generation_error(error: Exception | str) -> bool:
    text = str(error)
    return any(f"HTTP {status}" in text for status in (400, 401, 403, 404, 405, 422))


def _world_creator_timeout_seconds() -> float:
    return float(max(30, _env_int("AGORA_WORLD_CREATOR_TIMEOUT_SECONDS", 180)))


def _world_creator_max_retries() -> int:
    return max(1, _env_int("AGORA_WORLD_CREATOR_MAX_RETRIES", 3))


def _world_creator_max_output_tokens() -> int:
    return max(1024, _env_int("AGORA_WORLD_CREATOR_MAX_OUTPUT_TOKENS", 8192))


def _world_creator_thinking_level() -> str:
    raw = str(os.environ.get("AGORA_WORLD_CREATOR_THINKING_LEVEL", "high")).strip().lower()
    return raw if raw in {"none", "minimal", "low", "medium", "high"} else "high"


def _world_creator_thinking_budget() -> int:
    return max(0, _env_int("AGORA_WORLD_CREATOR_THINKING_BUDGET", 2046))


def _world_creator_provider(
    provider_type: str = "pro",
) -> VertexJsonClient | OpenAIResponsesJsonClient:
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
    max_output_tokens = _world_creator_max_output_tokens()
    thinking_level = _world_creator_thinking_level()
    thinking_budget = _world_creator_thinking_budget()
    config = {
        "vertex_api": {
            "backend": backend,
            "model": _world_creator_model(provider_type),
            "thinking_level": thinking_level,
            "thinking_budget": thinking_budget,
            "temperature": 0.2,
            "max_output_tokens": max_output_tokens,
            "timeout_seconds": int(_world_creator_timeout_seconds()),
            "api_key_env": "AGORA_AISTUDIO_API_KEY",
            "pacing_sleep_seconds": 1.0,
            "stages": {
                "world_creator_generation": {
                    "max_output_tokens": max_output_tokens,
                    "thinking_level": thinking_level,
                    "thinking_budget": thinking_budget,
                },
                "world_creator_text_generation": {
                    "max_output_tokens": max_output_tokens,
                    "thinking_level": "medium",
                    "thinking_budget": min(thinking_budget, 1024) if thinking_budget > 0 else 0,
                },
                "agent_wardrobe_policy_generation": {
                    "model": str(os.environ.get("AGORA_WARDROBE_POLICY_MODEL", "")).strip() or _world_creator_model("lite"),
                    "max_output_tokens": min(max_output_tokens, 4096),
                    "thinking_level": "low",
                    "thinking_budget": 128 if thinking_budget > 0 else 0,
                },
                "world_visual_canon_generation": {
                    "model": str(os.environ.get("AGORA_VISUAL_CANON_MODEL", "")).strip() or _world_creator_model("lite"),
                    "max_output_tokens": min(max_output_tokens, 2048),
                    "thinking_level": "low",
                    "thinking_budget": 128 if thinking_budget > 0 else 0,
                },
                "main_character_generation": {
                    "model": str(os.environ.get("AGORA_MAIN_CHARACTER_MODEL", "")).strip() or _world_creator_model("lite"),
                    "max_output_tokens": max(4096, _env_int("AGORA_MAIN_CHARACTER_MAX_OUTPUT_TOKENS", 8192)),
                    "thinking_level": "medium",
                    "thinking_budget": max(thinking_budget, _env_int("AGORA_MAIN_CHARACTER_THINKING_BUDGET", 2046)),
                },
                "main_character_profile_generation": {
                    "model": str(os.environ.get("AGORA_MAIN_CHARACTER_PROFILE_MODEL", "")).strip() or _world_creator_model("lite"),
                    "max_output_tokens": _env_int("AGORA_MAIN_CHARACTER_PROFILE_MAX_OUTPUT_TOKENS", 4096),
                    "thinking_level": "medium",
                    "thinking_budget": max(0, _env_int("AGORA_MAIN_CHARACTER_PROFILE_THINKING_BUDGET", 512)),
                },
                "agent_profile_generation": {
                    "model": str(os.environ.get("AGORA_AGENT_PROFILE_MODEL", "")).strip() or _world_creator_model("lite"),
                    "max_output_tokens": _env_int("AGORA_AGENT_PROFILE_MAX_OUTPUT_TOKENS", 4096),
                    "thinking_level": "low",
                    "thinking_budget": max(0, _env_int("AGORA_AGENT_PROFILE_THINKING_BUDGET", 128)),
                },
                "initial_inventory_generation": {
                    "model": str(os.environ.get("AGORA_INITIAL_INVENTORY_MODEL", "")).strip() or _world_creator_model("lite"),
                    "max_output_tokens": max(max_output_tokens, _env_int("AGORA_INITIAL_INVENTORY_MAX_OUTPUT_TOKENS", 12288)),
                    "thinking_level": "medium",
                    "thinking_budget": max(0, _env_int("AGORA_INITIAL_INVENTORY_THINKING_BUDGET", 1024)),
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
    if backend.lower() in {"openai", "openai_responses", "gpt"}:
        openai_config = dict(config["vertex_api"])
        openai_config.pop("backend", None)
        openai_config["api_key_env"] = str(
            os.environ.get("AGORA_GPT_API_KEY_ENV", "AGORA_GPT_API_KEY")
        ).strip() or "AGORA_GPT_API_KEY"
        openai_config["endpoint_base"] = str(
            os.environ.get("AGORA_GPT_BASE_URL", "https://api.openai.com/v1")
        ).strip().rstrip("/")
        return OpenAIResponsesJsonClient({"openai_api": openai_config})
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
    thinking_budget: int | None = None,
    stage: str = "world_creator_generation",
) -> dict[str, Any]:
    forced_temperature = str(os.environ.get("AGORA_EXPERIMENT_FORCE_TEMPERATURE", "")).strip()
    forced_thinking_level = str(os.environ.get("AGORA_EXPERIMENT_FORCE_THINKING_LEVEL", "")).strip().lower()
    forced_thinking_budget = str(os.environ.get("AGORA_EXPERIMENT_FORCE_THINKING_BUDGET", "")).strip()
    if forced_temperature:
        temperature = float(forced_temperature)
    if forced_thinking_level:
        if forced_thinking_level not in {"none", "minimal", "low", "medium", "high"}:
            raise ValueError(
                "AGORA_EXPERIMENT_FORCE_THINKING_LEVEL must be none, minimal, low, medium, or high"
            )
        thinking_level = forced_thinking_level
    if forced_thinking_budget:
        thinking_budget = max(0, int(forced_thinking_budget))

    provider.temperature = temperature
    provider.max_output_tokens = max_output_tokens
    provider.thinking_level = thinking_level
    if thinking_budget is not None:
        provider.thinking_budget = max(0, int(thinking_budget))
    stages = getattr(provider, "stages", None)
    if isinstance(stages, dict):
        stage_config = dict(stages.get(stage, {})) if isinstance(stages.get(stage, {}), dict) else {}
        stage_config.update(
            {
                "temperature": float(temperature),
                "max_output_tokens": int(max_output_tokens),
                "thinking_level": str(thinking_level),
                "thinking_budget": int(getattr(provider, "thinking_budget", 0)),
            }
        )
        stages[stage] = stage_config

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
    thinking_budget: int | None = None,
) -> str:
    forced_temperature = str(os.environ.get("AGORA_EXPERIMENT_FORCE_TEMPERATURE", "")).strip()
    forced_thinking_level = str(os.environ.get("AGORA_EXPERIMENT_FORCE_THINKING_LEVEL", "")).strip().lower()
    forced_thinking_budget = str(os.environ.get("AGORA_EXPERIMENT_FORCE_THINKING_BUDGET", "")).strip()
    if forced_temperature:
        temperature = float(forced_temperature)
    if forced_thinking_level:
        if forced_thinking_level not in {"none", "minimal", "low", "medium", "high"}:
            raise ValueError(
                "AGORA_EXPERIMENT_FORCE_THINKING_LEVEL must be none, minimal, low, medium, or high"
            )
        thinking_level = forced_thinking_level
    if forced_thinking_budget:
        thinking_budget = max(0, int(forced_thinking_budget))

    provider.temperature = temperature
    provider.max_output_tokens = max_output_tokens
    provider.thinking_level = thinking_level
    if thinking_budget is not None:
        provider.thinking_budget = max(0, int(thinking_budget))
    stage = "world_creator_text_generation"
    stages = getattr(provider, "stages", None)
    if isinstance(stages, dict):
        stage_config = dict(stages.get(stage, {})) if isinstance(stages.get(stage, {}), dict) else {}
        stage_config.update(
            {
                "temperature": float(temperature),
                "max_output_tokens": int(max_output_tokens),
                "thinking_level": str(thinking_level),
                "thinking_budget": int(getattr(provider, "thinking_budget", 0)),
            }
        )
        stages[stage] = stage_config

    text = provider.generate_text(
        system_instruction=system_instruction,
        prompt=prompt,
        stage=stage,
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
        scene_components = [
            {
                "component_id": _slug(str(component.get("component_id", "") or component.get("label", ""))),
                "label": str(component.get("label", "")).strip(),
                "description": str(component.get("description", "")).strip(),
                "anchor": str(component.get("anchor", "center")).strip(),
                "width_tiles": min(3, max(1, int(component.get("width_tiles", 1) or 1))),
                "height_tiles": min(3, max(1, int(component.get("height_tiles", 1) or 1))),
            }
            for component in room.get("scene_components", [])
            if isinstance(component, dict)
            and str(component.get("component_id", "") or component.get("label", "")).strip()
            and str(component.get("description", "")).strip()
        ]
        if not scene_components and isinstance(spec.get("visual_canon"), dict) and spec.get("visual_canon"):
            raise ValueError(f"Room {room.get('name', index + 1)!r} has no valid semantic scene component.")
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
                "scene_components": scene_components[:2],
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
        inventory = [
            dict(item)
            for item in character.get("inventory", [])
            if isinstance(item, dict) and str(item.get("name") or item.get("item_id") or "").strip()
        ]
        property_templates = [dict(item) for item in character.get("property_templates", []) if isinstance(item, dict)]
        knowledge_templates = [dict(item) for item in character.get("knowledge_templates", []) if isinstance(item, dict)]
        normalized_main_characters.append(
            {
                "display_name": _first_non_empty(character.get("display_name"), default=f"Main Character {index + 1}"),
                "role_name": _first_non_empty(character.get("role_name"), default=f"Lead {index + 1}"),
                "activity": _first_non_empty(character.get("activity"), default="drives a visible thread of world activity forward"),
                "home_base": _first_non_empty(character.get("home_base"), default=""),
                "arc_goal": _first_non_empty(character.get("arc_goal"), character.get("activity"), default=""),
                "inventory": inventory,
                "property_templates": property_templates,
                "knowledge_templates": knowledge_templates,
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
    open_action_examples = [
        dict(item) for item in spec.get("open_action_examples", []) if isinstance(item, dict)
    ][:12]
    world_id = _slug(_first_non_empty(spec.get("world_id"), world_name))
    raw_world_seed = dict(spec.get("world_seed", {})) if isinstance(spec.get("world_seed", {}), dict) else {}
    agent_visual_policy = dict(spec.get("agent_visual_policy", {})) if isinstance(spec.get("agent_visual_policy", {}), dict) else {}
    visual_canon = dict(spec.get("visual_canon", {})) if isinstance(spec.get("visual_canon", {}), dict) else {}
    
    item_catalog = []
    if "item_catalog" in spec and isinstance(spec["item_catalog"], list):
        for raw in spec["item_catalog"]:
            if isinstance(raw, dict) and "item_id" in raw:
                item_catalog.append(raw)

    raw_preset_id = _first_non_empty(raw_world_seed.get("preset_id"), raw_world_seed.get("profile_id"))
    legacy_preset_id = raw_preset_id if raw_preset_id in WORLD_PROFILE_LIBRARY else ""
    legacy_preset = dict(WORLD_PROFILE_LIBRARY.get(legacy_preset_id, {}))
    default_wallet = {"min": 1800, "max": 9000}
    if legacy_preset:
        economy_policy_id = _first_non_empty(
            raw_world_seed.get("policy_refs", {}).get("economy_policy_id")
            if isinstance(raw_world_seed.get("policy_refs", {}), dict) else "",
            legacy_preset.get("economy_policy_id"),
            default="civic_credit_v1",
        )
        economy_policy = dict(
            ECONOMY_POLICY_REGISTRY.get(economy_policy_id, ECONOMY_POLICY_REGISTRY["civic_credit_v1"])
        )
        default_wallet = dict(economy_policy.get("starting_wallet_minor", default_wallet))
    raw_starting_wallet = dict(raw_world_seed.get("starting_wallet_minor", {})) if isinstance(raw_world_seed.get("starting_wallet_minor", {}), dict) else {}
    starting_wallet_minor = {
        "min": max(0, int(raw_starting_wallet.get("min", default_wallet.get("min", 1800)) or 1800)),
        "max": max(
            0,
            int(
                raw_starting_wallet.get(
                    "max",
                    raw_starting_wallet.get("min", default_wallet.get("max", 9000)),
                )
                or 9000
            ),
        ),
    }
    world_seed = {
        "seed_version": _first_non_empty(raw_world_seed.get("seed_version"), default="world_seed_v3_open"),
        "locale": _first_non_empty(raw_world_seed.get("locale"), legacy_preset.get("locale"), default="en"),
        "tone": _first_non_empty(raw_world_seed.get("tone"), genre, default=genre),
        "visual_direction": _first_non_empty(raw_world_seed.get("visual_direction"), spec.get("visual_style"), default=genre),
        "currency_code": _first_non_empty(raw_world_seed.get("currency_code"), default="CRD"),
        "currency_symbol": _first_non_empty(raw_world_seed.get("currency_symbol"), default="cr"),
        "currency_minor_unit": _first_non_empty(raw_world_seed.get("currency_minor_unit"), default="point"),
        "currency_name": _first_non_empty(raw_world_seed.get("currency_name"), default="local credit"),
        "domain_label": _first_non_empty(raw_world_seed.get("domain_label"), legacy_preset.get("default_domain_label"), spec.get("economy_focus"), spec.get("premise"), default=genre),
        "starting_wallet_minor": starting_wallet_minor,
    }
    if legacy_preset:
        world_seed.update(
            {
                "preset_id": legacy_preset_id,
                "profile_id": legacy_preset_id,
                "kit_refs": dict(raw_world_seed.get("kit_refs", {})),
                "policy_refs": dict(raw_world_seed.get("policy_refs", {})),
            }
        )
    return {
        "world_name": world_name,
        "world_id": world_id,
        "world_seed": world_seed,
        "world_dynamics": dict(spec.get("world_dynamics", {})),
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
        "open_action_examples": open_action_examples,
        "social_rules": [str(item).strip() for item in spec.get("social_rules", []) if str(item).strip()] or [
            "Agents should build relationships through repeated work, trade, and small favors.",
            "Conflict should generate new tasks or bargains instead of collapsing the world loop.",
        ],
        "item_themes": item_themes,
        "item_catalog": item_catalog,
        "agent_visual_policy": agent_visual_policy,
        "visual_canon": visual_canon,
    }


def _validate_decoupled_generation_contract(
    spec: dict[str, Any],
    *,
    min_rooms: int,
    min_items_catalog: int,
    expected_characters: int,
) -> None:
    failures: list[str] = []
    required_planner_fields = (
        "world_name",
        "world_id",
        "world_seed",
        "genre",
        "premise",
        "simulation_objective",
        "economy_focus",
        "exploration_focus",
        "conflict_tone",
        "visual_style",
    )
    for field in required_planner_fields:
        value = spec.get(field)
        if not value or (isinstance(value, dict) and not value):
            failures.append(f"planner.{field} is missing")

    world_dynamics = spec.get("world_dynamics", {})
    if not isinstance(world_dynamics, dict):
        failures.append("planner.world_dynamics is missing")
    else:
        if len([item for item in world_dynamics.get("institutions", []) if isinstance(item, dict)]) < 3:
            failures.append("planner produced fewer than 3 institutions")
        state_ids = {
            str(item.get("state_id", "")).strip()
            for item in world_dynamics.get("state_variables", [])
            if isinstance(item, dict) and str(item.get("state_id", "")).strip()
        }
        if len(state_ids) < 4:
            failures.append("planner produced fewer than 4 unique state variables")
        causal_links = [item for item in world_dynamics.get("causal_links", []) if isinstance(item, dict)]
        if len(causal_links) < 4:
            failures.append("planner produced fewer than 4 causal links")
        for index, link in enumerate(causal_links, start=1):
            refs = {
                str(link.get(field, "")).strip()
                for field in ("source_state", "target_state")
            }
            if not refs.issubset(state_ids):
                failures.append(f"planner causal link {index} has unresolved state IDs")
        if len([item for item in world_dynamics.get("stakeholder_groups", []) if isinstance(item, dict)]) < 3:
            failures.append("planner produced fewer than 3 stakeholder groups")

    visual_canon = spec.get("visual_canon", {})
    if not isinstance(visual_canon, dict) or not visual_canon:
        failures.append("visual_canon node output is missing")
    wardrobe = spec.get("agent_visual_policy", {})
    if not isinstance(wardrobe, dict) or not wardrobe:
        failures.append("wardrobe node output is missing")

    rooms = [entry for entry in spec.get("rooms", []) if isinstance(entry, dict)]
    if len(rooms) < min_rooms:
        failures.append(f"rooms node produced {len(rooms)} rooms; required {min_rooms}")
    for index, room in enumerate(rooms, start=1):
        if not str(room.get("name", "")).strip():
            failures.append(f"room {index} has no name")
        if not [item for item in room.get("scene_components", []) if isinstance(item, dict)]:
            failures.append(f"room {index} has no semantic scene components")
        if not str(room.get("floor_tile", "")).strip() or not str(room.get("wall_tile", "")).strip():
            failures.append(f"room {index} has no matched materials output")

    items = [entry for entry in spec.get("item_catalog", []) if isinstance(entry, dict)]
    if len(items) < min_items_catalog:
        failures.append(
            f"items node produced {len(items)} items; required {min_items_catalog}"
        )

    characters = [
        entry for entry in spec.get("main_characters", []) if isinstance(entry, dict)
    ]
    if len(characters) != expected_characters:
        failures.append(
            f"roles node produced {len(characters)} characters; required {expected_characters}"
        )
    for index, character in enumerate(characters, start=1):
        inventory = [
            item
            for item in character.get("inventory", [])
            if isinstance(item, dict)
            and str(item.get("name") or item.get("item_id") or "").strip()
            and str(item.get("description", "")).strip()
        ]
        if len(inventory) < 8:
            failures.append(f"character {index} has fewer than 8 valid inventory items")
        if len(
            [item for item in character.get("property_templates", []) if isinstance(item, dict)]
        ) < 2:
            failures.append(f"character {index} has fewer than 2 property templates")
        if len(
            [item for item in character.get("knowledge_templates", []) if isinstance(item, dict)]
        ) < 2:
            failures.append(f"character {index} has fewer than 2 knowledge templates")

    if len([item for item in spec.get("social_rules", []) if str(item).strip()]) < 1:
        failures.append("hooks node produced no social rules")
    if len([item for item in spec.get("player_entry_points", []) if str(item).strip()]) < 1:
        failures.append("hooks node produced no player entry points")
    if len([item for item in spec.get("conflict_hooks", []) if str(item).strip()]) < 2:
        failures.append("hooks node produced fewer than 2 conflict hooks")
    if len([item for item in spec.get("custom_actions", []) if str(item).strip()]) < 6:
        failures.append("hooks node produced fewer than 6 custom actions")
    if len([item for item in spec.get("open_action_examples", []) if isinstance(item, dict)]) < 4:
        failures.append("hooks node produced fewer than 4 open-action examples")
    if len([item for item in spec.get("gameplay_loops", []) if isinstance(item, dict)]) < 3:
        failures.append("hooks node produced fewer than 3 gameplay loops")
    room_names = {
        str(room.get("name", "")).strip()
        for room in rooms
        if str(room.get("name", "")).strip()
    }
    role_names = {
        str(entry.get("role_name", "")).strip()
        for entry in [
            *[item for item in spec.get("role_groups", []) if isinstance(item, dict)],
            *characters,
        ]
        if str(entry.get("role_name", "")).strip()
    }
    for index, loop in enumerate(spec.get("gameplay_loops", []), start=1):
        if not isinstance(loop, dict):
            continue
        loop_rooms = {
            str(value).strip() for value in loop.get("rooms", []) if str(value).strip()
        }
        loop_roles = {
            str(value).strip() for value in loop.get("roles", []) if str(value).strip()
        }
        if not loop_rooms or not loop_rooms.issubset(room_names):
            failures.append(
                f"hooks loop {index} has unresolved rooms: "
                f"{sorted(loop_rooms - room_names) or ['<missing>']}"
            )
        if not loop_roles or not loop_roles.issubset(role_names):
            failures.append(
                f"hooks loop {index} has unresolved roles: "
                f"{sorted(loop_roles - role_names) or ['<missing>']}"
            )

    if failures:
        raise ValueError(
            "Decoupled generation contract failed; deterministic content fallback is "
            "forbidden: " + "; ".join(failures)
        )


def _generation_cache_keys_to_invalidate(
    active_node_key: str,
    error: Exception | str,
) -> set[str]:
    dependencies = {
        "planner": {
            "planner",
            "visual_canon",
            "rooms",
            "materials",
            "items",
            "roles",
            "wardrobe",
            "hooks",
        },
        "visual_canon": {
            "visual_canon",
            "rooms",
            "materials",
            "items",
            "roles",
            "wardrobe",
            "hooks",
        },
        "rooms": {"rooms", "materials", "roles", "wardrobe", "hooks"},
        "materials": {"materials"},
        "items": {"items", "roles", "wardrobe"},
        "roles": {"roles", "wardrobe", "hooks"},
        "wardrobe": {"wardrobe"},
        "hooks": {"hooks"},
    }
    if active_node_key in dependencies:
        return set(dependencies[active_node_key])

    message = str(error).lower()
    invalidated: set[str] = set()
    if "visual_canon" in message or "visual canon" in message:
        invalidated.update(dependencies["visual_canon"])
    if "room" in message or "component" in message:
        invalidated.update(dependencies["rooms"])
    if any(
        marker in message
        for marker in ("items node", "item_catalog", "item catalog", "catalog")
    ):
        invalidated.update(dependencies["items"])
    if any(
        marker in message
        for marker in (
            "character",
            "inventory",
            "merchant",
            "property",
            "knowledge",
            "role",
        )
    ):
        invalidated.update(dependencies["roles"])
    if "wardrobe" in message or "visual policy" in message:
        invalidated.update(dependencies["wardrobe"])
    if any(
        marker in message
        for marker in (
            "hook",
            "gameplay",
            "social rule",
            "custom action",
            "entry point",
            "conflict",
        )
    ):
        invalidated.update(dependencies["hooks"])
    return invalidated or set(dependencies["planner"])


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
        thinking_level="low",
    )


def _build_revision_payload(
    *,
    package_root: Path,
    request: dict[str, Any],
    prior_context: dict[str, Any] | None,
    feedback: str,
    repair_note: str = "",
) -> tuple[dict[str, Any], dict[str, Any], str, Path, dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    import copy

    from .nodes import (
        generate_planner_spec,
        generate_rooms_spec,
        generate_items_spec,
        generate_roles_spec,
        generate_hooks_spec,
        generate_materials_spec,
        generate_wardrobe_policy,
        generate_visual_canon,
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
    min_character_items = 8

    node_attempt_limit = 3
    max_pipeline_passes = node_attempt_limit * 9
    last_error_spec = ""
    builder_spec = None
    raw_spec = {}
    node_cache: dict[str, Any] = {}
    node_retry_events: list[dict[str, Any]] = []
    node_failure_counts: dict[str, int] = {}
    active_node_key = ""

    def cached_node(key: str, factory: Any) -> Any:
        if key not in node_cache:
            node_cache[key] = factory()
        return copy.deepcopy(node_cache[key])
    
    for attempt in range(max_pipeline_passes):
        actual_repair_note = repair_note
        if last_error_spec:
            actual_repair_note = (repair_note + last_error_spec).strip()

        try:
            print(f"[Node Generation Pass {attempt + 1}/{max_pipeline_passes}] Running Planner (Pro)...")
            active_node_key = "planner"
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_planner_spec...\n")
            planner_spec = cached_node(
                "planner",
                lambda: generate_planner_spec(provider_pro, request, prior_context, feedback, actual_repair_note),
            )
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Finished generate_planner_spec\n")

            print(f"[Node Generation Pass {attempt + 1}/{max_pipeline_passes}] Running Visual Canon (Lite)...")
            active_node_key = "visual_canon"
            with open("/tmp/generation_tracker.log", "a") as f: f.write("[TRACKER] Starting generate_visual_canon...\n")
            visual_canon = cached_node(
                "visual_canon",
                lambda: generate_visual_canon(provider_lite, planner_spec, actual_repair_note),
            )
            planner_spec = {**planner_spec, "visual_canon": visual_canon}
            with open("/tmp/generation_tracker.log", "a") as f: f.write("[TRACKER] Finished generate_visual_canon\n")
            
            print(f"[Node Generation Pass {attempt + 1}/{max_pipeline_passes}] Running Rooms (Pro, target: >={min_rooms})...")
            active_node_key = "rooms"
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_rooms_spec...\n")
            rooms_res = cached_node(
                "rooms",
                lambda: generate_rooms_spec(provider_pro, planner_spec, min_rooms),
            )
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Finished generate_rooms_spec\n")
            rooms = rooms_res.get("rooms", [])
            wall_color_theme = rooms_res.get("wall_color_theme", "dark_brick")
            outdoor_terrain = rooms_res.get("outdoor_terrain", "dirt")
            
            print(f"[Node Generation Pass {attempt + 1}/{max_pipeline_passes}] Running Materials (Pro)...")
            active_node_key = "materials"
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_materials_spec...\n")
            materials_spec = cached_node(
                "materials",
                lambda: generate_materials_spec(provider_pro, planner_spec, rooms, actual_repair_note),
            )
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Finished generate_materials_spec\n")
            
            # Map room materials by room name
            materials_by_name = {str(m.get("room_name", "")).strip().lower(): m for m in materials_spec if isinstance(m, dict)}
            unmatched_room_names: list[str] = []
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
                    unmatched_room_names.append(str(r.get("name", "")).strip())
            if unmatched_room_names:
                raise ValueError(
                    "Materials node omitted rooms: " + ", ".join(unmatched_room_names)
                )
            
            print(f"[Node Generation Pass {attempt + 1}/{max_pipeline_passes}] Running Items (Pro, target: >={min_items_catalog})...")
            active_node_key = "items"
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_items_spec...\n")
            items = cached_node(
                "items",
                lambda: generate_items_spec(provider_pro, planner_spec, min_items_catalog),
            )
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Finished generate_items_spec\n")
            
            print(f"[Node Generation Pass {attempt + 1}/{max_pipeline_passes}] Running Roles (Pro, personal inventory >={min_character_items})...")
            active_node_key = "roles"
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_roles_spec...\n")
            roles, main_chars = cached_node(
                "roles",
                lambda: generate_roles_spec(
                    provider_lite,
                    planner_spec,
                    rooms,
                    items,
                    agent_count_target,
                    min_character_items,
                    actual_repair_note,
                ),
            )
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Finished generate_roles_spec\n")

            print(f"[Node Generation Pass {attempt + 1}/{max_pipeline_passes}] Running Wardrobe Policy (Lite)...")
            active_node_key = "wardrobe"
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_wardrobe_policy...\n")
            wardrobe_policy = cached_node(
                "wardrobe",
                lambda: generate_wardrobe_policy(
                    provider_lite,
                    planner_spec,
                    rooms,
                    roles,
                    main_chars,
                    items,
                    actual_repair_note,
                ),
            )
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Finished generate_wardrobe_policy\n")
            
            print(f"[Node Generation Pass {attempt + 1}/{max_pipeline_passes}] Running Hooks (Pro)...")
            active_node_key = "hooks"
            with open("/tmp/generation_tracker.log", "a") as f: f.write(f"[TRACKER] Starting generate_hooks_spec...\n")
            hooks_spec = cached_node(
                "hooks",
                lambda: generate_hooks_spec(
                    provider_pro,
                    planner_spec,
                    roles,
                    rooms=rooms,
                    main_characters=main_chars,
                    repair_note=actual_repair_note,
                ),
            )
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
                "agent_visual_policy": wardrobe_policy,
                "visual_canon": visual_canon,
                **hooks_spec
            }

            active_node_key = "contract"
            _validate_decoupled_generation_contract(
                raw_spec,
                min_rooms=min_rooms,
                min_items_catalog=min_items_catalog,
                expected_characters=max(8, min(40, agent_count_target)),
            )
            builder_spec = _normalize_builder_spec(raw_spec, request)
            break
            
        except Exception as e:
            import traceback
            with open("/tmp/generation_tracker.log", "a") as f:
                f.write(traceback.format_exc() + "\n")
            last_error_spec = f"Node Generation failed: {str(e)}\nPlease regenerate keeping constraints in mind."
            failed_node = active_node_key or "unknown"
            node_failure_counts[failed_node] = node_failure_counts.get(failed_node, 0) + 1
            failed_node_attempt = node_failure_counts[failed_node]
            print(
                f"[Pipeline Retry node={failed_node} "
                f"attempt={failed_node_attempt}/{node_attempt_limit}] {last_error_spec}"
            )
            if _non_retryable_generation_error(e):
                raise
            invalidated_keys = _generation_cache_keys_to_invalidate(
                active_node_key,
                e,
            )
            for key in invalidated_keys:
                node_cache.pop(key, None)
            node_retry_events.append(
                {
                    "attempt": attempt + 1,
                    "failed_node": failed_node,
                    "failed_node_attempt": failed_node_attempt,
                    "error": f"{type(e).__name__}: {str(e)[:1000]}",
                    "invalidated_cache_keys": sorted(invalidated_keys),
                    "preserved_cache_keys": sorted(node_cache),
                }
            )
            if failed_node_attempt >= node_attempt_limit:
                break

    if builder_spec is None:
        raise DecoupledGenerationExhausted(
            "All decoupled generation attempts failed strict validation; no fallback "
            "world was compiled.",
            retry_events=node_retry_events,
        )
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
    package_validation["generation_node_retries"] = list(node_retry_events)
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
    # Provider and node-level retries already handle transient failures. Rebuilding
    # the entire world repeats every successful LLM call and is prohibitively costly.
    for attempt in range(1):
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
            _write_json(revision_path / "wardrobe_policy.json", builder_spec.get("agent_visual_policy", {}))
            _write_json(revision_path / "visual_canon.json", builder_spec.get("visual_canon", {}))
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
            if (
                "Resource exhausted" in last_error
                or "429" in last_error
                or _non_retryable_generation_error(exc)
            ):
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
