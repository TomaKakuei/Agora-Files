from __future__ import annotations
import argparse
import base64
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
from .validation import (
    _startup_validation_for_package_db,
    _pixel_launch_validation_for_package_db,
)
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



def _systemd_unit_property(unit_name: str, prop: str) -> str:
    if not unit_name:
        return ""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", unit_name, f"--property={prop}", "--value"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def _prepare_art_runtime(package_root: Path, draft_id: str, revision_id: str) -> Path:
    runtime_dir = _revision_art_runtime_dir(package_root, draft_id, revision_id)
    replay_backup_dir: Path | None = None
    existing_replay_dir = runtime_dir / "replay"
    if existing_replay_dir.is_dir():
        replay_backup_dir = Path(tempfile.mkdtemp(prefix="agora_world_creator_replay_backup_", dir=str(package_root / "output"))) / "replay"
        replay_backup_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(existing_replay_dir, replay_backup_dir)
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    run_inputs_dir = runtime_dir / "run_inputs"
    scenario_target = run_inputs_dir / "scenario"
    scenario_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_revision_world_config_path(package_root, draft_id, revision_id), run_inputs_dir / "world_config.json")
    shutil.copytree(_revision_scenario_dir(package_root, draft_id, revision_id), scenario_target)
    if replay_backup_dir is not None and replay_backup_dir.is_dir():
        shutil.copytree(replay_backup_dir, runtime_dir / "replay", dirs_exist_ok=True)
        shutil.rmtree(replay_backup_dir.parent, ignore_errors=True)
    return runtime_dir


def _load_creator_runtime_env() -> dict[str, str]:
    env = dict(os.environ)
    paths = _get_mocked_fallback("GLOBAL_CREATOR_ENV_PATHS", GLOBAL_CREATOR_ENV_PATHS)
    for env_path in paths:
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
                if not line or "=" not in line:
                    continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and value and key not in env:
                env[key] = value
    return env


def _run_worker_command(command: list[str], *, cwd: Path, log_path: Path) -> dict[str, Any]:
    mocked = _get_mocked_fallback("_run_worker_command", _run_worker_command)
    if mocked is not _run_worker_command:
        return mocked(command, cwd=cwd, log_path=log_path)

    started_at = _now_iso()
    started_perf = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=str(cwd),
        env=_load_creator_runtime_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[COMMAND] {' '.join(command)}\n")
        if result.stdout.strip():
            handle.write(result.stdout[-4000:] + "\n")
        if result.stderr.strip():
            handle.write(result.stderr[-4000:] + "\n")
    return {
        "command": command,
        "started_at": started_at,
        "duration_seconds": round(time.perf_counter() - started_perf, 3),
        "returncode": int(result.returncode),
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
    }


def _relative_generated_asset_path(value: str) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("./"):
        text = text[2:]
    if text.startswith("/"):
        return None
    if not text.startswith("assets/generated/"):
        return None
    return Path(text)


def _copy_generated_asset_reference(*, package_root: Path, target_root: Path, candidate: str) -> None:
    relative = _relative_generated_asset_path(candidate)
    if relative is None:
        return
    source_path = (package_root / "frontend" / relative).resolve()
    if not source_path.is_file():
        return
    target_path = (target_root / relative).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)


def _asset_event_matches_revision(payload: dict[str, Any], *, world_id: str, world_revision: str) -> bool:
    if not isinstance(payload, dict):
        return False
    payload_world_id = str(payload.get("world_id", "")).strip()
    payload_world_revision = str(payload.get("world_revision") or payload.get("revision") or "").strip()
    if world_id and payload_world_id != world_id:
        return False
    if world_revision and payload_world_revision != world_revision:
        return False
    return True


def _isolated_revision_asset_workspace(
    package_root: Path,
    draft_id: str,
    revision_id: str,
    *,
    target_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    config = _read_json(_revision_world_config_path(package_root, draft_id, revision_id))
    revision_slug = _revision_slug(draft_id, revision_id)
    source_generated_root = package_root / "frontend" / "assets" / "generated"
    manifest_dir = source_generated_root / "world_asset_sets" / revision_slug
    manifest_path = manifest_dir / "world_asset_set_manifest.json"
    manifest_payload = _read_json(manifest_path) if manifest_path.is_file() else {}
    map_asset_url = str(manifest_payload.get("map_asset_url", "")).strip()
    if map_asset_url:
        config.setdefault("pixel_asset_pipeline", {}).setdefault("frontend", {})["map_asset_url"] = map_asset_url

    run_inputs_dir = target_root / "run_inputs"
    run_inputs_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_inputs_dir / "world_config.json", config)
    shutil.copytree(
        _revision_scenario_dir(package_root, draft_id, revision_id),
        run_inputs_dir / "scenario",
        dirs_exist_ok=True,
    )
    scenario_map_grid_path = run_inputs_dir / "scenario" / "map_grid.json"
    if scenario_map_grid_path.is_file() and map_asset_url:
        map_grid_payload = _read_json(scenario_map_grid_path)
        map_grid_payload.setdefault("map_visual", {})["background_url"] = map_asset_url
        _write_json(scenario_map_grid_path, map_grid_payload)

    world_id = str(config.get("scenario_meta", {}).get("world_id", "")).strip()
    world_revision = revision_slug
    target_generated_root = target_root / "assets" / "generated"
    target_generated_root.mkdir(parents=True, exist_ok=True)

    if manifest_dir.is_dir():
        shutil.copytree(
            manifest_dir,
            target_generated_root / "world_asset_sets" / revision_slug,
            dirs_exist_ok=True,
        )
    if manifest_payload:
        _write_json(target_generated_root / "world_asset_sets" / "current_world_pixel_set.json", manifest_payload)

    bootstrap_path = source_generated_root / "events" / "bootstrap_assets.json"
    latest_path = source_generated_root / "events" / "latest.json"
    bootstrap_payload = _read_json(bootstrap_path) if bootstrap_path.is_file() else {}
    latest_payload = _read_json(latest_path) if latest_path.is_file() else {}

    filtered_assets: list[dict[str, Any]] = []
    if isinstance(bootstrap_payload.get("assets", []), list):
        filtered_assets = [
            entry
            for entry in bootstrap_payload.get("assets", [])
            if isinstance(entry, dict) and _asset_event_matches_revision(entry, world_id=world_id, world_revision=world_revision)
        ]
    if not filtered_assets and isinstance(manifest_payload.get("assets", []), list):
        filtered_assets = [
            entry
            for entry in manifest_payload.get("assets", [])
            if isinstance(entry, dict) and _asset_event_matches_revision(entry, world_id=world_id, world_revision=world_revision)
        ]
    if not filtered_assets and isinstance(latest_payload, dict) and _asset_event_matches_revision(latest_payload, world_id=world_id, world_revision=world_revision):
        filtered_assets = [latest_payload]

    filtered_bootstrap = {
        "generated_at": _now_iso(),
        "world_id": world_id,
        "world_revision": world_revision,
        "assets": filtered_assets,
    }
    filtered_latest = filtered_assets[-1] if filtered_assets else {}
    events_root = target_generated_root / "events"
    events_root.mkdir(parents=True, exist_ok=True)
    _write_json(events_root / "bootstrap_assets.json", filtered_bootstrap)
    _write_json(events_root / "latest.json", filtered_latest)

    if manifest_payload:
        _copy_generated_asset_reference(
            package_root=package_root,
            target_root=target_root,
            candidate=map_asset_url,
        )
    for payload in filtered_assets:
        _copy_generated_asset_reference(
            package_root=package_root,
            target_root=target_root,
            candidate=str(payload.get("atlas_url", "")),
        )
        _copy_generated_asset_reference(
            package_root=package_root,
            target_root=target_root,
            candidate=str(payload.get("json_url", "")),
        )
    return config, filtered_assets, manifest_payload


def _repack_revision_package_with_current_assets(package_root: Path, draft_id: str, revision_id: str) -> dict[str, Any]:
    mocked = _get_mocked_fallback("_repack_revision_package_with_current_assets", _repack_revision_package_with_current_assets)
    if mocked is not _repack_revision_package_with_current_assets:
        return mocked(package_root, draft_id, revision_id)

    temp_root = Path(tempfile.mkdtemp(prefix="agora_world_creator_artpkg_", dir=str(package_root / "output")))
    try:
        config, filtered_assets, manifest_payload = _isolated_revision_asset_workspace(
            package_root,
            draft_id,
            revision_id,
            target_root=temp_root,
        )
        package_db = temp_root / "world_package.db"
        pixel_report = assess_pixel_readiness_from_root(temp_root)
        pack_world_package(
            temp_root,
            package_db,
            package_name=str(config.get("scenario_meta", {}).get("world_name", draft_id)),
            source_label="world_creator_art_pipeline",
            extra_meta={
                "pixel_read": bool(pixel_report.get("pixel_read", False)),
                "pixel_read_report": json.dumps(pixel_report, ensure_ascii=False),
                "world_creator_draft_id": draft_id,
                "world_creator_revision": revision_id,
                "asset_count": len(filtered_assets),
                "asset_manifest_status": str(manifest_payload.get("status", "")) if isinstance(manifest_payload, dict) else "",
            },
        )
        destination = _revision_package_path(package_root, draft_id, revision_id)
        shutil.copy2(package_db, destination)
        return {
            "package_db": destination,
            "pixel_report": pixel_report,
            "asset_count": len(filtered_assets),
        }
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _pixel_read_report_for_revision(package_root: Path, draft_id: str, revision_id: str) -> dict[str, Any]:
    temp_root = Path(tempfile.mkdtemp(prefix="agora_world_creator_art_", dir=str(package_root / "output")))
    try:
        _isolated_revision_asset_workspace(
            package_root,
            draft_id,
            revision_id,
            target_root=temp_root,
        )
        return assess_pixel_readiness_from_root(temp_root)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _run_gemini_map_qa(config: dict[str, Any], map_path: Path, screenshot_path: Path) -> dict[str, Any]:
    from ..vertex_json_client import VertexJsonClient
    if not map_path.is_file() or not screenshot_path.is_file():
        return {
            "status": "error",
            "reasoning": f"Missing images: map_exists={map_path.is_file()}, screenshot_exists={screenshot_path.is_file()}",
            "is_pixel_map": "N",
            "has_visual_errors": "Y"
        }
    try:
        map_b64 = base64.b64encode(map_path.read_bytes()).decode("utf-8")
        screenshot_b64 = base64.b64encode(screenshot_path.read_bytes()).decode("utf-8")
        media_parts = [
            {"inlineData": {"mimeType": "image/png", "data": map_b64}},
            {"inlineData": {"mimeType": "image/png", "data": screenshot_b64}}
        ]
        client = VertexJsonClient(config)
        prompt = "Please review the provided stitched map asset and the live browser screenshot to answer the following questions."
        system_instruction = (
            "Expectation: This is a procedurally generated 2D top-down pixel art environment. "
            "It should look like a classic cohesive pixel art RPG map with coherent walls, floors, and rooms. "
            "There should be no black voids or chaotic overlapping textures. "
            "CRITICAL: The map MUST clearly display distinct rooms, structured floor textures, walls, and outdoor terrain. "
            "If the image is just a blank or solid color background (e.g., all beige or gray) with empty boxes, "
            "it is NOT a valid map and you MUST fail it by setting has_visual_errors='Y'."
        )
        schema = {
            "type": "object",
            "properties": {
                "is_pixel_map": {"type": "string", "enum": ["Y", "N"]},
                "has_visual_errors": {"type": "string", "enum": ["Y", "N"]},
                "reasoning": {"type": "string"}
            },
            "required": ["is_pixel_map", "has_visual_errors", "reasoning"]
        }
        result = client.generate_multimodal_json(
            system_instruction=system_instruction,
            prompt=prompt,
            schema=schema,
            stage="map_qa",
            media_parts=media_parts
        )
        return {
            "status": "ok",
            "is_pixel_map": result.get("is_pixel_map", "N"),
            "has_visual_errors": result.get("has_visual_errors", "Y"),
            "reasoning": result.get("reasoning", "")
        }
    except Exception as e:
        return {
            "status": "error",
            "reasoning": f"Gemini API error: {str(e)}",
            "is_pixel_map": "N",
            "has_visual_errors": "Y"
        }


def _resolve_map_qa_paths(
    *,
    package_root: Path,
    draft_id: str,
    revision_id: str,
    config: dict[str, Any],
    pixel_launch_validation: dict[str, Any],
) -> tuple[Path, Path]:
    screenshot_str = str(pixel_launch_validation.get("screenshot_path", "")).strip()
    screenshot_path = Path(screenshot_str) if screenshot_str else Path("/nonexistent")

    manifest_path = (
        package_root
        / "frontend"
        / "assets"
        / "generated"
        / "world_asset_sets"
        / _revision_slug(draft_id, revision_id)
        / "world_asset_set_manifest.json"
    )
    manifest_payload = _read_json(manifest_path) if manifest_path.is_file() else {}

    candidate_values = [
        str(manifest_payload.get("map_source_path", "")).strip(),
        str(manifest_payload.get("map_asset_url", "")).strip(),
        str(config.get("pixel_asset_pipeline", {}).get("frontend", {}).get("map_asset_url", "")).strip(),
    ]
    for candidate in candidate_values:
        if not candidate:
            continue
        candidate_path = Path(candidate).expanduser()
        if candidate_path.is_absolute():
            return candidate_path, screenshot_path
        normalized = candidate[2:] if candidate.startswith("./") else candidate.lstrip("/")
        if not normalized:
            continue
        return (package_root / "frontend" / normalized).resolve(), screenshot_path
    return Path("/nonexistent"), screenshot_path


def run_art_pipeline(package_root: Path, draft_id: str, revision_id: str) -> dict[str, Any]:
    package_root = package_root.resolve()
    manifest = _load_manifest(package_root, draft_id)
    runtime_dir = _prepare_art_runtime(package_root, draft_id, revision_id)
    log_path = runtime_dir / "art_pipeline.log"
    art_status = {
        "status": STATUS_ART_RUNNING,
        "unit_name": str(_read_json(_revision_art_worker_path(package_root, draft_id, revision_id)).get("unit_name", "")) if _revision_art_worker_path(package_root, draft_id, revision_id).is_file() else "",
        "run_dir": str(runtime_dir),
        "stdout_path": str(log_path),
        "updated_at": _now_iso(),
        "detail": "Art pipeline is generating world media and QA feeds.",
        "logs": [],
        "qa_summary": {},
        "backend_startup_validation": {},
        "pixel_launch_validation": {},
        "startup_validation": {},
    }
    _write_json(_revision_art_status_path(package_root, draft_id, revision_id), art_status)
    manifest["status"] = STATUS_ART_RUNNING
    manifest["art_status"] = STATUS_ART_RUNNING
    manifest["art"] = dict(art_status)
    _save_manifest(package_root, draft_id, manifest)

    mocked_resolve = _get_mocked_fallback("resolve_runtime_python", resolve_runtime_python)
    py_bin = mocked_resolve()
    config_path = runtime_dir / "run_inputs" / "world_config.json"
    scenario_dir = runtime_dir / "run_inputs" / "scenario"
    revision_slug = f"{draft_id}_{revision_id}"
    commands = [
        [
            py_bin,
            "-m",
            "macro_ui.build_macro_ui",
            "--run-dir",
            str(runtime_dir),
            "--wait-for-scenario-seconds",
            "0",
            "--no-agent-images",
            "--no-generate-images",
        ],
        [
            py_bin,
            str(package_root / "asset_pipeline" / "generate_world_asset_set.py"),
            "--config",
            str(config_path),
            "--scenario-dir",
            str(scenario_dir),
            "--revision",
            revision_slug,
            "--all-active-agents",
            "--max-workers",
            "1",
            "--update-current-alias",
            "--reuse-latest-raw-sheet",
        ],
        [
            py_bin,
            str(package_root / "asset_pipeline" / "build_live_ready_feed.py"),
            "--repo-root",
            str(package_root),
            "--config",
            str(config_path),
            "--scenario-dir",
            str(scenario_dir),
            "--target-ready-count",
            str(min(30, int(_read_json(config_path).get("runtime", {}).get("agent_count", 30) or 30))),
            "--all-active-agents",
            "--preferred-revision",
            revision_slug,
        ],
    ]

    logs: list[dict[str, Any]] = []
    for command in commands:
        result = _run_worker_command(command, cwd=package_root, log_path=log_path)
        logs.append(result)
        if result["returncode"] != 0:
            art_status.update(
                {
                    "status": STATUS_ART_FAILED,
                    "updated_at": _now_iso(),
                    "detail": "Art pipeline command failed.",
                    "logs": logs,
                    "qa_summary": {},
                    "backend_startup_validation": {},
                    "pixel_launch_validation": {},
                    "startup_validation": {},
                }
            )
            _write_json(_revision_art_status_path(package_root, draft_id, revision_id), art_status)
            manifest["status"] = STATUS_ART_FAILED
            manifest["art_status"] = STATUS_ART_FAILED
            manifest["art"] = dict(art_status)
            _save_manifest(package_root, draft_id, manifest)
            return art_status

    repack_result = _repack_revision_package_with_current_assets(package_root, draft_id, revision_id)
    pixel_report = dict(repack_result.get("pixel_report", {}))
    if not bool(pixel_report.get("pixel_read", False)):
        art_status.update(
            {
                "status": STATUS_QA_FAILED_RETRYING,
                "updated_at": _now_iso(),
                "detail": "Pixel readiness failed on the first pass. Retrying live-ready feed once.",
                "logs": logs,
                "qa_summary": pixel_report,
                "backend_startup_validation": {},
                "pixel_launch_validation": {},
                "startup_validation": {},
            }
        )
        _write_json(_revision_art_status_path(package_root, draft_id, revision_id), art_status)
        manifest["status"] = STATUS_QA_FAILED_RETRYING
        manifest["art_status"] = STATUS_QA_FAILED_RETRYING
        manifest["art"] = dict(art_status)
        _save_manifest(package_root, draft_id, manifest)
        retry_result = _run_worker_command(commands[-1], cwd=package_root, log_path=log_path)
        logs.append(retry_result)
        repack_result = _repack_revision_package_with_current_assets(package_root, draft_id, revision_id)
        pixel_report = dict(repack_result.get("pixel_report", {}))
        if retry_result["returncode"] != 0 or not bool(pixel_report.get("pixel_read", False)):
            art_status.update(
                {
                    "status": STATUS_ART_FAILED,
                    "updated_at": _now_iso(),
                    "detail": "Art pipeline could not reach PIXEL READ after retry.",
                    "logs": logs,
                    "qa_summary": pixel_report,
                    "backend_startup_validation": {},
                    "pixel_launch_validation": {},
                    "startup_validation": {},
                }
            )
            _write_json(_revision_art_status_path(package_root, draft_id, revision_id), art_status)
            manifest["status"] = STATUS_ART_FAILED
            manifest["art_status"] = STATUS_ART_FAILED
            manifest["art"] = dict(art_status)
            _save_manifest(package_root, draft_id, manifest)
            return art_status

    config = _read_json(_revision_world_config_path(package_root, draft_id, revision_id))
    backend_startup_validation = _startup_validation_for_package_db(
        package_root,
        _revision_package_path(package_root, draft_id, revision_id),
        display_name=str(config.get("scenario_meta", {}).get("world_name", "")),
    )
    if not bool(backend_startup_validation.get("startup_ok", False)):
        art_status.update(
            {
                "status": STATUS_ART_FAILED,
                "updated_at": _now_iso(),
                "detail": "Art pipeline passed pixel readiness but live startup smoke failed.",
                "logs": logs,
                "qa_summary": pixel_report,
                "backend_startup_validation": backend_startup_validation,
                "pixel_launch_validation": {},
                "startup_validation": {
                    "startup_ok": False,
                    "stage": "backend_startup",
                    "expected_access_code": "",
                    "selected_access_code": "",
                    "backend_startup_validation": backend_startup_validation,
                    "pixel_launch_validation": {},
                    "startup_status_text": "",
                    "session_endpoint": "",
                    "screenshot_path": "",
                    "error": str(backend_startup_validation.get("error", "")).strip(),
                },
            }
        )
        _write_json(_revision_art_status_path(package_root, draft_id, revision_id), art_status)
        manifest["status"] = STATUS_ART_FAILED
        manifest["art_status"] = STATUS_ART_FAILED
        manifest["art"] = dict(art_status)
        _save_manifest(package_root, draft_id, manifest)
        return art_status

    pixel_launch_validation = _pixel_launch_validation_for_package_db(
        package_root,
        _revision_package_path(package_root, draft_id, revision_id),
        display_name=str(config.get("scenario_meta", {}).get("world_name", "")),
        seed=int(config.get("runtime", {}).get("seed", 42627) or 42627),
    )
    startup_validation = {
        "startup_ok": bool(
            backend_startup_validation.get("startup_ok", False)
            and pixel_launch_validation.get("startup_ok", False)
        ),
        "stage": "ok" if bool(pixel_launch_validation.get("startup_ok", False)) else "pixel_launch",
        "expected_access_code": str(pixel_launch_validation.get("expected_access_code", "")).strip(),
        "selected_access_code": str(pixel_launch_validation.get("selected_access_code", "")).strip(),
        "backend_startup_validation": backend_startup_validation,
        "pixel_launch_validation": pixel_launch_validation,
        "startup_status_text": str(pixel_launch_validation.get("startup_status_text", "")).strip(),
        "session_endpoint": str(pixel_launch_validation.get("session_endpoint", "")).strip(),
        "screenshot_path": str(pixel_launch_validation.get("screenshot_path", "")).strip(),
        "error": str(pixel_launch_validation.get("error", "")).strip(),
    }
    if not bool(pixel_launch_validation.get("startup_ok", False)):
        art_status.update(
            {
                "status": STATUS_ART_FAILED,
                "updated_at": _now_iso(),
                "detail": "Art pipeline passed backend smoke but Pixel UI launch validation failed.",
                "logs": logs,
                "qa_summary": pixel_report,
                "backend_startup_validation": backend_startup_validation,
                "pixel_launch_validation": pixel_launch_validation,
                "startup_validation": startup_validation,
            }
        )
        _write_json(_revision_art_status_path(package_root, draft_id, revision_id), art_status)
        manifest["status"] = STATUS_ART_FAILED
        manifest["art_status"] = STATUS_ART_FAILED
        manifest["art"] = dict(art_status)
        _save_manifest(package_root, draft_id, manifest)
        return art_status

    map_path, screenshot_path = _resolve_map_qa_paths(
        package_root=package_root,
        draft_id=draft_id,
        revision_id=revision_id,
        config=config,
        pixel_launch_validation=pixel_launch_validation,
    )

    qa_result = _run_gemini_map_qa(config, map_path, screenshot_path)
    if qa_result.get("is_pixel_map") != "Y" or qa_result.get("has_visual_errors") != "N":
        art_status.update({
            "status": STATUS_ART_FAILED,
            "updated_at": _now_iso(),
            "detail": f"Map QA Failed: Gemini visual inspection raised a flag requiring backend intervention. Reasoning: {qa_result.get('reasoning', '')}",
            "logs": logs,
            "qa_summary": pixel_report,
            "backend_startup_validation": backend_startup_validation,
            "pixel_launch_validation": pixel_launch_validation,
            "startup_validation": startup_validation,
        })
        _write_json(_revision_art_status_path(package_root, draft_id, revision_id), art_status)
        manifest["status"] = STATUS_ART_FAILED
        manifest["art_status"] = STATUS_ART_FAILED
        manifest["art"] = dict(art_status)
        _save_manifest(package_root, draft_id, manifest)
        return art_status

    art_status.update(
        {
            "status": STATUS_PUBLISH_READY,
            "updated_at": _now_iso(),
            "detail": "Art pipeline and readiness checks passed. This draft can now be published.",
            "logs": logs,
            "qa_summary": pixel_report,
            "backend_startup_validation": backend_startup_validation,
            "pixel_launch_validation": pixel_launch_validation,
            "startup_validation": startup_validation,
        }
    )
    _write_json(_revision_art_status_path(package_root, draft_id, revision_id), art_status)
    manifest["status"] = STATUS_PUBLISH_READY
    manifest["art_status"] = STATUS_PUBLISH_READY
    manifest["art"] = dict(art_status)
    _save_manifest(package_root, draft_id, manifest)
    return art_status


def launch_art_worker(package_root: Path, draft_id: str) -> dict[str, Any]:
    package_root = package_root.resolve()
    manifest = _load_manifest(package_root, draft_id)
    revision_id = str(manifest.get("current_revision", "")).strip()
    if not revision_id:
        raise ValueError(f"Draft has no current revision: {draft_id}")
    unit_name = f"agora-world-creator-{_slug(draft_id)}-{_slug(revision_id)}"
    log_path = _revision_dir(package_root, draft_id, revision_id) / "art_worker_launch.log"
    py_bin = resolve_runtime_python()
    shell_command = (
        f". $HOME/.config/agora_ui_runtime.env && "
        f"export PYTHONPATH={json.dumps(str(package_root))}:$PYTHONPATH && "
        f"exec {json.dumps(py_bin)} -m agora_ui.world_builder art-worker "
        f"--package-root {json.dumps(str(package_root))} "
        f"--draft-id {json.dumps(draft_id)} "
        f"--revision-id {json.dumps(revision_id)} "
        f">> {json.dumps(str(log_path))} 2>&1"
    )
    # Clean up any stale or failed transient systemd units with the same name to prevent collisions
    subprocess.run(["systemctl", "--user", "stop", unit_name], capture_output=True, check=False)
    subprocess.run(["systemctl", "--user", "reset-failed", unit_name], capture_output=True, check=False)

    systemd_cmd = [
        "systemd-run",
        "--user",
        f"--unit={unit_name}",
        f"--working-directory={package_root}",
        "/bin/bash",
        "-lc",
        shell_command,
    ]
    result = subprocess.run(
        systemd_cmd,
        cwd=str(package_root),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = {
        "unit_name": unit_name,
        "draft_id": draft_id,
        "revision_id": revision_id,
        "stdout_path": str(log_path),
        "launcher_returncode": int(result.returncode),
        "launcher_stdout": result.stdout.strip(),
        "launcher_stderr": result.stderr.strip(),
        "status": STATUS_ART_QUEUED if result.returncode == 0 else STATUS_ART_FAILED,
    }
    _write_json(_revision_art_worker_path(package_root, draft_id, revision_id), payload)
    manifest_art = WorldBuilderArtStatusSpec(
        status=(STATUS_ART_QUEUED if result.returncode == 0 else STATUS_ART_FAILED),
        unit_name=unit_name,
        run_dir=str(_revision_art_runtime_dir(package_root, draft_id, revision_id)),
        stdout_path=str(log_path),
        updated_at=_now_iso(),
        detail=("Art worker queued." if result.returncode == 0 else "Failed to queue art worker."),
        logs=[],
        qa_summary={},
    ).model_dump()
    _write_json(
        _revision_art_status_path(package_root, draft_id, revision_id),
        manifest_art,
    )
    manifest["status"] = STATUS_ART_QUEUED if result.returncode == 0 else STATUS_ART_FAILED
    manifest["art_status"] = STATUS_ART_QUEUED if result.returncode == 0 else STATUS_ART_FAILED
    manifest["art"] = manifest_art
    _save_manifest(package_root, draft_id, manifest)
    return payload


def art_status(package_root: Path, draft_id: str) -> dict[str, Any]:
    from .core import _art_status_from_disk
    package_root = package_root.resolve()
    manifest = _load_manifest(package_root, draft_id)
    revision_id = str(manifest.get("current_revision", "")).strip()
    status = _art_status_from_disk(package_root, draft_id, revision_id, manifest)
    original_status = status.model_dump()
    unit_name = str(status.unit_name or "").strip()
    if unit_name:
        sub_state = _systemd_unit_property(unit_name, "SubState")
        if sub_state in {"running", "start", "start-pre", "start-post"} and status.status == STATUS_ART_QUEUED:
            status = WorldBuilderArtStatusSpec.model_validate(
                {
                    **status.model_dump(),
                    "status": STATUS_ART_RUNNING,
                    "detail": "Art worker is running.",
                    "updated_at": _now_iso(),
                }
            )
        elif sub_state == "failed" and status.status in {STATUS_ART_QUEUED, STATUS_ART_RUNNING}:
            status = WorldBuilderArtStatusSpec.model_validate(
                {
                    **status.model_dump(),
                    "status": STATUS_ART_FAILED,
                    "detail": "Art worker failed according to systemd.",
                    "updated_at": _now_iso(),
                }
            )
    if status.status in {STATUS_ART_QUEUED, STATUS_ART_RUNNING} and status.updated_at:
        try:
            dt_str = status.updated_at
            if dt_str.endswith("Z"):
                dt_str = dt_str[:-1] + "+00:00"
            updated_dt = datetime.fromisoformat(dt_str)
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            elapsed_seconds = (now_dt - updated_dt).total_seconds()
            timeout_limit = int(manifest.get("art_generation_timeout_seconds", 600))
            if elapsed_seconds > timeout_limit:
                status = WorldBuilderArtStatusSpec.model_validate(
                    {
                        **status.model_dump(),
                        "status": STATUS_ART_FAILED,
                        "detail": f"Art generation timed out after {elapsed_seconds:.1f}s (limit {timeout_limit}s). Failing the pipeline instead of skipping QA.",
                        "updated_at": _now_iso(),
                    }
                )
        except Exception as e:
            print(f"[ART_TIMEOUT_CHECK_FAILED] error={e}", flush=True)
    if status.model_dump() != original_status:
        manifest["art"] = status.model_dump()
        manifest["art_status"] = status.status
        if status.status in {STATUS_ART_RUNNING, STATUS_ART_FAILED}:
            manifest["status"] = status.status
        elif status.status == STATUS_ART_TIMEOUT_SKIPPED:
            manifest["status"] = STATUS_PUBLISH_READY
        _save_manifest(package_root, draft_id, manifest)
    return {
        "draft_id": draft_id,
        "revision_id": revision_id,
        "art": status.model_dump(),
    }
