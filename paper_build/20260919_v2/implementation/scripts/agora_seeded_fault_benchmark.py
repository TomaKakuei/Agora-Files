#!/usr/bin/env python3
"""Measure production-validator detection and attribution on seeded defects."""

from __future__ import annotations

import argparse
import copy
import json
import math
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agora_ui.world_builder.art import (  # noqa: E402
    _map_dimension_contract,
    _semantic_component_coverage,
)
from agora_ui.world_pipeline import build_world_pipeline  # noqa: E402
from asset_pipeline.build_live_ready_feed import (  # noqa: E402
    _bundle_provenance_matches,
)
from asset_pipeline.sprite_qa_programmatic import (  # noqa: E402
    final_atlas_transparency_qa,
    strict_programmatic_qa,
)


CASES = (
    "creator_20260727_233333_efa8235f",
    "creator_20260728_002605_dd9ffc0c",
    "creator_20260728_020032_6f7b670a",
    "creator_20260728_220950_e2278e2f",
    "creator_20260728_223205_1924f12f",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Expected JSON object at {path}")
    return payload


def _timed(check: Callable[[], tuple[bool, str, str]]) -> dict[str, Any]:
    started = time.perf_counter()
    passed, code, detail = check()
    return {
        "passed": bool(passed),
        "code": str(code),
        "detail": str(detail)[:500],
        "latency_ms": round((time.perf_counter() - started) * 1000.0, 4),
    }


def _compiler_check(spec: dict[str, Any]) -> tuple[bool, str, str]:
    try:
        result = build_world_pipeline(spec, {})
    except Exception as error:
        detail = str(error)
        folded = detail.casefold()
        if "valid inventory items" in folded:
            code = "agent_inventory_missing"
        elif "property_templates" in folded:
            code = "agent_property_templates_missing"
        elif "knowledge_templates" in folded:
            code = "agent_knowledge_templates_missing"
        elif "rooms_spec.room_definitions" in folded:
            code = "room_definitions_missing"
        elif "agents_spec.role_definitions" in folded:
            code = "agent_definitions_missing"
        else:
            code = "compiler_error_unlocalized"
        return False, code, detail
    report = result.get("compiler_report", {})
    passed = report.get("status") == "ok"
    return passed, "" if passed else "compiler_invalid", json.dumps(
        report.get("errors", []), ensure_ascii=False
    )


def _provenance_check(
    bundle_path: Path,
    *,
    world_id: str,
    world_revision: str,
) -> tuple[bool, str, str]:
    passed, report = _bundle_provenance_matches(
        bundle_path,
        expected_world_id=world_id,
        expected_world_revision=world_revision,
        allow_foreign_revision_fallback=False,
    )
    return passed, "" if passed else str(report.get("reason", "")), json.dumps(
        report, ensure_ascii=False
    )


def _raw_sheet_check(path: Path) -> tuple[bool, str, str]:
    report = strict_programmatic_qa(image_path=str(path))
    if report.get("pass_qa") is True:
        return True, "", ""
    failed_checks = [
        name
        for name, result in report.get("checks", {}).items()
        if isinstance(result, dict) and result.get("pass") is not True
    ]
    code = "raw_sheet_" + ("size_mismatch" if "size" in failed_checks else "qa_failure")
    return False, code, "; ".join(report.get("failures", [])[:4])


def _atlas_check(path: Path) -> tuple[bool, str, str]:
    report = final_atlas_transparency_qa(image_path=str(path))
    passed = report.get("pass") is True
    return passed, "" if passed else "atlas_transparency_failure", "; ".join(
        report.get("failures", [])[:4]
    )


def _map_dimension_check(
    config: dict[str, Any],
    actual_size: tuple[int, int],
) -> tuple[bool, str, str]:
    report = _map_dimension_contract(config, actual_size)
    passed = report["pass"] is True
    return passed, "" if passed else str(report["error_code"]), json.dumps(report)


def _semantic_check(
    config: dict[str, Any],
    sidecar: dict[str, Any],
) -> tuple[bool, str, str]:
    report = _semantic_component_coverage(config, sidecar)
    if report["status"] == "ok":
        return True, "", ""
    if report["missing_component_ids"]:
        code = "semantic_prop_missing"
    elif report["unreadable_component_ids"]:
        code = "semantic_prop_unreadable"
    else:
        code = "semantic_coverage_error"
    return False, code, json.dumps(report, ensure_ascii=False)


def _wilson(successes: int, trials: int) -> list[float]:
    if trials <= 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    center = (proportion + z * z / (2.0 * trials)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / trials
            + z * z / (4.0 * trials * trials)
        )
        / denominator
    )
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


def _record_pair(
    trials: list[dict[str, Any]],
    *,
    world_name: str,
    draft_id: str,
    fault_type: str,
    owner: str,
    expected_code: str,
    clean_check: Callable[[], tuple[bool, str, str]],
    fault_check: Callable[[], tuple[bool, str, str]],
) -> None:
    clean = _timed(clean_check)
    trials.append(
        {
            "world_name": world_name,
            "draft_id": draft_id,
            "fault_type": fault_type,
            "owner": owner,
            "condition": "clean",
            "detected": not clean["passed"],
            "attribution_correct": None,
            "expected_code": "",
            "observed_code": clean["code"],
            "latency_ms": clean["latency_ms"],
            "detail": clean["detail"],
        }
    )
    fault = _timed(fault_check)
    trials.append(
        {
            "world_name": world_name,
            "draft_id": draft_id,
            "fault_type": fault_type,
            "owner": owner,
            "condition": "seeded_fault",
            "detected": not fault["passed"],
            "attribution_correct": (
                not fault["passed"] and fault["code"] == expected_code
            ),
            "expected_code": expected_code,
            "observed_code": fault["code"],
            "latency_ms": fault["latency_ms"],
            "detail": fault["detail"],
        }
    )


def _world_trials(root: Path, draft_id: str, temp_root: Path) -> list[dict[str, Any]]:
    revision_id = "r001"
    world_revision = f"{draft_id}_{revision_id}"
    revision_dir = (
        root / "output" / "world_creator_drafts" / draft_id / "revisions" / revision_id
    )
    builder_spec = _read_json(revision_dir / "builder_spec.json")
    config = _read_json(revision_dir / "world_config.json")
    world_name = str(config.get("scenario_meta", {}).get("world_name", draft_id))
    world_id = str(builder_spec.get("world_id", "")).strip()
    asset_root = (
        root / "frontend" / "assets" / "generated" / "world_asset_sets" / world_revision
    )
    map_path = asset_root / "world_map_source.png"
    sidecar_path = asset_root / "world_map_source.components.json"
    bundles = sorted(
        (root / "frontend" / "assets" / "generated").glob(
            f"*_main_*/{world_revision}/asset_bundle.json"
        )
    )
    if not bundles:
        raise FileNotFoundError(f"No agent asset bundle for {world_revision}")
    bundle_path = bundles[0]
    raw_path = bundle_path.parent / "raw_character_128.png"
    atlas_path = bundle_path.parent / "character_atlas.png"
    trials: list[dict[str, Any]] = []

    compiler_faults = (
        (
            "agent_inventory_removed",
            "agent_inventory",
            "agent_inventory_missing",
            lambda spec: spec["main_characters"][0].__setitem__("inventory", []),
        ),
        (
            "agent_property_templates_removed",
            "agent_property",
            "agent_property_templates_missing",
            lambda spec: spec["main_characters"][0].__setitem__(
                "property_templates", []
            ),
        ),
        (
            "agent_knowledge_templates_removed",
            "agent_knowledge",
            "agent_knowledge_templates_missing",
            lambda spec: spec["main_characters"][0].__setitem__(
                "knowledge_templates", []
            ),
        ),
        (
            "room_definitions_removed",
            "room_ir",
            "room_definitions_missing",
            lambda spec: spec.__setitem__("rooms", []),
        ),
        (
            "agent_definitions_removed",
            "agent_ir",
            "agent_definitions_missing",
            lambda spec: (
                spec.__setitem__("main_characters", []),
                spec.__setitem__("role_groups", []),
            ),
        ),
    )
    for fault_type, owner, expected_code, mutate in compiler_faults:
        faulty_spec = copy.deepcopy(builder_spec)
        mutate(faulty_spec)
        _record_pair(
            trials,
            world_name=world_name,
            draft_id=draft_id,
            fault_type=fault_type,
            owner=owner,
            expected_code=expected_code,
            clean_check=lambda spec=builder_spec: _compiler_check(spec),
            fault_check=lambda spec=faulty_spec: _compiler_check(spec),
        )

    for field, fault_type, expected_code in (
        ("world_id", "asset_world_id_mismatch", "world_id_mismatch"),
        (
            "world_revision",
            "asset_world_revision_mismatch",
            "world_revision_mismatch",
        ),
    ):
        faulty_bundle = _read_json(bundle_path)
        faulty_bundle[field] = f"seeded_wrong_{field}"
        temp_bundle = temp_root / f"{draft_id}_{field}_asset_bundle.json"
        temp_bundle.write_text(
            json.dumps(faulty_bundle, ensure_ascii=False), encoding="utf-8"
        )
        _record_pair(
            trials,
            world_name=world_name,
            draft_id=draft_id,
            fault_type=fault_type,
            owner="asset_provenance",
            expected_code=expected_code,
            clean_check=lambda: _provenance_check(
                bundle_path,
                world_id=world_id,
                world_revision=world_revision,
            ),
            fault_check=lambda path=temp_bundle: _provenance_check(
                path,
                world_id=world_id,
                world_revision=world_revision,
            ),
        )

    with Image.open(raw_path) as source:
        cropped_raw = source.convert("RGBA").crop((0, 0, source.width - 1, source.height))
    faulty_raw_path = temp_root / f"{draft_id}_cropped_raw.png"
    cropped_raw.save(faulty_raw_path)
    _record_pair(
        trials,
        world_name=world_name,
        draft_id=draft_id,
        fault_type="raw_sprite_sheet_cropped",
        owner="sprite_source",
        expected_code="raw_sheet_size_mismatch",
        clean_check=lambda: _raw_sheet_check(raw_path),
        fault_check=lambda: _raw_sheet_check(faulty_raw_path),
    )

    with Image.open(atlas_path) as source:
        faulty_atlas = Image.new("RGBA", source.size, (255, 255, 255, 255))
    faulty_atlas_path = temp_root / f"{draft_id}_opaque_atlas.png"
    faulty_atlas.save(faulty_atlas_path)
    _record_pair(
        trials,
        world_name=world_name,
        draft_id=draft_id,
        fault_type="atlas_opaque_background",
        owner="sprite_atlas",
        expected_code="atlas_transparency_failure",
        clean_check=lambda: _atlas_check(atlas_path),
        fault_check=lambda: _atlas_check(faulty_atlas_path),
    )

    with Image.open(map_path) as map_image:
        actual_size = map_image.size
    faulty_size = (actual_size[0] + 1, actual_size[1])
    _record_pair(
        trials,
        world_name=world_name,
        draft_id=draft_id,
        fault_type="map_dimension_shift",
        owner="map_compositor",
        expected_code="margin_contract_mismatch",
        clean_check=lambda: _map_dimension_check(config, actual_size),
        fault_check=lambda: _map_dimension_check(config, faulty_size),
    )

    if sidecar_path.is_file():
        sidecar = _read_json(sidecar_path)
        clean_coverage = _semantic_component_coverage(config, sidecar)
        placements = [
            entry
            for entry in sidecar.get("placements", [])
            if isinstance(entry, dict)
            and entry.get("semantic_generated") is True
            and entry.get("pasted") is True
            and str(entry.get("component_id", "")).strip()
        ]
        if clean_coverage["status"] == "ok" and placements:
            target_id = str(placements[0]["component_id"]).strip()
            missing_sidecar = copy.deepcopy(sidecar)
            missing_sidecar["placements"] = [
                entry
                for entry in missing_sidecar.get("placements", [])
                if not (
                    isinstance(entry, dict)
                    and str(entry.get("component_id", "")).strip() == target_id
                )
            ]
            _record_pair(
                trials,
                world_name=world_name,
                draft_id=draft_id,
                fault_type="semantic_component_removed",
                owner="component_compositor",
                expected_code="semantic_prop_missing",
                clean_check=lambda: _semantic_check(config, sidecar),
                fault_check=lambda: _semantic_check(config, missing_sidecar),
            )

            unreadable_sidecar = copy.deepcopy(sidecar)
            unreadable_sidecar["schema_version"] = "agora.map_component_placements.v2"
            for placement in unreadable_sidecar.get("placements", []):
                if not isinstance(placement, dict):
                    continue
                if (
                    placement.get("semantic_generated") is True
                    and placement.get("pasted") is True
                ):
                    placement["readability_pass"] = (
                        str(placement.get("component_id", "")).strip() != target_id
                    )
            _record_pair(
                trials,
                world_name=world_name,
                draft_id=draft_id,
                fault_type="semantic_component_unreadable",
                owner="component_compositor",
                expected_code="semantic_prop_unreadable",
                clean_check=lambda: _semantic_check(config, sidecar),
                fault_check=lambda: _semantic_check(config, unreadable_sidecar),
            )
    return trials


def _summarize(trials: list[dict[str, Any]]) -> dict[str, Any]:
    fault_trials = [trial for trial in trials if trial["condition"] == "seeded_fault"]
    clean_trials = [trial for trial in trials if trial["condition"] == "clean"]
    detected = sum(trial["detected"] for trial in fault_trials)
    false_positives = sum(trial["detected"] for trial in clean_trials)
    attributed = sum(trial["attribution_correct"] is True for trial in fault_trials)
    fault_types = sorted({trial["fault_type"] for trial in fault_trials})
    by_fault: list[dict[str, Any]] = []
    for fault_type in fault_types:
        seeded = [trial for trial in fault_trials if trial["fault_type"] == fault_type]
        clean = [trial for trial in clean_trials if trial["fault_type"] == fault_type]
        fault_detected = sum(trial["detected"] for trial in seeded)
        fault_attributed = sum(trial["attribution_correct"] is True for trial in seeded)
        fault_false_positives = sum(trial["detected"] for trial in clean)
        by_fault.append(
            {
                "fault_type": fault_type,
                "owner": seeded[0]["owner"],
                "seeded_trials": len(seeded),
                "detected": fault_detected,
                "detection_rate": round(fault_detected / len(seeded), 4),
                "detection_wilson_95": _wilson(fault_detected, len(seeded)),
                "attribution_correct": fault_attributed,
                "attribution_rate": round(fault_attributed / len(seeded), 4),
                "clean_trials": len(clean),
                "false_positives": fault_false_positives,
                "false_positive_rate": round(
                    fault_false_positives / len(clean), 4
                ),
            }
        )
    latencies = [float(trial["latency_ms"]) for trial in trials]
    return {
        "seeded_trial_count": len(fault_trials),
        "clean_control_count": len(clean_trials),
        "detected_count": detected,
        "detection_rate": round(detected / len(fault_trials), 4),
        "detection_wilson_95": _wilson(detected, len(fault_trials)),
        "attribution_correct_count": attributed,
        "attribution_rate": round(attributed / len(fault_trials), 4),
        "attribution_wilson_95": _wilson(attributed, len(fault_trials)),
        "false_positive_count": false_positives,
        "false_positive_rate": round(false_positives / len(clean_trials), 4),
        "false_positive_wilson_95": _wilson(
            false_positives, len(clean_trials)
        ),
        "validator_latency_ms_mean": round(statistics.mean(latencies), 4),
        "validator_latency_ms_median": round(statistics.median(latencies), 4),
        "validator_latency_ms_max": round(max(latencies), 4),
        "by_fault": by_fault,
    }


def _markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Seeded-Fault Validator Benchmark",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "This benchmark mutates copies of five publish-ready world artifacts and "
        "invokes the same deterministic validators used by the production pipeline. "
        "It performs no LLM or image-generation calls.",
        "",
        "| Seeded defect | Owner | Detected | Attribution | Clean FP |",
        "|---|---|---:|---:|---:|",
    ]
    for row in summary["by_fault"]:
        lines.append(
            f"| {row['fault_type']} | {row['owner']} | "
            f"{row['detected']}/{row['seeded_trials']} | "
            f"{row['attribution_correct']}/{row['seeded_trials']} | "
            f"{row['false_positives']}/{row['clean_trials']} |"
        )
    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            f"- Detection: {summary['detected_count']}/{summary['seeded_trial_count']} "
            f"({summary['detection_rate']:.1%}, Wilson 95% CI "
            f"{summary['detection_wilson_95'][0]:.1%}-"
            f"{summary['detection_wilson_95'][1]:.1%})",
            f"- Correct attribution: {summary['attribution_correct_count']}/"
            f"{summary['seeded_trial_count']} ({summary['attribution_rate']:.1%}, "
            f"Wilson 95% CI {summary['attribution_wilson_95'][0]:.1%}-"
            f"{summary['attribution_wilson_95'][1]:.1%})",
            f"- False positives: {summary['false_positive_count']}/"
            f"{summary['clean_control_count']} ({summary['false_positive_rate']:.1%}, "
            f"Wilson 95% CI {summary['false_positive_wilson_95'][0]:.1%}-"
            f"{summary['false_positive_wilson_95'][1]:.1%})",
            f"- Validator latency: mean {summary['validator_latency_ms_mean']:.2f} ms, "
            f"median {summary['validator_latency_ms_median']:.2f} ms, "
            f"max {summary['validator_latency_ms_max']:.2f} ms",
            "",
            "The four sidecar-enabled worlds are eligible for semantic missing/readability "
            "faults. Archive of Borrowed Gravity predates the sidecar contract and is excluded "
            "only from those two fault categories.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path(
            "docs/benchmark_20260724/seeded_fault_benchmark_20260729.json"
        ),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path(
            "docs/benchmark_20260724/seeded_fault_benchmark_20260729.md"
        ),
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    with tempfile.TemporaryDirectory(prefix="agora_seeded_fault_") as temp_dir:
        temp_root = Path(temp_dir)
        trials = [
            trial
            for draft_id in CASES
            for trial in _world_trials(root, draft_id, temp_root)
        ]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "world_count": len(CASES),
            "draft_ids": list(CASES),
            "artifact_policy": "mutated_copies_only",
            "validator_policy": "production_deterministic_validators",
            "model_calls": 0,
            "paired_clean_controls": True,
        },
        "summary": _summarize(trials),
        "trials": trials,
    }
    output_json = args.output_json
    output_md = args.output_md
    if not output_json.is_absolute():
        output_json = root / output_json
    if not output_md.is_absolute():
        output_md = root / output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    output_md.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote {output_json}")
    print(f"Wrote {output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
