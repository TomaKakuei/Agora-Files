from __future__ import annotations
import argparse
import base64
import hashlib
import json
import math
import mimetypes
import os
import random
import shutil
import subprocess
import sys
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import asyncio
import copy
import traceback
from collections import Counter, deque
from datetime import datetime
from pathlib import Path
from typing import Any
from PIL import Image
from ..adjudicator_schemas import (
    AgentIntentBatchSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    InventoryItemSpec,
    RelationshipVectorSpec,
)
from ..flex_api import first_json_value_from_text
from ..foundation_schemas import GridPosition
from ..package_db import is_world_package_db, materialize_world_package
from ..jsonc_utils import dump_json, load_jsonc_path
from ..universal_adjudicator import core as adjudicator
from ..extra_world_functions import (
    extra_world_functions_config,
    recent_global_world_events,
    run_extra_world_functions,
)
from ..world_definition import default_wallet_payload
from ..world_definition import legacy_currency_inventory_entry
from ..world_definition import sync_world_definition_into_config
from ..agent_factory import (
    SafeDict,
    _format,
    _room_spawn_cells,
    _spawn_coordinate_for_room,
    _runner_config,
    _world_label,
    _domain_label,
    _story_filename,
    _run_name,
    _agent_id_prefix,
    _image_generation_config,
    _inventory_item,
    _currency_item,
    _starting_wallet_range,
    _role_sequence,
    _room_for_agent,
    _room_by_id,
    _main_character_specs,
    _main_character_ids,
    _force_cinematic_agent_ids,
    _main_character_payload,
    _variation_token,
    _display_name_for_agent,
    _build_agent_payloads,
    _vertex_agent_profile_payloads,
    _inventory_generation_config,
    _merge_inventory_items,
    _vertex_initial_inventory_payloads,
)
from ..vertex_json_client import VertexJsonClient
from ..vertex_image_client import VertexSDKImageClient

from .utils import *
from .config import *
from .grid import *
from .agents_state import *




SCRIPT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_ENV = "AGORA_SIM_CONFIG"
DEFAULT_PY_BIN = Path(sys.executable)



def _recording_context(actor: AgentRuntimeProfileSpec, target: AgentRuntimeProfileSpec) -> dict[str, Any]:
    actor_main = _is_main_character_agent(actor)
    target_main = _is_main_character_agent(target)
    required_ids = [
        agent_id
        for agent_id, required in (
            (actor.agent_id, actor_main),
            (target.agent_id, target_main),
        )
        if required
    ]
    return {
        "actor_is_main_character": actor_main,
        "target_is_main_character": target_main,
        "requires_visible_round_record": bool(required_ids),
        "required_agent_ids": required_ids,
        "policy": (
            "Main characters need a visible round record. Shared actions may extend beyond the JSON route library "
            "when the route stays legal and the visual behavior remains grounded."
        ),
    }


def _room_prompt_context(config: dict[str, Any], room_id: str) -> dict[str, Any]:
    if not str(room_id).strip():
        return {}
    room = _room_by_id(config, room_id)
    payload: dict[str, Any] = {
        "room_id": str(room.get("room_id", "")),
        "name": _limit_text(room.get("name", room.get("room_id", "")), 80),
    }
    for key in ("description", "story_use", "purpose", "mood", "visual_prompt", "image_prompt", "biome"):
        value = _limit_text(room.get(key, ""), 180)
        if value:
            payload[key] = value
    tags = room.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    if isinstance(tags, list):
        payload["tags"] = [str(item).strip()[:48] for item in tags if str(item).strip()][:6]
    
    decor_tags = room.get("decor_tags", [])
    if isinstance(decor_tags, list):
        payload["decor_tags"] = [str(item).strip()[:48] for item in decor_tags if str(item).strip()][:6]
        
    activity_tags = room.get("activity_tags", [])
    if isinstance(activity_tags, list):
        payload["activity_tags"] = [str(item).strip()[:48] for item in activity_tags if str(item).strip()][:6]
    capacity = room.get("capacity")
    if capacity is not None:
        payload["capacity"] = max(0, _safe_int(capacity, 0))
    return payload


def _visible_prop_context(actor: AgentRuntimeProfileSpec, target: AgentRuntimeProfileSpec, config: dict[str, Any]) -> list[str]:
    props: list[str] = []
    for agent in (actor, target):
        for item in _inventory_prompt_summary(agent, config, limit=3):
            label = _limit_text(item.get("description", "") or item.get("item_id", ""), 72)
            if label and label not in props:
                props.append(label)
        for item in _property_prompt_summary(agent, limit=2):
            label = _limit_text(item.get("asset_name", "") or item.get("story_use", ""), 72)
            if label and label not in props:
                props.append(label)
        for artifact in _initialize_runtime_memory(agent, config).get("visual_artifacts", [])[:2]:
            if not isinstance(artifact, dict):
                continue
            label = _limit_text(artifact.get("artifact_label", "") or artifact.get("item_id", ""), 72)
            if label and label not in props:
                props.append(label)
    return props[:8]


def _recent_joint_history(
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    config: dict[str, Any],
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    entries = []
    for item in _initialize_runtime_memory(actor, config).get("recent_rounds", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("other_agent_id", "")).strip() == target.agent_id:
            entries.append(dict(item))
    return entries[-limit:]


def _compact_agent_prompt_payload(
    agent: AgentRuntimeProfileSpec,
    state: AgentStateBundleSpec,
    config: dict[str, Any],
) -> dict[str, Any]:
    memory = _initialize_runtime_memory(agent, config)
    status_payload = [
        {
            "effect": item.effect,
            "duration_steps": int(item.duration_steps),
            "description": _limit_text(getattr(item, "description", "") or item.source, 120),
        }
        for item in agent.status_effects[-4:]
    ]
    public_state = dict(agent.public_state or {})
    return {
        "agent_id": agent.agent_id,
        "display_name": agent.display_name,
        "role_name": public_state.get("role_name", ""),
        "role_id": public_state.get("role_id", ""),
        "main_character": bool(public_state.get("main_character", False)),
        "main_character_archetype": _limit_text(public_state.get("main_character_archetype", ""), 96),
        "room_id": agent.room_id,
        "coordinates": agent.coordinates.model_dump(),
        "activity_directive": _limit_text(public_state.get("activity_directive", ""), 160),
        "appearance_prompt": _limit_text(agent.appearance_prompt, 180),
        "core_values": [str(item) for item in agent.core_values[:4]],
        "personality_tags": [str(item) for item in public_state.get("personality_tags", []) if str(item).strip()][:4],
        "status_effects": status_payload,
        "inventory_summary": _inventory_prompt_summary(agent, config),
        "property_summary": _property_prompt_summary(agent, limit=_memory_limit(config, "max_prompt_property_items", 3)),
        "knowledge_summary": _knowledge_prompt_summary(agent, limit=_memory_limit(config, "max_prompt_knowledge_items", 3)),
        "memory": {
            "mainline_summary": _limit_text(memory.get("mainline_summary", ""), 220),
            "current_focus": _limit_text(memory.get("current_focus", ""), 180),
            "active_long_tasks": [dict(item) for item in memory.get("active_long_tasks", [])[: _memory_limit(config, "max_active_long_tasks", 5)]],
            "recent_rounds": [dict(item) for item in memory.get("recent_rounds", [])[-_memory_limit(config, "keep_recent_rounds", 10):]],
            "cohort_ids": [str(item) for item in memory.get("cohort_ids", []) if str(item).strip()][: _memory_limit(config, "max_cohort_ids", 4)],
            "location_awareness": dict(memory.get("location_awareness", {})) if isinstance(memory.get("location_awareness", {}), dict) else {},
            "visual_artifacts": [
                {
                    "kind": str(item.get("kind", "")),
                    "artifact_label": _limit_text(item.get("artifact_label", ""), 96),
                    "item_id": str(item.get("item_id", ""))[:80],
                }
                for item in memory.get("visual_artifacts", [])[: _memory_limit(config, "max_visual_artifacts", 4)]
                if isinstance(item, dict)
            ],
            "textual_artifacts": [
                {
                    "kind": str(item.get("kind", "")),
                    "artifact_label": _limit_text(item.get("artifact_label", ""), 96),
                    "item_id": str(item.get("item_id", ""))[:80],
                    "description": _limit_text(item.get("description", ""), 220),
                }
                for item in memory.get("textual_artifacts", [])[: _memory_limit(config, "max_visual_artifacts", 4)]
                if isinstance(item, dict)
            ],
            "artist_feedback_follow_up": (
                dict(memory.get("artist_feedback_follow_up", {}))
                if isinstance(memory.get("artist_feedback_follow_up", {}), dict)
                else {}
            ),
            "archived_round_count": _safe_int(memory.get("archived_round_count", 0), 0),
        },
        "relationship_snapshot": {
            "strong_contacts": sorted(_strong_relationship_ids(state, agent, config))[: _memory_limit(config, "max_related_agents", 6)],
        },
    }


def _local_visual_context(
    state: AgentStateBundleSpec,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    *,
    limit: int = 6,
) -> dict[str, list[dict[str, Any]]]:
    keys = {
        f"{actor.coordinates.x},{actor.coordinates.y},{actor.coordinates.z}",
        f"{target.coordinates.x},{target.coordinates.y},{target.coordinates.z}",
        actor.room_id,
        target.room_id,
        "global",
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for key in keys:
        if not key:
            continue
        events = state.localized_visual_state.get(str(key), [])
        if events:
            result[str(key)] = [dict(item) for item in events[-limit:] if isinstance(item, dict)]
    return result


def _image_values(actor: AgentRuntimeProfileSpec, target: AgentRuntimeProfileSpec, route: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return {
        "world_name": _world_label(config),
        "domain_label": _domain_label(config),
        "actor_id": actor.agent_id,
        "actor_name": actor.display_name or actor.agent_id,
        "target_id": target.agent_id,
        "target_name": target.display_name or target.agent_id,
        "actor_appearance": actor.appearance_prompt,
        "target_appearance": target.appearance_prompt,
        "actor_role": actor.public_state.get("role_name", ""),
        "target_role": target.public_state.get("role_name", ""),
        "route_id": route.get("route_id", ""),
        "story_verb": route.get("story_verb", route.get("kind", "image")),
        "image_subject": route.get("image_subject", route.get("route_id", "scene artifact")),
    }


def _image_prompt_from_route(actor: AgentRuntimeProfileSpec, target: AgentRuntimeProfileSpec, route: dict[str, Any], config: dict[str, Any]) -> str:
    image_config = _image_generation_config(config)
    values = _image_values(actor, target, route, config)
    template = str(
        route.get("image_prompt_template")
        or image_config.get("default_prompt_template")
        or (
            "{domain_label}. Create a single polished image of {image_subject} connected to "
            "{actor_name} and {target_name}. No visible text, no watermark."
        )
    )
    prompt = _format(template, values)
    policy = str(image_config.get("prompt_policy", "")).strip()
    return (prompt + ("\n" + policy if policy else "")).strip()


def _vertex_still_image_prompt(
    client: VertexJsonClient,
    *,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    route: dict[str, Any],
    config: dict[str, Any],
    reason: str,
    source_owner: AgentRuntimeProfileSpec | None = None,
    source_artifact: dict[str, Any] | None = None,
) -> dict[str, str]:
    schema = {
        "image_prompt": "string, concise image-generation prompt, no discussion",
        "artifact_label": "string, <= 48 chars",
        "safety_notes": "string",
    }
    actor_memory = _initialize_runtime_memory(actor, config)
    target_memory = _initialize_runtime_memory(target, config)
    payload = {
        "world": config.get("scenario_meta", {}),
        "image_generation_policy": _image_generation_config(config),
        "route": route,
        "reason": reason,
        "actor": {
            "agent_id": actor.agent_id,
            "display_name": actor.display_name,
            "appearance_prompt": actor.appearance_prompt,
            "public_state": actor.public_state,
        },
        "target": {
            "agent_id": target.agent_id,
            "display_name": target.display_name,
            "appearance_prompt": target.appearance_prompt,
            "public_state": target.public_state,
        },
        "actor_memory": {
            "current_focus": actor_memory.get("current_focus", ""),
            "active_long_tasks": actor_memory.get("active_long_tasks", []),
            "recent_rounds": actor_memory.get("recent_rounds", [])[-4:],
        },
        "target_memory": {
            "current_focus": target_memory.get("current_focus", ""),
            "active_long_tasks": target_memory.get("active_long_tasks", []),
            "recent_rounds": target_memory.get("recent_rounds", [])[-4:],
        },
        "source_artifact": {
            "owner_agent_id": source_owner.agent_id if source_owner is not None else "",
            "owner_display_name": source_owner.display_name if source_owner is not None else "",
            "artifact_label": str(source_artifact.get("artifact_label", "")) if isinstance(source_artifact, dict) else "",
            "item_id": str(source_artifact.get("item_id", "")) if isinstance(source_artifact, dict) else "",
            "source": str(source_artifact.get("source", "")) if isinstance(source_artifact, dict) else "",
        },
    }
    media_parts: list[dict[str, Any]] = []
    if source_artifact is not None and not _text_only_mode(config):
        source_path = Path(str(source_artifact.get("image_path", "")).strip())
        compressed = _compress_image_for_reasoning(source_path, max_edge_px=_artifact_reasoning_max_edge_px(config))
        if compressed is not None and compressed.is_file():
            mime_type = mimetypes.guess_type(str(compressed))[0] or "image/jpeg"
            media_parts.append(
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": base64.b64encode(compressed.read_bytes()).decode("ascii"),
                    }
                }
            )
    generated = client.generate_json(
        system_instruction="You generate safe still-image prompts for simulation artifacts, not discussion prompts.",
        prompt=(
            "Create one prompt for a still-image generation request. The prompt must describe the image artifact "
            "itself. No visible text, no watermark. Do not ask the agent to write or save files; the system will do that.\n"
            "If a source artwork is provided, treat this as a bounded edit request: preserve the work's main subject, "
            "layout, and identity while applying socially grounded critique, selection pressure, or collaborative feedback.\n"
            f"context: {_json_dumps(payload)}"
        ),
        schema=schema,
        stage="image_prompt_generation",
    ) if not media_parts else client.generate_multimodal_json(
        system_instruction="You generate safe still-image prompts for simulation artifacts, not discussion prompts.",
        prompt=(
            "Create one prompt for a still-image generation request. The prompt must describe the image artifact "
            "itself. No visible text, no watermark. Do not ask the agent to write or save files; the system will do that.\n"
            "A source artwork image is attached. Use the image plus the social and memory context to decide what to revise "
            "or preserve. Keep the edit bounded and continuous with the existing work instead of replacing it with a new idea.\n"
            f"context: {_json_dumps(payload)}"
        ),
        schema=schema,
        stage="image_prompt_generation",
        media_parts=media_parts,
    )
    prompt = str(generated.get("image_prompt", "")).strip()
    if not prompt:
        prompt = _image_prompt_from_route(actor, target, route, config)
    return {
        "image_prompt": prompt,
        "artifact_label": str(generated.get("artifact_label", "image_artifact")).strip()[:80],
        "safety_notes": str(generated.get("safety_notes", "")).strip(),
    }


def _vertex_text_revision(
    client: VertexJsonClient,
    *,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    route: dict[str, Any],
    config: dict[str, Any],
    reason: str,
    source_item: InventoryItemSpec,
) -> dict[str, str]:
    schema = {
        "artifact_label": "string, <= 48 chars",
        "revised_description": "string, <= 220 chars, final revised artwork description only",
        "revision_summary": "string, <= 120 chars",
    }
    actor_memory = _initialize_runtime_memory(actor, config)
    target_memory = _initialize_runtime_memory(target, config)
    payload = {
        "world": config.get("scenario_meta", {}),
        "route": route,
        "reason": reason,
        "actor": {
            "agent_id": actor.agent_id,
            "display_name": actor.display_name,
            "role_name": actor.public_state.get("role_name", ""),
        },
        "target": {
            "agent_id": target.agent_id,
            "display_name": target.display_name,
            "role_name": target.public_state.get("role_name", ""),
        },
        "source_item": {
            "item_id": source_item.item_id,
            "description": source_item.description,
            "metadata": dict(source_item.metadata or {}),
        },
        "actor_memory": {
            "current_focus": actor_memory.get("current_focus", ""),
            "recent_rounds": actor_memory.get("recent_rounds", [])[-4:],
            "textual_artifacts": actor_memory.get("textual_artifacts", [])[-3:],
        },
        "target_memory": {
            "current_focus": target_memory.get("current_focus", ""),
            "recent_rounds": target_memory.get("recent_rounds", [])[-4:],
        },
    }
    generated = client.generate_json(
        system_instruction="You generate concise revised artwork descriptions for simulation memory, not essays.",
        prompt=(
            "Create one bounded textual revision of the actor artwork description after live critique. "
            "Preserve the artwork identity and core subject while tightening, clarifying, or refining it in response "
            "to the social feedback. Return only the final revised description, a short artifact label, and a short "
            "summary of what changed. Do not mention files, tools, or system internals.\n"
            f"context: {_json_dumps(payload)}"
        ),
        schema=schema,
        stage="text_revision_generation",
    )
    revised_description = str(generated.get("revised_description", "")).strip()
    if not revised_description:
        revised_description = _limit_text(source_item.description, 220)
    artifact_label = str(generated.get("artifact_label", "")).strip()[:80] or _limit_text(
        source_item.metadata.get("name", source_item.item_id),
        80,
    )
    return {
        "artifact_label": artifact_label,
        "revised_description": revised_description[:220],
        "revision_summary": str(generated.get("revision_summary", "")).strip()[:120],
    }


def _cinematic_values(actor: AgentRuntimeProfileSpec, target: AgentRuntimeProfileSpec) -> dict[str, Any]:
    return {
        "actor_name": actor.display_name or actor.agent_id,
        "target_name": target.display_name or target.agent_id,
        "actor_appearance": actor.appearance_prompt,
        "target_appearance": target.appearance_prompt,
        "actor_gender": actor.gender_presentation,
        "target_gender": target.gender_presentation,
    }


def _vertex_action_request(
    client: VertexJsonClient,
    *,
    state: AgentStateBundleSpec,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    config: dict[str, Any],
    round_index: int,
    video_quota_left: int,
    image_quota_left: int,
    force_cinematic: bool = False,
) -> dict[str, Any]:
    schema = {
        "route_id": "string",
        "kind": "custom|item_trade|move|cinematic|image",
        "reason": "string",
        "shared_action_core": {
            "shared_action_label": "string, <= 80 chars, the concrete visible action both participants are jointly doing",
            "shared_action_goal": "string, <= 160 chars, why this shared action matters now",
            "action_beats": ["string, <= 120 chars, 2-4 brief visible beats that can drive paired LongLive prompts"],
            "actor_role_in_action": "string, <= 120 chars",
            "target_role_in_action": "string, <= 120 chars",
            "props_in_use": ["string, <= 64 chars"],
            "location_focus": "string, <= 120 chars",
            "why_now": "string, <= 160 chars",
            "json_action_alignment": "route_only|off_json_extension|mixed",
            "off_json_detail": "string, <= 160 chars, blank if the route fully covers the visible action",
            "main_character_recording_note": "string, <= 160 chars, required when a main-character participant needs a clear round record",
        },
        "actor_relationship_instruction": "string, <= 160 chars, actor's subjective relationship update rationale for the selected route",
        "target_relationship_instruction": "string, <= 160 chars, target's subjective relationship update rationale for the selected route",
        "relationship_adjustments": [
            {
                "source_agent_id": "string, must be actor_id or target_id",
                "target_agent_id": "string, the other participant",
                "trust_delta": "integer from -20 to 20",
                "affection_delta": "integer from -20 to 20",
                "influence_fear_delta": "integer from -20 to 20",
                "reason": "string, <= 120 chars",
            }
        ],
    }
    forced_follow_up = _active_artist_feedback_follow_up(actor, round_index=round_index)
    forced_route_ids = (
        [
            route_id
            for route_id in forced_follow_up.get("preferred_route_ids", [])
            if str(route_id).strip()
        ]
        if forced_follow_up is not None and str(forced_follow_up.get("target_agent_id", "")) == target.agent_id
        else []
    )
    ordinary_routes = _filter_routes_for_context(
        list(config.get("actions", {}).get("ordinary_routes", [])),
        actor,
        target,
    )
    cinematic_routes = _filter_routes_for_context(
        list(config.get("actions", {}).get("cinematic_routes", [])),
        actor,
        target,
    )
    if forced_route_ids:
        ordinary_routes = [route for route in ordinary_routes if str(route.get("route_id", "")) in forced_route_ids] or ordinary_routes
        cinematic_routes = []
    cinematic_required = bool(force_cinematic and video_quota_left > 0)
    if cinematic_required:
        ordinary_routes = []
    routes = {
        "ordinary_routes": ordinary_routes,
        "cinematic_routes": cinematic_routes,
        "video_quota_left": video_quota_left,
        "image_quota_left": image_quota_left,
        "required_kind": "cinematic" if cinematic_required else "",
        "cinematic_candidate_probability": config.get("longlive", {}).get("candidate_probability", 0.12),
        "image_generation_policy": _image_generation_config(config),
        "forced_route_ids": forced_route_ids,
    }
    relationship_context = {
        "actor_to_target": _relationship_vector_payload(state, actor.agent_id, target.agent_id),
        "target_to_actor": _relationship_vector_payload(state, target.agent_id, actor.agent_id),
    }
    actor_payload = _compact_agent_prompt_payload(actor, state, config)
    target_payload = _compact_agent_prompt_payload(target, state, config)
    memory_context = {
        "actor_active_status_names": sorted(_status_names(actor)),
        "target_active_status_names": sorted(_status_names(target)),
        "local_visual_state": _local_visual_context(state, actor, target),
        "recent_global_world_events": _recent_global_world_events(state),
        "target_selection_policy": config.get("actions", {}).get("target_selection", {}),
        "routing_policy": config.get("actions", {}).get("routing_policy", {}),
        "world_progress_policy": config.get("world_progress", {}),
        "shared_task_threads": _shared_task_thread_ids(actor, target),
        "actor_location_awareness": actor_payload.get("memory", {}).get("location_awareness", {}),
        "target_location_awareness": target_payload.get("memory", {}).get("location_awareness", {}),
        "recording_context": _recording_context(actor, target),
    }
    media_parts, artifact_descriptors = _artifact_reasoning_parts(
        [actor, target],
        config=config,
    )
    if artifact_descriptors:
        memory_context["artifact_visual_context"] = artifact_descriptors
    prompt = (
        f"Choose one interaction route for the fixed JSON world '{_world_label(config)}', then judge the relationship-state deltas caused by that selected route.\n"
        f"round_index: {round_index}\n"
        f"actor: {_json_dumps(actor_payload)}\n"
        f"target: {_json_dumps(target_payload)}\n"
        f"current_relationships: {_json_dumps(relationship_context)}\n"
        f"memory_context: {_json_dumps(memory_context)}\n"
        f"routes: {_json_dumps(routes)}\n"
        + (
            "This request must validate the real LongLive path: choose an existing route_id from cinematic_routes. "
            "Do not choose ordinary_routes; the required kind is cinematic.\n"
            if cinematic_required
            else ""
        )
        + "Prefer ordinary routes for chat, trading, healing, coordination, and movement.\n"
        "When actor and target are in different rooms, prefer a move route unless the action is clearly remote-safe. "
        "Use movement to approach the target room before close-contact trade, healing, sparring, or cinematic body-cooperation.\n"
        "Treat the actor and target memory blocks as layered continuity. Keep recent_rounds from the last ten rounds vivid and specific. "
        "Use active_long_tasks and current_focus to keep multi-round goals alive instead of resetting to generic small talk.\n"
        "Prefer repeated interaction with a believable social circle when cohort_ids, strong_contacts, shared_task_threads, "
        "or location_awareness indicate an ongoing partnership, rivalry, or local clique.\n"
        "Treat shared_action_core as required planning output for the visible action, especially for cinematic routes. "
        "Define one concrete shared action that both participants are jointly performing right now, with clear beats, role split, props, "
        "and any off-json extension needed to make the behavior feel specific and lived-in while staying legal for the chosen route.\n"
        "When a main-character participant is present, prefer a route and interaction framing that can visibly record that character this round. "
        "Avoid generic filler or vague cooperation; the main_character_recording_note should say what must be shown.\n"
        "When video_quota_left is positive, choose a cinematic route for roughly the configured "
        "cinematic_candidate_probability of eligible interactions, but only when the route is a visible "
        "non-sexual body-cooperation action matching the supplied world policy.\n"
        "Only choose image routes when image_quota_left is positive and the supplied image_generation_policy conditions apply.\n"
        "Treat status and route memory fields as behavioral constraints: do not repeat a route suppressed by an active status; "
        "prefer follow-up or next-phase routes when current status effects, local visual state, or world progress policy indicate the prior need was already handled. "
        "When forced_route_ids is non-empty, treat it as a hard continuation constraint for this actor-target pair and choose one of those route_ids if legal.\n"
        "When artifact_visual_context is present, use the attached images as extra evidence about visible props and recent artifacts. "
        "Do not invent hidden features not visible in the images.\n"
        "Use existing status effects to avoid repeating resolved rescue/treatment/repair actions on the same target unless the route explicitly allows it.\n"
        "Return an existing route_id from the supplied route lists.\n"
        "Also return delta instructions, not final absolute relationship scores. Both participants must have one update: "
        "actor->target and target->actor. Use small values for routine actions. Trades usually raise trust if fair; "
        "healing and support can raise affection; warnings or pressure can reduce trust or raise influence_fear. "
        "Keep all deltas in [-20, 20] and do not invent new agents or world rules."
    )
    request_kwargs = {
        "system_instruction": "You are a strict JSON action router and relationship-delta judge. Do not invent world rules.",
        "prompt": prompt,
        "schema": schema,
        "stage": "interaction_routing",
    }
    if media_parts:
        return client.generate_multimodal_json(media_parts=media_parts, **request_kwargs)
    return client.generate_json(**request_kwargs)


def _vertex_video_prompts(
    client: VertexJsonClient,
    *,
    state: AgentStateBundleSpec,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    route: dict[str, Any],
    config: dict[str, Any],
    round_index: int,
    shared_action_core: dict[str, Any] | None = None,
) -> dict[str, str]:
    segment_seconds = int(config.get("longlive", {}).get("segment_seconds", 10))
    schema = {
        "actor_video_prompt": "string",
        "target_continuation_prompt": "string",
        "safety_notes": "string",
    }
    actor_payload = _compact_agent_prompt_payload(actor, state, config)
    target_payload = _compact_agent_prompt_payload(target, state, config)
    room_context = _room_prompt_context(config, actor.room_id or target.room_id)
    local_visual_state = _local_visual_context(state, actor, target)
    joint_history = _recent_joint_history(actor, target, config)
    visible_props = _visible_prop_context(actor, target, config)
    payload = {
        "visual_style": config.get("longlive", {}).get("visual_style", ""),
        "segment_seconds": segment_seconds,
        "round_index": round_index,
        "route": route,
        "shared_action_core": shared_action_core or {},
        "room_context": room_context,
        "local_visual_state": local_visual_state,
        "recent_joint_history": joint_history,
        "visible_props": visible_props,
        "recording_context": _recording_context(actor, target),
        "actor": {
            **actor_payload,
            "gender_presentation": actor.gender_presentation,
        },
        "target": {
            **target_payload,
            "gender_presentation": target.gender_presentation,
        },
    }
    prompt = (
        "Create two compliant video-generation prompts for one continuous LongLive video.\n"
        f"The first prompt covers seconds 0-{segment_seconds}; the second prompt continues the SAME video "
        f"from seconds {segment_seconds}-{segment_seconds * 2}.\n"
        f"The content must show a non-sexual body-cooperation interaction between exactly these two agents in {_world_label(config)}.\n"
        "Keep identity, appearance, room mood, camera continuity, and action continuity consistent. No subtitles, no visible text, no watermark.\n"
        "Use shared_action_core as the required action backbone. The two prompts should feel like two halves of the same concrete shared action, "
        "not a generic cooperation template. Honor the action beats, each participant role, visible props, room context, and any main-character recording note.\n"
        "It is allowed, and often better, for the visible action details to go beyond the route label when shared_action_core.off_json_detail indicates "
        "a more specific behavior that still fits the world, safety rules, and the chosen route.\n"
        "Avoid defaulting to maps, parchment, nodding, or vague discussion unless those props and beats are explicitly supported by the context.\n"
        "Do not produce discussion text. Return only the JSON object.\n"
        f"context: {_json_dumps(payload)}"
    )
    media_parts, artifact_descriptors = _artifact_reasoning_parts([actor, target], config=config)
    if artifact_descriptors:
        payload["artifact_visual_context"] = artifact_descriptors
        prompt = (
            "Create two compliant video-generation prompts for one continuous LongLive video.\n"
            f"The first prompt covers seconds 0-{segment_seconds}; the second prompt continues the SAME video "
            f"from seconds {segment_seconds}-{segment_seconds * 2}.\n"
            f"The content must show a non-sexual body-cooperation interaction between exactly these two agents in {_world_label(config)}.\n"
            "Keep identity, appearance, room mood, camera continuity, and action continuity consistent. No subtitles, no visible text, no watermark.\n"
            "Use shared_action_core as the required action backbone. The two prompts should feel like two halves of the same concrete shared action, "
            "not a generic cooperation template. Honor the action beats, each participant role, visible props, room context, and any main-character recording note.\n"
            "When artifact_visual_context is present, treat the attached images as evidence about visible props and recent artifacts. "
            "Use them to ground the prompts, but do not invent hidden features not visible in the images.\n"
            "Avoid defaulting to maps, parchment, nodding, or vague discussion unless those props and beats are explicitly supported by the context.\n"
            "Do not produce discussion text. Return only the JSON object.\n"
            f"context: {_json_dumps(payload)}"
        )
    request_kwargs = {
        "system_instruction": "You generate safe cinematic video prompts, not discussion prompts.",
        "prompt": prompt,
        "schema": schema,
        "stage": "video_prompt_generation",
    }
    if media_parts:
        generated = client.generate_multimodal_json(media_parts=media_parts, **request_kwargs)
    else:
        generated = client.generate_json(**request_kwargs)
    actor_prompt = str(generated.get("actor_video_prompt", "")).strip()
    target_prompt = str(generated.get("target_continuation_prompt", "")).strip()
    if not actor_prompt or not target_prompt:
        raise RuntimeError("Vertex video prompt generation returned empty prompt text")
    return {
        "actor_video_prompt": actor_prompt,
        "target_continuation_prompt": target_prompt,
        "safety_notes": str(generated.get("safety_notes", "")).strip(),
    }


