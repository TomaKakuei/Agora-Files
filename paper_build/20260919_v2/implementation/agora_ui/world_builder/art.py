from __future__ import annotations
import argparse
import base64
import io
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


def _map_qa_codes_with_textual_evidence(
    error_codes: list[str],
    reasoning: str,
) -> list[str]:
    reasoning_folded = str(reasoning or "").casefold()
    evidence_terms = {
        "component_perspective_drift": {
            "perspective",
            "isometric",
            "front face",
            "side face",
            "eye-level",
            "horizon",
            "footprint",
            "projection",
        },
        "floor_perspective_drift": {
            "perspective",
            "isometric",
            "eye-level",
            "horizon",
            "projection",
            "floor",
            "room plate",
        },
    }
    supported: list[str] = []
    for raw_code in error_codes:
        code = str(raw_code or "").strip()
        required_terms = evidence_terms.get(code)
        if required_terms and not any(term in reasoning_folded for term in required_terms):
            continue
        if code:
            supported.append(code)
    return supported or ["none"]


def _map_qa_codes_with_compiler_evidence(
    error_codes: list[str],
    reasoning: str,
    semantic_component_coverage: dict[str, Any],
) -> list[str]:
    compiler_verified = bool(
        semantic_component_coverage.get("status") == "ok"
        and int(semantic_component_coverage.get("expected_count", 0) or 0) > 0
        and int(semantic_component_coverage.get("placed_count", 0) or 0)
        == int(semantic_component_coverage.get("expected_count", 0) or 0)
        and not semantic_component_coverage.get("missing_component_ids")
        and not semantic_component_coverage.get("unreadable_component_ids")
    )
    reasoning_folded = str(reasoning or "").casefold()
    unsupported_absence_claim = bool(
        compiler_verified
        and "blank_void" in error_codes
        and re.search(
            r"(missing|lacks?|without|no)\b.{0,48}\b(required )?(semantic )?(component|prop)s?"
            r"|(semantic )?(component|prop)s?\b.{0,32}\b(missing|absent)",
            reasoning_folded,
        )
    )
    filtered = [
        code
        for code in error_codes
        if not (unsupported_absence_claim and code == "blank_void")
    ]
    return filtered or ["none"]


def _map_floor_projection_certificate(
    map_path: Path,
    room_ids: list[str],
) -> dict[str, Any]:
    floor_root = map_path.parent / "floors"
    certified_room_ids: list[str] = []
    reports: list[dict[str, Any]] = []
    for room_id in room_ids:
        report_path = floor_root / f"floor_{room_id}.qa.json"
        report = _read_json(report_path) if report_path.is_file() else {}
        certified = bool(
            report.get("pass") is True
            and report.get("size_ok") is True
            and str(report.get("geometry_conditioning", "")).strip()
            == "procedural_visual_canon_floor"
            and str(report.get("render_mode", "")).strip() == "layered"
        )
        if certified:
            certified_room_ids.append(room_id)
        reports.append(
            {
                "room_id": room_id,
                "certified_flat": certified,
                "report_path": str(report_path),
            }
        )
    return {
        "status": "ok" if room_ids and len(certified_room_ids) == len(room_ids) else "incomplete",
        "expected_room_count": len(room_ids),
        "certified_room_count": len(certified_room_ids),
        "certified_room_ids": certified_room_ids,
        "reports": reports,
    }


def _map_dimension_contract(
    config: dict[str, Any],
    actual_size: tuple[int, int],
) -> dict[str, Any]:
    space = config.get("space", {}) if isinstance(config.get("space", {}), dict) else {}
    pipeline = (
        config.get("pixel_asset_pipeline", {})
        if isinstance(config.get("pixel_asset_pipeline", {}), dict)
        else {}
    )
    map_generation = (
        pipeline.get("map_generation", {})
        if isinstance(pipeline.get("map_generation", {}), dict)
        else {}
    )
    tile_px = int(map_generation.get("tile_px", 32) or 32)
    margin_px = max(0, int(map_generation.get("margin_px", 0) or 0))
    expected_size = (
        int(space.get("width_tiles", 0) or 0) * tile_px + margin_px * 2,
        int(space.get("height_tiles", 0) or 0) * tile_px + margin_px * 2,
    )
    passed = (
        expected_size[0] > 0
        and expected_size[1] > 0
        and tuple(actual_size) == expected_size
    )
    return {
        "pass": passed,
        "expected_size": list(expected_size),
        "actual_size": list(actual_size),
        "error_code": "" if passed else "margin_contract_mismatch",
    }


def _semantic_component_coverage(
    config: dict[str, Any],
    component_sidecar: dict[str, Any],
    *,
    sidecar_path: str = "",
) -> dict[str, Any]:
    space = config.get("space", {}) if isinstance(config.get("space", {}), dict) else {}
    expected = {
        str(component.get("component_id", "")).strip()
        for room in space.get("rooms", [])
        if isinstance(room, dict)
        for component in (
            room.get("visual", {}).get("scene_components", [])
            if isinstance(room.get("visual", {}), dict)
            else []
        )
        if isinstance(component, dict) and str(component.get("component_id", "")).strip()
    }
    sidecar_schema = str(component_sidecar.get("schema_version", "")).strip()
    requires_readability = sidecar_schema == "agora.map_component_placements.v2"
    pasted = {
        str(placement.get("component_id", "")).strip()
        for placement in component_sidecar.get("placements", [])
        if isinstance(placement, dict)
        and placement.get("semantic_generated") is True
        and placement.get("pasted") is True
        and str(placement.get("component_id", "")).strip()
    }
    placed = {
        str(placement.get("component_id", "")).strip()
        for placement in component_sidecar.get("placements", [])
        if isinstance(placement, dict)
        and placement.get("semantic_generated") is True
        and placement.get("pasted") is True
        and (not requires_readability or placement.get("readability_pass") is True)
        and str(placement.get("component_id", "")).strip()
    }
    missing = sorted(expected - pasted)
    unreadable = sorted((expected & pasted) - placed)
    return {
        "status": "ok" if not missing and not unreadable else "error",
        "expected_count": len(expected),
        "placed_count": len(expected & placed),
        "missing_component_ids": missing,
        "unreadable_component_ids": unreadable,
        "sidecar_schema": sidecar_schema,
        "sidecar_path": sidecar_path,
    }


def _normalize_map_qa_repair_localization(
    *,
    error_codes: list[str],
    failing_room_names: list[str],
    room_names: list[str],
    repair_scope: str,
    reasoning: str,
) -> tuple[list[str], list[str], str]:
    actionable_codes = [code for code in error_codes if code and code != "none"]
    if not actionable_codes:
        return ["none"], [], "none"

    room_repair_codes = {
        "visible_text",
        "baked_character",
        "clipped_room_plate",
        "perspective_drift",
        "component_perspective_drift",
        "floor_perspective_drift",
        "palette_drift",
    }
    compositor_only_codes = {
        "blank_void",
        "door_transition_error",
        "margin_contract_mismatch",
    }
    if (
        any(code in room_repair_codes for code in actionable_codes)
        and not any(code in compositor_only_codes for code in actionable_codes)
    ):
        known_names = {name.casefold(): name for name in room_names if name}
        localized_names = [
            known_names[name.casefold()]
            for name in failing_room_names
            if name.casefold() in known_names
        ]
        if not localized_names:
            reasoning_folded = reasoning.casefold()
            localized_names = [
                name
                for name in room_names
                if name and name.casefold() in reasoning_folded
            ]
        if not localized_names:
            localized_names = list(room_names)
        return actionable_codes, list(dict.fromkeys(localized_names)), "room_asset"

    return actionable_codes, failing_room_names, repair_scope



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
    current_manifest_path = source_generated_root / "world_asset_sets" / "current_world_pixel_set.json"
    if current_manifest_path.is_file():
        current_manifest = _read_json(current_manifest_path)
        if str(current_manifest.get("world_revision", "")).strip() == revision_slug:
            # Asset revisions evolve independently of the immutable world
            # revision. Prefer the provenance-matching live manifest so a
            # repack does not silently roll character art back.
            manifest_payload = current_manifest
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


def _run_gemini_map_qa(
    config: dict[str, Any],
    map_path: Path,
    screenshot_path: Path | None = None,
) -> dict[str, Any]:
    from ..vertex_json_client import VertexJsonClient
    screenshot_available = bool(screenshot_path is not None and screenshot_path.is_file())
    if not map_path.is_file() or (screenshot_path is not None and not screenshot_available):
        return {
            "status": "error",
            "reasoning": (
                f"Missing images: map_exists={map_path.is_file()}, "
                f"screenshot_exists={screenshot_available}"
            ),
            "is_pixel_map": "N",
            "has_visual_errors": "Y"
        }
    try:
        from PIL import Image
        with Image.open(map_path) as map_image:
            actual_size = map_image.size
        dimension_contract = _map_dimension_contract(config, actual_size)
        expected_size = tuple(dimension_contract["expected_size"])
        if not dimension_contract["pass"]:
            return {
                "status": "ok",
                "is_pixel_map": "Y",
                "has_visual_errors": "Y",
                "reasoning": f"Map dimension contract failed: expected {expected_size}, got {actual_size}.",
                "error_codes": ["margin_contract_mismatch"],
                "failing_room_names": [],
                "repair_scope": "compositor",
                "expected_size": list(expected_size),
                "actual_size": list(actual_size),
            }
        space = config.get("space", {}) if isinstance(config.get("space", {}), dict) else {}
        component_sidecar_path = map_path.with_suffix(".components.json")
        component_sidecar = (
            json.loads(component_sidecar_path.read_text(encoding="utf-8"))
            if component_sidecar_path.is_file()
            else {}
        )
        semantic_component_coverage = _semantic_component_coverage(
            config,
            component_sidecar,
            sidecar_path=str(component_sidecar_path),
        )
        missing_semantic_components = semantic_component_coverage[
            "missing_component_ids"
        ]
        unreadable_semantic_components = semantic_component_coverage[
            "unreadable_component_ids"
        ]
        room_ids = [
            str(room.get("room_id", "")).strip()
            for room in space.get("rooms", [])
            if isinstance(room, dict) and str(room.get("room_id", "")).strip()
        ]
        floor_projection_certificate = _map_floor_projection_certificate(
            map_path,
            room_ids,
        )
        if missing_semantic_components or unreadable_semantic_components:
            compiler_failures = missing_semantic_components + unreadable_semantic_components
            return {
                "status": "ok",
                "is_pixel_map": "Y",
                "has_visual_errors": "Y",
                "reasoning": (
                    "Compiler semantic-component visibility contract failed: "
                    + ", ".join(compiler_failures)
                ),
                "error_codes": [
                    (
                        "semantic_prop_unreadable"
                        if unreadable_semantic_components
                        else "semantic_prop_missing"
                    )
                ],
                "failing_room_names": [],
                "repair_scope": "compositor",
                "expected_size": list(expected_size),
                "actual_size": list(actual_size),
                "semantic_component_coverage": semantic_component_coverage,
            }
        loaded_env = _load_creator_runtime_env()
        for key, value in loaded_env.items():
            if key not in os.environ:
                os.environ[key] = value
        api_key = (
            str(os.environ.get("AGORA_AISTUDIO_API_KEY", "")).strip()
            or str(os.environ.get("AGORA_GEMINI_API_KEY", "")).strip()
            or str(os.environ.get("GEMINI_API_KEY", "")).strip()
            or str(os.environ.get("GOOGLE_API_KEY", "")).strip()
        )
        if api_key and not os.environ.get("AGORA_AISTUDIO_API_KEY"):
            os.environ["AGORA_AISTUDIO_API_KEY"] = api_key
        map_qa_model = (
            str(os.environ.get("AGORA_MAP_QA_MODEL", "")).strip()
            or str(os.environ.get("AGORA_WORLD_CREATOR_LITE_MODEL", "")).strip()
            or "gemini-3.1-flash-lite-preview"
        )
        try:
            map_qa_max_output_tokens = int(
                str(os.environ.get("AGORA_MAP_QA_MAX_OUTPUT_TOKENS", "2048")).strip()
            )
        except ValueError:
            map_qa_max_output_tokens = 2048
        map_qa_max_output_tokens = max(1024, min(8192, map_qa_max_output_tokens))
        map_qa_config = {
            "vertex_api": {
                "backend": str(os.environ.get("AGORA_VERTEX_BACKEND", "ai_studio")).strip() or "ai_studio",
                "model": map_qa_model,
                "api_key_env": "AGORA_AISTUDIO_API_KEY",
                "temperature": 0.0,
                "max_output_tokens": map_qa_max_output_tokens,
                "invalid_json_retry_max_output_tokens": 4096,
                "thinking_level": "low",
                "thinking_budget": 128,
                "timeout_seconds": 180,
                "retry": {
                    "max_attempts": 3,
                    "initial_sleep_seconds": 5.0,
                    "max_sleep_seconds": 30.0,
                    "backoff_multiplier": 2.0,
                    "status_codes": [408, 429, 500, 502, 503, 504],
                },
                "stages": {
                    "map_qa": {
                        "model": map_qa_model,
                        "max_output_tokens": map_qa_max_output_tokens,
                        "invalid_json_retry_max_output_tokens": 4096,
                        "thinking_level": "low",
                        "thinking_budget": 128,
                        "temperature": 0.0,
                    }
                },
            }
        }
        qa_rooms = [
            room
            for room in space.get("rooms", [])
            if isinstance(room, dict) and str(room.get("name", "")).strip()
        ]
        rooms = [str(room.get("name", "")).strip() for room in qa_rooms]
        room_boxes = []
        expected_room_content = []
        for room in qa_rooms:
            left = margin_px + int(room.get("x_pos", room.get("x", 0)) or 0) * tile_px
            top = margin_px + int(room.get("y_pos", room.get("y", 0)) or 0) * tile_px
            right = left + max(1, int(room.get("width_tiles", 1) or 1)) * tile_px
            bottom = top + max(1, int(room.get("height_tiles", 1) or 1)) * tile_px
            room_boxes.append(
                {
                    "name": str(room.get("name", "")).strip(),
                    "pixel_box": [left, top, right, bottom],
                }
            )
            visual = room.get("visual", {}) if isinstance(room.get("visual", {}), dict) else {}
            metadata = room.get("metadata", {}) if isinstance(room.get("metadata", {}), dict) else {}
            expected_room_content.append(
                {
                    "name": str(room.get("name", "")).strip(),
                    "purpose": str(metadata.get("purpose", "")).strip(),
                    "expected_components": [
                        {
                            "component_id": str(component.get("component_id", "")).strip(),
                            "label": str(component.get("label", "")).strip(),
                            "description": str(component.get("description", "")).strip(),
                        }
                        for component in visual.get("scene_components", [])
                        if isinstance(component, dict)
                        and (
                            str(component.get("label", "")).strip()
                            or str(component.get("description", "")).strip()
                        )
                    ],
                }
            )
        map_b64 = base64.b64encode(map_path.read_bytes()).decode("utf-8")
        media_parts = [{"inlineData": {"mimeType": "image/png", "data": map_b64}}]
        with Image.open(map_path) as source_map:
            source_rgb = source_map.convert("RGB")
            cell_width = 256
            cell_height = 224
            header_height = 28
            columns = 3
            rows = max(1, math.ceil(len(room_boxes) / columns))
            atlas = Image.new("RGB", (columns * cell_width, rows * cell_height), "#111820")
            from PIL import ImageDraw, ImageOps

            draw = ImageDraw.Draw(atlas)
            for index, room_box in enumerate(room_boxes):
                left, top, right, bottom = room_box["pixel_box"]
                crop = source_rgb.crop((left, top, right, bottom))
                fitted = ImageOps.contain(
                    crop,
                    (cell_width - 8, cell_height - header_height - 8),
                    method=Image.Resampling.NEAREST,
                )
                column = index % columns
                row = index // columns
                cell_left = column * cell_width
                cell_top = row * cell_height
                paste_left = cell_left + (cell_width - fitted.width) // 2
                paste_top = cell_top + header_height + (
                    cell_height - header_height - fitted.height
                ) // 2
                atlas.paste(fitted, (paste_left, paste_top))
                draw.text(
                    (cell_left + 6, cell_top + 7),
                    f"{index + 1}. {room_box['name']}",
                    fill="#ffffff",
                )
            atlas_buffer = io.BytesIO()
            atlas.save(atlas_buffer, format="PNG")
        media_parts.append(
            {
                "inlineData": {
                    "mimeType": "image/png",
                    "data": base64.b64encode(atlas_buffer.getvalue()).decode("utf-8"),
                }
            }
        )
        component_reference_available = False
        component_atlas = Image.new(
            "RGB",
            (columns * cell_width, rows * cell_height),
            "#111820",
        )
        component_draw = ImageDraw.Draw(component_atlas)
        component_icon_root = map_path.parent / "component_generation" / "icons"
        for index, room in enumerate(qa_rooms):
            column = index % columns
            row = index // columns
            cell_left = column * cell_width
            cell_top = row * cell_height
            component_draw.text(
                (cell_left + 6, cell_top + 7),
                f"{index + 1}. {room_boxes[index]['name']}",
                fill="#ffffff",
            )
            components = [
                component
                for component in room.get("visual", {}).get("scene_components", [])
                if isinstance(component, dict) and str(component.get("component_id", "")).strip()
            ][:2]
            for component_index, component in enumerate(components):
                component_id = str(component.get("component_id", "")).strip()
                icon_path = component_icon_root / f"prop_{component_id}.png"
                if not icon_path.is_file():
                    continue
                with Image.open(icon_path) as component_icon:
                    fitted_icon = ImageOps.contain(
                        component_icon.convert("RGBA"),
                        (96, 96),
                        method=Image.Resampling.NEAREST,
                    )
                icon_left = cell_left + 20 + component_index * 116
                icon_top = cell_top + 58
                component_atlas.paste(fitted_icon, (icon_left, icon_top), fitted_icon)
                component_reference_available = True
        if component_reference_available:
            component_buffer = io.BytesIO()
            component_atlas.save(component_buffer, format="PNG")
            media_parts.append(
                {
                    "inlineData": {
                        "mimeType": "image/png",
                        "data": base64.b64encode(component_buffer.getvalue()).decode("utf-8"),
                    }
                }
            )
        if screenshot_available and screenshot_path is not None:
            screenshot_b64 = base64.b64encode(screenshot_path.read_bytes()).decode("utf-8")
            media_parts.append({"inlineData": {"mimeType": "image/png", "data": screenshot_b64}})
        client = VertexJsonClient(map_qa_config)
        visual_canon = config.get("pixel_asset_pipeline", {}).get("visual_canon", {})
        qa_visual_canon = dict(visual_canon) if isinstance(visual_canon, dict) else {}
        qa_visual_canon["camera"] = {
            "projection": "strict_top_down_or_shallow_three_quarter_top_down",
            "rule": (
                "collision-aligned 2D game projection; a strict top-down substrate may use shallow "
                "three-quarter object sprites with readable footprints, but never eye-level or deep perspective"
            ),
        }
        prompt = (
            "Image 1 is the authoritative full stitched source map. "
            "Image 2 is an enlarged room-by-room inspection atlas in the same order as the known room list. "
            "The white text in Image 2 headers is an external QA annotation and is not part of the world art. "
            "Inspect every atlas cell independently for baked figures and projection drift before returning a verdict. "
        )
        if component_reference_available:
            prompt += (
                "Image 3 is a room-aligned reference atlas of the actual generated semantic component icons. "
                "Its white headers are external QA annotations. Compare these icon silhouettes with Images 1 and 2 "
                "before reporting a semantic component as missing. "
            )
        if screenshot_available:
            screenshot_index = 4 if component_reference_available else 3
            prompt += (
                f"Image {screenshot_index} is a live browser camera viewport that may intentionally crop rooms outside the current view. "
            )
        prompt += (
            f"Known room names and authoritative source-map pixel boxes: {room_boxes}. "
            f"Expected semantic content per room: {expected_room_content}. "
            f"Shared visual canon: {qa_visual_canon}. "
            f"Compiler floor-projection certificate: {floor_projection_certificate}. "
            "Judge full-world room presence, layout, and connectivity only from image 1. "
            "Atlas headers and pixel boxes are authoritative room identities; do not relabel a room by guessing from style. "
            "The map dimensions have already been checked in code, so do not report margin_contract_mismatch when "
            "expected_size equals actual_size. "
        )
        if screenshot_available:
            prompt += (
                f"Use image {screenshot_index} only to confirm that the map and agents render cleanly in the live client. "
                "Dialogue bubbles are expected transient UI; report visible_text only for text baked into Image 1 room art. "
            )
        prompt += (
            "Return localized failures using only room names from the known list. "
            "Return fields in schema order and keep reasoning to one sentence of at most 20 words."
        )
        system_instruction = (
            "You are a strict render-and-verify reviewer for a generated persistent pixel world. "
            "The map must have coherent top-down or three-quarter-top-down perspective, shared palette and materials, "
            "readable connected rooms, clean door transitions, visible semantic props, no unintended text, and no "
            "people or humanoid figures baked into static room art because live agents are rendered separately. "
            "Fail clipped/floating room plates, poster-like margins, blank voids, labels baked into art, severe perspective "
            "or palette drift, unreadable tiny agents, dense debugging overlays, and dimension/margin errors. "
            "Ordinary browser chrome and the fixed test-harness status outside the game canvas are not map defects; "
            "judge unintended text only when it is inside the rendered world canvas or baked into the source map. "
            "When a live browser image is provided, it is a camera viewport, not an overview; never mark a room or "
            "semantic prop missing merely because it is offscreen there when it is present in the full source map. "
            "The operational tile-map projection accepts either consistent strict top-down or consistent shallow "
            "three-quarter top-down. A strict top-down floor with shallow extruded object sprites is a compatible "
            "2D game convention, not projection drift, when footprints and anchors remain clear. Fail eye-level, "
            "deep one-point perspective, dominant front/side faces, or objects whose footprint becomes ambiguous. "
            "Semantic component presence is compiler-verified separately; judge visual legibility but never report a "
            "component missing or a room swapped based only on interpreting an abstract icon. "
            "An abstract or symbolic top-down component remains valid when its compiler-verified footprint is readable; "
            "do not convert a preference for more detail into a perspective error. "
            "When the compiler floor-projection certificate is complete, do not attribute perspective drift to room floors; "
            "only report concrete front/side-face defects in generated semantic components. "
            "Use component_perspective_drift only when semantic props expose deep incompatible front or side faces "
            "or lose their collision footprint; a shallow rim, extrusion, or small cast shadow is acceptable. "
            "Use floor_perspective_drift only when a room plate itself has incompatible perspective. "
            "Do not fail intentional premise-specific stylistic differences that remain compatible with the shared canon."
        )
        schema = {
            "type": "object",
            "properties": {
                "is_pixel_map": {"type": "string", "enum": ["Y", "N"]},
                "has_visual_errors": {"type": "string", "enum": ["Y", "N"]},
                "error_codes": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "visible_text",
                            "baked_character",
                            "clipped_room_plate",
                            "blank_void",
                            "perspective_drift",
                            "component_perspective_drift",
                            "floor_perspective_drift",
                            "palette_drift",
                            "door_transition_error",
                            "margin_contract_mismatch",
                            "debug_overlay_density",
                            "agent_readability",
                            "none"
                        ],
                    },
                },
                "failing_room_names": {"type": "array", "items": {"type": "string"}},
                "repair_scope": {
                    "type": "string",
                    "enum": ["none", "room_asset", "compositor", "frontend", "mixed"],
                },
                "reasoning": {"type": "string"},
            },
            "required": [
                "is_pixel_map",
                "has_visual_errors",
                "error_codes",
                "failing_room_names",
                "repair_scope",
                "reasoning"
            ]
        }
        result = client.generate_multimodal_json(
            system_instruction=system_instruction,
            prompt=prompt,
            schema=schema,
            stage="map_qa",
            media_parts=media_parts
        )
        reviewer_reasoning_raw = str(result.get("reasoning", "")).strip()
        error_codes = _map_qa_codes_with_textual_evidence(
            [str(value).strip() for value in result.get("error_codes", []) if str(value).strip()],
            reviewer_reasoning_raw,
        )
        error_codes = _map_qa_codes_with_compiler_evidence(
            error_codes,
            reviewer_reasoning_raw,
            semantic_component_coverage,
        )
        if (
            floor_projection_certificate.get("status") == "ok"
            and "perspective_drift" in error_codes
        ):
            error_codes = [
                "component_perspective_drift" if code == "perspective_drift" else code
                for code in error_codes
            ]
        failing_room_names = [
            str(value).strip()
            for value in result.get("failing_room_names", [])
            if str(value).strip() in rooms
        ]
        repair_scope = str(result.get("repair_scope", "mixed")).strip()
        actionable_error_codes = [code for code in error_codes if code != "none"]
        has_visual_errors = str(result.get("has_visual_errors", "Y")).strip()
        reasoning = reviewer_reasoning_raw
        if not actionable_error_codes:
            error_codes = ["none"]
            failing_room_names = []
            repair_scope = "none"
            has_visual_errors = "N"
            reasoning = (
                "The structured reviewer returned no actionable render defect. "
                f"Compiler placement verified {semantic_component_coverage['placed_count']}/"
                f"{semantic_component_coverage['expected_count']} semantic components."
            )
        error_codes, failing_room_names, repair_scope = _normalize_map_qa_repair_localization(
            error_codes=error_codes,
            failing_room_names=failing_room_names,
            room_names=rooms,
            repair_scope=repair_scope,
            reasoning=reviewer_reasoning_raw,
        )
        return {
            "status": "ok",
            "is_pixel_map": result.get("is_pixel_map", "N"),
            "has_visual_errors": has_visual_errors,
            "reasoning": reasoning,
            "reviewer_reasoning_raw": reviewer_reasoning_raw,
            "error_codes": error_codes,
            "failing_room_names": failing_room_names,
            "repair_scope": repair_scope,
            "expected_size": list(expected_size),
            "actual_size": list(actual_size),
            "semantic_component_coverage": semantic_component_coverage,
            "floor_projection_certificate": floor_projection_certificate,
        }
    except Exception as e:
        return {
            "status": "error",
            "reasoning": f"Gemini API error: {str(e)}",
            "is_pixel_map": "N",
            "has_visual_errors": "Y",
            "error_codes": ["qa_provider_error"],
            "failing_room_names": [],
            "repair_scope": "mixed",
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
            "--skip-map-prompt",
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

    map_qa_path = _revision_dir(package_root, draft_id, revision_id) / "map_visual_qa.json"
    map_qa_history_path = _revision_dir(package_root, draft_id, revision_id) / "map_visual_qa_history.json"
    qa_result = _run_gemini_map_qa(config, map_path, screenshot_path)
    prior_history_payload = _read_json(map_qa_history_path) if map_qa_history_path.is_file() else {}
    qa_history = [
        dict(entry)
        for entry in prior_history_payload.get("attempts", [])
        if isinstance(entry, dict)
    ]
    validation_run = max(
        [int(entry.get("validation_run", 0) or 0) for entry in qa_history] or [0]
    ) + 1
    qa_history.append(
        {
            "validation_run": validation_run,
            "evaluated_at": _now_iso(),
            "attempt": 1,
            **qa_result,
        }
    )

    map_generation = config.get("pixel_asset_pipeline", {}).get("map_generation", {})
    max_local_repairs = min(2, max(0, int(map_generation.get("max_local_qa_repairs", 2) or 2)))
    repair_attempt = 0
    while (
        (qa_result.get("is_pixel_map") != "Y" or qa_result.get("has_visual_errors") != "N")
        and str(qa_result.get("repair_scope", "")).strip() == "room_asset"
        and repair_attempt < max_local_repairs
    ):
        repair_attempt += 1
        rooms = [
            room
            for room in config.get("space", {}).get("rooms", [])
            if isinstance(room, dict)
        ]
        room_ids_by_name = {
            str(room.get("name", "")).strip().casefold(): str(room.get("room_id", "")).strip()
            for room in rooms
            if str(room.get("name", "")).strip() and str(room.get("room_id", "")).strip()
        }
        repair_room_ids = sorted(
            {
                room_ids_by_name[name]
                for raw_name in qa_result.get("failing_room_names", [])
                if (name := str(raw_name).strip().casefold()) in room_ids_by_name
            }
        )
        repeated_projection_codes = {
            "perspective_drift",
            "component_perspective_drift",
            "floor_perspective_drift",
        }
        if (
            repair_attempt >= 2
            and any(
                str(code).strip() in repeated_projection_codes
                for code in qa_result.get("error_codes", [])
            )
        ):
            repair_room_ids = sorted(
                room_id
                for room_id in room_ids_by_name.values()
                if room_id
            )
        if not repair_room_ids:
            break
        if repair_room_ids:
            art_status.update(
                {
                    "status": STATUS_QA_FAILED_RETRYING,
                    "updated_at": _now_iso(),
                    "detail": (
                        f"Localized map QA repair {repair_attempt}/{max_local_repairs} "
                        f"is regenerating {len(repair_room_ids)} room asset(s)."
                    ),
                    "logs": logs,
                    "qa_summary": pixel_report,
                    "backend_startup_validation": backend_startup_validation,
                    "pixel_launch_validation": pixel_launch_validation,
                    "startup_validation": startup_validation,
                    "map_vision_qa": qa_result,
                }
            )
            _write_json(_revision_art_status_path(package_root, draft_id, revision_id), art_status)

            repair_command = [
                *commands[1],
                "--skip-agents",
                "--repair-attempt",
                str(repair_attempt),
            ]
            component_repair_codes = {
                "visible_text",
                "baked_character",
                "perspective_drift",
                "component_perspective_drift",
                "palette_drift",
            }
            regenerate_room_components = any(
                str(code).strip() in component_repair_codes
                for code in qa_result.get("error_codes", [])
            )
            if regenerate_room_components:
                repair_command.append("--regenerate-room-components")
            floor_repair_codes = {
                "clipped_room_plate",
                "perspective_drift",
                "floor_perspective_drift",
                "palette_drift",
            }
            if (
                regenerate_room_components
                and not any(
                    str(code).strip() in floor_repair_codes
                    for code in qa_result.get("error_codes", [])
                )
            ):
                repair_command.append("--preserve-room-floors")
            for room_id in repair_room_ids:
                repair_command.extend(["--regenerate-room-id", room_id])
            repair_result = _run_worker_command(repair_command, cwd=package_root, log_path=log_path)
            logs.append(repair_result)
            if repair_result["returncode"] == 0:
                repack_result = _repack_revision_package_with_current_assets(package_root, draft_id, revision_id)
                pixel_report = dict(repack_result.get("pixel_report", {}))
                if bool(pixel_report.get("pixel_read", False)):
                    qa_result = _run_gemini_map_qa(config, map_path)
                else:
                    qa_result = {
                        "status": "error",
                        "is_pixel_map": "N",
                        "has_visual_errors": "Y",
                        "reasoning": "PIXEL READ failed after localized room regeneration.",
                        "error_codes": ["pixel_read_after_repair"],
                        "failing_room_names": [],
                        "repair_scope": "mixed",
                    }
            else:
                qa_result = {
                    "status": "error",
                    "is_pixel_map": "N",
                    "has_visual_errors": "Y",
                    "reasoning": "Localized room asset regeneration command failed.",
                    "error_codes": ["room_asset_repair_failed"],
                    "failing_room_names": list(qa_result.get("failing_room_names", [])),
                    "repair_scope": "room_asset",
                }
            qa_history.append(
                {
                    "validation_run": validation_run,
                    "evaluated_at": _now_iso(),
                    "attempt": repair_attempt + 1,
                    "regenerated_room_ids": repair_room_ids,
                    "regenerated_room_components": regenerate_room_components,
                    **qa_result,
                }
            )

    _write_json(map_qa_path, qa_result)
    _write_json(map_qa_history_path, {"attempts": qa_history})
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
            "map_vision_qa": qa_result,
            "map_vision_qa_path": str(map_qa_path),
            "map_vision_qa_history_path": str(map_qa_history_path),
        })
        _write_json(_revision_art_status_path(package_root, draft_id, revision_id), art_status)
        manifest["status"] = STATUS_ART_FAILED
        manifest["art_status"] = STATUS_ART_FAILED
        manifest["art"] = dict(art_status)
        _save_manifest(package_root, draft_id, manifest)
        return art_status

    if repair_attempt > 0:
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
        if not bool(startup_validation.get("startup_ok", False)):
            art_status.update(
                {
                    "status": STATUS_ART_FAILED,
                    "updated_at": _now_iso(),
                    "detail": "Repaired art passed map QA but the final Pixel UI launch validation failed.",
                    "logs": logs,
                    "qa_summary": pixel_report,
                    "backend_startup_validation": backend_startup_validation,
                    "pixel_launch_validation": pixel_launch_validation,
                    "startup_validation": startup_validation,
                    "map_vision_qa": qa_result,
                    "map_vision_qa_path": str(map_qa_path),
                    "map_vision_qa_history_path": str(map_qa_history_path),
                }
            )
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
            "map_vision_qa": qa_result,
            "map_vision_qa_path": str(map_qa_path),
            "map_vision_qa_history_path": str(map_qa_history_path),
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
            timeout_limit = int(
                manifest.get(
                    "art_generation_timeout_seconds",
                    os.environ.get("AGORA_ART_GENERATION_TIMEOUT_SECONDS", "1200"),
                )
            )
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
