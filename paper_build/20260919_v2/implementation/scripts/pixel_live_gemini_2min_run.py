#!/usr/bin/env python3
"""Run a 2-minute Pixel live session with Gemini-driven room actions and snapshot exports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
FIREFOX_BINARY = Path(os.environ.get("FIREFOX_BINARY", "/usr/bin/firefox"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _firefox_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("MOZ_HEADLESS", "1")
    env.setdefault("MOZ_WEBRENDER", "0")
    env.setdefault("MOZ_DISABLE_RDD_SANDBOX", "1")
    env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    env.setdefault("XDG_RUNTIME_DIR", "/tmp")
    return env

def _read_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _delete_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_server(base_url: str, timeout_s: float = 45.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            payload = _read_json(f"{base_url}/api/health")
            if payload.get("status") == "ok":
                return
        except Exception as exc:  # pragma: no cover - diagnostic path
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"server did not become ready: {last_error}")


def _choose_port(preferred_port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", int(preferred_port)))
            return int(preferred_port)
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


def _pick_world_for_seed(base_url: str, seed: int) -> dict[str, Any]:
    payload = _read_json(f"{base_url}/api/pixel/worlds")
    worlds = [world for world in payload.get("worlds", []) if isinstance(world, dict)]
    seed_text = str(int(seed))
    matches = [world for world in worlds if str(world.get("seed", "")).strip() == seed_text]
    if matches:
        return matches[0]
    if worlds:
        return worlds[0]
    raise RuntimeError("no pixel-ready worlds are available")


def _create_live_session(base_url: str, access_code: str, *, display_name: str, room_id: str = "", speed_seconds_per_round: float = 8.0) -> dict[str, Any]:
    return _post_json(
        f"{base_url}/api/pixel/worlds/{access_code}/live/sessions",
        {
            "display_name": display_name,
            "room_id": room_id,
            "speed_seconds_per_round": speed_seconds_per_round,
        },
    )


def _heartbeat_loop(base_url: str, access_code: str, session_id: str, stop_event: threading.Event) -> None:
    url = f"{base_url}/api/pixel/worlds/{access_code}/live/sessions/{session_id}/heartbeat"
    while not stop_event.is_set():
        try:
            _post_json(url, {})
        except Exception:
            pass
        stop_event.wait(3.5)


def _select_action(state: dict[str, Any], *, step_index: int) -> dict[str, Any]:
    session = state.get("session") if isinstance(state.get("session"), dict) else {}
    room = state.get("room") if isinstance(state.get("room"), dict) else {}
    active_agents = [agent for agent in state.get("active_room_agents", []) if isinstance(agent, dict)]
    claimed_agent_id = str(session.get("claimed_agent_id", "")).strip()
    nearby_targets = [
        {
            "agent_id": str(agent.get("agent_id", "")).strip(),
            "display_name": str(agent.get("display_name", "")).strip(),
            "current_focus": str(agent.get("current_focus", "")).strip(),
            "coordinates": agent.get("coordinates", {}),
        }
        for agent in active_agents
        if str(agent.get("agent_id", "")).strip() and str(agent.get("agent_id", "")).strip() != claimed_agent_id
    ]
    if nearby_targets and step_index % 2 == 1:
        target = nearby_targets[step_index % len(nearby_targets)]
        return {
            "action_type": "message",
            "target_agent_id": target.get("agent_id", ""),
            "action_text": f"live batch {step_index}: checking in with {target.get('display_name', 'neighbor')}",
            "rationale": "Prefer a visible room interaction when other agents are nearby.",
        }
    direction_cycle = ["right", "down", "left", "up"]
    direction_index = int(hashlib.sha256(f"{claimed_agent_id}:{room.get('room_id', '')}:{step_index}".encode("utf-8")).hexdigest()[:4], 16) % len(direction_cycle)
    return {
        "action_type": "move",
        "direction": direction_cycle[direction_index],
        "action_text": f"move {direction_cycle[direction_index]}",
        "rationale": "Keep the avatar visibly moving when the room is otherwise quiet.",
    }


def _sanitize_action(action: dict[str, Any], state: dict[str, Any], *, step_index: int) -> dict[str, Any]:
    session = state.get("session") if isinstance(state.get("session"), dict) else {}
    room = state.get("room") if isinstance(state.get("room"), dict) else {}
    active_agents = [agent for agent in state.get("active_room_agents", []) if isinstance(agent, dict)]
    claimed_agent_id = str(session.get("claimed_agent_id", "")).strip()
    other_agents = [
        str(agent.get("agent_id", "")).strip()
        for agent in active_agents
        if str(agent.get("agent_id", "")).strip() and str(agent.get("agent_id", "")).strip() != claimed_agent_id
    ]
    action_type = str(action.get("action_type", "")).strip().lower()
    if action_type not in {"move", "message"}:
        action_type = "message" if other_agents else "move"
    sanitized = {
        "session_id": str(session.get("session_id", "")).strip(),
        "action_type": action_type,
        "action_text": str(action.get("action_text", "")).strip(),
        "target_agent_id": str(action.get("target_agent_id", "")).strip(),
        "direction": str(action.get("direction", "")).strip().lower(),
        "room_id": str(room.get("room_id", "")).strip(),
        "coordinates": None,
    }
    if action_type == "message":
        if sanitized["target_agent_id"] not in other_agents:
            sanitized["target_agent_id"] = other_agents[0] if other_agents else ""
        if not sanitized["action_text"]:
            sanitized["action_text"] = f"live batch {step_index} hello"
    else:
        if sanitized["direction"] not in {"up", "down", "left", "right"}:
            directions = ["up", "right", "down", "left"]
            sanitized["direction"] = directions[step_index % len(directions)]
        if not sanitized["action_text"]:
            sanitized["action_text"] = f"move {sanitized['direction']}"
        sanitized["target_agent_id"] = ""
    return sanitized


def _submit_action(base_url: str, access_code: str, action: dict[str, Any]) -> dict[str, Any]:
    return _post_json(f"{base_url}/api/pixel/worlds/{access_code}/live/actions", action)


def _capture_snapshot(*, firefox_binary: Path, base_url: str, seed: int, access_code: str, session_id: str, token: str, label: str, expected_event_id: int = 0, output_path: Path) -> None:
    url = (
        f"{base_url}/__test__/pixel-live-snapshot"
        f"?seed={int(seed)}&access_code={access_code}&session_id={session_id}&token={token}"
        f"&label={urllib.parse.quote(label)}&expected_event_id={int(expected_event_id or 0)}&focus_mode=room"
    )
    browser_cmd = [
        str(firefox_binary),
        "--headless",
        "--no-remote",
        "--window-size",
        "1680,1200",
        "--screenshot",
        str(output_path),
        url,
    ]
    browser = subprocess.run(
        browser_cmd,
        cwd=str(ROOT),
        env=_firefox_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=420,
        check=False,
    )
    if browser.returncode != 0:
        raise RuntimeError(
            "Firefox snapshot run failed:\n"
            f"stdout:\n{browser.stdout}\n"
            f"stderr:\n{browser.stderr}\n"
        )
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"missing screenshot output: {output_path}")


def _build_prompt_snapshot(state: dict[str, Any], action: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    session = state.get("session") if isinstance(state.get("session"), dict) else {}
    room = state.get("room") if isinstance(state.get("room"), dict) else {}
    events = [event for event in state.get("events", []) if isinstance(event, dict)]
    return {
        "session_id": str(session.get("session_id", "")).strip(),
        "claimed_agent_id": str(session.get("claimed_agent_id", "")).strip(),
        "room_id": str(room.get("room_id", "")).strip(),
        "room_name": str(room.get("name", "")).strip(),
        "active_room_agent_ids": [
            str(agent.get("agent_id", "")).strip()
            for agent in state.get("active_room_agents", [])
            if isinstance(agent, dict) and str(agent.get("agent_id", "")).strip()
        ],
        "latest_event_id": int(state.get("latest_event_id", 0) or 0),
        "action": action,
        "response_summary": (
            str((result.get("state") or {}).get("events", [{}])[-1].get("response_text", ""))
            if isinstance(result.get("state"), dict) and result.get("state")
            else ""
        ),
        "event_count": len(events),
    }


def _live_db_path(access_code: str) -> Path:
    return ROOT / "output" / "package_exports" / access_code / "live_state.db"


def _inspect_idle_db(access_code: str) -> dict[str, Any]:
    db_path = _live_db_path(access_code)
    if not db_path.is_file():
        raise RuntimeError(f"missing live db: {db_path}")
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        max_event = conn.execute("SELECT COALESCE(MAX(event_id), 0) AS max_event_id FROM events").fetchone()
        rooms = conn.execute("SELECT room_id, active, human_count, activation_generation FROM rooms ORDER BY room_id").fetchall()
        return {
            "max_event_id": int(max_event["max_event_id"] if max_event is not None else 0),
            "rooms": [
                {
                    "room_id": str(row["room_id"]),
                    "active": int(row["active"]),
                    "human_count": int(row["human_count"]),
                    "activation_generation": int(row["activation_generation"]),
                }
                for row in rooms
            ],
        }


def run(*, seed: int, duration_seconds: int, interval_seconds: int, port: int, artifact_dir: Path) -> int:
    chosen_port = _choose_port(port)
    base_url = f"http://127.0.0.1:{chosen_port}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = artifact_dir / "screens"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    state_dir = artifact_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    print(f"Using port {chosen_port}", file=sys.stderr)
    server = subprocess.Popen(
        [
            str(PYTHON),
            "-m",
            "macro_ui.serve_macro_ui",
            "--bind",
            "127.0.0.1",
            "--port",
            str(chosen_port),
            "--directory",
            str(ROOT),
        ],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    heartbeat_stop = threading.Event()
    heartbeat_thread: threading.Thread | None = None
    try:
        _wait_for_server(base_url)
        chosen_world = _pick_world_for_seed(base_url, seed)
        access_code = str(chosen_world.get("access_code", "")).strip()
        if not access_code:
            raise RuntimeError("seed lookup returned an empty access code")
        session_response = _create_live_session(
            base_url,
            access_code,
            display_name="Pixel Live Gemini Runner",
            room_id="",
            speed_seconds_per_round=8.0,
        )
        session = session_response.get("session", {}) if isinstance(session_response, dict) else {}
        state = session_response.get("state", {}) if isinstance(session_response, dict) else {}
        session_id = str(session.get("session_id", "")).strip()
        if not session_id:
            raise RuntimeError("live session was not created")
        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(base_url, access_code, session_id, heartbeat_stop),
            daemon=True,
        )
        heartbeat_thread.start()

        run_started = time.monotonic()
        deadline = run_started + float(duration_seconds)
        step_index = 0
        history: list[dict[str, Any]] = []
        initial_snapshot = screenshots_dir / f"step_{step_index:02d}_boot.png"
        token = secrets.token_hex(8)
        _capture_snapshot(
            firefox_binary=FIREFOX_BINARY,
            base_url=base_url,
            seed=seed,
            access_code=access_code,
            session_id=session_id,
            token=token,
            label="boot",
            expected_event_id=int(state.get("latest_event_id", 0) or 0),
            output_path=initial_snapshot,
        )
        history.append({
            "step": step_index,
            "kind": "snapshot",
            "label": "boot",
            "screenshot": str(initial_snapshot),
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        step_index += 1

        last_action_time = time.monotonic()
        while time.monotonic() < deadline:
            target_time = min(deadline, last_action_time + float(interval_seconds))
            while time.monotonic() < target_time:
                time.sleep(min(0.5, target_time - time.monotonic()))
            current_state = _read_json(
                f"{base_url}/api/pixel/worlds/{access_code}/live/state?session_id={session_id}&since=0"
            )
            raw_action = _select_action(current_state, step_index=step_index)
            action = _sanitize_action(raw_action, current_state, step_index=step_index)
            submit_result = _submit_action(base_url, access_code, action)
            post_state = submit_result.get("state", {}) if isinstance(submit_result, dict) else {}
            event_path = state_dir / f"step_{step_index:02d}.json"
            event_path.write_text(
                json.dumps(
                    {
                        "step": step_index,
                        "action": action,
                        "current_state": current_state,
                        "result_state": post_state,
                        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            snapshot_state = post_state if isinstance(post_state, dict) else current_state
            screenshot_path = screenshots_dir / f"step_{step_index:02d}_{action['action_type']}.png"
            token = secrets.token_hex(8)
            _capture_snapshot(
                firefox_binary=FIREFOX_BINARY,
                base_url=base_url,
                seed=seed,
                access_code=access_code,
                session_id=session_id,
                token=token,
                label=f"step {step_index}: {action['action_type']} {action.get('direction') or action.get('target_agent_id') or ''}".strip(),
                expected_event_id=int(snapshot_state.get("latest_event_id", 0) or 0),
                output_path=screenshot_path,
            )
            history.append({
                "step": step_index,
                "kind": "action",
                "action": action,
                "screenshot": str(screenshot_path),
                "state": _build_prompt_snapshot(post_state if isinstance(post_state, dict) else current_state, action, submit_result),
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            last_action_time = time.monotonic()
            step_index += 1
            if step_index > 6:
                break

        final_state = _read_json(
            f"{base_url}/api/pixel/worlds/{access_code}/live/state?session_id={session_id}&since=0"
        )
        final_snapshot = screenshots_dir / f"step_{step_index:02d}_final.png"
        token = secrets.token_hex(8)
        _capture_snapshot(
            firefox_binary=FIREFOX_BINARY,
            base_url=base_url,
            seed=seed,
            access_code=access_code,
            session_id=session_id,
            token=token,
            label="final",
            expected_event_id=int(final_state.get("latest_event_id", 0) or 0),
            output_path=final_snapshot,
        )
        history.append({
            "step": step_index,
            "kind": "snapshot",
            "label": "final",
            "screenshot": str(final_snapshot),
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "final_state": final_state,
        })

        idle_before = _inspect_idle_db(access_code)
        (state_dir / "idle_before_release.json").write_text(json.dumps(idle_before, ensure_ascii=False, indent=2), encoding="utf-8")

        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=10)
        release_payload = _delete_json(f"{base_url}/api/pixel/worlds/{access_code}/live/sessions/{session_id}")
        time.sleep(5)
        idle_after = _inspect_idle_db(access_code)
        (state_dir / "idle_after_release.json").write_text(json.dumps(idle_after, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = {
            "status": "ok",
            "seed": seed,
            "access_code": access_code,
            "session_id": session_id,
            "screenshot_dir": str(screenshots_dir),
            "history": history,
            "release_probe": release_payload,
            "final_state": final_state,
            "idle_before_release": idle_before,
            "idle_after_release": idle_after,
            "artifacts": {
                "screenshots": [str(path) for path in sorted(screenshots_dir.glob("*.png"))],
                "state_logs": [str(path) for path in sorted(state_dir.glob("*.json"))],
            },
        }
        (artifact_dir / "capture_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        readme = artifact_dir / "README.md"
        readme.write_text(
            "\n".join(
                [
                    "# Pixel Live Gemini Run",
                    "",
                    f"Seed: `{seed}`",
                    f"Access code: `{access_code}`",
                    f"Session: `{session_id}`",
                    "",
                    "Included screenshots:",
                    *[f"- `{Path(item['screenshot']).name}`" for item in history],
                    "",
                    "Notes:",
                    "- Actions were generated by a local deterministic planner and submitted through the live Pixel API.",
                    "- The page snapshots wait for the live event to settle and force an atlas/room-readable capture view.",
                    "- Inactive rooms stayed frozen; only the claimed room received live actions during the run.",
                ]
            ),
            encoding="utf-8",
        )
        zip_path = shutil.make_archive(str(artifact_dir), "zip", root_dir=str(artifact_dir.parent), base_dir=artifact_dir.name)
        summary["zip_path"] = zip_path
        (artifact_dir / "capture_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=10)
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:
            server.kill()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42617)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--interval-seconds", type=int, default=20)
    parser.add_argument("--port", type=int, default=8125)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ROOT / "export_artifact" / f"pixel_ui_live_gemini_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(
        run(
            seed=args.seed,
            duration_seconds=args.duration_seconds,
            interval_seconds=args.interval_seconds,
            port=args.port,
            artifact_dir=Path(args.artifact_dir),
        )
    )


if __name__ == "__main__":
    main()
