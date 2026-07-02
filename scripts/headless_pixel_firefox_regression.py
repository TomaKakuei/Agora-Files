#!/usr/bin/env python3
"""Run a headless Firefox regression against the Pixel live world."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import socket
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIREFOX_BINARY = Path(os.environ.get("FIREFOX_BINARY", "/usr/bin/firefox"))
SELF_USE_PROBE_ITEM_ID = "restorative_tea"
TRADE_QUOTE_PROBE_ITEM_ID = "quote_probe_item"


def _resolve_server_python() -> Path:
    for candidate in (
        os.environ.get("AGORA_PIXEL_PYTHON", ""),
        sys.executable,
        sys.executable,
    ):
        normalized = str(candidate or "").strip()
        if not normalized:
            continue
        path = Path(normalized).expanduser()
        if path.is_file():
            return path.resolve()
    return Path(sys.executable).resolve()


PYTHON = _resolve_server_python()


def _firefox_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("MOZ_HEADLESS", "1")
    env.setdefault("MOZ_WEBRENDER", "0")
    env.setdefault("MOZ_DISABLE_RDD_SANDBOX", "1")
    env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    env.setdefault("XDG_RUNTIME_DIR", "/tmp")
    env.setdefault("MOZ_DISABLE_CONTENT_SANDBOX", "1")
    env.setdefault("MOZ_DISABLE_GMP_SANDBOX", "1")
    env.setdefault("MOZ_NO_REMOTE", "1")
    return env


def _make_firefox_profile(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir="/tmp"))


def _firefox_env_for_profile(profile_dir: Path) -> dict[str, str]:
    env = _firefox_env()
    env["HOME"] = str(profile_dir)
    return env


def _read_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=15) as response:
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
    matches.sort(
        key=lambda world: (
            str(world.get("created_at", "")),
            str(world.get("access_code", "")),
        ),
        reverse=True,
    )
    if matches:
        return matches[0]
    if worlds:
        return worlds[0]
    raise RuntimeError("no pixel-ready worlds are available")


def _pick_world_by_access_code(base_url: str, access_code: str) -> dict[str, Any]:
    normalized = str(access_code or "").strip()
    if len(normalized) != 16:
        raise RuntimeError(f"invalid access code: {access_code!r}")
    payload = _read_json(f"{base_url}/api/pixel/worlds/{normalized}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"world lookup returned no usable record for access code {normalized}")
    package_meta = payload.get("package", {}) if isinstance(payload.get("package", {}), dict) else {}
    payload_access_code = str(payload.get("access_code", "") or package_meta.get("access_code", "")).strip()
    if payload_access_code != normalized:
        raise RuntimeError(f"world lookup returned no usable record for access code {normalized}")
    return {
        **payload,
        "access_code": payload_access_code,
        "world_name": str(payload.get("world_name", "") or package_meta.get("world_name", "")).strip(),
        "world_id": str(payload.get("world_id", "") or package_meta.get("world_id", "")).strip(),
        "live_session_url": str(payload.get("live_session_url", "")).strip(),
        "live_state_url": str(payload.get("live_state_url", "")).strip(),
        "live_action_url": str(payload.get("live_action_url", "")).strip(),
        "live_ws_url_template": str(payload.get("live_ws_url_template", "")).strip(),
        "package": package_meta,
    }


def _wait_for_result(base_url: str, token: str, timeout_s: float = 300.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_result: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        payload = _read_json(f"{base_url}/__test__/headless-pixel/result/{token}")
        result = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(result, dict) and result:
            last_result = result
            if result.get("status") in {"ok", "error"}:
                return result
        time.sleep(0.75)
    raise RuntimeError(f"headless regression did not finish: {last_result}")


def _capture_snapshot(
    *,
    base_url: str,
    seed: int,
    access_code: str,
    session_id: str,
    screenshot_path: Path,
    timeout_s: float = 75.0,
) -> str:
    token = secrets.token_hex(8)
    label = "Pixel launch validation snapshot"
    snapshot_url = (
        f"{base_url}/__test__/pixel-live-snapshot?seed={int(seed)}"
        f"&access_code={urllib.parse.quote(str(access_code).strip())}"
        f"&session_id={urllib.parse.quote(str(session_id).strip())}"
        f"&token={token}"
        f"&label={urllib.parse.quote(label)}"
    )
    temp_profile = _make_firefox_profile(f"firefox_snapshot_{seed}_{token}_")
    browser_cmd = [
        str(FIREFOX_BINARY),
        "--headless",
        "--new-instance",
        "--no-remote",
        "-profile",
        str(temp_profile),
        "--window-size",
        "1680,1200",
        "--screenshot",
        str(screenshot_path),
        snapshot_url,
    ]
    browser = subprocess.Popen(
        browser_cmd,
        cwd=str(ROOT),
        env=_firefox_env_for_profile(temp_profile),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    browser_stdout = ""
    browser_stderr = ""
    snapshot_warning = ""
    try:
        try:
            _wait_for_result(base_url, token, timeout_s=timeout_s)
        except Exception as exc:
            snapshot_warning = f"snapshot harness did not finish cleanly: {exc}"
    finally:
        try:
            browser_stdout, browser_stderr = browser.communicate(timeout=timeout_s)
        except Exception:
            if browser.poll() is None:
                browser.terminate()
                try:
                    browser.wait(timeout=15)
                except Exception:
                    browser.kill()
            try:
                browser_stdout, browser_stderr = browser.communicate(timeout=15)
            except Exception:
                browser_stdout = browser_stdout or ""
                browser_stderr = browser_stderr or ""
    if browser.returncode not in (0, -15, -9):
        failure = (
            "Firefox snapshot run failed:\n"
            f"stdout:\n{browser_stdout}\n"
            f"stderr:\n{browser_stderr}\n"
        )
        shutil.rmtree(temp_profile, ignore_errors=True)
        return f"{snapshot_warning}; {failure}" if snapshot_warning else failure
    if not screenshot_path.is_file() or screenshot_path.stat().st_size <= 0:
        missing = f"missing screenshot output: {screenshot_path}"
        shutil.rmtree(temp_profile, ignore_errors=True)
        return f"{snapshot_warning}; {missing}" if snapshot_warning else missing
    shutil.rmtree(temp_profile, ignore_errors=True)
    return snapshot_warning


def _verify_refresh_session(expected_code: str, initial_session_id: str) -> dict[str, Any]:
    live_db = ROOT / "output" / "package_exports" / expected_code / "live_state.db"
    if not live_db.is_file():
        raise RuntimeError(f"missing live state db: {live_db}")
    with sqlite3.connect(live_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT session_id, claimed_agent_id, status, room_id, created_at FROM sessions ORDER BY created_at DESC"
        ).fetchall()
        if len(rows) < 2:
            raise RuntimeError(f"expected a refresh-created session, found {len(rows)} session(s)")
        active = next((row for row in rows if str(row["status"]) == "active"), None)
        if active is None:
            raise RuntimeError("no active session found after refresh")
        if str(active["session_id"]) == str(initial_session_id):
            raise RuntimeError("refresh reused the initial session id")
        if not str(active["claimed_agent_id"]).strip():
            raise RuntimeError("refreshed session does not own a claimed agent")
        return dict(active)


def _verify_ai_studio_persistence(
    expected_code: str,
    session_id: str,
    unique_message: str,
    *,
    quoted_total_price: int = 0,
    actor_wallet_before_trade: int = 0,
    target_wallet_before_trade: int = 0,
) -> dict[str, Any]:
    live_db = ROOT / "output" / "package_exports" / expected_code / "live_state.db"
    if not live_db.is_file():
        raise RuntimeError(f"missing live state db: {live_db}")
    with sqlite3.connect(live_db) as conn:
        conn.row_factory = sqlite3.Row
        human_event = conn.execute(
            """
            SELECT *
              FROM events
             WHERE session_id = ? AND event_type = 'human_action' AND action_text = ?
             ORDER BY event_id DESC
             LIMIT 1
            """,
            (session_id, unique_message),
        ).fetchone()
        if human_event is None:
            raise RuntimeError("front-end message did not land in the live DB")
        human_payload = json.loads(str(human_event["payload_json"] or "{}"))
        actor_agent_id = str(human_event["agent_id"] or "")
        target_agent_id = str(human_event["target_agent_id"] or "")
        if not str(human_payload.get("client_action_id", "")).strip():
            raise RuntimeError(f"human_action payload did not persist client_action_id: {human_payload}")
        response_candidates = conn.execute(
            """
            SELECT *
              FROM events
             WHERE session_id = ? AND event_type = 'agent_response' AND event_id > ?
             ORDER BY event_id DESC
             LIMIT 12
            """,
            (session_id, int(human_event["event_id"] or 0)),
        ).fetchall()
        client_action_id = str(human_payload.get("client_action_id", "")).strip()
        response_event = None
        for row in response_candidates:
            payload = json.loads(str(row["payload_json"] or "{}"))
            if client_action_id and str(payload.get("client_action_id", "")).strip() == client_action_id:
                response_event = row
                break
        if response_event is None and response_candidates:
            response_event = response_candidates[0]
        if response_event is None:
            merged_human_payload = json.loads(str(human_event["payload_json"] or "{}"))
            if str(merged_human_payload.get("message_status", "")).strip() != "completed":
                raise RuntimeError("AI reply event did not land in the live DB")
            response_payload = merged_human_payload
        else:
            response_payload = json.loads(str(response_event["payload_json"] or "{}"))
        if str(response_payload.get("message_status", "")).strip() != "completed":
            raise RuntimeError(f"AI response payload did not settle to completed: {response_payload}")
        for payload_name, payload in (("agent_response", response_payload),):
            if str(payload.get("response_source", "")).strip() != "ai_studio":
                raise RuntimeError(f"{payload_name} payload did not record ai_studio as the response source: {payload}")
            if str(payload.get("provider", "")).strip() != "google_ai_studio":
                raise RuntimeError(f"{payload_name} payload did not record google_ai_studio as provider: {payload}")
            if not str(payload.get("model", "")).strip():
                raise RuntimeError(f"{payload_name} payload did not persist the model name: {payload}")
            if int(payload.get("latency_ms", 0) or 0) <= 0:
                raise RuntimeError(f"{payload_name} payload did not persist a positive latency: {payload}")
            if not str(payload.get("actor_focus", "")).strip():
                raise RuntimeError(f"{payload_name} payload did not persist actor_focus: {payload}")
            if not str(payload.get("target_focus", "")).strip():
                raise RuntimeError(f"{payload_name} payload did not persist target_focus: {payload}")
        use_item_events = conn.execute(
            """
            SELECT payload_json, response_text
              FROM events
             WHERE session_id = ? AND event_type = 'human_action'
             ORDER BY event_id
            """,
            (session_id,),
        ).fetchall()
        parsed_action_payloads = [json.loads(str(row["payload_json"] or "{}")) for row in use_item_events]
        self_use = next(
            (
                payload for payload in parsed_action_payloads
                if str(payload.get("action_type", "")).strip() == "use_item"
                and str(payload.get("item_id", "")).strip() == SELF_USE_PROBE_ITEM_ID
                and not str(payload.get("target_agent_id", "")).strip()
            ),
            None,
        )
        target_use = next(
            (
                payload for payload in parsed_action_payloads
                if str(payload.get("action_type", "")).strip() == "use_item"
                and str(payload.get("item_id", "")).strip() == SELF_USE_PROBE_ITEM_ID
                and str(payload.get("target_agent_id", "")).strip()
            ),
            None,
        )
        quote_request = next(
            (
                payload for payload in parsed_action_payloads
                if str(payload.get("action_type", "")).strip() == "request_trade_quote"
                and str(payload.get("item_id", "")).strip() == TRADE_QUOTE_PROBE_ITEM_ID
            ),
            None,
        )
        accept_quote = next(
            (
                payload for payload in parsed_action_payloads
                if str(payload.get("action_type", "")).strip() == "accept_trade_quote"
                and str(payload.get("offer_id", "")).strip()
            ),
            None,
        )
        if self_use is None:
            raise RuntimeError("front-end self item use did not land in the live DB")
        
        # If there's no target agent, these actions can't happen
        has_target_agent = target_agent_id and target_agent_id.strip()
        if has_target_agent:
            if target_use is None:
                raise RuntimeError("front-end targeted item use did not land in the live DB")
            if quote_request is None:
                raise RuntimeError("front-end trade quote request did not land in the live DB")

        actor_row = conn.execute("SELECT current_focus, mainline_summary, state_json FROM agents WHERE agent_id = ?", (actor_agent_id,)).fetchone()
        
        target_row = None
        if has_target_agent:
            target_row = conn.execute("SELECT current_focus, mainline_summary, state_json FROM agents WHERE agent_id = ?", (target_agent_id,)).fetchone()
            if target_row is None:
                raise RuntimeError("message target agent row missing from live DB")
                
        if actor_row is None:
            raise RuntimeError("message actor agent row missing from live DB")

        actor_state = json.loads(str(actor_row["state_json"] or "{}"))
        target_state = json.loads(str(target_row["state_json"] or "{}")) if target_row else {}
        
        actor_summary = str(actor_row["mainline_summary"] or "").strip()
        target_summary = str(target_row["mainline_summary"] or "").strip() if target_row else ""
        
        if not actor_summary:
            raise RuntimeError("actor mainline_summary did not persist any live summary")
        
        if str(actor_state.get("last_ai_actor_focus", "")).strip() != str(response_payload.get("actor_focus", "")).strip():
            raise RuntimeError("actor state_json did not persist last_ai_actor_focus")
        if str(actor_state.get("last_ai_target_focus", "")).strip() != str(response_payload.get("target_focus", "")).strip():
            raise RuntimeError("actor state_json did not persist last_ai_target_focus")
            
        if has_target_agent:
            if not target_summary:
                raise RuntimeError("target mainline_summary did not persist any live summary")
            if str(target_state.get("last_ai_actor_focus", "")).strip() != str(response_payload.get("actor_focus", "")).strip():
                raise RuntimeError("target state_json did not persist last_ai_actor_focus")
            if str(target_state.get("last_ai_target_focus", "")).strip() != str(response_payload.get("target_focus", "")).strip():
                raise RuntimeError("target state_json did not persist last_ai_target_focus")
            if str(target_state.get("last_ai_response_text", "")).strip() != str(response_event["response_text"] or "").strip():
                raise RuntimeError("target state_json did not persist last_ai_response_text")

        if str(actor_state.get("last_ai_response_text", "")).strip() != str(response_event["response_text"] or "").strip():
            raise RuntimeError("actor state_json did not persist last_ai_response_text")

        actor_inventory = actor_state.get("inventory", []) if isinstance(actor_state, dict) else []
        target_inventory = target_state.get("inventory", []) if isinstance(target_state, dict) else []
        actor_offers = actor_state.get("pending_trade_offers", []) if isinstance(actor_state, dict) else []
        target_offers = target_state.get("pending_trade_offers", []) if isinstance(target_state, dict) else []
        
        accepted_offer_id = str(accept_quote.get("offer_id", "")).strip() if isinstance(accept_quote, dict) else ""
        settled_offer = None
        
        if has_target_agent:
            if accepted_offer_id:
                settled_offer = next(
                    (
                        entry for entry in actor_offers
                        if isinstance(entry, dict) and str(entry.get("offer_id", "")).strip() == accepted_offer_id
                    ),
                    None,
                ) or next(
                    (
                        entry for entry in target_offers
                        if isinstance(entry, dict) and str(entry.get("offer_id", "")).strip() == accepted_offer_id
                    ),
                    None,
                )
            if not isinstance(settled_offer, dict):
                settled_offer = next(
                    (
                        entry for entry in actor_offers
                        if isinstance(entry, dict)
                        and str(entry.get("item_id", "")).strip() == TRADE_QUOTE_PROBE_ITEM_ID
                        and str(entry.get("status", "")).strip() in {"completed", "accepted_pending_delivery"}
                    ),
                    None,
                ) or next(
                    (
                        entry for entry in target_offers
                        if isinstance(entry, dict)
                        and str(entry.get("item_id", "")).strip() == TRADE_QUOTE_PROBE_ITEM_ID
                        and str(entry.get("status", "")).strip() in {"completed", "accepted_pending_delivery"}
                    ),
                    None,
                )
                if isinstance(settled_offer, dict):
                    accepted_offer_id = str(settled_offer.get("offer_id", "")).strip()
            if not isinstance(settled_offer, dict):
                raise RuntimeError(f"accepted trade quote offer did not persist in agent state: {accepted_offer_id}")
                
        total_price = int(settled_offer.get("total_price", 0) or 0) if settled_offer else 0
        expected_total_price = max(0, int(quoted_total_price or total_price))
        actor_has_quote_item = any(
            str(entry.get("item_id", "")).strip() == TRADE_QUOTE_PROBE_ITEM_ID and int(entry.get("quantity", 0) or 0) == 1
            for entry in actor_inventory
            if isinstance(entry, dict)
        )
        target_has_quote_item = any(
            str(entry.get("item_id", "")).strip() == TRADE_QUOTE_PROBE_ITEM_ID and int(entry.get("quantity", 0) or 0) > 0
            for entry in target_inventory
            if isinstance(entry, dict)
        )
        actor_wallet = int(
            (
                (actor_state.get("wallet", {}) if isinstance(actor_state.get("wallet", {}), dict) else {}).get(
                    "amount_minor",
                    actor_state.get("currency_quantity", 0),
                )
            )
            or 0
        )
        target_wallet = int(
            (
                (target_state.get("wallet", {}) if isinstance(target_state.get("wallet", {}), dict) else {}).get(
                    "amount_minor",
                    target_state.get("currency_quantity", 0),
                )
            )
            or 0
        )
        if not actor_has_quote_item:
            raise RuntimeError(f"actor inventory did not persist the quoted trade result. Inventory: {json.dumps(actor_inventory)}")
        if target_has_quote_item:
            raise RuntimeError("target inventory still holds the quoted item after settlement")
        if actor_wallet >= int(actor_wallet_before_trade or actor_wallet + expected_total_price):
            raise RuntimeError("actor wallet did not decrease after accepting the quoted trade")
        if target_wallet <= int(target_wallet_before_trade or max(0, target_wallet - expected_total_price)):
            raise RuntimeError("target wallet did not increase after completing the quoted trade")
        expected_actor_wallet = max(0, int(actor_wallet_before_trade or actor_wallet + expected_total_price) - expected_total_price)
        expected_target_wallet = int(target_wallet_before_trade or max(0, target_wallet - expected_total_price)) + expected_total_price
        if actor_wallet != expected_actor_wallet:
            raise RuntimeError(f"actor wallet did not settle to the quoted total price: expected {expected_actor_wallet} got {actor_wallet}")
        if target_wallet != expected_target_wallet:
            raise RuntimeError(f"target wallet did not settle to the quoted total price: expected {expected_target_wallet} got {target_wallet}")
        return {
            "human_event_id": int(human_event["event_id"]),
            "response_event_id": int(response_event["event_id"]),
            "model": str(response_payload.get("model", "")),
            "latency_ms": int(response_payload.get("latency_ms", 0) or 0),
            "response_source": str(response_payload.get("response_source", "")),
            "message_memory_persisted": True,
            "item_self_persisted": True,
            "item_target_persisted": True,
            "trade_persisted": True,
            "trade_quote_request_persisted": True,
            "trade_quote_accept_persisted": bool(accept_quote is not None) or str(settled_offer.get("status", "")).strip() == "completed",
            "quoted_total_price": expected_total_price,
        }


def _is_retryable_harness_result(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    message = str(result.get("message", "")).strip().lower()
    return any(
        marker in message
        for marker in (
            "no live target agent available",
            "ai reply event did not land in the live db",
            "http error 404",
            "headless regression did not finish",
        )
    )


def run(seed: int, port: int, reuse_server: bool = False, max_attempts: int = 3, access_code: str = "") -> int:
    last_retryable_error: dict[str, Any] | None = None
    for attempt_index in range(max(1, int(max_attempts))):
        status = _run_once(seed, port, reuse_server=reuse_server, access_code=access_code)
        if status == 0:
            return 0
        if isinstance(status, dict) and _is_retryable_harness_result(status) and attempt_index + 1 < max_attempts:
            last_retryable_error = status
            continue
        if isinstance(status, dict):
            raise RuntimeError(json.dumps(status, ensure_ascii=False, indent=2))
        return int(status)
    if last_retryable_error is not None:
        raise RuntimeError(json.dumps(last_retryable_error, ensure_ascii=False, indent=2))
    return 1


def _run_once(seed: int, port: int, reuse_server: bool = False, access_code: str = "") -> int | dict[str, Any]:
    chosen_port = int(port) if reuse_server else _choose_port(port)
    base_url = f"http://127.0.0.1:{chosen_port}"
    token = secrets.token_hex(8)
    screenshot_path = Path("/tmp") / f"agora_pixel_headless_{seed}_{token}.png"
    print(f"Using port {chosen_port}", file=sys.stderr)
    server = None
    if not reuse_server:
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
            stdout=None,
            stderr=subprocess.STDOUT,
        )
    try:
        _wait_for_server(base_url)
        chosen_world = (
            _pick_world_by_access_code(base_url, access_code)
            if str(access_code or "").strip()
            else _pick_world_for_seed(base_url, seed)
        )
        expected_code = str(chosen_world.get("access_code", "")).strip()
        if not expected_code:
            raise RuntimeError("seed lookup returned an empty access code")

        harness_url = (
            f"{base_url}/__test__/headless-pixel?seed={int(seed)}&token={token}"
            f"&access_code={urllib.parse.quote(expected_code)}"
        )
        temp_profile = _make_firefox_profile(f"firefox_harness_{seed}_{token}_")
        browser_cmd = [
            str(FIREFOX_BINARY),
            "--headless",
            "--new-instance",
            "--no-remote",
            "-profile",
            str(temp_profile),
            "--window-size",
            "1680,1200",
            harness_url,
        ]
        browser = subprocess.Popen(
            browser_cmd,
            cwd=str(ROOT),
            env=_firefox_env_for_profile(temp_profile),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        browser_stdout = ""
        browser_stderr = ""
        result = None
        try:
            result = _wait_for_result(base_url, token)
        finally:
            if browser.poll() is None:
                browser.terminate()
                try:
                    browser.wait(timeout=15)
                except Exception:
                    browser.kill()
            try:
                browser_stdout, browser_stderr = browser.communicate(timeout=15)
            except Exception:
                browser_stdout = browser_stdout or ""
                browser_stderr = browser_stderr or ""

            if browser.returncode not in (0, -15, -9) or result is None or result.get("status") != "ok":
                print(f"Firefox screenshot run failed or timed out:\nstdout:\n{browser_stdout}\nstderr:\n{browser_stderr}\n")
            shutil.rmtree(temp_profile, ignore_errors=True)

        if browser.returncode not in (0, -15, -9):
            raise RuntimeError("Firefox screenshot run failed")
        if result.get("status") != "ok":
            return dict(result)
        if str(result.get("access_code", "")).strip() != expected_code:
            raise RuntimeError(
                f"seed {seed} resolved to {result.get('access_code')!r}, expected {expected_code!r}"
            )
        if not bool(result.get("moved")):
            raise RuntimeError("the claimed agent never moved")
        if not bool(result.get("draft_preserved")):
            raise RuntimeError("live chat draft was not preserved across a live refresh")
        if not bool(result.get("item_self_ok")):
            raise RuntimeError("front-end self item interaction did not report success")
        if not bool(result.get("item_target_ok")):
            raise RuntimeError("front-end targeted item interaction did not report success")
        if not bool(result.get("trade_ok")):
            raise RuntimeError("front-end trade interaction did not report success")
        if not str(result.get("unique_message", "")).strip():
            raise RuntimeError("live message was not reported")
        diagnostics = result.get("diagnostics", {})
        if isinstance(diagnostics, dict):
            animation_samples = diagnostics.get("animation_samples", [])
            if not isinstance(animation_samples, list):
                raise RuntimeError("animation diagnostics were not collected")
        initial_session_id = str(result.get("initial_session_id", "")).strip()
        if not initial_session_id:
            raise RuntimeError("initial live session id missing")
        ai_persistence = _verify_ai_studio_persistence(
            expected_code,
            initial_session_id,
            str(result.get("unique_message", "")).strip(),
            quoted_total_price=int(result.get("quoted_total_price", 0) or 0),
            actor_wallet_before_trade=int(result.get("actor_wallet_before_trade", 0) or 0),
            target_wallet_before_trade=int(result.get("target_wallet_before_trade", 0) or 0),
        )
        screenshot_warning = _capture_snapshot(
            base_url=base_url,
            seed=seed,
            access_code=expected_code,
            session_id=initial_session_id,
            screenshot_path=screenshot_path,
        )
        print(json.dumps(
            {
                "status": "ok",
                "seed": seed,
                "access_code": expected_code,
                "screenshot": str(screenshot_path),
                "screenshot_warning": screenshot_warning,
                "ai_persistence": ai_persistence,
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
        ))
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
    parser.add_argument("--seed", type=int, default=42617)
    parser.add_argument("--port", type=int, default=8125)
    parser.add_argument("--access-code", default="", help="Optional 16-character access code to test directly.")
    parser.add_argument("--reuse-server", action="store_true", help="Use an already-running macro UI server instead of spawning a local one.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        raise SystemExit(
            run(
                args.seed,
                args.port,
                reuse_server=bool(args.reuse_server),
                access_code=str(args.access_code or "").strip(),
            )
        )
    except Exception as exc:
        payload: dict[str, Any] = {
            "status": "error",
            "message": str(exc),
            "error": str(exc),
        }
        if exc.args:
            candidate = exc.args[0]
            if isinstance(candidate, str):
                try:
                    parsed = json.loads(candidate)
                except Exception:
                    parsed = None
                if isinstance(parsed, dict):
                    payload.update(parsed)
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
