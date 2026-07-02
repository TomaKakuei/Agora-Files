from __future__ import annotations
import calendar
import contextlib
import copy
import hashlib
import json
import os
import queue
import secrets
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from ..adjudicator_schemas import AgentRuntimeProfileSpec
from ..package_db import materialize_world_package
from ..world_definition import default_wallet_payload
from ..world_definition import legacy_currency_inventory_entry
from ..world_definition import sync_world_definition_into_config





def _now_ts() -> float:
    return time.time()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _iso_to_ts(value: Any, default: float = 0.0) -> float:
    text = str(value or "").strip()
    if not text:
        return float(default)
    try:
        return float(calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")))
    except Exception:
        return float(default)


def _json_load(text: str, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _merge_event_payload_json(conn: sqlite3.Connection, event_id: int, extra_payload: dict[str, Any]) -> str:
    row = conn.execute("SELECT payload_json FROM events WHERE event_id = ?", (event_id,)).fetchone()
    existing = _json_load(str(row[0] or "") if row is not None else "", {})
    if not isinstance(existing, dict):
        existing = {}
    existing.update(extra_payload or {})
    return _json_dump(existing)


def _format_template(template: str, values: dict[str, Any]) -> str:
    text = str(template or "")
    for key, value in values.items():
        text = text.replace(f"{{{key}}}", str(value))
    return text


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _trim_text(value: Any, limit: int = 320) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


DEFAULT_SESSION_TIMEOUT_SECONDS = 1800.0
DEFAULT_ROAM_STEP_SECONDS = 4.0


def _session_timeout_seconds(config: dict[str, Any]) -> float:
    human_cfg = config.get("human_interaction", {}) if isinstance(config.get("human_interaction", {}), dict) else {}
    explicit_timeout = _safe_float(human_cfg.get("session_timeout_seconds", DEFAULT_SESSION_TIMEOUT_SECONDS), DEFAULT_SESSION_TIMEOUT_SECONDS)
    if explicit_timeout > 0:
        return max(1800.0, explicit_timeout)
    derived_timeout = _safe_float(human_cfg.get("speed_seconds_per_round", DEFAULT_ROAM_STEP_SECONDS), DEFAULT_ROAM_STEP_SECONDS) * 4.0
    return max(1800.0, derived_timeout)


def _roam_step_seconds(config: dict[str, Any]) -> float:
    frontend = config.get("pixel_asset_pipeline", {}).get("frontend", {})
    if isinstance(frontend, dict):
        return max(1.0, _safe_float(frontend.get("roam_preview_step_seconds", DEFAULT_ROAM_STEP_SECONDS), DEFAULT_ROAM_STEP_SECONDS))
    return DEFAULT_ROAM_STEP_SECONDS

__all__ = ['_now_ts', '_now_iso', '_iso_to_ts', '_json_load', '_json_dump', '_merge_event_payload_json', '_format_template', '_safe_int', '_safe_float', '_trim_text', '_load_json', '_session_timeout_seconds', '_roam_step_seconds']
