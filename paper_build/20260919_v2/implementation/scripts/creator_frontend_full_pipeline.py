from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from _playwright_firefox import launch_headless_firefox_page


BASE_URL = "http://127.0.0.1:8125"
ENV_PATH = Path.home() / ".config" / "agora_ui_runtime.env"
REQUIRED_ENV_KEYS = ("AGORA_AISTUDIO_API_KEY", "AGORA_VERTEX_API_KEY")


def _load_env_key_names(env_path: Path) -> set[str]:
    keys: set[str] = set()
    if not env_path.is_file():
        return keys
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, _value = line.split("=", 1)
        key = key.strip()
        if key:
            keys.add(key)
    return keys


def _assert_runtime_env() -> None:
    keys = _load_env_key_names(ENV_PATH)
    missing = [key for key in REQUIRED_ENV_KEYS if key not in keys]
    if missing:
        raise RuntimeError(
            f"creator runtime env missing required keys in {ENV_PATH}: {', '.join(missing)}"
        )
    print(f"[preflight] runtime env file present: {ENV_PATH}")
    print(f"[preflight] required env keys present: {', '.join(REQUIRED_ENV_KEYS)}")


def _normalize_seed(raw_seed: int) -> int:
    return max(1, min(999999999, int(raw_seed)))


def _page_fetch_json(page, path: str) -> dict[str, object]:
    payload = page.evaluate(
        """async (inputPath) => {
          const response = await fetch(inputPath, { method: "GET" });
          const text = await response.text();
          return {
            ok: response.ok,
            status: response.status,
            text,
          };
        }""",
        path,
    )
    if not payload.get("ok"):
        raise RuntimeError(f"fetch failed for {path}: {payload.get('status')} {payload.get('text')}")
    text = str(payload.get("text", "")).strip()
    return json.loads(text) if text else {}


def _poll_draft_ready(page, draft_id: str, *, timeout_seconds: int) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        draft = _page_fetch_json(page, f"/api/world-builder/drafts/{draft_id}")
        status = str(draft.get("status", "")).strip()
        world_name = str(draft.get("world_name", "")).strip()
        updated_at = str(draft.get("updated_at", "")).strip()
        print(
            f"[draft] status={status} world={world_name} updated_at={updated_at}"
        )
        if status == "draft_ready":
            return draft
        if status == "draft_failed":
            raise RuntimeError(json.dumps(draft, ensure_ascii=False, indent=2))
        page.wait_for_timeout(15000)
    raise TimeoutError(f"timed out waiting for draft_ready for {draft_id}")


def _poll_art_ready(page, draft_id: str, *, timeout_seconds: int) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    last_log_count = 0
    while time.time() < deadline:
        payload = _page_fetch_json(page, f"/api/world-builder/drafts/{draft_id}/art/status")
        art = dict(payload.get("art", {}))
        status = str(art.get("status", "")).strip()
        logs = art.get("logs", [])
        if isinstance(logs, list) and len(logs) > last_log_count:
            for entry in logs[last_log_count:]:
                command = " ".join(entry.get("command", []))
                returncode = entry.get("returncode")
                duration = entry.get("duration_seconds")
                print(
                    f"[art-log] returncode={returncode} duration={duration}s command={command}"
                )
            last_log_count = len(logs)
        print(f"[art] status={status}")
        if status in {"art_ready", "publish_ready", "published"}:
            return payload
        if status == "art_failed":
            raise RuntimeError(json.dumps(payload, ensure_ascii=False, indent=2))
        page.wait_for_timeout(10000)
    raise TimeoutError(f"timed out waiting for art readiness for {draft_id}")


def _world_concept(seed: int) -> dict[str, object]:
    normalized_seed = _normalize_seed(seed)
    world_name = f"Qingdao Cold-Chain Seafood Exchange {normalized_seed}"
    brief = (
        "Simulate a modern Qingdao cold-chain seafood auction complex. "
        "This is a dense pre-dawn wholesale world with refrigerated docks, inspection rooms, "
        "broker tables, ice factories, livestream resale corners, and fast logistics dispatch. "
        "Focus on authentic Chinese port-market economics: bulk bidding, quality disputes, "
        "temperature-control failures, cash-flow pressure, inspection bottlenecks, and reputation fights. "
        "Use modern industrial visuals, clean wet concrete, steel cold-room walls, pallet stacks, forklifts, "
        "foam boxes, barcode labels, and digital bidding screens. "
        "Make all 25 agents feel like distinct main characters tied into supply-chain power, local gossip, "
        "and recurring trade conflicts. Keep inventories dense and commercially realistic."
    )
    return {
        "world_name": world_name,
        "genre": "modern Chinese port seafood auction, cold-chain trade complex",
        "player_count_target": 4,
        "agent_count_target": 25,
        "focus": "economy and trade-heavy world",
        "seed": normalized_seed,
        "brief": brief,
    }


def run_pipeline(*, seed: int, draft_timeout: int, art_timeout: int) -> tuple[str, str]:
    concept = _world_concept(seed)
    print(f"[concept] world_name={concept['world_name']}")
    print(f"[concept] seed={concept['seed']}")

    with sync_playwright() as playwright:
        with launch_headless_firefox_page(playwright) as (_context, page):
            page.on("console", lambda msg: print(f"[browser-console] {msg.type}: {msg.text}"))
            page.on("pageerror", lambda err: print(f"[browser-error] {err}"))

            page.goto(f"{BASE_URL}/creator/index.html", timeout=15000, wait_until="domcontentloaded")
            page.fill('#create-form input[name="world_name"]', str(concept["world_name"]))
            page.fill('#create-form input[name="genre"]', str(concept["genre"]))
            page.fill('#create-form input[name="player_count_target"]', str(concept["player_count_target"]))
            page.fill('#create-form input[name="agent_count_target"]', str(concept["agent_count_target"]))
            page.select_option('#create-form select[name="focus"]', str(concept["focus"]))
            page.fill('#create-form input[name="seed"]', str(concept["seed"]))
            page.fill('#create-form textarea[name="brief"]', str(concept["brief"]))

            print("[creator] submitting new draft from frontend")
            is_valid = page.locator("#create-form").evaluate("form => form.reportValidity()")
            if not is_valid:
                raise RuntimeError("creator form was invalid before submit")
            with page.expect_response(
                lambda response: response.request.method == "POST"
                and response.url.endswith("/api/world-builder/drafts"),
                timeout=300000,
            ) as draft_response_info:
                page.locator("#create-form").evaluate("form => form.requestSubmit()")
            draft_response = draft_response_info.value
            if not draft_response.ok:
                raise RuntimeError(
                    f"creator draft POST failed: {draft_response.status} {draft_response.text()}"
                )
            page.wait_for_selector('#draft-review:not(.hidden)', timeout=3600000)

            draft_id = page.evaluate("window.localStorage.getItem('agora_world_creator_current_draft')")
            if not draft_id:
                raise RuntimeError("creator UI did not persist a draft id to localStorage")
            print(f"[creator] draft_id={draft_id}")

            draft_payload = _poll_draft_ready(page, draft_id, timeout_seconds=draft_timeout)
            status_pill_text = page.locator('#draft-status-pill').inner_text().strip()
            print(f"[creator] ui status pill={status_pill_text}")

            error_banner = page.locator('#draft-error-banner')
            if error_banner.is_visible():
                raise RuntimeError(f"creator UI error banner: {error_banner.inner_text().strip()}")

            print("[creator] starting art + qa from frontend")
            page.click('#start-art')
            _poll_art_ready(page, draft_id, timeout_seconds=art_timeout)

            print("[creator] publishing world from frontend")
            page.click('#publish-world')
            page.wait_for_function(
                "() => document.querySelector('#publish-access-code')?.textContent?.trim() && document.querySelector('#publish-access-code').textContent.trim() !== '-'",
                timeout=300000,
            )
            access_code = page.locator('#publish-access-code').inner_text().strip()
            if len(access_code) != 16:
                raise RuntimeError(f"unexpected access code after publish: {access_code}")
            print(f"[publish] access_code={access_code}")
            return draft_id, access_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a fresh Agora 2.0 creator frontend pipeline to publish.")
    parser.add_argument("--seed", type=int, default=int(time.time()))
    parser.add_argument("--draft-timeout", type=int, default=3600)
    parser.add_argument("--art-timeout", type=int, default=3600)
    args = parser.parse_args()

    _assert_runtime_env()
    draft_id, access_code = run_pipeline(
        seed=_normalize_seed(int(args.seed)),
        draft_timeout=int(args.draft_timeout),
        art_timeout=int(args.art_timeout),
    )
    print(f"[success] draft_id={draft_id} access_code={access_code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
