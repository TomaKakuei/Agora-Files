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
__all__ = ["_image_client_for_config", "_ensure_room_images", "_ensure_agent_images", "_collect_item_image_specs", "_ensure_item_images", "_prepare_media_jobs", "_room_frame_payload", "_room_cell_bounds", "_frame_agents_payload", "_image_request_spacing_seconds", "_character_portraits_enabled", "_item_image_mode", "_item_is_important_artifact"]

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


def _image_client_for_config(config: dict[str, Any]) -> VertexInlineImageClient:
    vertex_api = dict(config.get("vertex_api", {}))
    image_model = str(
        config.get("macro_ui", {}).get("image_model")
        or config.get("image_generation", {}).get("model")
        or "gemini-2.5-flash-image-preview"
    ).strip()
    return VertexInlineImageClient(
        api_key_env=str(vertex_api.get("api_key_env", "AGORA_VERTEX_API_KEY")),
        endpoint_base=str(vertex_api.get("endpoint_base", "https://aiplatform.googleapis.com/v1")),
        model=image_model,
        timeout_seconds=int(config.get("macro_ui", {}).get("timeout_seconds", 180) or 180),
    )


def _ensure_room_images(
    *,
    config: dict[str, Any],
    rooms: list[dict[str, Any]],
    replay_assets_dir: Path,
    force_refresh_images: bool,
    allow_generate: bool,
) -> dict[str, str]:
    image_client = _image_client_for_config(config) if allow_generate else None
    spacing_seconds = _image_request_spacing_seconds(config)
    room_urls: dict[str, str] = {}
    for room in rooms:
        prompt = _room_prompt(config, room)
        room_slug = _slug(room.get("room_id", room.get("name", "room")))
        prompt_hash = _hash_prompt(prompt)
        target_stub = replay_assets_dir / "images" / "rooms" / f"{room_slug}_{prompt_hash}"
        existing_candidates = list(target_stub.parent.glob(f"{target_stub.name}.*"))
        if existing_candidates and not force_refresh_images:
            image_path = existing_candidates[0]
        elif allow_generate:
            assert image_client is not None
            try:
                result = image_client.generate_image(prompt=prompt, output_path=target_stub.with_suffix(".png"))
                image_path = Path(result["image_path"])
                if spacing_seconds > 0:
                    time.sleep(spacing_seconds)
            except Exception as exc:
                print(
                    f"[MACRO_UI_IMAGE_WARN] kind=room room_id={room.get('room_id', '')} error={exc}",
                    flush=True,
                )
                image_path = existing_candidates[0] if existing_candidates else None
        else:
            image_path = None
        room_urls[str(room.get("room_id", ""))] = _static_url(image_path) if image_path is not None else ""
    return room_urls


def _ensure_agent_images(
    *,
    config: dict[str, Any],
    agents: list[dict[str, Any]],
    room_lookup: dict[str, dict[str, Any]],
    replay_assets_dir: Path,
    force_refresh_images: bool,
    allow_generate: bool,
) -> dict[str, str]:
    image_client = _image_client_for_config(config) if allow_generate else None
    spacing_seconds = _image_request_spacing_seconds(config)
    agent_urls: dict[str, str] = {}
    for agent in agents:
        prompt = _agent_prompt(config, agent, room_lookup)
        agent_slug = _slug(str(agent.get("agent_id", "")))
        prompt_hash = _hash_prompt(prompt)
        target_stub = replay_assets_dir / "images" / "agents" / f"{agent_slug}_{prompt_hash}"
        existing_candidates = list(target_stub.parent.glob(f"{target_stub.name}.*"))
        if existing_candidates and not force_refresh_images:
            image_path = existing_candidates[0]
        elif allow_generate:
            assert image_client is not None
            try:
                result = image_client.generate_image(prompt=prompt, output_path=target_stub.with_suffix(".png"))
                image_path = Path(result["image_path"])
                if spacing_seconds > 0:
                    time.sleep(spacing_seconds)
            except Exception as exc:
                print(
                    f"[MACRO_UI_IMAGE_WARN] kind=agent agent_id={agent.get('agent_id', '')} error={exc}",
                    flush=True,
                )
                image_path = existing_candidates[0] if existing_candidates else None
        else:
            image_path = None
        agent_urls[str(agent.get("agent_id", ""))] = _static_url(image_path) if image_path is not None else ""
    return agent_urls


def _collect_item_image_specs(
    agents: list[dict[str, Any]],
    *,
    mode: str,
) -> dict[str, dict[str, Any]]:
    if mode == "off":
        return {}
    collected: dict[str, dict[str, Any]] = {}
    for agent in agents:
        for item in agent.get("inventory", []) or []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("item_id", "")).strip()
            if not item_id or int(item.get("quantity", 0) or 0) <= 0:
                continue
            if mode == "important_only" and not _item_is_important_artifact(item):
                continue
            current = collected.get(item_id)
            candidate = dict(item)
            if current is None:
                collected[item_id] = candidate
                continue
            current_prompt = str(current.get("image_prompt", "")).strip()
            candidate_prompt = str(candidate.get("image_prompt", "")).strip()
            if candidate_prompt and not current_prompt:
                collected[item_id] = candidate
    return collected


def _ensure_item_images(
    *,
    config: dict[str, Any],
    items: dict[str, dict[str, Any]],
    replay_assets_dir: Path,
    force_refresh_images: bool,
    allow_generate: bool,
) -> dict[str, str]:
    if not items:
        return {}
    image_client = _image_client_for_config(config) if allow_generate else None
    spacing_seconds = _image_request_spacing_seconds(config)
    item_urls: dict[str, str] = {}
    for item_id, item in items.items():
        existing_local = _resolve_asset_path(item.get("image_path", ""))
        if existing_local is not None and existing_local.is_file():
            item_urls[item_id] = _static_url_if_local(existing_local)
            continue
        prompt = _item_prompt(config, item)
        item_slug = _slug(item_id or item.get("description", "item"))
        prompt_hash = _hash_prompt(prompt)
        target_stub = replay_assets_dir / "images" / "items" / f"{item_slug}_{prompt_hash}"
        existing_candidates = list(target_stub.parent.glob(f"{target_stub.name}.*"))
        if existing_candidates and not force_refresh_images:
            image_path = existing_candidates[0]
        elif allow_generate:
            assert image_client is not None
            try:
                result = image_client.generate_image(prompt=prompt, output_path=target_stub.with_suffix(".png"))
                image_path = Path(result["image_path"])
                if spacing_seconds > 0:
                    time.sleep(spacing_seconds)
            except Exception as exc:
                print(
                    f"[MACRO_UI_IMAGE_WARN] kind=item item_id={item_id} error={exc}",
                    flush=True,
                )
                image_path = existing_candidates[0] if existing_candidates else None
        else:
            image_path = None
        item_urls[item_id] = _static_url(image_path) if image_path is not None else ""
    return item_urls


def _prepare_media_jobs(jobs: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for job in jobs:
        record = dict(job)
        media_path_value = str(job.get(key, "")).strip()
        media_path = Path(media_path_value).resolve() if media_path_value else None
        record[f"{key[:-5]}_url"] = _static_url(media_path) if media_path and media_path.is_file() else ""
        prepared.append(record)
    return prepared


def _room_frame_payload(
    rooms: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    room_image_urls: dict[str, str],
    *,
    capacity_per_coordinate: int,
) -> list[dict[str, Any]]:
    occupants_by_room: dict[str, list[str]] = {}
    for agent in agents:
        room_id = str(agent.get("room_id", "")).strip()
        occupants_by_room.setdefault(room_id, []).append(str(agent.get("agent_id", "")))
    payload: list[dict[str, Any]] = []
    for room in rooms:
        room_id = str(room.get("room_id", ""))
        occupant_ids = sorted(occupants_by_room.get(room_id, []))
        capacity = _room_capacity_payload(room, len(occupant_ids), capacity_per_coordinate)
        payload.append(
            {
                "room_id": room_id,
                "name": str(room.get("name", room_id)),
                "x": int(room.get("x", 0)),
                "y": int(room.get("y", 0)),
                "z": int(room.get("z", 0)),
                "width_tiles": int(room.get("width_tiles", 1) or 1),
                "height_tiles": int(room.get("height_tiles", 1) or 1),
                "footprint_tiles": [dict(item) for item in room.get("footprint_tiles", []) if isinstance(item, dict)],
                "doorways": [dict(item) for item in room.get("doorways", []) if isinstance(item, dict)],
                "spawn_points": [dict(item) for item in room.get("spawn_points", []) if isinstance(item, dict)],
                "visual": dict(room.get("visual", {})),
                "image_url": room_image_urls.get(room_id, ""),
                "occupant_count": len(occupant_ids),
                "occupant_ids": occupant_ids,
                **capacity,
            }
        )
    return payload


def _room_cell_bounds(rooms: list[dict[str, Any]]) -> dict[str, int]:
    xs: list[int] = []
    ys: list[int] = []
    for room in rooms:
        explicit = [dict(item) for item in room.get("footprint_tiles", []) if isinstance(item, dict)]
        if explicit:
            xs.extend(int(item.get("x", room.get("x", 0))) for item in explicit)
            ys.extend(int(item.get("y", room.get("y", 0))) for item in explicit)
        else:
            base_x = int(room.get("x", 0))
            base_y = int(room.get("y", 0))
            width_tiles = max(1, int(room.get("width_tiles", 1) or 1))
            height_tiles = max(1, int(room.get("height_tiles", 1) or 1))
            xs.extend(base_x + offset for offset in range(width_tiles))
            ys.extend(base_y + offset for offset in range(height_tiles))
    return {
        "min_x": min(xs, default=0),
        "max_x": max(xs, default=0),
        "min_y": min(ys, default=0),
        "max_y": max(ys, default=0),
    }


def _frame_agents_payload(
    agents: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    item_image_urls: dict[str, str],
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for agent in agents:
        payload.append(_agent_payload(agent, config=config, item_image_urls=item_image_urls))
    return payload


def _image_request_spacing_seconds(config: dict[str, Any]) -> float:
    macro_ui = config.get("macro_ui", {})
    if isinstance(macro_ui, dict):
        try:
            return max(0.0, float(macro_ui.get("image_request_spacing_seconds", 2.5)))
        except Exception:
            return 2.5
    return 2.5


def _character_portraits_enabled(config: dict[str, Any]) -> bool:
    return bool(_image_generation_config(config).get("generate_character_portraits", True))


def _item_image_mode(config: dict[str, Any]) -> str:
    return _normalize_item_image_mode(_image_generation_config(config).get("item_image_mode", "important_only"))


def _item_is_important_artifact(item: dict[str, Any]) -> bool:
    metadata = dict(item.get("metadata", {})) if isinstance(item.get("metadata", {}), dict) else {}
    if bool(metadata.get("important_artifact")):
        return True
    rarity = str(metadata.get("rarity", "")).strip().lower()
    category = str(metadata.get("category", "")).strip().lower()
    text = " ".join(
        part
        for part in [
            str(metadata.get("name", "")),
            str(item.get("description", "")),
            str(item.get("item_id", "")),
            category,
        ]
        if str(part).strip()
    ).lower()
    if rarity in {"rare", "epic", "legendary", "unique"}:
        return True
    if category in {"artifact", "relic", "quest_item", "quest", "heirloom"}:
        return True
    return any(token in text for token in ("artifact", "relic", "heirloom", "seal", "crystal", "map"))


