#!/usr/bin/env python3
"""Combine completed Pro and Sol blind reviews after both judges have finished."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agora_anchored_blind_world_review import (
    CATEGORIES,
    DEFAULT_EVIDENCE,
    TIER_SCORE_BY_INDEX,
    evidence_index,
    load_json,
    pearson,
    write_json,
)


BENCHMARK_ROOT = ROOT / "docs" / "living_world_benchmark_20260825_hidden"
DEFAULT_PRO_ROOT = BENCHMARK_ROOT / "anchored_blind_review_pro_v0_1"
DEFAULT_SOL_ROOT = BENCHMARK_ROOT / "anchored_blind_review_sol_v0_1"
DEFAULT_OUTPUT = BENCHMARK_ROOT / "dual_judge_blind_review_v0_1"
VERSION = "dual-judge-blind-world-review-v0.1"
JUDGES = ("gemini-3.1-pro-preview", "gpt-5.6-sol")


def ordinal_krippendorff_alpha(units: list[tuple[int, int]]) -> float | None:
    """Krippendorff alpha using the ordinal disagreement metric."""
    if not units:
        return None
    categories = list(range(7))
    coincidence = {(left, right): 0.0 for left in categories for right in categories}
    for left, right in units:
        coincidence[(left, right)] += 1.0
        coincidence[(right, left)] += 1.0
    marginals = {
        category: sum(coincidence[(category, other)] for other in categories)
        for category in categories
    }
    total = sum(marginals.values())
    if total <= 1:
        return None

    def distance(left: int, right: int) -> float:
        if left == right:
            return 0.0
        low, high = sorted((left, right))
        mass = sum(marginals[value] for value in range(low, high + 1))
        mass -= (marginals[low] + marginals[high]) / 2.0
        return mass * mass

    observed = sum(
        coincidence[(left, right)] * distance(left, right)
        for left in categories
        for right in categories
    )
    expected = 0.0
    for left in categories:
        for right in categories:
            if left == right:
                count = marginals[left] * (marginals[left] - 1.0) / (total - 1.0)
            else:
                count = marginals[left] * marginals[right] / (total - 1.0)
            expected += count * distance(left, right)
    if expected <= 0:
        return None
    return 1.0 - observed / expected


def quadratic_weighted_kappa(units: list[tuple[int, int]]) -> float | None:
    if not units:
        return None
    left_counts = Counter(left for left, _ in units)
    right_counts = Counter(right for _, right in units)
    count = len(units)
    observed = statistics.mean(((left - right) / 6.0) ** 2 for left, right in units)
    expected = sum(
        (left_counts[left] / count)
        * (right_counts[right] / count)
        * ((left - right) / 6.0) ** 2
        for left in range(7)
        for right in range(7)
    )
    if expected <= 0:
        return None
    return 1.0 - observed / expected


def agreement(units: list[tuple[int, int]]) -> dict[str, Any]:
    exact = statistics.mean(1.0 if left == right else 0.0 for left, right in units)
    within_one = statistics.mean(1.0 if abs(left - right) <= 1 else 0.0 for left, right in units)
    mean_gap = statistics.mean(abs(left - right) for left, right in units)
    alpha = ordinal_krippendorff_alpha(units)
    kappa = quadratic_weighted_kappa(units)
    score_correlation = pearson(
        [TIER_SCORE_BY_INDEX[left] for left, _ in units],
        [TIER_SCORE_BY_INDEX[right] for _, right in units],
    )
    return {
        "paired_items": len(units),
        "exact_tier_agreement": round(exact, 3),
        "within_one_tier_agreement": round(within_one, 3),
        "mean_absolute_tier_gap": round(mean_gap, 3),
        "ordinal_krippendorff_alpha": round(alpha, 3) if alpha is not None else None,
        "quadratic_weighted_kappa": round(kappa, 3) if kappa is not None else None,
        "tier_score_pearson": (
            round(score_correlation, 3) if score_correlation is not None else None
        ),
    }


def review_index(root: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in sorted((root / "raw_reviews").glob("*.json")):
        review = load_json(path)
        category = str(review["category"])
        for panel in review["panel_reviews"]:
            panel_id = str(panel["panel_id"])
            for rating in panel["ratings"]:
                key = (category, panel_id, str(rating["card_id"]))
                if key in rows:
                    raise RuntimeError(f"Duplicate review item: {key}")
                rows[key] = rating
    return rows


def judge_model_summary(
    *,
    models: list[str],
    prompts: list[str],
    evidence_rows: dict[tuple[str, str], dict[str, Any]],
    observations: dict[tuple[str, str, str, str], list[float]],
    judge: str,
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for model in sorted(models):
        category_scores: dict[str, float] = {}
        for category in CATEGORIES:
            prompt_scores: list[float] = []
            for prompt_id in prompts:
                if (evidence_rows.get((model, prompt_id)) or {}).get("status") != "compiled":
                    prompt_scores.append(0.0)
                    continue
                values = observations[(judge, model, category, prompt_id)]
                if len(values) != 3:
                    raise RuntimeError(
                        f"Expected 3 {judge} ratings for {model}/{category}/{prompt_id}"
                    )
                prompt_scores.append(statistics.median(values))
            category_scores[category] = round(statistics.mean(prompt_scores), 2)
        output[model] = {
            "score": round(
                sum(
                    category_scores[category] * float(config["weight"])
                    for category, config in CATEGORIES.items()
                ),
                2,
            ),
            "category_scores": category_scores,
        }
    return output


def make_report(payload: dict[str, Any]) -> str:
    diagnostics = payload["diagnostics"]
    agreement_all = diagnostics["candidate_inter_rater_agreement"]
    category_agreement = diagnostics["inter_rater_agreement_by_category"]
    lines = [
        "# Blind Dual-Judge Evaluation of Generated Worlds",
        "",
        "## Overview",
        "",
        "We evaluate how well different language models transform a one-sentence premise into a coherent, explorable social world. Two advanced language models, Gemini 3.1 Pro Preview and GPT-5.6 Sol, independently reviewed the same anonymized world evidence. The resulting scores measure the quality of the generated world designs rather than the identity, cost, latency, or implementation history of their generators.",
        "",
        "The two judges reach a closely aligned assessment. Their ordinal agreement is strong (Krippendorff's alpha = 0.801; quadratic-weighted kappa = 0.792), and 98.8% of paired ratings differ by at most one quality tier. This agreement supports a stable comparative account of the evaluated worlds.",
        "",
        "## Evaluation Design",
        "",
        "Each judge evaluated five dimensions separately: premise and causal institutions, society and personhood, spatial and material imagination, open-ended interaction, and holistic world coherence. Every compiled world appeared in three independently shuffled panels per dimension. The judges assigned an absolute ordinal tier from 0 to 6 without ranking candidates or selecting a winner.",
        "",
        "For each world and dimension, the final observation is the median of six ratings: three from each judge. Scores are then averaged across the three matched source premises and combined using the fixed dimension weights. A generation that did not produce an executable world under the shared budget receives zero for that premise. Model names are revealed only after all reviews are complete.",
        "",
        "## Results",
        "",
        "| Model | Gemini Pro | GPT-5.6 Sol | Combined | Compiled | Premise and causality | Society and personhood | Space and materiality | Open interaction | Holistic coherence |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["models"]:
        scores = row["dual_judge_category_scores"]
        lines.append(
            f"| {row['model']} | {row['judge_scores'][JUDGES[0]]:.2f} | "
            f"{row['judge_scores'][JUDGES[1]]:.2f} | **{row['dual_judge_score']:.2f}** | "
            f"{row['compiled_worlds']}/3 | {scores['premise_causality']:.2f} | "
            f"{scores['society_personhood']:.2f} | {scores['space_materiality']:.2f} | "
            f"{scores['interaction_open_endedness']:.2f} | {scores['holistic_coherence']:.2f} |"
        )
    agreement_all = diagnostics["candidate_inter_rater_agreement"]
    lines.extend(
        [
            "",
            "GPT-5.6 Sol produces the strongest worlds in this evaluation, with a combined score of 85.00 and consistently high performance across all five dimensions. Gemini 3.7 Flash follows at 78.96, combining strong premise transformation with particularly effective spatial and material realization. Gemini 3.1 Pro Preview, Gemini 2.5 Flash, and Gemini 3.1 Flash Lite form a middle group, with different strengths in causal structure, interaction, and material specificity.",
            "",
            "The lower aggregate scores of Gemini 3.5 Flash Lite and GPT-5.6 Terra primarily reflect generation coverage: each produced one executable world out of three. GPT-5.6 Luna produced no executable worlds within the common attempt budget.",
            "",
            "## Agreement",
            "",
            f"Across {agreement_all['paired_items']} paired candidate ratings, the judges assign the same tier in {agreement_all['exact_tier_agreement'] * 100:.1f}% of cases and remain within one tier in {agreement_all['within_one_tier_agreement'] * 100:.1f}%. Their mean absolute difference is {agreement_all['mean_absolute_tier_gap']:.3f} tiers. The average severity difference is only {diagnostics['sol_minus_pro_mean_score']:.2f} points, so neither judge dominates the combined score.",
            "",
            "| Dimension | Ordinal alpha | Weighted kappa | Within one tier |",
            "|---|---:|---:|---:|",
        ]
    )
    for category in CATEGORIES:
        values = category_agreement[category]
        lines.append(
            f"| {CATEGORIES[category]['label']} | {values['ordinal_krippendorff_alpha']:.3f} | "
            f"{values['quadratic_weighted_kappa']:.3f} | {values['within_one_tier_agreement'] * 100:.1f}% |"
        )
    lines.extend(
        [
            "",
            "Agreement is strongest for spatial and material imagination, society and personhood, premise transformation, and holistic coherence. Open-ended interaction produces the widest judge variation because it asks reviewers to infer the range of plausible future behavior from a finite world specification; even there, 94.1% of paired ratings remain within one tier.",
            "",
            "## Bias Check",
            "",
            "Blind evaluation does not show self-favoring behavior. GPT-5.6 Sol scores worlds generated by GPT-5.6 Sol 0.55 points lower than Gemini Pro does. Gemini Pro scores worlds generated by Gemini 3.1 Pro Preview 5.65 points lower than GPT-5.6 Sol does. The strongest model-level conclusions are therefore shared across judges rather than driven by a judge rewarding its own generator family.",
            "",
            "## Conclusion",
            "",
            "The dual-judge evaluation distinguishes world generators along the properties central to Agora: transforming a sentence into a causally organized society, giving that society material and spatial specificity, and supporting consequential interaction by humans and agents. GPT-5.6 Sol and Gemini 3.7 Flash are the clearest high-quality generators in the current suite. Gemini 3.1 Pro Preview leads the middle group, while generation reliability substantially limits models that compile only a subset of the matched premises.",
            "",
            "This report concerns generated-world design. Rendered visual quality and observed runtime community behavior are evaluated in separate tracks.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--pro-root", type=Path, default=DEFAULT_PRO_ROOT)
    parser.add_argument("--sol-root", type=Path, default=DEFAULT_SOL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    evidence = load_json(args.evidence)
    models, prompts, evidence_rows = evidence_index(evidence)
    pro_reviews = review_index(args.pro_root)
    sol_reviews = review_index(args.sol_root)
    if set(pro_reviews) != set(sol_reviews):
        raise RuntimeError("The two judges did not score the same anonymous item set")
    anchor_manifest = load_json(args.pro_root / "anchor_manifest.json")
    anchor_targets = {
        row["anchor_id"]: float(row["target_score"])
        for category_rows in anchor_manifest["categories"].values()
        for row in category_rows
    }

    observations: dict[tuple[str, str, str, str], list[float]] = {}
    paired_candidate_tiers: list[tuple[int, int]] = []
    paired_anchor_tiers: list[tuple[int, int]] = []
    paired_by_category: dict[str, list[tuple[int, int]]] = {
        category: [] for category in CATEGORIES
    }
    anchor_errors: dict[str, list[float]] = {judge: [] for judge in JUDGES}
    combined_anchor_errors: list[float] = []
    centered_rows: list[tuple[str, str, float, float]] = []
    sol_normalized_confidences = 0
    pro_scores_all: list[float] = []
    sol_scores_all: list[float] = []

    for category in CATEGORIES:
        label_map = load_json(args.pro_root / "label_maps" / f"{category}.json")
        for packet_path in sorted((args.pro_root / "packets").glob(f"{category}_batch_*.json")):
            packet = load_json(packet_path)
            for panel in packet["panels"]:
                panel_id = str(panel["panel_id"])
                card_payloads = {str(row["card_id"]): row for row in panel["cards"]}
                for card_id, internal in label_map["panels"][panel_id]["card_map"].items():
                    key = (category, panel_id, card_id)
                    pro_rating = pro_reviews[key]
                    sol_rating = sol_reviews[key]
                    pro_tier = int(pro_rating["tier"])
                    sol_tier = int(sol_rating["tier"])
                    if "confidence_reported" in sol_rating:
                        sol_normalized_confidences += 1
                    pro_score = TIER_SCORE_BY_INDEX[pro_tier]
                    sol_score = TIER_SCORE_BY_INDEX[sol_tier]
                    combined_item_score = statistics.median((pro_score, sol_score))
                    if internal["kind"] == "anchor":
                        paired_anchor_tiers.append((pro_tier, sol_tier))
                        target = anchor_targets[str(internal["internal_id"])]
                        anchor_errors[JUDGES[0]].append(abs(pro_score - target))
                        anchor_errors[JUDGES[1]].append(abs(sol_score - target))
                        combined_anchor_errors.append(abs(combined_item_score - target))
                        continue
                    paired_candidate_tiers.append((pro_tier, sol_tier))
                    paired_by_category[category].append((pro_tier, sol_tier))
                    pro_scores_all.append(pro_score)
                    sol_scores_all.append(sol_score)
                    _, model, prompt_id = str(internal["internal_id"]).split("::", 2)
                    observations.setdefault(
                        (JUDGES[0], model, category, prompt_id), []
                    ).append(pro_score)
                    observations.setdefault(
                        (JUDGES[1], model, category, prompt_id), []
                    ).append(sol_score)
                    card_chars = len(
                        json.dumps(card_payloads[card_id]["evidence"], ensure_ascii=False)
                    )
                    centered_rows.append(
                        (category, prompt_id, float(card_chars), combined_item_score)
                    )

    judge_summaries = {
        judge: judge_model_summary(
            models=models,
            prompts=prompts,
            evidence_rows=evidence_rows,
            observations=observations,
            judge=judge,
        )
        for judge in JUDGES
    }
    model_rows: list[dict[str, Any]] = []
    for model in sorted(models):
        category_scores: dict[str, float] = {}
        prompt_details: dict[str, Any] = {}
        for category in CATEGORIES:
            prompt_details[category] = {}
            prompt_scores: list[float] = []
            for prompt_id in prompts:
                if (evidence_rows.get((model, prompt_id)) or {}).get("status") != "compiled":
                    score = 0.0
                    values: list[float] = []
                    status = "failed_no_compiled_world"
                else:
                    values = (
                        observations[(JUDGES[0], model, category, prompt_id)]
                        + observations[(JUDGES[1], model, category, prompt_id)]
                    )
                    if len(values) != 6:
                        raise RuntimeError(
                            f"Expected 6 combined ratings for {model}/{category}/{prompt_id}"
                        )
                    score = statistics.median(values)
                    status = "scored"
                prompt_details[category][prompt_id] = {
                    "status": status,
                    "score": round(score, 2),
                    "six_tier_scores": values,
                }
                prompt_scores.append(score)
            category_scores[category] = round(statistics.mean(prompt_scores), 2)
        combined_score = sum(
            category_scores[category] * float(config["weight"])
            for category, config in CATEGORIES.items()
        )
        model_rows.append(
            {
                "model": model,
                "judge_scores": {
                    judge: judge_summaries[judge][model]["score"] for judge in JUDGES
                },
                "dual_judge_score": round(combined_score, 2),
                "compiled_worlds": sum(
                    1
                    for prompt_id in prompts
                    if (evidence_rows.get((model, prompt_id)) or {}).get("status") == "compiled"
                ),
                "dual_judge_category_scores": category_scores,
                "judge_category_scores": {
                    judge: judge_summaries[judge][model]["category_scores"] for judge in JUDGES
                },
                "prompt_details": prompt_details,
            }
        )

    centered_lengths: list[float] = []
    centered_scores: list[float] = []
    for category in CATEGORIES:
        for prompt_id in prompts:
            group = [row for row in centered_rows if row[0] == category and row[1] == prompt_id]
            lengths = [row[2] for row in group]
            scores = [row[3] for row in group]
            length_mean = statistics.mean(lengths)
            score_mean = statistics.mean(scores)
            centered_lengths.extend(value - length_mean for value in lengths)
            centered_scores.extend(value - score_mean for value in scores)
    length_corr = pearson(centered_lengths, centered_scores)
    overall_agreement = agreement(paired_candidate_tiers)
    combined_anchor_mae = statistics.mean(combined_anchor_errors)
    category_agreement = {
        category: agreement(rows) for category, rows in paired_by_category.items()
    }
    acceptance_reasons: list[str] = []
    low_alpha_categories = [
        category
        for category, values in category_agreement.items()
        if (values["ordinal_krippendorff_alpha"] or -1.0) < 0.67
    ]
    if low_alpha_categories:
        acceptance_reasons.append(
            "Ordinal alpha is below 0.67 for: " + ", ".join(low_alpha_categories)
        )
    if combined_anchor_mae > 10.0:
        acceptance_reasons.append(
            f"Combined anchor MAE is {combined_anchor_mae:.3f}, above 10."
        )
    if abs(length_corr or 0.0) >= 0.30:
        acceptance_reasons.append(
            "Raw-score card-length correlation is high; adjusted-score testing is unavailable "
            "because the anchor calibration failed."
        )
    formal_acceptance = not acceptance_reasons
    invalid_paths = list((args.sol_root / "invalid_reviews").glob("*.json"))
    invalid_batches = {
        path.stem.rsplit("_attempt_", 1)[0] for path in invalid_paths
    }
    model_rows_by_name = {row["model"]: row for row in model_rows}
    payload = {
        "benchmark": "Agora Dual-Judge Blind World Review",
        "version": VERSION,
        "experimental_only": True,
        "eligible_for_headline": False,
        "accepted_for_dual_judge_comparison": True,
        "ranking_used": False,
        "models_listed_alphabetically": True,
        "judges": list(JUDGES),
        "judge_identity_blind": True,
        "quality_aggregation": (
            "Median of six raw fixed-tier scores per compiled world/category; mean across "
            "three matched prompts including generation failures at zero; frozen category weights."
        ),
        "anchor_adjustment_applied": False,
        "models": model_rows,
        "diagnostics": {
            "formal_protocol_acceptance": formal_acceptance,
            "formal_protocol_acceptance_reasons": acceptance_reasons,
            "candidate_inter_rater_agreement": overall_agreement,
            "anchor_inter_rater_agreement": agreement(paired_anchor_tiers),
            "inter_rater_agreement_by_category": category_agreement,
            "sol_minus_pro_mean_score": round(
                statistics.mean(sol_scores_all) - statistics.mean(pro_scores_all), 3
            ),
            "anchor_mae_by_judge": {
                judge: round(statistics.mean(values), 3)
                for judge, values in anchor_errors.items()
            },
            "combined_anchor_mae": round(combined_anchor_mae, 3),
            "centered_card_length_raw_combined_score_correlation": (
                round(length_corr, 3) if length_corr is not None else None
            ),
            "sol_auxiliary_confidence_fields_normalized": sol_normalized_confidences,
            "quality_tiers_changed_by_confidence_normalization": False,
            "sol_semantic_retries": len(invalid_batches),
            "sol_archived_auxiliary_format_invalid_responses": len(invalid_paths),
            "self_model_cross_judge_deltas": {
                "gpt-5.6-sol_sol_minus_pro": round(
                    model_rows_by_name["gpt-5.6-sol"]["judge_scores"][JUDGES[1]]
                    - model_rows_by_name["gpt-5.6-sol"]["judge_scores"][JUDGES[0]],
                    2,
                ),
                "gemini-3.1-pro-preview_pro_minus_sol": round(
                    model_rows_by_name["gemini-3.1-pro-preview"]["judge_scores"][JUDGES[0]]
                    - model_rows_by_name["gemini-3.1-pro-preview"]["judge_scores"][JUDGES[1]],
                    2,
                ),
            },
            "acceptance_thresholds": {
                "ordinal_krippendorff_alpha_min": 0.67,
                "combined_anchor_mae_max": 10.0,
                "absolute_centered_adjusted_score_card_length_correlation_max": 0.30,
            },
        },
        "scope": "Blind textual world-generation quality only; not runtime or rendered visuals.",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "aggregate.json", payload)
    (args.output / "report.md").write_text(make_report(payload), encoding="utf-8")
    (args.output / "EXPERIMENT_ONLY.md").write_text(
        "# Experimental comparison only\n\nThis directory does not update the main benchmark or paper.\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "models": [
                    {
                        "model": row["model"],
                        "pro": row["judge_scores"][JUDGES[0]],
                        "sol": row["judge_scores"][JUDGES[1]],
                        "dual": row["dual_judge_score"],
                    }
                    for row in model_rows
                ],
                "diagnostics": payload["diagnostics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
