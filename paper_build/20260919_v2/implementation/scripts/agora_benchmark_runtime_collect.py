#!/usr/bin/env python3
"""Aggregate Agora benchmark runtime batch summaries into paper-ready tables."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
    except Exception:
        pass
    return rows


def _metric(summary: dict[str, Any], endpoint: str, key: str) -> float:
    metric = summary.get("metrics", {}).get(endpoint, {}).get("client_latency_ms", {})
    try:
        return float(metric.get(key, 0.0))
    except Exception:
        return 0.0


def _error_rate(summary: dict[str, Any], endpoint: str) -> float:
    try:
        return float(summary.get("metrics", {}).get(endpoint, {}).get("error_rate", 0.0))
    except Exception:
        return 0.0


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 3)


def _collect_records(result_jsonl: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in _read_jsonl(result_jsonl):
        artifact_dir = Path(str(row.get("artifact_dir", "")))
        summary = _read_json(artifact_dir / "summary.json")
        if not summary:
            continue
        transport = str(summary.get("transport", row.get("transport", ""))).strip()
        records.append(
            {
                "world_name": str(summary.get("world_name", row.get("world_name", ""))).strip(),
                "access_code": str(summary.get("access_code", row.get("access_code", ""))).strip(),
                "transport": transport,
                "users_requested": summary.get("users_requested"),
                "users_created": summary.get("users_created"),
                "duration_seconds": summary.get("duration_seconds"),
                "backend_stress_signal": summary.get("backend_stress_signal"),
                "skip_catalog": summary.get("skip_catalog"),
                "disable_actions": summary.get("disable_actions"),
                "artifact_dir": str(artifact_dir),
                "create_session_p50_ms": _metric(summary, "create_session", "p50"),
                "create_session_p95_ms": _metric(summary, "create_session", "p95"),
                "heartbeat_p50_ms": _metric(summary, "heartbeat", "p50"),
                "heartbeat_p95_ms": _metric(summary, "heartbeat", "p95"),
                "live_state_p50_ms": _metric(summary, "live_state", "p50"),
                "live_state_p95_ms": _metric(summary, "live_state", "p95"),
                "live_action_p50_ms": _metric(summary, "live_action", "p50"),
                "live_action_p95_ms": _metric(summary, "live_action", "p95"),
                "ws_connect_p50_ms": _metric(summary, "ws_connect", "p50"),
                "ws_connect_p95_ms": _metric(summary, "ws_connect", "p95"),
                "ws_move_delta_p50_ms": _metric(summary, "ws_move_delta", "p50"),
                "ws_move_delta_p95_ms": _metric(summary, "ws_move_delta", "p95"),
                "create_session_error_rate": _error_rate(summary, "create_session"),
                "heartbeat_error_rate": _error_rate(summary, "heartbeat"),
                "live_state_error_rate": _error_rate(summary, "live_state"),
                "live_action_error_rate": _error_rate(summary, "live_action"),
                "ws_connect_error_rate": _error_rate(summary, "ws_connect"),
                "ws_move_delta_error_rate": _error_rate(summary, "ws_move_delta"),
            }
        )
    records.sort(key=lambda row: (row["world_name"], row["transport"]))
    return records


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    rest = [row for row in records if row["transport"] == "rest-mixed"]
    ws = [row for row in records if row["transport"] == "ws-movement"]
    return {
        "run_count": len(records),
        "world_count": len({row["access_code"] for row in records}),
        "rest_run_count": len(rest),
        "ws_run_count": len(ws),
        "all_runs_ok_10_users": all(int(row.get("users_created") or 0) == int(row.get("users_requested") or 0) == 10 for row in records),
        "backend_stress_runs": sum(1 for row in records if row.get("backend_stress_signal") is True),
        "rest_live_state_p50_mean_ms": _mean([row["live_state_p50_ms"] for row in rest]),
        "rest_live_state_p95_mean_ms": _mean([row["live_state_p95_ms"] for row in rest]),
        "rest_heartbeat_p50_mean_ms": _mean([row["heartbeat_p50_ms"] for row in rest]),
        "rest_heartbeat_p95_mean_ms": _mean([row["heartbeat_p95_ms"] for row in rest]),
        "rest_live_action_p50_mean_ms": _mean([row["live_action_p50_ms"] for row in rest]),
        "rest_live_action_p95_mean_ms": _mean([row["live_action_p95_ms"] for row in rest]),
        "ws_connect_p50_mean_ms": _mean([row["ws_connect_p50_ms"] for row in ws]),
        "ws_connect_p95_mean_ms": _mean([row["ws_connect_p95_ms"] for row in ws]),
        "ws_move_delta_p50_mean_ms": _mean([row["ws_move_delta_p50_ms"] for row in ws]),
        "ws_move_delta_p95_mean_ms": _mean([row["ws_move_delta_p95_ms"] for row in ws]),
        "max_rest_live_state_p95_ms": round(max([row["live_state_p95_ms"] for row in rest] or [0.0]), 3),
        "max_ws_move_delta_p95_ms": round(max([row["ws_move_delta_p95_ms"] for row in ws] or [0.0]), 3),
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = []
    summary = payload["summary"]
    lines.append("# Agora 10-World Runtime Evaluation")
    lines.append("")
    lines.append(f"Generated: `{payload['generated_at']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key, value in summary.items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## Per-World Runs")
    lines.append("")
    lines.append("| World | Transport | Users | Stress | Create p95 | State p95 | Action p95 | WS move p95 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in payload["records"]:
        users = f"{row['users_created']}/{row['users_requested']}"
        lines.append(
            f"| {row['world_name']} | {row['transport']} | {users} | {row['backend_stress_signal']} | "
            f"{row['create_session_p95_ms']} | {row['live_state_p95_ms']} | "
            f"{row['live_action_p95_ms']} | {row['ws_move_delta_p95_ms']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-jsonl", default="docs/benchmark_20260724/runtime_batch_hotpath_clean1.jsonl")
    parser.add_argument("--out-dir", default="docs/benchmark_20260724")
    args = parser.parse_args()
    result_jsonl = Path(args.result_jsonl).resolve()
    out_dir = Path(args.out_dir).resolve()
    records = _collect_records(result_jsonl)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "result_jsonl": str(result_jsonl),
        "summary": _summary(records),
        "records": records,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "runtime_evaluation_summary.json"
    md_path = out_dir / "runtime_evaluation_summary.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(md_path, payload)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "summary": payload["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
