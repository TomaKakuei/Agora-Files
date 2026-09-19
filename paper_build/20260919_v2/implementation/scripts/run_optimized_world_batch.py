#!/usr/bin/env python3
"""Run the bounded five-point visual-world evaluation cases sequentially."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "docs" / "optimized_worlds_20260728" / "cases.json"
DEFAULT_STATE = ROOT / "docs" / "optimized_worlds_20260728" / "batch_state.json"
DEFAULT_EVENTS = ROOT / "docs" / "optimized_worlds_20260728" / "batch_events.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": _now(), **payload}, ensure_ascii=False) + "\n")


class AgoraApi:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, *, timeout: float = 90.0, **kwargs: Any) -> dict[str, Any]:
        response = None
        for attempt in range(1, 4):
            try:
                response = requests.request(method, f"{self.base_url}{path}", timeout=timeout, **kwargs)
                if response.status_code < 500 or attempt == 3:
                    response.raise_for_status()
                    break
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 3:
                    raise
            time.sleep(float(2 ** (attempt - 1)))
        if response is None:
            raise RuntimeError(f"{method} {path} produced no response")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"{method} {path} returned a non-object payload")
        return payload


def _status(payload: dict[str, Any], nested_key: str) -> str:
    nested = payload.get(nested_key, {})
    nested_status = nested.get("status", "") if isinstance(nested, dict) else ""
    return str(nested_status or payload.get("status", "")).strip()


def _poll(
    api: AgoraApi,
    path: str,
    *,
    nested_key: str,
    ready: set[str],
    failed: set[str],
    timeout_seconds: int,
    interval_seconds: int,
    events_path: Path,
    draft_id: str,
    stage: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    previous = ""
    while time.monotonic() < deadline:
        payload = api.request("GET", path, timeout=60)
        status = _status(payload, nested_key)
        if status != previous:
            _append_event(
                events_path,
                {"draft_id": draft_id, "stage": stage, "status": status},
            )
            print(f"[{_now()}] {draft_id} {stage}: {status}", flush=True)
            previous = status
        if status in ready:
            return payload
        if status in failed:
            raise RuntimeError(f"{stage} failed for {draft_id}: {json.dumps(payload, ensure_ascii=False)}")
        time.sleep(interval_seconds)
    raise TimeoutError(f"{stage} timed out after {timeout_seconds}s for {draft_id}")


def _record_for(state: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    world_name = str(case["world_name"])
    records = state.setdefault("worlds", {})
    record = records.setdefault(
        world_name,
        {
            "world_name": world_name,
            "seed": int(case["seed"]),
            "status": "pending",
            "draft_id": "",
            "revision_id": "",
            "access_code": "",
            "timings_seconds": {},
        },
    )
    return record


def _save_progress(
    *,
    state_path: Path,
    state: dict[str, Any],
    record: dict[str, Any],
    status: str,
) -> None:
    if status != "failed":
        record.pop("error", None)
    record["status"] = status
    record["updated_at"] = _now()
    state["updated_at"] = record["updated_at"]
    _write_json_atomic(state_path, state)


def run_case(
    api: AgoraApi,
    case: dict[str, Any],
    *,
    state: dict[str, Any],
    state_path: Path,
    events_path: Path,
    draft_timeout: int,
    art_timeout: int,
    stop_at_publish_ready: bool,
) -> dict[str, Any]:
    record = _record_for(state, case)
    if str(record.get("status", "")) == "published" and str(record.get("access_code", "")).strip():
        print(f"[{_now()}] {case['world_name']}: already published", flush=True)
        return record

    case_started = time.monotonic()
    draft_id = str(record.get("draft_id", "")).strip()
    if not draft_id:
        started = time.monotonic()
        created = api.request("POST", "/world-builder/drafts", timeout=120, json=case)
        draft_id = str(created.get("draft_id", "")).strip()
        if not draft_id:
            raise RuntimeError(f"create returned no draft_id for {case['world_name']}")
        record["draft_id"] = draft_id
        record["revision_id"] = str(created.get("current_revision", "")).strip()
        record["timings_seconds"]["create_request"] = round(time.monotonic() - started, 3)
        _save_progress(state_path=state_path, state=state, record=record, status="draft_generating")
        _append_event(
            events_path,
            {"world_name": case["world_name"], "draft_id": draft_id, "stage": "created"},
        )

    started = time.monotonic()
    draft = _poll(
        api,
        f"/world-builder/drafts/{draft_id}",
        nested_key="generation",
        ready={"draft_ready", "publish_ready", "published"},
        failed={"draft_failed", "revision_failed"},
        timeout_seconds=draft_timeout,
        interval_seconds=15,
        events_path=events_path,
        draft_id=draft_id,
        stage="draft",
    )
    record["revision_id"] = str(draft.get("current_revision", record.get("revision_id", ""))).strip()
    record["timings_seconds"]["draft_wait"] = round(time.monotonic() - started, 3)
    _save_progress(state_path=state_path, state=state, record=record, status="draft_ready")

    art_status = _status(draft, "art")
    if art_status not in {"publish_ready", "published"}:
        api.request("POST", f"/world-builder/drafts/{draft_id}/art", timeout=90)
    started = time.monotonic()
    art = _poll(
        api,
        f"/world-builder/drafts/{draft_id}/art/status",
        nested_key="art",
        ready={"publish_ready", "published"},
        failed={"art_failed"},
        timeout_seconds=art_timeout,
        interval_seconds=20,
        events_path=events_path,
        draft_id=draft_id,
        stage="art",
    )
    record["timings_seconds"]["art_wait"] = round(time.monotonic() - started, 3)
    art_payload = art.get("art", {}) if isinstance(art.get("art"), dict) else art
    record["art_qa"] = {
        "pixel_read": bool(dict(art_payload.get("qa_summary", {})).get("pixel_read", False)),
        "startup_ok": bool(dict(art_payload.get("startup_validation", {})).get("startup_ok", False)),
        "map_vision_qa": dict(art_payload.get("map_vision_qa", {})),
    }
    _save_progress(state_path=state_path, state=state, record=record, status="publish_ready")
    if stop_at_publish_ready:
        _append_event(
            events_path,
            {
                "world_name": case["world_name"],
                "draft_id": draft_id,
                "stage": "publish_ready",
            },
        )
        return record

    started = time.monotonic()
    published = api.request("POST", f"/world-builder/drafts/{draft_id}/publish", timeout=1200)
    record["timings_seconds"]["publish"] = round(time.monotonic() - started, 3)
    publish_payload = published.get("publish", {}) if isinstance(published.get("publish"), dict) else published
    access_code = str(
        publish_payload.get("access_code")
        or published.get("published_access_code")
        or published.get("access_code")
        or ""
    ).strip()
    if not access_code:
        raise RuntimeError(f"publish returned no access code for {draft_id}: {published}")
    record["access_code"] = access_code
    record["publish"] = {
        "status": str(publish_payload.get("status", "")).strip(),
        "pixel_read": bool(publish_payload.get("pixel_read", False)),
        "startup_ok": bool(
            publish_payload.get("startup_ok")
            or dict(publish_payload.get("startup_validation", {})).get("startup_ok", False)
        ),
    }
    record["timings_seconds"]["total_this_invocation"] = round(time.monotonic() - case_started, 3)
    _save_progress(state_path=state_path, state=state, record=record, status="published")
    _append_event(
        events_path,
        {
            "world_name": case["world_name"],
            "draft_id": draft_id,
            "stage": "published",
            "access_code": access_code,
        },
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8125/api")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--draft-timeout", type=int, default=3600)
    parser.add_argument("--art-timeout", type=int, default=5400)
    parser.add_argument(
        "--stop-at-publish-ready",
        action="store_true",
        help="Run strict generation and art validation without publishing the world.",
    )
    args = parser.parse_args()

    cases = _read_json(args.cases.resolve(), [])
    if not isinstance(cases, list) or not cases:
        raise RuntimeError(f"no cases found in {args.cases}")
    selected = cases[max(0, args.start) : max(0, args.start) + max(0, args.count)]
    state = _read_json(
        args.state.resolve(),
        {
            "schema_version": "agora.optimized_world_batch.v1",
            "created_at": _now(),
            "updated_at": _now(),
            "worlds": {},
        },
    )
    api = AgoraApi(args.base_url)

    for case in selected:
        record = _record_for(state, case)
        try:
            run_case(
                api,
                case,
                state=state,
                state_path=args.state.resolve(),
                events_path=args.events.resolve(),
                draft_timeout=max(300, args.draft_timeout),
                art_timeout=max(600, args.art_timeout),
                stop_at_publish_ready=bool(args.stop_at_publish_ready),
            )
        except Exception as error:
            record["error"] = str(error)
            _save_progress(
                state_path=args.state.resolve(),
                state=state,
                record=record,
                status="failed",
            )
            _append_event(
                args.events.resolve(),
                {
                    "world_name": case.get("world_name", ""),
                    "draft_id": record.get("draft_id", ""),
                    "stage": "failed",
                    "error": str(error),
                },
            )
            raise

    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
