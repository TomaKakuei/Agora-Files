#!/usr/bin/env python3
"""Aggregate the frozen Agora paper experiments without changing analysis units."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("summary", {}).get("per_world", [])
    return [row for row in rows if isinstance(row, dict)]


def _world_outcomes(
    payload: dict[str, Any],
    *,
    success_key: str,
) -> dict[str, bool]:
    return {
        str(row["world_name"]): float(row.get(success_key) or 0.0) > 0.5
        for row in _rows(payload)
    }


def _paired_sign_test(
    left: dict[str, bool],
    right: dict[str, bool],
) -> dict[str, Any]:
    names = sorted(set(left) & set(right))
    left_only = sum(left[name] and not right[name] for name in names)
    right_only = sum(right[name] and not left[name] for name in names)
    discordant = left_only + right_only
    p_value = (
        sum(math.comb(discordant, k) for k in range(left_only, discordant + 1))
        / (2**discordant)
        if discordant
        else 1.0
    )
    return {
        "paired_world_count": len(names),
        "specialist_successes": sum(left[name] for name in names),
        "monolithic_successes": sum(right[name] for name in names),
        "specialist_only": left_only,
        "monolithic_only": right_only,
        "discordant_worlds": discordant,
        "one_sided_exact_p": round(p_value, 6),
    }


def _paired_world_rows(
    specialist: dict[str, Any],
    monolithic: dict[str, Any],
    *,
    split: str,
) -> list[dict[str, Any]]:
    specialist_rows = {
        str(row["world_name"]): row for row in _rows(specialist)
    }
    monolithic_rows = {
        str(row["world_name"]): row for row in _rows(monolithic)
    }
    paired: list[dict[str, Any]] = []
    for world_name in sorted(set(specialist_rows) & set(monolithic_rows)):
        left = specialist_rows[world_name]
        right = monolithic_rows[world_name]
        left_eventual = float(left.get("success_rate") or 0.0)
        right_eventual = float(right.get("success_rate") or 0.0)
        left_first = float(left.get("first_pass_success_rate") or 0.0)
        right_first = float(right.get("first_pass_success_rate") or 0.0)
        paired.append(
            {
                "world_name": world_name,
                "split": split,
                "specialist_eventual_rate": left_eventual,
                "monolithic_eventual_rate": right_eventual,
                "specialist_first_pass_rate": left_first,
                "monolithic_first_pass_rate": right_first,
                "specialist_eventual_success": left_eventual > 0.5,
                "monolithic_eventual_success": right_eventual > 0.5,
                "specialist_first_pass_success": left_first > 0.5,
                "monolithic_first_pass_success": right_first > 0.5,
            }
        )
    return paired


def _cost(payload: dict[str, Any], *, treatment: str) -> dict[str, Any]:
    summary = payload.get("summary", {})
    trials = int(summary.get("trial_count") or 0)
    attempts = int(summary.get("provider_attempt_count") or 0)
    return {
        "treatment": treatment,
        "trials": trials,
        "mean_total_tokens_per_trial": summary.get("mean_total_tokens_per_trial"),
        "mean_elapsed_seconds": summary.get("mean_elapsed_seconds"),
        "median_elapsed_seconds": summary.get("median_elapsed_seconds"),
        "mean_provider_attempts_per_trial": (
            round(attempts / trials, 4) if trials else 0.0
        ),
        "first_pass_successes": (
            summary.get("first_pass_complete_successes")
            if treatment == "specialist"
            else summary.get("first_pass_complete_successes")
        ),
        "eventual_successes": (
            summary.get("complete_successes")
            if treatment == "specialist"
            else summary.get("complete_trial_successes")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "docs/benchmark_20260724/paper_evidence_summary_20260729.json"
        ),
    )
    args = parser.parse_args()
    root = args.root.resolve()

    paths = {
        "primary_specialist": root
        / "docs/benchmark_20260724/decomposed_controlled_low_20260729"
        / "decomposed_controlled_summary.json",
        "primary_monolithic": root
        / "docs/benchmark_20260724/monolithic_baseline_low_24k_quality_20260729"
        / "monolithic_baseline_summary.json",
        "heldout_specialist": root
        / "docs/benchmark_20260724/decomposed_controlled_low_heldout_20260729"
        / "decomposed_controlled_summary.json",
        "heldout_monolithic": root
        / "docs/benchmark_20260724/monolithic_baseline_low_24k_quality_heldout_20260729"
        / "monolithic_baseline_summary.json",
        "quality": root
        / "docs/benchmark_20260724/objective_quality_combined10_20260729"
        / "objective_world_quality.json",
        "quality_heldout": root
        / "docs/benchmark_20260724/objective_quality_heldout_20260729"
        / "objective_world_quality.json",
        "local_repair": root
        / "docs/benchmark_20260724/seeded_local_retry_20260729"
        / "seeded_local_retry_summary.json",
    }
    data = {key: _read(path) for key, path in paths.items()}

    specialist_eventual: dict[str, bool] = {}
    monolithic_eventual: dict[str, bool] = {}
    specialist_first: dict[str, bool] = {}
    monolithic_first: dict[str, bool] = {}
    for split in ("primary", "heldout"):
        specialist_eventual.update(
            _world_outcomes(
                data[f"{split}_specialist"], success_key="success_rate"
            )
        )
        monolithic_eventual.update(
            _world_outcomes(
                data[f"{split}_monolithic"], success_key="success_rate"
            )
        )
        specialist_first.update(
            _world_outcomes(
                data[f"{split}_specialist"],
                success_key="first_pass_success_rate",
            )
        )
        monolithic_first.update(
            _world_outcomes(
                data[f"{split}_monolithic"],
                success_key="first_pass_success_rate",
            )
        )

    quality = data["quality"].get("aggregate", {})
    heldout_quality = data["quality_heldout"].get("aggregate", {})
    selected_quality = {
        key: quality[key]
        for key in (
            "merchant_inventory_pass_rate",
            "premise_items_recall",
            "premise_agents_recall",
            "role_unique_rate",
            "room_visual_canon_adherence",
            "wardrobe_canon_term_coverage",
        )
    }
    quality_worlds: list[dict[str, Any]] = []
    for row in data["quality"].get("worlds", []):
        if not isinstance(row, dict):
            continue
        quality_worlds.append(
            {
                "world_name": row.get("world_name"),
                "specialist": {
                    key: row.get("decomposed", {}).get(key)
                    for key in selected_quality
                },
                "monolithic": {
                    key: row.get("monolithic", {}).get(key)
                    for key in selected_quality
                },
            }
        )
    repair_worlds: list[dict[str, Any]] = []
    for row in data["local_repair"].get("worlds", []):
        if not isinstance(row, dict):
            continue
        measurement = row.get("localized_repair_measurement", {})
        initial_calls = float(measurement.get("full_rebuild_call_counterfactual") or 0)
        repair_calls = float(measurement.get("localized_repair_provider_attempts") or 0)
        initial_tokens = float(measurement.get("initial_tokens") or 0)
        repair_tokens = float(measurement.get("localized_repair_tokens") or 0)
        initial_time = float(measurement.get("initial_provider_elapsed_seconds") or 0)
        repair_time = float(
            measurement.get("localized_repair_provider_elapsed_seconds") or 0
        )
        repair_worlds.append(
            {
                "world_name": row.get("world_name"),
                "call_ratio": repair_calls / initial_calls if initial_calls else 0.0,
                "token_ratio": (
                    repair_tokens / initial_tokens if initial_tokens else 0.0
                ),
                "provider_time_ratio": (
                    repair_time / initial_time if initial_time else 0.0
                ),
            }
        )
    payload = {
        "protocol": {
            "project_name": "Agora",
            "project_vision": "One Sentence, One Executable World",
            "model": "gemini-3-flash-preview",
            "temperature": 0.2,
            "thinking_level": "low",
            "specialist_per_node_output_cap": 8192,
            "monolithic_output_cap": 24576,
            "strict_no_content_fallback": True,
            "primary_worlds": 5,
            "primary_replicates_per_world": 3,
            "heldout_worlds": 5,
            "heldout_replicates_per_world": 1,
            "primary_analysis_unit": "world",
            "all_completed_model_outputs_retained": True,
            "failed_contract_outputs_retained": True,
            "heldout_set_frozen_before_generation": True,
            "quality_evaluator_frozen_before_heldout_generation": True,
        },
        "reliability": {
            "eventual": _paired_sign_test(
                specialist_eventual, monolithic_eventual
            ),
            "first_pass": _paired_sign_test(
                specialist_first, monolithic_first
            ),
        },
        "paired_worlds": [
            *_paired_world_rows(
                data["primary_specialist"],
                data["primary_monolithic"],
                split="primary",
            ),
            *_paired_world_rows(
                data["heldout_specialist"],
                data["heldout_monolithic"],
                split="heldout",
            ),
        ],
        "cost_by_split": {
            "primary": [
                _cost(data["primary_specialist"], treatment="specialist"),
                _cost(data["primary_monolithic"], treatment="monolithic"),
            ],
            "heldout": [
                _cost(data["heldout_specialist"], treatment="specialist"),
                _cost(data["heldout_monolithic"], treatment="monolithic"),
            ],
        },
        "quality_combined_10_worlds": selected_quality,
        "quality_worlds": quality_worlds,
        "wardrobe_heldout_confirmation": heldout_quality.get(
            "wardrobe_canon_term_coverage", {}
        ),
        "localized_repair": {
            key: value
            for key, value in data["local_repair"].items()
            if key != "worlds"
        },
        "localized_repair_worlds": repair_worlds,
        "source_paths": {key: str(path) for key, path in paths.items()},
    }

    out = args.out if args.out.is_absolute() else root / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    md = out.with_suffix(".md")
    eventual = payload["reliability"]["eventual"]
    first = payload["reliability"]["first_pass"]
    repair = payload["localized_repair"]
    md.write_text(
        "\n".join(
            [
                "# Agora Paper Evidence Summary",
                "",
                "All reliability tests use world-level paired outcomes.",
                "",
                "## Reliability",
                "",
                f"- Eventual: specialist {eventual['specialist_successes']}/10; "
                f"monolithic {eventual['monolithic_successes']}/10; "
                f"one-sided exact p={eventual['one_sided_exact_p']}.",
                f"- First pass: specialist {first['specialist_successes']}/10; "
                f"monolithic {first['monolithic_successes']}/10; "
                f"one-sided exact p={first['one_sided_exact_p']}.",
                "",
                "## Localized Repair",
                "",
                f"- Correct recovery: {repair['complete_successes']}/"
                f"{repair['world_count']}.",
                f"- Mean provider-call reduction: "
                f"{100 * repair['mean_provider_call_reduction_vs_full_rebuild']:.1f}%.",
                f"- Mean token reduction: "
                f"{100 * repair['mean_token_reduction_vs_full_rebuild']:.1f}% "
                f"(p={repair['token_reduction_one_sided_sign_test_p']}).",
                "",
                "See the JSON file for costs, quality metrics, and source paths.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
