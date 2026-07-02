#!/usr/bin/env python3
"""Serve the Agora_UI macro UI with replay and run-launch APIs."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from agora_ui.live_world import shutdown_registered_live_stores

from macro_ui.routes.websocket import PixelLiveWebSocketManager
from macro_ui.components.html_utils import (
    _pixel_bundle_version,
    _creator_bundle_version,
    _render_versioned_html,
)

# Import routes
from macro_ui.routes import pixel_api, macro_api, websocket, testing

from agora_ui.package_db import (
    assess_pixel_readiness_from_root,
    ensure_materialized_world_package,
    materialize_world_package,
    read_world_package_metadata,
)
from agora_ui.live_world import get_pixel_live_store
from agora_ui import world_builder
from macro_ui.build_macro_ui import (
    load_world_config_from_access_code,
    _merge_json,
)

# Preserve complete namespace compatibility for unit tests and external scripts
from macro_ui.components.schemas import *

from macro_ui.routes.pixel_api import (
    _package_export_root,
    _package_export_dir,
    _pixel_world_workspace,
    _metadata_bool,
    _metadata_json,
    _pixel_world_template_key,
    _pixel_world_sort_key,
    _pixel_world_is_public,
    _all_pixel_world_records,
    _latest_pixel_world_records,
    _canonical_pixel_world_record,
    _require_latest_pixel_world_access_code,
    _pixel_world_record,
    _pixel_world_detail_payload,
    _pixel_live_store,
    api_pixel_worlds,
    api_pixel_world,
    api_create_live_session,
    api_live_session_heartbeat,
    api_live_session_release,
    api_live_state,
    api_live_action,
    api_pixel_world_file,
)

from macro_ui.routes.macro_api import (
    _run_dir_for_id,
    _human_paths,
    api_runs,
    api_current_run,
    api_config_template,
    api_world_builder_create_draft,
    api_world_builder_get_draft,
    api_world_builder_resolve,
    api_world_builder_revise_draft,
    api_world_builder_draft_package,
    api_world_builder_launch_art,
    api_world_builder_art_status,
    api_world_builder_publish,
    api_world_builder_history,
    api_run_summary,
    api_run_config,
    api_run_bundle,
    api_export_package,
    api_get_package,
    api_get_package_db,
    api_launch_run,
    api_asset_worker_status,
    api_launch_asset_worker,
    api_human_state,
    api_human_presence,
    api_human_action,
)

from macro_ui.routes.testing import (
    _HEADLESS_PIXEL_GATES,
    _HEADLESS_PIXEL_RESULTS,
    _HEADLESS_PIXEL_GIF,
    _now_iso_utc,
    _headless_pixel_gate,
    _headless_pixel_result,
    api_headless_pixel_harness,
    api_pixel_live_snapshot,
    api_phaser_minimal,
)
from macro_ui.routes.testing_html import (
    _render_headless_pixel_harness,
    _render_pixel_live_snapshot,
    _render_phaser_minimal_harness,
)
from macro_ui.routes.testing import (
    api_headless_pixel_gate,
    api_headless_pixel_result,
    api_headless_pixel_result_get,
    api_test_pixel_live_seed_inventory,
)

MACRO_PACKAGE_ROOT = Path(os.environ.get("AGORA_MACRO_PACKAGE_ROOT") or Path(__file__).resolve().parent.parent)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8125)
    parser.add_argument("--directory", default=str(PACKAGE_ROOT))
    return parser.parse_args()


app = FastAPI(title="Agora Macro UI")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def start_live_ws_manager() -> None:
    manager = PixelLiveWebSocketManager(MACRO_PACKAGE_ROOT)
    app.state.live_ws_manager = manager
    await manager.start()


@app.on_event("shutdown")
async def stop_live_runtime_workers() -> None:
    manager = getattr(app.state, "live_ws_manager", None)
    if manager is not None:
        await manager.stop()
    shutdown_registered_live_stores()


@app.middleware("http")
async def add_no_store_headers(request: Request, call_next):
    response = await call_next(request)
    path = str(request.url.path or "")
    if path.startswith("/pixel") or path.startswith("/api/pixel") or path.startswith("/__test__/headless-pixel"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# Health Check
@app.get("/api/health")
def api_health() -> dict[str, str]:
    return {"status": "ok"}


# Direct Root & Readme Handlers
@app.get("/")
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/macro/")


@app.get("/README.md")
def readme_file() -> FileResponse:
    return FileResponse(str(PACKAGE_ROOT / "README.md"))


@app.get("/README For LLM.md")
def llm_readme_file() -> FileResponse:
    return FileResponse(str(PACKAGE_ROOT / "README For LLM.md"))


# Index pages with versioned bundle injections
@app.get("/pixel", response_class=HTMLResponse)
@app.get("/pixel/", response_class=HTMLResponse)
@app.get("/pixel/index.html", response_class=HTMLResponse)
def pixel_index() -> HTMLResponse:
    return _render_versioned_html(
        PACKAGE_ROOT / "frontend" / "index.html",
        {"__AGORA_PIXEL_BUNDLE_VERSION__": _pixel_bundle_version()},
    )


@app.get("/creator", response_class=HTMLResponse)
@app.get("/creator/", response_class=HTMLResponse)
@app.get("/creator/index.html", response_class=HTMLResponse)
def creator_index() -> HTMLResponse:
    return _render_versioned_html(
        PACKAGE_ROOT / "world_creator_ui" / "index.html",
        {"__AGORA_CREATOR_BUNDLE_VERSION__": _creator_bundle_version()},
    )


# Include Routers
app.include_router(pixel_api.router)
app.include_router(macro_api.router)
app.include_router(testing.router)
app.include_router(websocket.router)

# --- Hot Reload Endpoint ---
@app.websocket("/_hot_reload")
async def hot_reload_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass

# --- Root Router ---Files
app.mount("/macro", StaticFiles(directory=str(PACKAGE_ROOT / "macro_ui"), html=True), name="macro-static")
app.mount("/creator", StaticFiles(directory=str(PACKAGE_ROOT / "world_creator_ui"), html=True), name="creator-static")
app.mount("/pixel", StaticFiles(directory=str(PACKAGE_ROOT / "frontend"), html=True), name="pixel-static")
app.mount("/output", StaticFiles(directory=str(PACKAGE_ROOT / "output")), name="output-static")
app.mount("/sample_json", StaticFiles(directory=str(PACKAGE_ROOT / "sample_json")), name="sample-json-static")


def main() -> None:
    global MACRO_PACKAGE_ROOT
    args = parse_args()
    if args.directory:
        MACRO_PACKAGE_ROOT = Path(args.directory).resolve()
        if "macro_ui.serve_macro_ui" in sys.modules:
            sys.modules["macro_ui.serve_macro_ui"].MACRO_PACKAGE_ROOT = MACRO_PACKAGE_ROOT
    uvicorn.run(
        "macro_ui.serve_macro_ui:app",
        host=args.bind,
        port=args.port,
        log_level="info",
        reload=True,
        reload_dirs=[str(PACKAGE_ROOT)]
    )


if __name__ == "__main__":
    main()
