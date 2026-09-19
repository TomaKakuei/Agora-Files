from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.world_builder.generation import _execute_json_prompt


HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _visual_canon_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "canon_id",
            "camera",
            "palette",
            "materials",
            "lighting",
            "architecture",
            "terrain",
            "sprite_language",
            "world_prompt_prefix",
            "sprite_prompt_prefix",
            "forbidden_visuals",
        ],
        "properties": {
            "canon_id": {"type": "string"},
            "camera": {
                "type": "object",
                "required": ["projection", "pitch", "scale_rule"],
                "properties": {
                    "projection": {
                        "type": "string",
                        "enum": ["strict_top_down"],
                    },
                    "pitch": {"type": "string"},
                    "scale_rule": {"type": "string"},
                },
            },
            "palette": {
                "type": "object",
                "required": ["dominant", "secondary", "accent", "shadow", "highlight"],
                "properties": {
                    "dominant": {"type": "string"},
                    "secondary": {"type": "string"},
                    "accent": {"type": "string"},
                    "shadow": {"type": "string"},
                    "highlight": {"type": "string"},
                },
            },
            "materials": {"type": "array", "items": {"type": "string"}},
            "lighting": {"type": "string"},
            "architecture": {"type": "array", "items": {"type": "string"}},
            "terrain": {
                "type": "object",
                "required": ["ground", "path", "edge"],
                "properties": {
                    "ground": {"type": "string"},
                    "path": {"type": "string"},
                    "edge": {"type": "string"},
                },
            },
            "sprite_language": {
                "type": "object",
                "required": ["body_proportion", "outline", "role_readability"],
                "properties": {
                    "body_proportion": {"type": "string"},
                    "outline": {"type": "string"},
                    "role_readability": {"type": "string"},
                },
            },
            "world_prompt_prefix": {"type": "string"},
            "sprite_prompt_prefix": {"type": "string"},
            "forbidden_visuals": {"type": "array", "items": {"type": "string"}},
        },
    }


def _compact_texts(values: Any, *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    if not isinstance(values, list):
        return result
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _normalize_visual_canon(payload: dict[str, Any], planner_spec: dict[str, Any]) -> dict[str, Any]:
    palette = dict(payload.get("palette", {}))
    for key in ("dominant", "secondary", "accent", "shadow", "highlight"):
        value = str(palette.get(key, "")).strip()
        if not HEX_COLOR.fullmatch(value):
            raise ValueError(f"Visual canon palette.{key} must be a six-digit hex color, got {value!r}.")
        palette[key] = value.lower()

    camera = dict(payload.get("camera", {}))
    projection = str(camera.get("projection", "")).strip()
    if projection != "strict_top_down":
        raise ValueError(f"Visual canon returned unsupported projection: {projection!r}.")

    materials = _compact_texts(payload.get("materials", []), limit=8)
    architecture = _compact_texts(payload.get("architecture", []), limit=8)
    forbidden = _compact_texts(payload.get("forbidden_visuals", []), limit=16)
    if len(materials) < 3 or len(architecture) < 3 or len(forbidden) < 4:
        raise ValueError("Visual canon must define at least three materials, three architectural rules, and four forbidden visuals.")

    normalized = {
        "canon_version": "world_visual_canon_v1",
        "generated_by": "world_builder.nodes.visual_canon",
        "model_stage": "world_visual_canon_generation",
        "canon_id": str(payload.get("canon_id", "") or f"{planner_spec.get('world_id', 'world')}_visual_canon").strip(),
        "camera": {
            "projection": projection,
            "pitch": str(camera.get("pitch", "")).strip(),
            "scale_rule": str(camera.get("scale_rule", "")).strip(),
        },
        "palette": palette,
        "materials": materials,
        "lighting": str(payload.get("lighting", "")).strip(),
        "architecture": architecture,
        "terrain": {
            key: str(dict(payload.get("terrain", {})).get(key, "")).strip()
            for key in ("ground", "path", "edge")
        },
        "sprite_language": {
            key: str(dict(payload.get("sprite_language", {})).get(key, "")).strip()
            for key in ("body_proportion", "outline", "role_readability")
        },
        "world_prompt_prefix": str(payload.get("world_prompt_prefix", "")).strip(),
        "sprite_prompt_prefix": str(payload.get("sprite_prompt_prefix", "")).strip(),
        "forbidden_visuals": forbidden,
    }
    required_texts = [
        normalized["lighting"],
        normalized["world_prompt_prefix"],
        normalized["sprite_prompt_prefix"],
        *normalized["terrain"].values(),
        *normalized["sprite_language"].values(),
        normalized["camera"]["pitch"],
        normalized["camera"]["scale_rule"],
    ]
    if any(not value for value in required_texts):
        raise ValueError("Visual canon contains an empty required visual rule.")

    canonical_json = json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    normalized["canon_hash"] = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:16]
    return normalized


def generate_visual_canon(
    provider: VertexJsonClient,
    planner_spec: dict[str, Any],
    repair_note: str = "",
) -> dict[str, Any]:
    prompt = f"""
You are the World Visual Canon node for Agora.

Create one compact, enforceable art direction shared by every room, character, prop, map layer, and runtime overlay.
This is a production contract, not mood-board prose. Use a strict orthographic top-down camera, one bounded five-color palette,
three to eight recurring materials, one lighting grammar, and repeatable architectural and sprite rules.

The canon must make this world visually distinguishable from generic fantasy RPGs, generic cyberpunk,
generic beige procedural terrain, and unrelated real-world locations. Use six-digit hex colors.
The world_prompt_prefix and sprite_prompt_prefix must be concise reusable prompt fragments.
The camera projection must be strict_top_down because the runtime uses a collision-aligned tile grid.
Forbid visible labels, title text, poster/card layouts, disconnected room dioramas, photorealism,
and any aesthetics unrelated to this exact premise.

Planner context:
{json.dumps(planner_spec, ensure_ascii=False)}
"""
    if repair_note:
        prompt += f"\nRepair note:\n{repair_note}\n"

    payload = _execute_json_prompt(
        provider=provider,
        system_instruction=(
            "You are a specialist visual director. Return only a compact JSON visual contract "
            "that downstream generators can reuse verbatim."
        ),
        prompt=prompt,
        response_schema=_visual_canon_schema(),
        temperature=0.25,
        max_output_tokens=2048,
        thinking_level="low",
        thinking_budget=128,
        stage="world_visual_canon_generation",
    )
    return _normalize_visual_canon(payload, planner_spec)
