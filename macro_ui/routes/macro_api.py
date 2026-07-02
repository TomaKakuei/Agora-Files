from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from agora_ui import world_builder

from macro_ui.build_macro_ui import (
    asset_worker_status,
    build_replay_bundle,
    current_run_record,
    discover_runs,
    generalized_world_config_template,
    launch_asset_bundle_worker,
    load_world_config_from_access_code,
    launch_run_subprocess,
    export_world_package_from_config,
    _merge_json,
)

from macro_ui.components.schemas import (
    RunLaunchRequest,
    AssetWorkerRequest,
    HumanPresenceRequest,
    HumanActionRequest,
    PackageExportRequest,
    WorldBuilderDraftCreateRequest,
    WorldBuilderDraftReviseRequest,
)

# Late import to prevent circular import issues via a lazy proxy
class _LazyServeMacroUi:
    def __getattr__(self, name):
        import macro_ui.serve_macro_ui as serve_macro_ui
        return getattr(serve_macro_ui, name)

serve_macro_ui = _LazyServeMacroUi()

router = APIRouter(prefix="/api")

def _run_dir_for_id(run_id: str) -> Path:
    runs = discover_runs(serve_macro_ui.PACKAGE_ROOT)
    for run in runs:
        if str(run.get("run_id", "")) == run_id:
            return Path(str(run["run_dir"])).resolve()
    raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")


def _human_paths(run_dir: Path) -> dict[str, Path]:
    return {
        "presence": run_dir / "human_presence.json",
        "queue": run_dir / "human_queue.jsonl",
        "history": run_dir / "human_interactions.jsonl",
    }


def _package_export_root() -> Path:
    return serve_macro_ui.PACKAGE_ROOT / "output" / "package_exports"


def _package_export_dir(access_code: str) -> Path:
    return serve_macro_ui._package_export_root() / access_code


@router.get("/runs")
def api_runs() -> dict[str, object]:
    runs = discover_runs(serve_macro_ui.PACKAGE_ROOT)
    return {"runs": runs}


@router.get("/runs/current")
def api_current_run() -> dict[str, object]:
    run = current_run_record(serve_macro_ui.PACKAGE_ROOT)
    if run is None:
        return {"current_run": None}
    return {"current_run": run}


@router.get("/config/template")
def api_config_template() -> dict[str, object]:
    template = generalized_world_config_template(serve_macro_ui.PACKAGE_ROOT)
    return {
        "world_config": template,
        "section_order": list(template.keys()),
        "readme_url": "/README.md",
    }


@router.post("/world-builder/drafts")
def api_world_builder_create_draft(request: WorldBuilderDraftCreateRequest) -> dict[str, object]:
    try:
        return world_builder.create_draft(serve_macro_ui.PACKAGE_ROOT, request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/world-builder/drafts/{draft_id}")
def api_world_builder_get_draft(draft_id: str) -> dict[str, object]:
    try:
        return world_builder.get_draft_response(serve_macro_ui.PACKAGE_ROOT, draft_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/world-builder/resolve")
def api_world_builder_resolve(identifier: str = "", world_name: str = "", world_id: str = "") -> dict[str, object]:
    try:
        return world_builder.resolve_draft(
            serve_macro_ui.PACKAGE_ROOT,
            identifier=str(identifier or ""),
            world_name=str(world_name or ""),
            world_id=str(world_id or ""),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/world-builder/drafts/{draft_id}/revise")
def api_world_builder_revise_draft(draft_id: str, request: WorldBuilderDraftReviseRequest) -> dict[str, object]:
    if not str(request.feedback or "").strip():
        raise HTTPException(status_code=400, detail="feedback is required")
    try:
        return world_builder.revise_draft(serve_macro_ui.PACKAGE_ROOT, draft_id, str(request.feedback))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/world-builder/drafts/{draft_id}/package")
def api_world_builder_draft_package(draft_id: str) -> FileResponse:
    try:
        package_path = world_builder.draft_package_path(serve_macro_ui.PACKAGE_ROOT, draft_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(str(package_path), filename=f"{draft_id}.db")


@router.post("/world-builder/drafts/{draft_id}/art")
def api_world_builder_launch_art(draft_id: str) -> dict[str, object]:
    try:
        return {
            "draft_id": draft_id,
            "art": world_builder.launch_art_worker(serve_macro_ui.PACKAGE_ROOT, draft_id),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/world-builder/drafts/{draft_id}/art/status")
def api_world_builder_art_status(draft_id: str) -> dict[str, object]:
    try:
        return world_builder.art_status(serve_macro_ui.PACKAGE_ROOT, draft_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/world-builder/drafts/{draft_id}/publish")
def api_world_builder_publish(draft_id: str) -> dict[str, object]:
    try:
        return world_builder.publish_draft(serve_macro_ui.PACKAGE_ROOT, draft_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/world-builder/drafts/{draft_id}/history")
def api_world_builder_history(draft_id: str) -> dict[str, object]:
    try:
        return world_builder.draft_history(serve_macro_ui.PACKAGE_ROOT, draft_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
def api_run_summary(run_id: str) -> dict[str, object]:
    runs = discover_runs(serve_macro_ui.PACKAGE_ROOT)
    for run in runs:
        if str(run.get("run_id", "")) == run_id:
            return {"run": run}
    raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")


@router.get("/runs/{run_id}/config")
def api_run_config(run_id: str) -> dict[str, object]:
    run_dir = _run_dir_for_id(run_id)
    config_path = run_dir / "run_inputs" / "world_config.json"
    if not config_path.is_file():
        raise HTTPException(status_code=404, detail=f"Run config not found: {run_id}")
    return {"run_id": run_id, "config_path": str(config_path), "world_config": json.loads(config_path.read_text(encoding="utf-8"))}


@router.get("/runs/{run_id}/bundle")
def api_run_bundle(run_id: str, force_refresh_images: bool = False, with_images: bool = False) -> JSONResponse:
    runs = discover_runs(serve_macro_ui.PACKAGE_ROOT)
    for run in runs:
        if str(run.get("run_id", "")) != run_id:
            continue
        bundle = build_replay_bundle(
            package_root=serve_macro_ui.PACKAGE_ROOT,
            run_dir=Path(str(run["run_dir"])),
            force_refresh_images=bool(force_refresh_images),
            all_agent_images=True,
            generate_images=bool(with_images),
        )
        return JSONResponse(bundle)
    raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")


@router.post("/packages/export")
def api_export_package(request: PackageExportRequest) -> dict[str, object]:
    world_config = dict(request.world_config or {})
    if not world_config:
        raise HTTPException(status_code=400, detail="world_config is required")
    try:
        metadata = export_world_package_from_config(
            package_root=serve_macro_ui.PACKAGE_ROOT,
            world_config=world_config,
            package_name=str(request.package_name).strip(),
            source_label=str(request.source_label).strip() or "macro_ui_export",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "access_code": metadata.get("access_code", ""), "package": metadata}


@router.get("/packages/{access_code}")
def api_get_package(access_code: str) -> dict[str, object]:
    normalized = str(access_code).strip()
    if len(normalized) != 16:
        raise HTTPException(status_code=400, detail="access code must be 16 characters")
    try:
        from macro_ui.routes.pixel_api import _pixel_world_workspace  # to avoid circular import issues
        export_dir = _package_export_dir(normalized)
        package_db = export_dir / "world_package.db"
        package_meta = read_world_package_metadata(package_db)
        workspace = _pixel_world_workspace(normalized)
        config, metadata = load_world_config_from_access_code(serve_macro_ui.PACKAGE_ROOT, normalized, materialize_dir=workspace)
        report = metadata.get("pixel_read_report")
        if report is None:
            report = serve_macro_ui.assess_pixel_readiness_from_root(workspace)
        metadata["pixel_read"] = bool(report.get("pixel_read", False))
        metadata["pixel_read_report"] = report
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "status": "ok",
        "package": metadata,
        "world_config": config,
        "asset_base_url": metadata.get("asset_base_url", ""),
        "map_grid_url": metadata.get("map_grid_url", ""),
        "world_config_url": metadata.get("world_config_url", ""),
        "live_session_url": f"/api/pixel/worlds/{normalized}/live/sessions",
        "live_state_url": f"/api/pixel/worlds/{normalized}/live/state",
        "live_action_url": f"/api/pixel/worlds/{normalized}/live/actions",
        "live_ws_url_template": f"/api/pixel/worlds/{normalized}/live/ws/{{session_id}}",
    }


@router.get("/packages/{access_code}/db")
def api_get_package_db(access_code: str) -> FileResponse:
    normalized = str(access_code).strip()
    export_dir = _package_export_dir(normalized)
    package_db = export_dir / "world_package.db"
    if not package_db.is_file():
        raise HTTPException(status_code=404, detail=f"Package not found: {normalized}")
    return FileResponse(str(package_db), filename=f"{normalized}.db")


@router.post("/runs")
def api_launch_run(request: RunLaunchRequest) -> dict[str, object]:
    requested_run_id = str(request.run_id).strip()
    resume_run_id = str(request.resume_run_id).strip()
    run_id = requested_run_id or f"scenario_{request.regular_agent_count}_agents_{request.seed}"
    resume_run_dir = None
    if resume_run_id:
        resume_run_dir = _run_dir_for_id(resume_run_id)
        if not requested_run_id or requested_run_id == resume_run_id:
            run_id = f"{resume_run_id}_resume"
    requested_config = dict(request.world_config or {})
    if requested_config:
        scenario_meta = requested_config.setdefault("scenario_meta", {})
        runner = requested_config.setdefault("runner", {})
        if request.world_name.strip():
            scenario_meta["world_name"] = request.world_name.strip()
        if request.world_id.strip():
            scenario_meta["world_id"] = request.world_id.strip()
        if request.description.strip():
            scenario_meta["description"] = request.description.strip()
        if request.domain_label.strip():
            runner["domain_label"] = request.domain_label.strip()
    package_access_code = str(request.package_access_code or "").strip()
    source_config = requested_config
    if package_access_code:
        try:
            package_config, _package_metadata = load_world_config_from_access_code(serve_macro_ui.PACKAGE_ROOT, package_access_code)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        source_config = _merge_json(package_config, requested_config) if requested_config else package_config
    launch_payload = launch_run_subprocess(
        package_root=serve_macro_ui.PACKAGE_ROOT,
        run_id=run_id,
        regular_agent_count=request.regular_agent_count,
        rounds=request.rounds,
        activation_probability=request.activation_probability,
        seed=request.seed,
        main_characters_always_activate=request.main_characters_always_activate,
        max_videos_per_round=request.max_videos_per_round,
        segment_seconds=request.segment_seconds,
        max_images_per_round=request.max_images_per_round,
        source_config=source_config or None,
        package_access_code=package_access_code,
        resume_run_dir=resume_run_dir,
    )
    asset_payload = None
    if request.start_asset_worker:
        asset_payload = launch_asset_bundle_worker(
            package_root=serve_macro_ui.PACKAGE_ROOT,
            run_dir=Path(str(launch_payload["run_dir"])),
            force_refresh_images=False,
        )
    return {"status": "launched", "run_id": run_id, "launch": launch_payload, "asset_worker": asset_payload}


@router.get("/runs/{run_id}/assets/status")
def api_asset_worker_status(run_id: str) -> dict[str, object]:
    run_dir = _run_dir_for_id(run_id)
    return {"run_id": run_id, "asset_worker": asset_worker_status(run_dir)}


@router.post("/runs/{run_id}/assets")
def api_launch_asset_worker(run_id: str, request: AssetWorkerRequest) -> dict[str, object]:
    run_dir = _run_dir_for_id(run_id)
    launch = launch_asset_bundle_worker(
        package_root=serve_macro_ui.PACKAGE_ROOT,
        run_dir=run_dir,
        force_refresh_images=bool(request.force_refresh_images),
    )
    return {"run_id": run_id, "asset_worker": launch}


@router.get("/runs/{run_id}/human")
def api_human_state(run_id: str) -> dict[str, object]:
    run_dir = _run_dir_for_id(run_id)
    paths = _human_paths(run_dir)
    presence = {}
    if paths["presence"].is_file():
        presence = json.loads(paths["presence"].read_text(encoding="utf-8"))
    pending = []
    if paths["queue"].is_file():
        for line in paths["queue"].read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict) and not payload.get("consumed", False):
                pending.append(payload)
    return {"run_id": run_id, "presence": presence, "pending_events": pending}


@router.post("/runs/{run_id}/human/presence")
def api_human_presence(run_id: str, request: HumanPresenceRequest) -> dict[str, object]:
    run_dir = _run_dir_for_id(run_id)
    paths = _human_paths(run_dir)
    payload = request.model_dump()
    paths["presence"].write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"run_id": run_id, "presence": payload}


@router.post("/runs/{run_id}/human/actions")
def api_human_action(run_id: str, request: HumanActionRequest) -> dict[str, object]:
    run_dir = _run_dir_for_id(run_id)
    paths = _human_paths(run_dir)
    presence_payload = {
        "display_name": request.display_name,
        "room_id": request.room_id,
        "coordinates": request.coordinates or {},
        "speed_seconds_per_round": request.speed_seconds_per_round,
        "current_focus": request.action_text,
    }
    paths["presence"].write_text(json.dumps(presence_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    event = {
        "display_name": request.display_name,
        "room_id": request.room_id,
        "coordinates": request.coordinates or {},
        "target_agent_id": request.target_agent_id,
        "action_text": request.action_text,
        "speed_seconds_per_round": request.speed_seconds_per_round,
        "consumed": False,
    }
    paths["queue"].parent.mkdir(parents=True, exist_ok=True)
    with paths["queue"].open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return {"run_id": run_id, "queued_event": event}
