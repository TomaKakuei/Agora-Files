#!/usr/bin/env python3
"""Audit whether a compiled world exposes varied, consequential interactions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


GENERIC_LABELS = {"chat", "inspect", "coordinate", "trade", "move", "interact", "act together", "document"}


def audit(config: dict[str, Any]) -> dict[str, Any]:
    actions = config.get("actions", {}) if isinstance(config.get("actions", {}), dict) else {}
    catalog = [item for item in actions.get("interaction_affordance_catalog", []) if isinstance(item, dict)]
    families = {str(item.get("interaction_family", "")) for item in catalog if item.get("interaction_family")}
    shared = [item for item in catalog if {"human", "ai"}.issubset(set(item.get("actor_modes", [])))]
    consequential = [item for item in catalog if item.get("persistent_effects")]
    world_specific = [item for item in catalog if str(item.get("label", "")).strip().lower() not in GENERIC_LABELS]
    target_types = {target for item in catalog for target in item.get("target_types", [])}
    count = len(catalog)
    checks = {
        "at_least_eight_affordances": count >= 8,
        "at_least_four_interaction_families": len(families) >= 4,
        "human_ai_shared_contract": len(shared) == count and count > 0,
        "persistent_effect_coverage": len(consequential) / count >= 0.75 if count else False,
        "world_specific_actions": len(world_specific) >= 3,
        "supports_agents_and_players": {"agent", "human_player"}.issubset(target_types),
    }
    return {
        "world_id": config.get("scenario_meta", {}).get("world_id", ""),
        "affordance_count": count,
        "interaction_families": sorted(families),
        "world_specific_affordance_count": len(world_specific),
        "shared_human_ai_fraction": round(len(shared) / count, 4) if count else 0.0,
        "persistent_effect_fraction": round(len(consequential) / count, 4) if count else 0.0,
        "target_types": sorted(target_types),
        "checks": checks,
        "passed": all(checks.values()),
        "affordances": catalog,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    result = audit(config)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
