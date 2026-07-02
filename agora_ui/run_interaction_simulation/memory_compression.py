from __future__ import annotations
import base64
import json
import re
import subprocess
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from ..adjudicator_schemas import AgentRuntimeProfileSpec

def _limit_text(value: Any, limit: int = 180) -> str:
    return str(value or "").strip().replace("\n", " ")[:limit]


def _sanitize_recent_entry(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "round_index": _safe_int(raw.get("round_index", 0), 0),
        "other_agent_id": str(raw.get("other_agent_id", ""))[:128],
        "other_agent_name": _limit_text(raw.get("other_agent_name", ""), 80),
        "route_id": str(raw.get("route_id", ""))[:80],
        "story_verb": _limit_text(raw.get("story_verb", ""), 96),
        "room_id": str(raw.get("room_id", ""))[:80],
        "same_room": bool(raw.get("same_room", False)),
        "distance": _safe_int(raw.get("distance", 0), 0),
        "focus_note": _limit_text(raw.get("focus_note", ""), 140),
    }


def _sanitize_long_task(raw: dict[str, Any]) -> dict[str, Any]:
    preferred_routes = raw.get("preferred_routes", [])
    if isinstance(preferred_routes, str):
        preferred_routes = [preferred_routes]
    preferred_routes = [str(item)[:80] for item in preferred_routes if str(item).strip()][:8]
    return {
        "thread_id": str(raw.get("thread_id", ""))[:120],
        "title": _limit_text(raw.get("title", ""), 120),
        "description": _limit_text(raw.get("description", ""), 220),
        "room_id": str(raw.get("room_id", ""))[:80],
        "status": _limit_text(raw.get("status", "open"), 32) or "open",
        "next_step": _limit_text(raw.get("next_step", ""), 140),
        "preferred_routes": preferred_routes,
        "last_updated_round": _safe_int(raw.get("last_updated_round", 0), 0),
        "expires_after_rounds": max(1, _safe_int(raw.get("expires_after_rounds", 3), 3)),
        "touch_count": max(0, _safe_int(raw.get("touch_count", 0), 0)),
        "source": _limit_text(raw.get("source", ""), 48),
    }


def _sanitize_visual_artifact(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": _limit_text(raw.get("kind", "artifact"), 24) or "artifact",
        "artifact_label": _limit_text(raw.get("artifact_label", raw.get("item_name", "")), 96),
        "item_id": str(raw.get("item_id", "")).strip()[:80],
        "image_path": str(raw.get("image_path", "")).strip()[:500],
        "source": _limit_text(raw.get("source", ""), 48),
        "round_index": _safe_int(raw.get("round_index", 0), 0),
        "reasoning_image_path": str(raw.get("reasoning_image_path", "")).strip()[:500],
    }


def _sanitize_textual_artifact(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": _limit_text(raw.get("kind", "text_revision"), 24) or "text_revision",
        "artifact_label": _limit_text(raw.get("artifact_label", raw.get("item_id", "artifact")), 96),
        "item_id": str(raw.get("item_id", "")).strip()[:80],
        "description": _limit_text(raw.get("description", ""), 320),
        "source": _limit_text(raw.get("source", ""), 48),
        "round_index": _safe_int(raw.get("round_index", 0), 0),
        "counterpart_agent_id": str(raw.get("counterpart_agent_id", "")).strip()[:128],
        "counterpart_name": _limit_text(raw.get("counterpart_name", ""), 80),
    }


def _compress_image_for_reasoning(image_path: Path, *, max_edge_px: int) -> Path | None:
    try:
        resolved = image_path.resolve()
    except Exception:
        return None
    if not resolved.is_file():
        return None
    target = resolved.with_name(f"{resolved.stem}_reasoning_{int(max_edge_px)}px.jpg")
    if target.is_file():
        return target
    try:
        with Image.open(resolved) as handle:
            prepared = handle.convert("RGB")
            prepared.thumbnail((max_edge_px, max_edge_px), Image.LANCZOS)
            target.parent.mkdir(parents=True, exist_ok=True)
            prepared.save(target, format="JPEG", quality=88, optimize=True)
        return target
    except Exception:
        return None


def _archive_recent_entry(memory: dict[str, Any], entry: dict[str, Any]) -> None:
    memory["archived_round_count"] = max(0, _safe_int(memory.get("archived_round_count", 0), 0)) + 1
    route_counts = dict(memory.get("archived_route_counts", {}))
    route_id = str(entry.get("route_id", "")).strip()
    if route_id:
        route_counts[route_id] = max(0, _safe_int(route_counts.get(route_id, 0), 0)) + 1
    memory["archived_route_counts"] = route_counts
    counterpart_counts = dict(memory.get("archived_counterpart_counts", {}))
    other_agent_id = str(entry.get("other_agent_id", "")).strip()
    if other_agent_id:
        counterpart_counts[other_agent_id] = max(0, _safe_int(counterpart_counts.get(other_agent_id, 0), 0)) + 1
    memory["archived_counterpart_counts"] = counterpart_counts

