#!/usr/bin/env python3
"""Extract auditable generation and localized-repair cost evidence."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _generation_record(root: Path, draft_id: str) -> dict[str, Any]:
    revision_dir = (
        root / "output" / "world_creator_drafts" / draft_id / "revisions" / "r001"
    )
    request = _read_json(revision_dir / "generation_request.json")
    status = _read_json(revision_dir / "status.json")
    config = _read_json(revision_dir / "world_config.json")
    log_text = (revision_dir / "generation_worker_launch.log").read_text(
        encoding="utf-8", errors="replace"
    )
    start = _iso(str(request["created_at"]))
    end = _iso(str(status["created_at"]))
    outer_attempts = [
        int(value)
        for value in re.findall(r"Node Generation Attempt (\d+)/\d+", log_text)
    ]
    character_batches = len(re.findall(r"Generating characters batch", log_text))
    named_nodes = len(
        {
            value
            for value in re.findall(
                r"Running (Planner|Visual Canon|Rooms|Materials|Items|Roles|Wardrobe Policy|Hooks)",
                log_text,
            )
        }
    )
    return {
        "draft_id": draft_id,
        "world_name": str(config.get("scenario_meta", {}).get("world_name", draft_id)),
        "wall_seconds": round((end - start).total_seconds(), 3),
        "started_at": request["created_at"],
        "completed_at": status["created_at"],
        "outer_generation_attempts": max(outer_attempts, default=0),
        "named_node_count": named_nodes,
        "character_batch_calls": character_batches,
        "estimated_specialist_model_calls": max(
            0, named_nodes - 1 + character_batches
        ),
        "builder_spec_bytes": (revision_dir / "builder_spec.json").stat().st_size,
    }


def _archive_repair_records(root: Path) -> list[dict[str, Any]]:
    log_path = (
        root
        / "output"
        / "world_creator_drafts"
        / "creator_20260728_002605_dd9ffc0c"
        / "revisions"
        / "r001"
        / "art_worker_launch.log"
    )
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    records: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if '"stdout": ' not in line or "regenerated_room_ids" not in line:
            continue
        encoded = line.split('"stdout": ', 1)[1].strip()
        if encoded.endswith(","):
            encoded = encoded[:-1]
        try:
            stdout = json.loads(encoded)
        except Exception:
            continue
        room_match = re.search(
            r'"regenerated_room_ids"\s*:\s*\[(.*?)\]',
            stdout,
            flags=re.DOTALL,
        )
        if room_match is None:
            continue
        room_ids = re.findall(r'"([^"]+)"', room_match.group(1))
        agent_match = re.search(r'"agents_reused"\s*:\s*(\d+)', stdout)
        duration = None
        for previous in reversed(lines[max(0, index - 6) : index]):
            match = re.search(r'"duration_seconds"\s*:\s*([0-9.]+)', previous)
            if match:
                duration = float(match.group(1))
                break
        if duration is None:
            continue
        records.append(
            {
                "regenerated_room_ids": room_ids,
                "regenerated_room_count": len(room_ids),
                "agents_reused": int(agent_match.group(1)) if agent_match else 0,
                "duration_seconds": round(duration, 3),
            }
        )
    return records


def _summary(
    generation: list[dict[str, Any]],
    baseline: dict[str, Any],
    repair_records: list[dict[str, Any]],
) -> dict[str, Any]:
    generation_seconds = [float(row["wall_seconds"]) for row in generation]
    full_repairs = [
        row for row in repair_records if row["regenerated_room_count"] == 6
    ]
    localized_repairs = [
        row for row in repair_records if 0 < row["regenerated_room_count"] < 6
    ]
    full_duration = (
        statistics.median(row["duration_seconds"] for row in full_repairs)
        if full_repairs
        else 0.0
    )
    local_durations = [row["duration_seconds"] for row in localized_repairs]
    local_median = statistics.median(local_durations) if local_durations else 0.0
    return {
        "decomposed_generation_world_count": len(generation),
        "decomposed_generation_success_count": len(generation),
        "decomposed_generation_wall_seconds_mean": round(
            statistics.mean(generation_seconds), 3
        ),
        "decomposed_generation_wall_seconds_median": round(
            statistics.median(generation_seconds), 3
        ),
        "decomposed_generation_wall_seconds_min": round(min(generation_seconds), 3),
        "decomposed_generation_wall_seconds_max": round(max(generation_seconds), 3),
        "decomposed_outer_retry_count": sum(
            max(0, int(row["outer_generation_attempts"]) - 1)
            for row in generation
        ),
        "monolithic_trials": int(baseline["summary"]["trial_count"]),
        "monolithic_complete_successes": int(
            baseline["summary"]["complete_trial_successes"]
        ),
        "monolithic_complete_success_rate": float(
            baseline["summary"]["complete_trial_success_rate"]
        ),
        "monolithic_complete_wilson_95": baseline["summary"][
            "complete_trial_wilson_95"
        ],
        "monolithic_truncation_failures": int(
            baseline["summary"]["truncation_failure_count"]
        ),
        "monolithic_wall_seconds_mean": float(
            baseline["summary"]["mean_elapsed_seconds"]
        ),
        "monolithic_success_wall_seconds_mean": float(
            baseline["summary"]["mean_success_elapsed_seconds"]
        ),
        "archive_repair_trace_count": len(repair_records),
        "archive_localized_repair_count": len(localized_repairs),
        "archive_full_six_room_repair_count": len(full_repairs),
        "archive_full_six_room_repair_seconds_median": round(full_duration, 3),
        "archive_localized_repair_seconds_median": round(local_median, 3),
        "archive_localized_vs_full_median_reduction": round(
            1.0 - local_median / full_duration, 4
        )
        if full_duration > 0
        else 0.0,
        "archive_agents_reused_min": min(
            (row["agents_reused"] for row in repair_records), default=0
        ),
    }


def _markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Paper Cost and Localized-Repair Evidence",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Text Generation",
        "",
        "| World | Decomposed wall time (s) | Outer attempts | Specialist calls (estimated) |",
        "|---|---:|---:|---:|",
    ]
    for row in payload["decomposed_generation"]:
        lines.append(
            f"| {row['world_name']} | {row['wall_seconds']:.1f} | "
            f"{row['outer_generation_attempts']} | "
            f"{row['estimated_specialist_model_calls']} |"
        )
    lines.extend(
        [
            "",
            f"Decomposed median wall time: **{summary['decomposed_generation_wall_seconds_median']:.1f} s** "
            f"(range {summary['decomposed_generation_wall_seconds_min']:.1f}-"
            f"{summary['decomposed_generation_wall_seconds_max']:.1f} s); "
            f"outer retries: **{summary['decomposed_outer_retry_count']}**.",
            "",
            f"Complete monolithic baseline: **{summary['monolithic_complete_successes']}/"
            f"{summary['monolithic_trials']}**; truncation failures: "
            f"**{summary['monolithic_truncation_failures']}**; mean wall time "
            f"**{summary['monolithic_wall_seconds_mean']:.1f} s**.",
            "",
            "## Observational Local Repair Trace",
            "",
            "| Rooms regenerated | Agents reused | Duration (s) |",
            "|---:|---:|---:|",
        ]
    )
    for row in payload["archive_repair_records"]:
        lines.append(
            f"| {row['regenerated_room_count']} | {row['agents_reused']} | "
            f"{row['duration_seconds']:.3f} |"
        )
    lines.extend(
        [
            "",
            f"Across the archived same-world trace, localized repairs have median duration "
            f"**{summary['archive_localized_repair_seconds_median']:.3f} s** versus "
            f"**{summary['archive_full_six_room_repair_seconds_median']:.3f} s** for the "
            f"six-room repair ({summary['archive_localized_vs_full_median_reduction']:.1%} lower). "
            f"All records reuse at least {summary['archive_agents_reused_min']} agent sprites.",
            "",
            "The repair trace is observational and is not presented as a randomized timing "
            "experiment. It supports the narrower claim that structured localization reduces "
            "repair fan-out while preserving already validated sprites.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path(
            "docs/benchmark_20260724/monolithic_baseline_fair_20260729/"
            "monolithic_baseline_summary.json"
        ),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("docs/benchmark_20260724/paper_cost_analysis_20260729.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/benchmark_20260724/paper_cost_analysis_20260729.md"),
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    baseline_path = args.baseline
    if not baseline_path.is_absolute():
        baseline_path = root / baseline_path
    generation = [_generation_record(root, draft_id) for draft_id in CASES]
    repair_records = _archive_repair_records(root)
    baseline = _read_json(baseline_path)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "generation_time": "generation_request.created_at to draft status.created_at",
            "repair_time": "duration_seconds from archived Archive of Borrowed Gravity art command records",
            "repair_design": "observational_same_world_trace",
            "token_cost_available": False,
            "token_cost_note": "Historical source runs did not persist provider usageMetadata.",
        },
        "summary": _summary(generation, baseline, repair_records),
        "decomposed_generation": generation,
        "archive_repair_records": repair_records,
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
