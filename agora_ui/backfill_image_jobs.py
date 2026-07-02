#!/usr/bin/env python3
"""Backfill failed still-image jobs for an existing Agora UI run."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .adjudicator_schemas import AgentStateBundleSpec
from .jsonc_utils import dump_json, load_jsonc_path
from .run_interaction_simulation import (
    SCRIPT_DIR,
    VertexSDKImageClient,
    _append_jsonl,
    _publish_frontend_state,
    _rebuild_runtime_memories_from_history,
    _replace_inventory_item_image,
)


def _now_stamp() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _agent_lookup(state: AgentStateBundleSpec) -> dict[str, Any]:
    return {agent.agent_id: agent for agent in state.agents}


def _story_payload(run_dir: Path) -> dict[str, Any]:
    story_path = run_dir / "guild_atwill_mainchars_story.json"
    payload = _load_json(story_path)
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected story payload format: {story_path}")
    return payload


def _next_backfill_attempt(image_jobs: list[dict[str, Any]], source_job_id: str) -> int:
    highest = 0
    for job in image_jobs:
        if str(job.get("backfilled_from_job_id", "")).strip() != source_job_id:
            continue
        try:
            highest = max(highest, int(job.get("backfill_attempt", 0)))
        except Exception:
            continue
    return highest + 1


def _build_backfill_record(
    original: dict[str, Any],
    *,
    all_image_jobs: list[dict[str, Any]],
    stamp: str,
) -> dict[str, Any]:
    source_job_id = str(original.get("job_id", "")).strip()
    attempt = _next_backfill_attempt(all_image_jobs, source_job_id)
    job_id = f"{source_job_id}_backfill_{stamp}_{attempt:02d}"
    record = dict(original)
    record.update(
        {
            "job_id": job_id,
            "status": "pending",
            "image_path": "",
            "image_mime_type": "",
            "error": "",
            "backfilled_from_job_id": source_job_id,
            "backfill_attempt": attempt,
            "backfill_source_status": str(original.get("status", "")),
            "backfill_created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "job_dir": str(Path(str(original.get("job_dir", "")).strip()).with_name(job_id)),
        }
    )
    return record


def _select_jobs(
    image_jobs: list[dict[str, Any]],
    *,
    only_failed: bool,
    job_ids: set[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for job in image_jobs:
        if not isinstance(job, dict):
            continue
        if str(job.get("backfilled_from_job_id", "")).strip():
            continue
        if job_ids and str(job.get("job_id", "")).strip() not in job_ids:
            continue
        if only_failed and str(job.get("status", "")).strip() != "failed":
            continue
        selected.append(job)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Existing replay run directory to patch in place.")
    parser.add_argument("--job-id", action="append", default=[], help="Optional original job_id to backfill.")
    parser.add_argument("--include-nonfailed", action="store_true", help="Allow selecting jobs regardless of original status.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    config_path = run_dir / "run_inputs" / "world_config.json"
    final_state_path = run_dir / "final_agent_profiles.json"
    final_manifest_path = run_dir / "final_manifest.json"
    image_jobs_path = run_dir / "image_jobs.jsonl"
    backfill_log_path = run_dir / "image_jobs_backfill.jsonl"
    backfill_manifest_path = run_dir / "image_backfill_manifest.json"
    scenario_dir = run_dir / "run_inputs" / "scenario"

    config = load_jsonc_path(config_path)
    if not isinstance(config, dict):
        raise ValueError(f"Invalid config payload: {config_path}")
    final_manifest = _load_json(final_manifest_path)
    state = AgentStateBundleSpec.model_validate(_load_json(final_state_path))
    story_payload = _story_payload(run_dir)
    stories = [dict(item) for item in story_payload.get("stories", []) if isinstance(item, dict)]
    extra_world_events = [dict(item) for item in story_payload.get("extra_world_events", []) if isinstance(item, dict)]
    all_image_jobs = _read_jsonl(image_jobs_path)
    selected = _select_jobs(
        all_image_jobs,
        only_failed=not bool(args.include_nonfailed),
        job_ids={str(item).strip() for item in args.job_id if str(item).strip()},
    )

    summary = {
        "run_id": str(final_manifest.get("run_id", run_dir.name)),
        "run_dir": str(run_dir),
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "selected_job_count": len(selected),
        "selected_job_ids": [str(item.get("job_id", "")) for item in selected],
        "dry_run": bool(args.dry_run),
        "results": [],
    }
    if not selected:
        dump_json(backfill_manifest_path, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    image_client = VertexSDKImageClient(config)
    stamp = _now_stamp()
    agent_lookup = _agent_lookup(state)
    appended_records: list[dict[str, Any]] = []

    for original in selected:
        record = _build_backfill_record(original, all_image_jobs=all_image_jobs + appended_records, stamp=stamp)
        prompt = str(record.get("prompt", "")).strip()
        source_image_path = Path(str(record.get("source_image_path", "")).strip()) if str(record.get("source_image_path", "")).strip() else None
        try:
            if args.dry_run:
                record["status"] = "dry_run"
            else:
                generated = image_client.generate_image(
                    prompt=prompt,
                    job_dir=Path(str(record.get("job_dir", "")).strip()),
                    filename_stem="artifact",
                    source_image_path=source_image_path if source_image_path is not None and source_image_path.is_file() else None,
                )
                record.update(generated)
                source_owner_id = str(record.get("source_owner_agent_id", "")).strip()
                source_item_id = str(record.get("source_item_id", "")).strip()
                if str(record.get("status", "")) == "ok" and source_owner_id and source_item_id:
                    source_owner = agent_lookup.get(source_owner_id)
                    if source_owner is not None:
                        _replace_inventory_item_image(
                            source_owner,
                            item_id=source_item_id,
                            image_path=str(record.get("image_path", "")),
                            artifact_label=str(record.get("artifact_label", "")),
                        )
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = str(exc)[:500]
        appended_records.append(record)
        summary["results"].append(
            {
                "source_job_id": str(original.get("job_id", "")),
                "backfill_job_id": str(record.get("job_id", "")),
                "status": str(record.get("status", "")),
                "image_path": str(record.get("image_path", "")),
                "error": str(record.get("error", "")),
            }
        )

    if not args.dry_run:
        for record in appended_records:
            _append_jsonl(image_jobs_path, record)
            _append_jsonl(backfill_log_path, record)
        completed_round = int(final_manifest.get("rounds", 0))
        _rebuild_runtime_memories_from_history(
            state,
            config=config,
            stories=stories,
            image_jobs=all_image_jobs + appended_records,
            extra_world_events=extra_world_events,
            completed_round=completed_round,
        )
        final_state_payload = state.model_dump()
        dump_json(final_state_path, final_state_payload)
        timestep_final_state = run_dir / f"timestep_{completed_round:03d}" / "updated_agent_profiles.json"
        if timestep_final_state.is_file():
            dump_json(timestep_final_state, final_state_payload)
        _publish_frontend_state(
            run_id=str(final_manifest.get("run_id", run_dir.name)),
            run_dir=run_dir,
            config=config,
            scenario_dir=scenario_dir,
            state_payload=final_state_payload,
            status=str(final_manifest.get("status", "ok")),
            round_index=completed_round,
        )

    dump_json(backfill_manifest_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
