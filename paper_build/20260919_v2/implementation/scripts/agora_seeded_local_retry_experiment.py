#!/usr/bin/env python3
"""Measure real node-local recovery from an evaluator-seeded roles defect."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agora_ui.world_builder import generation
from scripts.agora_decomposed_controlled_baseline import (
    _configure_controlled_environment,
    _read_jsonl,
    _run_one,
)
from scripts.agora_monolithic_baseline import (
    _load_paper_rows,
    _read_json,
    _safe_array,
    _safe_object,
    _slug,
    _text,
)


def _tokens(rows: list[dict[str, Any]]) -> int:
    total = 0
    for row in rows:
        usage = _safe_object(row.get("usage_metadata"))
        total += int(usage.get("totalTokenCount") or 0)
    return total


def _elapsed(rows: list[dict[str, Any]]) -> float:
    return round(sum(float(row.get("elapsed_seconds") or 0.0) for row in rows), 4)


def _segments(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    first_wardrobe = next(
        (
            index
            for index, row in enumerate(rows)
            if _text(row.get("stage")) == "agent_wardrobe_policy_generation"
            and _text(row.get("status")) == "ok"
        ),
        -1,
    )
    first_hooks = next(
        (
            index
            for index, row in enumerate(rows)
            if index > first_wardrobe
            and _text(row.get("stage")) == "world_creator_generation"
            and _text(row.get("status")) == "ok"
        ),
        -1,
    )
    summary_index = next(
        (
            index
            for index, row in enumerate(rows)
            if index > first_hooks
            and _text(row.get("stage")) == "world_creator_text_generation"
        ),
        len(rows),
    )
    if first_hooks < 0:
        return {
            "initial_observed": rows,
            "initial_nominal": rows,
            "localized_repair": [],
            "summary": [],
        }
    initial_observed = rows[: first_hooks + 1]
    successful_by_stage: dict[str, list[dict[str, Any]]] = {}
    for row in initial_observed:
        if _text(row.get("status")) != "ok":
            continue
        successful_by_stage.setdefault(_text(row.get("stage")), []).append(row)
    nominal_limits = {
        "world_creator_generation": 5,
        "world_visual_canon_generation": 1,
        "main_character_generation": 3,
        "agent_wardrobe_policy_generation": 1,
    }
    initial_nominal_ids = {
        id(row)
        for stage, limit in nominal_limits.items()
        for row in successful_by_stage.get(stage, [])[-limit:]
    }
    return {
        "initial_observed": initial_observed,
        "initial_nominal": [
            row for row in initial_observed if id(row) in initial_nominal_ids
        ],
        "localized_repair": rows[first_hooks + 1 : summary_index],
        "summary": rows[summary_index:],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _augment_result(
    result: dict[str, Any],
    *,
    seeded_fault_fired: bool,
) -> dict[str, Any]:
    telemetry_path = Path(
        _text(_safe_object(result.get("telemetry")).get("path"))
    )
    segments = _segments(_read_jsonl(telemetry_path))
    retry_events = [
        event
        for event in _safe_array(result.get("generation_node_retries"))
        if isinstance(event, dict)
    ]
    seed_event_index = next(
        (
            index
            for index, event in enumerate(retry_events)
            if "evaluator-seeded roles defect"
            in _text(event.get("error")).lower()
        ),
        -1,
    )
    seed_event = (
        retry_events[seed_event_index] if seed_event_index >= 0 else {}
    )
    initial_observed = segments["initial_observed"]
    initial_rows = segments["initial_nominal"]
    repair_rows = segments["localized_repair"]
    result["seeded_fault_fired"] = bool(
        seeded_fault_fired or seed_event_index >= 0
    )
    result["localized_repair_measurement"] = {
        "initial_provider_attempts": len(initial_rows),
        "pre_seed_extra_provider_attempts": max(
            0, len(initial_observed) - len(initial_rows)
        ),
        "pre_seed_retry_event_count": max(0, seed_event_index),
        "localized_repair_provider_attempts": len(repair_rows),
        "full_rebuild_call_counterfactual": len(initial_rows),
        "provider_call_reduction_vs_full_rebuild": (
            round(1.0 - len(repair_rows) / len(initial_rows), 4)
            if initial_rows
            else 0.0
        ),
        "initial_tokens": _tokens(initial_rows),
        "localized_repair_tokens": _tokens(repair_rows),
        "token_reduction_vs_full_rebuild": (
            round(1.0 - _tokens(repair_rows) / _tokens(initial_rows), 4)
            if _tokens(initial_rows)
            else 0.0
        ),
        "initial_provider_elapsed_seconds": _elapsed(initial_rows),
        "localized_repair_provider_elapsed_seconds": _elapsed(repair_rows),
        "repair_stage_attempt_counts": dict(
            sorted(
                Counter(
                    _text(row.get("stage")) for row in repair_rows
                ).items()
            )
        ),
        "failed_node": _text(seed_event.get("failed_node")),
        "invalidated_cache_keys": _safe_array(
            seed_event.get("invalidated_cache_keys")
        ),
        "preserved_cache_keys": _safe_array(
            seed_event.get("preserved_cache_keys")
        ),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        default="docs/benchmark_20260724/seeded_local_retry_20260729",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--model", default="gemini-3-flash-preview")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    _configure_controlled_environment(
        model=str(args.model),
        temperature=0.2,
        thinking_level="low",
        thinking_budget=1024,
        max_output_tokens=8192,
    )

    source_validator = generation._validate_decoupled_generation_contract
    results: list[dict[str, Any]] = []
    try:
        for source_row in _load_paper_rows(REPO_ROOT, args.limit):
            world_name = _text(source_row.get("world_name"))
            seeded_result_path = (
                out_dir / f"{_slug(world_name)}_r01_seeded_retry_result.json"
            )
            if args.resume and seeded_result_path.is_file():
                cached = _read_json(seeded_result_path)
                if cached:
                    print(f"[SEEDED_RETRY_RESUME] world={world_name}", flush=True)
                    cached = _augment_result(
                        cached,
                        seeded_fault_fired=True,
                    )
                    _write_json(seeded_result_path, cached)
                    results.append(cached)
                    continue
            fired = False

            def seeded_validator(
                spec: dict[str, Any],
                *,
                min_rooms: int,
                min_items_catalog: int,
                expected_characters: int,
            ) -> None:
                nonlocal fired
                if not fired:
                    fired = True
                    raise ValueError(
                        "Evaluator-seeded roles defect: character 1 has fewer "
                        "than 8 valid inventory items"
                    )
                source_validator(
                    spec,
                    min_rooms=min_rooms,
                    min_items_catalog=min_items_catalog,
                    expected_characters=expected_characters,
                )

            generation._validate_decoupled_generation_contract = seeded_validator
            result = _run_one(
                package_root=REPO_ROOT,
                out_dir=out_dir,
                row=source_row,
                replicate=1,
                resume=bool(args.resume),
                treatment="decomposed_seeded_roles_fault",
            )
            result = _augment_result(result, seeded_fault_fired=fired)
            _write_json(seeded_result_path, result)
            results.append(result)
    finally:
        generation._validate_decoupled_generation_contract = source_validator

    measurements = [
        _safe_object(result.get("localized_repair_measurement"))
        for result in results
    ]
    token_reduction_worlds = sum(
        int(measurement.get("localized_repair_tokens") or 0)
        < int(measurement.get("initial_tokens") or 0)
        for measurement in measurements
    )
    elapsed_reduction_worlds = sum(
        float(measurement.get("localized_repair_provider_elapsed_seconds") or 0.0)
        < float(measurement.get("initial_provider_elapsed_seconds") or 0.0)
        for measurement in measurements
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fault": "roles inventory contract defect after the first complete node pass",
        "world_count": len(results),
        "complete_successes": sum(
            result.get("complete_success") is True for result in results
        ),
        "correctly_attributed_roles_faults": sum(
            _text(measurement.get("failed_node")) == "contract"
            and set(_safe_array(measurement.get("invalidated_cache_keys")))
            == {"roles", "wardrobe", "hooks"}
            for measurement in measurements
        ),
        "mean_provider_call_reduction_vs_full_rebuild": round(
            statistics.mean(
                float(measurement.get("provider_call_reduction_vs_full_rebuild") or 0.0)
                for measurement in measurements
            ),
            4,
        )
        if measurements
        else 0.0,
        "mean_token_reduction_vs_full_rebuild": round(
            statistics.mean(
                float(measurement.get("token_reduction_vs_full_rebuild") or 0.0)
                for measurement in measurements
            ),
            4,
        )
        if measurements
        else 0.0,
        "mean_localized_repair_provider_elapsed_seconds": round(
            statistics.mean(
                float(
                    measurement.get("localized_repair_provider_elapsed_seconds")
                    or 0.0
                )
                for measurement in measurements
            ),
            4,
        )
        if measurements
        else 0.0,
        "mean_initial_provider_elapsed_seconds": round(
            statistics.mean(
                float(measurement.get("initial_provider_elapsed_seconds") or 0.0)
                for measurement in measurements
            ),
            4,
        )
        if measurements
        else 0.0,
        "median_localized_repair_provider_elapsed_seconds": round(
            statistics.median(
                float(
                    measurement.get("localized_repair_provider_elapsed_seconds")
                    or 0.0
                )
                for measurement in measurements
            ),
            4,
        )
        if measurements
        else 0.0,
        "median_initial_provider_elapsed_seconds": round(
            statistics.median(
                float(measurement.get("initial_provider_elapsed_seconds") or 0.0)
                for measurement in measurements
            ),
            4,
        )
        if measurements
        else 0.0,
        "token_reduction_worlds": token_reduction_worlds,
        "token_reduction_one_sided_sign_test_p": round(
            0.5**token_reduction_worlds
            if token_reduction_worlds == len(measurements)
            else sum(
                math.comb(len(measurements), value)
                for value in range(token_reduction_worlds, len(measurements) + 1)
            )
            / (2 ** len(measurements)),
            6,
        )
        if measurements
        else 1.0,
        "elapsed_reduction_worlds": elapsed_reduction_worlds,
        "elapsed_reduction_one_sided_sign_test_p": round(
            sum(
                math.comb(len(measurements), value)
                for value in range(elapsed_reduction_worlds, len(measurements) + 1)
            )
            / (2 ** len(measurements)),
            6,
        )
        if measurements
        else 1.0,
        "worlds": results,
    }
    _write_json(out_dir / "seeded_local_retry_summary.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
