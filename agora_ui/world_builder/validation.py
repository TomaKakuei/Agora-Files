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



def _validate_revision_agents(scenario_dir: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "manifest_ok": False,
        "manifest_agent_refs_ok": False,
        "agent_schema_ok": False,
        "agent_count": 0,
        "active_agent_count": 0,
        "validated_agents": [],
        "manifest_path": str(scenario_dir / "manifest.json"),
        "error": "",
    }
    manifest_path = scenario_dir / "manifest.json"
    if not manifest_path.is_file():
        report["error"] = "manifest.json is missing"
        return report
    try:
        manifest = ScenarioManifestSpec.model_validate(_read_json(manifest_path))
        report["manifest_ok"] = True
    except Exception as exc:
        report["error"] = str(exc)
        return report

    active_agents = [str(ref).strip() for ref in manifest.asset_bindings.active_agents if str(ref).strip()]
    report["active_agent_count"] = len(active_agents)
    if not active_agents:
        report["error"] = "manifest asset_bindings.active_agents is empty"
        return report

    agent_paths: list[Path] = []
    missing_refs: list[str] = []
    for ref in active_agents:
        resolved = _scenario_relative_path(scenario_dir, ref)
        if not resolved.is_file():
            missing_refs.append(ref)
            continue
        agent_paths.append(resolved)
    if missing_refs:
        report["error"] = "missing agent reference(s): " + ", ".join(missing_refs[:5])
        return report
    report["manifest_agent_refs_ok"] = True

    validated_agents: list[str] = []
    try:
        for agent_path in agent_paths:
            payload = _read_json(agent_path)
            AgentRuntimeProfileSpec.model_validate(payload)
            validated_agents.append(str(agent_path.relative_to(scenario_dir)).replace("\\", "/"))
        report["agent_schema_ok"] = True
        report["agent_count"] = len(agent_paths)
        report["validated_agents"] = validated_agents
        return report
    except Exception as exc:
        report["error"] = str(exc)
        report["agent_count"] = len(agent_paths)
        report["validated_agents"] = validated_agents
        return report


def _startup_validation_for_package_db(
    package_root: Path,
    package_db: Path,
    *,
    display_name: str,
) -> dict[str, Any]:
    mocked = _get_mocked_fallback("_startup_validation_for_package_db", _startup_validation_for_package_db)
    if mocked is not _startup_validation_for_package_db:
        return mocked(package_root, package_db, display_name=display_name)

    (package_root / "output").mkdir(parents=True, exist_ok=True)
    smoke_root = Path(tempfile.mkdtemp(prefix="agora_world_creator_startup_", dir=str(package_root / "output")))
    access_code = f"smoke_{uuid4().hex[:16]}"
    try:
        export_dir = smoke_root / "output" / "package_exports" / access_code
        export_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package_db, export_dir / "world_package.db")
        mocked_startup = _get_mocked_fallback("validate_world_package_startup", validate_world_package_startup)
        report = mocked_startup(
            smoke_root,
            access_code,
            display_name=display_name,
        )
        report["package_root"] = str(package_root.resolve())
        report["package_db"] = str(package_db.resolve())
        return report
    finally:
        shutil.rmtree(smoke_root, ignore_errors=True)


def _pixel_launch_validation_for_package_db(
    package_root: Path,
    package_db: Path,
    *,
    display_name: str,
    seed: int,
) -> dict[str, Any]:
    mocked = _get_mocked_fallback("_pixel_launch_validation_for_package_db", _pixel_launch_validation_for_package_db)
    if mocked is not _pixel_launch_validation_for_package_db:
        return mocked(package_root, package_db, display_name=display_name, seed=seed)
    (package_root / "output").mkdir(parents=True, exist_ok=True)
    export_root = package_root / "output" / "package_exports"
    export_root.mkdir(parents=True, exist_ok=True)
    access_code = uuid4().hex[:16]
    export_dir = export_root / access_code
    try:
        shutil.rmtree(export_dir, ignore_errors=True)
        export_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package_db, export_dir / "world_package.db")
        with sqlite3.connect(export_dir / "world_package.db") as conn:
            conn.execute(
                """
                INSERT INTO meta(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("validation_probe", "1"),
            )
            conn.execute(
                """
                INSERT INTO meta(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("validation_probe_created_at", _now_iso()),
            )
            conn.commit()
        ensure_materialized_world_package(export_dir / "world_package.db", output_dir=export_dir / "materialized")
        mocked_launch = _get_mocked_fallback("validate_pixel_ui_launch", validate_pixel_ui_launch)
        report = mocked_launch(
            package_root,
            access_code,
            seed=seed,
        )
        report["package_root"] = str(package_root.resolve())
        report["package_db"] = str(package_db.resolve())
        report["display_name"] = display_name
        # Promote: clear validation_probe after successful validation so the
        # world becomes publicly visible in the frontend catalog.
        # If validation failed, the probe flag stays set and the world remains
        # correctly hidden from the catalog.
        if bool(report.get("startup_ok", False)):
            try:
                with sqlite3.connect(export_dir / "world_package.db") as conn:
                    conn.execute("DELETE FROM meta WHERE key = 'validation_probe'")
                    conn.execute("DELETE FROM meta WHERE key = 'validation_probe_created_at'")
                    conn.commit()
            except Exception:
                pass  # Non-fatal: world just stays hidden until next successful validation
        return report
    finally:
        # Keep the export dir: successful probes are promoted above,
        # failed probes are kept for debugging.
        pass


def _validation_workspace(
    package_root: Path,
    config: dict[str, Any],
    *,
    finalize_agents: bool = False,
    provider: VertexJsonClient | None = None,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    temp_root = Path(tempfile.mkdtemp(prefix="agora_world_creator_validate_", dir=str(package_root / "output")))
    try:
        run_inputs_dir = temp_root / "run_inputs"
        run_inputs_dir.mkdir(parents=True, exist_ok=True)
        _write_json(run_inputs_dir / "world_config.json", config)
        scenario_dir = run_inputs_dir / "scenario"
        
        from ..agent_factory import _build_agent_payloads, _vertex_agent_profile_payloads, _vertex_initial_inventory_payloads
        agent_payloads = _build_agent_payloads(config)
        
        if finalize_agents and provider is not None:
            agent_payloads = _vertex_agent_profile_payloads(
                provider,
                config,
                agent_payloads,
            )
            agent_payloads = _vertex_initial_inventory_payloads(
                provider,
                config,
                agent_payloads,
            )

        materialize_scenario(config, scenario_dir, agent_payloads=agent_payloads)
        source_assets = package_root / "frontend" / "assets" / "generated"
        if source_assets.is_dir():
            shutil.copytree(source_assets, temp_root / "assets" / "generated", dirs_exist_ok=True)
        package_db = temp_root / "world_package.db"
        pixel_report = assess_pixel_readiness_from_root(temp_root)
        agent_validation = _validate_revision_agents(scenario_dir)
        pack_world_package(
            temp_root,
            package_db,
            package_name=str(config.get("scenario_meta", {}).get("world_name", "World Creator Draft")),
            source_label="world_creator_draft_validation",
            extra_meta={
                "pixel_read": pixel_report.get("pixel_read", False),
                "pixel_read_report": json.dumps(pixel_report, ensure_ascii=False),
                "startup_validation_report": json.dumps(agent_validation, ensure_ascii=False),
            },
        )
        metadata = read_world_package_metadata(package_db)
        startup_validation = _startup_validation_for_package_db(
            package_root,
            package_db,
            display_name=str(config.get("scenario_meta", {}).get("world_name", "World Creator Draft")),
        )
        if not (
            agent_validation.get("manifest_ok", False)
            and agent_validation.get("manifest_agent_refs_ok", False)
            and agent_validation.get("agent_schema_ok", False)
        ):
            raise ValueError(f"Revision agent validation failed: {json.dumps(agent_validation, ensure_ascii=False)}")
        if not bool(startup_validation.get("startup_ok", False)):
            raise ValueError(f"Revision startup validation failed: {json.dumps(startup_validation, ensure_ascii=False)}")
        persistent_handle = tempfile.NamedTemporaryFile(
            prefix="agora_world_creator_pkg_",
            suffix=".db",
            dir=str(package_root / "output"),
            delete=False,
        )
        persistent_handle.close()
        persistent_path = Path(persistent_handle.name)
        shutil.copy2(package_db, persistent_path)
        validation = {
            "materialize_ok": package_contains_paths(
                package_db,
                [
                    "run_inputs/world_config.json",
                    "run_inputs/scenario/map_grid.json",
                    "run_inputs/scenario/manifest.json",
                ],
            ),
            "package_kind": metadata.get("package_kind", ""),
            "package_version": metadata.get("package_version", ""),
            "pixel_read": bool(pixel_report.get("pixel_read", False)),
            "pixel_read_report": pixel_report,
            "agent_validation": agent_validation,
            "startup_validation": startup_validation,
        }
        return persistent_path, validation, agent_payloads
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


