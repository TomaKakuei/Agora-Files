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
    WorldBuilderGenerationStatusSpec,
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

GLOBAL_CREATOR_ENV_PATHS = (Path.home() / ".config" / "agora_ui_runtime.env",)




# Sub-modules imports
import inspect
from . import validation, art, generation, builder, generation_schemas, generation_prompts, critique_loop
for mod in (validation, art, generation, builder, generation_schemas, generation_prompts, critique_loop):
    for name, obj in inspect.getmembers(mod):
        if not name.startswith('__'):
            globals()[name] = obj



def _fallback_player_entry_points(builder_spec: dict[str, Any]) -> list[str]:
    world_name = str(builder_spec.get("world_name", "the world")).strip() or "the world"
    loops = [dict(entry) for entry in builder_spec.get("gameplay_loops", []) if isinstance(entry, dict)]
    primary_loop = dict(loops[0]) if loops else {}
    primary_label = _first_non_empty(primary_loop.get("label"), default="the central loop")
    pressure = _first_non_empty(primary_loop.get("pressure"), default="the world's main pressure point")
    return [
        f"Arrive in {world_name} as a newcomer who must understand {primary_label.lower()} before choosing allies.",
        f"Step into a live situation where {pressure} is already reshaping who trusts whom.",
        "Use conversation, movement, trade, and inspection to turn vague world lore into a concrete next move.",
    ]


def _fallback_conflict_hooks(builder_spec: dict[str, Any], focus_profile: dict[str, Any]) -> list[str]:
    base_hooks = [
        "Two groups want the same scarce opportunity but for incompatible reasons.",
        "Information is valuable enough that agents may delay, distort, or barter it.",
    ]
    if focus_profile.get("conflict"):
        base_hooks.append("A recent disruption has made routine coordination feel politically charged.")
    if focus_profile.get("exploration"):
        base_hooks.append("New territory or new evidence keeps reopening old assumptions.")
    return base_hooks[:4]


def _fallback_custom_actions(focus_profile: dict[str, Any]) -> list[str]:
    actions = ["Chat", "Inspect", "Coordinate", "Trade", "Move", "CinematicInteraction"]
    if focus_profile.get("economy"):
        actions.extend(["Negotiate", "Broker"])
    if focus_profile.get("exploration"):
        actions.extend(["ScoutReport", "Research"])
    if focus_profile.get("conflict") or focus_profile.get("story"):
        actions.extend(["Mediate", "Debate", "Warn"])
    if focus_profile.get("craft"):
        actions.extend(["Repair", "Build"])
    return _dedupe_texts(actions, limit=12)


def _next_revision_id(existing: list[str]) -> str:
    highest = 0
    for value in existing:
        text = str(value or "").strip().lower()
        if len(text) == 4 and text.startswith("r") and text[1:].isdigit():
            highest = max(highest, int(text[1:]))
    return f"r{highest + 1:03d}"




def _current_summary_text(package_root: Path, draft_id: str, revision_id: str, status: dict[str, Any] | None = None, manifest: dict[str, Any] | None = None) -> str:
    if isinstance(status, dict):
        cached = str(status.get("world_summary_markdown", "")).strip()
        if cached:
            return cached
    if isinstance(manifest, dict):
        cached_manifest_summary = str(manifest.get("world_summary_markdown", "")).strip()
        if cached_manifest_summary and str(manifest.get("current_revision", "")).strip() == str(revision_id).strip():
            return cached_manifest_summary
    path = _revision_summary_path(package_root, draft_id, revision_id)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _art_status_from_disk(package_root: Path, draft_id: str, revision_id: str, manifest: dict[str, Any]) -> WorldBuilderArtStatusSpec:
    cached = manifest.get("art", {})
    if isinstance(cached, dict) and str(cached.get("status", "")).strip():
        return WorldBuilderArtStatusSpec.model_validate(cached)
    path = _revision_art_status_path(package_root, draft_id, revision_id)
    if path.is_file():
        return WorldBuilderArtStatusSpec.model_validate(_read_json(path))
    return WorldBuilderArtStatusSpec(
        status=str(manifest.get("art_status", STATUS_DRAFT_READY)),
        updated_at=str(manifest.get("updated_at", "")),
        detail="Art pipeline has not started yet.",
    )


def _generation_status_from_disk(package_root: Path, draft_id: str, revision_id: str, manifest: dict[str, Any]) -> WorldBuilderGenerationStatusSpec:
    cached = manifest.get("generation", {})
    if isinstance(cached, dict) and str(cached.get("status", "")).strip():
        status = WorldBuilderGenerationStatusSpec.model_validate(cached)
    else:
        path = _revision_generation_worker_path(package_root, draft_id, revision_id)
        if path.is_file():
            status = WorldBuilderGenerationStatusSpec.model_validate(_read_json(path))
        else:
            status = WorldBuilderGenerationStatusSpec(
                status=str(manifest.get("status", STATUS_DRAFT_READY)),
                updated_at=str(manifest.get("updated_at", "")),
                detail="Generation worker has not started yet.",
                draft_id=draft_id,
                revision_id=revision_id,
            )
    unit_name = str(status.unit_name or "").strip()
    if unit_name:
        sub_state = _systemd_unit_property(unit_name, "SubState")
        active_state = _systemd_unit_property(unit_name, "ActiveState")
        if sub_state in {"queued", "waiting"}:
            detail = "Generation worker is queued."
        elif sub_state in {"running", "start", "start-pre", "start-post"} or active_state == "activating":
            detail = "Generation worker is running."
        elif active_state == "active" and str(status.status) in {STATUS_DRAFT_GENERATING, STATUS_REVISION_GENERATING}:
            detail = "Generation worker is finishing."
        elif sub_state == "failed" and str(status.status) in {STATUS_DRAFT_GENERATING, STATUS_REVISION_GENERATING}:
            detail = "Generation worker failed according to systemd."
            status = WorldBuilderGenerationStatusSpec.model_validate(
                {
                    **status.model_dump(),
                    "status": STATUS_DRAFT_FAILED,
                    "detail": detail,
                    "updated_at": _now_iso(),
                }
            )
            return status
        else:
            detail = str(status.detail or "").strip() or "Generation worker state updated."
        status = WorldBuilderGenerationStatusSpec.model_validate(
            {
                **status.model_dump(),
                "detail": detail,
                "updated_at": _now_iso(),
            }
        )
    return status


def _placeholder_revision_status(
    *,
    package_root: Path,
    draft_id: str,
    revision_id: str,
    world_name: str,
    world_id: str,
    status: str,
    error: str = "",
) -> dict[str, Any]:
    return {
        "revision_id": revision_id,
        "created_at": _now_iso(),
        "status": status,
        "world_name": str(world_name or ""),
        "world_id": str(world_id or ""),
        "summary_path": str(_revision_summary_path(package_root, draft_id, revision_id)),
        "package_path": str(_revision_package_path(package_root, draft_id, revision_id)),
        "package_validation": {},
        "startup_validation": {},
        "structured_summary": {},
        "compiler_critique": {},
        "compiled_preview": {},
        "world_summary_markdown": "",
        "error": str(error or ""),
    }


def _queue_generation_worker(
    *,
    package_root: Path,
    draft_id: str,
    revision_id: str,
    request: dict[str, Any],
    prior_context: dict[str, Any] | None,
    feedback: str,
    request_kind: str,
) -> dict[str, Any]:
    unit_name = f"agora-world-creator-gen-{_slug(draft_id)}-{_slug(revision_id)}"
    log_path = _revision_dir(package_root, draft_id, revision_id) / "generation_worker_launch.log"
    request_path = _revision_generation_request_path(package_root, draft_id, revision_id)
    _write_json(
        request_path,
        {
            "draft_id": draft_id,
            "revision_id": revision_id,
            "request_kind": str(request_kind or "create"),
            "request": dict(request or {}),
            "prior_context": dict(prior_context or {}),
            "feedback": str(feedback or ""),
            "created_at": _now_iso(),
        },
    )
    py_bin = resolve_runtime_python()
    shell_command = (
        f". $HOME/.config/agora_ui_runtime.env && "
        f"export PYTHONPATH={json.dumps(str(package_root))}:$PYTHONPATH && "
        f"exec {json.dumps(py_bin)} -m agora_ui.world_builder generate-worker "
        f"--package-root {json.dumps(str(package_root))} "
        f"--draft-id {json.dumps(draft_id)} "
        f"--revision-id {json.dumps(revision_id)} "
        f">> {json.dumps(str(log_path))} 2>&1"
    )
    subprocess.run(["systemctl", "--user", "stop", unit_name], capture_output=True, check=False)
    subprocess.run(["systemctl", "--user", "reset-failed", unit_name], capture_output=True, check=False)
    result = subprocess.run(
        [
            "systemd-run",
            "--user",
            f"--unit={unit_name}",
            f"--working-directory={package_root}",
            "/bin/bash",
            "-lc",
            shell_command,
        ],
        cwd=str(package_root),
        capture_output=True,
        text=True,
        check=False,
    )
    queued_ok = int(result.returncode) == 0
    payload = {
        "status": (STATUS_DRAFT_GENERATING if queued_ok else STATUS_DRAFT_FAILED),
        "unit_name": unit_name,
        "stdout_path": str(log_path),
        "updated_at": _now_iso(),
        "detail": ("Generation worker queued." if queued_ok else "Failed to queue generation worker."),
        "request_kind": str(request_kind or "create"),
        "draft_id": draft_id,
        "revision_id": revision_id,
        "launcher_returncode": int(result.returncode),
        "launcher_stdout": result.stdout.strip(),
        "launcher_stderr": result.stderr.strip(),
    }
    _write_json(_revision_generation_worker_path(package_root, draft_id, revision_id), payload)
    return payload


def run_generation_worker(package_root: Path, draft_id: str, revision_id: str) -> dict[str, Any]:
    package_root = package_root.resolve()
    request_payload = _read_json(_revision_generation_request_path(package_root, draft_id, revision_id))
    request = dict(request_payload.get("request", {}))
    prior_context = dict(request_payload.get("prior_context", {}))
    feedback = str(request_payload.get("feedback", ""))
    request_kind = str(request_payload.get("request_kind", "create") or "create")
    revision_status = _generate_revision(
        package_root=package_root,
        draft_id=draft_id,
        revision_id=revision_id,
        request=request,
        prior_context=(prior_context or None),
        feedback=feedback,
    )
    manifest = _load_manifest(package_root, draft_id)
    manifest.update(
        {
            "current_revision": revision_id,
            "status": str(revision_status.get("status", STATUS_DRAFT_FAILED)),
            "world_name": str(revision_status.get("world_name", manifest.get("world_name", ""))),
            "world_id": str(revision_status.get("world_id", manifest.get("world_id", ""))),
        }
    )
    if request_kind == "revise":
        manifest.update(
            {
                "art_status": STATUS_DRAFT_READY,
                "publish_status": STATUS_DRAFT_READY,
                "published_access_code": "",
                "publish": {},
            }
        )
    _cache_revision_in_manifest(manifest, revision_status)
    _require_unique_world_identity(
        package_root,
        world_name=str(manifest.get("world_name", "")),
        world_id=str(manifest.get("world_id", manifest.get("world_name", ""))),
        exclude_draft_id=draft_id,
    )
    manifest["generation"] = WorldBuilderGenerationStatusSpec(
        status=str(revision_status.get("status", STATUS_DRAFT_FAILED)),
        unit_name=str(_read_json(_revision_generation_worker_path(package_root, draft_id, revision_id)).get("unit_name", "")) if _revision_generation_worker_path(package_root, draft_id, revision_id).is_file() else "",
        stdout_path=str(_revision_dir(package_root, draft_id, revision_id) / "generation_worker_launch.log"),
        updated_at=_now_iso(),
        detail=("Generation completed." if str(revision_status.get("status", "")) == STATUS_DRAFT_READY else str(revision_status.get("error", "Generation failed."))),
        request_kind=request_kind,
        draft_id=draft_id,
        revision_id=revision_id,
    ).model_dump()
    _save_manifest(package_root, draft_id, manifest)
    return revision_status


def get_draft_response(package_root: Path, draft_id: str) -> dict[str, Any]:
    manifest = _load_manifest(package_root, draft_id)
    current_revision = str(manifest.get("current_revision", "")).strip()
    current_status = _current_status_from_manifest(manifest, current_revision) or _load_revision_status(package_root, draft_id, current_revision)
    generation_status = _generation_status_from_disk(package_root, draft_id, current_revision, manifest)
    if generation_status.status == STATUS_DRAFT_FAILED and str(manifest.get("status", "")) in {STATUS_DRAFT_GENERATING, STATUS_REVISION_GENERATING}:
        manifest["status"] = STATUS_DRAFT_FAILED
        manifest["generation"] = generation_status.model_dump()
        current_status["status"] = STATUS_DRAFT_FAILED
        current_status["error"] = str(current_status.get("error", "") or generation_status.detail or "Generation worker failed.")
        _cache_revision_in_manifest(manifest, current_status)
        _save_manifest(package_root, draft_id, manifest)
    history = _revision_history(package_root, draft_id, manifest)
    current_revision_data = _build_revision_model(current_status)
    draft = WorldBuilderDraftSpec(
        draft_id=str(manifest.get("draft_id", "")),
        created_at=str(manifest.get("created_at", "")),
        updated_at=str(manifest.get("updated_at", "")),
        current_revision=current_revision,
        status=str(manifest.get("status", "")),
        art_status=str(manifest.get("art_status", STATUS_DRAFT_READY)),
        publish_status=str(manifest.get("publish_status", STATUS_DRAFT_READY)),
        published_access_code=str(manifest.get("published_access_code", "")),
        world_name=str(manifest.get("world_name", "")),
        world_id=str(manifest.get("world_id", "")),
        current_revision_data=current_revision_data,
        history=history,
        world_summary_markdown=_current_summary_text(package_root, draft_id, current_revision, current_status, manifest),
        package_download_url=f"/api/world-builder/drafts/{draft_id}/package",
        generation=generation_status,
        art=_art_status_from_disk(package_root, draft_id, current_revision, manifest),
        publish=_publish_status_from_manifest(manifest),
    )
    return draft.model_dump()


def resolve_draft(package_root: Path, *, identifier: str = "", world_name: str = "", world_id: str = "") -> dict[str, Any]:
    package_root = package_root.resolve()
    manifest = _find_draft_match(
        package_root,
        identifier=identifier,
        world_name=world_name,
        world_id=world_id,
    )
    if manifest is None:
        raise FileNotFoundError("No creator draft matched that world name or ID.")
    draft_id = str(manifest.get("draft_id", "")).strip()
    if not draft_id:
        raise FileNotFoundError("Matched draft manifest was missing a draft_id.")
    draft = get_draft_response(package_root, draft_id)
    matched_by = "identifier"
    normalized_identifier = _normalized_lookup(identifier)
    if normalized_identifier:
        if normalized_identifier == _normalized_lookup(manifest.get("world_name", "")):
            matched_by = "world_name"
        elif normalized_identifier == _normalized_lookup(manifest.get("world_id", "")):
            matched_by = "world_id"
        elif normalized_identifier == _normalized_lookup(manifest.get("draft_id", "")):
            matched_by = "draft_id"
    elif _normalized_lookup(world_name):
        matched_by = "world_name"
    elif _normalized_lookup(world_id):
        matched_by = "world_id"
    return {
        "matched_by": matched_by,
        "draft": draft,
    }


def create_draft(package_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    package_root = package_root.resolve()
    requested_world_name = _first_non_empty(request.get("world_name"), default="")
    requested_world_id = _slug(_first_non_empty(request.get("world_id"), requested_world_name or "draft_world"))
    _require_unique_world_identity(
        package_root,
        world_name=requested_world_name,
        world_id=requested_world_id,
    )
    draft_id = f"creator_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    draft_path = _draft_dir(package_root, draft_id)
    draft_path.mkdir(parents=True, exist_ok=True)
    manifest = {
        "draft_id": draft_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "current_revision": "",
        "status": STATUS_DRAFT_GENERATING,
        "art_status": STATUS_DRAFT_READY,
        "publish_status": STATUS_DRAFT_READY,
        "published_access_code": "",
        "world_name": requested_world_name,
        "world_id": requested_world_id,
        "revision_ids": [],
        "history_cache": [],
        "current_revision_data": {},
        "world_summary_markdown": "",
        "generation": {},
        "art": {},
        "publish": {},
    }
    existing_revisions: list[str] = []
    revision_id = _next_revision_id(existing_revisions)
    placeholder_status = _placeholder_revision_status(
        package_root=package_root,
        draft_id=draft_id,
        revision_id=revision_id,
        world_name=requested_world_name,
        world_id=requested_world_id,
        status=STATUS_DRAFT_GENERATING,
    )
    _save_revision_status(package_root, draft_id, revision_id, placeholder_status)
    manifest["current_revision"] = revision_id
    _cache_revision_in_manifest(manifest, placeholder_status)
    _save_manifest(package_root, draft_id, manifest)
    generation_payload = _queue_generation_worker(
        package_root=package_root,
        draft_id=draft_id,
        revision_id=revision_id,
        request=request,
        prior_context=None,
        feedback="",
        request_kind="create",
    )
    manifest["generation"] = dict(generation_payload)
    if str(generation_payload.get("status", "")) == STATUS_DRAFT_FAILED:
        manifest["status"] = STATUS_DRAFT_FAILED
        placeholder_status["status"] = STATUS_DRAFT_FAILED
        placeholder_status["error"] = str(generation_payload.get("detail", "Failed to queue generation worker."))
        _save_revision_status(package_root, draft_id, revision_id, placeholder_status)
        _cache_revision_in_manifest(manifest, placeholder_status)
    _save_manifest(package_root, draft_id, manifest)
    return get_draft_response(package_root, draft_id)


def revise_draft(package_root: Path, draft_id: str, feedback: str) -> dict[str, Any]:
    package_root = package_root.resolve()
    manifest = _load_manifest(package_root, draft_id)
    current_revision = str(manifest.get("current_revision", "")).strip()
    if not current_revision:
        raise ValueError(f"Draft has no current revision: {draft_id}")
    current_status = _current_status_from_manifest(manifest, current_revision) or _load_revision_status(package_root, draft_id, current_revision)
    current_config = {}
    current_config_path = Path(str(current_status.get("world_config_path", "")).strip())
    if current_config_path.is_file():
        current_config = _read_json(current_config_path)
    prior_brief = ""
    input_brief_path = _revision_input_brief_path(package_root, draft_id, current_revision)
    if input_brief_path.is_file():
        prior_brief = input_brief_path.read_text(encoding="utf-8").strip()
    request = {
        "world_name": str(manifest.get("world_name", "")),
        "genre": current_config.get("runner", {}).get("domain_label", ""),
        "player_count_target": 4,
        "agent_count_target": int(current_config.get("runtime", {}).get("agent_count", 40) or 40),
        "focus": current_config.get("scenario_meta", {}).get("simulation_objective", ""),
        "seed": int(current_config.get("runtime", {}).get("seed", 42627) or 42627),
        "brief": current_config.get("scenario_meta", {}).get("description", "") or prior_brief,
    }
    revision_id = _next_revision_id([str(value).strip() for value in manifest.get("revision_ids", []) if str(value).strip()])
    prior_context = {
        "world_name": current_status.get("world_name", ""),
        "world_id": current_status.get("world_id", ""),
        "structured_summary": current_status.get("structured_summary", {}),
        "world_summary": _current_summary_text(package_root, draft_id, current_revision, current_status, manifest)[:3000],
    }
    placeholder_status = _placeholder_revision_status(
        package_root=package_root,
        draft_id=draft_id,
        revision_id=revision_id,
        world_name=str(manifest.get("world_name", "")),
        world_id=str(manifest.get("world_id", "")),
        status=STATUS_REVISION_GENERATING,
    )
    _save_revision_status(package_root, draft_id, revision_id, placeholder_status)
    manifest.update(
        {
            "current_revision": revision_id,
            "status": STATUS_REVISION_GENERATING,
            "art_status": STATUS_DRAFT_READY,
            "publish_status": STATUS_DRAFT_READY,
            "published_access_code": "",
            "publish": {},
            "art": {},
        }
    )
    _cache_revision_in_manifest(manifest, placeholder_status)
    _save_manifest(package_root, draft_id, manifest)
    generation_payload = _queue_generation_worker(
        package_root=package_root,
        draft_id=draft_id,
        revision_id=revision_id,
        request=request,
        prior_context=prior_context,
        feedback=feedback,
        request_kind="revise",
    )
    manifest["generation"] = dict(generation_payload)
    if str(generation_payload.get("status", "")) == STATUS_DRAFT_FAILED:
        manifest["status"] = STATUS_DRAFT_FAILED
        placeholder_status["status"] = STATUS_DRAFT_FAILED
        placeholder_status["error"] = str(generation_payload.get("detail", "Failed to queue generation worker."))
        _save_revision_status(package_root, draft_id, revision_id, placeholder_status)
        _cache_revision_in_manifest(manifest, placeholder_status)
    _save_manifest(package_root, draft_id, manifest)
    return get_draft_response(package_root, draft_id)


def draft_history(package_root: Path, draft_id: str) -> dict[str, Any]:
    manifest = _load_manifest(package_root.resolve(), draft_id)
    history = _revision_history(package_root.resolve(), draft_id, manifest)
    return {
        "draft_id": draft_id,
        "history": [entry.model_dump() for entry in history],
    }


def draft_package_path(package_root: Path, draft_id: str) -> Path:
    manifest = _load_manifest(package_root.resolve(), draft_id)
    revision_id = str(manifest.get("current_revision", "")).strip()
    path = _revision_package_path(package_root.resolve(), draft_id, revision_id)
    if not path.is_file():
        raise FileNotFoundError(f"Draft package missing: {draft_id}")
    return path


def publish_draft(package_root: Path, draft_id: str) -> dict[str, Any]:
    package_root = package_root.resolve()
    from macro_ui.build_macro_ui import export_world_package_from_db

    manifest = _load_manifest(package_root, draft_id)
    if str(manifest.get("status", "")).strip() not in {STATUS_PUBLISH_READY, STATUS_PUBLISHED}:
        raise ValueError("Draft is not publish-ready yet")
    if str(manifest.get("publish_status", "")).strip() == STATUS_PUBLISHED and str(manifest.get("published_access_code", "")).strip():
        return get_draft_response(package_root, draft_id)
    revision_id = str(manifest.get("current_revision", "")).strip()
    revision_package = _revision_package_path(package_root, draft_id, revision_id)
    metadata = export_world_package_from_db(
        package_root=package_root,
        package_db=revision_package,
        package_name=str(manifest.get("world_name", "")).strip() or draft_id,
        source_label="world_creator_publish",
        extra_meta={
            "world_creator_draft_id": draft_id,
            "world_creator_revision": revision_id,
        },
    )
    access_code = str(metadata.get("access_code", "")).strip()
    publish_payload = WorldBuilderPublishStatusSpec(
        status=STATUS_PUBLISHED,
        access_code=access_code,
        pixel_read=bool(metadata.get("pixel_read", False)),
        world_url=(f"/pixel/?pixel_world={access_code}" if access_code else ""),
        package_db_url=(f"/api/packages/{access_code}/db" if access_code else ""),
        detail="Published world exported and available in the public world catalog.",
        package_validation=dict(metadata.get("package_validation", {})),
        backend_startup_validation=dict(metadata.get("backend_startup_validation", {})),
        pixel_launch_validation=dict(metadata.get("pixel_launch_validation", {})),
        startup_validation=dict(metadata.get("startup_validation", {})),
    ).model_dump()
    manifest.update(
        {
            "status": STATUS_PUBLISHED,
            "publish_status": STATUS_PUBLISHED,
            "published_access_code": access_code,
            "publish": publish_payload,
        }
    )
    _save_manifest(package_root, draft_id, manifest)
    return get_draft_response(package_root, draft_id)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="World builder workflow utilities for Agora creator drafts.")
    sub = parser.add_subparsers(dest="command", required=True)
    art = sub.add_parser("art-worker", help="Run the world creator art pipeline for one revision.")
    art.add_argument("--package-root", required=True)
    art.add_argument("--draft-id", required=True)
    art.add_argument("--revision-id", required=True)
    gen = sub.add_parser("generate-worker", help="Run the world creator generation pipeline for one revision.")
    gen.add_argument("--package-root", required=True)
    gen.add_argument("--draft-id", required=True)
    gen.add_argument("--revision-id", required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.command == "art-worker":
        payload = run_art_pipeline(
            package_root=Path(args.package_root).resolve(),
            draft_id=str(args.draft_id),
            revision_id=str(args.revision_id),
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if args.command == "generate-worker":
        payload = run_generation_worker(
            package_root=Path(args.package_root).resolve(),
            draft_id=str(args.draft_id),
            revision_id=str(args.revision_id),
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()

__all__ = ['STATUS_DRAFT_GENERATING', 'STATUS_DRAFT_READY', 'STATUS_DRAFT_FAILED', 'STATUS_REVISION_GENERATING', 'STATUS_ART_QUEUED', 'STATUS_ART_RUNNING', 'STATUS_ART_FAILED', 'STATUS_ART_TIMEOUT_SKIPPED', 'STATUS_QA_FAILED_RETRYING', 'STATUS_PUBLISH_READY', 'STATUS_PUBLISHED', 'GLOBAL_CREATOR_ENV_PATHS', '_drafts_root', '_revisions_root', '_next_revision_id', '_load_revision_status', '_save_revision_status', '_cached_history_entries', '_normalized_lookup', '_find_draft_match', '_require_unique_world_identity', '_env_int', '_world_creator_model', '_world_creator_timeout_seconds', '_world_creator_max_retries', '_world_creator_provider', '_execute_json_prompt', '_execute_text_prompt', '_builder_spec_schema', '_world_config_critique_schema', '_render_builder_prompt', '_focus_profile', '_synthesized_gameplay_loops', '_fallback_player_entry_points', '_fallback_conflict_hooks', '_fallback_custom_actions', '_config_snapshot_for_critique', '_world_config_critique_prompt', '_normalized_critique_dict', '_critique_compiled_world_config', '_merge_gameplay_loops', '_apply_compiler_critique_to_builder_spec', '_normalize_builder_spec', '_scaled_counts', '_cycled_value', '_allowed_item_ids', '_deep_replace_exact_strings', '_item_id_from_hint', '_inventory_specs_for_role', '_inventory_specs_from_item_ids', '_choose_room_id', '_route_story_verb', '_loop_action_name', '_ordinary_routes', '_cinematic_routes', '_event_function_id', '_main_character_policy', '_loop_event_function', '_conflict_event_function', '_player_entry_event_function', '_compiled_extra_world_functions', '_build_world_config_from_spec', '_scenario_relative_path', '_validate_revision_agents', '_startup_validation_for_package_db', '_pixel_launch_validation_for_package_db', '_validation_workspace', '_structured_summary', '_compiled_preview_from_config', '_world_summary_prompt', '_generate_summary', '_build_revision_payload', '_generate_revision', '_build_revision_model', '_current_summary_text', '_art_status_from_disk', 'get_draft_response', 'resolve_draft', 'create_draft', 'revise_draft', 'draft_history', 'draft_package_path', '_systemd_unit_property', '_prepare_art_runtime', '_load_creator_runtime_env', '_run_worker_command', '_relative_generated_asset_path', '_copy_generated_asset_reference', '_asset_event_matches_revision', '_isolated_revision_asset_workspace', '_repack_revision_package_with_current_assets', '_pixel_read_report_for_revision', 'run_art_pipeline', 'launch_art_worker', 'art_status', 'publish_draft', '_parse_args', 'main']
