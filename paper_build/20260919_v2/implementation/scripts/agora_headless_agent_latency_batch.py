#!/usr/bin/env python3
"""Run headless Pixel UI message-latency probes over selected worlds."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORLDS = [
    ("Clockwork Rain Conservatory", "a0d595161b975dd0"),
    ("Aurora Court of Migrating Cities", "cfa9e1aa1ed06a38"),
    ("Mycelium Patent Bazaar", "995cad4cf9d281d9"),
    ("Tidal Embassy of Lost Languages", "21c6573255c5933f"),
    ("Sunken Satellite Monastery", "82f0356e41af144a"),
]


def _parse_json_from_stdout(stdout: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError(f"no JSON object found in output: {stdout[-1000:]}")


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(float(ordered[0]), 3)
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return round(float(ordered[lower] * (1 - fraction) + ordered[upper] * fraction), 3)


def _metrics(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "mean": 0.0, "median": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
    return {
        "count": len(values),
        "mean": round(float(statistics.mean(values)), 3),
        "median": round(float(statistics.median(values)), 3),
        "p95": _percentile(values, 0.95),
        "min": round(float(min(values)), 3),
        "max": round(float(max(values)), 3),
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# Agora Headless Agent Reply Latency",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "## Summary",
        "",
        f"- `world_count`: {summary['world_count']}",
        f"- `ok_count`: {summary['ok_count']}",
        f"- `error_count`: {summary['error_count']}",
        f"- `agent_reply_ms`: {summary['agent_reply_ms']}",
        f"- `provider_latency_ms`: {summary['provider_latency_ms']}",
        f"- `message_persist_ms`: {summary['message_persist_ms']}",
        "",
        "## Per-World Runs",
        "",
        "| World | Access | Status | Model | Persist ms | Agent Reply ms | Provider ms | Error |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in payload["runs"]:
        lines.append(
            f"| {row['world_name']} | `{row['access_code']}` | {row['status']} | "
            f"{row.get('model', '')} | {row.get('message_persist_ms', '')} | "
            f"{row.get('agent_reply_ms', '')} | {row.get('provider_latency_ms', '')} | "
            f"{row.get('error', '')} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-port", type=int, default=8125)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--snapshot-timeout-seconds", type=int, default=30)
    parser.add_argument("--out-dir", default="docs/benchmark_20260724")
    parser.add_argument("--world", action="append", default=[], help="World in the form Name=access_code. Defaults to strict 5.")
    args = parser.parse_args()

    worlds = DEFAULT_WORLDS
    if args.world:
        worlds = []
        for raw in args.world:
            if "=" not in raw:
                raise SystemExit(f"--world must use Name=access_code: {raw}")
            name, access_code = raw.split("=", 1)
            worlds.append((name.strip(), access_code.strip()))

    out_dir = (ROOT / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    harness = ROOT / "scripts" / "headless_pixel_firefox_regression.py"
    python = Path(sys.executable).resolve()

    for world_name, access_code in worlds:
        command = [
            str(python),
            str(harness),
            "--reuse-server",
            "--port",
            str(args.base_port),
            "--access-code",
            access_code,
            "--timeout-seconds",
            str(args.timeout_seconds),
            "--snapshot-timeout-seconds",
            str(args.snapshot_timeout_seconds),
        ]
        started_at = datetime.now(timezone.utc).isoformat()
        completed = subprocess.run(command, cwd=str(ROOT), text=True, capture_output=True, timeout=args.timeout_seconds + args.snapshot_timeout_seconds + 90)
        row: dict[str, Any] = {
            "world_name": world_name,
            "access_code": access_code,
            "started_at": started_at,
            "returncode": completed.returncode,
        }
        try:
            payload = _parse_json_from_stdout(completed.stdout)
            result = payload.get("result", {}) if isinstance(payload.get("result"), dict) else {}
            persistence = payload.get("ai_persistence", {}) if isinstance(payload.get("ai_persistence"), dict) else {}
            row.update(
                {
                    "status": str(payload.get("status") or result.get("status") or "unknown"),
                    "message_persist_ms": int(result.get("message_persist_ms") or 0),
                    "agent_reply_ms": int(result.get("agent_reply_ms") or 0),
                    "provider_latency_ms": int(persistence.get("latency_ms") or 0),
                    "model": str(persistence.get("model") or ""),
                    "session_id": str(result.get("initial_session_id") or ""),
                    "target_agent_id": str(result.get("target_agent_id") or ""),
                    "unique_message": str(result.get("unique_message") or ""),
                    "screenshot": str(payload.get("screenshot") or ""),
                    "screenshot_warning": str(payload.get("screenshot_warning") or ""),
                }
            )
            if row["status"] != "ok":
                row["error"] = json.dumps(payload, ensure_ascii=False)[:1000]
        except Exception as exc:
            row.update(
                {
                    "status": "error",
                    "error": str(exc),
                    "stdout_tail": completed.stdout[-2000:],
                    "stderr_tail": completed.stderr[-2000:],
                }
            )
        runs.append(row)

    ok_runs = [row for row in runs if row.get("status") == "ok"]
    summary = {
        "world_count": len(runs),
        "ok_count": len(ok_runs),
        "error_count": len(runs) - len(ok_runs),
        "agent_reply_ms": _metrics([float(row.get("agent_reply_ms") or 0) for row in ok_runs]),
        "provider_latency_ms": _metrics([float(row.get("provider_latency_ms") or 0) for row in ok_runs]),
        "message_persist_ms": _metrics([float(row.get("message_persist_ms") or 0) for row in ok_runs]),
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "summary": summary,
        "runs": runs,
    }
    json_path = out_dir / "headless_agent_latency_summary.json"
    md_path = out_dir / "headless_agent_latency_summary.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(md_path, payload)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "summary": summary}, ensure_ascii=False, indent=2))
    return 0 if summary["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
