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


def _static_url(path: Path) -> str:
def _resolve_asset_path(path_value: Any, *, package_root: Path = PACKAGE_ROOT) -> Path | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    resolved = (package_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not resolved.is_file():
        return None
    try:
        resolved.relative_to(package_root)
    except Exception:
        return None
    return resolved


def _image_request_spacing_seconds(config: dict[str, Any]) -> float:
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
