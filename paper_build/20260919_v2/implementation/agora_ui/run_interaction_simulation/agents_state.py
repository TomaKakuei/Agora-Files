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





def _normalize_frontend_agent(
    agent: dict[str, Any],
    *,
    run_id: str,
    image_cache: dict[str, str],
) -> dict[str, Any]:
    public_state = agent.get("public_state", {})
    runtime_memory = public_state.get("runtime_memory", {}) if isinstance(public_state, dict) else {}
    object_images: list[dict[str, Any]] = []
    for raw_item in agent.get("inventory", []) or []:
        if not isinstance(raw_item, dict):
            continue
        image_path = str(raw_item.get("image_path", "")).strip()
        image_url = _mirror_runtime_image(image_path, run_id=run_id, image_cache=image_cache)
        if not image_url:
            continue
        metadata = raw_item.get("metadata", {}) if isinstance(raw_item.get("metadata", {}), dict) else {}
        object_images.append(
            {
                "label": str(metadata.get("name", raw_item.get("description", raw_item.get("item_id", "Object")))).strip(),
                "item_id": str(raw_item.get("item_id", "")).strip(),
                "description": str(raw_item.get("description", "")).strip(),
                "image_url": image_url,
                "source_path": image_path,
            }
        )

    artifact_images: list[dict[str, Any]] = []
    for raw_artifact in runtime_memory.get("visual_artifacts", []) or []:
        if not isinstance(raw_artifact, dict):
            continue
        image_path = str(raw_artifact.get("image_path", "")).strip()
        image_url = _mirror_runtime_image(image_path, run_id=run_id, image_cache=image_cache)
        if not image_url:
            continue
        reasoning_image_path = str(raw_artifact.get("reasoning_image_path", "")).strip()
        artifact_images.append(
            {
                "label": str(raw_artifact.get("artifact_label", raw_artifact.get("item_id", "Artifact"))).strip(),
                "item_id": str(raw_artifact.get("item_id", "")).strip(),
                "image_url": image_url,
                "source_path": image_path,
                "reasoning_image_url": (
                    _mirror_runtime_image(reasoning_image_path, run_id=run_id, image_cache=image_cache)
                    if reasoning_image_path
                    else ""
                ),
            }
        )

    return {
        "agent_id": str(agent.get("agent_id", "")).strip(),
        "display_name": str(agent.get("display_name", agent.get("agent_id", "Agent"))).strip(),
        "room_id": str(agent.get("room_id", public_state.get("home_room_id", "unknown"))).strip(),
        "coordinates": agent.get("coordinates", {}),
        "main_character": bool(agent.get("main_character", public_state.get("main_character", False))),
        "role_name": str(agent.get("role_name", public_state.get("role_name", "Agent"))).strip(),
        "activity_directive": str(agent.get("activity_directive", public_state.get("activity_directive", ""))).strip(),
        "appearance_prompt": str(agent.get("appearance_prompt", "")).strip(),
        "current_focus": str(runtime_memory.get("current_focus", "")).strip(),
        "mainline_summary": str(runtime_memory.get("mainline_summary", "")).strip(),
        "object_images": object_images,
        "artifact_images": artifact_images,
    }


def _publish_frontend_state(
    *,
    run_id: str,
    run_dir: Path,
    config: dict[str, Any],
    scenario_dir: Path,
    state_payload: dict[str, Any],
    status: str,
    round_index: int,
) -> None:
    frontend_dir = SCRIPT_DIR / "frontend"
    map_grid_path = scenario_dir / "map_grid.json"
    frontend_config = config.get("pixel_asset_pipeline", {}).get("frontend", {})
    frontend_world_config_path = run_dir / "frontend_world_config.json"
    dump_json(frontend_world_config_path, config)
    image_cache: dict[str, str] = {}
    agents = [
        _normalize_frontend_agent(agent, run_id=run_id, image_cache=image_cache)
        for agent in state_payload.get("agents", [])
        if isinstance(agent, dict)
    ]
    frontend_state = {
        "updated_at": _now_iso(),
        "run_id": run_id,
        "status": status,
        "round_index": int(round_index),
        "world_name": str(config.get("scenario_meta", {}).get("world_name", "Agora World")),
        "agent_count": len(agents),
        "map_grid_url": _browser_relative_url(frontend_dir, map_grid_path),
        "world_config_url": _browser_relative_url(frontend_dir, frontend_world_config_path),
        "asset_feed_url": str(frontend_config.get("event_feed_path", "./assets/generated/events/latest.json")),
        "bootstrap_feed_url": str(frontend_config.get("bootstrap_feed_path", "./assets/generated/events/bootstrap_assets.json")),
        "poll_interval_ms": int(frontend_config.get("poll_interval_ms", 3000)),
        "agents": agents,
    }
    frontend_state_path = run_dir / "frontend_state.json"
    dump_json(frontend_state_path, frontend_state)
    latest_pointer = {
        "updated_at": frontend_state["updated_at"],
        "run_id": run_id,
        "status": status,
        "round_index": int(round_index),
        "state_url": _browser_relative_url(frontend_dir, frontend_state_path),
    }
    dump_json(SCRIPT_DIR / "output" / "replay_runs" / "latest_frontend_state.json", latest_pointer)


def _weighted_choice(rng: random.Random, items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        raise ValueError("weighted choice requires at least one item")
    total = sum(max(0.0, float(item.get("weight", 1))) for item in items)
    if total <= 0:
        return dict(items[rng.randrange(len(items))])
    threshold = rng.random() * total
    running = 0.0
    for item in items:
        running += max(0.0, float(item.get("weight", 1)))
        if running >= threshold:
            return dict(item)
    return dict(items[-1])


def _load_agent_state(scenario_dir: Path, config: dict[str, Any]) -> AgentStateBundleSpec:
    agents_dir = scenario_dir / "Agents"
    agents: list[AgentRuntimeProfileSpec] = []
    for path in sorted(agents_dir.glob("*.json")):
        agents.append(AgentRuntimeProfileSpec.model_validate(load_jsonc_path(path)))
    relationships: dict[str, dict[str, RelationshipVectorSpec]] = {}
    for source in agents:
        relationships[source.agent_id] = {}
        for target in agents:
            if source.agent_id != target.agent_id:
                relationships[source.agent_id][target.agent_id] = RelationshipVectorSpec()
    return AgentStateBundleSpec(agents=agents, relationship_tensor=relationships, localized_visual_state={})


def _agent_map(state: AgentStateBundleSpec) -> dict[str, AgentRuntimeProfileSpec]:
    return {agent.agent_id: agent for agent in state.agents}


def _legal_targets(
    actor: AgentRuntimeProfileSpec,
    state: AgentStateBundleSpec,
    config: dict[str, Any],
) -> list[AgentRuntimeProfileSpec]:
    targeting = config.get("space", {}).get("targeting", {})
    selection = config.get("actions", {}).get("target_selection", {})
    prefer_same_room = bool(selection.get("prefer_same_room", targeting.get("prefer_same_room", True)))
    max_distance = int(selection.get("max_range_steps", targeting.get("max_range_steps", 3)))
    peers = [agent for agent in state.agents if agent.agent_id != actor.agent_id]
    nearby = [
        agent
        for agent in peers
        if (_walkable_distance_config(actor.coordinates, agent.coordinates, config, max_steps=max_distance) is not None)
    ]
    if not prefer_same_room or not actor.room_id:
        return nearby
    same_room = [agent for agent in nearby if agent.room_id == actor.room_id]
    other_rooms = [agent for agent in nearby if agent.room_id != actor.room_id]
    return same_room + other_rooms


def _status_names(agent: AgentRuntimeProfileSpec) -> set[str]:
    return {str(effect.effect) for effect in agent.status_effects if str(effect.effect).strip()}


def _inventory_item_ids(agent: AgentRuntimeProfileSpec) -> set[str]:
    return {
        str(item.item_id).strip()
        for item in agent.inventory
        if str(item.item_id).strip() and int(item.quantity) > 0
    }


def _route_status_values(route: dict[str, Any], *keys: str) -> set[str]:
    values: set[str] = set()
    for key in keys:
        raw = route.get(key, [])
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, list):
            values.update(str(item).strip() for item in raw if str(item).strip())
    return values


def _matches_any_status(agent: AgentRuntimeProfileSpec, values: set[str]) -> bool:
    return not values or bool(_status_names(agent) & values)


def _route_allowed_for_status(
    route: dict[str, Any],
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
) -> bool:
    actor_required = _route_status_values(route, "requires_actor_status", "requires_actor_status_any")
    target_required = _route_status_values(route, "requires_target_status", "requires_target_status_any")
    actor_suppressed = _route_status_values(route, "suppress_if_actor_status", "suppress_if_actor_status_any")
    target_suppressed = _route_status_values(route, "suppress_if_target_status", "suppress_if_target_status_any")
    if not _matches_any_status(actor, actor_required):
        return False
    if not _matches_any_status(target, target_required):
        return False
    if actor_suppressed and _status_names(actor) & actor_suppressed:
        return False
    if target_suppressed and _status_names(target) & target_suppressed:
        return False
    return True


def _route_allowed_for_inventory(
    route: dict[str, Any],
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
) -> bool:
    actor_items = _inventory_item_ids(actor)
    target_items = _inventory_item_ids(target)

    def _values(key: str) -> set[str]:
        raw = route.get(key, [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return set()
        return {str(item).strip() for item in raw if str(item).strip()}

    actor_required_all = _values("requires_actor_item_ids")
    target_required_all = _values("requires_target_item_ids")
    actor_required_any = _values("requires_actor_item_ids_any")
    target_required_any = _values("requires_target_item_ids_any")

    if actor_required_all and not actor_required_all.issubset(actor_items):
        return False
    if target_required_all and not target_required_all.issubset(target_items):
        return False
    if actor_required_any and not (actor_items & actor_required_any):
        return False
    if target_required_any and not (target_items & target_required_any):
        return False
    return True


def _filter_routes_for_context(
    routes: list[dict[str, Any]],
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
) -> list[dict[str, Any]]:
    filtered = [
        dict(route)
        for route in routes
        if (
            isinstance(route, dict)
            and _route_allowed_for_status(route, actor, target)
            and _route_allowed_for_inventory(route, actor, target)
        )
    ]
    return filtered or [dict(route) for route in routes if isinstance(route, dict)]


def _role_id(agent: AgentRuntimeProfileSpec) -> str:
    return str(agent.public_state.get("role_id", "")).strip()


def _is_main_character_agent(agent: AgentRuntimeProfileSpec) -> bool:
    return bool(agent.public_state.get("main_character", False))


def _rule_matches_agent(rule: dict[str, Any], agent: AgentRuntimeProfileSpec, *, prefix: str) -> bool:
    role_ids = rule.get(f"{prefix}_role_ids", [])
    if isinstance(role_ids, str):
        role_ids = [role_ids]
    if isinstance(role_ids, list) and role_ids:
        if _role_id(agent) not in {str(item).strip() for item in role_ids}:
            return False
    statuses = rule.get(f"{prefix}_status_any", rule.get(f"{prefix}_status", []))
    if isinstance(statuses, str):
        statuses = [statuses]
    if isinstance(statuses, list) and statuses:
        if not (_status_names(agent) & {str(item).strip() for item in statuses}):
            return False
    return True


def _target_weight(
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    state: AgentStateBundleSpec,
    config: dict[str, Any],
) -> float:
    selection = config.get("actions", {}).get("target_selection", {})
    if not isinstance(selection, dict) or not bool(selection.get("enabled", False)):
        return 1.0
    weight = float(selection.get("base_weight", 1.0))
    for rule in selection.get("status_weights", []) or []:
        if not isinstance(rule, dict):
            continue
        if not _rule_matches_agent(rule, actor, prefix="actor"):
            continue
        if not _rule_matches_agent(rule, target, prefix="target"):
            continue
        weight += float(rule.get("weight", 0.0))
    relationship = state.relationship_tensor.get(actor.agent_id, {}).get(target.agent_id)
    if relationship is not None:
        weight += max(0.0, float(relationship.trust - 50)) * float(selection.get("trust_above_neutral_weight", 0.0))
        weight += max(0.0, float(relationship.affection - 50)) * float(selection.get("affection_above_neutral_weight", 0.0))
        weight += max(0.0, float(relationship.influence_fear)) * float(selection.get("influence_fear_weight", 0.0))
    recent_interaction_bonus = float(selection.get("recent_interaction_bonus", 0.45))
    repeat_soft_cap = max(1, _safe_int(selection.get("repeat_interaction_soft_cap", 4), 4))
    weight += min(_recent_interaction_count(actor, target.agent_id), repeat_soft_cap) * recent_interaction_bonus
    cohort_ids = {str(item) for item in _runtime_memory(actor).get("cohort_ids", []) if str(item).strip()}
    if target.agent_id in cohort_ids:
        weight *= max(1.0, float(selection.get("cohort_weight", 1.4)))
    shared_task_count = len(_shared_task_thread_ids(actor, target))
    if shared_task_count > 0:
        shared_task_weight = max(1.0, float(selection.get("shared_task_weight", 1.35)))
        weight *= shared_task_weight + min(0.3, 0.1 * max(0, shared_task_count - 1))
    actor_location_awareness = _runtime_memory(actor).get("location_awareness", {})
    if isinstance(actor_location_awareness, dict):
        related_agents = actor_location_awareness.get("related_agents", [])
        if isinstance(related_agents, list) and any(
            isinstance(item, dict) and str(item.get("agent_id", "")) == target.agent_id
            for item in related_agents
        ):
            weight *= max(1.0, float(selection.get("related_presence_weight", 1.15)))
    distance_steps = (
        _walkable_distance_config(actor.coordinates, target.coordinates, config)
        or _distance(actor.coordinates, target.coordinates)
    )
    same_room_weight = float(selection.get("same_room_weight", 2.25 if actor.room_id else 1.0))
    other_room_weight = float(selection.get("other_room_weight", 1.0))
    if actor.room_id and target.room_id == actor.room_id:
        weight *= max(0.1, same_room_weight)
    else:
        weight *= max(0.1, other_room_weight)
    distance_penalty_per_step = float(selection.get("distance_penalty_per_step", 0.12))
    if distance_steps > 0:
        weight *= max(0.2, 1.0 - distance_penalty_per_step * distance_steps)
    return max(0.0, weight)


def _pick_target(
    rng: random.Random,
    actor: AgentRuntimeProfileSpec,
    state: AgentStateBundleSpec,
    config: dict[str, Any],
    *,
    round_index: int,
    prefer_same_room_only: bool = False,
) -> AgentRuntimeProfileSpec | None:
    targets = _legal_targets(actor, state, config)
    if not targets:
        return None
    forced_follow_up = _active_artist_feedback_follow_up(actor, round_index=round_index)
    if forced_follow_up is not None:
        target_by_id = {target.agent_id: target for target in targets}
        forced_target = target_by_id.get(str(forced_follow_up.get("target_agent_id", "")))
        if forced_target is not None:
            return forced_target
    if prefer_same_room_only and actor.room_id:
        same_room_targets = [target for target in targets if target.room_id == actor.room_id]
        if same_room_targets:
            targets = same_room_targets
    weights = [_target_weight(actor, target, state, config) for target in targets]
    total = sum(weights)
    if total <= 0:
        return targets[rng.randrange(len(targets))]
    threshold = rng.random() * total
    running = 0.0
    for target, weight in zip(targets, weights):
        running += weight
        if running >= threshold:
            return target
    return targets[-1]

__all__ = ['_normalize_frontend_agent', '_publish_frontend_state', '_weighted_choice', '_load_agent_state', '_agent_map', '_legal_targets', '_status_names', '_inventory_item_ids', '_route_status_values', '_matches_any_status', '_route_allowed_for_status', '_route_allowed_for_inventory', '_filter_routes_for_context', '_role_id', '_is_main_character_agent', '_rule_matches_agent', '_target_weight', '_pick_target']
