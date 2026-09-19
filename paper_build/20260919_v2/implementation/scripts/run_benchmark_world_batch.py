from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


BASE_URL = "http://127.0.0.1:8125/api"


CASES: list[dict[str, Any]] = [
    {
        "world_name": "Aurora Court of Migrating Cities",
        "genre": "mobile arctic city-state diplomacy, logistics market, civic intrigue",
        "player_count_target": 4,
        "agent_count_target": 25,
        "focus": "economy and trade-heavy world",
        "seed": 26072401,
        "brief": (
            "A chain of walking polar cities crosses an aurora-lit ice shelf, trading heat, route rights, "
            "food cultures, spare legs, weather predictions, and citizenship favors. Build a dense social "
            "simulation around convoy scheduling, fuel debt, inter-city marriages, border inspections, "
            "black-market engine parts, and public ceremonies where each city's reputation can rise or fall."
        ),
    },
    {
        "world_name": "Mycelium Patent Bazaar",
        "genre": "biotech undercity market, fungal infrastructure, intellectual-property conflict",
        "player_count_target": 4,
        "agent_count_target": 25,
        "focus": "economy and trade-heavy world",
        "seed": 26072402,
        "brief": (
            "In a humid undercity grown through engineered mycelium, families and guilds trade living bridges, "
            "spore encryption keys, medicine cultures, repair enzymes, and patent claims. Emphasize contracts, "
            "counterfeit strains, quarantine politics, lab gossip, and visible biological infrastructure."
        ),
    },
    {
        "world_name": "Tidal Embassy of Lost Languages",
        "genre": "floating diplomatic archive, translation economy, ritual trade",
        "player_count_target": 4,
        "agent_count_target": 25,
        "focus": "social conflict and knowledge economy",
        "seed": 26072403,
        "brief": (
            "A floating embassy rises and sinks with the tide while linguists, smugglers, ambassadors, and "
            "memory divers trade endangered languages as political assets. Build loops around translation "
            "rights, ritual protocols, archive access, forged idioms, cultural debts, and diplomatic scandals."
        ),
    },
    {
        "world_name": "Sunken Satellite Monastery",
        "genre": "post-orbital ocean monastery, salvage ethics, signal economy",
        "player_count_target": 4,
        "agent_count_target": 25,
        "focus": "economy and trade-heavy world",
        "seed": 26072404,
        "brief": (
            "A monastery built around a crashed communications satellite sits below a stormy sea dome. Monks, "
            "engineers, pearl brokers, signal pirates, and pilgrims trade bandwidth vows, pressure-suit favors, "
            "relic access, repair labor, and secret transmissions. Make consequences visible and commercially grounded."
        ),
    },
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _request_json(method: str, url: str, *, timeout: int = 60, **kwargs: Any) -> dict[str, Any]:
    response = requests.request(method, url, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response.json()


def _poll_draft(draft_id: str, *, timeout_seconds: int, interval_seconds: int, out_path: Path) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        payload = _request_json("GET", f"{BASE_URL}/world-builder/drafts/{draft_id}", timeout=30)
        status = str(payload.get("status", "")).strip()
        generation = payload.get("generation", {}) if isinstance(payload.get("generation"), dict) else {}
        _write_event(out_path, {"ts": _now(), "draft_id": draft_id, "stage": "draft_poll", "status": status, "generation_status": generation.get("status")})
        if status == "draft_ready" or generation.get("status") == "draft_ready":
            return payload
        if status == "draft_failed" or generation.get("status") == "draft_failed":
            raise RuntimeError(json.dumps(payload, ensure_ascii=False, indent=2))
        time.sleep(interval_seconds)
    raise TimeoutError(f"draft generation timed out for {draft_id}")


def _poll_art(draft_id: str, *, timeout_seconds: int, interval_seconds: int, out_path: Path) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        payload = _request_json("GET", f"{BASE_URL}/world-builder/drafts/{draft_id}/art/status", timeout=30)
        art = payload.get("art", {}) if isinstance(payload.get("art"), dict) else {}
        status = str(art.get("status", "")).strip()
        _write_event(out_path, {"ts": _now(), "draft_id": draft_id, "stage": "art_poll", "status": status})
        if status in {"publish_ready", "published"}:
            return payload
        if status == "art_failed":
            raise RuntimeError(json.dumps(payload, ensure_ascii=False, indent=2))
        time.sleep(interval_seconds)
    raise TimeoutError(f"art pipeline timed out for {draft_id}")


def run_case(case: dict[str, Any], *, out_path: Path, draft_timeout: int, art_timeout: int) -> dict[str, Any]:
    started = time.perf_counter()
    record: dict[str, Any] = {
        "ts": _now(),
        "world_name": case["world_name"],
        "seed": case["seed"],
        "status": "running",
    }
    _write_event(out_path, {**record, "stage": "case_start"})
    draft_started = time.perf_counter()
    draft = _request_json("POST", f"{BASE_URL}/world-builder/drafts", timeout=600, json=case)
    draft_id = str(draft.get("draft_id", "")).strip()
    if not draft_id:
        raise RuntimeError(f"draft creation returned no draft_id: {draft}")
    record["draft_id"] = draft_id
    record["create_post_seconds"] = round(time.perf_counter() - draft_started, 3)
    _write_event(out_path, {**record, "stage": "draft_created"})

    draft_ready_started = time.perf_counter()
    draft_ready = _poll_draft(draft_id, timeout_seconds=draft_timeout, interval_seconds=15, out_path=out_path)
    record["draft_ready_seconds"] = round(time.perf_counter() - draft_ready_started, 3)
    record["world_id"] = draft_ready.get("world_id")

    art_start = time.perf_counter()
    _request_json("POST", f"{BASE_URL}/world-builder/drafts/{draft_id}/art", timeout=60)
    _poll_art(draft_id, timeout_seconds=art_timeout, interval_seconds=15, out_path=out_path)
    record["art_ready_seconds"] = round(time.perf_counter() - art_start, 3)

    publish_start = time.perf_counter()
    published = _request_json("POST", f"{BASE_URL}/world-builder/drafts/{draft_id}/publish", timeout=900)
    publish_payload = published.get("publish", {}) if isinstance(published.get("publish"), dict) else {}
    record["publish_seconds"] = round(time.perf_counter() - publish_start, 3)
    record["access_code"] = str(publish_payload.get("access_code", "")).strip()
    record["pixel_read"] = publish_payload.get("pixel_read")
    record["publish_status"] = publish_payload.get("status")
    record["total_seconds"] = round(time.perf_counter() - started, 3)
    record["status"] = "published" if record["access_code"] else "publish_response_missing_access_code"
    _write_event(out_path, {**record, "stage": "case_done"})
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Agora benchmark worlds through create -> art -> publish.")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=len(CASES))
    parser.add_argument("--out", default="docs/benchmark_20260724/e2e_generation_runs.jsonl")
    parser.add_argument("--draft-timeout", type=int, default=5400)
    parser.add_argument("--art-timeout", type=int, default=5400)
    args = parser.parse_args()

    selected = CASES[args.start : args.start + args.count]
    out_path = Path(args.out)
    results = []
    for case in selected:
        try:
            results.append(run_case(case, out_path=out_path, draft_timeout=args.draft_timeout, art_timeout=args.art_timeout))
        except Exception as error:
            failure = {
                "ts": _now(),
                "world_name": case.get("world_name"),
                "seed": case.get("seed"),
                "stage": "case_failed",
                "status": "failed",
                "error": str(error),
            }
            _write_event(out_path, failure)
            print(json.dumps(failure, ensure_ascii=False, indent=2), flush=True)
            raise
    print(json.dumps({"status": "ok", "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
