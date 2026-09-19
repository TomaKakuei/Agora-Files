#!/usr/bin/env python3
"""Prepare paired, fixed-world Tidal Embassy interaction configurations."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from agora_ui.world_builder.builder import _interaction_affordance_catalog


SEED_FACT = (
    "PRIVATE FLOOD ALERT: The lower archive will flood before the sixteenth round. "
    "The only surviving peace treaty must be moved and authenticated; most residents do not know this."
)

WORLD_ROUTES = [
    {
        "route_id": "translate_archaic_bribe",
        "kind": "custom",
        "action": "Translate Bribe",
        "status_effect": "bribe_translation_shared",
        "duration_steps": 2,
        "weight": 13,
        "story_verb": "translated an archaic bribe with",
        "selection_guidance": "Translate a political bribe into an archaic metaphor whose meaning can be passed to another resident.",
    },
    {
        "route_id": "forge_linguistic_seal",
        "kind": "custom",
        "action": "Forge Linguistic Seal",
        "status_effect": "treaty_seal_forged",
        "duration_steps": 3,
        "weight": 13,
        "story_verb": "forged a linguistic seal with",
        "selection_guidance": "Create or inspect a seal that can authenticate a disputed treaty or archive record.",
    },
    {
        "route_id": "rescue_flooded_treaty",
        "kind": "custom",
        "action": "Rescue Treaty",
        "status_effect": "treaty_rescue_advanced",
        "duration_steps": 3,
        "weight": 16,
        "story_verb": "advanced the treaty rescue with",
        "selection_guidance": "Coordinate a concrete step to locate, move, preserve, or authenticate the threatened peace treaty.",
    },
]


def prepare(base: dict[str, Any], *, memory_ablation: bool) -> dict[str, Any]:
    config = copy.deepcopy(base)
    config.setdefault("scenario_meta", {})["experiment_condition"] = "memory_ablation" if memory_ablation else "full_memory"
    config["scenario_meta"]["seed_event_protocol"] = "private_treaty_flood_alert_v1"
    vertex = config.setdefault("vertex_api", {})
    vertex.update(
        {
            "backend": "ai_studio",
            "api_key_env": "AGORA_AISTUDIO_API_KEY",
            "endpoint_base": "https://generativelanguage.googleapis.com/v1beta",
            "method": "generateContent",
            "model": "gemini-2.5-flash",
            "thinking_level": "low",
            "thinking_budget": 512,
        }
    )
    for stage in vertex.get("stages", {}).values():
        if isinstance(stage, dict):
            stage["model"] = "gemini-2.5-flash"
    actions = config.setdefault("actions", {})
    existing = [dict(route) for route in actions.get("ordinary_routes", []) if isinstance(route, dict)]
    existing_ids = {str(route.get("route_id", "")) for route in existing}
    actions["ordinary_routes"] = existing + [route for route in WORLD_ROUTES if route["route_id"] not in existing_ids]
    actions["interaction_affordance_catalog"] = _interaction_affordance_catalog(
        actions["ordinary_routes"]
        + [dict(route) for route in actions.get("cinematic_routes", []) if isinstance(route, dict)]
    )
    for character in config.get("main_characters", [])[:3]:
        if not isinstance(character, dict):
            continue
        knowledge = character.setdefault("knowledge_assets", [])
        knowledge.append(
            {
                "knowledge_id": "private_treaty_flood_alert_v1",
                "topic": "Lower Archive Flood Threat",
                "summary": SEED_FACT,
                "confidence": 100,
                "visibility": "private",
            }
        )
        character["private_notes"] = f"{character.get('private_notes', '')} {SEED_FACT}".strip()
    for index, character in enumerate(config.get("main_characters", [])):
        if isinstance(character, dict):
            character["always_activate"] = index < 3
    memory = config.setdefault("memory", {})
    if memory_ablation:
        memory.update(
            {
                "keep_recent_rounds": 0,
                "max_active_long_tasks": 0,
                "max_cohort_ids": 0,
                "max_related_agents": 0,
            }
        )
    config.setdefault("image_generation", {})["enabled"] = False
    config.setdefault("longlive", {})["enabled"] = False
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    base = json.loads(args.base.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, ablation in (("full_memory", False), ("memory_ablation", True)):
        output = args.output_dir / f"tidal_embassy_{name}.json"
        output.write_text(json.dumps(prepare(base, memory_ablation=ablation), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
