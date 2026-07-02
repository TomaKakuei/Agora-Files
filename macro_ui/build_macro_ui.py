from __future__ import annotations
import argparse
import base64
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import socket
import time
import secrets
import shutil
import sqlite3
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))
from .payload_formatters import *
from .process_manager import *
from .image_generation import *




DEFAULT_PY_BIN = Path("/home/yz_wang/.conda/envs/new_py310/bin/python")
RUN_INPUTS_DIRNAME = "run_inputs"
REPLAY_DIRNAME = "replay"
PROCESS_RECORD_PATH = Path("runtime/process.json")
ASSET_WORKER_RECORD_PATH = Path("runtime/asset_worker.json")
PACKAGE_EXPORTS_DIRNAME = "package_exports"
PACKAGE_META_FILENAME = "package_meta.json"

DEFAULT_GIVEN_NAMES = [
    "Airi", "Akio", "Amaya", "Asahi", "Aya", "Chihiro", "Daichi", "Emi", "Fumika", "Hana",
    "Haruto", "Hikari", "Hinata", "Ichika", "Itsuki", "Jun", "Kaede", "Kaoru", "Koharu", "Makoto",
    "Mei", "Midori", "Minato", "Nao", "Noboru", "Nozomi", "Riku", "Rio", "Rin", "Risa",
    "Saki", "Seina", "Shin", "Shiori", "Suzu", "Takumi", "Touma", "Tsukasa", "Yori", "Yui",
    "Alden", "Brisa", "Caelum", "Darian", "Elio", "Fiora", "Galen", "Iria", "Joren", "Liora",
    "Maren", "Nerin", "Orin", "Perrin", "Quilla", "Sorrel", "Tarin", "Vesper", "Wren", "Zephyr",
]
DEFAULT_FAMILY_NAMES = [
    "Aster", "Ashdown", "Briar", "Cinderfell", "Dawnmere", "Emberfall", "Fairwind", "Foxglove", "Glenmere", "Hawthorne",
    "Ironbloom", "Juniper", "Kestrel", "Larkspur", "Moonridge", "Nightbrook", "Oakfen", "Pinecrest", "Quill", "Rainmere",
    "Starfall", "Stonewell", "Sunmeadow", "Thornfield", "Vale", "Verdant", "Westmere", "Windmere", "Wrenford", "Yarrow",
]
DEFAULT_VISUAL_VARIATION = {
    "age_bands": ["young adult", "adult", "seasoned adult"],
    "skin_tones": [
        "warm brown", "light olive", "golden tan", "cool fair", "deep umber", "sun-browned",
        "soft bronze", "freckled fair", "neutral beige", "rich sienna",
    ],
    "hair_colors": [
        "black", "dark brown", "auburn", "silver", "ash blond", "copper", "deep blue-black",
        "chestnut", "platinum blond", "dark teal",
    ],
    "hair_styles": [
        "braided hair", "short layered hair", "long tied-back hair", "curly shoulder-length hair",
        "wavy cropped hair", "undercut with loose fringe", "straight bob hair", "high ponytail",
        "loose locs", "messy medium hair",
    ],
    "body_types": [
        "lean", "broad-shouldered", "compact athletic", "tall wiry", "soft sturdy", "slight agile",
        "muscular", "graceful long-limbed",
    ],
    "signature_accessories": [
        "a rune charm", "a stitched satchel", "a patterned scarf", "a brass ear cuff", "fingerless gloves",
        "a lacquered hair pin", "a weathered shoulder cape", "a leather wrist wrap", "a tiny talisman", "an enamel brooch",
    ],
    "silhouette_traits": [
        "a clear layered silhouette", "a distinctive asymmetrical hem", "a strong traveling silhouette",
        "a compact practical outline", "a cloak-forward silhouette", "a clean ceremonial outline",
    ],
}

from agora_ui.adjudicator_schemas import AgentStateBundleSpec
from agora_ui.boundary_schemas import FinalManifestSpec, ReplayBundleSpec, RunConfigSpec, TimelineRecordSpec
from agora_ui.package_db import assess_pixel_readiness_from_root
from agora_ui.package_db import ensure_materialized_world_package
from agora_ui.package_db import materialize_world_package
from agora_ui.package_db import pack_world_package
from agora_ui.package_db import validate_pixel_ui_launch
from agora_ui.package_db import validate_world_package_startup
from agora_ui.jsonc_utils import load_jsonc_path
from agora_ui.scenario_schemas import ScenarioMapGridSpec, ScenarioManifestSpec
from agora_ui.world_definition import default_wallet_payload
from agora_ui.world_definition import sync_world_definition_into_config


def export_world_package_from_config(
    *,
    package_root: Path = PACKAGE_ROOT,
    world_config: dict[str, Any],
    package_name: str = "",
    source_label: str = "macro_ui_export",
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = sync_world_definition_into_config(_clone_json(world_config))
    access_code = _generate_package_access_code(package_root)
    export_dir = _package_export_dir(package_root, access_code)
    export_dir.mkdir(parents=True, exist_ok=True)
    (package_root / "output").mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="agora_world_export_", dir=str(package_root / "output")))
    try:
        run_inputs_dir = temp_root / "run_inputs"
        run_inputs_dir.mkdir(parents=True, exist_ok=True)
        config_path = run_inputs_dir / "world_config.json"
        _write_json(config_path, config)
        scenario_dir = run_inputs_dir / "scenario"
        _materialize_scenario(config, scenario_dir)
        _copy_pixel_assets(package_root, temp_root)
        package_db = temp_root / "world_package.db"
        pixel_report = assess_pixel_readiness_from_root(temp_root)
        pack_world_package(
            temp_root,
            package_db,
            package_name=package_name or str(config.get("scenario_meta", {}).get("world_name", access_code)),
            source_label=source_label,
            extra_meta={
                "pixel_read": pixel_report.get("pixel_read", False),
                "pixel_read_report": json.dumps(pixel_report, ensure_ascii=False),
                **(dict(extra_meta or {})),
            },
        )
        exported_db = export_dir / "world_package.db"
        shutil.copy2(package_db, exported_db)
        backend_startup_validation = validate_world_package_startup(
            package_root,
            access_code,
            display_name=str(config.get("scenario_meta", {}).get("world_name", access_code)),
        )
        if not bool(backend_startup_validation.get("startup_ok", False)):
            # shutil.rmtree(export_dir, ignore_errors=True)
            raise RuntimeError(
                "exported world package failed live startup smoke test: "
                + json.dumps(backend_startup_validation, ensure_ascii=False)
            )
        pixel_launch_validation = validate_pixel_ui_launch(
            package_root,
            access_code,
            seed=int(config.get("runtime", {}).get("seed", 42627) or 42627),
        )
        if not bool(pixel_launch_validation.get("startup_ok", False)):
            # shutil.rmtree(export_dir, ignore_errors=True)
            raise RuntimeError(
                "exported world package failed Pixel UI launch validation: "
                + json.dumps(pixel_launch_validation, ensure_ascii=False)
            )
        startup_validation = {
            "startup_ok": True,
            "stage": "ok",
            "expected_access_code": access_code,
            "selected_access_code": str(pixel_launch_validation.get("selected_access_code", "")).strip(),
            "backend_startup_validation": backend_startup_validation,
            "pixel_launch_validation": pixel_launch_validation,
            "startup_status_text": str(pixel_launch_validation.get("startup_status_text", "")).strip(),
            "session_endpoint": str(pixel_launch_validation.get("session_endpoint", "")).strip(),
            "screenshot_path": str(pixel_launch_validation.get("screenshot_path", "")).strip(),
            "error": "",
        }
        metadata = {
            "access_code": access_code,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "package_name": package_name or str(config.get("scenario_meta", {}).get("world_name", access_code)),
            "world_name": str(config.get("scenario_meta", {}).get("world_name", "")),
            "world_id": str(config.get("scenario_meta", {}).get("world_id", "")),
            "source_label": source_label,
            "package_db": str(exported_db),
            "pixel_read": bool(pixel_report.get("pixel_read", False)),
            "pixel_read_report": json.dumps(pixel_report, ensure_ascii=False),
            "startup_ok": bool(startup_validation.get("startup_ok", False)),
            "package_validation": {
                "stage": "ok",
                "pixel_read": bool(pixel_report.get("pixel_read", False)),
            },
            "backend_startup_validation": backend_startup_validation,
            "pixel_launch_validation": pixel_launch_validation,
            "startup_validation": startup_validation,
        }
        if extra_meta:
            metadata.update(
                {
                    str(key): value
                    for key, value in dict(extra_meta).items()
                    if value is not None
                }
            )
        _write_json(export_dir / PACKAGE_META_FILENAME, metadata)
        return metadata
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def export_world_package_from_db(
    *,
    package_root: Path = PACKAGE_ROOT,
    package_db: Path | str,
    package_name: str = "",
    source_label: str = "macro_ui_export",
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_db = Path(package_db).resolve()
    if not source_db.is_file():
        raise FileNotFoundError(f"world package db not found: {source_db}")

    access_code = _generate_package_access_code(package_root)
    export_dir = _package_export_dir(package_root, access_code)
    shutil.rmtree(export_dir, ignore_errors=True)
    export_dir.mkdir(parents=True, exist_ok=True)
    exported_db = export_dir / "world_package.db"
    shutil.copy2(source_db, exported_db)

    workspace = ensure_materialized_world_package(exported_db, output_dir=export_dir / "materialized")
    config_path = workspace / "run_inputs" / "world_config.json"
    if not config_path.is_file():
        config_path = workspace / "world_config.json"
    config = sync_world_definition_into_config(_read_world_config(config_path))
    world_name = str(config.get("scenario_meta", {}).get("world_name", "")).strip() or package_name or access_code
    world_id = str(config.get("scenario_meta", {}).get("world_id", "")).strip()
    runtime_seed = config.get("runtime", {}).get("seed", 42627)
    seed = int(runtime_seed) if str(runtime_seed).strip().isdigit() else 42627
    pixel_report = assess_pixel_readiness_from_root(workspace)

    meta_updates: dict[str, Any] = {
        "package_name": package_name or world_name,
        "source_label": source_label,
        "pixel_read": pixel_report.get("pixel_read", False),
        "pixel_read_report": json.dumps(pixel_report, ensure_ascii=False),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if extra_meta:
        meta_updates.update({str(key): value for key, value in dict(extra_meta).items() if value is not None})
    with sqlite3.connect(exported_db) as conn:
        for key, value in meta_updates.items():
            if isinstance(value, bool):
                stored = "true" if value else "false"
            else:
                stored = str(value)
            conn.execute(
                """
                INSERT INTO meta(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(key), stored),
            )
        conn.commit()

    backend_startup_validation = validate_world_package_startup(
        package_root,
        access_code,
        display_name=world_name,
    )
    if not bool(backend_startup_validation.get("startup_ok", False)):
        raise RuntimeError(
            "exported world package failed live startup smoke test: "
            + json.dumps(backend_startup_validation, ensure_ascii=False)
        )
    pixel_launch_validation = validate_pixel_ui_launch(
        package_root,
        access_code,
        seed=seed,
    )
    if not bool(pixel_launch_validation.get("startup_ok", False)):
        raise RuntimeError(
            "exported world package failed Pixel UI launch validation: "
            + json.dumps(pixel_launch_validation, ensure_ascii=False)
        )
    startup_validation = {
        "startup_ok": True,
        "stage": "ok",
        "expected_access_code": access_code,
        "selected_access_code": str(pixel_launch_validation.get("selected_access_code", "")).strip(),
        "backend_startup_validation": backend_startup_validation,
        "pixel_launch_validation": pixel_launch_validation,
        "startup_status_text": str(pixel_launch_validation.get("startup_status_text", "")).strip(),
        "session_endpoint": str(pixel_launch_validation.get("session_endpoint", "")).strip(),
        "screenshot_path": str(pixel_launch_validation.get("screenshot_path", "")).strip(),
        "error": "",
    }
    metadata = {
        "access_code": access_code,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "package_name": package_name or world_name,
        "world_name": world_name,
        "world_id": world_id,
        "source_label": source_label,
        "package_db": str(exported_db),
        "pixel_read": bool(pixel_report.get("pixel_read", False)),
        "pixel_read_report": json.dumps(pixel_report, ensure_ascii=False),
        "startup_ok": bool(startup_validation.get("startup_ok", False)),
        "package_validation": {
            "stage": "ok",
            "pixel_read": bool(pixel_report.get("pixel_read", False)),
        },
        "backend_startup_validation": backend_startup_validation,
        "pixel_launch_validation": pixel_launch_validation,
        "startup_validation": startup_validation,
    }
    if extra_meta:
        metadata.update(
            {
                str(key): value
                for key, value in dict(extra_meta).items()
                if value is not None
            }
        )
    _write_json(export_dir / PACKAGE_META_FILENAME, metadata)
    return metadata


def load_world_config_from_access_code(
    package_root: Path = PACKAGE_ROOT,
    access_code: str = "",
    *,
    materialize_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = str(access_code or "").strip()
    if not normalized:
        raise ValueError("package access code is required")
    export_dir = _package_export_dir(package_root, normalized)
    package_db = export_dir / "world_package.db"
    if not package_db.is_file():
        raise FileNotFoundError(f"package access code not found: {normalized}")
    if materialize_dir is not None:
        workspace = ensure_materialized_world_package(package_db, output_dir=materialize_dir)
        config_path = workspace / "run_inputs" / "world_config.json"
        if not config_path.is_file():
            config_path = workspace / "world_config.json"
        config = _read_world_config(config_path)
    else:
        package = materialize_world_package(package_db)
        config = _read_world_config(package.config_path)
    _rewrite_package_frontend_base_urls(config, normalized)
    metadata_path = export_dir / PACKAGE_META_FILENAME
    metadata = _read_json(metadata_path) if metadata_path.is_file() else {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.setdefault("access_code", normalized)
    metadata.setdefault("package_db", str(package_db))
    metadata.setdefault("world_name", str(config.get("scenario_meta", {}).get("world_name", "")))
    metadata.setdefault("world_id", str(config.get("scenario_meta", {}).get("world_id", "")))
    raw_pixel_read = metadata.get("pixel_read", False)
    if isinstance(raw_pixel_read, str):
        pixel_read = raw_pixel_read.strip().lower() in {"1", "true", "yes", "ok"}
    else:
        pixel_read = bool(raw_pixel_read)
    metadata["pixel_read"] = pixel_read
    metadata["asset_base_url"] = _pixel_package_base_url(normalized)
    # Probe whether the materialized workspace uses a run_inputs/ prefix or stores
    # files at the top level, then generate URLs that match the actual file layout.
    _base = _pixel_package_base_url(normalized)
    if materialize_dir is not None:
        _ws = Path(materialize_dir)
    else:
        _ws = export_dir / "materialized"
    if (_ws / "run_inputs" / "scenario" / "map_grid.json").is_file():
        _files_prefix = "run_inputs/"
    elif (_ws / "scenario" / "map_grid.json").is_file():
        _files_prefix = ""
    else:
        _files_prefix = "run_inputs/"
    metadata["map_grid_url"] = f"{_base}{_files_prefix}scenario/map_grid.json"
    metadata["world_config_url"] = f"{_base}{_files_prefix}world_config.json"
    return config, metadata


def generalized_world_config_template(package_root: Path = PACKAGE_ROOT) -> dict[str, Any]:
    config = _clone_json(_read_world_config(_base_sample_config_path(package_root)))
    scenario_meta = config.setdefault("scenario_meta", {})
    runner = config.setdefault("runner", {})
    output = config.setdefault("output", {})
    scenario_meta["world_id"] = "agora_multiscene_template"
    scenario_meta["world_name"] = "Agora Multi-Scene Scenario Template"
    scenario_meta["description"] = (
        "A reusable multi-scene simulation template. The default JSON is seeded with one concrete world, "
        "but every section can be edited in the UI or replaced by another AI-generated config."
    )
    scenario_meta["simulation_objective"] = (
        "Author a scene-compatible world config, launch the simulation, stream checkpointed results, "
        "and keep heavyweight visual generation on an independent background worker."
    )
    runner["run_name"] = "agora_multiscene_template"
    runner["world_label"] = "Scenario World"
    runner["domain_label"] = "multi-scene simulation world"
    runner["agent_id_prefix"] = "agent"
    output["default_output_dir"] = "output/agora_multi_scene_runs"
    return sync_world_definition_into_config(config)


def _resolve_run_config_path(run_dir: Path) -> Path:
    direct = run_dir / RUN_INPUTS_DIRNAME / "world_config.json"
    if direct.is_file():
        return direct
    run_config = run_dir / "run_config.json"
    if run_config.is_file():
        payload = _read_json(run_config)
        candidate = Path(str(payload.get("config_path", "")).strip())
        if candidate.is_file():
            return candidate.resolve()
    return _base_sample_config_path(PACKAGE_ROOT)


def _resolve_scenario_dir(run_dir: Path) -> Path:
    direct = run_dir / RUN_INPUTS_DIRNAME / "scenario"
    if direct.is_dir():
        return direct
    run_config = run_dir / "run_config.json"
    if run_config.is_file():
        payload = _read_json(run_config)
        candidate = Path(str(payload.get("scenario_dir", "")).strip())
        if candidate.is_dir():
            return candidate.resolve()
    manifest = run_dir / "final_manifest.json"
    if manifest.is_file():
        payload = _read_json(manifest)
        candidate = Path(str(payload.get("scenario_dir", "")).strip())
        if candidate.is_dir():
            return candidate.resolve()
    return (PACKAGE_ROOT / "sample_json/scenario").resolve()


def _load_agents_from_scenario(scenario_dir: Path) -> list[dict[str, Any]]:
    agents_dir = scenario_dir / "Agents"
    if agents_dir.is_dir():
        agents = [_read_json(path) for path in sorted(agents_dir.glob("*.json"))]
        if agents:
            return agents
    return []


def _load_cached_runtime_agents(run_dir: Path) -> list[dict[str, Any]]:
    cache_dir = run_dir / "agent_profile_api_cache"
    agents: list[dict[str, Any]] = []
    for path in sorted(cache_dir.glob("*.json")):
        payload = _read_json(path)
        runtime_agent = payload.get("runtime_agent") if isinstance(payload, dict) else None
        if isinstance(runtime_agent, dict):
            agents.append(runtime_agent)
    return agents


def _state_by_round(run_dir: Path) -> dict[int, dict[str, Any]]:
    states: dict[int, dict[str, Any]] = {}
    for step_dir in sorted(run_dir.glob("timestep_*")):
        if not step_dir.is_dir():
            continue
        try:
            round_index = int(step_dir.name.split("_")[-1])
        except Exception:
            continue
        state_path = step_dir / "updated_agent_profiles.json"
        if state_path.is_file():
            states[round_index] = AgentStateBundleSpec.model_validate(_read_json(state_path)).model_dump()
    return states


def _timeline_by_round(run_dir: Path) -> dict[int, dict[str, Any]]:
    rows = [TimelineRecordSpec.model_validate(row).model_dump() for row in _read_jsonl(run_dir / "timeline.jsonl")]
    return {int(row.get("round_index", 0)): row for row in rows if int(row.get("round_index", 0)) > 0}


def _completed_rounds(run_dir: Path) -> int:
    states = _state_by_round(run_dir)
    return max(states) if states else 0


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _clone_json(payload: Any) -> Any:
    return json.loads(json.dumps(payload))


def _materialize_scenario(config: dict[str, Any], scenario_dir: Path) -> None:
    from agora_ui.run_interaction_simulation import materialize_scenario

    materialize_scenario(config, scenario_dir)


def _copy_pixel_assets(package_root: Path, target_root: Path) -> None:
    source_assets = package_root / "frontend" / "assets" / "generated"
    if not source_assets.is_dir():
        return
    target_assets = target_root / "assets" / "generated"
    target_assets.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_assets, target_assets, dirs_exist_ok=True)


def _pixel_package_base_url(access_code: str) -> str:
    return f"/output/package_exports/{access_code}/materialized/"


def _rewrite_package_frontend_base_urls(config: dict[str, Any], access_code: str) -> None:
    frontend = config.setdefault("pixel_asset_pipeline", {}).setdefault("frontend", {})
    frontend["asset_base_url"] = _pixel_package_base_url(access_code)


def _merge_json(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = _clone_json(base)
        for key, value in override.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = _merge_json(merged[key], value)
            else:
                merged[key] = _clone_json(value)
        return merged
    return _clone_json(override)


def _safe_text(value: Any, limit: int = 220) -> str:
    return str(value or "").strip().replace("\n", " ")[:limit]


def _slug(text: str) -> str:
    chars = [ch.lower() if ch.isalnum() else "_" for ch in str(text)]
    return "".join(chars).strip("_")


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _image_generation_config(config: dict[str, Any]) -> dict[str, Any]:
    image_generation = config.get("image_generation", {})
    return image_generation if isinstance(image_generation, dict) else {}


def _normalize_item_image_mode(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"off", "important_only", "all"}:
        return raw
    if raw in {"important", "important-artifacts", "important_artifacts"}:
        return "important_only"
    return "important_only"





def _latest_run_dir(package_root: Path) -> Path | None:
    output_root = package_root / "output"
    if not output_root.is_dir():
        return None
    candidates = [
        path
        for path in output_root.rglob("*")
        if path.is_dir()
        and (
            (path / "run_config.json").is_file()
            or (path / "profile_generation_run.json").is_file()
            or (path / PROCESS_RECORD_PATH).is_file()
        )
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _wait_for_run_inputs(run_dir: Path, *, timeout_seconds: int = 0) -> None:
    if timeout_seconds <= 0:
        return
    deadline = time.time() + timeout_seconds
    while time.time() <= deadline:
        scenario_dir = run_dir / RUN_INPUTS_DIRNAME / "scenario"
        if (run_dir / RUN_INPUTS_DIRNAME / "world_config.json").is_file() and (scenario_dir / "Agents").is_dir():
            return
        time.sleep(2.0)


def _read_world_config(config_path: Path) -> dict[str, Any]:
    payload = load_jsonc_path(config_path)
    if not isinstance(payload, dict):
        raise ValueError(f"world config must be a JSON object: {config_path}")
    return sync_world_definition_into_config(payload)


def _base_sample_config_path(package_root: Path) -> Path:
    return (package_root / "sample_json/world_config.json").resolve()


def _package_exports_root(package_root: Path) -> Path:
    return package_root / "output" / PACKAGE_EXPORTS_DIRNAME


def _package_export_dir(package_root: Path, access_code: str) -> Path:
    return _package_exports_root(package_root) / access_code


def _generate_package_access_code(package_root: Path) -> str:
    exports_root = _package_exports_root(package_root)
    exports_root.mkdir(parents=True, exist_ok=True)
    while True:
        code = secrets.token_hex(8)
        if not _package_export_dir(package_root, code).exists():
            return code


def build_replay_bundle(
    *,
    package_root: Path = PACKAGE_ROOT,
    run_dir: Path,
    force_refresh_images: bool = False,
    all_agent_images: bool = True,
    generate_images: bool = True,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    config_path = _resolve_run_config_path(run_dir)
    scenario_dir = _resolve_scenario_dir(run_dir)
    config = _read_world_config(config_path)
    initial_agents = _load_agents_from_scenario(scenario_dir)
    if not initial_agents:
        initial_agents = _load_cached_runtime_agents(run_dir)
    capacity_per_coordinate = max(
        1,
        int(config.get("space", {}).get("movement", {}).get("capacity_per_coordinate", 1) or 1),
    )
    map_grid_path = scenario_dir / "map_grid.json"
    raw_map_grid = load_jsonc_path(map_grid_path) if map_grid_path.is_file() else _fallback_map_grid(config, initial_agents)
    map_grid = ScenarioMapGridSpec.model_validate(raw_map_grid).model_dump()
    final_state_path = run_dir / "final_agent_profiles.json"
    final_state = _read_json(final_state_path) if final_state_path.is_file() else {}
    states = _state_by_round(run_dir)
    timeline = _timeline_by_round(run_dir)
    replay_dir = run_dir / REPLAY_DIRNAME
    replay_assets_dir = replay_dir / "assets"
    rooms = [dict(room) for room in map_grid.get("rooms", []) if isinstance(room, dict)]
    room_lookup = {str(room.get("room_id", "")): room for room in rooms}
    catalog_agents = final_state.get("agents", initial_agents) if isinstance(final_state, dict) else initial_agents
    item_image_mode = _item_image_mode(config)
    portraits_enabled = _character_portraits_enabled(config)
    item_image_specs = _collect_item_image_specs(catalog_agents, mode=item_image_mode)
    item_image_urls = _ensure_item_images(
        config=config,
        items=item_image_specs,
        replay_assets_dir=replay_assets_dir,
        force_refresh_images=force_refresh_images,
        allow_generate=generate_images,
    )
    agent_lookup = {
        str(agent.get("agent_id", "")): _agent_payload(agent, config=config, item_image_urls=item_image_urls)
        for agent in catalog_agents
        if isinstance(agent, dict) and str(agent.get("agent_id", "")).strip()
    }
    room_image_urls = _ensure_room_images(
        config=config,
        rooms=rooms,
        replay_assets_dir=replay_assets_dir,
        force_refresh_images=force_refresh_images,
        allow_generate=generate_images,
    )
    if all_agent_images and portraits_enabled:
        agent_image_urls = _ensure_agent_images(
            config=config,
            agents=list(agent_lookup.values()),
            room_lookup=room_lookup,
            replay_assets_dir=replay_assets_dir,
            force_refresh_images=force_refresh_images,
            allow_generate=generate_images,
        )
    else:
        agent_image_urls = {}
    initial_agent_ids = [str(agent.get("agent_id", "")) for agent in initial_agents]
    initial_relationship_tensor = _neutral_relationship_tensor(initial_agent_ids)
    frames: list[dict[str, Any]] = []
    initial_frame_agents = [dict(agent) for agent in initial_agents]
    frames.append(
        {
            "frame_index": 0,
            "round_index": 0,
            "label": "Initial",
            "summary": {
                "round_index": 0,
                "activated_agent_count": 0,
                "intent_count": 0,
                "story_event_count": 0,
                "video_job_count": 0,
                "image_job_count": 0,
                "action_success_count": 0,
                "action_result_count": 0,
                "routes": {},
            },
            "rooms": _room_frame_payload(
                rooms,
                initial_frame_agents,
                room_image_urls,
                capacity_per_coordinate=capacity_per_coordinate,
            ),
            "agents": _frame_agents_payload(initial_frame_agents, config=config, item_image_urls=item_image_urls),
            "relationship_edges": _relationship_edges(initial_relationship_tensor, agent_lookup),
            "social_groups": _social_groups_payload(initial_frame_agents, initial_relationship_tensor, agent_lookup),
            "stories": [],
            "longlive_jobs": [],
            "image_jobs": [],
            "extra_world_events": [],
            "action_results": [],
        }
    )
    completed_round = max(states) if states else 0
    for round_index in range(1, completed_round + 1):
        state = states.get(round_index, {})
        timeline_row = timeline.get(round_index, {})
        agents = [dict(agent) for agent in state.get("agents", []) if isinstance(agent, dict)]
        relationship_tensor = dict(state.get("relationship_tensor", {}))
        frames.append(
            {
                "frame_index": round_index,
                "round_index": round_index,
                "label": f"Round {round_index}",
                "summary": dict(timeline_row.get("summary", {"round_index": round_index})),
                "rooms": _room_frame_payload(
                    rooms,
                    agents,
                    room_image_urls,
                    capacity_per_coordinate=capacity_per_coordinate,
                ),
                "agents": _frame_agents_payload(agents, config=config, item_image_urls=item_image_urls),
                "relationship_edges": _relationship_edges(relationship_tensor, agent_lookup),
                "social_groups": _social_groups_payload(agents, relationship_tensor, agent_lookup),
                "stories": [dict(item) for item in timeline_row.get("stories", []) if isinstance(item, dict)],
                "longlive_jobs": _prepare_media_jobs(
                    [dict(item) for item in timeline_row.get("video_jobs", []) if isinstance(item, dict)],
                    "video_path",
                ),
                "image_jobs": _prepare_media_jobs(
                    [dict(item) for item in timeline_row.get("image_jobs", []) if isinstance(item, dict)],
                    "image_path",
                ),
                "extra_world_events": [dict(item) for item in timeline_row.get("extra_world_events", []) if isinstance(item, dict)],
                "action_results": [dict(item) for item in timeline_row.get("action_results", []) if isinstance(item, dict)],
            }
        )
    relationship_nodes = [
        {
            "id": agent_id,
            "label": agent.get("display_name", agent_id),
            "group": "main" if agent.get("main_character") else "agent",
            "room_id": agent.get("room_id", ""),
            "title": f"{agent.get('display_name', agent_id)} | {agent.get('role_name', 'Agent')}",
        }
        for agent_id, agent in sorted(agent_lookup.items())
    ]
    agents_payload = []
    for agent_id, agent in sorted(agent_lookup.items()):
        agents_payload.append(
            {
                **agent,
                "agent_number": _agent_id_number(agent_id),
                "image_url": agent_image_urls.get(agent_id, ""),
            }
        )
    run_config = _read_json(run_dir / "run_config.json") if (run_dir / "run_config.json").is_file() else {}
    final_manifest = FinalManifestSpec.model_validate(_read_json(run_dir / "final_manifest.json")).model_dump() if (run_dir / "final_manifest.json").is_file() else {}
    room_bounds = _room_cell_bounds(rooms)
    bundle = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "world": {
            "world_id": str(config.get("scenario_meta", {}).get("world_id", "")),
            "world_name": str(config.get("scenario_meta", {}).get("world_name", "")),
            "description": str(config.get("scenario_meta", {}).get("description", "")),
            "simulation_objective": str(config.get("scenario_meta", {}).get("simulation_objective", "")),
            "domain_label": str(config.get("runner", {}).get("domain_label", "")),
            "image_options": {
                "generate_character_portraits": portraits_enabled,
                "item_image_mode": item_image_mode,
            },
        },
        "run": {
            "run_id": str(run_config.get("run_id", run_dir.name)),
            "run_dir": str(run_dir),
            "status": _run_status(run_dir),
            "created_at": str(run_config.get("created_at", "")),
            "rounds_target": int(run_config.get("rounds", config.get("runtime", {}).get("rounds", 0)) or 0),
            "rounds_completed": completed_round,
            "activation_probability": float(run_config.get("activation_probability", config.get("runtime", {}).get("activation_probability", 0.0)) or 0.0),
            "agent_count": 25,
            "route_counts": dict(final_manifest.get("route_counts", {})),
            "longlive_counts": dict(final_manifest.get("longlive_counts", {})),
            "image_counts": dict(final_manifest.get("image_counts", {})),
        },
        "map": {
            "grid_shape": dict(map_grid.get("grid_shape", {})),
            "map_visual": dict(map_grid.get("map_visual", {})),
            "bounds": room_bounds,
            "capacity_per_coordinate": capacity_per_coordinate,
            "rooms": [
                {
                    **_room_capacity_payload(room, 0, capacity_per_coordinate),
                    "room_id": str(room.get("room_id", "")),
                    "name": str(room.get("name", "")),
                    "x": int(room.get("x", 0)),
                    "y": int(room.get("y", 0)),
                    "z": int(room.get("z", 0)),
                    "width_tiles": int(room.get("width_tiles", 1) or 1),
                    "height_tiles": int(room.get("height_tiles", 1) or 1),
                    "footprint_tiles": [dict(item) for item in room.get("footprint_tiles", []) if isinstance(item, dict)],
                    "doorways": [dict(item) for item in room.get("doorways", []) if isinstance(item, dict)],
                    "spawn_points": [dict(item) for item in room.get("spawn_points", []) if isinstance(item, dict)],
                    "visual": dict(room.get("visual", {})),
                    "image_url": room_image_urls.get(str(room.get("room_id", "")), ""),
                }
                for room in rooms
            ],
        },
        "agents": agents_payload[:25],
        "relationship_graph": {"nodes": relationship_nodes[:25]},
        "frames": frames,
    }
    _write_json(replay_dir / "macro_bundle.json", bundle)
    bundle = ReplayBundleSpec.model_validate(bundle).model_dump()
    return bundle


def _scaled_role_groups(base_role_groups: list[dict[str, Any]], regular_agent_count: int) -> list[dict[str, Any]]:
    if regular_agent_count <= 0:
        return []
    total = sum(int(group.get("count", 0) or 0) for group in base_role_groups)
    if total <= 0:
        raise ValueError("base role_groups count total must be positive")
    scaled: list[dict[str, Any]] = []
    running_total = 0
    remainders: list[tuple[float, int]] = []
    for index, group in enumerate(base_role_groups):
        proportion = (int(group.get("count", 0) or 0) / total) * regular_agent_count
        count = int(math.floor(proportion))
        running_total += count
        scaled.append({**group, "count": count})
        remainders.append((proportion - count, index))
    for _, index in sorted(remainders, reverse=True)[: max(0, regular_agent_count - running_total)]:
        scaled[index]["count"] = int(scaled[index].get("count", 0)) + 1
    return scaled


def build_run_local_config(
    *,
    package_root: Path = PACKAGE_ROOT,
    run_dir: Path,
    run_id: str,
    regular_agent_count: int,
    rounds: int,
    activation_probability: float,
    seed: int,
    main_characters_always_activate: bool,
    max_videos_per_round: int,
    segment_seconds: int,
    max_images_per_round: int,
    source_config: dict[str, Any] | None = None,
) -> Path:
    base_config = source_config if source_config is not None else generalized_world_config_template(package_root)
    config = _clone_json(base_config)
    scenario_meta = config.setdefault("scenario_meta", {})
    runtime = config.setdefault("runtime", {})
    runner = config.setdefault("runner", {})
    output = config.setdefault("output", {})
    world_rules = config.setdefault("world_rules", {})
    image_generation = config.setdefault("image_generation", {})
    longlive = config.setdefault("longlive", {})
    agent_generation = dict(config.get("agent_generation", {}))
    main_characters = [dict(item) for item in config.get("main_characters", []) if isinstance(item, dict)]
    main_count = len(main_characters)
    if not str(scenario_meta.get("world_id", "")).strip():
        scenario_meta["world_id"] = f"agora_scenario_{regular_agent_count + main_count}_agents"
    if not str(scenario_meta.get("world_name", "")).strip():
        scenario_meta["world_name"] = f"Agora Scenario {regular_agent_count + main_count} Agents"
    if not str(scenario_meta.get("description", "")).strip():
        scenario_meta["description"] = (
            "A configurable Agora simulation run. Use the UI or a generated JSON config to adapt the same runtime "
            "to different worlds, casts, and interaction rules."
        )
    runtime["agent_count"] = regular_agent_count + main_count
    runtime["rounds"] = rounds
    runtime["activation_probability"] = activation_probability
    runtime["seed"] = seed
    runner["run_name"] = str(runner.get("run_name", "")).strip() or run_id
    output["default_output_dir"] = str(run_dir.parent)
    agent_generation["role_groups"] = _scaled_role_groups(
        [dict(group) for group in agent_generation.get("role_groups", []) if isinstance(group, dict)],
        regular_agent_count,
    )
    agent_generation["name_mode"] = "given_family"
    agent_generation["name_include_index"] = False
    agent_generation["given_names"] = DEFAULT_GIVEN_NAMES
    agent_generation["family_names"] = DEFAULT_FAMILY_NAMES
    agent_generation["visual_variation"] = DEFAULT_VISUAL_VARIATION
    agent_generation["profile_diversity_policy"] = (
        "Distribute facial structure, age cues, skin tone, hair texture, body build, height impression, outfit layering, "
        "accessories, and regional styling widely across the cast. Avoid converging on one face, one body type, or one palette."
    )
    domain_label = str(runner.get("domain_label", "scenario world")).strip() or "scenario world"
    for group in agent_generation.get("role_groups", []):
        if not isinstance(group, dict):
            continue
        role_name = str(group.get("role_name", "guild member"))
        group["appearance_template"] = (
            f"A {{gender_presentation}} {{age_band}} {role_name.lower()} with {{skin_tone}} skin, {{hair_color}} {{hair_style}}, "
            f"a {{body_type}} build, {{signature_accessory}}, {{silhouette_trait}}, and a clear {domain_label} silhouette."
        )
    config["agent_generation"] = agent_generation
    for item in main_characters:
        item["always_activate"] = bool(main_characters_always_activate)
    config["main_characters"] = main_characters
    longlive["max_videos_per_round"] = int(max_videos_per_round)
    longlive["segment_seconds"] = int(segment_seconds)
    longlive["candidate_probability"] = float(longlive.get("candidate_probability", 0.4) or 0.4)
    longlive["force_cinematic_for_main_characters"] = bool(longlive.get("force_cinematic_for_main_characters", True))
    image_generation["max_images_per_round"] = int(max_images_per_round)
    image_generation["generate_character_portraits"] = bool(image_generation.get("generate_character_portraits", True))
    image_generation["item_image_mode"] = _normalize_item_image_mode(image_generation.get("item_image_mode", "important_only"))
    image_generation["artifact_image_reasoning_enabled"] = bool(image_generation.get("artifact_image_reasoning_enabled", True))
    image_generation["artifact_reasoning_max_edge_px"] = max(
        128,
        int(image_generation.get("artifact_reasoning_max_edge_px", 500) or 500),
    )
    world_rules["social_rules"] = [
        str(rule)
        for rule in world_rules.get("social_rules", [])
        if "must use LongLive for every successful activation" not in str(rule)
    ]
    if not any("prefer at-will LongLive" in str(rule) for rule in world_rules["social_rules"]):
        world_rules["social_rules"].append(
            "Main characters should strongly prefer at-will LongLive when video quota remains and target legality allows it."
        )
    config["image_generation"] = image_generation
    config["longlive"] = longlive
    config["world_rules"] = world_rules
    run_inputs_dir = run_dir / RUN_INPUTS_DIRNAME
    run_inputs_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_inputs_dir / "world_config.json"
    _write_json(config_path, config)
    scenario_dir = run_inputs_dir / "scenario"
    _materialize_scenario(config, scenario_dir)
    package_workspace = Path(tempfile.mkdtemp(prefix="agora_run_package_", dir=str(run_dir)))
    try:
        package_run_inputs_dir = package_workspace / RUN_INPUTS_DIRNAME
        package_run_inputs_dir.mkdir(parents=True, exist_ok=True)
        _write_json(package_run_inputs_dir / "world_config.json", config)
        _materialize_scenario(config, package_run_inputs_dir / "scenario")
        _copy_pixel_assets(package_root, package_workspace)
        pixel_report = assess_pixel_readiness_from_root(package_workspace)
        package_path = run_dir / "world_package.db"
        pack_world_package(
            package_workspace,
            package_path,
            package_name=run_id,
            source_label="macro_ui_run_inputs",
            extra_meta={
                "pixel_read": pixel_report.get("pixel_read", False),
                "pixel_read_report": json.dumps(pixel_report, ensure_ascii=False),
            },
        )
    finally:
        shutil.rmtree(package_workspace, ignore_errors=True)
    return package_path


def build_bundle(
    *,
    package_root: Path,
    config_path: Path | None = None,
    scenario_dir: Path | None = None,
    run_dir: Path | None,
    max_agent_images: int = 0,
    force_refresh_images: bool = False,
    wait_for_scenario_seconds: int = 0,
    all_agent_images: bool = True,
    generate_images: bool = True,
) -> dict[str, Any]:
    del config_path, scenario_dir, max_agent_images
    resolved_run_dir = run_dir.resolve() if run_dir is not None else _latest_run_dir(package_root)
    if resolved_run_dir is None:
        raise FileNotFoundError("No run directory found under output/")
    _wait_for_run_inputs(resolved_run_dir, timeout_seconds=wait_for_scenario_seconds)
    return build_replay_bundle(
        package_root=package_root,
        run_dir=resolved_run_dir,
        force_refresh_images=force_refresh_images,
        all_agent_images=all_agent_images,
        generate_images=generate_images,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default="", help="Optional run output directory. If omitted, use the latest local output run.")
    parser.add_argument("--force-refresh-images", action="store_true")
    parser.add_argument("--no-agent-images", action="store_true", help="Skip replay-bundle agent portrait generation.")
    parser.add_argument("--no-generate-images", action="store_true", help="Build the replay bundle without invoking image generation.")
    parser.add_argument("--wait-for-scenario-seconds", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve() if args.run_dir else None
    bundle = build_bundle(
        package_root=PACKAGE_ROOT,
        run_dir=run_dir,
        force_refresh_images=bool(args.force_refresh_images),
        wait_for_scenario_seconds=int(args.wait_for_scenario_seconds or 0),
        all_agent_images=not bool(args.no_agent_images),
        generate_images=not bool(args.no_generate_images),
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "world_name": bundle["world"]["world_name"],
                "run_id": bundle["run"]["run_id"],
                "frame_count": len(bundle["frames"]),
                "agent_count": len(bundle["agents"]),
                "rounds_completed": bundle["run"]["rounds_completed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
