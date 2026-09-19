#!/usr/bin/env python3
"""Measure real Pixel UI agent reply latency with a message-only headless browser probe."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from _playwright_firefox import launch_headless_firefox_page


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORLDS = [
    ("Clockwork Rain Conservatory", "a0d595161b975dd0"),
    ("Aurora Court of Migrating Cities", "cfa9e1aa1ed06a38"),
    ("Mycelium Patent Bazaar", "995cad4cf9d281d9"),
    ("Tidal Embassy of Lost Languages", "21c6573255c5933f"),
    ("Sunken Satellite Monastery", "82f0356e41af144a"),
]


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


def _extract_payload(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("payload_json")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _probe_world(
    *,
    page: Any,
    base_url: str,
    world_name: str,
    access_code: str,
    seed: int,
    timeout_ms: int,
) -> dict[str, Any]:
    run_id = f"{int(time.time() * 1000)}"
    url = (
        f"{base_url.rstrip('/')}/pixel/?mode=live"
        f"&seed={seed}"
        f"&pixel_world={quote(access_code)}"
        f"&persist_session=0"
        f"&reset_client_state=1"
        f"&headless_kick=1"
        f"&bundle=message-latency-{run_id}"
    )
    started_wall = datetime.now(timezone.utc).isoformat()
    boot_started = time.perf_counter()
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_selector("[data-live-message-input]", timeout=timeout_ms)
    page.wait_for_selector("[data-live-send-message]", timeout=timeout_ms)
    page.wait_for_function(
        "() => Boolean(window.localStorage.getItem('agora_pixel_live_session_id'))",
        timeout=timeout_ms,
    )
    boot_ready_ms = round((time.perf_counter() - boot_started) * 1000.0, 3)
    session_id = str(page.evaluate("() => window.localStorage.getItem('agora_pixel_live_session_id') || ''")).strip()
    if not session_id:
        movement_text = str(page.locator("#movement-module").inner_text(timeout=5000))
        match = re.search(r"Live session\s+([0-9a-f-]+)", movement_text)
        if match:
            session_id = match.group(1)
    if not session_id:
        raise RuntimeError("could not discover live session id from Pixel UI")

    state_url = f"{base_url.rstrip('/')}/api/pixel/worlds/{quote(access_code)}/live/state"
    before_state = page.evaluate(
        """async ({stateUrl, sessionId}) => {
          const url = new URL(stateUrl);
          url.searchParams.set("session_id", sessionId);
          url.searchParams.set("since", "0");
          url.searchParams.set("t", String(Date.now()));
          const response = await fetch(url.toString(), { cache: "no-store" });
          if (!response.ok) throw new Error(`state fetch failed ${response.status}`);
          return response.json();
        }""",
        {"stateUrl": state_url, "sessionId": session_id},
    )
    baseline_event_id = int(before_state.get("latest_event_id") or 0)
    unique_message = f"message-only latency probe {run_id}"

    send_started = time.perf_counter()
    page.fill("[data-live-message-input]", unique_message)
    page.click("[data-live-send-message]")
    message_persist_ms = 0
    agent_reply_ms = 0
    provider_latency_ms = 0
    model = ""
    response_source = ""
    response_event_id = 0

    deadline = time.perf_counter() + (timeout_ms / 1000.0)
    message_seen = False
    last_state: dict[str, Any] = {}
    while time.perf_counter() < deadline:
        current_state = page.evaluate(
            """async ({stateUrl, sessionId, since}) => {
              const url = new URL(stateUrl);
              url.searchParams.set("session_id", sessionId);
              url.searchParams.set("since", String(since));
              url.searchParams.set("t", String(Date.now()));
              const response = await fetch(url.toString(), { cache: "no-store" });
              if (!response.ok) throw new Error(`state fetch failed ${response.status}`);
              return response.json();
            }""",
            {"stateUrl": state_url, "sessionId": session_id, "since": baseline_event_id},
        )
        last_state = current_state if isinstance(current_state, dict) else {}
        events = last_state.get("events") if isinstance(last_state.get("events"), list) else []
        for event in events:
            event_text = json.dumps(event, ensure_ascii=False)
            if not message_seen and unique_message in event_text:
                message_seen = True
                message_persist_ms = round((time.perf_counter() - send_started) * 1000.0)
            payload = _extract_payload(event)
            completed = (
                int(event.get("event_id") or 0) > baseline_event_id
                and str(payload.get("message_status") or "") == "completed"
                and str(payload.get("response_source") or "") == "ai_studio"
                and (
                    str(event.get("event_type") or "") == "agent_response"
                    or (str(event.get("event_type") or "") == "human_action" and str(event.get("action_text") or "") == unique_message)
                )
            )
            if completed:
                agent_reply_ms = round((time.perf_counter() - send_started) * 1000.0)
                provider_latency_ms = int(payload.get("latency_ms") or 0)
                model = str(payload.get("model") or "")
                response_source = str(payload.get("response_source") or "")
                response_event_id = int(event.get("event_id") or 0)
                return {
                    "world_name": world_name,
                    "access_code": access_code,
                    "status": "ok",
                    "started_at": started_wall,
                    "session_id": session_id,
                    "baseline_event_id": baseline_event_id,
                    "response_event_id": response_event_id,
                    "boot_ready_ms": boot_ready_ms,
                    "message_persist_ms": int(message_persist_ms),
                    "agent_reply_ms": int(agent_reply_ms),
                    "provider_latency_ms": int(provider_latency_ms),
                    "model": model,
                    "response_source": response_source,
                    "unique_message": unique_message,
                }
        time.sleep(0.35)
    raise RuntimeError(
        "timed out waiting for completed AI Studio reply; "
        f"message_seen={message_seen}; latest_event_id={last_state.get('latest_event_id')}"
    )


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# Agora Message-Only Headless Agent Reply Latency",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "This measures a real Pixel UI page in headless Firefox. The probe opens the live world, waits for the message composer, sends one user message, polls live state, and records the first completed AI Studio reply.",
        "",
        "## Summary",
        "",
        f"- `world_count`: {summary['world_count']}",
        f"- `ok_count`: {summary['ok_count']}",
        f"- `error_count`: {summary['error_count']}",
        f"- `boot_ready_ms`: {summary['boot_ready_ms']}",
        f"- `message_persist_ms`: {summary['message_persist_ms']}",
        f"- `agent_reply_ms`: {summary['agent_reply_ms']}",
        f"- `provider_latency_ms`: {summary['provider_latency_ms']}",
        "",
        "## Per-World Runs",
        "",
        "| World | Access | Status | Model | Boot Ready ms | Persist ms | Agent Reply ms | Provider ms | Error |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in payload["runs"]:
        lines.append(
            f"| {row['world_name']} | `{row['access_code']}` | {row['status']} | "
            f"{row.get('model', '')} | {row.get('boot_ready_ms', '')} | "
            f"{row.get('message_persist_ms', '')} | {row.get('agent_reply_ms', '')} | "
            f"{row.get('provider_latency_ms', '')} | {row.get('error', '')} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8125")
    parser.add_argument("--seed", type=int, default=42617)
    parser.add_argument("--timeout-seconds", type=int, default=90)
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

    runs: list[dict[str, Any]] = []
    timeout_ms = int(args.timeout_seconds * 1000)
    with sync_playwright() as playwright:
        for world_name, access_code in worlds:
            try:
                with launch_headless_firefox_page(playwright, viewport={"width": 1440, "height": 1024}) as (_context, page):
                    runs.append(
                        _probe_world(
                            page=page,
                            base_url=args.base_url,
                            world_name=world_name,
                            access_code=access_code,
                            seed=args.seed,
                            timeout_ms=timeout_ms,
                        )
                    )
            except (PlaywrightTimeoutError, Exception) as exc:
                runs.append(
                    {
                        "world_name": world_name,
                        "access_code": access_code,
                        "status": "error",
                        "error": str(exc)[:1400],
                    }
                )

    ok_runs = [row for row in runs if row.get("status") == "ok"]
    summary = {
        "world_count": len(runs),
        "ok_count": len(ok_runs),
        "error_count": len(runs) - len(ok_runs),
        "boot_ready_ms": _metrics([float(row.get("boot_ready_ms") or 0) for row in ok_runs]),
        "message_persist_ms": _metrics([float(row.get("message_persist_ms") or 0) for row in ok_runs]),
        "agent_reply_ms": _metrics([float(row.get("agent_reply_ms") or 0) for row in ok_runs]),
        "provider_latency_ms": _metrics([float(row.get("provider_latency_ms") or 0) for row in ok_runs]),
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "summary": summary,
        "runs": runs,
    }
    out_dir = (ROOT / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "headless_message_latency_summary.json"
    md_path = out_dir / "headless_message_latency_summary.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(md_path, payload)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "summary": summary}, ensure_ascii=False, indent=2))
    return 0 if summary["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
