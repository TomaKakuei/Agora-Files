from __future__ import annotations

import argparse

import asyncio

import json

import random

from collections import Counter, deque

from dataclasses import dataclass

from datetime import datetime

from pathlib import Path

from typing import Any, Dict, List, Optional, Tuple, Union

from ..flex_client import AsyncFlexClient

from ..foundation_schemas import (
    CompiledRoomSpec,
    CompiledWorldAgent,
    CompiledWorldSpec,
    GridPosition,
    GridShape,
    MovementPolicy,
    RoomSpec,
    WorldAgentSpec,
    WorldAgentsSpec,
    WorldControlSpec,
    WorldRuleDebugManifest,
    WorldRuleTraceRecord,
    WorldSpec,
)

from ..jsonc_utils import dump_json, load_jsonc_path

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent

DEFAULT_TEMPLATE_DIR = SCRIPT_DIR / "data" / "templates" / "foundation"

DEFAULT_WORLD_TEMPLATE = DEFAULT_TEMPLATE_DIR / "world_template.jsonc"

DEFAULT_WORLD_AGENTS = DEFAULT_TEMPLATE_DIR / "world_agents.jsonc"

DEFAULT_WORLD_CONTROL = DEFAULT_TEMPLATE_DIR / "world_control.jsonc"

DEFAULT_OUTPUT_ROOT = SCRIPT_DIR / "output" / "world_rule_debug"

CoordKey = Tuple[int, int, int]

RoomAdjacency = Dict[str, List[Tuple[str, GridPosition, str]]]

RuntimeRooms = Dict[str, str]

RuntimePositions = Dict[str, GridPosition]

@dataclass
class ReachableTarget:
    """A room that an agent can reach from the current round snapshot."""

    room_id: str
    room_name: str
    coordinate: GridPosition
    steps: int
    path_room_ids: List[str]
    axis_usage: Dict[str, int]

@dataclass
class MovementDecision:
    """Normalized planner output used by both heuristic and Flex backends."""

    agent_id: str
    decision_backend: str
    requested_action: str
    decision_status: str
    decision_reason: str
    requested_target_room_id: Optional[str] = None
    target_coordinate: Optional[GridPosition] = None
    requested_steps: int = 0
    path_room_ids: Optional[List[str]] = None
    note: str = ""

def _resolve_path(path_like: Union[str, Path]) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path.resolve()
    local = (SCRIPT_DIR / path).resolve()
    if local.exists():
        return local
    return (Path.cwd() / path).resolve()

def _now_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _coord_key(position: GridPosition) -> CoordKey:
    return (position.x, position.y, position.z)

def _time_to_minutes(raw: str) -> int:
    hour_text, minute_text = str(raw).strip().split(":")
    return int(hour_text) * 60 + int(minute_text)

def _minutes_to_time(total_minutes: int) -> str:
    normalized = int(total_minutes) % (24 * 60)
    hour = normalized // 60
    minute = normalized % 60
    return f"{hour:02d}:{minute:02d}"

__all__ = ["SCRIPT_DIR", "DEFAULT_TEMPLATE_DIR", "DEFAULT_WORLD_TEMPLATE", "DEFAULT_WORLD_AGENTS", "DEFAULT_WORLD_CONTROL", "DEFAULT_OUTPUT_ROOT", "CoordKey", "RoomAdjacency", "RuntimeRooms", "RuntimePositions", "ReachableTarget", "MovementDecision", "_resolve_path", "_now_run_id", "_now_iso", "_coord_key", "_time_to_minutes", "_minutes_to_time"]
