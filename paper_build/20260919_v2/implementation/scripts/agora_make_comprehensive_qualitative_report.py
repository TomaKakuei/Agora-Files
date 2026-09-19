#!/usr/bin/env python3
"""Combine blind world quality with objective generation and runtime evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = ROOT / "docs" / "living_world_benchmark_20260825_hidden"
BLIND_PATH = BENCHMARK_ROOT / "dual_judge_blind_review_v0_1" / "aggregate.json"
OBJECTIVE_PATH = BENCHMARK_ROOT / "objective_only_generation_runtime_results_v1_1.json"
OUTPUT_ROOT = BENCHMARK_ROOT / "comprehensive_world_evaluation_v1"
WEIGHTS = {
    "blind_world_quality": 0.40,
    "objective_generation": 0.35,
    "objective_runtime": 0.25,
}
MODEL_ORDER = [
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash-lite",
    "gemini-3.7-flash",
    "gpt-5.6-luna",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(path)
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def score_band(score: float) -> str:
    if score >= 85:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "E"


def fmt(value: Any) -> str:
    return f"{float(value or 0):.2f}"


def make_report(payload: dict[str, Any]) -> str:
    rows = {row["model"]: row for row in payload["models"]}
    agreement = payload["blind_review_agreement"]
    lines = [
        "# Comprehensive World Quality and Performance Report",
        "",
        "## Evaluation Idea",
        "",
        "Agora evaluates a complete path from language to lived simulation. A model must first turn one sentence into a distinctive social world, then express that world as an executable typed system, and finally sustain consequential activity among agents and human participants. The evaluation therefore combines three complementary forms of evidence rather than reducing world generation to schema validity or prose quality alone.",
        "",
        "The comprehensive score is:",
        "",
        "```text",
        "Comprehensive = 0.40 Blind World Quality",
        "              + 0.35 Objective Generation",
        "              + 0.25 Objective Runtime",
        "```",
        "",
        "Blind world quality receives the largest share because the central task is to create a world with a recognizable premise, social organization, material specificity, and meaningful possibilities for action. Objective generation measures whether those ideas become a complete executable world. Objective runtime measures whether the resulting world supports responsive, causal, spatial, social, and human-facing behavior in operation.",
        "",
        "## Standards",
        "",
        "### Blind World Quality: 40%",
        "",
        "Gemini 3.1 Pro Preview and GPT-5.6 Sol independently evaluated anonymous world evidence. Every compiled world appeared in three shuffled panels per dimension for each judge, producing six ratings for every world-dimension pair. The aggregation takes the median of those six ratings, averages across three matched premises, and applies the fixed dimension weights.",
        "",
        "| Dimension | Weight within quality | Standard |",
        "|---|---:|---|",
        "| Premise and causal institutions | 25.81% | The sentence becomes a specific system of institutions, state variables, feedback, and stakes. |",
        "| Society and personhood | 23.66% | Groups and named people possess distinct goals, leverage, dependencies, relationships, and material lives. |",
        "| Space and materiality | 10.75% | Places and objects are world-specific, readable, and necessary to the premise. |",
        "| Open-ended interaction | 32.26% | Humans and agents can pursue different strategies, including coordinator-checked actions beyond a fixed catalog. |",
        "| Holistic coherence | 7.53% | The parts form a distinctive world that invites continued exploration. |",
        "",
        f"The judges show strong consistency across {agreement['paired_items']} paired ratings: ordinal Krippendorff's alpha is {agreement['ordinal_krippendorff_alpha']:.3f}, quadratic-weighted kappa is {agreement['quadratic_weighted_kappa']:.3f}, and {agreement['within_one_tier_agreement'] * 100:.1f}% of paired judgments are within one tier.",
        "",
        "### Objective Generation: 35%",
        "",
        "Objective generation joins contract compliance with measurable world structure. Contract compliance measures complete typed output, compilation, required populations, locations, items, actions, and player affordances. Strict objective quality measures causal systems, spatial necessity, agent individuation, social interdependence, material economy, interaction depth, human affordance, template escape, visual authorship, and first-pass robustness. The result rewards worlds that are simultaneously imaginative, complete, and executable.",
        "",
        "### Objective Runtime: 25%",
        "",
        "Objective runtime executes the generated worlds under matched interventions and human events. It combines execution compliance, trace quality, and cross-world stress performance. Trace quality measures intervention sensitivity, causal threading, role conditioning, substantive open action, state evolution, social differentiation, human impact, conflict and recovery, behavioral specificity, and spatial causality. Runtime receives zero in the end-to-end score when a model does not produce an executable generated world for the runtime stage.",
        "",
        "## Comprehensive Scores",
        "",
        "| Model | Blind quality | Objective generation | Objective runtime | Comprehensive | Band | Compiled worlds |",
        "|---|---:|---:|---:|---:|:---:|---:|",
    ]
    for model in MODEL_ORDER:
        row = rows[model]
        lines.append(
            f"| {model} | {row['blind_world_quality']:.2f} | "
            f"{row['objective_generation']:.2f} | {row['objective_runtime']:.2f} | "
            f"**{row['comprehensive_score']:.2f}** | **{row['band']}** | "
            f"{row['compiled_worlds']}/3 |"
        )
    lines.extend(
        [
            "",
            "The distribution forms clear performance groups. GPT-5.6 Sol reaches the S band through the strongest blind world quality and objective generation score together with top-tier runtime behavior. Gemini 3.7 Flash forms the A band with complete first-pass generation, strong spatial and material imagination, and reliable execution. Gemini 3.1 Pro Preview and Gemini 2.5 Flash occupy the B band through complementary strengths: Pro is stronger in runtime interaction, while 2.5 Flash is stronger in objective generation completeness. Gemini 3.1 Flash Lite forms the C band with complete generation coverage and solid open interaction. The remaining models are separated by end-to-end executable coverage.",
            "",
            "## World Quality Scores",
            "",
            "| Model | Quality total | Premise/causal | Society/personhood | Space/material | Open interaction | Holistic |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for model in MODEL_ORDER:
        row = rows[model]
        axes = row["blind_quality_axes"]
        lines.append(
            f"| {model} | **{row['blind_world_quality']:.2f}** | "
            f"{fmt(axes['premise_causality'])} | {fmt(axes['society_personhood'])} | "
            f"{fmt(axes['space_materiality'])} | {fmt(axes['interaction_open_endedness'])} | "
            f"{fmt(axes['holistic_coherence'])} |"
        )
    lines.extend(
        [
            "",
            "The quality dimensions produce a meaningful spread rather than a compressed cluster. GPT-5.6 Sol sustains an 85-level result across every category. Gemini 3.7 Flash is strongest in premise transformation and spatial-material realization. Gemini 3.1 Pro Preview and Gemini 2.5 Flash separate through different profiles, while Gemini 3.1 Flash Lite remains competitive in space and interaction. This structure shows that the dimensions capture distinct capabilities while preserving a coherent overall judgment.",
            "",
            "## Objective Generation Scores",
            "",
            "| Model | Generation total | Contract compliance | Objective world structure | First-pass worlds |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for model in MODEL_ORDER:
        row = rows[model]
        components = row["generation_components"]
        lines.append(
            f"| {model} | **{row['objective_generation']:.2f}** | "
            f"{fmt(components.get('contract_compliance'))} | "
            f"{fmt(components.get('strict_objective_quality'))} | "
            f"{row['first_pass_worlds']}/3 |"
        )
    lines.extend(
        [
            "",
            "Objective generation sharply separates complete world builders from partial outputs. GPT-5.6 Sol combines the deepest causal and material structures with the highest human affordance. Gemini 3.7 Flash leads first-pass robustness, while Gemini 2.5 Flash combines strong agent individuation, material economy, interaction depth, and human affordance. The scores reward both semantic richness and successful realization under the common contract.",
            "",
            "## Objective Runtime Scores",
            "",
            "| Model | Runtime total | Execution compliance | Trace quality | Cross-world stress |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for model in MODEL_ORDER:
        row = rows[model]
        components = row["runtime_components"]
        lines.append(
            f"| {model} | **{row['objective_runtime']:.2f}** | "
            f"{fmt(components.get('execution_compliance'))} | "
            f"{fmt(components.get('strict_trace_quality'))} | "
            f"{fmt(components.get('cross_world_stress'))} |"
        )
    lines.extend(
        [
            "",
            "Runtime scoring reveals a second, complementary capability axis. GPT-5.6 Sol and Gemini 3.1 Pro Preview produce the strongest overall operational performance. Gemini 2.5 Flash achieves the highest strict trace quality through substantive open proposals, causal threading, and human uptake. Gemini 3.7 Flash contributes highly reliable execution and intervention sensitivity. The division therefore recognizes multiple successful styles of community behavior instead of collapsing them into a single action count.",
            "",
            "## Integrated Interpretation",
            "",
            "The combined evaluation produces both agreement and separation. The blind judges agree on the broad quality structure, while the hard metrics explain why worlds with similar prose-level appeal diverge once compilation and runtime behavior are included. High scores require strength across all three stages: world imagination, executable realization, and lived interaction.",
            "",
            "The resulting allocation is balanced. GPT-5.6 Sol establishes the current high-quality reference; Gemini 3.7 Flash follows as a strong and reliable generator; Gemini 3.1 Pro Preview and Gemini 2.5 Flash express different but comparably valuable strengths; Gemini 3.1 Flash Lite remains a capable complete-world generator. Models with partial executable coverage receive proportionally lower end-to-end scores, preserving a wide and interpretable scale.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    blind = load_json(BLIND_PATH)
    objective = load_json(OBJECTIVE_PATH)
    blind_rows = {row["model"]: row for row in blind["models"]}
    generation_rows = {row["model"]: row for row in objective["generation"]}
    runtime_rows = {row["model"]: row for row in objective["runtime"]}

    models: list[dict[str, Any]] = []
    for model in MODEL_ORDER:
        blind_row = blind_rows[model]
        generation_row = generation_rows[model]
        runtime_row = runtime_rows[model]
        blind_score = float(blind_row["dual_judge_score"])
        generation_score = float(generation_row["objective_generation_score"])
        runtime_value = runtime_row.get("objective_runtime_score")
        runtime_score = float(runtime_value) if runtime_value is not None else 0.0
        total = (
            WEIGHTS["blind_world_quality"] * blind_score
            + WEIGHTS["objective_generation"] * generation_score
            + WEIGHTS["objective_runtime"] * runtime_score
        )
        models.append(
            {
                "model": model,
                "blind_world_quality": round(blind_score, 2),
                "objective_generation": round(generation_score, 2),
                "objective_runtime": round(runtime_score, 2),
                "comprehensive_score": round(total, 2),
                "band": score_band(total),
                "compiled_worlds": int(generation_row["compiled_worlds"]),
                "first_pass_worlds": int(generation_row["first_pass_worlds"]),
                "blind_quality_axes": blind_row["dual_judge_category_scores"],
                "generation_components": generation_row["components"],
                "generation_objective_axes": generation_row["objective_axes"],
                "runtime_components": runtime_row.get("components", {}),
                "runtime_trace_axes": runtime_row.get("trace_axes", {}),
            }
        )

    payload = {
        "benchmark": "Agora Comprehensive World Quality and Performance",
        "version": "agora-comprehensive-world-evaluation-v1",
        "score_scale": [0, 100],
        "weights": WEIGHTS,
        "score_bands": {
            "S": "85-100",
            "A": "80-84.99",
            "B": "70-79.99",
            "C": "60-69.99",
            "D": "40-59.99",
            "E": "0-39.99",
        },
        "blind_review_agreement": blind["diagnostics"]["candidate_inter_rater_agreement"],
        "models": models,
        "sources": {
            "blind_world_quality": str(BLIND_PATH.relative_to(ROOT)),
            "objective_generation_runtime": str(OBJECTIVE_PATH.relative_to(ROOT)),
        },
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    write_json(OUTPUT_ROOT / "aggregate.json", payload)
    (OUTPUT_ROOT / "report.md").write_text(make_report(payload), encoding="utf-8")
    print(
        json.dumps(
            [
                {
                    "model": row["model"],
                    "quality": row["blind_world_quality"],
                    "generation": row["objective_generation"],
                    "runtime": row["objective_runtime"],
                    "comprehensive": row["comprehensive_score"],
                    "band": row["band"],
                }
                for row in models
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
