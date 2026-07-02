from __future__ import annotations
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from agora_ui.live_world import get_pixel_live_store

from macro_ui.components.schemas import (
    PixelLiveSessionCreateRequest,
    PixelLiveActionRequest,
)

# Late import to prevent circular import issues via a lazy proxy
class _LazyServeMacroUi:
    def __getattr__(self, name):
        import macro_ui.serve_macro_ui as serve_macro_ui
        return getattr(serve_macro_ui, name)

serve_macro_ui = _LazyServeMacroUi()

router = APIRouter(prefix="/api/pixel")

def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _with_server_timing(payload: dict[str, Any], started_at: float) -> dict[str, Any]:
    result = dict(payload)
    existing_timing = result.get("timing", {})
    timing = dict(existing_timing) if isinstance(existing_timing, dict) else {}
    timing["server_elapsed_ms"] = max(1, int(round((time.perf_counter() - started_at) * 1000.0)))
    result["timing"] = timing
    return result


def _package_export_root() -> Path:
    # Use serve_macro_ui's MACRO_PACKAGE_ROOT dynamically to support unit test mocks
    return serve_macro_ui.MACRO_PACKAGE_ROOT / "output" / "package_exports"


def _package_export_dir(access_code: str) -> Path:
    return serve_macro_ui._package_export_root() / access_code


def _pixel_world_workspace(access_code: str) -> Path:
    export_dir = _package_export_dir(access_code)
    package_db = export_dir / "world_package.db"
    if not package_db.is_file():
        raise FileNotFoundError(f"Package not found: {access_code}")
    workspace = export_dir / "materialized"
    return serve_macro_ui.ensure_materialized_world_package(package_db, output_dir=workspace)


def _metadata_bool(metadata: dict[str, object], key: str) -> bool | None:
    value = metadata.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "ok"}:
        return True
    if text in {"0", "false", "no"}:
        return False
    return None


def _metadata_json(metadata: dict[str, object], key: str) -> dict[str, object] | None:
    raw = metadata.get(key)
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except Exception:
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _pixel_world_template_key(record: dict[str, object]) -> str:
    seed = str(record.get("seed", "")).strip()
    if seed:
        return f"seed:{seed}"
    world_id = str(record.get("world_id", "")).strip().lower()
    if world_id:
        return f"world_id:{world_id}"
    world_name = str(record.get("world_name", "")).strip().lower()
    if world_name:
        return f"world_name:{world_name}"
    return f"access_code:{str(record.get('access_code', '')).strip().lower()}"


def _pixel_world_sort_key(record: dict[str, object]) -> tuple[str, str]:
    return (
        str(record.get("created_at", "")),
        str(record.get("access_code", "")),
    )


def _pixel_world_is_public(record: dict[str, object]) -> bool:
    if bool(record.get("validation_probe")):
        return False
    world_id = str(record.get("world_id", "")).strip().lower()
    world_name = str(record.get("world_name", "")).strip().lower()
    if not world_id and not world_name:
        return False
    world_id = str(record.get("world_id", "")).strip()
    if "_autonomous" in world_id:
        return True
    source_label = str(record.get("source_label", "")).strip()
    if source_label in {"world_creator_publish", "macro_ui_export", "world_creator_art_pipeline"}:
        return True
    return False


def _all_pixel_world_records() -> list[dict[str, object]]:
    worlds: list[dict[str, object]] = []
    export_root = serve_macro_ui._package_export_root()
    if export_root.is_dir():
        for export_dir in sorted(path for path in export_root.iterdir() if path.is_dir()):
            access_code = export_dir.name
            record = serve_macro_ui._pixel_world_record(access_code)
            if record is not None and _pixel_world_is_public(record):
                worlds.append(record)
    worlds.sort(key=_pixel_world_sort_key, reverse=True)
    return worlds


def _latest_pixel_world_records() -> list[dict[str, object]]:
    latest_by_template: dict[str, dict[str, object]] = {}
    for record in serve_macro_ui._all_pixel_world_records():
        template_key = _pixel_world_template_key(record)
        if template_key not in latest_by_template:
            latest_by_template[template_key] = record
    records = list(latest_by_template.values())
    records.sort(key=_pixel_world_sort_key, reverse=True)
    return records


def _canonical_pixel_world_record(access_code: str) -> dict[str, object] | None:
    normalized = str(access_code).strip()
    if len(normalized) != 16:
        return None
    requested = serve_macro_ui._pixel_world_record(normalized)
    if requested is None:
        return None
    if bool(requested.get("validation_probe")):
        return requested
    if not _pixel_world_is_public(requested):
        return None
    requested_template = _pixel_world_template_key(requested)
    latest = next(
        (
            record
            for record in serve_macro_ui._latest_pixel_world_records()
            if _pixel_world_template_key(record) == requested_template
        ),
        None,
    )
    if latest is None:
        return None
    if str(latest.get("access_code", "")).strip() != normalized:
        return None
    return latest


def _require_latest_pixel_world_access_code(access_code: str) -> str:
    normalized = str(access_code).strip()
    if len(normalized) != 16:
        raise HTTPException(status_code=400, detail="access code must be 16 characters")
    if serve_macro_ui._canonical_pixel_world_record(normalized) is None:
        raise HTTPException(status_code=404, detail=f"Pixel world not available as the latest template revision: {normalized}")
    return normalized


def _pixel_world_record(access_code: str) -> dict[str, object] | None:
    normalized = str(access_code).strip()
    if len(normalized) != 16:
        return None
    export_dir = _package_export_dir(normalized)
    package_db = export_dir / "world_package.db"
    if not package_db.is_file():
        return None
    try:
        package_meta = serve_macro_ui.read_world_package_metadata(package_db)
        pixel_read = _metadata_bool(package_meta, "pixel_read")
        if pixel_read is False:
            return None
        startup_ok = _metadata_bool(package_meta, "startup_ok")
        if startup_ok is False:
            return None
        workspace = serve_macro_ui._pixel_world_workspace(normalized)
        report = _metadata_json(package_meta, "pixel_read_report")
        if report is None:
            report = serve_macro_ui.assess_pixel_readiness_from_root(workspace)
        if not bool(report.get("pixel_read", pixel_read is True)):
            return None
        config, metadata = serve_macro_ui.load_world_config_from_access_code(serve_macro_ui.MACRO_PACKAGE_ROOT, normalized, materialize_dir=workspace)
        metadata["pixel_read"] = True
        metadata["pixel_read_report"] = report
        has_startup_ok = "startup_ok" in metadata
        metadata["startup_ok"] = bool(metadata.get("startup_ok", False))
        if has_startup_ok and not metadata["startup_ok"]:
            return None
        runtime_seed = config.get("runtime", {}).get("seed", "")
        return {
            "access_code": normalized,
            "created_at": str(package_meta.get("created_at", "") or metadata.get("created_at", "")),
            "world_name": str(config.get("scenario_meta", {}).get("world_name", "")),
            "world_id": str(config.get("scenario_meta", {}).get("world_id", "")),
            "seed": int(runtime_seed) if str(runtime_seed).strip().isdigit() else str(runtime_seed).strip(),
            "package_name": str(package_meta.get("package_name", "") or metadata.get("package_name", "")),
            "source_label": str(package_meta.get("source_label", "") or metadata.get("source_label", "")),
            "asset_base_url": str(metadata.get("asset_base_url", "")),
            "map_grid_url": str(metadata.get("map_grid_url", "")),
            "world_config_url": str(metadata.get("world_config_url", "")),
            "live_session_url": f"/api/pixel/worlds/{normalized}/live/sessions",
            "live_state_url": f"/api/pixel/worlds/{normalized}/live/state",
            "live_action_url": f"/api/pixel/worlds/{normalized}/live/actions",
            "live_ws_url_template": f"/api/pixel/worlds/{normalized}/live/ws/{{session_id}}",
            "pixel_read": True,
            "pixel_read_report": report,
            "validation_probe": _metadata_bool(package_meta, "validation_probe") is True,
            "package_db": str(package_db),
        }
    except Exception:
        return None


def _pixel_world_detail_payload(
    *,
    access_code: str,
    config: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, object]:
    normalized = str(access_code).strip()
    runtime_seed = config.get("runtime", {}).get("seed", "")
    return {
        "status": "ok",
        "access_code": normalized,
        "created_at": str(metadata.get("created_at", "")),
        "world_name": str(config.get("scenario_meta", {}).get("world_name", "")),
        "world_id": str(config.get("scenario_meta", {}).get("world_id", "")),
        "seed": int(runtime_seed) if str(runtime_seed).strip().isdigit() else str(runtime_seed).strip(),
        "package_name": str(metadata.get("package_name", "")),
        "source_label": str(metadata.get("source_label", "")),
        "pixel_read": bool(metadata.get("pixel_read", False)),
        "package": metadata,
        "world_config": config,
        "asset_base_url": str(metadata.get("asset_base_url", "")),
        "map_grid_url": str(metadata.get("map_grid_url", "")),
        "world_config_url": str(metadata.get("world_config_url", "")),
        "live_session_url": f"/api/pixel/worlds/{normalized}/live/sessions",
        "live_state_url": f"/api/pixel/worlds/{normalized}/live/state",
        "live_action_url": f"/api/pixel/worlds/{normalized}/live/actions",
        "live_ws_url_template": f"/api/pixel/worlds/{normalized}/live/ws/{{session_id}}",
    }


def _pixel_live_store(access_code: str):
    return get_pixel_live_store(str(serve_macro_ui.MACRO_PACKAGE_ROOT), str(access_code).strip())


@router.get("/worlds")
def api_pixel_worlds() -> dict[str, object]:
    return {"worlds": serve_macro_ui._latest_pixel_world_records()}


@router.get("/worlds/{access_code}")
def api_pixel_world(access_code: str) -> dict[str, object]:
    normalized = _require_latest_pixel_world_access_code(access_code)
    try:
        export_dir = _package_export_dir(normalized)
        package_db = export_dir / "world_package.db"
        package_meta = serve_macro_ui.read_world_package_metadata(package_db)
        workspace = serve_macro_ui._pixel_world_workspace(normalized)
        config, metadata = serve_macro_ui.load_world_config_from_access_code(serve_macro_ui.MACRO_PACKAGE_ROOT, normalized, materialize_dir=workspace)
        report = _metadata_json(package_meta, "pixel_read_report")
        if report is None:
            report = serve_macro_ui.assess_pixel_readiness_from_root(workspace)
        if not bool(report.get("pixel_read", False)):
            raise HTTPException(status_code=404, detail=f"Pixel world not ready: {normalized}")
        metadata["pixel_read"] = True
        metadata["pixel_read_report"] = report
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _pixel_world_detail_payload(
        access_code=normalized,
        config=config,
        metadata=metadata,
    )


@router.post("/worlds/{access_code}/live/sessions")
def api_create_live_session(access_code: str, request: PixelLiveSessionCreateRequest) -> dict[str, object]:
    started_at = time.perf_counter()
    normalized = _require_latest_pixel_world_access_code(access_code)
    try:
        store = _pixel_live_store(normalized)
        payload = store.create_session(
            display_name=request.display_name,
            room_id=request.room_id,
            speed_seconds_per_round=float(request.speed_seconds_per_round),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        message = str(exc)
        if "world full" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=500, detail=message) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    session = payload.get("session", {}) if isinstance(payload.get("session", {}), dict) else {}
    session_id = str(session.get("session_id", "")).strip()
    return _with_server_timing(
        {
            "status": "ok",
            "session": session,
            "state": payload,
            "realtime": {
                "enabled": True,
                "transport": "websocket",
                "tick_interval_ms": 50,
                "flush_interval_ms": 1000,
                "ws_url": f"/api/pixel/worlds/{normalized}/live/ws/{session_id}" if session_id else "",
            },
        },
        started_at,
    )


@router.post("/worlds/{access_code}/live/sessions/{session_id}/heartbeat")
def api_live_session_heartbeat(access_code: str, session_id: str) -> dict[str, object]:
    started_at = time.perf_counter()
    normalized = _require_latest_pixel_world_access_code(access_code)
    if not str(session_id).strip():
        raise HTTPException(status_code=400, detail="session_id is required")
    try:
        store = _pixel_live_store(normalized)
        payload = store.heartbeat(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _with_server_timing({"status": "ok", "state": payload}, started_at)


@router.delete("/worlds/{access_code}/live/sessions/{session_id}")
def api_live_session_release(access_code: str, session_id: str) -> dict[str, object]:
    normalized = _require_latest_pixel_world_access_code(access_code)
    if not str(session_id).strip():
        raise HTTPException(status_code=400, detail="session_id is required")
    try:
        store = _pixel_live_store(normalized)
        payload = store.release_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return payload


@router.get("/worlds/{access_code}/live/state")
def api_live_state(
    access_code: str,
    session_id: str,
    since: int = 0,
    compact: int = 0,
    if_world_revision: int = 0,
) -> dict[str, object]:
    started_at = time.perf_counter()
    normalized = _require_latest_pixel_world_access_code(access_code)
    if not str(session_id).strip():
        raise HTTPException(status_code=400, detail="session_id is required")
    try:
        store = _pixel_live_store(normalized)
        payload = store.state_payload(
            session_id,
            since=max(0, int(since)),
            compact=bool(int(compact)),
            if_world_revision=max(0, int(if_world_revision)),
        )
        return _with_server_timing(payload, started_at)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/worlds/{access_code}/live/actions")
def api_live_action(access_code: str, request: PixelLiveActionRequest) -> dict[str, object]:
    started_at = time.perf_counter()
    normalized = _require_latest_pixel_world_access_code(access_code)
    session_id = str(request.session_id).strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    try:
        store = _pixel_live_store(normalized)
        payload = store.submit_action(
            session_id=session_id,
            payload=request.model_dump(),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    result = dict(payload if isinstance(payload, dict) else {})
    result.setdefault("status", "ok")
    return _with_server_timing(result, started_at)


@router.get("/worlds/{access_code}/files/{file_path:path}")
def api_pixel_world_file(access_code: str, file_path: str) -> FileResponse:
    normalized = _require_latest_pixel_world_access_code(access_code)
    workspace = serve_macro_ui._pixel_world_workspace(normalized)
    candidate = (workspace / file_path).resolve()
    try:
        candidate.relative_to(workspace.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid file path") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    return FileResponse(str(candidate))
