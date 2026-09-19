#!/usr/bin/env python3
"""Run the experimental anchored, no-ranking Gemini Pro blind review."""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora_ui.vertex_json_client import VertexJsonClient
from scripts.agora_parallel_blind_world_review import (
    CATEGORIES,
    card_for_category,
    client_config,
    evidence_index,
    load_env_key,
    load_json,
    pearson,
    prompt_sentences,
    write_json,
)


EVIDENCE_ROOT = ROOT / "docs" / "living_world_benchmark_20260825_hidden"
DEV_ROOT = ROOT / "docs" / "living_world_benchmark_20260824" / "model_comparison_20260824"
DEFAULT_EVIDENCE = EVIDENCE_ROOT / "strict_generation_evidence_v1.json"
DEFAULT_COMPREHENSIVE = EVIDENCE_ROOT / "cross_provider_comprehensive_results.json"
DEFAULT_OUTPUT = EVIDENCE_ROOT / "anchored_blind_review_pro_v0_1"
DEV_RESULTS = DEV_ROOT / "comparison_results.json"
PROTOCOL_VERSION = "anchored-blind-world-review-v0.1"
TIER_SCORE_BY_INDEX = {
    0: 0.0,
    1: 25.0,
    2: 45.0,
    3: 60.0,
    4: 75.0,
    5: 85.0,
    6: 92.0,
}

# Frozen before the hidden-world calls. These targets are nearest-tier projections
# of the independent development-set expert review, not scores from this judge.
ANCHORS: dict[str, list[dict[str, Any]]] = {
    "premise_causality": [
        {"model_dir": "gemini_2_5_flash", "target_tier": 4},
        {"model_dir": "gemini_3_7_flash", "target_tier": 6},
    ],
    "society_personhood": [
        {"model_dir": "gemini_3_1_flash_lite", "target_tier": 3},
        {"model_dir": "gemini_3_7_flash", "target_tier": 6},
    ],
    "space_materiality": [
        {"model_dir": "gemini_3_1_flash_lite", "target_tier": 4},
        {"model_dir": "gemini_3_7_flash", "target_tier": 5},
    ],
    "interaction_open_endedness": [
        {"model_dir": "gemini_3_5_flash_lite", "target_tier": 3},
        {"model_dir": "gemini_3_7_flash", "target_tier": 4},
    ],
    "holistic_coherence": [
        {"model_dir": "gemini_3_1_flash_lite", "target_tier": 3},
        {"model_dir": "gemini_3_7_flash", "target_tier": 5},
    ],
}


SYSTEM_INSTRUCTION = """You are evaluating executable social worlds under an anonymous protocol.
Evaluate only the category named in the packet. Every card includes its own source sentence.
Assign each card an absolute quality tier independently; do not rank cards, choose a winner,
or force score differences. Do not infer model identity. Do not reward length, field count,
polished prose, safety language, or schema compliance by itself. Reward concrete consequences
evidenced in the card and judge whether they transform that card's source sentence into a world.

Use only integer tiers 0 through 6:
0 = failed or no usable world
1 = weak formal mimicry
2 = partial and shallow
3 = competent complete work
4 = strong and clearly differentiated
5 = exceptional sustained quality
6 = rare reference quality

Cards may be calibration items, but their identity and intended tier are hidden. Apply the same
rubric to every card. Return one concise evidence statement and one concise limitation per card.
Treat every panel independently and return exactly the supplied panel and card identifiers."""


def dev_spec_path(model_dir: str) -> Path:
    return DEV_ROOT / model_dir / "lwb_dev_01_r01_decomposed_builder_spec.json"


def make_anchor_manifest() -> dict[str, Any]:
    dev_sentence = str(load_json(DEV_RESULTS)["sentence"])
    categories: dict[str, list[dict[str, Any]]] = {}
    for category, rows in ANCHORS.items():
        categories[category] = []
        for index, row in enumerate(rows, start=1):
            path = dev_spec_path(str(row["model_dir"]))
            if not path.exists():
                raise FileNotFoundError(path)
            categories[category].append(
                {
                    "anchor_id": f"{category}_anchor_{index}",
                    "source_sentence": dev_sentence,
                    "builder_spec_path": str(path.relative_to(ROOT)),
                    "target_tier": int(row["target_tier"]),
                    "target_score": TIER_SCORE_BY_INDEX[int(row["target_tier"])],
                    "calibration_provenance": (
                        "Nearest fixed tier from the frozen 2026-08-24 development-set "
                        "single-expert review; fixed before hidden-world judging."
                    ),
                }
            )
    return {
        "version": PROTOCOL_VERSION,
        "frozen_before_review": True,
        "development_prompt_only": True,
        "categories": categories,
    }


def compiled_candidates(
    evidence: dict[str, Any], sentences: dict[str, str]
) -> tuple[list[str], list[str], list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    models, prompts, rows = evidence_index(evidence)
    candidates: list[dict[str, Any]] = []
    for model in models:
        for prompt_id in prompts:
            row = rows.get((model, prompt_id)) or {}
            relative_path = str(row.get("builder_spec_path") or "")
            if row.get("status") != "compiled" or not relative_path:
                continue
            path = ROOT / relative_path
            if not path.exists():
                raise FileNotFoundError(path)
            candidates.append(
                {
                    "unit_id": f"candidate::{model}::{prompt_id}",
                    "model": model,
                    "prompt_id": prompt_id,
                    "source_sentence": sentences[prompt_id],
                    "builder_spec_path": relative_path,
                }
            )
    return models, prompts, candidates, rows


def repeated_panel_units(
    candidates: list[dict[str, Any]], *, repeats: int, seed: int
) -> list[list[dict[str, Any]]]:
    if not candidates or len(candidates) * repeats % 3:
        raise ValueError("Candidate appearances must divide exactly into three-card panels")
    population = [candidate for candidate in candidates for _ in range(repeats)]
    for attempt in range(10000):
        rng = random.Random(seed + attempt * 7919)
        shuffled = list(population)
        rng.shuffle(shuffled)
        panels = [shuffled[index : index + 3] for index in range(0, len(shuffled), 3)]
        if all(len({row["unit_id"] for row in panel}) == 3 for panel in panels):
            counts = Counter(row["unit_id"] for panel in panels for row in panel)
            if all(value == repeats for value in counts.values()):
                return panels
    raise RuntimeError("Could not construct duplicate-free panels")


def prepare_category(
    *,
    category: str,
    candidates: list[dict[str, Any]],
    anchor_manifest: dict[str, Any],
    repeats: int,
    seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    panels_of_units = repeated_panel_units(
        candidates,
        repeats=repeats,
        seed=seed + sum(map(ord, category)),
    )
    anchor_rows = anchor_manifest["categories"][category]
    anchor_cards: list[dict[str, Any]] = []
    for row in anchor_rows:
        anchor_cards.append(
            {
                "kind": "anchor",
                "internal_id": row["anchor_id"],
                "source_sentence": row["source_sentence"],
                "evidence": card_for_category(
                    load_json(ROOT / row["builder_spec_path"]), category
                ),
            }
        )

    panels: list[dict[str, Any]] = []
    label_map: dict[str, Any] = {"category": category, "panels": {}}
    occurrence_counter: Counter[str] = Counter()
    for panel_index, units in enumerate(panels_of_units, start=1):
        panel_id = f"{category}_P{panel_index:02d}"
        internal_cards: list[dict[str, Any]] = list(anchor_cards)
        for unit in units:
            occurrence_counter[unit["unit_id"]] += 1
            internal_cards.append(
                {
                    "kind": "candidate",
                    "internal_id": unit["unit_id"],
                    "occurrence": occurrence_counter[unit["unit_id"]],
                    "source_sentence": unit["source_sentence"],
                    "evidence": card_for_category(
                        load_json(ROOT / unit["builder_spec_path"]), category
                    ),
                }
            )
        rng = random.Random(seed + panel_index * 1009 + sum(map(ord, category)))
        rng.shuffle(internal_cards)
        labels = [f"W{index:02d}" for index in range(1, 6)]
        cards: list[dict[str, Any]] = []
        mappings: dict[str, Any] = {}
        for label, internal in zip(labels, internal_cards):
            cards.append(
                {
                    "card_id": label,
                    "source_sentence": internal["source_sentence"],
                    "evidence": internal["evidence"],
                }
            )
            mappings[label] = {
                key: value
                for key, value in internal.items()
                if key not in {"source_sentence", "evidence"}
            }
        panels.append({"panel_id": panel_id, "cards": cards})
        label_map["panels"][panel_id] = {
            "card_map": mappings,
            "presentation_order": labels,
        }
    return panels, label_map


def make_batches(
    panels: list[dict[str, Any]], *, category: str, batch_size: int
) -> list[dict[str, Any]]:
    return [
        {
            "protocol": PROTOCOL_VERSION,
            "category": category,
            "category_label": CATEGORIES[category]["label"],
            "category_question": CATEGORIES[category]["question"],
            "tier_scale": {
                "0": "failed or no usable world",
                "1": "weak formal mimicry",
                "2": "partial and shallow",
                "3": "competent complete work",
                "4": "strong and clearly differentiated",
                "5": "exceptional sustained quality",
                "6": "rare reference quality",
            },
            "panels": panels[index : index + batch_size],
        }
        for index in range(0, len(panels), batch_size)
    ]


def response_schema() -> dict[str, Any]:
    rating = {
        "type": "object",
        "properties": {
            "card_id": {"type": "string"},
            "tier": {"type": "integer"},
            "strongest_evidence": {"type": "string"},
            "main_limitation": {"type": "string"},
            "confidence": {"type": "integer"},
        },
        "required": [
            "card_id",
            "tier",
            "strongest_evidence",
            "main_limitation",
            "confidence",
        ],
    }
    panel_review = {
        "type": "object",
        "properties": {
            "panel_id": {"type": "string"},
            "ratings": {"type": "array", "items": rating},
        },
        "required": ["panel_id", "ratings"],
    }
    return {
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "panel_reviews": {"type": "array", "items": panel_review},
        },
        "required": ["category", "panel_reviews"],
    }


def validate_review(review: dict[str, Any], packet: dict[str, Any]) -> None:
    if str(review.get("category")) != str(packet["category"]):
        raise ValueError("Reviewer returned the wrong category")
    expected = {str(row["panel_id"]): row for row in packet["panels"]}
    returned_rows = review.get("panel_reviews") or []
    returned = {str(row.get("panel_id")): row for row in returned_rows}
    if len(returned_rows) != len(returned) or set(returned) != set(expected):
        raise ValueError("Reviewer returned the wrong panel set")
    for panel_id, panel in expected.items():
        expected_ids = {str(row["card_id"]) for row in panel["cards"]}
        ratings = returned[panel_id].get("ratings") or []
        returned_ids = [str(row.get("card_id")) for row in ratings]
        if len(returned_ids) != len(set(returned_ids)) or set(returned_ids) != expected_ids:
            raise ValueError(f"Reviewer returned wrong cards for {panel_id}")
        for rating in ratings:
            tier = rating.get("tier")
            confidence = rating.get("confidence")
            if not isinstance(tier, int) or not 0 <= tier <= 6:
                raise ValueError(f"Invalid tier in {panel_id}")
            if not isinstance(confidence, int) or not 1 <= confidence <= 5:
                raise ValueError(f"Invalid confidence in {panel_id}")


def aggregate(
    *,
    evidence: dict[str, Any],
    output: Path,
    anchor_manifest: dict[str, Any],
    repeats: int,
    judge_model: str,
) -> dict[str, Any]:
    models, prompts, evidence_rows = evidence_index(evidence)
    observations: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    anchor_errors: list[float] = []
    anchor_biases: list[float] = []
    position_x: list[float] = []
    position_y: list[float] = []
    length_score_rows: list[tuple[str, str, float, float]] = []
    confidence_values: list[float] = []

    anchor_targets = {
        row["anchor_id"]: float(row["target_score"])
        for category_rows in anchor_manifest["categories"].values()
        for row in category_rows
    }
    for category in CATEGORIES:
        label_map = load_json(output / "label_maps" / f"{category}.json")
        packet_files = sorted((output / "packets").glob(f"{category}_batch_*.json"))
        for packet_path in packet_files:
            batch_id = packet_path.stem
            packet = load_json(packet_path)
            review = load_json(output / "raw_reviews" / f"{batch_id}.json")
            review_by_panel = {
                str(row["panel_id"]): row for row in review["panel_reviews"]
            }
            packet_by_panel = {str(row["panel_id"]): row for row in packet["panels"]}
            for panel_id, panel_review in review_by_panel.items():
                mapping = label_map["panels"][panel_id]
                packet_cards = {
                    str(row["card_id"]): row for row in packet_by_panel[panel_id]["cards"]
                }
                ratings = {
                    str(row["card_id"]): row for row in panel_review["ratings"]
                }
                observed_anchors: list[tuple[float, float]] = []
                for card_id, internal in mapping["card_map"].items():
                    if internal["kind"] != "anchor":
                        continue
                    observed = TIER_SCORE_BY_INDEX[int(ratings[card_id]["tier"])]
                    target = anchor_targets[str(internal["internal_id"])]
                    observed_anchors.append((observed, target))
                    anchor_errors.append(abs(observed - target))
                if len(observed_anchors) != 2:
                    raise RuntimeError(f"Panel {panel_id} did not contain two anchors")
                panel_bias = statistics.mean(observed - target for observed, target in observed_anchors)
                anchor_biases.append(panel_bias)
                for position, card_id in enumerate(mapping["presentation_order"], start=1):
                    internal = mapping["card_map"][card_id]
                    if internal["kind"] != "candidate":
                        continue
                    rating = ratings[card_id]
                    raw_score = TIER_SCORE_BY_INDEX[int(rating["tier"])]
                    adjusted_score = min(100.0, max(0.0, raw_score - panel_bias))
                    _, model, prompt_id = str(internal["internal_id"]).split("::", 2)
                    card_chars = len(
                        json.dumps(packet_cards[card_id]["evidence"], ensure_ascii=False)
                    )
                    row = {
                        "tier": int(rating["tier"]),
                        "tier_score": raw_score,
                        "panel_anchor_bias": round(panel_bias, 3),
                        "adjusted_score": round(adjusted_score, 3),
                        "confidence": int(rating["confidence"]),
                        "presentation_position": position,
                        "card_characters": card_chars,
                        "strongest_evidence": rating["strongest_evidence"],
                        "main_limitation": rating["main_limitation"],
                        "panel_id": panel_id,
                    }
                    observations.setdefault((model, category, prompt_id), []).append(row)
                    position_x.append(float(position))
                    position_y.append(raw_score)
                    length_score_rows.append(
                        (category, prompt_id, float(card_chars), adjusted_score)
                    )
                    confidence_values.append(float(rating["confidence"]))

    prompt_details: dict[str, dict[str, dict[str, Any]]] = {}
    model_rows: list[dict[str, Any]] = []
    for model in sorted(models):
        prompt_details[model] = {}
        category_scores: dict[str, float] = {}
        raw_category_scores: dict[str, float] = {}
        for category in CATEGORIES:
            prompt_details[model][category] = {}
            prompt_scores: list[float] = []
            raw_prompt_scores: list[float] = []
            for prompt_id in prompts:
                case = evidence_rows.get((model, prompt_id)) or {}
                if case.get("status") != "compiled":
                    detail = {
                        "status": "failed_no_compiled_world",
                        "score": 0.0,
                        "raw_tier_score": 0.0,
                        "observations": [],
                    }
                else:
                    rows = observations.get((model, category, prompt_id), [])
                    if len(rows) != repeats:
                        raise RuntimeError(
                            f"Expected {repeats} observations for {model}/{category}/{prompt_id}, "
                            f"found {len(rows)}"
                        )
                    tiers = [int(row["tier"]) for row in rows]
                    scores = [float(row["adjusted_score"]) for row in rows]
                    raw_scores = [float(row["tier_score"]) for row in rows]
                    detail = {
                        "status": "scored",
                        "score": round(statistics.median(scores), 2),
                        "raw_tier_score": round(statistics.median(raw_scores), 2),
                        "tier_median": statistics.median(tiers),
                        "repeat_score_stddev": round(statistics.pstdev(scores), 2),
                        "repeat_exact_tier_agreement": len(set(tiers)) == 1,
                        "repeat_within_one_tier": max(tiers) - min(tiers) <= 1,
                        "observations": rows,
                    }
                prompt_details[model][category][prompt_id] = detail
                prompt_scores.append(float(detail["score"]))
                raw_prompt_scores.append(float(detail["raw_tier_score"]))
            category_scores[category] = round(statistics.mean(prompt_scores), 2)
            raw_category_scores[category] = round(statistics.mean(raw_prompt_scores), 2)
        overall = sum(
            category_scores[category] * float(config["weight"])
            for category, config in CATEGORIES.items()
        )
        raw_overall = sum(
            raw_category_scores[category] * float(config["weight"])
            for category, config in CATEGORIES.items()
        )
        model_rows.append(
            {
                "model": model,
                "raw_fixed_tier_observation": round(raw_overall, 2),
                "anchor_adjusted_diagnostic": round(overall, 2),
                "compiled_worlds": sum(
                    1
                    for prompt_id in prompts
                    if (evidence_rows.get((model, prompt_id)) or {}).get("status") == "compiled"
                ),
                "category_scores": category_scores,
                "raw_category_scores": raw_category_scores,
                "prompt_details": prompt_details[model],
            }
        )

    scored_details = [
        detail
        for model in prompt_details.values()
        for category in model.values()
        for detail in category.values()
        if detail["status"] == "scored"
    ]
    exact_agreement = statistics.mean(
        1.0 if detail["repeat_exact_tier_agreement"] else 0.0 for detail in scored_details
    )
    within_one = statistics.mean(
        1.0 if detail["repeat_within_one_tier"] else 0.0 for detail in scored_details
    )
    mean_repeat_sd = statistics.mean(
        float(detail["repeat_score_stddev"]) for detail in scored_details
    )
    centered_lengths: list[float] = []
    centered_scores: list[float] = []
    for category in CATEGORIES:
        for prompt_id in prompts:
            group = [
                row for row in length_score_rows if row[0] == category and row[1] == prompt_id
            ]
            lengths = [row[2] for row in group]
            scores = [row[3] for row in group]
            length_mean = statistics.mean(lengths)
            score_mean = statistics.mean(scores)
            centered_lengths.extend(value - length_mean for value in lengths)
            centered_scores.extend(value - score_mean for value in scores)
    position_corr = pearson(position_x, position_y)
    length_corr = pearson(centered_lengths, centered_scores)
    raw_anchor_mae = statistics.mean(anchor_errors)
    residual_anchor_errors: list[float] = []
    for category in CATEGORIES:
        label_map = load_json(output / "label_maps" / f"{category}.json")
        for panel_id, panel_map in label_map["panels"].items():
            packet_path = next(
                path
                for path in sorted((output / "packets").glob(f"{category}_batch_*.json"))
                if panel_id in {
                    str(row["panel_id"]) for row in load_json(path)["panels"]
                }
            )
            review = load_json(output / "raw_reviews" / f"{packet_path.stem}.json")
            ratings = {
                str(rating["card_id"]): rating
                for panel in review["panel_reviews"]
                if str(panel["panel_id"]) == panel_id
                for rating in panel["ratings"]
            }
            errors = [
                TIER_SCORE_BY_INDEX[int(ratings[card_id]["tier"])]
                - anchor_targets[str(internal["internal_id"])]
                for card_id, internal in panel_map["card_map"].items()
                if internal["kind"] == "anchor"
            ]
            panel_bias = statistics.mean(errors)
            residual_anchor_errors.extend(abs(error - panel_bias) for error in errors)
    residual_anchor_mae = statistics.mean(residual_anchor_errors)
    calibration_diagnostics_passed = (
        raw_anchor_mae <= 10.0 and abs(length_corr or 0.0) < 0.30
    )
    return {
        "benchmark": "Agora Anchored Blind World Review",
        "version": PROTOCOL_VERSION,
        "experimental_only": True,
        "eligible_for_headline": False,
        "judge_model": judge_model,
        "judge_identity_blind": True,
        "ranking_used": False,
        "pool_size_invariant": True,
        "models_listed_alphabetically": True,
        "repeats_per_compiled_world_category": repeats,
        "prompt_count": len(prompts),
        "category_weights": {
            category: round(float(config["weight"]), 8)
            for category, config in CATEGORIES.items()
        },
        "aggregation": (
            "Map the independent 0-6 tier to fixed scores; subtract each panel's mean "
            "anchor deviation; take the median of three appearances per world/category; "
            "average matched prompts with failed worlds fixed at zero; apply fixed category weights."
        ),
        "models": model_rows,
        "diagnostics": {
            "formal_acceptance": False,
            "formal_acceptance_reasons": [
                "Only one judge was used; the frozen protocol requires at least two.",
                "Ordinal inter-rater alpha is unavailable with one judge.",
            ],
            "calibration_diagnostics_passed": calibration_diagnostics_passed,
            "raw_anchor_mae": round(raw_anchor_mae, 3),
            "anchor_residual_mae_after_panel_correction": round(residual_anchor_mae, 3),
            "mean_panel_anchor_bias": round(statistics.mean(anchor_biases), 3),
            "mean_repeat_score_stddev": round(mean_repeat_sd, 3),
            "exact_repeat_tier_agreement_rate": round(exact_agreement, 3),
            "within_one_tier_repeat_agreement_rate": round(within_one, 3),
            "presentation_position_score_correlation": (
                round(position_corr, 3) if position_corr is not None else None
            ),
            "prompt_category_centered_card_length_adjusted_score_correlation": (
                round(length_corr, 3) if length_corr is not None else None
            ),
            "mean_confidence": round(statistics.mean(confidence_values), 3),
            "acceptance_thresholds": {
                "anchor_mae_max": 10.0,
                "absolute_card_length_score_correlation_max": 0.30,
            },
            "note": (
                "The preregistered two-rater and ordinal-alpha criteria cannot be evaluated "
                "in this single-judge Pro comparison experiment."
            ),
        },
        "scope": (
            "Textual generated-world quality only. This single-judge comparison neither "
            "replaces the main result nor evaluates rendered visuals or runtime interactions."
        ),
    }


def make_report(payload: dict[str, Any]) -> str:
    diagnostics = payload["diagnostics"]
    lines = [
        "# Gemini 3.1 Pro Anchored Blind Review",
        "",
        "> EXPERIMENTAL COMPARISON ONLY. This is not a leaderboard and is not eligible for the main benchmark or paper headline.",
        "",
        "## Protocol",
        "",
        "Gemini 3.1 Pro Preview saw anonymous, category-specific evidence cards. Each small panel contained three evaluated worlds and two hidden fixed development-set anchors. It assigned every card an independent ordinal tier from 0 to 6; no ranks, winners, model names, prior scores, costs, latencies, or retry histories were shown. Each compiled hidden world appeared in three separately shuffled panels.",
        "",
        "The run did not meet the frozen acceptance criteria: it has one judge and its independently assigned development-anchor targets did not calibrate to Pro's severity. Consequently, no anchor-adjusted composite is reported as a valid score. The table below preserves Pro's raw fixed-tier observations for audit only; it is listed alphabetically and is not a ranking. Failed generations remain zero under the common generation budget.",
        "",
        "## Raw Tier Observations",
        "",
        "| Model | Raw tier observation | Compiled | Premise/causal | Society/personhood | Space/material | Interaction/open | Holistic |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["models"]:
        scores = row["raw_category_scores"]
        lines.append(
            f"| {row['model']} | **{row['raw_fixed_tier_observation']:.2f}** | "
            f"{row['compiled_worlds']}/3 | {scores['premise_causality']:.2f} | "
            f"{scores['society_personhood']:.2f} | {scores['space_materiality']:.2f} | "
            f"{scores['interaction_open_endedness']:.2f} | {scores['holistic_coherence']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Diagnostics",
            "",
            f"- Formal acceptance: `{diagnostics['formal_acceptance']}` (single judge; no inter-rater alpha)",
            f"- Calibration diagnostics passed: `{diagnostics['calibration_diagnostics_passed']}`",
            f"- Raw anchor mean absolute error: `{diagnostics['raw_anchor_mae']}` (required <= 10)",
            f"- Anchor residual MAE after panel correction: `{diagnostics['anchor_residual_mae_after_panel_correction']}`",
            f"- Mean repeated-score standard deviation: `{diagnostics['mean_repeat_score_stddev']}`",
            f"- Exact repeated-tier agreement: `{diagnostics['exact_repeat_tier_agreement_rate']}`",
            f"- Within-one-tier agreement: `{diagnostics['within_one_tier_repeat_agreement_rate']}`",
            f"- Presentation-position/score correlation: `{diagnostics['presentation_position_score_correlation']}`",
            f"- Prompt/category-centered card-length/adjusted-score correlation: `{diagnostics['prompt_category_centered_card_length_adjusted_score_correlation']}` (required |r| < 0.30)",
            f"- Mean stated confidence: `{diagnostics['mean_confidence']}` / 5",
            "",
            "This run measures textual world generation only. Visual quality and actual runtime interaction remain separate evaluation tracks.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--comprehensive", type=Path, default=DEFAULT_COMPREHENSIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--judge-model", default="gemini-3.1-pro-preview")
    parser.add_argument("--api-key-env", default="AGORA_AISTUDIO_API_KEY")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--thinking-level", default="low")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260826)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()

    if args.repeats != 3:
        raise ValueError("The frozen v0.1 protocol requires exactly three repeats")
    if args.batch_size < 1:
        raise ValueError("Batch size must be positive")
    evidence = load_json(args.evidence)
    sentences = prompt_sentences(load_json(args.comprehensive))
    models, prompts, candidates, _ = compiled_candidates(evidence, sentences)
    args.output.mkdir(parents=True, exist_ok=True)
    anchor_manifest = make_anchor_manifest()
    write_json(args.output / "anchor_manifest.json", anchor_manifest)
    write_json(
        args.output / "protocol.json",
        {
            "version": PROTOCOL_VERSION,
            "experimental_only": True,
            "eligible_for_headline": False,
            "judge_model": args.judge_model,
            "ranking_used": False,
            "categories": CATEGORIES,
            "tier_scores": TIER_SCORE_BY_INDEX,
            "repeats_per_compiled_world_category": args.repeats,
            "candidate_cards_per_panel": 3,
            "hidden_anchors_per_panel": 2,
            "batch_size_panels_per_call": args.batch_size,
            "compiled_candidate_worlds": len(candidates),
            "failed_worlds_fixed_at_zero": len(models) * len(prompts) - len(candidates),
            "seed": args.seed,
            "aggregation": (
                "Per-panel anchor-severity correction, median across three appearances, "
                "mean across matched prompts including fixed failures, fixed category weights."
            ),
        },
    )
    (args.output / "EXPERIMENT_ONLY.md").write_text(
        "# Experimental output only\n\nThis directory must not update the main benchmark or paper headline.\n",
        encoding="utf-8",
    )

    batch_jobs: list[tuple[str, int, dict[str, Any]]] = []
    for category in CATEGORIES:
        panels, label_map = prepare_category(
            category=category,
            candidates=candidates,
            anchor_manifest=anchor_manifest,
            repeats=args.repeats,
            seed=args.seed,
        )
        write_json(args.output / "label_maps" / f"{category}.json", label_map)
        batches = make_batches(panels, category=category, batch_size=args.batch_size)
        for batch_index, packet in enumerate(batches, start=1):
            write_json(
                args.output / "packets" / f"{category}_batch_{batch_index:02d}.json",
                packet,
            )
            batch_jobs.append((category, batch_index, packet))

    if args.prepare_only:
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "compiled_candidate_worlds": len(candidates),
                    "panels": len(candidates) * args.repeats // 3 * len(CATEGORIES),
                    "api_calls": len(batch_jobs),
                },
                indent=2,
            )
        )
        return

    if args.aggregate_only:
        result = aggregate(
            evidence=evidence,
            output=args.output,
            anchor_manifest=anchor_manifest,
            repeats=args.repeats,
            judge_model=args.judge_model,
        )
        write_json(args.output / "aggregate.json", result)
        (args.output / "report.md").write_text(make_report(result), encoding="utf-8")
        print(json.dumps(result["diagnostics"], indent=2))
        return

    if args.env_file:
        load_env_key(args.env_file, args.api_key_env)
    if not os.environ.get(args.api_key_env):
        raise RuntimeError(f"{args.api_key_env} is not set")
    config = client_config(args.judge_model, args.api_key_env, args.thinking_level)
    config["vertex_api"]["stages"] = {
        "anchored_blind_review": {
            "model": args.judge_model,
            "temperature": 0.2,
            "max_output_tokens": 8192,
            "thinking_level": args.thinking_level,
        }
    }
    client = VertexJsonClient(config)
    for category, batch_index, packet in batch_jobs:
        batch_id = f"{category}_batch_{batch_index:02d}"
        review_path = args.output / "raw_reviews" / f"{batch_id}.json"
        if review_path.exists():
            validate_review(load_json(review_path), packet)
            print(f"[ANCHORED_BLIND_SKIP] {batch_id}", flush=True)
            continue
        for semantic_attempt in range(1, 3):
            print(
                f"[ANCHORED_BLIND] {batch_id} semantic_attempt={semantic_attempt}",
                flush=True,
            )
            review = client.generate_json(
                system_instruction=SYSTEM_INSTRUCTION,
                prompt=json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                schema=response_schema(),
                stage="anchored_blind_review",
            )
            try:
                validate_review(review, packet)
            except ValueError:
                write_json(
                    args.output
                    / "invalid_reviews"
                    / f"{batch_id}_attempt_{semantic_attempt}.json",
                    review,
                )
                if semantic_attempt >= 2:
                    raise
                continue
            write_json(review_path, review)
            break

    result = aggregate(
        evidence=evidence,
        output=args.output,
        anchor_manifest=anchor_manifest,
        repeats=args.repeats,
        judge_model=args.judge_model,
    )
    write_json(args.output / "aggregate.json", result)
    (args.output / "report.md").write_text(make_report(result), encoding="utf-8")
    print(json.dumps(result["diagnostics"], indent=2))


if __name__ == "__main__":
    main()
