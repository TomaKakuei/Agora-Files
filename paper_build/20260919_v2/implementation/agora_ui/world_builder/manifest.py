from __future__ import annotations
import argparse
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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

from .io_utils import *

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


def _drafts_root(package_root: Path) -> Path:
    return package_root / "output" / "world_creator_drafts"


def _revisions_root(package_root: Path, draft_id: str) -> Path:
    return _draft_dir(package_root, draft_id) / "revisions"


def _normalized_lookup(value: Any) -> str:
    return str(value or "").strip().lower()


def _cached_history_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    entries = manifest.get("history_cache", [])
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _build_revision_model(status: dict[str, Any]) -> WorldBuilderRevisionSpec:
    return WorldBuilderRevisionSpec(
        revision_id=str(status.get("revision_id", "")),
        created_at=str(status.get("created_at", "")),
        status=str(status.get("status", "")),
        world_name=str(status.get("world_name", "")),
        world_id=str(status.get("world_id", "")),
        summary_path=str(status.get("summary_path", "")),
        package_path=str(status.get("package_path", "")),
        package_validation=dict(status.get("package_validation", {})),
        startup_validation=dict(status.get("startup_validation", {})),
        structured_summary=WorldBuilderStructuredSummarySpec.model_validate(status.get("structured_summary", {})),
        compiler_critique=dict(status.get("compiler_critique", {})),
        compiled_preview=dict(status.get("compiled_preview", {})),
        error=str(status.get("error", "")),
    )


def _load_revision_status(package_root: Path, draft_id: str, revision_id: str) -> dict[str, Any]:
    path = _revision_status_path(package_root, draft_id, revision_id)
    if not path.is_file():
        raise FileNotFoundError(f"Revision status not found: {draft_id}/{revision_id}")
    return _read_json(path)


def _save_revision_status(package_root: Path, draft_id: str, revision_id: str, status: dict[str, Any]) -> None:
    status["updated_at"] = _now_iso()
    _write_json(_revision_status_path(package_root, draft_id, revision_id), status)


def _find_draft_match(
    package_root: Path,
    *,
    identifier: str = "",
    world_name: str = "",
    world_id: str = "",
) -> dict[str, Any] | None:
    normalized_identifier = _normalized_lookup(identifier)
    normalized_world_name = _normalized_lookup(world_name)
    normalized_world_id = _normalized_lookup(world_id)
    if not any((normalized_identifier, normalized_world_name, normalized_world_id)):
        return None
    index = _load_draft_index(package_root)
    draft_id = ""
    if normalized_identifier:
        draft_id = (
            str(index.get("draft_ids", {}).get(normalized_identifier, "")).strip()
            or str(index.get("world_names", {}).get(normalized_identifier, "")).strip()
            or str(index.get("world_ids", {}).get(normalized_identifier, "")).strip()
        )
    if not draft_id and normalized_world_name:
        draft_id = str(index.get("world_names", {}).get(normalized_world_name, "")).strip()
    if not draft_id and normalized_world_id:
        draft_id = str(index.get("world_ids", {}).get(normalized_world_id, "")).strip()
    if draft_id:
        try:
            return _load_manifest(package_root, draft_id)
        except FileNotFoundError:
            _rebuild_draft_index(package_root)
            return None
    return None


def _require_unique_world_identity(
    package_root: Path,
    *,
    world_name: str,
    world_id: str,
    exclude_draft_id: str = "",
) -> None:
    normalized_world_name = _normalized_lookup(world_name)
    normalized_world_id = _normalized_lookup(world_id)
    if not normalized_world_name:
        raise ValueError("world_name is required so the creator can resume this world later.")
    index = _load_draft_index(package_root)
    conflicting_name_draft_id = str(index.get("world_names", {}).get(normalized_world_name, "")).strip() if normalized_world_name else ""
    conflicting_world_id = str(index.get("world_ids", {}).get(normalized_world_id, "")).strip() if normalized_world_id else ""
    if conflicting_name_draft_id and conflicting_name_draft_id != exclude_draft_id:
        raise ValueError(
            f"World name '{world_name}' is already in use by draft {conflicting_name_draft_id}. "
            "Resume that world by world name or ID instead of creating a new one."
        )
    if conflicting_world_id and conflicting_world_id != exclude_draft_id:
        raise ValueError(
            f"World ID '{world_id}' is already in use by draft {conflicting_world_id}. "
            "Resume that world by world name or ID instead of creating a new one."
        )


def _scenario_relative_path(scenario_dir: Path, path_value: str) -> Path:
    candidate = Path(str(path_value or "").strip()).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (scenario_dir / candidate).resolve()


def _draft_index_path(package_root: Path) -> Path:
    return _drafts_root(package_root) / "draft_index.json"


def _draft_dir(package_root: Path, draft_id: str) -> Path:
    return _drafts_root(package_root) / draft_id


def _manifest_path(package_root: Path, draft_id: str) -> Path:
    return _draft_dir(package_root, draft_id) / "draft_manifest.json"


def _revision_dir(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revisions_root(package_root, draft_id) / revision_id


def _revision_status_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "status.json"


def _revision_input_brief_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "input_brief.txt"


def _revision_summary_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "world_summary.md"


def _revision_package_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "world_package.db"


def _revision_world_config_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "world_config.json"


def _revision_scenario_dir(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "scenario"


def _revision_builder_spec_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "builder_spec.json"


def _revision_planner_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "planner.json"


def _revision_rooms_spec_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "rooms_spec.json"


def _revision_items_spec_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "items_spec.json"


def _revision_agents_spec_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "agents_spec.json"


def _revision_pixel_frontend_spec_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "pixel_frontend_spec.json"


def _revision_compiler_report_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "compiler_report.json"


def _revision_compiler_critique_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "compiler_critique.json"


def _revision_art_runtime_dir(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "art_runtime"


def _revision_art_worker_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "art_worker.json"


def _revision_generation_worker_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "generation_worker.json"


def _revision_generation_request_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "generation_request.json"


def _revision_art_status_path(package_root: Path, draft_id: str, revision_id: str) -> Path:
    return _revision_dir(package_root, draft_id, revision_id) / "art_status.json"


def _load_manifest(package_root: Path, draft_id: str) -> dict[str, Any]:
    path = _manifest_path(package_root, draft_id)
    if not path.is_file():
        raise FileNotFoundError(f"Draft not found: {draft_id}")
    return _read_json(path)


def _save_manifest(package_root: Path, draft_id: str, manifest: dict[str, Any]) -> None:
    existing = _manifest_path(package_root, draft_id)
    previous_manifest = _read_json(existing) if existing.is_file() else None
    manifest["updated_at"] = _now_iso()
    _write_json(_manifest_path(package_root, draft_id), manifest)
    index = _load_draft_index(package_root)
    if previous_manifest:
        _remove_manifest_record_from_index(index, previous_manifest)
    _index_manifest_record(index, manifest)
    _save_draft_index(package_root, index)


def _cache_revision_in_manifest(manifest: dict[str, Any], status: dict[str, Any]) -> None:
    revision_id = str(status.get("revision_id", "")).strip()
    if not revision_id:
        return
    revision_ids = [str(value).strip() for value in manifest.get("revision_ids", []) if str(value).strip()]
    if revision_id not in revision_ids:
        revision_ids.append(revision_id)
    history_cache = [entry for entry in _cached_history_entries(manifest) if str(entry.get("revision_id", "")).strip() != revision_id]
    history_cache.append(dict(status))
    history_cache.sort(key=lambda entry: str(entry.get("revision_id", "")))
    manifest["revision_ids"] = revision_ids
    manifest["history_cache"] = history_cache
    manifest["current_revision_data"] = dict(status)
    manifest["world_summary_markdown"] = str(status.get("world_summary_markdown", manifest.get("world_summary_markdown", "")))


def _current_status_from_manifest(manifest: dict[str, Any], revision_id: str) -> dict[str, Any] | None:
    cached = manifest.get("current_revision_data", {})
    if isinstance(cached, dict) and str(cached.get("revision_id", "")).strip() == str(revision_id).strip():
        return dict(cached)
    for entry in _cached_history_entries(manifest):
        if str(entry.get("revision_id", "")).strip() == str(revision_id).strip():
            return dict(entry)
    return None


def _empty_draft_index() -> dict[str, Any]:
    return {
        "draft_ids": {},
        "world_names": {},
        "world_ids": {},
        "updated_at": _now_iso(),
    }


def _load_draft_index(package_root: Path) -> dict[str, Any]:
    path = _draft_index_path(package_root.resolve())
    if path.is_file():
        payload = _read_json(path)
        if isinstance(payload.get("draft_ids"), dict) and isinstance(payload.get("world_names"), dict) and isinstance(payload.get("world_ids"), dict):
            return payload
    return _rebuild_draft_index(package_root)


def _save_draft_index(package_root: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = _now_iso()
    _write_json(_draft_index_path(package_root.resolve()), payload)


def _rebuild_draft_index(package_root: Path) -> dict[str, Any]:
    index = _empty_draft_index()
    root = _drafts_root(package_root.resolve())
    if root.is_dir():
        for draft_dir in sorted(root.iterdir()):
            if not draft_dir.is_dir():
                continue
            manifest_path = draft_dir / "draft_manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = _read_json(manifest_path)
            except Exception:
                continue
            _index_manifest_record(index, manifest)
    _save_draft_index(package_root, index)
    return index


def _index_manifest_record(index: dict[str, Any], manifest: dict[str, Any]) -> None:
    draft_id = str(manifest.get("draft_id", "")).strip()
    if not draft_id:
        return
    index.setdefault("draft_ids", {})[_normalized_lookup(draft_id)] = draft_id
    world_name = str(manifest.get("world_name", "")).strip()
    if world_name:
        index.setdefault("world_names", {})[_normalized_lookup(world_name)] = draft_id
    world_id = str(manifest.get("world_id", "")).strip()
    if world_id:
        index.setdefault("world_ids", {})[_normalized_lookup(world_id)] = draft_id


def _remove_manifest_record_from_index(index: dict[str, Any], manifest: dict[str, Any]) -> None:
    draft_id = str(manifest.get("draft_id", "")).strip()
    if draft_id:
        index.setdefault("draft_ids", {}).pop(_normalized_lookup(draft_id), None)
    world_name = str(manifest.get("world_name", "")).strip()
    if world_name:
        index.setdefault("world_names", {}).pop(_normalized_lookup(world_name), None)
    world_id = str(manifest.get("world_id", "")).strip()
    if world_id:
        index.setdefault("world_ids", {}).pop(_normalized_lookup(world_id), None)


def _draft_manifest_records(package_root: Path) -> list[dict[str, Any]]:
    root = _drafts_root(package_root.resolve())
    if not root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for draft_dir in sorted(root.iterdir()):
        if not draft_dir.is_dir():
            continue
        manifest_path = draft_dir / "draft_manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = _read_json(manifest_path)
        except Exception:
            continue
        records.append(manifest)
    return records


def _room_spec_for_index(
    room_specs: list[dict[str, Any]],
    gameplay_loops: list[dict[str, Any]],
    index: int,
) -> dict[str, Any]:
    if index < len(room_specs):
        return dict(room_specs[index])
    loop = dict(_cycled_value(gameplay_loops, index, gameplay_loops[0] if gameplay_loops else {}))
    label = _first_non_empty(loop.get("label"), default=f"Loop {index + 1}")
    pressure = _first_non_empty(loop.get("pressure"), default="social pressure")
    summary = _first_non_empty(loop.get("summary"), default="support repeated interaction")
    return {
        "name": f"{label} Annex",
        "biome": pressure,
        "purpose": summary,
        "decor_tags": _dedupe_texts([label, pressure, "signals", "stations"], limit=5) or ["signals", "stations"],
        "activity_tags": _dedupe_texts(loop.get("roles", []), limit=4),
    }


def _revision_history(package_root: Path, draft_id: str, manifest: dict[str, Any] | None = None) -> list[WorldBuilderRevisionSpec]:
    active_manifest = manifest if isinstance(manifest, dict) else None
    cached_history = _cached_history_entries(active_manifest or {})
    if cached_history:
        return [_build_revision_model(entry) for entry in cached_history]
    history: list[WorldBuilderRevisionSpec] = []
    revisions_dir = _revisions_root(package_root, draft_id)
    if not revisions_dir.is_dir():
        return history
    for revision_dir in sorted(path for path in revisions_dir.iterdir() if path.is_dir()):
        status_path = revision_dir / "status.json"
        if not status_path.is_file():
            continue
        history.append(_build_revision_model(_read_json(status_path)))
    return history


def _publish_status_from_manifest(manifest: dict[str, Any]) -> WorldBuilderPublishStatusSpec:
    payload = dict(manifest.get("publish", {}))
    if payload:
        return WorldBuilderPublishStatusSpec.model_validate(payload)
    access_code = str(manifest.get("published_access_code", "")).strip()
    return WorldBuilderPublishStatusSpec(
        status=str(manifest.get("publish_status", STATUS_DRAFT_READY)),
        access_code=access_code,
        pixel_read=bool(access_code),
        world_url=(f"/pixel/?pixel_world={access_code}" if access_code else ""),
        package_db_url=(f"/api/packages/{access_code}/db" if access_code else ""),
        detail=("Published world ready." if access_code else "World has not been published yet."),
    )


def _revision_slug(draft_id: str, revision_id: str) -> str:
    return f"{draft_id}_{revision_id}"

__all__ = ['STATUS_DRAFT_GENERATING', 'STATUS_DRAFT_READY', 'STATUS_DRAFT_FAILED', 'STATUS_REVISION_GENERATING', 'STATUS_ART_QUEUED', 'STATUS_ART_RUNNING', 'STATUS_ART_FAILED', 'STATUS_ART_TIMEOUT_SKIPPED', 'STATUS_QA_FAILED_RETRYING', 'STATUS_PUBLISH_READY', 'STATUS_PUBLISHED', '_drafts_root', '_revisions_root', '_normalized_lookup', '_cached_history_entries', '_build_revision_model', '_load_revision_status', '_save_revision_status', '_find_draft_match', '_require_unique_world_identity', '_scenario_relative_path', '_draft_index_path', '_draft_dir', '_manifest_path', '_revision_dir', '_revision_status_path', '_revision_input_brief_path', '_revision_summary_path', '_revision_package_path', '_revision_world_config_path', '_revision_scenario_dir', '_revision_builder_spec_path', '_revision_planner_path', '_revision_rooms_spec_path', '_revision_items_spec_path', '_revision_agents_spec_path', '_revision_pixel_frontend_spec_path', '_revision_compiler_report_path', '_revision_compiler_critique_path', '_revision_art_runtime_dir', '_revision_art_worker_path', '_revision_generation_worker_path', '_revision_generation_request_path', '_revision_art_status_path', '_load_manifest', '_save_manifest', '_cache_revision_in_manifest', '_current_status_from_manifest', '_empty_draft_index', '_load_draft_index', '_save_draft_index', '_rebuild_draft_index', '_index_manifest_record', '_remove_manifest_record_from_index', '_draft_manifest_records', '_room_spec_for_index', '_revision_history', '_publish_status_from_manifest', '_revision_slug']
