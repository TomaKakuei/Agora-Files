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
from .intent_schemas import *
from .intent_builders import *





SCRIPT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_ENV = "AGORA_SIM_CONFIG"
DEFAULT_PY_BIN = Path(sys.executable)



def _build_intents_for_request(
    *,
    rng: random.Random,
    round_index: int,
    serial: int,
    state: AgentStateBundleSpec,
    actor: AgentRuntimeProfileSpec,
    target: AgentRuntimeProfileSpec,
    request: dict[str, Any],
    config: dict[str, Any],
    longlive: LongLiveTwoPromptGenerator,
    run_dir: Path,
    seed: int,
    disable_longlive: bool,
    disable_images: bool,
    video_prompt_client: VertexJsonClient | None,
    image_prompt_client: VertexJsonClient | None,
    image_client: VertexSDKImageClient | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    routes = _route_lookup(config)
    route = routes.get(str(request.get("route_id", "")), dict(request))
    if isinstance(request, dict):
        route = {
            **route,
            "selection_reason": str(request.get("reason", route.get("selection_reason", "")))[:300],
        }
    kind = str(route.get("kind", request.get("kind", "custom")))
    video_jobs: list[dict[str, Any]] = []
    image_jobs: list[dict[str, Any]] = []
    story = {
        "round_index": round_index,
        "actor_id": actor.agent_id,
        "actor_name": actor.display_name,
        "actor_room_id": actor.room_id,
        "actor_coordinate": actor.coordinates.model_dump(),
        "target_id": target.agent_id,
        "target_name": target.display_name,
        "target_room_id": target.room_id,
        "target_coordinate": target.coordinates.model_dump(),
        "same_room": bool(actor.room_id and actor.room_id == target.room_id),
        "distance": _walkable_distance_config(actor.coordinates, target.coordinates, config) or _distance(actor.coordinates, target.coordinates),
        "route_id": str(route.get("route_id", "")),
        "kind": kind,
        "story_verb": str(route.get("story_verb", kind)),
        "longlive_status": "",
        "image_status": "",
        "selection_reason": str(route.get("selection_reason", "")),
        "shared_task_threads": _shared_task_thread_ids(actor, target),
        "actor_focus": _limit_text(_runtime_memory(actor).get("current_focus", ""), 140),
        "target_focus": _limit_text(_runtime_memory(target).get("current_focus", ""), 140),
    }
    shared_action_core = _normalize_shared_action_core(
        request.get("shared_action_core", {}),
        actor=actor,
        target=target,
        route=route,
        selection_reason=str(route.get("selection_reason", request.get("reason", ""))),
    )
    story["shared_action_core"] = shared_action_core
    story["shared_action_label"] = shared_action_core.get("shared_action_label", "")
    story["shared_action_alignment"] = shared_action_core.get("json_action_alignment", "")
    story["main_character_recording_note"] = shared_action_core.get("main_character_recording_note", "")
    relationship_metadata: dict[str, Any] = {}
    if kind in {"custom", "item_trade", "cinematic"} and isinstance(request.get("relationship_adjustments"), list):
        relationship_metadata = {
            "relationship_adjustments_mode": "model",
            "relationship_adjustment_source": "vertex_api_merged_interaction_routing",
            "actor_relationship_instruction": str(request.get("actor_relationship_instruction", ""))[:200],
            "target_relationship_instruction": str(request.get("target_relationship_instruction", ""))[:200],
            "relationship_adjustments": _normalize_relationship_adjustments(request, actor=actor, target=target),
        }
        story["relationship_adjustments"] = relationship_metadata.get("relationship_adjustments", [])
    if kind == "item_trade":
        if actor.room_id != target.room_id:
            move_route = _first_move_route(config) or {"route_id": "move_to_task", "kind": "move", "story_verb": "moved toward"}
            move_intent = _build_move_intent(
                rng=rng,
                round_index=round_index,
                serial=serial,
                actor=actor,
                route=move_route,
                config=config,
                target_agent=target,
            )
            if move_intent is not None:
                story["planned_route_id"] = story["route_id"]
                story["route_id"] = str(move_route.get("route_id", "move_to_task"))
                story["kind"] = "move"
                story["story_verb"] = f"moved toward {target.display_name}"
                story["selection_reason"] = (
                    f"{story.get('selection_reason', '')} proximity required before trade"
                ).strip()
                return [move_intent], video_jobs, image_jobs, story
            story["movement_status"] = "blocked_no_reachable_destination"
            story["intent_count"] = 0
            return [], video_jobs, image_jobs, story
        intents = _build_trade_intents(
            round_index=round_index,
            serial=serial,
            buyer=actor,
            seller=target,
            route=route,
            config=config,
        )
        _attach_relationship_metadata_once(intents, relationship_metadata)
        if intents:
            metadata = intents[0].get("metadata", {})
            if isinstance(metadata, dict) and str(metadata.get("story_verb", "")).strip():
                story["story_verb"] = str(metadata.get("story_verb", "")).strip()
        story["intent_count"] = len(intents)
        return intents, video_jobs, image_jobs, story
    if kind == "move":
        intent = _build_move_intent(
            rng=rng,
            round_index=round_index,
            serial=serial,
            actor=actor,
            route=route,
            config=config,
            target_agent=target,
        )
        if intent is None:
            story["movement_status"] = "blocked_no_reachable_destination"
            story["intent_count"] = 0
            return [], video_jobs, image_jobs, story
        return [intent], video_jobs, image_jobs, story
    if kind in {"custom", "cinematic"} and actor.room_id != target.room_id:
        move_route = _first_move_route(config) or {"route_id": "move_to_task", "kind": "move", "story_verb": "moved toward"}
        move_intent = _build_move_intent(
            rng=rng,
            round_index=round_index,
            serial=serial,
            actor=actor,
            route=move_route,
            config=config,
            target_agent=target,
        )
        if move_intent is not None:
            story["planned_route_id"] = story["route_id"]
            story["route_id"] = str(move_route.get("route_id", "move_to_task"))
            story["kind"] = "move"
            story["story_verb"] = f"moved toward {target.display_name}"
            story["selection_reason"] = (
                f"{story.get('selection_reason', '')} proximity required before interaction"
            ).strip()
            return [move_intent], video_jobs, image_jobs, story
        story["movement_status"] = "blocked_no_reachable_destination"
        story["intent_count"] = 0
        return [], video_jobs, image_jobs, story
    if kind == "cinematic":
        prompt_source = "vertex_api"
        safety_notes = ""
        if video_prompt_client is None:
            raise RuntimeError("video prompt client is required for cinematic routes")
        generated_prompts = _vertex_video_prompts(
            video_prompt_client,
            state=state,
            actor=actor,
            target=target,
            route=route,
            config=config,
            round_index=round_index,
            shared_action_core=shared_action_core,
        )
        actor_prompt = generated_prompts["actor_video_prompt"]
        target_prompt = generated_prompts["target_continuation_prompt"]
        safety_notes = generated_prompts.get("safety_notes", "")
        job_id = f"r{round_index:03d}_{serial:04d}_{actor.agent_id}_{target.agent_id}"
        job = longlive.run(
            prompts=[actor_prompt, target_prompt],
            job_id=job_id,
            seed=seed + round_index * 1000 + serial,
            disabled=disable_longlive,
        )
        video_jobs.append(
            {
                **job,
                "round_index": round_index,
                "actor_id": actor.agent_id,
                "target_id": target.agent_id,
                "actor_prompt": actor_prompt,
                "target_continuation_prompt": target_prompt,
                "prompt_source": prompt_source,
                "safety_notes": safety_notes,
                "shared_action_core": shared_action_core,
                "prompt_schedule_seconds": [0, int(config.get("longlive", {}).get("segment_seconds", 10))],
            }
        )
        story["longlive_status"] = str(job.get("status", ""))
        intent = _build_custom_intent(
            round_index=round_index,
            serial=serial,
            actor=actor,
            target=target,
            route=route,
            metadata={
                "requires_longlive": True,
                "participants": [actor.agent_id, target.agent_id],
                "actor_video_prompt": actor_prompt,
                "target_continuation_prompt": target_prompt,
                "prompt_source": prompt_source,
                "safety_notes": safety_notes,
                "prompt_schedule_seconds": [0, int(config.get("longlive", {}).get("segment_seconds", 10))],
                "shared_action_core": shared_action_core,
                "longlive_job": job,
                **relationship_metadata,
            },
        )
        return [intent], video_jobs, image_jobs, story

    if kind == "image":
        reason = str(request.get("reason", route.get("image_reason", "agent requested still image artifact")))
        prompt_source = "json_template"
        safety_notes = ""
        artifact_label = str(route.get("image_subject", route.get("route_id", "image_artifact")))
        source_owner, source_artifact = _select_route_source_artifact(
            actor=actor,
            target=target,
            route=route,
            config=config,
        )
        require_source_artifact = bool(route.get("require_source_artifact", False))
        if image_prompt_client is not None:
            generated_image_prompt = _vertex_still_image_prompt(
                image_prompt_client,
                actor=actor,
                target=target,
                route=route,
                config=config,
                reason=reason,
                source_owner=source_owner,
                source_artifact=source_artifact,
            )
            image_prompt = generated_image_prompt["image_prompt"]
            artifact_label = generated_image_prompt.get("artifact_label", artifact_label)
            safety_notes = generated_image_prompt.get("safety_notes", "")
            prompt_source = "vertex_api"
        else:
            image_prompt = _image_prompt_from_route(actor, target, route, config)
        job_id = f"r{round_index:03d}_{serial:04d}_{actor.agent_id}_{target.agent_id}_image"
        job_dir = run_dir / str(_image_generation_config(config).get("output_subdir", "image_jobs")) / job_id
        image_record = {
            "job_id": job_id,
            "round_index": round_index,
            "actor_id": actor.agent_id,
            "target_id": target.agent_id,
            "route_id": str(route.get("route_id", "")),
            "status": "disabled" if disable_images else "pending",
            "prompt": image_prompt,
            "prompt_source": prompt_source,
            "artifact_label": artifact_label,
            "safety_notes": safety_notes,
            "job_dir": str(job_dir),
            "image_path": "",
            "image_mime_type": "",
            "operation": "edit" if source_artifact is not None else str(route.get("image_operation", "create") or "create"),
            "source_owner_agent_id": source_owner.agent_id if source_owner is not None else "",
            "source_owner_display_name": source_owner.display_name if source_owner is not None else "",
            "source_item_id": str(source_artifact.get("item_id", "")) if isinstance(source_artifact, dict) else "",
            "source_artifact_label": str(source_artifact.get("artifact_label", "")) if isinstance(source_artifact, dict) else "",
            "source_image_path": str(source_artifact.get("image_path", "")) if isinstance(source_artifact, dict) else "",
        }
        if disable_images:
            pass
        elif require_source_artifact and (source_artifact is None or not str(source_artifact.get("image_path", "")).strip()):
            image_record["status"] = "skipped_no_source_artifact"
        elif image_client is None:
            image_record["status"] = "skipped_no_image_client"
        else:
            try:
                generated = image_client.generate_image(
                    prompt=image_prompt,
                    job_dir=job_dir,
                    filename_stem="artifact",
                    source_image_path=(
                        Path(str(source_artifact.get("image_path", "")).strip())
                        if isinstance(source_artifact, dict) and str(source_artifact.get("image_path", "")).strip()
                        else None
                    ),
                )
                image_record.update(generated)
                if (
                    str(image_record.get("status", "")) == "ok"
                    and source_owner is not None
                    and str(image_record.get("source_item_id", "")).strip()
                ):
                    _replace_inventory_item_image(
                        source_owner,
                        item_id=str(image_record.get("source_item_id", "")),
                        image_path=str(image_record.get("image_path", "")),
                        artifact_label=str(image_record.get("artifact_label", "")),
                    )
            except Exception as exc:
                image_record["status"] = "failed"
                image_record["error"] = str(exc)[:500]
        image_jobs.append(image_record)
        story["image_status"] = str(image_record.get("status", ""))
        story["image_job_id"] = job_id
        story["image_path"] = str(image_record.get("image_path", ""))
        intent = _build_image_intent(
            round_index=round_index,
            serial=serial,
            actor=actor,
            target=target,
            route=route,
            image_prompt=image_prompt,
            image_record=image_record,
            reason=reason,
            metadata=relationship_metadata,
        )
        return [intent], video_jobs, image_jobs, story

    if str(route.get("route_id", "")) == "revise_description_after_feedback":
        reason = str(request.get("reason", route.get("selection_reason", "text-only artwork revision after critique")))
        source_item = _find_inventory_item_by_id(actor, "signature_artwork")
        text_revision = {
            "artifact_label": "",
            "revised_description": "",
            "revision_summary": "",
        }
        if source_item is not None and image_prompt_client is not None:
            try:
                text_revision = _vertex_text_revision(
                    image_prompt_client,
                    actor=actor,
                    target=target,
                    route=route,
                    config=config,
                    reason=reason,
                    source_item=source_item,
                )
            except Exception as exc:
                text_revision["revision_summary"] = f"text revision fallback: {str(exc)[:80]}"
                text_revision["revised_description"] = _limit_text(source_item.description, 220)
                text_revision["artifact_label"] = _limit_text(
                    source_item.metadata.get("name", source_item.item_id),
                    80,
                )
        if source_item is not None and str(text_revision.get("revised_description", "")).strip():
            source_item.description = str(text_revision.get("revised_description", "")).strip()
            metadata = dict(source_item.metadata or {})
            revision_history = metadata.get("text_revision_history", [])
            if not isinstance(revision_history, list):
                revision_history = []
            revision_history.append(
                {
                    "round_index": round_index,
                    "target_agent_id": target.agent_id,
                    "target_name": target.display_name,
                    "description": source_item.description,
                    "summary": str(text_revision.get("revision_summary", "")).strip(),
                }
            )
            metadata["text_revision_history"] = revision_history[-6:]
            metadata["latest_text_revision_round"] = int(round_index)
            source_item.metadata = metadata
            memory = _runtime_memory(actor)
            textual_artifacts = [dict(item) for item in memory.get("textual_artifacts", []) if isinstance(item, dict)]
            textual_artifacts.insert(
                0,
                _sanitize_textual_artifact(
                    {
                        "kind": "text_revision",
                        "artifact_label": str(text_revision.get("artifact_label", source_item.item_id)),
                        "item_id": source_item.item_id,
                        "description": source_item.description,
                        "source": "text_revision_job",
                        "round_index": round_index,
                        "counterpart_agent_id": target.agent_id,
                        "counterpart_name": target.display_name,
                    }
                ),
            )
            deduped_textual: list[dict[str, Any]] = []
            seen_descriptions: set[str] = set()
            for artifact in textual_artifacts:
                key = str(artifact.get("description", "")).strip()
                if not key or key in seen_descriptions:
                    continue
                seen_descriptions.add(key)
                deduped_textual.append(artifact)
            memory["textual_artifacts"] = deduped_textual[:_memory_limit(config, "max_visual_artifacts", 4)]
            _set_runtime_memory(actor, memory)
            story["text_revision_status"] = "ok"
            story["text_revision_description"] = source_item.description
            story["text_revision_summary"] = str(text_revision.get("revision_summary", "")).strip()

    intent = _build_custom_intent(
        round_index=round_index,
        serial=serial,
        actor=actor,
        target=target,
        route=route,
        metadata={**relationship_metadata, "shared_action_core": shared_action_core},
    )
    return [intent], video_jobs, image_jobs, story


def _validate_target_legality(stories: list[dict[str, Any]], state_by_id: dict[str, AgentRuntimeProfileSpec], config: dict[str, Any]) -> dict[str, Any]:
    max_distance = int(config.get("space", {}).get("targeting", {}).get("max_range_steps", 3))
    invalid: list[dict[str, Any]] = []
    for story in stories:
        same_room = bool(story.get("same_room", False))
        in_range = int(story.get("distance", max_distance + 1)) <= max_distance
        if not same_room and not in_range:
            invalid.append(dict(story))
    return {"invalid_count": len(invalid), "invalid": invalid[:20]}


def _vertex_story_summary(
    client: VertexJsonClient,
    *,
    config: dict[str, Any],
    story_payload: dict[str, Any],
    video_jobs: list[dict[str, Any]],
    image_jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    schema = {
        "overall_story_summary": "string",
        "round_summaries": [
            {
                "round_index": "integer",
                "story_summary": "string",
                "key_trade_or_task": "string",
                "representative_interaction": "string",
            }
        ],
        "quest_and_trade_summary": "string",
        "video_prompt_chain_summary": "string",
        "image_artifact_summary": "string",
        "notable_video_jobs": [
            {
                "round_index": "integer",
                "actor_id": "string",
                "target_id": "string",
                "status": "string",
                "reason_to_use_longlive": "string",
            }
        ],
        "notable_image_jobs": [
            {
                "round_index": "integer",
                "actor_id": "string",
                "target_id": "string",
                "status": "string",
                "reason_to_use_image": "string",
            }
        ],
    }
    compact_story = {
        "scenario_meta": story_payload.get("scenario_meta", {}),
        "round_summaries": story_payload.get("round_summaries", []),
        "route_counts": story_payload.get("route_counts", {}),
        "longlive_counts": story_payload.get("longlive_counts", {}),
        "image_counts": story_payload.get("image_counts", {}),
        "target_legality": story_payload.get("target_legality", {}),
        "extra_world_events": story_payload.get("extra_world_events", [])[:120],
        "stories": story_payload.get("stories", [])[:240],
        "video_jobs": video_jobs[:40],
        "image_jobs": image_jobs[:40],
    }
    prompt = (
        f"Write the story summary for a completed simulation report for {_world_label(config)}.\n"
        "Focus on the configured world story, task momentum, trading economy when present, representative ordinary actions, "
        "representative LongLive video actions, prompt schedule, and artifact locations.\n"
        "Keep diagnostics short and appendix-level. Do not invent extra world rules.\n"
        f"Report language: {config.get('report', {}).get('language', 'English')}.\n"
        f"simulation_payload: {_json_dumps(compact_story)}"
    )
    return client.generate_json(
        system_instruction="You write JSON story summaries for simulation reports.",
        prompt=prompt,
        schema=schema,
        stage="story_report_generation",
    )


