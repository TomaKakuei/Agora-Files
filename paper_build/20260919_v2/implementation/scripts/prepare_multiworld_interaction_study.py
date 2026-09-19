#!/usr/bin/env python3
"""Prepare comparable AI Studio interaction configs for held-out worlds."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from agora_ui.world_builder.builder import _interaction_affordance_catalog


def prepare(base: dict[str, Any]) -> dict[str, Any]:
    config = copy.deepcopy(base)
    config.setdefault("scenario_meta", {})["interaction_study_protocol"] = "multiworld_open_actions_v1"
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
    ordinary = [dict(item) for item in actions.get("ordinary_routes", []) if isinstance(item, dict)]
    existing_actions = {str(item.get("action", "")).strip().lower() for item in ordinary}
    generic_actions = {"chat", "inspect", "coordinate", "trade", "move", "cinematicinteraction"}
    for index, raw_action in enumerate(actions.get("allowed_custom_actions", []), start=1):
        action = str(raw_action).strip()
        if not action or action.lower() in generic_actions or action.lower() in existing_actions:
            continue
        ordinary.append(
            {
                "route_id": "world_action_" + "_".join(action.lower().replace("-", " ").split())[:64],
                "kind": "custom",
                "action": action,
                "status_effect": "world_action_advanced_" + str(index),
                "duration_steps": 2,
                "weight": 10,
                "story_verb": action.lower(),
                "selection_guidance": f"Perform the world-specific action: {action}",
                "open_follow_up_allowed": True,
            }
        )
        existing_actions.add(action.lower())
    actions["ordinary_routes"] = ordinary
    cinematic = [dict(item) for item in actions.get("cinematic_routes", []) if isinstance(item, dict)]
    actions["interaction_affordance_catalog"] = _interaction_affordance_catalog(ordinary + cinematic)
    actions.setdefault("routing_policy", {})["catalog_role"] = (
        "The catalog is a discovery surface, not an action ceiling. Use __propose__ when a specific, legal intention is not represented."
    )
    actions["routing_policy"]["open_action_examples"] = [
        "say context-specific words to this particular target",
        "offer an asymmetric trade the target may accept, reject, or counter",
        "create a bounded new object from available inputs",
    ]
    config.setdefault("world_rules", {}).setdefault("custom_action_rules", {})["open_proposals_enabled"] = True
    for index, character in enumerate(config.get("main_characters", [])):
        if isinstance(character, dict):
            character["always_activate"] = index < 2
    config.setdefault("agent_generation", {}).setdefault("profile_generation", {})["enabled"] = False
    config.setdefault("image_generation", {})["enabled"] = False
    config.setdefault("longlive", {})["enabled"] = False
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for source in args.inputs:
        base = json.loads(source.read_text(encoding="utf-8"))
        config = prepare(base)
        world_id = str(config.get("scenario_meta", {}).get("world_id", source.stem))
        output = args.output_dir / f"{world_id}.json"
        output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest.append({"world_id": world_id, "world_name": config.get("scenario_meta", {}).get("world_name", ""), "config": str(output)})
    (args.output_dir / "manifest.json").write_text(json.dumps({"worlds": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
