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

from .utils import _load_json





def _seed_agent(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = AgentRuntimeProfileSpec.model_validate(payload).model_dump()
    public_state = normalized.get("public_state", {})
    runtime_memory = public_state.get("runtime_memory", {}) if isinstance(public_state, dict) else {}
    return {
        **normalized,
        "display_name": str(normalized.get("display_name", "")).strip() or str(normalized.get("agent_id", "")),
        "current_focus": str(runtime_memory.get("current_focus", "")) if isinstance(runtime_memory, dict) else "",
        "mainline_summary": str(runtime_memory.get("mainline_summary", "")) if isinstance(runtime_memory, dict) else "",
    }


def _resolve_agent_seed_payloads(workspace: Path) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    for relative in (
        "scenario/Agents",
        "run_inputs/scenario/Agents",
    ):
        directory = workspace / relative
        if directory.is_dir():
            candidates.extend(sorted(directory.glob("*.json")))
    if not candidates:
        bootstrap = workspace / "frontend" / "bootstrap_agents.json"
        if bootstrap.is_file():
            raw = _load_json(bootstrap)
            agents = raw.get("agents", []) if isinstance(raw, dict) else []
            if isinstance(agents, list):
                candidates = []
                return [_seed_agent(agent) for agent in agents if isinstance(agent, dict)]
    payloads: list[dict[str, Any]] = []
    for path in candidates:
        try:
            payload = _load_json(path)
        except Exception:
            continue
        if isinstance(payload, dict):
            payloads.append(_seed_agent(payload))
    return payloads

__all__ = ['_seed_agent', '_resolve_agent_seed_payloads']
