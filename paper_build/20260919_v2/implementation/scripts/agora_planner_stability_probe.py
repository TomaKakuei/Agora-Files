#!/usr/bin/env python3
"""Run repeated open-world planner calls and retain completeness telemetry."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora_ui.world_builder.generation import _world_creator_provider  # noqa: E402
from agora_ui.world_builder.nodes.planner import generate_planner_spec  # noqa: E402


def _valid(spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    seed = spec.get("world_seed", {}) if isinstance(spec.get("world_seed"), dict) else {}
    dynamics = spec.get("world_dynamics", {}) if isinstance(spec.get("world_dynamics"), dict) else {}
    states = {
        str(item.get("state_id", "")).strip()
        for item in dynamics.get("state_variables", [])
        if isinstance(item, dict) and str(item.get("state_id", "")).strip()
    }
    links = [item for item in dynamics.get("causal_links", []) if isinstance(item, dict)]
    exact = sum(
        str(item.get("source_state", "")).strip() in states
        and str(item.get("target_state", "")).strip() in states
        for item in links
    )
    forbidden = sorted({"preset_id", "profile_id", "kit_refs", "policy_refs"} & set(seed))
    observations = {
        "seed_version": seed.get("seed_version"),
        "forbidden_seed_keys": forbidden,
        "institution_count": len(dynamics.get("institutions", [])),
        "state_count": len(states),
        "causal_link_count": len(links),
        "exact_causal_link_count": exact,
        "stakeholder_count": len(dynamics.get("stakeholder_groups", [])),
    }
    return bool(
        seed.get("seed_version") == "world_seed_v3_open"
        and not forbidden
        and observations["institution_count"] >= 3
        and observations["state_count"] >= 4
        and observations["causal_link_count"] >= 4
        and exact == len(links)
        and observations["stakeholder_count"] >= 3
    ), observations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sentence", required=True)
    parser.add_argument("--model", default="gemini-3.7-flash")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    os.environ.update(
        {
            "AGORA_WORLD_CREATOR_MODEL": args.model,
            "AGORA_WORLD_CREATOR_LITE_MODEL": args.model,
            "AGORA_PLANNER_MAX_OUTPUT_TOKENS": "32768",
            "AGORA_EXPERIMENT_FORCE_TEMPERATURE": "0.2",
            "AGORA_EXPERIMENT_FORCE_THINKING_LEVEL": "low",
        }
    )
    rows = []
    for index in range(max(1, args.repeats)):
        telemetry_path = args.output.parent / f"planner_probe_{index + 1:02d}_calls.jsonl"
        os.environ["AGORA_VERTEX_TELEMETRY_PATH"] = str(telemetry_path.resolve())
        os.environ["AGORA_VERTEX_TELEMETRY_RUN_ID"] = f"planner_probe_{index + 1:02d}"
        provider = _world_creator_provider("pro")
        started = time.perf_counter()
        error = ""
        spec: dict[str, Any] = {}
        try:
            spec = generate_planner_spec(
                provider,
                {
                    "world_name": "",
                    "genre": "",
                    "focus": "",
                    "brief": args.sentence,
                    "player_count_target": 4,
                },
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        passed, observations = _valid(spec)
        spec_path = args.output.parent / f"planner_probe_{index + 1:02d}.json"
        if spec:
            spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rows.append(
            {
                "repeat": index + 1,
                "pass": passed and not error,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "provider_attempt_count": len(provider.call_history),
                "invalid_json_attempt_count": sum(row.get("status") == "invalid_json" for row in provider.call_history),
                "observations": observations,
                "error": error,
                "spec_path": str(spec_path) if spec else "",
                "telemetry_path": str(telemetry_path),
            }
        )
    payload = {
        "model": args.model,
        "sentence": args.sentence,
        "planner_max_output_tokens": 32768,
        "native_response_json_schema": True,
        "repeat_count": len(rows),
        "pass_count": sum(row["pass"] for row in rows),
        "all_pass": all(row["pass"] for row in rows),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_pass": payload["all_pass"], "pass_count": payload["pass_count"], "rows": rows}, ensure_ascii=False, indent=2))
    if not payload["all_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
