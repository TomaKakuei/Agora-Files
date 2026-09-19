#!/usr/bin/env python3
"""Build a provisional five-layer ranking across Gemini and GPT models."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agora_comprehensive_hidden_benchmark import (  # noqa: E402
    BENCHMARK_ROOT,
    HEADLINE_WEIGHTS,
    MODEL_DIRS,
    RUN_ROOT,
    _expert_layer,
    _generation_layer,
    _visual_layer,
    _weighted_geometric,
)
from scripts.agora_cross_provider_objective_benchmark import (  # noqa: E402
    _apply_failed_retry_audit,
    _ranking_by_model,
    _read,
)


def _direct_expert_layer(model: str, review: dict[str, Any]) -> dict[str, Any]:
    weights = review.get("axis_weights", {})
    cases = review.get("models", {}).get(model, {}).get("cases", {})
    axis_means = {
        axis: sum(float(case.get("scores", {}).get(axis, 0.0)) for case in cases.values())
        / max(1, len(cases))
        for axis in weights
    }
    score = sum(float(weights[axis]) * axis_means[axis] for axis in weights)
    return {
        "score": round(score, 2),
        "review_status": str(review.get("status", "")),
        "axis_means": {axis: round(value, 2) for axis, value in axis_means.items()},
        "cases": cases,
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Cross-provider provisional comprehensive ranking",
        "",
        "| Rank | Model | Composite | Worlds | Generation | Community | Visual | Runtime | Expert | Evidence |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in payload["ranking"]:
        generation = row["generated_world"]
        scores = row["layer_scores"]
        lines.append(
            "| {rank} | {model} | {headline:.2f} | {done}/{total} | {generated_world:.2f} | "
            "{community_policy:.2f} | {visual_realization:.2f} | {generated_world_runtime:.2f} | "
            "{expert_world_quality:.2f} | {evidence} |".format(
                rank=row["rank"],
                model=row["model"],
                headline=row["headline_score"],
                done=generation["completed_cases"],
                total=generation["total_cases"],
                evidence=row["expert_evidence"],
                **scores,
            )
        )
    lines.extend(
        [
            "",
            "The layer weights are 35% generated world, 20% community policy, 15% visual",
            "realization, 15% generated-world runtime, and 15% expert world quality.",
            "Gemini expert evidence is the existing single-blind review; GPT expert evidence",
            "is a model-visible post-hoc review under the same rubric. The table is therefore",
            "provisional and should not be presented as a fully blind cross-provider result.",
            "",
        ]
    )
    return "\n".join(lines)


def build(benchmark_root: Path) -> dict[str, Any]:
    prompts = [
        item
        for item in _read(benchmark_root / "prompt_suite_hidden_v2.json").get("prompts", [])
        if isinstance(item, dict)
    ]
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
    blind_review = _read(benchmark_root / "blind_review" / "review_form.json")
    label_map = _read(benchmark_root / "blind_review" / "blind_label_map.json")
    model_to_label = {model: label for label, model in label_map.items()}
    gpt_review = _read(benchmark_root / "gpt_expert_review.json")
    retry_audit = _read(benchmark_root / "failed_generation_retry_audit.json")

    rows: list[dict[str, Any]] = []
    for model, model_dir in MODEL_DIRS.items():
        generation = _generation_layer(model, prompts)
        _apply_failed_retry_audit(model, generation, retry_audit)
        if model in model_to_label:
            expert = _expert_layer(model_to_label[model], blind_review)
            expert_evidence = "single_blind"
        else:
            expert = _direct_expert_layer(model, gpt_review)
            expert_evidence = "posthoc_model_visible"
        first_case = generation["cases"][0]
        builder_path = (
            RUN_ROOT
            / model_dir
            / prompts[0]["prompt_id"]
            / f"{prompts[0]['prompt_id']}_r01_decomposed_builder_spec.json"
        )
        builder = _read(builder_path) if first_case.get("status") == "compiled" else {}
        direct_visual = float(
            expert.get("cases", {})
            .get(prompts[0]["prompt_id"], {})
            .get("scores", {})
            .get("experienced_visual_coherence", 0.0)
            or 0.0
        )
        visual = _visual_layer(model, direct_visual, builder)
        community_row = community.get(model, {})
        runtime_row = runtime.get(model, {})
        runtime_score = float(
            runtime_row.get("score", {}).get("score", 0.0)
            if isinstance(runtime_row.get("score"), dict)
            else 0.0
        )
        layer_scores = {
            "generated_world": float(generation.get("score", 0.0) or 0.0),
            "community_policy": float(community_row.get("community_score", 0.0) or 0.0),
            "visual_realization": float(visual.get("score", 0.0) or 0.0),
            "generated_world_runtime": runtime_score,
            "expert_world_quality": float(expert.get("score", 0.0) or 0.0),
        }
        raw_headline = (
            _weighted_geometric(layer_scores, HEADLINE_WEIGHTS)
            if all(value > 0.0 for value in layer_scores.values())
            else 0.0
        )
        interaction = interaction_by_model.get(model, {})
        cap_reasons: list[str] = []
        if generation["completed_cases"] < 2:
            cap_reasons.append("fewer_than_two_of_three_worlds_compiled")
        if not visual.get("hard_gate_pass", False):
            cap_reasons.append("representative_visual_hard_gate_failed")
        if interaction.get("status") == "ready" and float(
            interaction.get("interaction_score", 0.0) or 0.0
        ) < 100.0:
            cap_reasons.append("interaction_contract_safety_probe_failed")
        headline = min(raw_headline, 59.0) if cap_reasons else raw_headline
        rows.append(
            {
                "model": model,
                "headline_score": round(headline, 2),
                "raw_headline_score": round(raw_headline, 2),
                "expert_evidence": expert_evidence,
                "score_cap_reasons": cap_reasons,
                "layer_scores": {key: round(value, 2) for key, value in layer_scores.items()},
                "generated_world": generation,
                "community_policy": community_row,
                "visual_realization": visual,
                "generated_world_runtime": runtime_row,
                "expert_world_quality": expert,
                "interaction_contract_probe": interaction,
            }
        )
    ranking = sorted(rows, key=lambda row: row["headline_score"], reverse=True)
    for rank, row in enumerate(ranking, start=1):
        row["rank"] = rank
    return {
        "benchmark": "Agora cross-provider provisional comprehensive evaluation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headline_weights": HEADLINE_WEIGHTS,
        "retry_policy": "retry_policy_v1.json",
        "fully_blind_cross_provider_review": False,
        "ranking": ranking,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path, default=BENCHMARK_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=BENCHMARK_ROOT / "cross_provider_comprehensive_results.json",
    )
    args = parser.parse_args()
    payload = build(args.benchmark_root.resolve())
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output.with_suffix(".md").write_text(_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "ranking": [
                    {"model": row["model"], "score": row["headline_score"]}
                    for row in payload["ranking"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
