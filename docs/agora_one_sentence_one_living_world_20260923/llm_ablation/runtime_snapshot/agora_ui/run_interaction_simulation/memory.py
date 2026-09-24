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
from .memory_compression import *





SCRIPT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_ENV = "AGORA_SIM_CONFIG"
DEFAULT_PY_BIN = Path(sys.executable)



def _find_inventory_item(agent: AgentRuntimeProfileSpec, config: dict[str, Any]) -> InventoryItemSpec | None:
    currency_id = str(config.get("economy", {}).get("currency_item_id", "gold"))
    for item in agent.inventory:
        if item.item_id != currency_id and item.quantity > 0:
            return item
    return None


def _find_inventory_item_by_id(agent: AgentRuntimeProfileSpec, item_id: str) -> InventoryItemSpec | None:
    wanted = str(item_id).strip()
    if not wanted:
        return None
    for item in agent.inventory:
        if str(item.item_id).strip() == wanted and int(item.quantity) > 0:
            return item
    return None


def _item_quantity(agent: AgentRuntimeProfileSpec, item_id: str) -> int:
    for item in agent.inventory:
        if item.item_id == item_id:
            return int(item.quantity)
    return 0


def _catalog_price(config: dict[str, Any], item_id: str) -> int:
    return int(_catalog_by_id(config).get(item_id, {}).get("price", 0))


def _memory_config(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("memory", {})
    return value if isinstance(value, dict) else {}


def _runtime_memory(agent: AgentRuntimeProfileSpec) -> dict[str, Any]:
    value = agent.public_state.get("runtime_memory", {}) if isinstance(agent.public_state, dict) else {}
    return dict(value) if isinstance(value, dict) else {}


def _set_runtime_memory(agent: AgentRuntimeProfileSpec, memory: dict[str, Any]) -> None:
    public_state = dict(agent.public_state or {})
    public_state["runtime_memory"] = dict(memory)
    agent.public_state = public_state


def _memory_limit(config: dict[str, Any], key: str, default: int) -> int:
    value = _memory_config(config).get(key, default)
    return max(1, _safe_int(value, default))


def _inventory_prompt_summary(
    agent: AgentRuntimeProfileSpec,
    config: dict[str, Any],
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    currency_id = str(config.get("economy", {}).get("currency_item_id", "gold"))
    max_items = limit or _memory_limit(config, "max_prompt_inventory_items", 4)
    items: list[dict[str, Any]] = []
    for item in agent.inventory:
        if item.item_id == currency_id or int(item.quantity) <= 0:
            continue
        items.append(
            {
                "item_id": item.item_id,
                "quantity": int(item.quantity),
                "description": _limit_text(item.description, 96),
            }
        )
    return items[:max_items]


def _property_prompt_summary(agent: AgentRuntimeProfileSpec, *, limit: int) -> list[dict[str, Any]]:
    public_state = dict(agent.public_state or {})
    raw = public_state.get("property_library", [])
    if not isinstance(raw, list):
        return []
    payload: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        payload.append(
            {
                "asset_name": _limit_text(item.get("asset_name", ""), 72),
                "asset_type": _limit_text(item.get("asset_type", ""), 48),
                "story_use": _limit_text(item.get("story_use", item.get("description", "")), 120),
            }
        )
    return payload[:limit]


def _knowledge_prompt_summary(agent: AgentRuntimeProfileSpec, *, limit: int) -> list[dict[str, Any]]:
    raw = agent.knowledge_assets
    if not isinstance(raw, list):
        return []
    payload: list[dict[str, Any]] = []
    for item in raw:
        topic = getattr(item, "topic", "")
        summary = getattr(item, "summary", "")
        if not str(topic).strip() and not str(summary).strip():
            continue
        payload.append(
            {
                "topic": _limit_text(topic, 72),
                "summary": _limit_text(summary, 120),
            }
        )
    return payload[:limit]


def _artist_feedback_follow_up_config(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("actions", {}).get("artist_feedback_follow_up", {})
    return value if isinstance(value, dict) else {}


def _active_artist_feedback_follow_up(agent: AgentRuntimeProfileSpec, *, round_index: int) -> dict[str, Any] | None:
    memory = _runtime_memory(agent)
    raw = memory.get("artist_feedback_follow_up", {})
    if not isinstance(raw, dict) or not raw:
        return None
    due_round = _safe_int(raw.get("due_round", 0), 0)
    expires_round = _safe_int(raw.get("expires_round", 0), 0)
    target_id = str(raw.get("target_agent_id", "")).strip()
    if not target_id:
        return None
    if due_round > 0 and round_index < due_round:
        return None
    if expires_round > 0 and round_index > expires_round:
        return None
    return {
        "target_agent_id": target_id,
        "due_round": due_round,
        "expires_round": expires_round,
        "preferred_route_ids": [
            str(item).strip()
            for item in raw.get("preferred_route_ids", [])
            if str(item).strip()
        ],
        "note": _limit_text(raw.get("note", ""), 180),
        "source_round": _safe_int(raw.get("source_round", 0), 0),
    }


def _item_is_important_artifact(item: InventoryItemSpec | dict[str, Any], config: dict[str, Any]) -> bool:
    metadata = {}
    if isinstance(item, InventoryItemSpec):
        metadata = dict(item.metadata or {})
        item_id = item.item_id
        description = item.description
    else:
        metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata", {}), dict) else {}
        item_id = str(item.get("item_id", ""))
        description = str(item.get("description", ""))
    if bool(metadata.get("important_artifact")):
        return True
    rarity = str(metadata.get("rarity", "")).strip().lower()
    category = str(metadata.get("category", "")).strip().lower()
    text = " ".join(
        part
        for part in [
            str(metadata.get("name", "")),
            description,
            category,
            str(item_id),
        ]
        if str(part).strip()
    ).lower()
    if rarity in {"epic", "legendary", "unique", "rare"}:
        return True
    if category in {"artifact", "relic", "quest_item", "quest", "heirloom"}:
        return True
    return any(token in text for token in ("artifact", "relic", "heirloom", "commission", "map", "seal", "crystal"))


def _catalog_item_visual_records(agent: AgentRuntimeProfileSpec, config: dict[str, Any]) -> list[dict[str, Any]]:
    mode = _item_image_mode(config)
    if mode == "off":
        return []
    records: list[dict[str, Any]] = []
    for item in agent.inventory:
        if int(item.quantity) <= 0:
            continue
        if mode == "important_only" and not _item_is_important_artifact(item, config):
            continue
        if not str(item.image_path).strip():
            continue
        records.append(
            _sanitize_visual_artifact(
                {
                    "kind": "inventory_item",
                    "artifact_label": str(item.metadata.get("name", "") or item.description or item.item_id),
                    "item_id": item.item_id,
                    "image_path": item.image_path,
                    "source": "inventory",
                }
            )
        )
    return records[:4]


def _initialize_runtime_memory(agent: AgentRuntimeProfileSpec, config: dict[str, Any]) -> dict[str, Any]:
    memory = _runtime_memory(agent)
    directive = _limit_text(agent.public_state.get("activity_directive", ""), 180)
    mainline = _limit_text(memory.get("mainline_summary", "") or directive or agent.private_notes, 220)
    memory["mainline_summary"] = mainline
    memory["current_focus"] = _limit_text(memory.get("current_focus", "") or directive or mainline, 180)
    raw_recent = memory.get("recent_rounds", [])
    if not isinstance(raw_recent, list):
        raw_recent = []
    memory["recent_rounds"] = [
        _sanitize_recent_entry(item)
        for item in raw_recent
        if isinstance(item, dict)
    ][-_memory_limit(config, "keep_recent_rounds", 10):]
    raw_tasks = memory.get("active_long_tasks", [])
    if not isinstance(raw_tasks, list):
        raw_tasks = []
    memory["active_long_tasks"] = [
        _sanitize_long_task(item)
        for item in raw_tasks
        if isinstance(item, dict) and str(item.get("thread_id", "")).strip()
    ][:_memory_limit(config, "max_active_long_tasks", 5)]
    interaction_counts = memory.get("interaction_counts", {})
    if not isinstance(interaction_counts, dict):
        interaction_counts = {}
    memory["interaction_counts"] = {
        str(agent_id): max(0, _safe_int(count, 0))
        for agent_id, count in interaction_counts.items()
        if str(agent_id).strip()
    }
    archived_route_counts = memory.get("archived_route_counts", {})
    if not isinstance(archived_route_counts, dict):
        archived_route_counts = {}
    memory["archived_route_counts"] = {
        str(route_id): max(0, _safe_int(count, 0))
        for route_id, count in archived_route_counts.items()
        if str(route_id).strip()
    }
    archived_counterpart_counts = memory.get("archived_counterpart_counts", {})
    if not isinstance(archived_counterpart_counts, dict):
        archived_counterpart_counts = {}
    memory["archived_counterpart_counts"] = {
        str(agent_id): max(0, _safe_int(count, 0))
        for agent_id, count in archived_counterpart_counts.items()
        if str(agent_id).strip()
    }
    cohort_ids = memory.get("cohort_ids", [])
    if not isinstance(cohort_ids, list):
        cohort_ids = []
    memory["cohort_ids"] = [str(item) for item in cohort_ids if str(item).strip()][: _memory_limit(config, "max_cohort_ids", 4)]
    location_awareness = memory.get("location_awareness", {})
    memory["location_awareness"] = dict(location_awareness) if isinstance(location_awareness, dict) else {}
    visual_artifacts = memory.get("visual_artifacts", [])
    if not isinstance(visual_artifacts, list):
        visual_artifacts = []
    normalized_visual_artifacts = [
        _sanitize_visual_artifact(item)
        for item in visual_artifacts
        if isinstance(item, dict) and str(item.get("image_path", "")).strip()
    ]
    if not normalized_visual_artifacts:
        normalized_visual_artifacts = _catalog_item_visual_records(agent, config)
    memory["visual_artifacts"] = normalized_visual_artifacts[:_memory_limit(config, "max_visual_artifacts", 4)]
    textual_artifacts = memory.get("textual_artifacts", [])
    if not isinstance(textual_artifacts, list):
        textual_artifacts = []
    memory["textual_artifacts"] = [
        _sanitize_textual_artifact(item)
        for item in textual_artifacts
        if isinstance(item, dict) and str(item.get("description", "")).strip()
    ][:_memory_limit(config, "max_visual_artifacts", 4)]
    follow_up = memory.get("artist_feedback_follow_up", {})
    if not isinstance(follow_up, dict):
        follow_up = {}
    if str(follow_up.get("target_agent_id", "")).strip():
        memory["artist_feedback_follow_up"] = {
            "target_agent_id": str(follow_up.get("target_agent_id", "")).strip()[:128],
            "due_round": _safe_int(follow_up.get("due_round", 0), 0),
            "expires_round": _safe_int(follow_up.get("expires_round", 0), 0),
            "preferred_route_ids": [
                str(item).strip()[:80]
                for item in follow_up.get("preferred_route_ids", [])
                if str(item).strip()
            ][:4],
            "note": _limit_text(follow_up.get("note", ""), 180),
            "source_round": _safe_int(follow_up.get("source_round", 0), 0),
        }
    else:
        memory.pop("artist_feedback_follow_up", None)
    memory["archived_round_count"] = max(0, _safe_int(memory.get("archived_round_count", 0), 0))
    return memory


def _task_thread_ids(agent: AgentRuntimeProfileSpec) -> set[str]:
    task_ids: set[str] = set()
    for item in _runtime_memory(agent).get("active_long_tasks", []):
        if isinstance(item, dict):
            thread_id = str(item.get("thread_id", "")).strip()
            if thread_id:
                task_ids.add(thread_id)
    return task_ids


def _shared_task_thread_ids(actor: AgentRuntimeProfileSpec, target: AgentRuntimeProfileSpec) -> list[str]:
    shared = _task_thread_ids(actor) & _task_thread_ids(target)
    return sorted(shared)


def _recent_interaction_count(actor: AgentRuntimeProfileSpec, target_id: str) -> int:
    counts = _runtime_memory(actor).get("interaction_counts", {})
    if not isinstance(counts, dict):
        return 0
    return max(0, _safe_int(counts.get(target_id, 0), 0))


def _strong_relationship_ids(
    state: AgentStateBundleSpec,
    actor: AgentRuntimeProfileSpec,
    config: dict[str, Any],
) -> set[str]:
    selection = config.get("actions", {}).get("target_selection", {})
    trust_threshold = _safe_int(selection.get("relationship_trust_threshold", 60), 60)
    affection_threshold = _safe_int(selection.get("relationship_affection_threshold", 60), 60)
    strong_ids: set[str] = set()
    for target_id, vector in state.relationship_tensor.get(actor.agent_id, {}).items():
        if (
            int(vector.trust) >= trust_threshold
            or int(vector.affection) >= affection_threshold
            or int(vector.influence_fear) >= 30
        ):
            strong_ids.add(str(target_id))
    return strong_ids


def _location_awareness_payload(
    state: AgentStateBundleSpec,
    actor: AgentRuntimeProfileSpec,
    config: dict[str, Any],
) -> dict[str, Any]:
    memory = _initialize_runtime_memory(actor, config)
    same_room_ids = [
        agent.agent_id
        for agent in state.agents
        if agent.agent_id != actor.agent_id and actor.room_id and agent.room_id == actor.room_id
    ]
    nearby_limit = _memory_limit(config, "max_nearby_agents", 6)
    related_limit = _memory_limit(config, "max_related_agents", 6)
    nearby_agents: list[dict[str, Any]] = []
    for agent in state.agents:
        if agent.agent_id == actor.agent_id:
            continue
        walk_distance = _walkable_distance_config(actor.coordinates, agent.coordinates, config)
        if walk_distance is None:
            continue
        nearby_agents.append(
            {
                "agent_id": agent.agent_id,
                "display_name": agent.display_name,
                "room_id": agent.room_id,
                "distance": int(walk_distance),
                "same_room": bool(actor.room_id and actor.room_id == agent.room_id),
                "recent_interactions": _recent_interaction_count(actor, agent.agent_id),
            }
        )
    nearby_agents.sort(key=lambda item: (int(item["distance"]), -int(item["recent_interactions"]), item["agent_id"]))
    recent_counterpart_ids = [
        str(item.get("other_agent_id", "")).strip()
        for item in memory.get("recent_rounds", [])
        if isinstance(item, dict) and str(item.get("other_agent_id", "")).strip()
    ]
    notable_ids = list(dict.fromkeys(memory.get("cohort_ids", []) + recent_counterpart_ids + sorted(_strong_relationship_ids(state, actor, config))))
    agent_lookup = _agent_map(state)
    related_agents: list[dict[str, Any]] = []
    for target_id in notable_ids:
        target = agent_lookup.get(target_id)
        if target is None:
            continue
        vector = _relationship_vector_payload(state, actor.agent_id, target_id)
        related_agents.append(
            {
                "agent_id": target.agent_id,
                "display_name": target.display_name,
                "room_id": target.room_id,
                "coordinates": target.coordinates.model_dump(),
                "distance": _walkable_distance_config(actor.coordinates, target.coordinates, config) or _distance(actor.coordinates, target.coordinates),
                "relationship": vector,
            }
        )
    return {
        "current_room_id": actor.room_id,
        "same_room_agent_ids": same_room_ids[:nearby_limit],
        "nearby_agents": nearby_agents[:nearby_limit],
        "related_agents": related_agents[:related_limit],
    }


def _artifact_reasoning_parts(
    agent_sources: list[AgentRuntimeProfileSpec | dict[str, Any]],
    *,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not _artifact_reasoning_enabled(config):
        return [], []
    media_parts: list[dict[str, Any]] = []
    descriptors: list[dict[str, Any]] = []
    max_edge_px = _artifact_reasoning_max_edge_px(config)
    seen_paths: set[str] = set()
    for source in agent_sources:
        if isinstance(source, AgentRuntimeProfileSpec):
            agent_id = source.agent_id
            memory = _initialize_runtime_memory(source, config)
        else:
            agent_id = str(source.get("agent_id", "")).strip()
            memory = source.get("memory", {})
            if not isinstance(memory, dict):
                continue
        visual_artifacts = memory.get("visual_artifacts", [])
        if not isinstance(visual_artifacts, list):
            continue
        for artifact in visual_artifacts[:2]:
            if not isinstance(artifact, dict):
                continue
            image_path = str(artifact.get("image_path", "")).strip()
            if not image_path or image_path in seen_paths:
                continue
            compressed = _compress_image_for_reasoning(Path(image_path), max_edge_px=max_edge_px)
            if compressed is None or not compressed.is_file():
                continue
            mime_type = mimetypes.guess_type(str(compressed))[0] or "image/jpeg"
            try:
                encoded = base64.b64encode(compressed.read_bytes()).decode("ascii")
            except Exception:
                continue
            media_parts.append(
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": encoded,
                    }
                }
            )
            descriptors.append(
                {
                    "agent_id": agent_id,
                    "artifact_label": str(artifact.get("artifact_label", "")),
                    "kind": str(artifact.get("kind", "")),
                    "item_id": str(artifact.get("item_id", "")),
                    "reasoning_image_path": str(compressed),
                }
            )
            seen_paths.add(image_path)
            if len(media_parts) >= 3:
                return media_parts, descriptors
    return media_parts, descriptors


def _visual_artifacts_for_agent(agent: AgentRuntimeProfileSpec, config: dict[str, Any]) -> list[dict[str, Any]]:
    memory = _initialize_runtime_memory(agent, config)
    visual_artifacts = memory.get("visual_artifacts", [])
    if not isinstance(visual_artifacts, list):
        return []
    return [
        _sanitize_visual_artifact(item)
        for item in visual_artifacts
        if isinstance(item, dict) and str(item.get("image_path", "")).strip()
    ]


def _select_route_source_artifact(
    *,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    route: dict[str, Any],
    config: dict[str, Any],
) -> tuple[AgentRuntimeProfileSpec | None, dict[str, Any] | None]:
    owner_pref = str(route.get("image_source_agent", route.get("source_artifact_agent", ""))).strip().lower()
    preferred_item_id = str(route.get("image_source_item_id", "")).strip()
    name_contains = str(route.get("image_source_name_contains", "")).strip().lower()
    candidates: list[AgentRuntimeProfileSpec]
    if owner_pref == "target":
        candidates = [target]
    elif owner_pref == "actor":
        candidates = [actor]
    elif owner_pref in {"either", "shared"}:
        candidates = [actor, target]
    else:
        candidates = [actor, target]
    for owner in candidates:
        artifacts = _visual_artifacts_for_agent(owner, config)
        if preferred_item_id:
            preferred = [item for item in artifacts if str(item.get("item_id", "")).strip() == preferred_item_id]
            if preferred:
                return owner, preferred[0]
        if name_contains:
            preferred = [
                item
                for item in artifacts
                if name_contains in str(item.get("artifact_label", "")).strip().lower()
                or name_contains in str(item.get("item_id", "")).strip().lower()
            ]
            if preferred:
                return owner, preferred[0]
        if artifacts:
            return owner, artifacts[0]
    return None, None


def _replace_inventory_item_image(
    agent: AgentRuntimeProfileSpec,
    *,
    item_id: str,
    image_path: str,
    artifact_label: str = "",
) -> None:
    target_item_id = str(item_id).strip()
    if not target_item_id or not str(image_path).strip():
        return
    for item in agent.inventory:
        if str(item.item_id).strip() != target_item_id:
            continue
        item.image_path = str(image_path).strip()
        if artifact_label and not str(item.description).strip():
            item.description = artifact_label.strip()
        return


def _update_agent_runtime_memory(
    state: AgentStateBundleSpec,
    *,
    config: dict[str, Any],
    round_index: int,
    round_stories: list[dict[str, Any]],
    round_extra_world_events: list[dict[str, Any]],
    round_image_jobs: list[dict[str, Any]] | None = None,
) -> None:
    keep_recent = _memory_limit(config, "keep_recent_rounds", 10)
    max_tasks = _memory_limit(config, "max_active_long_tasks", 5)
    max_cohort_ids = _memory_limit(config, "max_cohort_ids", 4)
    agent_lookup = _agent_map(state)
    room_occupants: dict[str, list[str]] = {}
    for agent in state.agents:
        room_occupants.setdefault(agent.room_id, []).append(agent.agent_id)
        _set_runtime_memory(agent, _initialize_runtime_memory(agent, config))

    for event in round_extra_world_events:
        if not isinstance(event, dict):
            continue
        thread_id = f"world:{str(event.get('event_id', 'event')).strip()}"
        task_record = _sanitize_long_task(
            {
                "thread_id": thread_id,
                "title": event.get("title", ""),
                "description": event.get("description", ""),
                "room_id": event.get("room_id", ""),
                "status": "open",
                "next_step": event.get("description", ""),
                "preferred_routes": event.get("preferred_routes", []),
                "last_updated_round": round_index,
                "expires_after_rounds": event.get("expires_after_rounds", 3),
                "touch_count": 0,
                "source": event.get("event_type", "world_event"),
            }
        )
        interested_ids = set(
            str(item)
            for item in event.get("main_character_hooks", [])
            if str(item).strip()
        )
        interested_ids.update(room_occupants.get(str(event.get("room_id", "")), [])[:8])
        for agent_id in interested_ids:
            agent = agent_lookup.get(agent_id)
            if agent is None:
                continue
            memory = _runtime_memory(agent)
            tasks = [dict(item) for item in memory.get("active_long_tasks", []) if isinstance(item, dict)]
            replaced = False
            for index, task in enumerate(tasks):
                if str(task.get("thread_id", "")) == thread_id:
                    tasks[index] = {**task, **task_record, "touch_count": max(0, _safe_int(task.get("touch_count", 0), 0))}
                    replaced = True
                    break
            if not replaced:
                tasks.append(task_record)
            tasks.sort(
                key=lambda item: (
                    -_safe_int(item.get("touch_count", 0), 0),
                    -_safe_int(item.get("last_updated_round", 0), 0),
                    item.get("title", ""),
                )
            )
            memory["active_long_tasks"] = tasks[:max_tasks]
            _set_runtime_memory(agent, memory)

    for story in round_stories:
        if not isinstance(story, dict):
            continue
        actor = agent_lookup.get(str(story.get("actor_id", "")))
        target = agent_lookup.get(str(story.get("target_id", "")))
        if actor is None or target is None:
            continue
        follow_up_config = _artist_feedback_follow_up_config(config)
        if bool(follow_up_config.get("enabled", False)):
            trigger_routes = {
                str(item).strip()
                for item in follow_up_config.get("trigger_route_ids", [])
                if str(item).strip()
            }
            required_item_id = str(follow_up_config.get("actor_requires_item_id", "signature_artwork")).strip()
            route_id = str(story.get("route_id", "")).strip()
            if route_id in trigger_routes and _find_inventory_item_by_id(target, required_item_id) is not None:
                memory = _runtime_memory(target)
                delay_rounds = max(1, _safe_int(follow_up_config.get("follow_up_after_rounds", 1), 1))
                expires_after = max(delay_rounds, _safe_int(follow_up_config.get("expires_after_rounds", 3), 3))
                preferred_route_ids = [
                    str(item).strip()
                    for item in follow_up_config.get("preferred_route_ids", [])
                    if str(item).strip()
                ]
                memory["artist_feedback_follow_up"] = {
                    "target_agent_id": actor.agent_id,
                    "due_round": round_index + delay_rounds,
                    "expires_round": round_index + expires_after,
                    "preferred_route_ids": preferred_route_ids[:4],
                    "note": _limit_text(
                        f"Return to {actor.display_name} after their feedback on your artwork.",
                        180,
                    ),
                    "source_round": round_index,
                }
                memory["current_focus"] = _limit_text(
                    f"Return to {actor.display_name} next round to answer their feedback on your artwork.",
                    180,
                )
                _set_runtime_memory(target, memory)
        shared_task_ids = _shared_task_thread_ids(actor, target)
        for current, other, room_key in (
            (actor, target, "actor_room_id"),
            (target, actor, "target_room_id"),
        ):
            memory = _runtime_memory(current)
            recent = [dict(item) for item in memory.get("recent_rounds", []) if isinstance(item, dict)]
            entry = _sanitize_recent_entry(
                {
                    "round_index": round_index,
                    "other_agent_id": other.agent_id,
                    "other_agent_name": other.display_name,
                    "route_id": story.get("route_id", story.get("kind", "")),
                    "story_verb": story.get("story_verb", ""),
                    "room_id": story.get(room_key, ""),
                    "same_room": story.get("same_room", False),
                    "distance": story.get("distance", 0),
                    "focus_note": story.get("selection_reason", ""),
                }
            )
            recent.append(entry)
            while len(recent) > keep_recent:
                _archive_recent_entry(memory, recent.pop(0))
            memory["recent_rounds"] = recent
            counts = dict(memory.get("interaction_counts", {}))
            counts[other.agent_id] = max(0, _safe_int(counts.get(other.agent_id, 0), 0)) + 1
            memory["interaction_counts"] = counts
            tasks = [dict(item) for item in memory.get("active_long_tasks", []) if isinstance(item, dict)]
            for task in tasks:
                task_room = str(task.get("room_id", "")).strip()
                preferred_routes = {str(item).strip() for item in task.get("preferred_routes", []) if str(item).strip()}
                if (
                    (task_room and task_room in {str(story.get("actor_room_id", "")), str(story.get("target_room_id", ""))})
                    or str(story.get("route_id", "")) in preferred_routes
                    or str(story.get("planned_route_id", "")) in preferred_routes
                ):
                    task["touch_count"] = max(0, _safe_int(task.get("touch_count", 0), 0)) + 1
                    task["last_updated_round"] = round_index
                    task["next_step"] = _limit_text(
                        f"Continue after {story.get('story_verb', 'the latest interaction')} with {other.display_name}.",
                        140,
                    )
            memory["active_long_tasks"] = tasks[:max_tasks]
            pending_follow_up = _active_artist_feedback_follow_up(current, round_index=round_index)
            if (
                pending_follow_up is not None
                and current.agent_id == str(story.get("actor_id", "")).strip()
                and other.agent_id == str(pending_follow_up.get("target_agent_id", "")).strip()
                and str(story.get("route_id", "")).strip() not in {"move_between_rooms", "move_to_task"}
            ):
                memory.pop("artist_feedback_follow_up", None)
            _set_runtime_memory(current, memory)

    if round_image_jobs:
        jobs_by_actor: dict[str, list[dict[str, Any]]] = {}
        for job in round_image_jobs:
            if not isinstance(job, dict):
                continue
            if str(job.get("status", "")) != "ok":
                continue
            image_path = str(job.get("image_path", "")).strip()
            actor_id = str(job.get("actor_id", "")).strip()
            if not image_path or not actor_id:
                continue
            jobs_by_actor.setdefault(actor_id, []).append(dict(job))
        for actor_id, jobs in jobs_by_actor.items():
            agent = agent_lookup.get(actor_id)
            if agent is None:
                continue
            memory = _runtime_memory(agent)
            artifacts = [dict(item) for item in memory.get("visual_artifacts", []) if isinstance(item, dict)]
            for job in jobs:
                reasoning_image = _compress_image_for_reasoning(
                    Path(str(job.get("image_path", ""))),
                    max_edge_px=_artifact_reasoning_max_edge_px(config),
                )
                artifacts.insert(
                    0,
                    _sanitize_visual_artifact(
                        {
                            "kind": "image_artifact",
                            "artifact_label": str(job.get("artifact_label", job.get("route_id", "artifact"))),
                            "item_id": str(job.get("source_item_id", job.get("route_id", ""))),
                            "image_path": str(job.get("image_path", "")),
                            "source": "image_job",
                            "round_index": round_index,
                            "reasoning_image_path": str(reasoning_image) if reasoning_image is not None else "",
                        }
                    ),
                )
            deduped: list[dict[str, Any]] = []
            seen_paths: set[str] = set()
            for artifact in artifacts:
                path_key = str(artifact.get("image_path", "")).strip()
                if not path_key or path_key in seen_paths:
                    continue
                seen_paths.add(path_key)
                deduped.append(artifact)
            memory["visual_artifacts"] = deduped[:_memory_limit(config, "max_visual_artifacts", 4)]
            _set_runtime_memory(agent, memory)

    for agent in state.agents:
        memory = _runtime_memory(agent)
        recent_rounds = [dict(item) for item in memory.get("recent_rounds", []) if isinstance(item, dict)]
        interaction_counts = dict(memory.get("interaction_counts", {}))
        candidate_ids: list[str] = []
        for entry in reversed(recent_rounds):
            other_id = str(entry.get("other_agent_id", "")).strip()
            if other_id and other_id not in candidate_ids:
                candidate_ids.append(other_id)
        for other_id, count in sorted(interaction_counts.items(), key=lambda item: (-_safe_int(item[1], 0), item[0])):
            if _safe_int(count, 0) > 0 and other_id not in candidate_ids:
                candidate_ids.append(other_id)
        for other_id in sorted(_strong_relationship_ids(state, agent, config)):
            if other_id not in candidate_ids:
                candidate_ids.append(other_id)
        cohort_ids = [
            other_id
            for other_id in candidate_ids
            if other_id != agent.agent_id and (
                _recent_interaction_count(agent, other_id) >= 2 or other_id in _strong_relationship_ids(state, agent, config)
            )
        ][:max_cohort_ids]
        memory["cohort_ids"] = cohort_ids
        fresh_tasks: list[dict[str, Any]] = []
        for raw_task in memory.get("active_long_tasks", []):
            if not isinstance(raw_task, dict):
                continue
            task = _sanitize_long_task(raw_task)
            age = round_index - _safe_int(task.get("last_updated_round", 0), 0)
            if age <= max(keep_recent + 2, _safe_int(task.get("expires_after_rounds", 3), 3) + 2):
                fresh_tasks.append(task)
        fresh_tasks.sort(
            key=lambda item: (
                -_safe_int(item.get("touch_count", 0), 0),
                -_safe_int(item.get("last_updated_round", 0), 0),
                item.get("title", ""),
            )
        )
        memory["active_long_tasks"] = fresh_tasks[:max_tasks]
        if fresh_tasks:
            lead_task = fresh_tasks[0]
            memory["current_focus"] = _limit_text(
                lead_task.get("next_step", "") or lead_task.get("title", "") or agent.public_state.get("activity_directive", ""),
                180,
            )
        elif recent_rounds:
            latest = recent_rounds[-1]
            memory["current_focus"] = _limit_text(
                f"Follow up after {latest.get('story_verb', 'the recent interaction')} with {latest.get('other_agent_name', latest.get('other_agent_id', 'someone'))}.",
                180,
            )
        else:
            memory["current_focus"] = _limit_text(
                agent.public_state.get("activity_directive", "") or memory.get("mainline_summary", ""),
                180,
            )
        notable_contacts = [
            agent_lookup[other_id].display_name
            for other_id in cohort_ids
            if other_id in agent_lookup
        ]
        task_titles = [task.get("title", "") for task in fresh_tasks[:2] if str(task.get("title", "")).strip()]
        archived_round_count = _safe_int(memory.get("archived_round_count", 0), 0)
        summary_parts = [
            _limit_text(agent.public_state.get("activity_directive", ""), 120),
            f"focus {memory.get('current_focus', '')}" if memory.get("current_focus", "") else "",
            f"threads {', '.join(task_titles)}" if task_titles else "",
            f"circle {', '.join(notable_contacts[:3])}" if notable_contacts else "",
            f"archived {archived_round_count} older rounds" if archived_round_count > 0 else "",
        ]
        memory["mainline_summary"] = _limit_text("; ".join(part for part in summary_parts if part), 220)
        memory["location_awareness"] = _location_awareness_payload(state, agent, config)
        _set_runtime_memory(agent, memory)


def _rebuild_runtime_memories_from_history(
    state: AgentStateBundleSpec,
    *,
    config: dict[str, Any],
    stories: list[dict[str, Any]],
    image_jobs: list[dict[str, Any]],
    extra_world_events: list[dict[str, Any]],
    completed_round: int,
) -> None:
    for agent in state.agents:
        _set_runtime_memory(agent, _initialize_runtime_memory(agent, config))
    stories_by_round: dict[int, list[dict[str, Any]]] = {}
    for story in stories:
        if not isinstance(story, dict):
            continue
        round_index = _safe_int(story.get("round_index", 0), 0)
        if round_index > 0:
            stories_by_round.setdefault(round_index, []).append(dict(story))
    events_by_round: dict[int, list[dict[str, Any]]] = {}
    for event in extra_world_events:
        if not isinstance(event, dict):
            continue
        round_index = _safe_int(event.get("round_index", 0), 0)
        if round_index > 0:
            events_by_round.setdefault(round_index, []).append(dict(event))
    image_jobs_by_round: dict[int, list[dict[str, Any]]] = {}
    for job in image_jobs:
        if not isinstance(job, dict):
            continue
        round_index = _safe_int(job.get("round_index", 0), 0)
        if round_index > 0:
            image_jobs_by_round.setdefault(round_index, []).append(dict(job))
    for round_index in range(1, max(0, completed_round) + 1):
        _update_agent_runtime_memory(
            state,
            config=config,
            round_index=round_index,
            round_stories=stories_by_round.get(round_index, []),
            round_extra_world_events=events_by_round.get(round_index, []),
            round_image_jobs=image_jobs_by_round.get(round_index, []),
        )


