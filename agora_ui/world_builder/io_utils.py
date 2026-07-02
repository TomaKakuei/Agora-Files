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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text), encoding="utf-8")


def _clone_json(payload: Any) -> Any:
    return json.loads(json.dumps(payload))


def _slug(text: str) -> str:
    chars = [char.lower() if char.isalnum() else "_" for char in str(text or "")]
    normalized = "".join(chars).strip("_")
    return normalized or "world"


def _dedupe_texts(values: list[Any], *, limit: int | None = None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(text)
        if limit is not None and len(deduped) >= limit:
            break
    return deduped


def _keyword_tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
        tokens.update(part for part in text.split() if len(part) >= 3)
    return tokens


def _keyword_overlap_score(*values: Any, against: set[str]) -> int:
    if not against:
        return 0
    return len(_keyword_tokens(*values) & against)


def _first_non_empty(*values: Any, default: str = "") -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return default


def _get_mocked_fallback(func_name: str, default_val: Any) -> Any:
    import sys
    world_builder = sys.modules.get("agora_ui.world_builder")
    if world_builder is not None:
        mocked_func = getattr(world_builder, func_name, None)
        if mocked_func is not None:
            is_mocked = False
            is_mocked = False
            try:
                from unittest.mock import Mock
                if isinstance(mocked_func, Mock):
                    is_mocked = True
            except ImportError:
                pass

            if not is_mocked:
                if hasattr(mocked_func, "__code__") and hasattr(default_val, "__code__"):
                    if mocked_func.__code__ != default_val.__code__:
                        is_mocked = True
                elif mocked_func != default_val:
                    is_mocked = True
            if is_mocked:
                return mocked_func
    return default_val


__all__ = ['_now_iso', '_read_json', '_write_json', '_write_text', '_clone_json', '_slug', '_dedupe_texts', '_keyword_tokens', '_keyword_overlap_score', '_first_non_empty', '_get_mocked_fallback']
