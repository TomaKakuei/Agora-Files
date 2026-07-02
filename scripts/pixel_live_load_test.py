#!/usr/bin/env python3
"""Drive concurrent Pixel live sessions and summarize backend latency."""

from __future__ import annotations

import asyncio
import argparse
import json
import math
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse, urlunparse


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
DEFAULT_REMOTE_BASE_URL = "https://agora.dell.ing"
DEFAULT_USERS = 20
DEFAULT_HEARTBEAT_SECONDS = 3.5
DEFAULT_ACTION_SECONDS = 4.0
DEFAULT_POLL_INTERVAL_MS = 1200
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_WS_MOVE_SECONDS = 0.18


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _safe_array(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json_loads(value: Any, default: Any) -> Any:
    if not str(value or "").strip():
        return default
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _safe_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _resolve_ws_url(base_url: str, template: str, session_id: str) -> str:
    template_text = str(template or "").strip()
    if not template_text:
        raise RuntimeError("missing live_ws_url_template for websocket load test")
    rendered = template_text.replace("{session_id}", quote(str(session_id).strip()))
    if rendered.startswith(("ws://", "wss://")):
        return rendered
    if rendered.startswith(("http://", "https://")):
        parsed = urlparse(rendered)
    else:
        parsed = urlparse(urljoin(str(base_url).rstrip("/") + "/", rendered.lstrip("/")))
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((ws_scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def build_trace_record(
    *,
    env_name: str,
    session_label: str,
    endpoint: str,
    method: str,
    url: str,
    ok: bool,
    client_latency_ms: float,
    response_bytes: int = 0,
    status_code: int | None = None,
    action_type: str = "",
    server_elapsed_ms: float | None = None,
    latest_event_id_before: int | None = None,
    latest_event_id_after: int | None = None,
    ai_reply_latency_ms: int | None = None,
    response_mode: str = "",
    response_unchanged: bool | None = None,
    error: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "ts": _now_iso(),
        "env_name": env_name,
        "session_label": session_label,
        "endpoint": endpoint,
        "method": method,
        "url": url,
        "ok": bool(ok),
        "status_code": status_code,
        "client_latency_ms": round(float(client_latency_ms), 3),
        "server_elapsed_ms": round(float(server_elapsed_ms), 3) if server_elapsed_ms is not None else None,
        "response_bytes": int(response_bytes),
        "action_type": action_type or "",
        "latest_event_id_before": latest_event_id_before,
        "latest_event_id_after": latest_event_id_after,
        "latest_event_advanced": (
            bool(latest_event_id_after > latest_event_id_before)
            if latest_event_id_before is not None and latest_event_id_after is not None
            else None
        ),
        "ai_reply_latency_ms": ai_reply_latency_ms,
        "response_mode": response_mode or "",
        "response_unchanged": response_unchanged,
        "error": error,
    }
    if isinstance(extra, dict):
        payload.update(extra)
    return payload


def parse_header_args(header_args: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw_header in header_args:
        if ":" not in raw_header:
            raise ValueError(f"invalid header, expected 'Name: value': {raw_header}")
        name, value = raw_header.split(":", 1)
        header_name = str(name).strip()
        if not header_name:
            raise ValueError(f"invalid header name: {raw_header}")
        headers[header_name] = str(value).strip()
    return headers


def choose_world_record(worlds: list[dict[str, Any]], *, access_code: str = "", seed: int | None = None) -> dict[str, Any]:
    if access_code:
        normalized = str(access_code).strip()
        for world in worlds:
            if str(world.get("access_code", "")).strip() == normalized:
                return world
        raise RuntimeError(f"requested access code is not available in /api/pixel/worlds: {normalized}")
    if seed is not None:
        seed_text = str(int(seed))
        matches = [world for world in worlds if str(world.get("seed", "")).strip() == seed_text]
        matches.sort(
            key=lambda world: (
                str(world.get("created_at", "")),
                str(world.get("access_code", "")),
            ),
            reverse=True,
        )
        if matches:
            return matches[0]
        raise RuntimeError(f"no PIXEL READ world matched seed {seed_text}")
    if worlds:
        return worlds[0]
    raise RuntimeError("no PIXEL READ worlds are available")


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0.0, min(1.0, float(q))) * (len(ordered) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    ok_records = [record for record in records if bool(record.get("ok"))]
    metric_names = ("client_latency_ms", "server_elapsed_ms", "response_bytes", "ai_reply_latency_ms")
    summary: dict[str, Any] = {
        "count": total,
        "ok_count": len(ok_records),
        "error_count": total - len(ok_records),
        "error_rate": round((total - len(ok_records)) / total, 6) if total else 0.0,
    }
    for metric_name in metric_names:
        values = [float(record[metric_name]) for record in ok_records if record.get(metric_name) is not None]
        summary[metric_name] = {
            "count": len(values),
            "p50": round(percentile(values, 0.50), 3),
            "p95": round(percentile(values, 0.95), 3),
            "p99": round(percentile(values, 0.99), 3),
            "max": round(max(values), 3) if values else 0.0,
        }
    event_advances = [
        bool(record.get("latest_event_advanced"))
        for record in ok_records
        if record.get("latest_event_advanced") is not None
    ]
    summary["latest_event_advance_rate"] = (
        round(sum(1 for value in event_advances if value) / len(event_advances), 6) if event_advances else 0.0
    )
    status_codes: dict[str, int] = {}
    for record in records:
        code = record.get("status_code")
        if code is None:
            continue
        key = str(code)
        status_codes[key] = status_codes.get(key, 0) + 1
    summary["status_codes"] = status_codes
    return summary


def compare_metric_summaries(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    comparison: dict[str, Any] = {}
    for metric_name in ("client_latency_ms", "server_elapsed_ms", "error_rate"):
        current_metric = current.get(metric_name, {})
        baseline_metric = baseline.get(metric_name, {})
        if metric_name == "error_rate":
            comparison[metric_name] = round(float(current.get("error_rate", 0.0)) - float(baseline.get("error_rate", 0.0)), 6)
            continue
        deltas: dict[str, float] = {}
        for key in ("p50", "p95", "p99", "max"):
            deltas[key] = round(float(current_metric.get(key, 0.0)) - float(baseline_metric.get(key, 0.0)), 3)
        comparison[metric_name] = deltas
    return comparison


def extract_event_ai_latency(events: list[dict[str, Any]]) -> int | None:
    latencies: list[int] = []
    for event in events:
        if str(event.get("event_type", "")).strip() != "agent_response":
            continue
        payload = _json_loads(event.get("payload_json", ""), {})
        if not isinstance(payload, dict):
            continue
        latency_ms = _safe_int(payload.get("latency_ms"), 0)
        if latency_ms > 0:
            latencies.append(latency_ms)
    return max(latencies) if latencies else None


def _other_room_agents(state: dict[str, Any]) -> list[dict[str, Any]]:
    session = state.get("session", {}) if isinstance(state.get("session"), dict) else {}
    claimed_agent_id = str(session.get("claimed_agent_id", "")).strip()
    agents = []
    for agent in _safe_array(state.get("active_room_agents")):
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agent_id", "")).strip()
        if agent_id and agent_id != claimed_agent_id:
            agents.append(agent)
    return agents


def _choose_direction(step_index: int) -> str:
    directions = ("up", "right", "down", "left")
    return directions[int(step_index) % len(directions)]


def _first_connected_room_id(room: dict[str, Any]) -> str:
    for doorway in _safe_array(room.get("doorways")):
        if not isinstance(doorway, dict):
            continue
        candidate = _first_non_empty(doorway.get("target_room_id"), doorway.get("connects_to_room_id"))
        if candidate:
            return candidate
    return ""


def _first_inventory_item(agent: dict[str, Any]) -> str:
    for entry in _safe_array(agent.get("inventory")):
        if not isinstance(entry, dict):
            continue
        item_id = str(entry.get("item_id", "")).strip()
        quantity = _safe_int(entry.get("quantity"), 0)
        if item_id and quantity > 0 and item_id.lower() != "gold":
            return item_id
    return ""


def build_mixed_action(state: dict[str, Any], *, step_index: int) -> dict[str, Any]:
    session = state.get("session", {}) if isinstance(state.get("session"), dict) else {}
    room = state.get("room", {}) if isinstance(state.get("room"), dict) else {}
    session_id = str(session.get("session_id", "")).strip()
    others = _other_room_agents(state)
    target_agent_id = str(others[0].get("agent_id", "")).strip() if others else ""
    route_bucket = step_index % 10

    if route_bucket < 6:
        return {
            "session_id": session_id,
            "action_type": "message",
            "target_agent_id": target_agent_id,
            "action_text": f"load test message {step_index}: report the next useful room step",
        }

    if route_bucket < 9:
        direction = _choose_direction(step_index)
        return {
            "session_id": session_id,
            "action_type": "move",
            "direction": direction,
            "action_text": f"move {direction}",
        }

    if others:
        first_item_id = _first_inventory_item(others[0])
        if first_item_id:
            return {
                "session_id": session_id,
                "action_type": "request_trade_quote",
                "target_agent_id": target_agent_id,
                "item_id": first_item_id,
                "quantity": 1,
                "action_text": f"quote {first_item_id} for load test {step_index}",
            }
        destination_room_id = _first_connected_room_id(room)
        if destination_room_id:
            return {
                "session_id": session_id,
                "action_type": "assign_move_task",
                "target_agent_id": target_agent_id,
                "destination_room_id": destination_room_id,
                "action_text": f"move to {destination_room_id} for load test {step_index}",
            }
        return {
            "session_id": session_id,
            "action_type": "assign_follow_task",
            "target_agent_id": target_agent_id,
            "action_text": f"follow me for load test {step_index}",
        }

    direction = _choose_direction(step_index)
    return {
        "session_id": session_id,
        "action_type": "move",
        "direction": direction,
        "action_text": f"move {direction}",
    }


@dataclass
class RequestResult:
    endpoint: str
    method: str
    url: str
    ok: bool
    status_code: int | None
    client_latency_ms: float
    response_bytes: int
    payload: dict[str, Any] | None
    error: str = ""
    action_type: str = ""


class ApiClient:
    def __init__(self, *, base_url: str, headers: dict[str, str] | None = None, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.headers = dict(headers or {})
        self.headers.setdefault(
            "User-Agent",
            (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36 AgoraPixelLoadTest/1.0"
            ),
        )
        self.headers.setdefault("Accept", "application/json")
        self.timeout_seconds = float(timeout_seconds)

    def request_json(
        self,
        *,
        method: str,
        path: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        action_type: str = "",
    ) -> RequestResult:
        url = path if str(path).startswith(("http://", "https://")) else f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = dict(self.headers)
        if body is not None:
            headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        started_at = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read()
                latency_ms = max(1.0, (time.perf_counter() - started_at) * 1000.0)
                payload_json = json.loads(response_body.decode("utf-8")) if response_body else {}
                return RequestResult(
                    endpoint=endpoint,
                    method=method.upper(),
                    url=url,
                    ok=True,
                    status_code=int(response.status),
                    client_latency_ms=latency_ms,
                    response_bytes=len(response_body),
                    payload=payload_json if isinstance(payload_json, dict) else {"value": payload_json},
                    action_type=action_type,
                )
        except urllib.error.HTTPError as exc:
            response_body = exc.read()
            latency_ms = max(1.0, (time.perf_counter() - started_at) * 1000.0)
            payload_json = _json_loads(response_body.decode("utf-8", errors="replace"), {})
            detail = ""
            if isinstance(payload_json, dict):
                detail = _first_non_empty(payload_json.get("detail"), payload_json.get("status"))
            if not detail:
                detail = response_body.decode("utf-8", errors="replace")[:400]
            return RequestResult(
                endpoint=endpoint,
                method=method.upper(),
                url=url,
                ok=False,
                status_code=int(exc.code),
                client_latency_ms=latency_ms,
                response_bytes=len(response_body),
                payload=payload_json if isinstance(payload_json, dict) else None,
                error=detail or str(exc),
                action_type=action_type,
            )
        except Exception as exc:
            latency_ms = max(1.0, (time.perf_counter() - started_at) * 1000.0)
            return RequestResult(
                endpoint=endpoint,
                method=method.upper(),
                url=url,
                ok=False,
                status_code=None,
                client_latency_ms=latency_ms,
                response_bytes=0,
                payload=None,
                error=str(exc),
                action_type=action_type,
            )


@dataclass
class TraceWriter:
    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def write(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


@dataclass
class SessionRuntime:
    user_index: int
    access_code: str
    session_id: str
    display_name: str
    session_payload: dict[str, Any]
    state_payload: dict[str, Any]
    created_result: RequestResult
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    last_event_id: int = 0
    world_revision: int = 0
    poll_interval_ms: int = DEFAULT_POLL_INTERVAL_MS
    action_step: int = 0

    def __post_init__(self) -> None:
        self.last_event_id = _safe_int(self.state_payload.get("latest_event_id"), 0)
        self.world_revision = _safe_int(self.state_payload.get("world_revision"), 0)
        self.poll_interval_ms = _safe_int(self.state_payload.get("poll_interval_ms"), DEFAULT_POLL_INTERVAL_MS) or DEFAULT_POLL_INTERVAL_MS

    def snapshot(self) -> tuple[int, int, int, dict[str, Any]]:
        with self.lock:
            return self.last_event_id, self.world_revision, self.action_step, json.loads(json.dumps(self.state_payload))

    def advance_action_step(self) -> int:
        with self.lock:
            step_index = self.action_step
            self.action_step += 1
            return step_index

    def apply_state(self, payload: dict[str, Any]) -> None:
        with self.lock:
            if bool(payload.get("unchanged")) and str(payload.get("mode", "")).strip() == "compact":
                merged = json.loads(json.dumps(self.state_payload))
                merged["status"] = payload.get("status", merged.get("status"))
                merged["session"] = json.loads(json.dumps(payload.get("session", merged.get("session", {}))))
                merged["events"] = [event for event in _safe_array(payload.get("events")) if isinstance(event, dict)]
                merged["latest_event_id"] = _safe_int(payload.get("latest_event_id"), self.last_event_id)
                merged["world_revision"] = _safe_int(payload.get("world_revision"), self.world_revision)
                merged["poll_interval_ms"] = _safe_int(payload.get("poll_interval_ms"), self.poll_interval_ms) or self.poll_interval_ms
                merged["mode"] = "compact"
                merged["unchanged"] = True
                self.state_payload = merged
            else:
                self.state_payload = json.loads(json.dumps(payload))
            self.last_event_id = _safe_int(payload.get("latest_event_id"), self.last_event_id)
            self.world_revision = _safe_int(payload.get("world_revision"), self.world_revision)
            next_interval = _safe_int(payload.get("poll_interval_ms"), self.poll_interval_ms)
            if next_interval > 0:
                self.poll_interval_ms = next_interval


def request_result_to_trace(
    result: RequestResult,
    *,
    env_name: str,
    session_label: str,
    latest_event_id_before: int | None = None,
    latest_event_id_after: int | None = None,
    ai_reply_latency_ms: int | None = None,
) -> dict[str, Any]:
    payload = result.payload if isinstance(result.payload, dict) else {}
    timing = payload.get("timing", {}) if isinstance(payload.get("timing"), dict) else {}
    server_elapsed_ms = _safe_float(timing.get("server_elapsed_ms"), 0.0) or None
    return build_trace_record(
        env_name=env_name,
        session_label=session_label,
        endpoint=result.endpoint,
        method=result.method,
        url=result.url,
        ok=result.ok,
        status_code=result.status_code,
        client_latency_ms=result.client_latency_ms,
        response_bytes=result.response_bytes,
        action_type=result.action_type or "",
        server_elapsed_ms=server_elapsed_ms,
        latest_event_id_before=latest_event_id_before,
        latest_event_id_after=latest_event_id_after,
        ai_reply_latency_ms=ai_reply_latency_ms,
        response_mode=str(payload.get("mode", "")).strip(),
        response_unchanged=bool(payload.get("unchanged")) if "unchanged" in payload else None,
        error=result.error,
    )


def _choose_port(preferred_port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if preferred_port > 0:
            try:
                sock.bind(("127.0.0.1", int(preferred_port)))
                return int(preferred_port)
            except OSError:
                pass
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(client: ApiClient, timeout_seconds: float = 45.0) -> None:
    deadline = time.monotonic() + float(timeout_seconds)
    last_error = "server did not respond"
    while time.monotonic() < deadline:
        result = client.request_json(method="GET", path="/api/health", endpoint="health")
        if result.ok and isinstance(result.payload, dict) and result.payload.get("status") == "ok":
            return
        last_error = result.error or f"status={result.status_code}"
        time.sleep(0.5)
    raise RuntimeError(f"server did not become ready: {last_error}")


def _catalog_worlds(client: ApiClient) -> list[dict[str, Any]]:
    result = client.request_json(method="GET", path="/api/pixel/worlds", endpoint="pixel_worlds")
    if not result.ok or not isinstance(result.payload, dict):
        raise RuntimeError(f"failed to load /api/pixel/worlds: {result.error or result.status_code}")
    return [world for world in _safe_array(result.payload.get("worlds")) if isinstance(world, dict)]


def _run_heartbeat_loop(
    session: SessionRuntime,
    *,
    client: ApiClient,
    deadline: float,
    env_name: str,
    trace_writer: TraceWriter,
    stop_event: threading.Event,
    interval_seconds: float,
) -> None:
    next_due = time.monotonic() + float(interval_seconds)
    session_label = f"user_{session.user_index:02d}"
    while not stop_event.is_set() and time.monotonic() < deadline:
        wait_seconds = max(0.0, next_due - time.monotonic())
        if stop_event.wait(wait_seconds):
            return
        result = client.request_json(
            method="POST",
            path=f"/api/pixel/worlds/{session.access_code}/live/sessions/{session.session_id}/heartbeat",
            endpoint="heartbeat",
        )
        latest_before, _, _, _ = session.snapshot()
        latest_after = latest_before
        if result.ok and isinstance(result.payload, dict):
            state_payload = result.payload.get("state", {})
            if isinstance(state_payload, dict):
                latest_after = _safe_int(state_payload.get("latest_event_id"), latest_before)
                session.apply_state(state_payload)
        trace_writer.write(
            request_result_to_trace(
                result,
                env_name=env_name,
                session_label=session_label,
                latest_event_id_before=latest_before,
                latest_event_id_after=latest_after,
            )
        )
        next_due += float(interval_seconds)


def _run_poll_loop(
    session: SessionRuntime,
    *,
    client: ApiClient,
    deadline: float,
    env_name: str,
    trace_writer: TraceWriter,
    stop_event: threading.Event,
) -> None:
    session_label = f"user_{session.user_index:02d}"
    next_due = time.monotonic()
    while not stop_event.is_set() and time.monotonic() < deadline:
        latest_before, world_revision_before, _, _ = session.snapshot()
        wait_seconds = max(0.0, next_due - time.monotonic())
        if stop_event.wait(wait_seconds):
            return
        result = client.request_json(
            method="GET",
            path=(
                f"/api/pixel/worlds/{session.access_code}/live/state"
                f"?session_id={urllib.parse.quote(session.session_id)}"
                f"&since={latest_before}"
                f"&compact=1"
                f"&if_world_revision={world_revision_before}"
            ),
            endpoint="live_state",
        )
        latest_after = latest_before
        ai_reply_latency_ms: int | None = None
        if result.ok and isinstance(result.payload, dict):
            latest_after = _safe_int(result.payload.get("latest_event_id"), latest_before)
            session.apply_state(result.payload)
            ai_reply_latency_ms = extract_event_ai_latency(
                [event for event in _safe_array(result.payload.get("events")) if isinstance(event, dict)]
            )
        trace_writer.write(
            request_result_to_trace(
                result,
                env_name=env_name,
                session_label=session_label,
                latest_event_id_before=latest_before,
                latest_event_id_after=latest_after,
                ai_reply_latency_ms=ai_reply_latency_ms,
            )
        )
        _, _, _, current_state = session.snapshot()
        next_interval_ms = _safe_int(current_state.get("poll_interval_ms"), DEFAULT_POLL_INTERVAL_MS) or DEFAULT_POLL_INTERVAL_MS
        next_due = time.monotonic() + (next_interval_ms / 1000.0)


def _run_action_loop(
    session: SessionRuntime,
    *,
    client: ApiClient,
    deadline: float,
    env_name: str,
    trace_writer: TraceWriter,
    stop_event: threading.Event,
    interval_seconds: float,
) -> None:
    next_due = time.monotonic() + 0.5 + (session.user_index % 5) * 0.08
    session_label = f"user_{session.user_index:02d}"
    while not stop_event.is_set() and time.monotonic() < deadline:
        wait_seconds = max(0.0, next_due - time.monotonic())
        if stop_event.wait(wait_seconds):
            return
        latest_before, _, _, state_snapshot = session.snapshot()
        step_index = session.advance_action_step()
        action = build_mixed_action(state_snapshot, step_index=step_index)
        action_type = str(action.get("action_type", "")).strip()
        result = client.request_json(
            method="POST",
            path=f"/api/pixel/worlds/{session.access_code}/live/actions",
            endpoint="live_action",
            payload=action,
            action_type=action_type,
        )
        latest_after = latest_before
        ai_reply_latency_ms: int | None = None
        if result.ok and isinstance(result.payload, dict):
            state_payload = result.payload.get("state", {})
            if isinstance(state_payload, dict):
                latest_after = _safe_int(state_payload.get("latest_event_id"), latest_before)
                session.apply_state(state_payload)
                ai_reply_latency_ms = extract_event_ai_latency(
                    [event for event in _safe_array(state_payload.get("events")) if isinstance(event, dict)]
                )
        trace_writer.write(
            request_result_to_trace(
                result,
                env_name=env_name,
                session_label=session_label,
                latest_event_id_before=latest_before,
                latest_event_id_after=latest_after,
                ai_reply_latency_ms=ai_reply_latency_ms,
            )
        )
        jitter = ((session.user_index + step_index) % 5) * 0.09
        next_due += float(interval_seconds) + jitter


async def _run_ws_move_session(
    session: SessionRuntime,
    *,
    ws_url: str,
    deadline: float,
    env_name: str,
    trace_writer: TraceWriter,
    move_interval_seconds: float,
    heartbeat_seconds: float,
    timeout_seconds: float,
) -> None:
    import websockets

    session_label = f"user_{session.user_index:02d}"
    connect_started_at = time.perf_counter()
    try:
        async with websockets.connect(
            ws_url,
            open_timeout=float(timeout_seconds),
            close_timeout=min(5.0, float(timeout_seconds)),
            ping_interval=None,
            ping_timeout=None,
            max_queue=None,
        ) as websocket:
            hello_raw = await asyncio.wait_for(websocket.recv(), timeout=float(timeout_seconds))
            hello_latency_ms = max(1.0, (time.perf_counter() - connect_started_at) * 1000.0)
            hello_payload = _safe_object(_json_loads(hello_raw, {}))
            trace_writer.write(
                build_trace_record(
                    env_name=env_name,
                    session_label=session_label,
                    endpoint="ws_connect",
                    method="WS",
                    url=ws_url,
                    ok=str(hello_payload.get("type", "")).strip() == "hello",
                    client_latency_ms=hello_latency_ms,
                    response_bytes=len(str(hello_raw).encode("utf-8")),
                    response_mode="ws",
                    error="" if str(hello_payload.get("type", "")).strip() == "hello" else f"unexpected hello payload: {hello_payload}",
                )
            )
            bootstrap_state = _safe_object(hello_payload.get("state"))
            if bootstrap_state:
                session.apply_state(bootstrap_state)
            claimed_agent_id = _first_non_empty(
                bootstrap_state.get("session", {}).get("claimed_agent_id") if isinstance(bootstrap_state.get("session"), dict) else "",
                session.session_payload.get("claimed_agent_id"),
                session.state_payload.get("session", {}).get("claimed_agent_id") if isinstance(session.state_payload.get("session"), dict) else "",
            )
            realtime = _safe_object(hello_payload.get("realtime"))
            tick_interval_ms = max(25, _safe_int(realtime.get("tick_interval_ms"), 50) or 50)
            next_ping_due = time.monotonic() + max(1.0, float(heartbeat_seconds))
            next_move_due = time.monotonic() + 0.25 + (session.user_index % 5) * 0.04
            next_input_seq = 0
            pending_inputs: dict[int, dict[str, Any]] = {}

            while time.monotonic() < deadline:
                now = time.monotonic()
                while now >= next_move_due:
                    step_index = session.advance_action_step()
                    direction = _choose_direction(step_index)
                    next_input_seq += 1
                    payload = {
                        "type": "input",
                        "direction": direction,
                        "input_seq": next_input_seq,
                        "client_time_ms": int(round(time.time() * 1000.0)),
                    }
                    await websocket.send(json.dumps(payload))
                    pending_inputs[next_input_seq] = {
                        "sent_at": time.perf_counter(),
                        "direction": direction,
                    }
                    jitter = ((session.user_index + step_index) % 5) * 0.01
                    next_move_due += max(0.05, float(move_interval_seconds)) + jitter
                    now = time.monotonic()
                if now >= next_ping_due:
                    await websocket.send(json.dumps({"type": "ping", "client_time_ms": int(round(time.time() * 1000.0))}))
                    next_ping_due = now + max(1.0, float(heartbeat_seconds))

                wait_deadline = min(deadline, next_move_due, next_ping_due)
                timeout = max(0.02, wait_deadline - time.monotonic())
                try:
                    raw_message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    continue
                received_at = time.perf_counter()
                payload = _safe_object(_json_loads(raw_message, {}))
                payload_type = str(payload.get("type", "")).strip()
                if payload_type == "hello":
                    continue
                if payload_type == "error":
                    trace_writer.write(
                        build_trace_record(
                            env_name=env_name,
                            session_label=session_label,
                            endpoint="ws_error",
                            method="WS",
                            url=ws_url,
                            ok=False,
                            client_latency_ms=1.0,
                            response_bytes=len(str(raw_message).encode("utf-8")),
                            response_mode="ws",
                            error=str(payload.get("detail", "")).strip() or str(payload),
                        )
                    )
                    continue
                if payload_type != "state_delta":
                    continue
                for agent_delta in _safe_array(payload.get("agents")):
                    delta = _safe_object(agent_delta)
                    if _first_non_empty(delta.get("agent_id")) != claimed_agent_id:
                        continue
                    input_seq = _safe_int(delta.get("last_input_seq"), 0)
                    pending = pending_inputs.pop(input_seq, None)
                    if pending is None:
                        continue
                    move_latency_ms = max(1.0, (received_at - float(pending["sent_at"])) * 1000.0)
                    session.state_payload["world_revision"] = _safe_int(payload.get("world_revision"), session.world_revision)
                    trace_writer.write(
                        build_trace_record(
                            env_name=env_name,
                            session_label=session_label,
                            endpoint="ws_move_delta",
                            method="WS",
                            url=ws_url,
                            ok=bool(delta.get("accepted", False)),
                            client_latency_ms=move_latency_ms,
                            response_bytes=len(str(raw_message).encode("utf-8")),
                            action_type="move",
                            response_mode="ws",
                            error="" if bool(delta.get("accepted", False)) else "move_rejected",
                            extra={
                                "input_seq": input_seq,
                                "accepted": bool(delta.get("accepted", False)),
                                "tick": _safe_int(payload.get("tick"), 0),
                                "server_time_ms": _safe_int(payload.get("server_time_ms"), 0),
                                "tick_interval_ms": tick_interval_ms,
                            },
                        )
                    )
    except Exception as exc:
        trace_writer.write(
            build_trace_record(
                env_name=env_name,
                session_label=session_label,
                endpoint="ws_connect",
                method="WS",
                url=ws_url,
                ok=False,
                client_latency_ms=max(1.0, (time.perf_counter() - connect_started_at) * 1000.0),
                response_mode="ws",
                error=str(exc),
            )
        )


async def _run_ws_move_transport(
    sessions: list[SessionRuntime],
    *,
    base_url: str,
    ws_template: str,
    deadline: float,
    env_name: str,
    trace_writer: TraceWriter,
    move_interval_seconds: float,
    heartbeat_seconds: float,
    timeout_seconds: float,
) -> None:
    tasks = [
        _run_ws_move_session(
            session,
            ws_url=_resolve_ws_url(base_url, ws_template, session.session_id),
            deadline=deadline,
            env_name=env_name,
            trace_writer=trace_writer,
            move_interval_seconds=move_interval_seconds,
            heartbeat_seconds=heartbeat_seconds,
            timeout_seconds=timeout_seconds,
        )
        for session in sessions
    ]
    await asyncio.gather(*tasks)


def _load_records(trace_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not trace_path.is_file():
        return records
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = _json_loads(line, None)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _release_sessions_parallel(
    sessions: list[SessionRuntime],
    *,
    base_url: str,
    headers: dict[str, str],
    env_name: str,
    trace_writer: TraceWriter,
    timeout_seconds: float,
) -> None:
    release_client = ApiClient(
        base_url=base_url,
        headers=headers,
        timeout_seconds=min(3.0, float(timeout_seconds)),
    )

    def _release_one(session: SessionRuntime) -> None:
        result = release_client.request_json(
            method="DELETE",
            path=f"/api/pixel/worlds/{session.access_code}/live/sessions/{session.session_id}",
            endpoint="release_session",
        )
        trace_writer.write(
            request_result_to_trace(
                result,
                env_name=env_name,
                session_label=f"user_{session.user_index:02d}",
            )
        )

    threads = [
        threading.Thread(target=_release_one, args=(session,), daemon=True)
        for session in sessions
    ]
    for thread in threads:
        thread.start()
    join_deadline = time.monotonic() + max(3.0, min(15.0, float(timeout_seconds)))
    for thread in threads:
        remaining_seconds = max(0.0, join_deadline - time.monotonic())
        if remaining_seconds <= 0:
            break
        thread.join(timeout=remaining_seconds)


def _build_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    def _action_type(record: dict[str, Any]) -> str:
        return str(record.get("action_type", "")).strip()

    groups: dict[str, list[dict[str, Any]]] = {
        "create_session": [record for record in records if record.get("endpoint") == "create_session"],
        "heartbeat": [record for record in records if record.get("endpoint") == "heartbeat"],
        "live_state": [record for record in records if record.get("endpoint") == "live_state"],
        "live_action": [record for record in records if record.get("endpoint") == "live_action"],
        "ws_connect": [record for record in records if record.get("endpoint") == "ws_connect"],
        "ws_move_delta": [record for record in records if record.get("endpoint") == "ws_move_delta"],
        "ws_error": [record for record in records if record.get("endpoint") == "ws_error"],
        "live_action_message": [
            record
            for record in records
            if record.get("endpoint") == "live_action" and _action_type(record) == "message"
        ],
        "live_action_move": [
            record
            for record in records
            if record.get("endpoint") == "live_action" and _action_type(record) == "move"
        ],
        "live_action_interaction": [
            record
            for record in records
            if record.get("endpoint") == "live_action" and _action_type(record) not in {"", "message", "move"}
        ],
        "live_action_non_message": [
            record
            for record in records
            if record.get("endpoint") == "live_action" and _action_type(record) != "message"
        ],
    }
    return {name: summarize_records(group_records) for name, group_records in groups.items()}


def _backend_stress_detected(metrics: dict[str, Any]) -> bool:
    live_state = metrics.get("live_state", {})
    live_action = metrics.get("live_action", {})
    ws_move = metrics.get("ws_move_delta", {})
    return bool(
        float(live_state.get("client_latency_ms", {}).get("p95", 0.0)) >= 1500.0
        or float(live_action.get("client_latency_ms", {}).get("p95", 0.0)) >= 2500.0
        or float(ws_move.get("client_latency_ms", {}).get("p95", 0.0)) >= 250.0
        or float(live_action.get("error_rate", 0.0)) >= 0.05
        or float(live_state.get("error_rate", 0.0)) >= 0.05
        or float(ws_move.get("error_rate", 0.0)) >= 0.05
    )


def _render_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Pixel Live Load Test Summary",
        "",
        f"- Generated at: `{summary['finished_at']}`",
        f"- Environment: `{summary['env_name']}`",
        f"- Transport: `{summary.get('transport', 'rest-mixed')}`",
        f"- Base URL: `{summary['base_url']}`",
        f"- Access code: `{summary['access_code']}`",
        f"- World name: `{summary['world_name']}`",
        f"- Users requested: `{summary['users_requested']}`",
        f"- Users created: `{summary['users_created']}`",
        f"- Duration seconds: `{summary['duration_seconds']}`",
        f"- Backend stress signal: `{summary['backend_stress_signal']}`",
        "",
        "## Endpoint Metrics",
        "",
        "| Endpoint | Count | Error Rate | p50 ms | p95 ms | p99 ms | Max ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for endpoint_name, endpoint_summary in summary.get("metrics", {}).items():
        latency = endpoint_summary.get("client_latency_ms", {})
        lines.append(
            "| "
            + f"{endpoint_name} | {endpoint_summary.get('count', 0)} | {endpoint_summary.get('error_rate', 0.0)}"
            + f" | {latency.get('p50', 0.0)} | {latency.get('p95', 0.0)} | {latency.get('p99', 0.0)} | {latency.get('max', 0.0)} |"
        )
    comparison = summary.get("comparison")
    if isinstance(comparison, dict):
        lines.extend(
            [
                "",
                "## Comparison",
                "",
                f"- Baseline summary: `{comparison.get('baseline_path', '')}`",
            ]
        )
        for endpoint_name, delta in comparison.get("endpoint_deltas", {}).items():
            lines.append(
                f"- `{endpoint_name}` p95 delta: `{delta.get('client_latency_ms', {}).get('p95', 0.0)}` ms, "
                f"error-rate delta: `{delta.get('error_rate', 0.0)}`"
            )
    return "\n".join(lines) + "\n"


def _load_comparison(baseline_path: Path, current_metrics: dict[str, Any]) -> dict[str, Any]:
    baseline_payload = _json_loads(baseline_path.read_text(encoding="utf-8"), {})
    baseline_metrics = baseline_payload.get("metrics", {}) if isinstance(baseline_payload, dict) else {}
    endpoint_deltas: dict[str, Any] = {}
    for endpoint_name, current_summary in current_metrics.items():
        baseline_summary = baseline_metrics.get(endpoint_name, {}) if isinstance(baseline_metrics, dict) else {}
        endpoint_deltas[endpoint_name] = compare_metric_summaries(current_summary, baseline_summary)
    return {
        "baseline_path": str(baseline_path),
        "baseline_env_name": baseline_payload.get("env_name", "") if isinstance(baseline_payload, dict) else "",
        "endpoint_deltas": endpoint_deltas,
    }


def _write_summary_files(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (artifact_dir / "summary.md").write_text(_render_summary_markdown(summary), encoding="utf-8")


def run_load_test(args: argparse.Namespace) -> int:
    env_name = f"{args.mode}_{args.transport}"
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    trace_writer = TraceWriter(artifact_dir / "trace.ndjson")
    started_at_iso = _now_iso()

    server: subprocess.Popen[str] | None = None
    bind_host = str(args.bind or "127.0.0.1").strip() or "127.0.0.1"
    client_host = "127.0.0.1" if bind_host in {"0.0.0.0", "::"} else bind_host
    base_url = str(args.base_url).rstrip("/") if args.mode == "remote" else f"http://{client_host}:{_choose_port(args.port)}"
    request_headers = parse_header_args(args.header)
    try:
        if args.mode == "local":
            actual_port = int(urllib.parse.urlparse(base_url).port or args.port)
            server = subprocess.Popen(
                [
                    str(PYTHON),
                    "-m",
                    "macro_ui.serve_macro_ui",
                    "--bind",
                    bind_host,
                    "--port",
                    str(actual_port),
                    "--directory",
                    str(ROOT),
                ],
                cwd=str(ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        client = ApiClient(base_url=base_url, headers=request_headers, timeout_seconds=args.timeout_seconds)
        if args.mode == "local":
            _wait_for_server(client)

        worlds = _catalog_worlds(client)
        world = choose_world_record(worlds, access_code=args.access_code, seed=args.seed)
        access_code = str(world.get("access_code", "")).strip()
        if len(access_code) != 16:
            raise RuntimeError(f"selected world returned an invalid access code: {access_code}")

        sessions: list[SessionRuntime] = []
        for user_index in range(int(args.users)):
            create_payload = {
                "display_name": f"Load Tester {user_index + 1:02d}",
                "room_id": "",
                "speed_seconds_per_round": float(args.speed_seconds_per_round),
            }
            result = client.request_json(
                method="POST",
                path=f"/api/pixel/worlds/{access_code}/live/sessions",
                endpoint="create_session",
                payload=create_payload,
            )
            trace_payload = request_result_to_trace(
                result,
                env_name=env_name,
                session_label=f"user_{user_index:02d}",
                latest_event_id_before=None,
                latest_event_id_after=(
                    _safe_int((result.payload or {}).get("state", {}).get("latest_event_id"), 0)
                    if isinstance(result.payload, dict)
                    else None
                ),
            )
            trace_writer.write(trace_payload)
            if not result.ok or not isinstance(result.payload, dict):
                continue
            session_payload = result.payload.get("session", {})
            state_payload = result.payload.get("state", {})
            if not isinstance(session_payload, dict) or not isinstance(state_payload, dict):
                continue
            session_id = str(session_payload.get("session_id", "")).strip()
            if not session_id:
                continue
            sessions.append(
                SessionRuntime(
                    user_index=user_index,
                    access_code=access_code,
                    session_id=session_id,
                    display_name=str(create_payload["display_name"]),
                    session_payload=session_payload,
                    state_payload=state_payload,
                    created_result=result,
                )
            )

        if len(sessions) < int(args.users):
            print(
                json.dumps(
                    {
                        "status": "warning",
                        "requested_users": int(args.users),
                        "created_users": len(sessions),
                        "message": "not all sessions were created; proceeding with the sessions that succeeded",
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
        if not sessions:
            raise RuntimeError("no live sessions were created; aborting load test")

        deadline = time.monotonic() + float(args.duration_seconds)
        if str(args.transport) == "ws-movement":
            ws_template = _first_non_empty(
                world.get("live_ws_url_template"),
                f"/api/pixel/worlds/{access_code}/live/ws/{{session_id}}",
            )
            asyncio.run(
                _run_ws_move_transport(
                    sessions,
                    base_url=base_url,
                    ws_template=ws_template,
                    deadline=deadline,
                    env_name=env_name,
                    trace_writer=trace_writer,
                    move_interval_seconds=float(args.ws_move_seconds),
                    heartbeat_seconds=float(args.heartbeat_seconds),
                    timeout_seconds=float(args.timeout_seconds),
                )
            )
        else:
            stop_event = threading.Event()
            threads: list[threading.Thread] = []
            for session in sessions:
                threads.extend(
                    [
                        threading.Thread(
                            target=_run_heartbeat_loop,
                            kwargs={
                                "session": session,
                                "client": client,
                                "deadline": deadline,
                                "env_name": env_name,
                                "trace_writer": trace_writer,
                                "stop_event": stop_event,
                                "interval_seconds": float(args.heartbeat_seconds),
                            },
                            daemon=True,
                        ),
                        threading.Thread(
                            target=_run_poll_loop,
                            kwargs={
                                "session": session,
                                "client": client,
                                "deadline": deadline,
                                "env_name": env_name,
                                "trace_writer": trace_writer,
                                "stop_event": stop_event,
                            },
                            daemon=True,
                        ),
                        threading.Thread(
                            target=_run_action_loop,
                            kwargs={
                                "session": session,
                                "client": client,
                                "deadline": deadline,
                                "env_name": env_name,
                                "trace_writer": trace_writer,
                                "stop_event": stop_event,
                                "interval_seconds": float(args.action_seconds),
                            },
                            daemon=True,
                        ),
                    ]
                )
            for thread in threads:
                thread.start()
            remaining_run_seconds = max(0.0, deadline - time.monotonic())
            if remaining_run_seconds > 0:
                stop_event.wait(remaining_run_seconds)
            stop_event.set()
            join_deadline = time.monotonic() + 10.0
            for thread in threads:
                remaining_join_seconds = max(0.0, join_deadline - time.monotonic())
                if remaining_join_seconds <= 0:
                    break
                thread.join(timeout=remaining_join_seconds)

        _release_sessions_parallel(
            sessions,
            base_url=base_url,
            headers=request_headers,
            env_name=env_name,
            trace_writer=trace_writer,
            timeout_seconds=float(args.timeout_seconds),
        )

        records = _load_records(trace_writer.path)
        metrics = _build_metrics(records)
        summary: dict[str, Any] = {
            "status": "ok",
            "env_name": env_name,
            "base_url": base_url,
            "started_at": started_at_iso,
            "finished_at": _now_iso(),
            "artifact_dir": str(artifact_dir),
            "trace_path": str(trace_writer.path),
            "access_code": access_code,
            "world_name": str(world.get("world_name", "")),
            "seed": world.get("seed"),
            "users_requested": int(args.users),
            "users_created": len(sessions),
            "duration_seconds": int(args.duration_seconds),
            "transport": str(args.transport),
            "speed_seconds_per_round": float(args.speed_seconds_per_round),
            "heartbeat_seconds": float(args.heartbeat_seconds),
            "action_seconds": float(args.action_seconds),
            "ws_move_seconds": float(args.ws_move_seconds),
            "timeout_seconds": float(args.timeout_seconds),
            "metrics": metrics,
            "backend_stress_signal": _backend_stress_detected(metrics),
            "session_ids": [session.session_id for session in sessions],
            "world_catalog_count": len(worlds),
        }
        if args.compare_summary:
            summary["comparison"] = _load_comparison(Path(args.compare_summary), metrics)
        _write_summary_files(artifact_dir=artifact_dir, summary=summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except Exception:
                server.kill()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "remote"), default="local")
    parser.add_argument("--transport", choices=("rest-mixed", "ws-movement"), default="rest-mixed")
    parser.add_argument("--base-url", default=DEFAULT_REMOTE_BASE_URL)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8125)
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--duration-seconds", type=int, default=300)
    parser.add_argument("--heartbeat-seconds", type=float, default=DEFAULT_HEARTBEAT_SECONDS)
    parser.add_argument("--action-seconds", type=float, default=DEFAULT_ACTION_SECONDS)
    parser.add_argument("--ws-move-seconds", type=float, default=DEFAULT_WS_MOVE_SECONDS)
    parser.add_argument("--speed-seconds-per-round", type=float, default=8.0)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--access-code", default="")
    parser.add_argument("--header", action="append", default=[], help="repeatable HTTP header in 'Name: value' form")
    parser.add_argument("--compare-summary", default="")
    parser.add_argument("--artifact-dir", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == "remote" and not str(args.base_url).strip():
        args.base_url = DEFAULT_REMOTE_BASE_URL
    if not str(args.artifact_dir).strip():
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        args.artifact_dir = str(ROOT / "export_artifact" / "live_load_tests" / f"{timestamp}_{args.mode}")
    raise SystemExit(run_load_test(args))


if __name__ == "__main__":
    main()
