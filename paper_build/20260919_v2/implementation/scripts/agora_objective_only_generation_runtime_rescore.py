#!/usr/bin/env python3
"""Recompute generation and runtime scores without any expert-review input."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "docs" / "living_world_benchmark_20260825_hidden"
DEFAULT_GENERATION = EVIDENCE_ROOT / "strict_generation_evidence_v1.json"
DEFAULT_RUNTIME = EVIDENCE_ROOT / "strict_runtime_evidence_v1.json"
DEFAULT_RUNTIME_GEMINI = EVIDENCE_ROOT / "generated_world_runtime_results.json"
DEFAULT_RUNTIME_GPT = EVIDENCE_ROOT / "generated_world_runtime_results_gpt.json"
DEFAULT_COMMUNITY_GEMINI = EVIDENCE_ROOT / "community_results.json"
DEFAULT_COMMUNITY_GPT = EVIDENCE_ROOT / "community_results_gpt.json"
DEFAULT_OUTPUT = EVIDENCE_ROOT / "objective_only_generation_runtime_results_v1_1.json"

GENERATION_WEIGHTS = {
    "contract_compliance": 0.20 / 0.55,
    "strict_objective_quality": 0.35 / 0.55,
}
RUNTIME_WEIGHTS = {
    "execution_compliance": 0.15 / 0.60,
    "strict_trace_quality": 0.25 / 0.60,
    "cross_world_stress": 0.20 / 0.60,
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def weighted_geometric(values: dict[str, float], weights: dict[str, float]) -> float:
    if any(values[name] <= 0 for name in weights):
        return 0.0
    return round(
        100
        * math.exp(
            sum(
                weights[name] * math.log(values[name] / 100.0)
                for name in weights
            )
        ),
        2,
    )


def index_rows(payload: dict[str, Any], key: str = "ranking") -> dict[str, dict[str, Any]]:
    return {str(row["model"]): row for row in payload.get(key) or []}


def merge_rows(*payloads: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        rows.update(index_rows(payload))
    return rows


def community_index(*payloads: dict[str, Any]) -> dict[str, float]:
    rows: dict[str, float] = {}
    for payload in payloads:
        for row in payload.get("ranking") or []:
            rows[str(row["model"])] = float(row.get("community_score") or 0.0)
    return rows


def generation_results(generation: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in generation.get("ranking") or []:
        components = {
            "contract_compliance": float(row["contract_score_v1"]),
            "strict_objective_quality": float(row["strict_generation_objective"]),
        }
        raw_score = weighted_geometric(components, GENERATION_WEIGHTS)
        compiled_worlds = int(row.get("compiled_worlds") or 0)
        first_pass_worlds = int(row.get("first_pass_worlds") or 0)
        cap = 100.0
        cap_reasons: list[str] = []
        if compiled_worlds < 3:
            cap = min(cap, 49.0)
            cap_reasons.append("fewer than three of three hidden worlds compiled")
        if first_pass_worlds == 0 and compiled_worlds > 0:
            cap = min(cap, 84.0)
            cap_reasons.append("zero first-pass world completions")
        output.append(
            {
                "model": str(row["model"]),
                "objective_generation_score": round(min(raw_score, cap), 2),
                "raw_score": raw_score,
                "score_cap": cap,
                "cap_reasons": cap_reasons,
                "components": components,
                "compiled_worlds": compiled_worlds,
                "first_pass_worlds": first_pass_worlds,
                "objective_axes": row["axes"],
            }
        )
    return sorted(output, key=lambda item: item["objective_generation_score"], reverse=True)


def runtime_results(
    runtime_evidence: dict[str, Any],
    compliance_rows: dict[str, dict[str, Any]],
    community_rows: dict[str, float],
    model_order: list[str],
) -> list[dict[str, Any]]:
    trace_rows = index_rows(runtime_evidence)
    output: list[dict[str, Any]] = []
    for model in model_order:
        if model not in compliance_rows or model not in trace_rows:
            output.append(
                {
                    "model": model,
                    "objective_runtime_score": None,
                    "eligibility": "N/E",
                    "reason": "no compiled first-premise world for generated-world runtime",
                    "community_stress_score": community_rows.get(model),
                }
            )
            continue
        compliance = compliance_rows[model]
        trace = trace_rows[model]
        components = {
            "execution_compliance": float(compliance["score"]["score"]),
            "strict_trace_quality": float(trace["strict_trace_objective"]),
            "cross_world_stress": float(community_rows.get(model, 0.0)),
        }
        raw_score = weighted_geometric(components, RUNTIME_WEIGHTS)
        cap = 100.0
        cap_reasons: list[str] = []
        human_axis = float(compliance["score"].get("axes", {}).get("human_integration") or 0.0)
        if human_axis <= 0:
            cap = min(cap, 49.0)
            cap_reasons.append("no substantive human uptake in any eligible replicate")
        replicate_reasons = trace.get("cap_reasons_by_replicate") or []
        if replicate_reasons and all(
            "all approved open proposals are speech-only" in reasons
            for reasons in replicate_reasons
        ):
            cap = min(cap, 79.0)
            cap_reasons.append("all approved open proposals are speech-only")
        output.append(
            {
                "model": model,
                "objective_runtime_score": round(min(raw_score, cap), 2),
                "eligibility": "eligible",
                "raw_score": raw_score,
                "score_cap": cap,
                "cap_reasons": cap_reasons,
                "components": components,
                "compliance_stddev": compliance["score"].get("score_stddev"),
                "trace_stddev": trace.get("score_stddev"),
                "trace_axes": trace["axes"],
                "trace_raw_means": trace["raw_means"],
            }
        )
    return sorted(
        output,
        key=lambda item: (
            item["objective_runtime_score"] is not None,
            item["objective_runtime_score"] or -1,
        ),
        reverse=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generation", type=Path, default=DEFAULT_GENERATION)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--runtime-gemini", type=Path, default=DEFAULT_RUNTIME_GEMINI)
    parser.add_argument("--runtime-gpt", type=Path, default=DEFAULT_RUNTIME_GPT)
    parser.add_argument("--community-gemini", type=Path, default=DEFAULT_COMMUNITY_GEMINI)
    parser.add_argument("--community-gpt", type=Path, default=DEFAULT_COMMUNITY_GPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    generation = load_json(args.generation)
    runtime_evidence = load_json(args.runtime)
    compliance = merge_rows(load_json(args.runtime_gemini), load_json(args.runtime_gpt))
    community = community_index(
        load_json(args.community_gemini), load_json(args.community_gpt)
    )
    model_order = [str(row["model"]) for row in generation.get("ranking") or []]
    payload = {
        "benchmark": "Agora Generation and Runtime Objective-Only Scoring",
        "version": "agora-gr-objective-v1.1",
        "date": "2026-08-26",
        "reviewer_scores_used": False,
        "reviewer_score_weight": 0.0,
        "exclusion_reason": (
            "The reviewing assistant belongs to one evaluated model family; all "
            "expert and holistic ratings are excluded to remove that conflict."
        ),
        "method": {
            "aggregation": "weighted geometric mean",
            "generation_weights": GENERATION_WEIGHTS,
            "runtime_weights": RUNTIME_WEIGHTS,
            "weight_derivation": (
                "The non-review components retain their strict-v1.1 relative weights "
                "and are renormalized to sum to one."
            ),
            "gates": {
                "generation": [
                    "score <= 49 when fewer than three hidden worlds compile",
                    "score <= 84 when no compiled world succeeds on the first semantic pass",
                ],
                "runtime": [
                    "score <= 49 without substantive human uptake",
                    "score <= 79 when every approved proposal is speech-only in every replicate",
                ],
            },
        },
        "generation": generation_results(generation),
        "runtime": runtime_results(
            runtime_evidence, compliance, community, model_order
        ),
        "interpretation_limit": (
            "These scores compare reproducible structural and behavioral evidence. "
            "They do not independently establish aesthetic quality, believability, "
            "or whether a person would want to inhabit the world."
        ),
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
