#!/usr/bin/env python3
"""Generate a replaceable guild asset set: one map plus selected agent atlases."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps


def _load_runtime_clients():
    package_root = Path(__file__).resolve().parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from agora_ui.run_interaction_simulation import VertexJsonClient, VertexSDKImageClient

    return VertexJsonClient, VertexSDKImageClient


def _load_map_renderer():
    package_root = Path(__file__).resolve().parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from asset_pipeline.map_rendering.compositor import render_component_icon, render_map_asset

    return render_map_asset, render_component_icon


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _endpoint_port(endpoint: str) -> int | None:
    parsed = urlparse(str(endpoint or "").strip())
    if parsed.port is not None:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    return None


def _append_timing_event(
    output_path: Path,
    *,
    stage: str,
    status: str,
    started_at: str,
    duration_seconds: float,
    endpoint: str = "",
    adapter: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    payload = {
        "stage": stage,
        "status": status,
        "started_at": started_at,
        "duration_seconds": round(float(duration_seconds), 3),
        "endpoint": str(endpoint or "").strip(),
        "port": _endpoint_port(endpoint),
        "adapter": str(adapter or "").strip(),
        "details": details or {},
    }
    path = output_path.parent / "timing_trace.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _locate_package_root(config_path: Path) -> Path:
    current = config_path.resolve()
    for candidate in [current.parent, *current.parents]:
        if (candidate / "agora_ui").is_dir() and (candidate / "asset_pipeline").is_dir():
            return candidate
    raise RuntimeError(f"Could not locate Agora_UI package root from config path: {config_path}")


def _browser_asset_url(package_root: Path, target_path: Path) -> str:
    relative = target_path.resolve().relative_to((package_root / "frontend").resolve())
    return f"./{relative.as_posix()}"


def _request_gemini_text(prompt: str, *, world_config: dict[str, Any], output_path: Path) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    started_perf = time.perf_counter()
    endpoint = str(world_config.get("vertex_api", {}).get("endpoint_base", "")).strip()
    event_status = "error"
    VertexJsonClient, _ = _load_runtime_clients()
    client = VertexJsonClient(world_config)
    schema = {"prompt_text": "string, one polished map asset prompt"}
    try:
        generated = client.generate_compact_json(
            system_instruction="You write one clean map-art prompt as strict JSON.",
            prompt=prompt,
            schema=schema,
            stage="image_prompt_generation",
        )
        _write_json(output_path, generated)
        event_status = "ok"
        return {"status": "ok", "text": str(generated.get("prompt_text", "")).strip() or prompt, "response_path": str(output_path)}
    finally:
        _append_timing_event(
            output_path,
            stage="map_prompt_generation",
            status=event_status,
            started_at=started_at,
            duration_seconds=time.perf_counter() - started_perf,
            endpoint=endpoint,
            adapter="gemini_image_prompt",
        )


def _request_flux_map(prompt: str, *, endpoint: str, output_path: Path) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    started_perf = time.perf_counter()
    event_status = "error"
    payload = {
        "prompt": prompt,
        "negative_prompt": "text, watermark, blurry, anti-aliased, realistic photo texture",
        "width": 1024,
        "height": 1024,
        "steps": 8,
        "guidance_scale": 0.0,
        "output_path": str(output_path),
        "return_base64": False,
        "asset_kind": "map_asset",
    }
    try:
        response = requests.post(f"{endpoint.rstrip('/')}/generate", json=payload, timeout=1200)
        response.raise_for_status()
        event_status = "ok"
        return response.json()
    finally:
        _append_timing_event(
            output_path,
            stage="map_image_generation",
            status=event_status,
            started_at=started_at,
            duration_seconds=time.perf_counter() - started_perf,
            endpoint=endpoint,
            adapter="flux_local_service",
        )


def _generate_ai_map(
    prompt: str,
    *,
    world_config: dict[str, Any],
    pipeline: dict[str, Any],
    output_path: Path,
    batch_root: Path,
) -> dict[str, Any]:
    map_config = pipeline.get("map_generation", {})
    map_adapter = str(map_config.get("adapter", "")).strip() or "vertex_sdk_image"
    
    # Check if local FLUX service is configured and preferred
    flux_endpoint = str(map_config.get("endpoint", "")).strip()
    if not flux_endpoint:
        flux_endpoint = str(pipeline.get("sprite_generation", {}).get("endpoint", "")).strip()
    if not flux_endpoint:
        flux_endpoint = str(world_config.get("image_generation", {}).get("endpoint", "")).strip()
        
    if map_adapter == "flux_local_service" or (flux_endpoint and not world_config.get("image_generation", {}).get("endpoint_base")):
        if not flux_endpoint:
            raise ValueError("Missing endpoint for local FLUX map generation.")
        return _request_flux_map(prompt, endpoint=flux_endpoint, output_path=output_path)

    
    # Default to Vertex AI Image SDK
    _, VertexSDKImageClient = _load_runtime_clients()
    image_client = VertexSDKImageClient(world_config)
    started_at = datetime.now(timezone.utc).isoformat()
    started_perf = time.perf_counter()
    event_status = "error"
    try:
        result = image_client.generate_image(
            prompt=(
                f"{prompt}\n"
                "Create a high-quality top-down fantasy/retro-styled video game map source image. "
                "Ensure clean, beautiful layout without any overlays, text labels, UI chrome, or watermarks."
            ),
            job_dir=batch_root,
            filename_stem=output_path.stem,
        )
        _write_json(batch_root / "vertex_map_response.json", result)
        generated_path = Path(str(result.get("image_path", "")).strip())
        if generated_path.is_file() and generated_path != output_path:
            output_path.write_bytes(generated_path.read_bytes())
        event_status = "ok"
        return {
            "status": "ok",
            "adapter": "vertex_sdk_image",
            "output_path": str(output_path),
            "response_path": str(batch_root / "vertex_map_response.json"),
        }
    finally:
        _append_timing_event(
            output_path,
            stage="map_image_generation",
            status=event_status,
            started_at=started_at,
            duration_seconds=time.perf_counter() - started_perf,
            endpoint=str(world_config.get("image_generation", {}).get("endpoint_base", "")).strip(),
            adapter="vertex_sdk_image",
        )



def _render_structured_map(
    *,
    map_grid: dict[str, Any],
    pipeline: dict[str, Any],
    room_loot: list[dict[str, Any]],
    component_icons: dict[str, str],
    output_path: Path,
) -> dict[str, Any]:
    render_map_asset, _ = _load_map_renderer()
    map_config = dict(pipeline.get("map_generation", {}))
    render_map_asset(
        map_grid=map_grid,
        output_path=output_path,
        tile_px=int(map_config.get("tile_px", 32)),
        margin_px=int(map_config.get("margin_px", 56)),
        background_hex=str(map_config.get("background_hex", "#efe1c4")),
        component_library=map_config.get("component_library", {}),
        world_terrain=map_config.get("world_terrain", {}),
        room_loot=room_loot,
        component_icons=component_icons,
    )
    return {
        "status": "ok",
        "adapter": str(map_config.get("adapter", "room_part_compositor")),
        "output_path": str(output_path),
        "tile_px": int(map_config.get("tile_px", 32)),
        "margin_px": int(map_config.get("margin_px", 56)),
    }


def _room_loot(world_config: dict[str, Any]) -> list[dict[str, Any]]:
    frontend = world_config.get("pixel_asset_pipeline", {}).get("frontend", {})
    pov_modules = frontend.get("pov_local_modules", {})
    inventory_exchange = pov_modules.get("inventory_exchange", {})
    return [entry for entry in inventory_exchange.get("room_loot", []) if isinstance(entry, dict)]


def _component_jobs(map_grid: dict[str, Any], pipeline: dict[str, Any], room_loot: list[dict[str, Any]]) -> list[dict[str, Any]]:
    map_config = pipeline.get("map_generation", {})
    library = map_config.get("component_library", {})
    prop_library = library.get("props", {})
    pickup_library = library.get("pickup_items", {})
    room_presets = library.get("room_layout_presets", {})
    archetype_presets = library.get("room_archetype_presets", {})
    jobs: dict[str, dict[str, Any]] = {}

    def register(component_id: str, component_type: str, label: str) -> None:
        key = f"{component_type}:{component_id}"
        if key not in jobs:
            jobs[key] = {
                "component_id": component_id,
                "component_type": component_type,
                "label": label,
            }

    for room in map_grid.get("rooms", []):
        for decor_tag in room.get("visual", {}).get("decor_tags", []):
            spec = prop_library.get(decor_tag, {})
            register(str(decor_tag), "prop", str(spec.get("label", decor_tag)).strip() or str(decor_tag))
        metadata = room.get("metadata", {}) if isinstance(room.get("metadata", {}), dict) else {}
        archetype = str(metadata.get("room_archetype", "")).strip()
        if archetype and isinstance(archetype_presets.get(archetype), dict):
            for entry in archetype_presets.get(archetype, {}).get("supplemental_props", []):
                component_id = str(entry.get("component_id", "")).strip()
                if component_id:
                    spec = prop_library.get(component_id, {})
                    register(component_id, "prop", str(spec.get("label", component_id)).strip() or component_id)
        preset = room_presets.get(room.get("room_id", ""), {})
        for entry in preset.get("supplemental_props", []):
            component_id = str(entry.get("component_id", "")).strip()
            if component_id:
                spec = prop_library.get(component_id, {})
                register(component_id, "prop", str(spec.get("label", component_id)).strip() or component_id)

    for loot in room_loot:
        item_id = str(loot.get("item_id", "")).strip()
        if not item_id:
            continue
        spec = pickup_library.get(item_id, {})
        register(item_id, "pickup", str(spec.get("label", loot.get("label", item_id))).strip() or item_id)

    return sorted(jobs.values(), key=lambda entry: (entry["component_type"], entry["component_id"]))


def _generate_local_component_icons(
    *,
    pipeline: dict[str, Any],
    map_grid: dict[str, Any],
    room_loot: list[dict[str, Any]],
    batch_root: Path,
) -> dict[str, Any]:
    _, render_component_icon = _load_map_renderer()
    map_config = pipeline.get("map_generation", {})
    library = map_config.get("component_library", {})
    prop_library = library.get("props", {})
    pickup_library = library.get("pickup_items", {})
    jobs = _component_jobs(map_grid, pipeline, room_loot)
    icon_root = batch_root / "component_generation" / "local_icons"
    icons: dict[str, str] = {}
    records: list[dict[str, Any]] = []

    for job in jobs:
        component_id = str(job["component_id"])
        if job["component_type"] == "prop":
            spec = prop_library.get(component_id, {})
        else:
            spec = pickup_library.get(component_id, {})
        render_name = str(spec.get("render", "quest_notice"))
        output_path = icon_root / f"{job['component_type']}_{component_id}.png"
        render_component_icon(
            render_name=render_name,
            output_path=output_path,
            icon_px=int(map_config.get("component_generation", {}).get("icon_px", 96)),
        )
        icons[component_id] = str(output_path)
        records.append({
            **job,
            "status": "ok",
            "source": "local_preset",
            "render_name": render_name,
            "icon_path": str(output_path),
        })

    manifest = {
        "status": "ok",
        "backend": "local_preset",
        "coverage": "full",
        "jobs": records,
        "icons": icons,
    }
    _write_json(batch_root / "component_generation" / "local_component_generation_manifest.json", manifest)
    return manifest


def _strip_near_white_background(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = []
    for red, green, blue, alpha in rgba.getdata():
        near_white = red >= 242 and green >= 242 and blue >= 242 and max(red, green, blue) - min(red, green, blue) <= 18
        pixels.append((red, green, blue, 0 if near_white else alpha))
    rgba.putdata(pixels)
    return rgba


def _alpha_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value >= 8 else 0)
    return mask.getbbox()


def _prepare_component_icon(source_path: Path, output_path: Path, *, icon_px: int = 96) -> Path:
    image = Image.open(source_path).convert("RGBA")
    image = _strip_near_white_background(image)
    bbox = _alpha_bbox(image)
    if bbox is not None:
        image = image.crop(bbox)
    fitted = ImageOps.contain(image, (icon_px, icon_px), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (icon_px, icon_px), (0, 0, 0, 0))
    canvas.paste(fitted, ((icon_px - fitted.width) // 2, (icon_px - fitted.height) // 2), fitted)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return output_path


def _component_prompt(job: dict[str, Any], *, world_name: str) -> str:
    label = str(job.get("label", job.get("component_id", "component"))).strip()
    if job.get("component_type") == "pickup":
        return (
            f"Top-down fantasy JRPG pickup icon for {label} in {world_name}. "
            "Render one isolated prop only, centered, readable silhouette, pixel-friendly shape language, "
            "plain white background, no text, no watermark, no hands holding it."
        )
    return (
        f"Top-down fantasy JRPG room prop for {label} in {world_name}. "
        "Render one isolated environment prop only, centered, readable silhouette, pixel-friendly shape language, "
        "plain white background, no text, no watermark, no room background."
    )


def _generate_component_icons(
    *,
    world_config: dict[str, Any],
    pipeline: dict[str, Any],
    map_grid: dict[str, Any],
    room_loot: list[dict[str, Any]],
    batch_root: Path,
) -> dict[str, Any]:
    map_config = pipeline.get("map_generation", {})
    generation = map_config.get("component_generation", {})
    jobs = _component_jobs(map_grid, pipeline, room_loot)
    manifest = {
        "status": "skipped",
        "enabled": bool(generation.get("enabled", False)),
        "backend": str(generation.get("backend", "")),
        "jobs": [],
        "icons": {},
    }
    if not generation.get("enabled"):
        return manifest

    _, VertexSDKImageClient = _load_runtime_clients()
    component_world_config = json.loads(json.dumps(world_config))
    component_world_config["image_generation"] = {
        **world_config.get("image_generation", {}),
        **generation,
    }
    raw_root = batch_root / "component_generation" / "raw"
    icon_root = batch_root / "component_generation" / "icons"
    world_name = world_config.get("scenario_meta", {}).get("world_name", "Agora world")
    try:
        client = VertexSDKImageClient(component_world_config)
    except Exception as error:
        manifest["status"] = "skipped"
        manifest["reason"] = str(error)
        return manifest

    manifest["status"] = "ok"
    for job in jobs:
        component_id = str(job["component_id"])
        filename_stem = f"{job['component_type']}_{component_id}"
        raw_path = raw_root / f"{filename_stem}.png"
        icon_path = icon_root / f"{filename_stem}.png"
        record = dict(job)
        try:
            result = client.generate_image(
                prompt=_component_prompt(job, world_name=world_name),
                job_dir=raw_root,
                filename_stem=filename_stem,
            )
            generated_path = Path(str(result.get("image_path", raw_path)).strip() or raw_path)
            if generated_path.suffix.lower() != ".png" and generated_path.is_file():
                raw_path.write_bytes(generated_path.read_bytes())
                generated_path = raw_path
            processed = _prepare_component_icon(generated_path, icon_path, icon_px=int(generation.get("icon_px", 96)))
            record["status"] = "ok"
            record["raw_path"] = str(generated_path)
            record["icon_path"] = str(processed)
            manifest["icons"][component_id] = str(processed)
        except Exception as error:
            record["status"] = "error"
            record["reason"] = str(error)
        manifest["jobs"].append(record)
    _write_json(batch_root / "component_generation" / "component_generation_manifest.json", manifest)
    return manifest


def _default_agent_ids() -> list[str]:
    return [
        "world_main_hero",
        "world_main_princess",
        "world_main_cadre",
        "world_001",
        "world_002",
        "world_003",
        "world_004",
        "world_005",
        "world_006",
        "world_007",
    ]


def _manifest_agent_ids(scenario_dir: Path) -> list[str]:
    manifest = _read_json(scenario_dir / "manifest.json")
    active_agents = manifest.get("asset_bindings", {}).get("active_agents", [])
    agent_ids: list[str] = []
    for ref in active_agents:
        path = Path(str(ref))
        stem = path.stem.strip()
        if stem:
            agent_ids.append(stem)
    return agent_ids


def _write_current_alias(package_root: Path, manifest_path: Path) -> None:
    payload = _read_json(manifest_path)
    alias_paths = [
        package_root / "frontend" / "assets" / "generated" / "world_asset_sets" / "current_world_pixel_set.json",
        package_root / "frontend" / "assets" / "generated" / "world_asset_sets" / "current_world_pixel_set.json",
    ]
    for alias_path in alias_paths:
        _write_json(alias_path, payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--scenario-dir", required=True)
    parser.add_argument("--revision", default=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--agent-id", action="append", dest="agent_ids", default=[])
    parser.add_argument("--remote-agent-id", action="append", dest="remote_agent_ids", default=[])
    parser.add_argument("--all-active-agents", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--update-current-alias", action="store_true")
    parser.add_argument("--reuse-latest-raw-sheet", action="store_true")
    parser.add_argument("--skip-map-prompt", action="store_true")
    parser.add_argument("--allow-partial-success", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    scenario_dir = Path(args.scenario_dir).resolve()
    package_root = _locate_package_root(config_path)
    world_config = _read_json(config_path)
    map_grid = _read_json(scenario_dir / "map_grid.json")
    scenario_manifest = _read_json(scenario_dir / "manifest.json")
    pipeline = world_config.get("pixel_asset_pipeline", {})
    room_loot = _room_loot(world_config)
    if args.all_active_agents:
        selected_agent_ids = _manifest_agent_ids(scenario_dir)
    else:
        selected_agent_ids = args.agent_ids or _default_agent_ids()
    if args.limit > 0:
        selected_agent_ids = selected_agent_ids[: args.limit]
    remote_agent_ids = {agent_id for agent_id in args.remote_agent_ids if agent_id}

    batch_root = package_root / "frontend" / "assets" / "generated" / "world_asset_sets" / args.revision
    batch_root.mkdir(parents=True, exist_ok=True)

    rooms = map_grid.get("rooms", [])
    world_name = world_config.get("scenario_meta", {}).get("world_name", "Agora Guild")
    room_lines = []
    for room in rooms[:100]:
        if not isinstance(room, dict):
            continue
        visual = room.get("visual", {})
        room_lines.append(
            f"{room.get('name', room.get('room_id', 'room'))}: biome={visual.get('biome', '')}, "
            f"decor={', '.join(visual.get('decor_tags', []))}, palette={visual.get('ambient_palette', '')}"
        )
    map_prompt = (
        f"Write one strong image-generation prompt for a top-down fantasy guild map key art for {world_name}. "
        f"It should feel like a readable, pixel-friendly game map source image with rooms, corridors, props, and spatial identity. "
        f"Important rooms: {'; '.join(room_lines)}. No visible text or labels."
    )
    if args.skip_map_prompt:
        map_prompt_result = {"status": "skipped", "reason": "skip_map_prompt enabled", "text": map_prompt}
    else:
        try:
            map_prompt_result = _request_gemini_text(
                map_prompt,
                world_config=world_config,
                output_path=batch_root / "map_prompt_response.json",
            )
        except Exception as error:
            map_prompt_result = {"status": "skipped", "reason": str(error), "text": map_prompt}
    local_component_manifest = _generate_local_component_icons(
        pipeline=pipeline,
        map_grid=map_grid,
        room_loot=room_loot,
        batch_root=batch_root,
    )
    component_generation_manifest = _generate_component_icons(
        world_config=world_config,
        pipeline=pipeline,
        map_grid=map_grid,
        room_loot=room_loot,
        batch_root=batch_root,
    )
    combined_component_icons = dict(local_component_manifest.get("icons", {}))
    combined_component_icons.update(component_generation_manifest.get("icons", {}))
    map_source_path = batch_root / "world_map_source.png"
    map_config = pipeline.get("map_generation", {})
    map_adapter = str(map_config.get("adapter", "room_part_compositor"))
    
    if False: # map_adapter in {"vertex_sdk_image", "flux_local_service"} and not args.skip_map_prompt and map_prompt_result.get("status") == "ok":
        pass
    else:
        print(f"[MAP_PIPELINE] Using structured procedural map renderer (adapter: {map_adapter})", flush=True)
        map_render_result = _render_structured_map(
            map_grid=map_grid,
            pipeline=pipeline,
            room_loot=room_loot,
            component_icons=combined_component_icons,
            output_path=map_source_path,
        )


    manifest = {
        "revision": args.revision,
        "world_revision": args.revision,
        "world_id": str(world_config.get("scenario_meta", {}).get("world_id", "")),
        "world_name": world_name,
        "map_prompt": map_prompt_result,
        "local_component_generation": local_component_manifest,
        "component_generation": component_generation_manifest,
        "map_render_result": map_render_result,
        "map_source_path": str(map_source_path),
        "map_asset_url": _browser_asset_url(package_root, map_source_path),
        "agents": [],
        "assets": [],
    }

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{package_root}:{env.get('PYTHONPATH', '')}".rstrip(":")

    def run_agent_generation(index: int, agent_id: str) -> tuple[int, dict[str, Any], dict[str, Any] | None]:
        started_at = datetime.now(timezone.utc).isoformat()
        started_perf = time.perf_counter()
        cmd = [
            sys.executable,
            str(package_root / "asset_pipeline" / "generate_agent_assets.py"),
            "--config",
            str(config_path),
            "--scenario-dir",
            str(scenario_dir),
            "--agent-id",
            agent_id,
            "--revision",
            args.revision,
        ]
        from asset_pipeline.agent_assets.compositor import _find_latest_raw_sheet
        has_reusable = _find_latest_raw_sheet(package_root, agent_id, exclude_revision=None) is not None

        should_reuse = bool(args.reuse_latest_raw_sheet) and has_reusable
        if should_reuse:
            cmd.append("--reuse-latest-raw-sheet")
        else:
            cmd.append("--invoke-remote")
        if index == 0:
            cmd.append("--write-frontend-bootstrap")
        result = subprocess.run(cmd, cwd=str(package_root), env=env, capture_output=True, text=True, check=False)
        agent_record = {
            "agent_id": agent_id,
            "returncode": result.returncode,
            "duration_seconds": round(time.perf_counter() - started_perf, 3),
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
            "publishable": False,
        }
        _append_timing_event(
            batch_root / "world_asset_set_manifest.json",
            stage="agent_asset_subprocess",
            status=("ok" if result.returncode == 0 else "error"),
            started_at=started_at,
            duration_seconds=time.perf_counter() - started_perf,
            adapter="generate_agent_assets",
            details={"agent_id": agent_id},
        )
        asset_bundle = package_root / "frontend" / "assets" / "generated" / agent_id / args.revision / "asset_bundle.json"
        if result.returncode == 0 and asset_bundle.is_file():
            agent_record["asset_bundle_path"] = str(asset_bundle)
            agent_record["asset_bundle"] = _read_json(asset_bundle)
            agent_record["quality_summary"] = agent_record["asset_bundle"].get("quality_summary", {})
            event_payload = agent_record["asset_bundle"].get("event")
            sprite_summary = agent_record["asset_bundle"].get("sprite_summary", {})
            reused_raw_summary = agent_record["asset_bundle"].get("reused_raw_summary", {})
            sprite_status = str(sprite_summary.get("status", "")).strip().lower()
            sprite_source = str(sprite_summary.get("source", "")).strip().lower()
            reused_status = str(reused_raw_summary.get("status", "")).strip().lower()
            bundle_publishable = isinstance(event_payload, dict)
            if bundle_publishable:
                agent_record["publishable"] = True
                return index, agent_record, event_payload
        elif result.returncode == 0:
            agent_record["returncode"] = 1
            stderr = str(agent_record.get("stderr", "") or "").strip()
            agent_record["stderr"] = f"{stderr}\nExpected bundle missing after successful subprocess exit: {asset_bundle}".strip()
        return index, agent_record, None

    indexed_records: list[dict[str, Any] | None] = [None] * len(selected_agent_ids)
    publishable_events: list[dict[str, Any]] = []
    max_workers = max(1, int(args.max_workers))
    if max_workers == 1:
        for index, agent_id in enumerate(selected_agent_ids):
            result_index, agent_record, event_payload = run_agent_generation(index, agent_id)
            indexed_records[result_index] = agent_record
            if isinstance(event_payload, dict):
                publishable_events.append(event_payload)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(run_agent_generation, index, agent_id): (index, agent_id)
                for index, agent_id in enumerate(selected_agent_ids)
            }
            for future in as_completed(future_map):
                result_index, agent_record, event_payload = future.result()
                indexed_records[result_index] = agent_record
                if isinstance(event_payload, dict):
                    publishable_events.append(event_payload)

    manifest["agents"] = [record for record in indexed_records if isinstance(record, dict)]
    manifest["assets"] = publishable_events
    failed_agent_ids = [
        str(record.get("agent_id", "")).strip()
        for record in manifest["agents"]
        if int(record.get("returncode", 0) or 0) != 0 or not bool(record.get("publishable", False))
    ]

    quality_summaries = [record.get("quality_summary", {}) for record in manifest["agents"] if isinstance(record.get("quality_summary"), dict)]
    sprite_summaries = [record.get("asset_bundle", {}).get("sprite_summary", {}) for record in manifest["agents"] if isinstance(record.get("asset_bundle"), dict)]
    fallback_count = sum(1 for summary in sprite_summaries if summary.get("status") in {"quality_fallback_procedural", "fallback"})

    manifest["quality_summary"] = {
        "agent_count": len(manifest["agents"]),
        "passing_agents": sum(1 for summary in quality_summaries if summary.get("pass") is True),
        "failing_agents": sum(1 for summary in quality_summaries if summary.get("pass") is False),
        "fallback_agents": fallback_count,
        "remote_agent_ids": sorted(remote_agent_ids),
        "reuse_latest_raw_sheet": bool(args.reuse_latest_raw_sheet),
        "max_workers": max_workers,
    }

    import math
    allowed_fallbacks = max(3, math.ceil(len(manifest["agents"]) * 0.10))
    if fallback_count > allowed_fallbacks:
        print(f"[QA_FAILURE] Over {allowed_fallbacks} fallback robots generated ({fallback_count} total, threshold 10%). Failing batch QA.", flush=True)
        manifest["status"] = "failed"
        failed_agent_ids.append("QA_FALLBACK_LIMIT_EXCEEDED")
    elif not publishable_events:
        manifest["status"] = "failed"
    elif failed_agent_ids and args.allow_partial_success:
        manifest["status"] = "partial"
    else:
        manifest["status"] = "ok" if not failed_agent_ids else "failed"
    manifest["failed_agent_ids"] = failed_agent_ids
    manifest["requested_agent_ids"] = list(selected_agent_ids)
    manifest["active_agents_from_manifest"] = list(scenario_manifest.get("asset_bindings", {}).get("active_agents", []))
    manifest_path = batch_root / "world_asset_set_manifest.json"
    _write_json(manifest_path, manifest)
    compatibility_manifest = package_root / "frontend" / "assets" / "generated" / "world_asset_sets" / args.revision / "world_asset_set_manifest.json"
    _write_json(compatibility_manifest, manifest)
    if args.update_current_alias:
        _write_current_alias(package_root, manifest_path)
    status = "ok" if manifest["status"] in {"ok", "partial"} else "error"
    print(json.dumps({"status": status, "revision": args.revision, "manifest": str(manifest_path), "failed_agent_ids": failed_agent_ids}, indent=2))
    if manifest["status"] not in {"ok", "partial"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
