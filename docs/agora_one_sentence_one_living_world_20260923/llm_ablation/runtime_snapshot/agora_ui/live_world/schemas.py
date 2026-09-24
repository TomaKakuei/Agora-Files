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


LIVE_ACTION_SYNC_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class LiveAgentReply:
    response_text: str
    actor_focus: str
    target_focus: str
    response_source: str
    model: str
    latency_ms: int
    route_selection: dict[str, Any] | None = None
    tool_call: dict[str, Any] | None = None


@dataclass
class LiveCoordinatorCommand:
    command: str
    session_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    wait_for_completion: bool = True
    timeout_seconds: float = LIVE_ACTION_SYNC_TIMEOUT_SECONDS
    done: threading.Event = field(default_factory=threading.Event, repr=False)
    response: dict[str, Any] | None = None
    error: Exception | None = None


@dataclass(frozen=True)
class PixelWorldContext:
    package_root: Path
    access_code: str
    export_dir: Path
    package_db: Path
    workspace: Path
    config: dict[str, Any]
    metadata: dict[str, Any]
    rooms: list[dict[str, Any]]
    room_lookup: dict[str, dict[str, Any]]
    room_tile_index: dict[str, set[str]]
    outer_wall_tile_index: dict[str, set[str]]
    inner_wall_tile_index: dict[str, set[str]]
    agent_seed_payloads: list[dict[str, Any]]
    live_db_path: Path
    session_timeout_seconds: float
    roam_step_seconds: float

__all__ = ['LiveAgentReply', 'LiveCoordinatorCommand', 'PixelWorldContext']
