#!/usr/bin/env python3
"""Run Pixel live runtime load tests for completed benchmark worlds."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_array(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: str) -> str:
    chars: list[str] = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        elif chars and chars[-1] != "_":
            chars.append("_")
    return "".join(chars).strip("_")[:56] or "world"


def _completed_worlds(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = _read_json(manifest_path)
    worlds: list[dict[str, Any]] = []
    for row in _safe_array(manifest.get("drafts")):
        if not isinstance(row, dict) or row.get("complete_for_benchmark") is not True:
            continue
        access_code = _text(row.get("published_access_code") or row.get("export_access_code"))
        if len(access_code) != 16:
            continue
        worlds.append(
            {
                "world_name": _text(row.get("world_name")),
                "draft_id": _text(row.get("draft_id")),
                "access_code": access_code,
            }
        )
    worlds.sort(key=lambda row: (row["world_name"], row["draft_id"]))
    return worlds


def _run_one(
    *,
    world: dict[str, Any],
    transport: str,
    out_root: Path,
    users: int,
    duration_seconds: int,
    base_url: str,
    timeout_seconds: float,
    skip_existing: bool,
    skip_catalog: bool,
    disable_actions: bool,
    run_label: str,
) -> dict[str, Any]:
    access_code = world["access_code"]
    slug = _slug(world["world_name"])
    mode_suffix = "hotpath" if skip_catalog and disable_actions else "fullmix"
    label = _slug(run_label) if run_label else "run"
    artifact_dir = out_root / f"20260725_10world_{label}_{mode_suffix}_{transport}_{slug}_{access_code[:6]}"
    summary_path = artifact_dir / "summary.json"
    if skip_existing and summary_path.is_file():
        summary = _read_json(summary_path)
        return {
            "status": "skipped_existing",
            "world_name": world["world_name"],
            "access_code": access_code,
            "transport": transport,
            "artifact_dir": str(artifact_dir),
            "summary_status": summary.get("status"),
        }

    command = [
        sys.executable,
        str(ROOT / "scripts" / "pixel_live_load_test.py"),
        "--mode",
        "remote",
        "--base-url",
        base_url.rstrip("/"),
        "--access-code",
        access_code,
        "--transport",
        transport,
        "--users",
        str(users),
        "--duration-seconds",
        str(duration_seconds),
        "--timeout-seconds",
        str(timeout_seconds),
        "--world-name",
        world["world_name"],
        "--artifact-dir",
        str(artifact_dir),
    ]
    if skip_catalog:
        command.append("--skip-catalog")
    if disable_actions:
        command.append("--disable-actions")
    started = time.perf_counter()
    result = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, timeout=max(120, duration_seconds + 180))
    elapsed = round(time.perf_counter() - started, 3)
    record = {
        "status": "ok" if result.returncode == 0 else "failed",
        "world_name": world["world_name"],
        "draft_id": world["draft_id"],
        "access_code": access_code,
        "transport": transport,
        "artifact_dir": str(artifact_dir),
        "returncode": result.returncode,
        "elapsed_seconds": elapsed,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }
    if result.returncode != 0:
        return record
    summary = _read_json(summary_path)
    record["summary_status"] = summary.get("status")
    record["users_created"] = summary.get("users_created")
    record["backend_stress_signal"] = summary.get("backend_stress_signal")
    record["metrics"] = summary.get("metrics", {})
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="docs/benchmark_20260724/benchmark_manifest.json")
    parser.add_argument("--out-root", default="export_artifact/live_load_tests")
    parser.add_argument("--base-url", default="http://127.0.0.1:8125")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--transport", choices=("rest-mixed", "ws-movement", "both"), default="both")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--skip-catalog", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--disable-actions", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--run-label", default="")
    parser.add_argument("--result-jsonl", default="docs/benchmark_20260724/runtime_batch_runs.jsonl")
    args = parser.parse_args()

    manifest_path = (ROOT / args.manifest).resolve() if not Path(args.manifest).is_absolute() else Path(args.manifest)
    out_root = (ROOT / args.out_root).resolve() if not Path(args.out_root).is_absolute() else Path(args.out_root)
    result_path = (ROOT / args.result_jsonl).resolve() if not Path(args.result_jsonl).is_absolute() else Path(args.result_jsonl)
    out_root.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)

    worlds = _completed_worlds(manifest_path)
    if args.limit > 0:
        worlds = worlds[: args.limit]
    transports = ["rest-mixed", "ws-movement"] if args.transport == "both" else [args.transport]
    records: list[dict[str, Any]] = []
    with result_path.open("a", encoding="utf-8") as handle:
        for world in worlds:
            for transport in transports:
                record = _run_one(
                    world=world,
                    transport=transport,
                    out_root=out_root,
                    users=max(1, int(args.users)),
                    duration_seconds=max(1, int(args.duration_seconds)),
                    base_url=str(args.base_url),
                    timeout_seconds=float(args.timeout_seconds),
                    skip_existing=bool(args.skip_existing),
                    skip_catalog=bool(args.skip_catalog),
                    disable_actions=bool(args.disable_actions),
                    run_label=str(args.run_label),
                )
                records.append(record)
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                print(json.dumps({k: record.get(k) for k in ("status", "world_name", "transport", "users_created", "backend_stress_signal", "artifact_dir")}, ensure_ascii=False), flush=True)
                if record["status"] == "failed":
                    return 1
    print(json.dumps({"status": "ok", "runs": len(records), "result_jsonl": str(result_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
