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
from .core import SCRIPT_DIR
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





def _now_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _resolve(path_like: str | Path, *, base: Path = SCRIPT_DIR) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _browser_relative_url(base_dir: Path, target: Path) -> str:
    relative = os.path.relpath(str(target), str(base_dir)).replace(os.sep, "/")
    return relative if relative.startswith(".") else f"./{relative}"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _reuse_agent_profile_cache(
    cache_dir: Path,
    base_payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not cache_dir.is_dir():
        raise FileNotFoundError(f"agent profile cache dir not found: {cache_dir}")
    payloads: list[dict[str, Any]] = []
    missing: list[str] = []
    for base in base_payloads:
        agent_id = str(base.get("agent_id", "")).strip()
        cache_path = cache_dir / f"{agent_id}.json"
        if not cache_path.is_file():
            missing.append(agent_id)
            continue
        cached = load_jsonc_path(cache_path)
        runtime_agent = cached.get("runtime_agent") if isinstance(cached, dict) else None
        if not isinstance(runtime_agent, dict):
            raise ValueError(f"profile cache file lacks runtime_agent object: {cache_path}")
        if str(runtime_agent.get("agent_id", "")) != agent_id:
            raise ValueError(
                f"profile cache agent_id mismatch for {cache_path}: "
                f"expected {agent_id}, got {runtime_agent.get('agent_id')}"
            )
        payload = AgentRuntimeProfileSpec.model_validate(runtime_agent).model_dump()
        payloads.append(payload)
    if missing:
        raise FileNotFoundError(
            f"profile cache is missing {len(missing)} runtime agents: {', '.join(missing[:12])}"
        )
    if len(payloads) != len(base_payloads):
        raise ValueError(f"profile cache yielded {len(payloads)} agents, expected {len(base_payloads)}")
    print(f"[PROFILE_REUSE] loaded {len(payloads)} runtime agents from {cache_dir}", flush=True)
    return payloads


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except Exception as exc:
            raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
        if isinstance(record, dict):
            records.append(record)
    return records


def _load_resume_state(resume_run_dir: Path) -> dict[str, Any]:
    if not resume_run_dir.is_dir():
        raise FileNotFoundError(f"resume run dir not found: {resume_run_dir}")
    records = _load_jsonl(resume_run_dir / "timeline.jsonl")
    completed_records: list[dict[str, Any]] = []
    for record in records:
        round_index = int(record.get("round_index", record.get("summary", {}).get("round_index", 0)) or 0)
        if round_index <= 0:
            continue
        step_dir = resume_run_dir / f"timestep_{round_index:03d}"
        if (
            (step_dir / "updated_agent_profiles.json").is_file()
            and (step_dir / "updated_world_rules.json").is_file()
        ):
            completed_records.append(record)
    if not completed_records:
        return {
            "completed_round": 0,
            "timeline_records": [],
            "state": None,
            "world_rules": None,
            "stories": [],
            "video_jobs": [],
            "image_jobs": [],
            "round_summaries": [],
            "route_counts": Counter(),
            "longlive_counts": Counter(),
            "image_counts": Counter(),
        }
    completed_records.sort(key=lambda item: int(item.get("round_index", item.get("summary", {}).get("round_index", 0)) or 0))
    completed_round = int(completed_records[-1].get("round_index", completed_records[-1].get("summary", {}).get("round_index", 0)) or 0)
    timeline_records = [
        record
        for record in records
        if 0 < int(record.get("round_index", record.get("summary", {}).get("round_index", 0)) or 0) <= completed_round
    ]
    timeline_records.sort(key=lambda item: int(item.get("round_index", item.get("summary", {}).get("round_index", 0)) or 0))
    step_dir = resume_run_dir / f"timestep_{completed_round:03d}"
    state = AgentStateBundleSpec.model_validate(load_jsonc_path(step_dir / "updated_agent_profiles.json"))
    world_rules = adjudicator.WorldRulesSpec.model_validate(load_jsonc_path(step_dir / "updated_world_rules.json"))
    stories: list[dict[str, Any]] = []
    video_jobs: list[dict[str, Any]] = []
    image_jobs: list[dict[str, Any]] = []
    extra_world_events: list[dict[str, Any]] = []
    round_summaries: list[dict[str, Any]] = []
    route_counts: Counter[str] = Counter()
    longlive_counts: Counter[str] = Counter()
    image_counts: Counter[str] = Counter()
    for record in timeline_records:
        summary = record.get("summary", {})
        if isinstance(summary, dict):
            round_summaries.append(dict(summary))
        record_stories = [dict(item) for item in record.get("stories", []) if isinstance(item, dict)]
        stories.extend(record_stories)
        for story in record_stories:
            route_counts[str(story.get("route_id", story.get("kind", "")))] += 1
        record_video_jobs = [dict(item) for item in record.get("video_jobs", []) if isinstance(item, dict)]
        video_jobs.extend(record_video_jobs)
        for job in record_video_jobs:
            longlive_counts[str(job.get("status", ""))] += 1
        record_image_jobs = [dict(item) for item in record.get("image_jobs", []) if isinstance(item, dict)]
        image_jobs.extend(record_image_jobs)
        for job in record_image_jobs:
            image_counts[str(job.get("status", ""))] += 1
        extra_world_events.extend(
            dict(item) for item in record.get("extra_world_events", []) if isinstance(item, dict)
        )
    return {
        "completed_round": completed_round,
        "timeline_records": timeline_records,
        "state": state,
        "world_rules": world_rules,
        "stories": stories,
        "video_jobs": video_jobs,
        "image_jobs": image_jobs,
        "extra_world_events": extra_world_events,
        "round_summaries": round_summaries,
        "route_counts": route_counts,
        "longlive_counts": longlive_counts,
        "image_counts": image_counts,
    }

__all__ = ['_now_run_id', '_now_iso', '_resolve', '_json_dumps', '_browser_relative_url', '_safe_int', '_reuse_agent_profile_cache', '_load_jsonl', '_load_resume_state']
