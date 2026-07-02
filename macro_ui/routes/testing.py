from __future__ import annotations
import base64
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import HTMLResponse

from macro_ui.components.html_utils import _pixel_bundle_version
from .testing_html import _render_headless_pixel_harness, _render_pixel_live_snapshot, _render_phaser_minimal_harness



router = APIRouter(prefix="/__test__")

MACRO_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = MACRO_PACKAGE_ROOT.parent

_HEADLESS_PIXEL_GATES: dict[str, threading.Event] = {}
_HEADLESS_PIXEL_RESULTS: dict[str, dict[str, object]] = {}
_HEADLESS_PIXEL_GIF = base64.b64decode(
    "R0lGODlhAQABAPAAAP///wAAACH5BAAAAAAALAAAAAABAAEAAAICRAEAOw=="
)

def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _headless_pixel_gate(token: str) -> threading.Event:
    normalized = str(token or "").strip()
    if not normalized:
        normalized = "default"
    gate = _HEADLESS_PIXEL_GATES.get(normalized)
    if gate is None:
        gate = threading.Event()
        _HEADLESS_PIXEL_GATES[normalized] = gate
    return gate


def _headless_pixel_result(token: str) -> dict[str, object]:
    normalized = str(token or "").strip() or "default"
    return _HEADLESS_PIXEL_RESULTS.get(normalized, {})


@router.get("/headless-pixel")
def api_headless_pixel_harness(seed: int = 42617, token: str = "", access_code: str = "") -> HTMLResponse:
    return HTMLResponse(_render_headless_pixel_harness(seed, token, access_code=access_code))


@router.get("/pixel-live-snapshot")
def api_pixel_live_snapshot(
    seed: int = 42617,
    access_code: str = "",
    session_id: str = "",
    token: str = "",
    label: str = "live snapshot",
) -> HTMLResponse:
    if not str(access_code or "").strip():
        raise HTTPException(status_code=400, detail="access_code is required")
    if not str(session_id or "").strip():
        raise HTTPException(status_code=400, detail="session_id is required")
    return HTMLResponse(_render_pixel_live_snapshot(seed=seed, access_code=access_code, session_id=session_id, token=token, label=label))


@router.get("/phaser-minimal")
def api_phaser_minimal(token: str = "") -> HTMLResponse:
    return HTMLResponse(_render_phaser_minimal_harness(token))


@router.get("/headless-pixel/gate/{token}")
def api_headless_pixel_gate(token: str) -> Response:
    gate = _headless_pixel_gate(token)
    gate.wait(timeout=120)
    if not gate.is_set():
        return Response(status_code=504, content="headless pixel gate timed out")
    return Response(content=_HEADLESS_PIXEL_GIF, media_type="image/gif")


@router.post("/headless-pixel/result/{token}")
def api_headless_pixel_result(token: str, payload: dict[str, object]) -> dict[str, object]:
    from macro_ui.routes.pixel_api import _pixel_live_store
    access_code = str(payload.get("access_code", "")).strip()
    if access_code:
        try:
            store = _pixel_live_store(access_code)
            store.wait_for_background_idle(timeout_seconds=30.0)
            store.flush_hot_spatial_state(force=True)
        except Exception as e:
            print(f"Failed to wait for background idle: {e}")
    normalized = str(token or "").strip() or "default"
    _HEADLESS_PIXEL_RESULTS[normalized] = dict(payload or {})
    _headless_pixel_gate(normalized).set()
    return {"status": "ok", "token": normalized}


@router.get("/headless-pixel/result/{token}")
def api_headless_pixel_result_get(token: str) -> dict[str, object]:
    normalized = str(token or "").strip() or "default"
    return {"status": "ok", "result": _headless_pixel_result(normalized)}


@router.post("/pixel-live-seed-inventory")
def api_test_pixel_live_seed_inventory(payload: dict[str, object]) -> dict[str, object]:
    from macro_ui.routes.pixel_api import _pixel_live_store
    access_code = str(payload.get("access_code", "")).strip()
    session_id = str(payload.get("session_id", "")).strip()
    target_agent_id = str(payload.get("target_agent_id", "")).strip()
    if len(access_code) != 16:
        raise HTTPException(status_code=400, detail="access_code is required")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    actor_inventory = payload.get("actor_inventory", [])
    target_inventory = payload.get("target_inventory", [])
    if not isinstance(actor_inventory, list) or not isinstance(target_inventory, list):
        raise HTTPException(status_code=400, detail="actor_inventory and target_inventory must be lists")
    store = _pixel_live_store(access_code)
    with store._write_transaction() as conn:
        session = store._session_row(conn, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
        actor_agent_id = str(session["claimed_agent_id"])
        actor_row = store._agent_row(conn, actor_agent_id)
        if actor_row is None:
            raise HTTPException(status_code=404, detail="actor agent missing")
        actor_state = store._ensure_agent_state_defaults(actor_agent_id, json.loads(str(actor_row["state_json"] or "{}")))
        actor_state["inventory"] = actor_inventory
        store._save_agent_state(conn, agent_row=actor_row, state=actor_state)

        if not target_agent_id:
            room_id = str(session["room_id"])
            row = conn.execute(
                "SELECT agent_id FROM agents WHERE room_id = ? AND agent_id != ? ORDER BY agent_id LIMIT 1",
                (room_id, actor_agent_id),
            ).fetchone()
            if row is not None:
                target_agent_id = str(row["agent_id"])
            else:
                row = conn.execute(
                    "SELECT agent_id FROM agents WHERE agent_id != ? ORDER BY agent_id LIMIT 1",
                    (actor_agent_id,)
                ).fetchone()
                if row is not None:
                    target_agent_id = str(row["agent_id"])
                    
        if target_agent_id:
            room_id = str(session["room_id"])
            conn.execute(
                "UPDATE agents SET room_id = ? WHERE agent_id = ?",
                (room_id, target_agent_id)
            )
            target_row = store._agent_row(conn, target_agent_id)
            if target_row:
                target_state = store._ensure_agent_state_defaults(target_agent_id, json.loads(str(target_row["state_json"] or "{}")))
                target_state["inventory"] = target_inventory
                store._save_agent_state(conn, agent_row=target_row, state=target_state)

        store._touch_world_revision()
        store._refresh_hot_world_snapshot(conn)

        seeded_at = _now_iso_utc()
        conn.execute(
            """
            INSERT INTO events(
                session_id, room_id, agent_id, target_agent_id,
                event_type, action_text, response_text, processed, created_at, processed_at, payload_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                session_id,
                str(session["room_id"]),
                actor_agent_id,
                target_agent_id,
                "test_inventory_seed",
                f"Test inventory seed applied for {actor_agent_id}.",
                "Headless regression seeded inventory for front-end interaction checks.",
                seeded_at,
                seeded_at,
                json.dumps(
                    {
                        "actor_agent_id": actor_agent_id,
                        "target_agent_id": target_agent_id,
                        "actor_inventory": actor_inventory,
                        "target_inventory": target_inventory,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        store._touch_world_revision()
        store._refresh_hot_world_snapshot(conn)
        conn.commit()
    return {
        "status": "ok",
        "session_id": session_id,
        "actor_agent_id": actor_agent_id,
        "target_agent_id": target_agent_id,
        "actor_inventory_count": len(actor_inventory),
        "target_inventory_count": len(target_inventory),
    }
