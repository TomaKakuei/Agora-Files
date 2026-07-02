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





def _output_config(config: dict[str, Any]) -> dict[str, Any]:
    output = config.get("output", {})
    return output if isinstance(output, dict) else {}


def _report_config(config: dict[str, Any]) -> dict[str, Any]:
    report = config.get("report", {})
    return report if isinstance(report, dict) else {}


def _condition_mode(config: dict[str, Any]) -> str:
    meta = config.get("scenario_meta", {})
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("condition_mode", "")).strip().lower()


def _text_only_mode(config: dict[str, Any]) -> bool:
    return _condition_mode(config) == "text_only"


def _normalize_item_image_mode(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"all", "important_only", "off"}:
        return raw
    if raw in {"important", "important-artifacts", "important_artifacts"}:
        return "important_only"
    return "important_only"


def _character_portraits_enabled(config: dict[str, Any]) -> bool:
    return bool(_image_generation_config(config).get("generate_character_portraits", True))


def _item_image_mode(config: dict[str, Any]) -> str:
    if _text_only_mode(config):
        return "off"
    return _normalize_item_image_mode(_image_generation_config(config).get("item_image_mode", "important_only"))


def _artifact_reasoning_enabled(config: dict[str, Any]) -> bool:
    if _text_only_mode(config):
        return False
    image_config = _image_generation_config(config)
    return bool(image_config.get("artifact_image_reasoning_enabled", True))


def _artifact_reasoning_max_edge_px(config: dict[str, Any]) -> int:
    image_config = _image_generation_config(config)
    return max(128, int(image_config.get("artifact_reasoning_max_edge_px", 500) or 500))


def _images_enabled(config: dict[str, Any]) -> bool:
    return bool(_image_generation_config(config).get("enabled", False))


def _image_max_per_round(config: dict[str, Any]) -> int:
    return max(0, int(_image_generation_config(config).get("max_images_per_round", 0)))


def _catalog_by_id(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["item_id"]): dict(item)
        for item in (
            config.get("property_library", {}).get("item_catalog", [])
            if isinstance(config.get("property_library", {}), dict) and config.get("property_library", {}).get("item_catalog")
            else config.get("economy", {}).get("item_catalog", [])
        )
        if isinstance(item, dict) and str(item.get("item_id", "")).strip()
    }


def _scenario_file_paths(scenario_dir: Path) -> dict[str, Path]:
    return {
        "manifest": scenario_dir / "manifest.json",
        "world_rules": scenario_dir / "world_rules.json",
        "map_grid": scenario_dir / "map_grid.json",
        "agents_dir": scenario_dir / "Agents",
    }

__all__ = ['_output_config', '_report_config', '_condition_mode', '_text_only_mode', '_normalize_item_image_mode', '_character_portraits_enabled', '_item_image_mode', '_artifact_reasoning_enabled', '_artifact_reasoning_max_edge_px', '_images_enabled', '_image_max_per_round', '_catalog_by_id', '_scenario_file_paths']
