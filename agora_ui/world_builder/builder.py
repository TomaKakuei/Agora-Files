from __future__ import annotations
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



def _scaled_counts(role_groups: list[dict[str, Any]], total_regular_agents: int) -> list[int]:
    base_total = sum(max(1, int(entry.get("count", 1))) for entry in role_groups)
    if base_total <= 0:
        return [total_regular_agents]
    scaled: list[int] = []
    running_total = 0
    remainders: list[tuple[float, int]] = []
    for index, entry in enumerate(role_groups):
        proportion = (max(1, int(entry.get("count", 1))) / base_total) * total_regular_agents
        count = int(math.floor(proportion))
        scaled.append(count)
        running_total += count
        remainders.append((proportion - count, index))
    for _, index in sorted(remainders, reverse=True)[: max(0, total_regular_agents - running_total)]:
        scaled[index] += 1
    return [max(1, value) for value in scaled]


def _cycled_value(items: list[Any], index: int, default: Any) -> Any:
    if not items:
        return default
    return items[index % len(items)]


def _allowed_item_ids(config: dict[str, Any]) -> list[str]:
    raw = config.get("inventory_generation", {}).get("allowed_item_ids", [])
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _deep_replace_exact_strings(payload: Any, replacements: dict[str, str]) -> Any:
    if isinstance(payload, dict):
        updated: dict[Any, Any] = {}
        for key, value in payload.items():
            next_key = replacements.get(key, key) if isinstance(key, str) else key
            updated[next_key] = _deep_replace_exact_strings(value, replacements)
        return updated
    if isinstance(payload, list):
        return [_deep_replace_exact_strings(item, replacements) for item in payload]
    if isinstance(payload, str):
        return replacements.get(payload, payload)
    return payload


def _item_id_from_hint(hint: str, allowed_item_ids: list[str]) -> str:
    normalized_hint = str(hint or "").strip().lower()
    if not normalized_hint:
        return ""
    exact = {item.lower(): item for item in allowed_item_ids}
    if normalized_hint in exact:
        return exact[normalized_hint]
    worldish_pairs = [
        (("contract", "commission", "permit", "consign"), "consignment_note"),
        (("apprais", "verify", "opinion", "authentic"), "appraisal_slip"),
        (("broker", "buyer", "contact", "network"), "buyer_card"),
        (("store", "stash", "storage", "ticket", "warehouse"), "storage_ticket"),
        (("repair", "tool", "parts", "kit", "workshop", "measure"), "loupe"),
        (("flashlight", "uv", "surface"), "uv_flashlight"),
        (("pack", "cloth", "wrap"), "packing_cloth"),
        (("tea", "talk", "hospitality"), "tea_flask"),
        (("smoke", "cigarette"), "cigarette_pack"),
        (("glove", "handle"), "cloth_gloves"),
        (("porcelain", "ceramic"), "porcelain_shard_set"),
        (("jade", "stone"), "jade_pendant"),
        (("photo", "archive", "paper"), "old_photo_bundle"),
        (("fake", "forg", "replica", "copy"), "high_copy_bracelet"),
    ]
    for tokens, candidate_id in worldish_pairs:
        if any(token in normalized_hint for token in tokens) and candidate_id in allowed_item_ids:
            return candidate_id
    if any(token in normalized_hint for token in ("ration", "food", "supply", "cargo", "travel")):
        for candidate_id in ("tea_flask", "packing_cloth", "storage_ticket"):
            if candidate_id in allowed_item_ids:
                return candidate_id
    return ""


def _inventory_specs_for_role(
    *,
    config: dict[str, Any],
    role_group: dict[str, Any],
    item_themes: list[str],
    focus_profile: dict[str, Any],
    index: int,
) -> list[dict[str, Any]]:
    allowed_item_ids = _allowed_item_ids(config)
    hints = list(role_group.get("starting_items", [])) + item_themes
    role_tokens = _keyword_tokens(role_group.get("role_name", ""), role_group.get("activity", ""))
    if {"trade", "broker", "merchant", "seller", "dealer", "stall"} & role_tokens:
        hints.extend(["consignment note", "buyer contact", "packing cloth"])
    if {"pilot", "scout", "explore", "cartograph", "route", "rumor"} & role_tokens:
        hints.extend(["buyer contact", "storage ticket", "old photo bundle"])
    if {"heal", "medic", "care"} & role_tokens:
        hints.extend(["cloth gloves", "tea flask"])
    if {"repair", "maker", "forge", "engineer", "apprais", "inspect"} & role_tokens:
        hints.extend(["loupe", "uv flashlight", "appraisal slip"])
    if {"archive", "book", "record", "history"} & role_tokens:
        hints.extend(["old photo bundle", "stall ledger copy"])
    if focus_profile.get("economy"):
        hints.append("tea flask")
    selected: list[str] = []
    for hint in hints:
        item_id = _item_id_from_hint(str(hint), allowed_item_ids)
        if item_id and item_id not in selected:
            selected.append(item_id)
        if len(selected) >= 3:
            break
    if not selected:
        defaults = ["consignment_note", "buyer_card", "packing_cloth", "loupe", "tea_flask"]
        selected = [item_id for item_id in defaults if item_id in allowed_item_ids][:2]
    inventory: list[dict[str, Any]] = []
    for offset, item_id in enumerate(selected):
        inventory.append(
            {
                "item_id": item_id,
                "quantity": 2 if offset == 0 and item_id in {"tea_flask", "packing_cloth"} else 1,
            }
        )
    return inventory


def _inventory_specs_from_item_ids(item_ids: list[str]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for offset, raw_item_id in enumerate(item_ids):
        item_id = str(raw_item_id or "").strip()
        if not item_id:
            continue
        counts[item_id] = counts.get(item_id, 0) + (2 if offset == 0 and item_id in {"tea_flask", "tea_tin", "packing_cloth"} else 1)
    
    return [
        {
            "item_id": k,
            "quantity": v,
        }
        for k, v in counts.items()
    ]


def _choose_room_id(
    rooms: list[dict[str, Any]],
    *signals: Any,
    fallback_room_id: str,
) -> str:
    if not rooms:
        return fallback_room_id
    best_room = dict(rooms[0])
    best_score = -1
    target_tokens = _keyword_tokens(*signals)
    for room in rooms:
        metadata = dict(room.get("metadata", {})) if isinstance(room.get("metadata", {}), dict) else {}
        score = _keyword_overlap_score(
            room.get("name", ""),
            metadata.get("purpose", ""),
            metadata.get("activity_tags", []),
            against=target_tokens,
        )
        if score > best_score:
            best_score = score
            best_room = dict(room)
    return _first_non_empty(best_room.get("room_id"), default=fallback_room_id)


def _route_story_verb(action_name: str) -> str:
    mapping = {
        "trade": "traded with",
        "negotiate": "negotiated terms with",
        "broker": "brokered a deal with",
        "inspect": "inspected clues with",
        "research": "researched with",
        "scoutreport": "shared a field report with",
        "coordinate": "coordinated with",
        "mediate": "mediated tension with",
        "debate": "debated strategy with",
        "warn": "warned",
        "repair": "repaired assets for",
        "build": "built plans with",
        "chat": "spoke with",
    }
    compact = _slug(action_name).replace("_", "")
    return mapping.get(compact, f"{action_name.lower()}ed with")


def _loop_action_name(loop: dict[str, Any], focus_profile: dict[str, Any], index: int) -> str:
    text = " ".join(
        [
            str(loop.get("label", "")),
            str(loop.get("summary", "")),
            str(loop.get("pressure", "")),
        ]
    ).lower()
    if any(keyword in text for keyword in ("trade", "market", "contract", "supply", "bargain", "exchange")):
        return "Negotiate"
    if any(keyword in text for keyword in ("discover", "route", "explore", "rumor", "archive", "signal")):
        return "ScoutReport" if index % 2 else "Inspect"
    if any(keyword in text for keyword in ("repair", "build", "craft", "forge")):
        return "Repair"
    if any(keyword in text for keyword in ("tension", "rival", "conflict", "suspicion", "distrust")):
        return "Mediate" if focus_profile.get("story") else "Warn"
    return "Coordinate"


def _ordinary_routes(
    *,
    builder_spec: dict[str, Any],
    config: dict[str, Any],
    generated_role_groups: list[dict[str, Any]],
    focus_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    role_id_by_name = {
        str(entry.get("role_name", "")).strip().lower(): str(entry.get("role_id", "")).strip()
        for entry in generated_role_groups
        if str(entry.get("role_name", "")).strip() and str(entry.get("role_id", "")).strip()
    }
    routes: list[dict[str, Any]] = [
        {
            "route_id": "trade_supplies",
            "kind": "item_trade",
            "weight": 12 if focus_profile.get("economy") else 8,
            "story_verb": "traded supplies with",
        }
    ]
    for index, loop in enumerate([dict(entry) for entry in builder_spec.get("gameplay_loops", []) if isinstance(entry, dict)], start=1):
        action_name = _loop_action_name(loop, focus_profile, index)
        route_id = _slug(f"{loop.get('label', 'loop')}_{action_name}_{index}")
        actor_role_ids = [
            role_id_by_name.get(str(name).strip().lower(), "")
            for name in loop.get("roles", [])
        ]
        actor_role_ids = [role_id for role_id in actor_role_ids if role_id]
        route = {
            "route_id": route_id,
            "kind": "custom",
            "action": action_name,
            "status_effect": _slug(f"{loop.get('label', 'loop')}_advanced"),
            "duration_steps": 2,
            "weight": max(8, 16 - index),
            "story_verb": _route_story_verb(action_name),
            "selection_guidance": _first_non_empty(loop.get("summary"), default="Advance the world's core loop."),
        }
        if actor_role_ids:
            route["actor_role_ids"] = actor_role_ids
        requires_item = _item_id_from_hint(" ".join(builder_spec.get("item_themes", [])[:2]), _allowed_item_ids(config))
        if requires_item and action_name in {"Negotiate", "Trade", "Broker", "Inspect", "ScoutReport"}:
            route["requires_actor_item_ids_any"] = [requires_item]
        routes.append(route)
    if focus_profile.get("story") or focus_profile.get("conflict"):
        routes.append(
            {
                "route_id": "ease_world_tension",
                "kind": "custom",
                "action": "Mediate",
                "status_effect": "local_tension_softened",
                "duration_steps": 2,
                "weight": 10,
                "story_verb": "mediated a tense exchange with",
            }
        )
    routes.extend(
        [
            {
                "route_id": "creator_world_chat",
                "kind": "custom",
                "action": "Chat",
                "status_effect": "local_context_shared",
                "duration_steps": 1,
                "weight": 8,
                "story_verb": "spoke with",
            },
            {
                "route_id": "document_world_detail",
                "kind": "image",
                "weight": 3,
                "story_verb": "documented a notable world detail with",
                "image_subject": f"a concrete moment from {builder_spec.get('world_name', 'the world')} involving {', '.join(builder_spec.get('item_themes', [])[:2]) or 'the current world loop'}",
                "image_reason": "world creator draft documentation route",
                "image_prompt_template": "{domain_label}. Create one polished still image of {image_subject}. No visible text, no watermark.",
            },
            {
                "route_id": "move_to_next_thread",
                "kind": "move",
                "weight": 7,
                "story_verb": "moved toward the next thread of activity",
            },
        ]
    )
    return routes


def _cinematic_routes(builder_spec: dict[str, Any], focus_profile: dict[str, Any]) -> list[dict[str, Any]]:
    weight = 100 if focus_profile.get("story") or focus_profile.get("conflict") else 70
    return [
        {
            "route_id": "model_cinematic_interaction",
            "kind": "cinematic",
            "action": "CinematicInteraction",
            "status_effect": "freeform_cinematic_world_moment",
            "duration_steps": 2,
            "weight": weight,
            "model_selected_action": True,
            "story_verb": "performed a freeform cinematic interaction with",
            "selection_guidance": (
                f"Invent a safe, context-specific, visible two-person action that expresses the world pressure in {builder_spec.get('world_name', 'this world')} "
                "and cannot be reduced to a simple routine exchange."
            ),
            "freeform_required": True,
        }
    ]


def _event_function_id(label: str, suffix: str) -> str:
    return _slug(f"{label}_{suffix}")[:60]


def _main_character_policy(main_characters: list[dict[str, Any]]) -> str:
    if not main_characters:
        return "Hook main characters only when the event naturally matches their directive."
    fragments = []
    for character in main_characters[:80]:
        name = _first_non_empty(character.get("display_name"), default="A main character")
        role = _first_non_empty(character.get("role_name"), default="lead")
        activity = _first_non_empty(character.get("activity"), character.get("arc_goal"), default="their directive")
        fragments.append(f"{name} ({role}) should care when the event supports {activity}")
    return "; ".join(fragments) + "."


def _loop_event_function(loop: dict[str, Any], *, main_characters: list[dict[str, Any]], player_entry_points: list[str]) -> dict[str, Any]:
    label = _first_non_empty(loop.get("label"), default="world_loop")
    route_words = ", ".join(_dedupe_texts(loop.get("roles", []), limit=10)) or "relevant local roles"
    room_words = ", ".join(_dedupe_texts(loop.get("rooms", []), limit=10)) or "active rooms"
    player_hook = _first_non_empty(_cycled_value(player_entry_points, 0, ""), default="a clear multiplayer entry point")
    return {
        "function_id": _event_function_id(label, "progressor"),
        "enabled": True,
        "activation_probability": 1.0,
        "max_events": 2,
        "purpose": (
            f"Create or advance event threads for the {label} loop so the world keeps generating concrete next steps in {room_words}."
        ),
        "event_policy": (
            f"Prefer compact progress events that deepen {label}: {loop.get('summary', '')} "
            f"Use {route_words} as likely responders, keep the pressure on {loop.get('pressure', 'unfinished obligations')}, "
            f"and ensure at least one event gives players a readable way into the world such as {player_hook}."
        ).strip(),
        "main_character_policy": _main_character_policy(main_characters),
        "continuity_policy": (
            f"Use titles and status_tags to show next-phase progress for {label}, such as posted, blocked, negotiated, rerouted, verified, escalated, or resolved."
        ),
    }


def _conflict_event_function(
    *,
    builder_spec: dict[str, Any],
    conflict_hooks: list[str],
    main_characters: list[dict[str, Any]],
) -> dict[str, Any]:
    sample_hooks = "; ".join(conflict_hooks[:3]) or "competing priorities, scarce opportunity, and asymmetric information"
    return {
        "function_id": _event_function_id(builder_spec.get("world_id", "world"), "tension_generator"),
        "enabled": True,
        "activation_probability": 0.88,
        "max_events": 2,
        "purpose": (
            "Generate light-to-moderate persistent tension incidents that sharpen negotiation, routing, alliances, and local stakes without overriding agent autonomy."
        ),
        "event_policy": (
            f"Use the compiled conflict hooks as style anchors only when they fit current world memory: {sample_hooks}. "
            "Prefer incidents that create follow-up routes, targetable bottlenecks, or contested interpretations instead of one-off flavor."
        ),
        "main_character_policy": _main_character_policy(main_characters),
        "continuity_policy": (
            "Let tension incidents branch or cool down over multiple rounds through status_tags such as delayed, inspected, contested, exposed, rerouted, softened, or settled."
        ),
    }


def _player_entry_event_function(
    *,
    builder_spec: dict[str, Any],
    player_entry_points: list[str],
    main_characters: list[dict[str, Any]],
) -> dict[str, Any]:
    entry_lines = "; ".join(player_entry_points[:3]) or "players should be able to enter through an understandable local problem"
    return {
        "function_id": _event_function_id(builder_spec.get("world_id", "world"), "player_entry_generator"),
        "enabled": True,
        "activation_probability": 0.72,
        "max_events": 1,
        "purpose": "Generate newcomer-readable incidents that expose what the world is about and give human players an immediate way to participate.",
        "event_policy": (
            f"Prefer events that make the world legible from the ground level: {entry_lines}. "
            "A good event should tell a player where to go, who to ask, or which pressure is already live."
        ),
        "main_character_policy": _main_character_policy(main_characters),
        "continuity_policy": (
            "Entry incidents should either resolve into a larger loop or hand off to an existing conflict, rumor, or coordination thread within 1-3 rounds."
        ),
    }


def _compiled_extra_world_functions(
    *,
    builder_spec: dict[str, Any],
    gameplay_loops: list[dict[str, Any]],
    conflict_hooks: list[str],
    player_entry_points: list[str],
    main_characters: list[dict[str, Any]],
    focus_profile: dict[str, Any],
) -> dict[str, Any]:
    functions = [
        _loop_event_function(loop, main_characters=main_characters, player_entry_points=player_entry_points)
        for loop in gameplay_loops[:2]
    ]
    if conflict_hooks or focus_profile.get("conflict") or focus_profile.get("story"):
        functions.append(
            _conflict_event_function(
                builder_spec=builder_spec,
                conflict_hooks=conflict_hooks,
                main_characters=main_characters,
            )
        )
    functions.append(
        _player_entry_event_function(
            builder_spec=builder_spec,
            player_entry_points=player_entry_points,
            main_characters=main_characters,
        )
    )
    return {
        "enabled": True,
        "stage": "extra_world_functions",
        "activation_probability": 1.0,
        "max_events_per_function": 2,
        "max_events_per_round": 5 if focus_profile.get("story") or focus_profile.get("conflict") else 4,
        "functions": functions[:4],
    }


def _build_world_config_from_spec(
    package_root: Path,
    builder_spec: dict[str, Any],
    request: dict[str, Any],
    *,
    pipeline_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from macro_ui.build_macro_ui import generalized_world_config_template

    pipeline_artifacts = pipeline_artifacts or build_world_pipeline(builder_spec, request)
    structured_world = dict(pipeline_artifacts.get("structured_world_definition", {}))
    planner = dict(pipeline_artifacts.get("planner", {}))
    rooms_spec_artifact = dict(pipeline_artifacts.get("rooms_spec", {}))
    agents_spec_artifact = dict(pipeline_artifacts.get("agents_spec", {}))
    asset_prompt_kits = dict(structured_world.get("asset_prompt_kits", {})) if isinstance(structured_world.get("asset_prompt_kits", {}), dict) else {}
    world_meta = dict(structured_world.get("world_definition", {})) if isinstance(structured_world.get("world_definition", {}), dict) else {}
    room_definitions = [dict(entry) for entry in rooms_spec_artifact.get("room_definitions", []) if isinstance(entry, dict)]
    role_definitions = [dict(entry) for entry in agents_spec_artifact.get("role_definitions", []) if isinstance(entry, dict)]
    specialist_main_characters = [dict(entry) for entry in agents_spec_artifact.get("main_characters", []) if isinstance(entry, dict)]

    config = generalized_world_config_template(package_root)
    world_slug = _slug(str(builder_spec["world_id"]))
    scenario_meta = config.setdefault("scenario_meta", {})
    runner = config.setdefault("runner", {})
    scenario_meta["world_id"] = str(builder_spec["world_id"])
    scenario_meta["world_name"] = str(builder_spec["world_name"])
    scenario_meta["description"] = _first_non_empty(
        request.get("brief"),
        builder_spec.get("premise"),
        default=f"A persistent {builder_spec.get('genre', 'fictional')} world.",
    )
    scenario_meta["simulation_objective"] = str(builder_spec.get("simulation_objective", ""))
    runner["run_name"] = world_slug
    runner["world_label"] = str(builder_spec["world_name"])
    runner["domain_label"] = str(dict(world_meta.get("policy_refs", {})).get("domain_label") or f"{builder_spec.get('genre', 'fictional world')} · {builder_spec.get('premise', '')}".strip(" ·"))
    runner["agent_id_prefix"] = str(dict(structured_world.get("generation_policies", {})).get("agent_generation", {}).get("agent_id_prefix", "agent"))
    if structured_world:
        config["world_definition"] = structured_world
    config = sync_world_definition_into_config(config)

    scenario_meta = config.setdefault("scenario_meta", {})
    runtime = config.setdefault("runtime", {})
    runner = config.setdefault("runner", {})
    output = config.setdefault("output", {})
    human_interaction = config.setdefault("human_interaction", {})
    world_rules = config.setdefault("world_rules", {})
    image_generation = config.setdefault("image_generation", {})
    longlive = config.setdefault("longlive", {})
    report = config.setdefault("report", {})
    space = config.setdefault("space", {})
    actions = config.setdefault("actions", {})
    world_progress = config.setdefault("world_progress", {})
    economy = config.setdefault("economy", {})
    agent_generation = config.setdefault("agent_generation", {})
    extra_world_functions = config.setdefault("extra_world_functions", {})
    pixel_frontend = config.setdefault("pixel_asset_pipeline", {}).setdefault("frontend", {})
    base_rooms = [dict(room) for room in space.get("rooms", []) if isinstance(room, dict)]
    main_characters = specialist_main_characters or [dict(entry) for entry in builder_spec.get("main_characters", []) if isinstance(entry, dict)]
    gameplay_loops = [dict(entry) for entry in builder_spec.get("gameplay_loops", []) if isinstance(entry, dict)]
    player_entry_points = _dedupe_texts(builder_spec.get("player_entry_points", []), limit=4)
    conflict_hooks = _dedupe_texts(builder_spec.get("conflict_hooks", []), limit=4)
    from .critique_loop import _focus_profile
    focus_profile = _focus_profile(request, builder_spec)
    total_regular_agents = sum(max(1, int(role.get("count", 1) or 1)) for role in role_definitions)
    if total_regular_agents <= 0 and len(main_characters) < 8:
        total_regular_agents = max(8, int(builder_spec.get("agent_count_target", 40))) - len(main_characters)
        total_regular_agents = max(0, total_regular_agents)
    
    # If the user strictly wanted an agent_count_target that exactly matches the number of generated main characters, we assume no generic NPCs.
    if int(builder_spec.get("agent_count_target", 0)) == len(main_characters):
        total_regular_agents = 0

    scenario_meta["player_entry_points"] = player_entry_points
    scenario_meta["creator_conflict_hooks"] = conflict_hooks
    runner["creator_focus_tags"] = [
        label
        for label, enabled in (
            ("economy", focus_profile.get("economy")),
            ("exploration", focus_profile.get("exploration")),
            ("story", focus_profile.get("story")),
            ("conflict", focus_profile.get("conflict")),
            ("craft", focus_profile.get("craft")),
        )
        if enabled
    ]
    runtime["agent_count"] = total_regular_agents + len(main_characters)
    runtime["rounds"] = 32 if focus_profile.get("story") else 26
    if runtime["agent_count"] <= 24:
        runtime["activation_probability"] = 0.34
    elif runtime["agent_count"] <= 48:
        runtime["activation_probability"] = 0.28
    else:
        runtime["activation_probability"] = 0.22
    runtime["seed"] = int(request.get("seed") or runtime.get("seed", 42627) or 42627)
    output["default_output_dir"] = f"output/world_creator_{world_slug}"
    output["story_filename"] = f"{world_slug}_story.json"
    agent_generation["agent_id_prefix"] = str(runner.get("agent_id_prefix", "agent"))

    updated_rooms: list[dict[str, Any]] = []
    source_room_defs = room_definitions or [dict(entry) for entry in builder_spec.get("rooms", []) if isinstance(entry, dict)]
    
    # Pre-resolve dimensions from templates before packing
    base_rooms = [dict(room) for room in space.get("rooms", []) if isinstance(room, dict)]
    for index, room_spec in enumerate(source_room_defs):
        template_room = dict(_cycled_value(base_rooms, index, base_rooms[0] if base_rooms else {}))
        room_spec["width_tiles"] = max(1, int(room_spec.get("width_tiles") or template_room.get("width_tiles") or 10))
        room_spec["height_tiles"] = max(1, int(room_spec.get("height_tiles") or template_room.get("height_tiles") or 10))
    
    # 2D Grid coordinates layout calculation using procedural rectangular packing
    from .nodes.layout import pack_rooms
    packed_layout = pack_rooms(source_room_defs)
    packed_rooms = packed_layout.get("rooms", [])
    space["width_tiles"] = packed_layout.get("width_tiles", 100)
    space["height_tiles"] = packed_layout.get("height_tiles", 100)
    space["thin_walls"] = packed_layout.get("thin_walls", [])
    space["outer_walls"] = packed_layout.get("outer_walls", [])
    space["wall_color_theme"] = str(builder_spec.get("wall_color_theme", "dark_brick"))
    space["outdoor_terrain"] = str(builder_spec.get("outdoor_terrain", "dirt"))
    
    # We must use packed_rooms because it contains x_pos, y_pos
    source_room_defs = packed_rooms
    
    for index, room_spec in enumerate(source_room_defs):
        template_room = dict(_cycled_value(base_rooms, index, base_rooms[0] if base_rooms else {}))
        room_name = _first_non_empty(room_spec.get("name"), template_room.get("name"), default=f"Room {index + 1}")
        room_id = _first_non_empty(room_spec.get("room_id"), default=_slug(f"room_{index + 1:02d}_{room_name}")[:128])
        visual = dict(template_room.get("visual", {}))
        visual["biome"] = _first_non_empty(room_spec.get("biome"), visual.get("biome"), default="interior")
        visual["decor_tags"] = _dedupe_texts(room_spec.get("decor_tags", []), limit=30)
        visual["ambient_palette"] = _first_non_empty(room_spec.get("ambient_palette"), visual.get("ambient_palette"), default="warm_lantern")
        visual["floor_tile"] = _first_non_empty(room_spec.get("floor_tile"), visual.get("floor_tile"), default="stone_checker")
        visual["wall_tile"] = _first_non_empty(room_spec.get("wall_tile"), visual.get("wall_tile"), default="plain_wall")
        
        # Propagate custom material settings
        spec_details = dict(room_spec.get("visual_details", {}))
        visual["showcase_shelf"] = bool(spec_details.get("showcase_shelf", False))
        visual["showcase_item_colors"] = list(spec_details.get("showcase_item_colors", []))
        visual["reflection_glares"] = bool(spec_details.get("reflection_glares", False))

        metadata = dict(template_room.get("metadata", {})) if isinstance(template_room.get("metadata", {}), dict) else {}
        metadata["purpose"] = _first_non_empty(room_spec.get("purpose"), metadata.get("purpose"), default="support world interaction")
        metadata["activity_tags"] = _dedupe_texts(room_spec.get("activity_tags", []), limit=30)
        metadata["player_entry_hook"] = _first_non_empty(
            _cycled_value(room_spec.get("entry_hints", []), 0, ""),
            _cycled_value(player_entry_points, index, player_entry_points[0] if player_entry_points else ""),
        )
        metadata["room_archetype"] = _first_non_empty(room_spec.get("archetype"), metadata.get("room_archetype"), default="commons")
        metadata["layout_signal"] = " | ".join(
            _dedupe_texts(
                [room_name, metadata["purpose"], visual["biome"]] + metadata["activity_tags"] + visual["decor_tags"],
                limit=30,
            )
        )
        
        room_width = max(1, int(room_spec.get("width_tiles", 10)))
        room_height = max(1, int(room_spec.get("height_tiles", 10)))
        
        room_x = int(room_spec.get("x_pos", 0))
        room_y = int(room_spec.get("y_pos", 0))
        room_flux_prompt = room_spec.get("flux_floor_prompt", "")
        room_scene_prompt = room_spec.get("room_scene_prompt", "") or room_flux_prompt

        updated_rooms.append(
            {
                **template_room,
                "room_id": room_id,
                "name": room_name,
                "visual": visual,
                "metadata": metadata,
                "doorways": [],
                "x": room_x,
                "y": room_y,
                "z": 0,
                "footprint_tiles": [],
                "spawn_points": [],
                "width_tiles": room_width,
                "height_tiles": room_height,
                "flux_floor_prompt": room_flux_prompt,
                "room_scene_prompt": room_scene_prompt,
            }
        )

    for index, room in enumerate(updated_rooms):
        room["doorways"] = []
    space["rooms"] = updated_rooms
    map_visual = space.setdefault("map_visual", {})
    map_visual["theme_label"] = str(builder_spec.get("visual_style", "") or world_meta.get("visual_direction", ""))
    map_visual.setdefault("tileset", {})["key"] = f"{world_slug}_pixel_tiles"
    hub_room_id = _choose_room_id(
        updated_rooms,
        "hub commons central market forum coordination",
        builder_spec.get("premise", ""),
        fallback_room_id=_first_non_empty(updated_rooms[0].get("room_id") if updated_rooms else "", default="room_01"),
    )
    camera = map_visual.setdefault("camera", {})
    camera["start_room_id"] = hub_room_id
    human_interaction["default_room_id"] = hub_room_id

    base_role_groups = [dict(entry) for entry in config.get("agent_generation", {}).get("role_groups", []) if isinstance(entry, dict)]
    generated_role_groups: list[dict[str, Any]] = []
    
    # Empty role groups entirely if doing pure boutique protagonist generation
    if int(builder_spec.get("agent_count_target", 0)) == len(specialist_main_characters):
        base_role_groups = []
        role_definitions = []
    for index, spec_group in enumerate(role_definitions):
        base_group = dict(_cycled_value(base_role_groups, index, base_role_groups[0] if base_role_groups else {}))
        role_name = _first_non_empty(spec_group.get("role_name"), base_group.get("role_name"), default=f"Role Group {index + 1}")
        home_room_id = _choose_room_id(
            updated_rooms,
            spec_group.get("home_room_policy", ""),
            role_name,
            spec_group.get("activity", ""),
            fallback_room_id=hub_room_id,
        )
        loop = dict(_cycled_value(gameplay_loops, index, gameplay_loops[0] if gameplay_loops else {}))
        role_inventory = _inventory_specs_from_item_ids([str(item) for item in spec_group.get("starting_item_ids", []) if str(item).strip()])
        generated_role_groups.append(
            {
                **base_group,
                "role_id": _slug(_first_non_empty(spec_group.get("role_id"), role_name)),
                "role_name": role_name,
                "count": max(1, int(spec_group.get("count", 1) or 1)),
                "core_values": [str(item).strip() for item in spec_group.get("core_values", []) if str(item).strip()] or base_group.get("core_values", []),
                "home_room_id": home_room_id,
                "agent_number_start": sum(int(entry.get("count", 0) or 0) for entry in generated_role_groups) + 1,
                "activity_directive": (
                    f"Prioritize {spec_group.get('activity', 'meaningful social work')} in and around {home_room_id}, "
                    f"using {loop.get('label', 'the world loop')} to create follow-up interactions."
                ),
                "appearance_template": _first_non_empty(
                    spec_group.get("appearance_policy"),
                    base_group.get("appearance_template"),
                    default=(
                        f"A {{gender_presentation}} {role_name.lower()} in {builder_spec.get('genre', 'the world')}, "
                        f"showing {spec_group.get('activity', 'their role')} with a readable silhouette and {builder_spec.get('visual_style', 'pixel-world styling')}."
                    ),
                ),
                "inventory": role_inventory or list(base_group.get("inventory", [])),
                "property_library": [dict(item) for item in spec_group.get("property_templates", []) if isinstance(item, dict)],
                "knowledge_assets": [dict(item) for item in spec_group.get("knowledge_templates", []) if isinstance(item, dict)],
            }
        )
    agent_generation["role_groups"] = generated_role_groups

    base_main_characters = [dict(entry) for entry in config.get("main_characters", []) if isinstance(entry, dict)]
    base_main_ids = [str(entry.get("agent_id", "")).strip() for entry in base_main_characters if str(entry.get("agent_id", "")).strip()]
    generated_main_characters: list[dict[str, Any]] = []
    for index, character in enumerate(specialist_main_characters):
        base_character = dict(_cycled_value(base_main_characters, index, base_main_characters[0] if base_main_characters else {}))
        home_room_id = _choose_room_id(
            updated_rooms,
            character.get("home_base", ""),
            character.get("role_name", ""),
            character.get("activity", ""),
            fallback_room_id=hub_room_id,
        )
        loop = dict(_cycled_value(gameplay_loops, index, gameplay_loops[0] if gameplay_loops else {}))
        generated_main_characters.append(
            {
                **base_character,
                "enabled": True,
                "agent_id": _first_non_empty(character.get("agent_id"), default=f"{world_slug}_main_{index + 1:02d}")[:128],
                "display_name": _first_non_empty(character.get("display_name"), base_character.get("display_name"), default=f"Main Character {index + 1}"),
                "role_id": _slug(_first_non_empty(character.get("role_name"), base_character.get("role_name"), default=f"main_role_{index + 1}")),
                "role_name": _first_non_empty(character.get("role_name"), base_character.get("role_name"), default=f"Lead {index + 1}"),
                "archetype": _first_non_empty(character.get("arc_goal"), character.get("role_name"), base_character.get("archetype"), default=f"Lead of {loop.get('label', 'the world')}"),
                "home_room_id": home_room_id,
                "agent_number": total_regular_agents + index + 1,
                "appearance_prompt": (
                    f"A lead character from {builder_spec.get('world_name', 'the world')} with the role of {character.get('role_name', 'protagonist')}, "
                    f"visually grounded in {builder_spec.get('visual_style', 'readable pixel-world style')}."
                ),
                "activity_directive": (
                    f"{_first_non_empty(character.get('activity'), default='Drive the world forward.')}"
                    f" Use {loop.get('label', 'the main world loop')} to push visible consequences and keep the world responsive to players."
                ),
                "private_notes": _first_non_empty(character.get("activity"), base_character.get("private_notes"), default="A main character for the world creator draft."),
                "inventory": [
                    {
                        "item_id": _slug(str(item.get("name", item.get("item_id", "")))),
                        "name": str(item.get("name", item.get("item_id", ""))),
                        "description": str(item.get("description", "")),
                        "quantity": int(item.get("quantity", 1)),
                        "metadata": {
                            "name": str(item.get("name", item.get("item_id", ""))),
                            "description": str(item.get("description", ""))
                        }
                    }
                    for item in character.get("inventory", [])
                    if isinstance(item, dict) and (item.get("name") or item.get("item_id"))
                ] or _inventory_specs_from_item_ids([str(item) for item in character.get("starting_item_ids", []) if str(item).strip()]),
                "property_library": [dict(item) for item in character.get("property_templates", []) if isinstance(item, dict)],
                "knowledge_assets": [dict(item) for item in character.get("knowledge_templates", []) if isinstance(item, dict)],
                "always_activate": True,
            }
        )
    config["main_characters"] = generated_main_characters
    if generated_main_characters:
        camera["follow_main_character"] = str(generated_main_characters[0].get("agent_id", ""))
    main_replacements = {
        old_id: str(new_entry.get("agent_id", "")).strip()
        for old_id, new_entry in zip(base_main_ids, generated_main_characters)
        if old_id and str(new_entry.get("agent_id", "")).strip()
    }
    replacement_map = dict(main_replacements)
    pixel_frontend = _deep_replace_exact_strings(pixel_frontend, replacement_map)
    pixel_frontend["asset_set_manifest_path"] = "./assets/generated/world_asset_sets/current_world_pixel_set.json"
    if generated_main_characters:
        pixel_frontend.setdefault("pov_local_modules", {})["protagonist_agent_id"] = str(generated_main_characters[0].get("agent_id", ""))
    config["pixel_asset_pipeline"]["frontend"] = pixel_frontend

    social_rules = [str(rule).strip() for rule in builder_spec.get("social_rules", []) if str(rule).strip()]
    world_rules["social_rules"] = _dedupe_texts(
        social_rules
        + [
            "Generated gameplay loops should create follow-up choices instead of dead ends.",
            "Player entry points should remain understandable through local conversation, movement, and inspection.",
        ]
        + [f"Conflict hook: {hook}" for hook in conflict_hooks],
        limit=12,
    )
    world_rules.setdefault("custom_action_rules", {})["default_duration_steps"] = 2
    world_rules.setdefault("image_rules", {})["enabled"] = True
    world_rules.setdefault("image_rules", {})["allowed_operations"] = ["create"]
    if focus_profile.get("story") or focus_profile.get("conflict"):
        world_rules["image_rules"]["allowed_operations"] = ["create", "edit"]

    allowed_custom_actions = _dedupe_texts(
        builder_spec.get("custom_actions", [])
        + ["Chat", "Inspect", "Coordinate", "Trade", "Move", "CinematicInteraction"],
        limit=16,
    )
    if "CinematicInteraction" not in allowed_custom_actions:
        allowed_custom_actions.append("CinematicInteraction")
    actions["allowed_custom_actions"] = allowed_custom_actions
    actions["ordinary_routes"] = _ordinary_routes(
        builder_spec=builder_spec,
        config=config,
        generated_role_groups=generated_role_groups,
        focus_profile=focus_profile,
    )
    actions["cinematic_routes"] = _cinematic_routes(builder_spec, focus_profile)
    actions["routing_policy"] = {
        "ordinary_first": True,
        "world_memory_use": (
            "Use recent_global_world_events, relationship changes, and room context as active evidence. "
            "Prefer advancing an existing loop over resetting to generic chatter."
        ),
        "main_character_use": (
            "Main characters should visibly convert local pressure into concrete next steps without bypassing normal room and target legality."
        ),
        "repeat_avoidance": (
            "Avoid repeating the same abstract exchange. Each repeated interaction should escalate, clarify, trade, inspect, or resolve something."
        ),
    }
    actions["target_selection"] = {
        "enabled": True,
        "prefer_same_room": True,
        "max_range_steps": int(space.get("targeting", {}).get("max_range_steps", 10) or 10),
        "same_room_weight": 1.45,
        "other_room_weight": 1.08,
        "distance_penalty_per_step": 0.05,
        "recent_interaction_bonus": 0.55,
        "repeat_interaction_soft_cap": 4,
        "cohort_weight": 1.3,
        "shared_task_weight": 1.25,
    }

    world_progress["enabled"] = True
    world_progress["source"] = "world creator gameplay loops, status effects, and localized visual state"
    world_progress["gameplay_loops"] = gameplay_loops
    world_progress["player_entry_points"] = player_entry_points
    world_progress["routing_instruction"] = (
        f"Treat {', '.join(loop.get('label', '') for loop in gameplay_loops[:3] if loop.get('label')) or 'the compiled world loops'} "
        "as persistent soft objectives. Route agents toward advancing, contesting, or clarifying them when compatible with role, room, and target legality."
    )
    world_progress["status_follow_up_examples"] = [
        f"{loop.get('label', 'A loop')} should turn a first interaction into a follow-up obligation, clue, or decision."
        for loop in gameplay_loops[:3]
    ]
    extra_world_functions.update(
        _compiled_extra_world_functions(
            builder_spec=builder_spec,
            gameplay_loops=gameplay_loops,
            conflict_hooks=conflict_hooks,
            player_entry_points=player_entry_points,
            main_characters=main_characters,
            focus_profile=focus_profile,
        )
    )

    longlive["enabled"] = True
    longlive["max_videos_per_round"] = max(2, min(4, len(generated_main_characters) + (1 if focus_profile.get("story") else 0)))
    longlive["candidate_probability"] = 0.3 if focus_profile.get("story") or focus_profile.get("conflict") else 0.18
    longlive["segment_seconds"] = 4
    longlive["visual_style"] = str(builder_spec.get("visual_style", ""))
    longlive["force_cinematic_for_main_characters"] = True
    longlive["force_cinematic_agent_ids"] = [str(entry.get("agent_id", "")).strip() for entry in generated_main_characters if str(entry.get("agent_id", "")).strip()]
    image_generation["enabled"] = True
    image_generation["generate_character_portraits"] = True
    image_generation["item_image_mode"] = "important_only"
    image_generation["conditions"] = [
        "Still images should document meaningful world details rather than generic filler scenes.",
        "When a route produces an image, tie it to the current world loop or recent interaction context.",
    ]
    prompt_image_generation = dict(asset_prompt_kits.get("image_generation", {}))
    if str(prompt_image_generation.get("prompt_policy", "")).strip():
        image_generation["prompt_policy"] = str(prompt_image_generation.get("prompt_policy", "")).strip()
    if str(prompt_image_generation.get("default_prompt_template", "")).strip():
        image_generation["default_prompt_template"] = str(prompt_image_generation.get("default_prompt_template", "")).strip()
    economy["starting_wallet_minor"] = dict(world_meta.get("starting_wallet_minor", economy.get("starting_wallet_minor", {"min": 2400, "max": 11000})))
    economy.pop("starting_gold", None)
    report["title"] = f"{builder_spec['world_name']} Story Report"
    report["tex_filename"] = f"{world_slug}_story_report.tex"
    report["pdf_filename"] = f"{world_slug}_story_report.pdf"
    report["focus"] = (
        f"World creator draft for {builder_spec['world_name']} with loops: "
        + ", ".join(loop.get("label", "") for loop in gameplay_loops[:3] if loop.get("label"))
    )
    config["world_definition"] = structured_world
    return sync_world_definition_into_config(config)


def _structured_summary(config: dict[str, Any]) -> dict[str, Any]:
    ordinary_routes = [entry for entry in config.get("actions", {}).get("ordinary_routes", []) if isinstance(entry, dict)]
    cinematic_routes = [entry for entry in config.get("actions", {}).get("cinematic_routes", []) if isinstance(entry, dict)]
    role_groups = [entry for entry in config.get("agent_generation", {}).get("role_groups", []) if isinstance(entry, dict)]
    custom_actions = [entry for entry in config.get("actions", {}).get("allowed_custom_actions", []) if str(entry).strip()]
    gameplay_loops = [entry for entry in config.get("world_progress", {}).get("gameplay_loops", []) if isinstance(entry, dict)]
    player_entry_points = [entry for entry in config.get("world_progress", {}).get("player_entry_points", []) if str(entry).strip()]
    summary = WorldBuilderStructuredSummarySpec(
        room_count=len([entry for entry in config.get("space", {}).get("rooms", []) if isinstance(entry, dict)]),
        agent_count=int(config.get("runtime", {}).get("agent_count", 0) or 0),
        main_character_count=len([entry for entry in config.get("main_characters", []) if isinstance(entry, dict)]),
        role_group_count=len(role_groups),
        ordinary_route_count=len(ordinary_routes),
        cinematic_route_count=len(cinematic_routes),
        custom_action_count=len(custom_actions),
        gameplay_loop_count=len(gameplay_loops),
        player_entry_point_count=len(player_entry_points),
        economy_focus=_first_non_empty(config.get("runner", {}).get("domain_label"), default=""),
        exploration_focus=_first_non_empty(config.get("scenario_meta", {}).get("simulation_objective"), default=""),
        longlive_enabled=bool(config.get("longlive", {}).get("enabled", True)),
        image_generation_enabled=bool(config.get("image_generation", {}).get("enabled", True)),
        item_image_mode=str(config.get("image_generation", {}).get("item_image_mode", "")),
    )
    return summary.model_dump()


def _compiled_preview_from_config(config: dict[str, Any]) -> dict[str, Any]:
    gameplay_loops = [
        {
            "label": str(entry.get("label", "")),
            "summary": str(entry.get("summary", "")),
            "roles": [str(item) for item in entry.get("roles", []) if str(item).strip()][:4],
            "rooms": [str(item) for item in entry.get("rooms", []) if str(item).strip()][:4],
            "pressure": str(entry.get("pressure", "")),
        }
        for entry in config.get("world_progress", {}).get("gameplay_loops", [])
        if isinstance(entry, dict)
    ][:6]
    player_entry_points = [
        str(entry)
        for entry in config.get("world_progress", {}).get("player_entry_points", [])
        if str(entry).strip()
    ][:6]
    conflict_hooks = [
        str(entry)
        for entry in config.get("scenario_meta", {}).get("creator_conflict_hooks", [])
        if str(entry).strip()
    ][:6]
    event_functions = [
        {
            "function_id": str(entry.get("function_id", "")),
            "purpose": str(entry.get("purpose", "")),
            "event_policy": str(entry.get("event_policy", "")),
            "continuity_policy": str(entry.get("continuity_policy", "")),
            "activation_probability": float(entry.get("activation_probability", 0.0) or 0.0),
            "max_events": int(entry.get("max_events", 0) or 0),
        }
        for entry in config.get("extra_world_functions", {}).get("functions", [])
        if isinstance(entry, dict)
    ][:6]
    focus_tags = [
        str(entry)
        for entry in config.get("runner", {}).get("creator_focus_tags", [])
        if str(entry).strip()
    ]
    return {
        "gameplay_loops": gameplay_loops,
        "player_entry_points": player_entry_points,
        "conflict_hooks": conflict_hooks,
        "event_functions": event_functions,
        "focus_tags": focus_tags,
    }

