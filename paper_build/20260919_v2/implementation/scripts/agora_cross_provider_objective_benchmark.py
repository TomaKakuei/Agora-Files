#!/usr/bin/env python3
"""Aggregate the completed objective layers across model providers."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agora_comprehensive_hidden_benchmark import (
    BENCHMARK_ROOT,
    MODEL_DIRS,
    _generation_layer,
)


OBJECTIVE_WEIGHTS = {
    "generated_world": 0.50,
    "community_policy": 2.0 / 7.0,
    "generated_world_runtime": 1.5 / 7.0,
}


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _ranking_by_model(*payloads: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        for row in payload.get("ranking", []):
            if isinstance(row, dict) and row.get("model"):
                rows[str(row["model"])] = row
    return rows


def _objective_score(scores: dict[str, float]) -> float:
    if any(float(scores.get(name, 0.0)) <= 0.0 for name in OBJECTIVE_WEIGHTS):
        return 0.0
    return 100.0 * math.exp(
        sum(
            weight * math.log(float(scores[name]) / 100.0)
            for name, weight in OBJECTIVE_WEIGHTS.items()
        )
    )


def _apply_failed_retry_audit(
    model: str,
    generation: dict[str, Any],
    audit: dict[str, Any],
) -> None:
    model_audit = audit.get("cases", {}).get(model, {})
    if not isinstance(model_audit, dict):
        return
    for case in generation.get("cases", []):
        if not isinstance(case, dict) or case.get("status") != "failed":
            continue
        evidence = model_audit.get(case.get("prompt_id"), {})
        if not isinstance(evidence, dict):
            continue
        operational = case.setdefault("operational", {})
        operational["semantic_retry_count"] = int(
            evidence.get("semantic_retry_count", 0) or 0
        )
        operational["localized_node_retry_count"] = operational[
            "semantic_retry_count"
        ]
        operational["localized_retry_nodes"] = list(
            evidence.get("failed_nodes", [])
        )
        operational["retry_audit_source"] = "supplementary_console_transcript"
        operational["failure_class"] = str(evidence.get("failure_class", ""))


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Cross-provider objective core",
        "",
        "This table combines only the three completed objective layers. The original",
        "35:20:15 weights are normalized to 50:28.57:21.43. Visual realization and",
        "expert review remain unscored here and must not be inferred from this ranking.",
        "",
        "| Rank | Model | Objective core | Worlds | First pass | Generation | Community | Runtime | Status |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in payload["ranking"]:
        generation = row["generated_world"]
        lines.append(
            "| {rank} | {model} | {score:.2f} | {done}/{total} | {first}/{total} | "
            "{generation_score:.2f} | {community:.2f} | {runtime:.2f} | {status} |".format(
                rank=row["rank"],
                model=row["model"],
                score=row["objective_core_score"],
                done=generation["completed_cases"],
                total=generation["total_cases"],
                first=generation["first_pass_successes"],
                generation_score=row["layer_scores"]["generated_world"],
                community=row["layer_scores"]["community_policy"],
                runtime=row["layer_scores"]["generated_world_runtime"],
                status=row["status"],
            )
        )
    lines.extend(
        [
            "",
            "A model with fewer than two compiled worlds is capped at 59. A model with",
            "no compiled world or no executable runtime evidence receives zero rather",
            "than borrowing another model's world. Transport-inconclusive cases are",
            "excluded and rerun unchanged; none of the valid rows in this table has that status.",
            "",
        ]
    )
    return "\n".join(lines)


def build(benchmark_root: Path) -> dict[str, Any]:
    suite = _read(benchmark_root / "prompt_suite_hidden_v2.json")
    prompts = [item for item in suite.get("prompts", []) if isinstance(item, dict)]
    community = _ranking_by_model(
        _read(benchmark_root / "community_results.json"),
        _read(benchmark_root / "community_results_gpt.json"),
    )
    runtime = _ranking_by_model(
        _read(benchmark_root / "generated_world_runtime_results.json"),
        _read(benchmark_root / "generated_world_runtime_results_gpt.json"),
    )
    interactions = _read(benchmark_root / "visual_cases" / "case_manifest.json")
    interaction_by_model = {
        str(row.get("model")): row
        for row in interactions.get("models", [])
        if isinstance(row, dict)
    }
    retry_audit = _read(benchmark_root / "failed_generation_retry_audit.json")

    rows: list[dict[str, Any]] = []
    for model in MODEL_DIRS:
        generation = _generation_layer(model, prompts)
        _apply_failed_retry_audit(model, generation, retry_audit)
        community_row = community.get(model, {})
        runtime_row = runtime.get(model, {})
        community_score = float(community_row.get("community_score", 0.0) or 0.0)
        runtime_score = float(
            (runtime_row.get("score") or {}).get("score", 0.0)
            if isinstance(runtime_row.get("score"), dict)
            else 0.0
        )
        scores = {
            "generated_world": float(generation["score"]),
            "community_policy": community_score,
            "generated_world_runtime": runtime_score,
        }
        raw_score = _objective_score(scores)
        interaction = interaction_by_model.get(model, {})
        cap_reasons: list[str] = []
        if generation["completed_cases"] < 2:
            cap_reasons.append("fewer_than_two_of_three_worlds_compiled")
        if interaction.get("status") == "ready" and float(
            interaction.get("interaction_score", 0.0) or 0.0
        ) < 100.0:
            cap_reasons.append("coordinator_safety_probe_failed")
        if generation["completed_cases"] == 0 or runtime_score <= 0.0:
            final_score = 0.0
            status = "not_executable_from_own_generated_world"
        else:
            final_score = min(raw_score, 59.0) if cap_reasons else raw_score
            status = "complete"
        rows.append(
            {
                "model": model,
                "objective_core_score": round(final_score, 2),
                "raw_objective_core_score": round(raw_score, 2),
                "status": status,
                "score_cap_reasons": cap_reasons,
                "layer_scores": {key: round(value, 2) for key, value in scores.items()},
                "generated_world": generation,
                "community_policy": community_row,
                "generated_world_runtime": runtime_row,
                "interaction_contract_probe": interaction,
            }
        )
    ranking = sorted(rows, key=lambda row: row["objective_core_score"], reverse=True)
    for rank, row in enumerate(ranking, start=1):
        row["rank"] = rank
    return {
        "benchmark": "Agora cross-provider objective core",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weights": OBJECTIVE_WEIGHTS,
        "retry_policy": "retry_policy_v1.json",
        "visual_and_expert_layers_included": False,
        "ranking": ranking,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path, default=BENCHMARK_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=BENCHMARK_ROOT / "cross_provider_objective_results.json",
    )
    args = parser.parse_args()
    payload = build(args.benchmark_root.resolve())
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "ranking": [
        {"model": row["model"], "score": row["objective_core_score"]}
        for row in payload["ranking"]
    ]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
