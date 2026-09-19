#!/usr/bin/env python3
"""Combine compliance, strict objective evidence, stress tests, and expert review."""

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
DEFAULT_REVIEW = EVIDENCE_ROOT / "strict_expert_review_v1.json"
DEFAULT_RUNTIME_GEMINI = EVIDENCE_ROOT / "generated_world_runtime_results.json"
DEFAULT_RUNTIME_GPT = EVIDENCE_ROOT / "generated_world_runtime_results_gpt.json"
DEFAULT_COMMUNITY_GEMINI = EVIDENCE_ROOT / "community_results.json"
DEFAULT_COMMUNITY_GPT = EVIDENCE_ROOT / "community_results_gpt.json"
DEFAULT_OUTPUT = EVIDENCE_ROOT / "strict_generation_runtime_results_v1_1.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def weighted_score(scores: dict[str, float], weights: dict[str, float]) -> float:
    total = sum(weights.values())
    return round(sum(scores[name] * weight for name, weight in weights.items()) / total, 2)


def weighted_geometric(values: dict[str, float], weights: dict[str, float]) -> float:
    total = sum(weights.values())
    if total <= 0 or any(values[name] <= 0 for name in weights):
        return 0.0
    return round(
        100
        * math.exp(
            sum(
                (weights[name] / total) * math.log(values[name] / 100.0)
                for name in weights
            )
        ),
        2,
    )


def index_rows(payload: dict[str, Any], key: str = "ranking") -> dict[str, dict[str, Any]]:
    return {str(row["model"]): row for row in payload.get(key) or []}


def runtime_compliance_index(*payloads: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        for row in payload.get("ranking") or []:
            rows[str(row["model"])] = row
    return rows


def community_index(*payloads: dict[str, Any]) -> dict[str, float]:
    rows: dict[str, float] = {}
    for payload in payloads:
        for row in payload.get("ranking") or []:
            rows[str(row["model"])] = float(row.get("community_score") or 0.0)
    return rows


def generation_results(
    generation: dict[str, Any], review: dict[str, Any]
) -> list[dict[str, Any]]:
    review_block = review["generation"]
    review_weights = review_block["axis_weights"]
    output: list[dict[str, Any]] = []
    for row in generation.get("ranking") or []:
        model = str(row["model"])
        review_row = review_block["models"][model]
        judge_axes = {name: float(value) for name, value in review_row["scores"].items()}
        judge_score = weighted_score(judge_axes, review_weights)
        components = {
            "contract_compliance": float(row["contract_score_v1"]),
            "strict_objective_quality": float(row["strict_generation_objective"]),
            "anchored_expert_quality": judge_score,
        }
        component_weights = {
            "contract_compliance": 0.20,
            "strict_objective_quality": 0.35,
            "anchored_expert_quality": 0.45,
        }
        raw_score = weighted_geometric(components, component_weights)
        cap = 100.0
        cap_reasons: list[str] = []
        if int(row.get("compiled_worlds") or 0) < 3:
            cap = min(cap, 49.0)
            cap_reasons.append("fewer than three of three hidden worlds compiled")
        if int(row.get("first_pass_worlds") or 0) == 0 and int(row.get("compiled_worlds") or 0) > 0:
            cap = min(cap, 84.0)
            cap_reasons.append("zero first-pass world completions")
        if min(judge_axes.values()) < 75 or min(components.values()) < 85:
            cap = min(cap, 89.0)
            cap_reasons.append("90+ excellence gate not met")
        output.append(
            {
                "model": model,
                "strict_generation_score": round(min(raw_score, cap), 2),
                "raw_score": raw_score,
                "score_cap": cap,
                "cap_reasons": cap_reasons,
                "components": components,
                "compiled_worlds": row.get("compiled_worlds", 0),
                "first_pass_worlds": row.get("first_pass_worlds", 0),
                "objective_axes": row["axes"],
                "expert_axes": judge_axes,
                "expert_rationale": review_row["rationale"],
            }
        )
    return sorted(output, key=lambda item: item["strict_generation_score"], reverse=True)


def runtime_results(
    runtime_evidence: dict[str, Any],
    review: dict[str, Any],
    compliance_rows: dict[str, dict[str, Any]],
    community_rows: dict[str, float],
) -> list[dict[str, Any]]:
    review_block = review["runtime"]
    review_weights = review_block["axis_weights"]
    trace_rows = index_rows(runtime_evidence)
    models = list(review_block["models"].keys())
    output: list[dict[str, Any]] = []
    for model in models:
        review_row = review_block["models"][model]
        judge_axes = {name: float(value) for name, value in review_row["scores"].items()}
        judge_score = weighted_score(judge_axes, review_weights)
        if model not in compliance_rows or model not in trace_rows:
            output.append(
                {
                    "model": model,
                    "strict_runtime_score": None,
                    "eligibility": "N/E",
                    "reason": "no compiled first-premise world for generated-world runtime",
                    "community_stress_score": community_rows.get(model),
                    "expert_axes": judge_axes,
                    "expert_rationale": review_row["rationale"],
                }
            )
            continue
        compliance = compliance_rows[model]
        trace = trace_rows[model]
        components = {
            "execution_compliance": float(compliance["score"]["score"]),
            "strict_trace_quality": float(trace["strict_trace_objective"]),
            "cross_world_stress": float(community_rows.get(model, 0.0)),
            "anchored_expert_quality": judge_score,
        }
        component_weights = {
            "execution_compliance": 0.15,
            "strict_trace_quality": 0.25,
            "cross_world_stress": 0.20,
            "anchored_expert_quality": 0.40,
        }
        raw_score = weighted_geometric(components, component_weights)
        cap = 100.0
        cap_reasons: list[str] = []
        old_human_axis = float(compliance["score"].get("axes", {}).get("human_integration") or 0.0)
        if old_human_axis <= 0:
            cap = min(cap, 49.0)
            cap_reasons.append("no substantive human uptake in any eligible replicate")
        if all(
            "all approved open proposals are speech-only" in reasons
            for reasons in trace.get("cap_reasons_by_replicate") or []
        ):
            cap = min(cap, 79.0)
            cap_reasons.append("all approved open proposals are speech-only")
        if min(judge_axes.values()) < 75 or min(components.values()) < 85:
            cap = min(cap, 89.0)
            cap_reasons.append("90+ excellence gate not met")
        output.append(
            {
                "model": model,
                "strict_runtime_score": round(min(raw_score, cap), 2),
                "eligibility": "eligible",
                "raw_score": raw_score,
                "score_cap": cap,
                "cap_reasons": cap_reasons,
                "components": components,
                "compliance_stddev": compliance["score"].get("score_stddev"),
                "trace_stddev": trace.get("score_stddev"),
                "trace_axes": trace["axes"],
                "trace_raw_means": trace["raw_means"],
                "expert_axes": judge_axes,
                "expert_rationale": review_row["rationale"],
            }
        )
    return sorted(
        output,
        key=lambda item: (
            item["strict_runtime_score"] is not None,
            item["strict_runtime_score"] or -1,
        ),
        reverse=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generation", type=Path, default=DEFAULT_GENERATION)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--runtime-gemini", type=Path, default=DEFAULT_RUNTIME_GEMINI)
    parser.add_argument("--runtime-gpt", type=Path, default=DEFAULT_RUNTIME_GPT)
    parser.add_argument("--community-gemini", type=Path, default=DEFAULT_COMMUNITY_GEMINI)
    parser.add_argument("--community-gpt", type=Path, default=DEFAULT_COMMUNITY_GPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    generation = load_json(args.generation)
    runtime_evidence = load_json(args.runtime)
    review = load_json(args.review)
    compliance = runtime_compliance_index(
        load_json(args.runtime_gemini), load_json(args.runtime_gpt)
    )
    community = community_index(
        load_json(args.community_gemini), load_json(args.community_gpt)
    )
    payload = {
        "benchmark": "Agora Generation and Runtime Strict Scoring",
        "version": "agora-gr-strict-v1.1",
        "date": "2026-08-26",
        "score_scale": review["calibration"],
        "principle": (
            "Compliance is necessary but cannot compensate for shallow causal, social, "
            "human, or open-action quality. Generation and runtime remain separate."
        ),
        "generation": generation_results(generation, review),
        "runtime": runtime_results(runtime_evidence, review, compliance, community),
        "review_status": review["status"],
        "review_method_note": review["method_note"],
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
