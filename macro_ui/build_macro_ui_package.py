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
__all__ = ["export_world_package_from_config", "load_world_config_from_access_code", "generalized_world_config_template", "_resolve_run_config_path", "_resolve_scenario_dir", "_room_prompt", "_agent_prompt", "_item_prompt", "_agent_statuses", "_inventory_payload", "_currency_amount", "_agent_payload", "_room_capacity_payload", "_social_groups_payload", "_relationship_edges", "_agent_id_number", "_neutral_relationship_tensor", "_load_agents_from_scenario", "_load_cached_runtime_agents", "_fallback_map_grid", "_state_by_round", "_timeline_by_round", "_completed_rounds", "_run_process_payload", "_systemd_unit_property", "_run_status", "discover_runs", "current_run_record", "_asset_worker_payload", "asset_worker_status", "launch_asset_bundle_worker"]

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
    metadata.setdefault("asset_base_url", _pixel_package_base_url(normalized))
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
    metadata.setdefault("map_grid_url", f"{_base}{_files_prefix}scenario/map_grid.json")
    metadata.setdefault("world_config_url", f"{_base}{_files_prefix}world_config.json")
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


def _room_prompt(config: dict[str, Any], room: dict[str, Any]) -> str:
    world = config.get("scenario_meta", {})
    room_visual = room.get("visual", {})
    decor = ", ".join(room_visual.get("decor_tags", [])) or "minimal decor"
    return (
        f"Create one clean illustrative environment image for a macro world viewer. "
        f"Setting: {world.get('world_name', 'Agora World')}. "
        f"Theme: {config.get('runner', {}).get('domain_label', 'fictional world')}. "
        f"Room: {room.get('name', room.get('room_id', 'room'))}. "
        f"Biome: {room_visual.get('biome', 'interior')}. "
        f"Floor material token: {room_visual.get('floor_tile', 'floor')}. "
        f"Wall material token: {room_visual.get('wall_tile', 'wall')}. "
        f"Decor: {decor}. Ambient palette: {room_visual.get('ambient_palette', 'balanced')}. "
        "No people in frame. No visible text. No watermark. Pixel-friendly environment illustration grounded in the active world."
    )


def _agent_prompt(config: dict[str, Any], agent: dict[str, Any], room_lookup: dict[str, dict[str, Any]]) -> str:
    room = room_lookup.get(agent.get("room_id", ""), {})
    room_visual = room.get("visual", {})
    return (
        f"Create one clean character portrait for a macro world viewer. "
        f"World: {config.get('scenario_meta', {}).get('world_name', 'Agora World')}. "
        f"Theme: {config.get('runner', {}).get('domain_label', 'fictional world')}. "
        f"Character: {agent.get('display_name', agent.get('agent_id', 'Agent'))}. "
        f"Role: {agent.get('role_name', 'Agent')}. "
        f"Appearance: {agent.get('appearance_prompt', '')}. "
        f"Current room mood: {room.get('name', agent.get('room_id', 'room'))}, biome {room_visual.get('biome', 'neutral')}, palette {room_visual.get('ambient_palette', 'balanced')}. "
        "Waist-up portrait, readable silhouette, distinct face and outfit, no text, no watermark."
    )


def _item_prompt(config: dict[str, Any], item: dict[str, Any]) -> str:
    metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata", {}), dict) else {}
    name = str(metadata.get("name") or item.get("description") or item.get("item_id") or "Item")
    description = str(item.get("description", "")).strip()
    category = str(metadata.get("category", "")).strip()
    rarity = str(metadata.get("rarity", "")).strip()
    explicit_prompt = str(item.get("image_prompt", "")).strip()
    importance = "important artifact item" if _item_is_important_artifact(item) else "inventory object"
    if explicit_prompt:
        detail = explicit_prompt
    else:
        detail = (
            f"Item name: {name}. "
            f"Category: {category or 'general item'}. "
            f"Rarity: {rarity or 'ordinary'}. "
            f"Description: {description or 'portable object used in the simulation world.'}"
        )
    return (
        "Create one clean object render for a macro world viewer. "
        f"World: {config.get('scenario_meta', {}).get('world_name', 'Agora World')}. "
        f"Theme: {config.get('runner', {}).get('domain_label', 'fictional world')}. "
        f"Render this as a {importance}. "
        f"{detail} "
        "Single item, centered, readable silhouette, no hands, no people, no text, no watermark."
    )


def _agent_statuses(agent_payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for effect in agent_payload.get("status_effects", []) or []:
        if isinstance(effect, dict):
            effect_name = str(effect.get("effect", "")).strip()
            if effect_name:
                values.append(effect_name)
    return values


def _inventory_payload(
    agent_payload: dict[str, Any],
    *,
    item_image_urls: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    image_urls = item_image_urls or {}
    for item in agent_payload.get("inventory", []) or []:
        if not isinstance(item, dict):
            continue
        image_path = _resolve_asset_path(item.get("image_path", ""))
        metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata", {}), dict) else {}
        item_id = str(item.get("item_id", ""))
        payload.append(
            {
                "item_id": item_id,
                "name": str(metadata.get("name") or item.get("description") or item.get("item_id") or "Item"),
                "quantity": int(item.get("quantity", 0) or 0),
                "mass": float(item.get("mass", 0.0) or 0.0),
                "description": str(item.get("description", "")),
                "image_path": str(item.get("image_path", "")),
                "image_prompt": str(item.get("image_prompt", "")),
                "image_url": image_urls.get(item_id, "") or _static_url_if_local(image_path),
                "important_artifact": _item_is_important_artifact(item),
                "condition": str(item.get("condition", "")),
                "authenticity_state": str(item.get("authenticity_state", "")),
                "trade_state": str(item.get("trade_state", "")),
                "asking_price_minor": int(item.get("asking_price_minor", 0) or 0),
                "metadata": metadata,
            }
        )
    return payload


def _currency_amount(agent_payload: dict[str, Any], *, config: dict[str, Any]) -> tuple[str, int, str]:
    wallet = agent_payload.get("wallet", {}) if isinstance(agent_payload.get("wallet", {}), dict) else {}
    if wallet:
        return (
            str(config.get("economy", {}).get("currency_item_id", "currency") or "currency"),
            int(wallet.get("amount_minor", 0) or 0),
            str(wallet.get("currency_symbol", config.get("economy", {}).get("currency_symbol", "")) or ""),
        )
    inventory = [item for item in agent_payload.get("inventory", []) or [] if isinstance(item, dict)]
    for item in inventory:
        metadata = item.get("metadata", {})
        if isinstance(metadata, dict) and bool(metadata.get("currency")):
            return (
                str(item.get("item_id", "currency") or "currency"),
                int(item.get("quantity", 0) or 0),
                str(metadata.get("currency_symbol", config.get("economy", {}).get("currency_symbol", "")) or ""),
            )
    for item in inventory:
        if str(item.get("item_id", "")).strip() == "gold":
            return "gold", int(item.get("quantity", 0) or 0), ""
    return (
        str(config.get("economy", {}).get("currency_item_id", "currency") or "currency"),
        0,
        str(config.get("economy", {}).get("currency_symbol", "")),
    )


def _agent_payload(
    agent: dict[str, Any],
    *,
    config: dict[str, Any],
    item_image_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    public_state = dict(agent.get("public_state", {})) if isinstance(agent.get("public_state", {}), dict) else {}
    currency_item_id, currency_amount, currency_symbol = _currency_amount(agent, config=config)
    status_effects = [dict(item) for item in agent.get("status_effects", []) if isinstance(item, dict)]
    runtime_memory = dict(public_state.get("runtime_memory", {})) if isinstance(public_state.get("runtime_memory", {}), dict) else {}
    wallet = agent.get("wallet", {}) if isinstance(agent.get("wallet", {}), dict) else default_wallet_payload(currency_amount, config=config)
    return {
        "agent_id": str(agent.get("agent_id", "")),
        "display_name": str(agent.get("display_name", "")),
        "gender_presentation": str(agent.get("gender_presentation", "")),
        "room_id": str(agent.get("room_id", "")),
        "coordinates": dict(agent.get("coordinates", {})),
        "status_effect_names": _agent_statuses(agent),
        "role_name": str(public_state.get("role_name", "")),
        "role_id": str(public_state.get("role_id", "")),
        "home_room_id": str(public_state.get("home_room_id", "")),
        "main_character": bool(public_state.get("main_character", False)),
        "appearance_prompt": str(agent.get("appearance_prompt", "")),
        "activity_directive": str(public_state.get("activity_directive", "")),
        "core_values": [str(item) for item in agent.get("core_values", []) if str(item).strip()],
        "personality_tags": [str(item) for item in public_state.get("personality_tags", []) if str(item).strip()],
        "wallet": wallet,
        "property_library": [dict(item) for item in agent.get("property_library", public_state.get("property_library", [])) if isinstance(item, dict)],
        "knowledge_assets": [dict(item) for item in agent.get("knowledge_assets", []) if isinstance(item, dict)],
        "public_state": public_state,
        "runtime_memory": runtime_memory,
        "private_notes": str(agent.get("private_notes", "")),
        "status_effects": status_effects,
        "inventory": _inventory_payload(agent, item_image_urls=item_image_urls),
        "currency_item_id": currency_item_id,
        "currency_amount": currency_amount,
        "currency_symbol": currency_symbol,
    }


def _room_capacity_payload(room: dict[str, Any], occupant_count: int, capacity_per_coordinate: int) -> dict[str, Any]:
    explicit = [dict(item) for item in room.get("footprint_tiles", []) if isinstance(item, dict)]
    if explicit:
        footprint_area = max(1, len(explicit))
    else:
        footprint_area = max(1, int(room.get("width_tiles", 1) or 1) * int(room.get("height_tiles", 1) or 1))
    capacity_estimate = max(1, footprint_area * max(1, capacity_per_coordinate))
    occupancy_density = occupant_count / max(1, capacity_estimate)
    if occupancy_density >= 1.0:
        pressure_band = "compressed"
    elif occupancy_density >= 0.7:
        pressure_band = "crowded"
    elif occupancy_density >= 0.4:
        pressure_band = "busy"
    else:
        pressure_band = "clear"
    return {
        "footprint_area": footprint_area,
        "capacity_estimate": capacity_estimate,
        "occupancy_density": round(occupancy_density, 3),
        "pressure_band": pressure_band,
    }


def _social_groups_payload(
    agents: list[dict[str, Any]],
    relationship_tensor: dict[str, dict[str, Any]],
    agent_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    adjacency: dict[str, set[str]] = {}
    for agent in agents:
        agent_id = str(agent.get("agent_id", "")).strip()
        if not agent_id:
            continue
        adjacency.setdefault(agent_id, set())
        runtime_memory = agent.get("runtime_memory", {})
        if isinstance(runtime_memory, dict):
            for other_id in runtime_memory.get("cohort_ids", []):
                other_key = str(other_id).strip()
                if other_key and other_key in agent_lookup:
                    adjacency[agent_id].add(other_key)
                    adjacency.setdefault(other_key, set()).add(agent_id)
    for source_id, targets in relationship_tensor.items():
        if source_id not in adjacency:
            continue
        for target_id, vector in (targets or {}).items():
            target_key = str(target_id).strip()
            if target_key not in adjacency or not isinstance(vector, dict):
                continue
            trust = int(vector.get("trust", 50))
            affection = int(vector.get("affection", 50))
            if trust >= 62 or affection >= 62:
                adjacency[source_id].add(target_key)
                adjacency[target_key].add(source_id)
    groups: list[dict[str, Any]] = []
    seen: set[str] = set()
    for agent_id in sorted(adjacency):
        if agent_id in seen:
            continue
        queue = deque([agent_id])
        component: list[str] = []
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            component.append(current)
            for neighbor in sorted(adjacency.get(current, set())):
                if neighbor not in seen:
                    queue.append(neighbor)
        if len(component) < 2:
            continue
        labels = [
            str(agent_lookup.get(member, {}).get("display_name", member))
            for member in component[:3]
        ]
        groups.append(
            {
                "group_id": "group_" + "_".join(component[:4]),
                "member_ids": component,
                "label": ", ".join(labels) + (f" +{len(component) - 3}" if len(component) > 3 else ""),
                "size": len(component),
            }
        )
    groups.sort(key=lambda item: (-int(item.get("size", 0)), str(item.get("group_id", ""))))
    return groups[:10]


def _relationship_edges(relationship_tensor: dict[str, dict[str, Any]], agent_lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source_id, targets in relationship_tensor.items():
        for target_id, vector in (targets or {}).items():
            if not isinstance(vector, dict) or source_id not in agent_lookup or target_id not in agent_lookup:
                continue
            pair = tuple(sorted((source_id, str(target_id))))
            if pair in seen:
                continue
            trust = int(vector.get("trust", 50))
            affection = int(vector.get("affection", 50))
            influence = int(vector.get("influence_fear", 0))
            reverse = relationship_tensor.get(target_id, {}).get(source_id, {})
            if isinstance(reverse, dict):
                trust = round((trust + int(reverse.get("trust", 50))) / 2)
                affection = round((affection + int(reverse.get("affection", 50))) / 2)
                influence = round((influence + int(reverse.get("influence_fear", 0))) / 2)
            if trust == 50 and affection == 50 and influence == 0:
                continue
            weight = trust + affection - abs(influence)
            label = f"T {trust} | A {affection} | F {influence}"
            edges.append(
                {
                    "from": source_id,
                    "to": str(target_id),
                    "trust": trust,
                    "affection": affection,
                    "influence_fear": influence,
                    "weight": weight,
                    "label": label,
                }
            )
            seen.add(pair)
    return sorted(edges, key=lambda edge: edge["weight"], reverse=True)


def _agent_id_number(agent_id: str) -> int:
    digits = "".join(ch for ch in str(agent_id) if ch.isdigit())
    if digits:
        return int(digits[-3:].lstrip("0") or "0")
    # Keep main-character style ids stable without relying on a trailing digit suffix.
    return sum(ord(ch) for ch in str(agent_id)) % 1000


def _neutral_relationship_tensor(agent_ids: list[str]) -> dict[str, dict[str, dict[str, int]]]:
    payload: dict[str, dict[str, dict[str, int]]] = {}
    for source_id in agent_ids:
        payload[source_id] = {}
        for target_id in agent_ids:
            if source_id == target_id:
                continue
            payload[source_id][target_id] = {"trust": 50, "affection": 50, "influence_fear": 0}
    return payload


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


def _fallback_map_grid(config: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "grid_shape": dict(config.get("space", {}).get("grid_shape", {})),
        "map_visual": dict(config.get("space", {}).get("map_visual", {})),
        "rooms": [dict(room) for room in config.get("space", {}).get("rooms", []) if isinstance(room, dict)],
        "initial_positions": {
            str(agent.get("agent_id", "")): dict(agent.get("coordinates", {}))
            for agent in agents
            if str(agent.get("agent_id", "")).strip()
        },
        "initial_room_ids": {
            str(agent.get("agent_id", "")): str(agent.get("room_id", ""))
            for agent in agents
            if str(agent.get("agent_id", "")).strip()
        },
    }


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


def _run_process_payload(run_dir: Path) -> dict[str, Any]:
    process_path = run_dir / PROCESS_RECORD_PATH
    if not process_path.is_file():
        return {}
    try:
        payload = _read_json(process_path)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


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


def _run_status(run_dir: Path) -> str:
    final_manifest = run_dir / "final_manifest.json"
    if final_manifest.is_file():
        return "complete"
    process_payload = _run_process_payload(run_dir)
    unit_name = str(process_payload.get("unit_name", "")).strip()
    if unit_name:
        sub_state = _systemd_unit_property(unit_name, "SubState")
        if sub_state in {"running", "start", "start-pre", "start-post"}:
            return "running"
        if sub_state == "failed":
            return "failed"
    pid = int(process_payload.get("pid", 0) or 0)
    if _pid_alive(pid):
        return "running"
    if (run_dir / "run_config.json").is_file():
        return "stopped"
    return "unknown"


def discover_runs(package_root: Path = PACKAGE_ROOT) -> list[dict[str, Any]]:
    output_root = package_root / "output"
    if not output_root.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for run_dir in sorted(output_root.rglob("*")):
        if not run_dir.is_dir():
            continue
        if not (
            (run_dir / "run_config.json").is_file()
            or (run_dir / "profile_generation_run.json").is_file()
            or (run_dir / PROCESS_RECORD_PATH).is_file()
        ):
            continue
        run_config = RunConfigSpec.model_validate(_read_json(run_dir / "run_config.json")).model_dump() if (run_dir / "run_config.json").is_file() else {}
        profile_generation = _read_json(run_dir / "profile_generation_run.json") if (run_dir / "profile_generation_run.json").is_file() else {}
        process_payload = _run_process_payload(run_dir)
        config_path = _resolve_run_config_path(run_dir)
        config = _read_world_config(config_path) if config_path.is_file() else {}
        rounds = int(run_config.get("rounds", config.get("runtime", {}).get("rounds", 0)) or 0)
        completed_round = _completed_rounds(run_dir)
        runs.append(
            {
                "run_id": str(run_config.get("run_id") or profile_generation.get("run_id") or process_payload.get("run_id") or run_dir.name),
                "run_dir": str(run_dir),
                "created_at": str(run_config.get("created_at") or profile_generation.get("created_at") or process_payload.get("launched_at") or ""),
                "status": _run_status(run_dir),
                "rounds_target": rounds,
                "rounds_completed": completed_round,
                "activation_probability": float(run_config.get("activation_probability", config.get("runtime", {}).get("activation_probability", 0.0)) or 0.0),
                "agent_count": int(profile_generation.get("agent_count", config.get("runtime", {}).get("agent_count", 0)) or 0),
                "world_name": str(config.get("scenario_meta", {}).get("world_name", run_dir.name)),
                "world_id": str(config.get("scenario_meta", {}).get("world_id", "")),
                "story_filename": str(run_config.get("story_filename", "")),
            }
        )
    runs.sort(key=lambda item: (item.get("created_at", ""), item.get("run_id", "")), reverse=True)
    return runs


def current_run_record(package_root: Path = PACKAGE_ROOT) -> dict[str, Any] | None:
    runs = discover_runs(package_root)
    for run in runs:
        if run.get("status") == "running":
            return run
    return runs[0] if runs else None


def _asset_worker_payload(run_dir: Path) -> dict[str, Any]:
    path = run_dir / ASSET_WORKER_RECORD_PATH
    if not path.is_file():
        return {}
    try:
        payload = _read_json(path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def asset_worker_status(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    worker_payload = _asset_worker_payload(run_dir)
    config_path = _resolve_run_config_path(run_dir)
    config = _read_world_config(config_path) if config_path.is_file() else {}
    scenario_dir = _resolve_scenario_dir(run_dir)
    scenario_manifest_path = scenario_dir / "manifest.json"
    if scenario_manifest_path.is_file():
        ScenarioManifestSpec.model_validate(_read_json(scenario_manifest_path)).model_dump()
    initial_agents = _load_agents_from_scenario(scenario_dir) or _load_cached_runtime_agents(run_dir)
    final_state_path = run_dir / "final_agent_profiles.json"
    final_state = AgentStateBundleSpec.model_validate(_read_json(final_state_path)).model_dump() if final_state_path.is_file() else {}
    final_agents = final_state.get("agents", initial_agents) if isinstance(final_state, dict) else initial_agents
    rooms = [dict(room) for room in config.get("space", {}).get("rooms", []) if isinstance(room, dict)]
    replay_assets_dir = run_dir / REPLAY_DIRNAME / "assets"
    room_image_count = len(list((replay_assets_dir / "images" / "rooms").glob("*.*")))
    agent_image_count = len(list((replay_assets_dir / "images" / "agents").glob("*.*")))
    item_image_count = len(list((replay_assets_dir / "images" / "items").glob("*.*")))
    expected_room_count = len(rooms)
    portraits_enabled = _character_portraits_enabled(config)
    expected_agent_count = len([agent for agent in final_agents if isinstance(agent, dict)]) if portraits_enabled else 0
    item_mode = _item_image_mode(config)
    expected_item_count = 0
    if item_mode != "off":
        seen_item_ids: set[str] = set()
        for agent in final_agents:
            if not isinstance(agent, dict):
                continue
            for item in agent.get("inventory", []) or []:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("item_id", "")).strip()
                if not item_id or item_id in seen_item_ids or int(item.get("quantity", 0) or 0) <= 0:
                    continue
                if item_mode == "important_only" and not _item_is_important_artifact(item):
                    continue
                existing_local = _resolve_asset_path(item.get("image_path", ""))
                if existing_local is not None and existing_local.is_file():
                    continue
                seen_item_ids.add(item_id)
        expected_item_count = len(seen_item_ids)
    unit_name = str(worker_payload.get("unit_name", "")).strip()
    sub_state = _systemd_unit_property(unit_name, "SubState") if unit_name else ""
    status = "idle"
    if unit_name and sub_state in {"running", "start", "start-pre", "start-post"}:
        status = "running"
    elif unit_name and sub_state == "failed":
        status = "failed"
    elif (
        expected_room_count and room_image_count >= expected_room_count
        and (expected_agent_count == 0 or agent_image_count >= expected_agent_count)
        and (expected_item_count == 0 or item_image_count >= expected_item_count)
    ):
        status = "complete"
    elif room_image_count or agent_image_count or item_image_count:
        status = "partial"
    elif worker_payload.get("status") == "launch_failed":
        status = "failed"
    return {
        "status": status,
        "unit_name": unit_name,
        "room_images": room_image_count,
        "expected_room_images": expected_room_count,
        "agent_images": agent_image_count,
        "expected_agent_images": expected_agent_count,
        "item_images": item_image_count,
        "expected_item_images": expected_item_count,
        "stdout_path": str(worker_payload.get("stdout_path", "")),
        "launcher_returncode": worker_payload.get("launcher_returncode", None),
        "launcher_stderr": str(worker_payload.get("launcher_stderr", "")),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def launch_asset_bundle_worker(
    *,
    package_root: Path = PACKAGE_ROOT,
    run_dir: Path,
    force_refresh_images: bool = False,
    wait_for_scenario_seconds: int = 180,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    log_dir = run_dir / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "asset_worker.log"
    py_bin = str(DEFAULT_PY_BIN if DEFAULT_PY_BIN.is_file() else Path(sys.executable))
    worker_cmd = [
        py_bin,
        "-m",
        "macro_ui.build_macro_ui",
        "--run-dir",
        str(run_dir),
        "--wait-for-scenario-seconds",
        str(int(wait_for_scenario_seconds)),
    ]
    if force_refresh_images:
        worker_cmd.append("--force-refresh-images")
    unit_name = f"agora-replay-assets-{_slug(run_dir.name)}"
    shell_command = (
        f". /home/yz_wang/.config/agora_ui_runtime.env && "
        f"export PYTHONPATH={json.dumps(str(package_root))}:$PYTHONPATH && "
        f"exec {' '.join(json.dumps(part) for part in worker_cmd)} >> {json.dumps(str(stdout_path))} 2>&1"
    )
    systemd_cmd = [
        "systemd-run",
        "--user",
        f"--unit={unit_name}",
        f"--working-directory={package_root}",
        "/bin/bash",
        "-lc",
        shell_command,
    ]
    with stdout_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[ASSET_WORKER] {datetime.now(timezone.utc).isoformat()} {' '.join(worker_cmd)}\n")
        handle.flush()
    result = subprocess.run(
        systemd_cmd,
        cwd=str(package_root),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = {
        "unit_name": unit_name,
        "run_dir": str(run_dir),
        "launched_at": datetime.now(timezone.utc).isoformat(),
        "stdout_path": str(stdout_path),
        "command": worker_cmd,
        "launcher_command": systemd_cmd,
        "launcher_returncode": int(result.returncode),
        "launcher_stdout": result.stdout.strip(),
        "launcher_stderr": result.stderr.strip(),
        "status": "launched" if result.returncode == 0 else "launch_failed",
    }
    _write_json(run_dir / ASSET_WORKER_RECORD_PATH, payload)
    return payload


