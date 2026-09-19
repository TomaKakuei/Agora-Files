#!/usr/bin/env python3
"""Generate a replaceable guild asset set: one map plus selected agent atlases."""

from __future__ import annotations

import argparse
import base64
import hashlib
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

SPRITE_BATCH_QA_CONTRACT_VERSION = "agora.sprite_batch_vision_qa.v3"


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
    map_adapter = str(map_config.get("adapter", "")).strip() or "flux_local_service"

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

    raise RuntimeError(
        f"Unsupported map image adapter {map_adapter!r}; Gemini/Vertex direct image generation is disabled. "
        "Use pixel_asset_pipeline.map_generation.adapter='flux_local_service'."
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
    overlay_supporting_props = _supporting_prop_overlay_enabled(pipeline)
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
        overlay_supporting_props=overlay_supporting_props,
        show_grid_overlay=bool(map_config.get("show_grid_overlay", False)),
    )
    return {
        "status": "ok",
        "adapter": str(map_config.get("adapter", "room_part_compositor")),
        "output_path": str(output_path),
        "tile_px": int(map_config.get("tile_px", 32)),
        "margin_px": int(map_config.get("margin_px", 56)),
        "show_grid_overlay": bool(map_config.get("show_grid_overlay", False)),
        "overlay_supporting_props": overlay_supporting_props,
    }


def _supporting_prop_overlay_enabled(pipeline: dict[str, Any]) -> bool:
    map_config = dict(pipeline.get("map_generation", {}))
    if "overlay_supporting_props" in map_config:
        return bool(map_config.get("overlay_supporting_props"))
    policy_version = str(map_config.get("supporting_prop_policy_version", "")).strip()
    if policy_version:
        return True
    # Legacy packages did not define the collision-aware support policy.
    # Preserve their sparse authored layout instead of changing presentation.
    return False


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

    def register(component_id: str, component_type: str, label: str, spec: dict[str, Any] | None = None) -> None:
        key = f"{component_type}:{component_id}"
        if key not in jobs:
            resolved_spec = spec if isinstance(spec, dict) else {}
            jobs[key] = {
                "component_id": component_id,
                "component_type": component_type,
                "label": label,
                "description": str(resolved_spec.get("description", "")).strip(),
                "semantic_generated": bool(resolved_spec.get("semantic_generated", False)),
                "visual_canon_hash": str(resolved_spec.get("visual_canon_hash", "")).strip(),
            }

    for room in map_grid.get("rooms", []):
        for decor_tag in room.get("visual", {}).get("decor_tags", []):
            spec = prop_library.get(decor_tag, {})
            if isinstance(spec, dict) and spec:
                register(str(decor_tag), "prop", str(spec.get("label", decor_tag)).strip() or str(decor_tag), spec)
        metadata = room.get("metadata", {}) if isinstance(room.get("metadata", {}), dict) else {}
        archetype = str(metadata.get("room_archetype", "")).strip()
        if archetype and isinstance(archetype_presets.get(archetype), dict):
            for entry in archetype_presets.get(archetype, {}).get("supplemental_props", []):
                component_id = str(entry.get("component_id", "")).strip()
                if component_id:
                    spec = prop_library.get(component_id, {})
                    register(component_id, "prop", str(spec.get("label", component_id)).strip() or component_id, spec)
        preset = room_presets.get(room.get("room_id", ""), {})
        for entry in preset.get("supplemental_props", []):
            component_id = str(entry.get("component_id", "")).strip()
            if component_id:
                spec = prop_library.get(component_id, {})
                register(component_id, "prop", str(spec.get("label", component_id)).strip() or component_id, spec)

    for loot in room_loot:
        item_id = str(loot.get("item_id", "")).strip()
        if not item_id:
            continue
        spec = pickup_library.get(item_id, {})
        register(item_id, "pickup", str(spec.get("label", loot.get("label", item_id))).strip() or item_id, spec)

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
    visual_canon = pipeline.get("visual_canon", {}) if isinstance(pipeline.get("visual_canon", {}), dict) else {}
    canon_palette = visual_canon.get("palette", {}) if isinstance(visual_canon.get("palette", {}), dict) else {}
    base_color = str(canon_palette.get("dominant") or canon_palette.get("shadow") or "#5f4634")
    accent_color = str(canon_palette.get("secondary") or canon_palette.get("highlight") or "#f4d3a3")
    detail_color = str(canon_palette.get("accent") or canon_palette.get("highlight") or "#d8a44c")

    for job in jobs:
        if bool(job.get("semantic_generated", False)):
            continue
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
            base_color=base_color,
            accent_color=accent_color,
            detail_color=detail_color,
        )
        icons[component_id] = str(output_path)
        records.append({
            **job,
            "status": "ok",
            "source": "local_preset",
            "render_name": render_name,
            "base_color": base_color,
            "accent_color": accent_color,
            "detail_color": detail_color,
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
    from asset_pipeline.agent_assets.image_processing import _strip_dominant_border_background

    image = Image.open(source_path).convert("RGBA")
    image = _strip_near_white_background(image)
    image = _strip_dominant_border_background(image, tolerance=22)
    bbox = _alpha_bbox(image)
    if bbox is not None:
        image = image.crop(bbox)
    fitted = ImageOps.contain(image, (icon_px, icon_px), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (icon_px, icon_px), (0, 0, 0, 0))
    canvas.paste(fitted, ((icon_px - fitted.width) // 2, (icon_px - fitted.height) // 2), fitted)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return output_path


def _component_prompt(
    job: dict[str, Any],
    *,
    world_name: str,
    visual_canon: dict[str, Any],
    repair_attempt: int = 0,
) -> str:
    label = str(job.get("label", job.get("component_id", "component"))).strip()
    description = str(job.get("description", "")).strip()[:120]
    canon_prefix = str(visual_canon.get("world_prompt_prefix", "")).strip()[:180]
    shared_style = " ".join(canon_prefix.split()[:12])
    if repair_attempt > 0:
        return (
            "FLAT 2D FLOOR-PLAN SPRITE, direct nadir camera. Represent "
            f"{label} only by its compact horizontal footprint and topmost surfaces. "
            "Translate vertical machinery or furniture into an overhead-readable map symbol; collapse height. "
            "No front face, side face, horizon, perspective, room, person, statue, or text. "
            f"Pixel art, isolated on white. Style: {shared_style}."
        )
    if job.get("component_type") == "pickup":
        return (
            "ORTHOGRAPHIC 90-degree overhead pixel icon. One isolated unoccupied inanimate pickup; "
            "top surface and footprint only, no front or side faces. No person, head, face, body, hand, "
            f"statue, text, or scene. {label}: {description}. Style: {shared_style}. White background."
        )
    return (
        "ORTHOGRAPHIC 90-degree overhead pixel icon. One isolated unoccupied inanimate furnishing or machine; "
        "top surface and footprint only, no front or side faces. No person, head, face, body, limb, mannequin, "
        f"statue, text, or scene. {label}: {description}. Style: {shared_style}. White background."
    )


def _semantic_component_job_limit(
    generation: dict[str, Any],
    semantic_job_count: int,
) -> int:
    hard_limit = max(1, int(generation.get("hard_max_jobs", 64) or 64))
    if bool(generation.get("strict_semantic_components", True)):
        if semantic_job_count > hard_limit:
            raise ValueError(
                "Strict semantic component generation exceeds the safety limit: "
                f"required={semantic_job_count}, hard_limit={hard_limit}"
            )
        return max(1, semantic_job_count)
    configured_limit = generation.get("max_jobs")
    if configured_limit is None:
        limit = min(hard_limit, max(1, semantic_job_count))
    else:
        limit = min(hard_limit, max(1, int(configured_limit or 1)))
    return limit


def _generate_component_icons(
    *,
    world_config: dict[str, Any],
    pipeline: dict[str, Any],
    map_grid: dict[str, Any],
    room_loot: list[dict[str, Any]],
    batch_root: Path,
    repair_attempt: int = 0,
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

    flux_endpoint = str(
        generation.get("endpoint")
        or map_config.get("endpoint")
        or pipeline.get("sprite_generation", {}).get("endpoint", "")
        or world_config.get("image_generation", {}).get("endpoint", "")
    ).rstrip("/")
    if not flux_endpoint:
        raise ValueError("Missing endpoint for FLUX component icon generation.")

    raw_root = batch_root / "component_generation" / "raw"
    icon_root = batch_root / "component_generation" / "icons"
    world_name = world_config.get("scenario_meta", {}).get("world_name", "Agora world")
    visual_canon = pipeline.get("visual_canon", {}) if isinstance(pipeline.get("visual_canon", {}), dict) else {}
    semantic_jobs = [job for job in jobs if bool(job.get("semantic_generated", False))]
    supporting_jobs = [job for job in jobs if not bool(job.get("semantic_generated", False))]
    max_jobs = _semantic_component_job_limit(generation, len(semantic_jobs))
    if bool(generation.get("include_non_semantic", False)):
        jobs = (semantic_jobs + supporting_jobs)[:max_jobs]
    else:
        jobs = semantic_jobs[:max_jobs]
    manifest["include_non_semantic"] = bool(generation.get("include_non_semantic", False))
    manifest["status"] = "ok"
    manifest["backend"] = "flux_local_service"
    for job in jobs:
        component_id = str(job["component_id"])
        filename_stem = f"{job['component_type']}_{component_id}"
        raw_path = raw_root / f"{filename_stem}.png"
        icon_path = icon_root / f"{filename_stem}.png"
        record = dict(job)
        if raw_path.is_file() and raw_path.stat().st_size > 1024:
            try:
                processed = _prepare_component_icon(
                    raw_path,
                    icon_path,
                    icon_px=int(generation.get("icon_px", 96)),
                )
                record["status"] = "ok"
                record["adapter"] = "flux_local_service"
                record["source"] = "cached_raw_reprocessed"
                record["cleanup_version"] = "dominant_border_v2"
                record["raw_path"] = str(raw_path)
                record["icon_path"] = str(processed)
                manifest["icons"][component_id] = str(processed)
                manifest["jobs"].append(record)
                continue
            except Exception:
                icon_path.unlink(missing_ok=True)
        if icon_path.is_file() and icon_path.stat().st_size > 1024:
            try:
                with Image.open(icon_path) as cached_icon:
                    cached_icon.verify()
                record["status"] = "ok"
                record["adapter"] = "flux_local_service"
                record["source"] = "cached"
                record["icon_path"] = str(icon_path)
                manifest["icons"][component_id] = str(icon_path)
                manifest["jobs"].append(record)
                continue
            except Exception:
                icon_path.unlink(missing_ok=True)
        try:
            prompt = _component_prompt(
                job,
                world_name=world_name,
                visual_canon=visual_canon,
                repair_attempt=repair_attempt,
            )
            record["prompt"] = prompt
            record["projection_mode"] = (
                "flattened_floor_plan_repair" if repair_attempt > 0 else "orthographic_overhead"
            )
            record["repair_attempt"] = max(0, int(repair_attempt))
            payload = {
                "prompt": prompt,
                "negative_prompt": (
                    "text, watermark, hands, person, people, human, humanoid, character, face, head, "
                    "body, torso, arms, legs, mannequin, statue, blurry, low quality, room background, "
                    "isometric, three-quarter view, front view, side view, perspective, horizon"
                ),
                "width": int(generation.get("width", 512)),
                "height": int(generation.get("height", 512)),
                "steps": int(generation.get("steps", 8)),
                "guidance_scale": float(generation.get("guidance_scale", 0.0)),
                "output_path": str(raw_path),
                "return_base64": True,
                "asset_kind": "room_prop",
            }
            max_attempts = max(1, int(generation.get("max_attempts", 3) or 3))
            response = None
            for attempt in range(1, max_attempts + 1):
                try:
                    response = requests.post(
                        f"{flux_endpoint}/generate",
                        json=payload,
                        timeout=int(generation.get("timeout_seconds", 600)),
                    )
                    response.raise_for_status()
                    break
                except requests.RequestException as error:
                    status_code = getattr(getattr(error, "response", None), "status_code", 0)
                    retryable = status_code in {0, 408, 429, 500, 502, 503, 504}
                    if attempt >= max_attempts or not retryable:
                        raise
                    time.sleep(float(attempt))
            if response is None:
                raise RuntimeError(f"FLUX component request produced no response for {component_id}")
            result = response.json()
            if isinstance(result.get("image_base64"), str) and result["image_base64"].strip():
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(base64.b64decode(result["image_base64"]))
            elif not raw_path.is_file() and isinstance(result.get("image_path"), str):
                generated_path = Path(result["image_path"])
                if generated_path.is_file():
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_path.write_bytes(generated_path.read_bytes())
            processed = _prepare_component_icon(raw_path, icon_path, icon_px=int(generation.get("icon_px", 96)))
            record["status"] = "ok"
            record["adapter"] = "flux_local_service"
            record["raw_path"] = str(raw_path)
            record["icon_path"] = str(processed)
            record["cleanup_version"] = "dominant_border_v2"
            manifest["icons"][component_id] = str(processed)
        except Exception as error:
            record["status"] = "error"
            record["reason"] = str(error)
        manifest["jobs"].append(record)
    failed_semantic_jobs = [
        record
        for record in manifest["jobs"]
        if bool(record.get("semantic_generated", False)) and record.get("status") != "ok"
    ]
    if failed_semantic_jobs and bool(generation.get("strict_semantic_components", True)):
        manifest["status"] = "failed"
    _write_json(batch_root / "component_generation" / "component_generation_manifest.json", manifest)
    if manifest["status"] == "failed":
        failed_ids = [str(record.get("component_id", "")) for record in failed_semantic_jobs]
        raise RuntimeError(f"Semantic component generation failed for: {failed_ids}")
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


def _sprite_batch_preview(agent_records: list[dict[str, Any]], output_path: Path) -> tuple[Path, list[str]]:
    usable: list[tuple[str, Path]] = []
    for record in agent_records:
        agent_id = str(record.get("agent_id", "")).strip()
        bundle_path = Path(str(record.get("asset_bundle_path", "")))
        raw_path = bundle_path.parent / "raw_character_128.png"
        if agent_id and raw_path.is_file():
            usable.append((agent_id, raw_path))
    if not usable:
        raise ValueError("No generated raw sprite sheets were available for batch vision QA.")

    columns = min(4, len(usable))
    rows = (len(usable) + columns - 1) // columns
    cell_width = 288
    cell_height = 286
    canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), "#f4f5f7")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(canvas)
    for index, (agent_id, raw_path) in enumerate(usable):
        source = Image.open(raw_path).convert("RGBA")
        checker = Image.new("RGBA", source.size, "#e8e8e8")
        checker_draw = ImageDraw.Draw(checker)
        block = 32
        for y in range(0, checker.height, block):
            for x in range(0, checker.width, block):
                if ((x // block) + (y // block)) % 2:
                    checker_draw.rectangle((x, y, x + block - 1, y + block - 1), fill="#cfd3d8")
        checker.alpha_composite(source)
        preview = checker.convert("RGB").resize((256, 256), Image.Resampling.NEAREST)
        col = index % columns
        row = index // columns
        left = col * cell_width + 16
        top = row * cell_height + 22
        canvas.paste(preview, (left, top))
        draw.text((left, 4), agent_id, fill="#172033")
        draw.rectangle((left, top, left + 255, top + 255), outline="#7a8392", width=2)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return output_path, [agent_id for agent_id, _ in usable]


def _sprite_batch_input_fingerprint(
    *,
    visual_canon: dict[str, Any],
    agent_records: list[dict[str, Any]],
) -> str:
    digest = hashlib.sha256()
    digest.update(SPRITE_BATCH_QA_CONTRACT_VERSION.encode("utf-8"))
    digest.update(
        json.dumps(
            visual_canon,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    for record in sorted(
        agent_records,
        key=lambda entry: str(entry.get("agent_id", "")).strip(),
    ):
        agent_id = str(record.get("agent_id", "")).strip()
        bundle_path = Path(str(record.get("asset_bundle_path", "")))
        raw_path = bundle_path.parent / "raw_character_128.png"
        digest.update(agent_id.encode("utf-8"))
        if not raw_path.is_file():
            digest.update(b"<missing>")
            continue
        with raw_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _validated_cached_sprite_batch_qa(
    *,
    cached_qa: dict[str, Any] | None,
    visual_canon: dict[str, Any],
    agent_records: list[dict[str, Any]],
    input_fingerprint: str,
) -> dict[str, Any] | None:
    if not isinstance(cached_qa, dict):
        return None
    if cached_qa.get("status") != "ok" or cached_qa.get("overall_pass") is not True:
        return None
    canon_hash = str(visual_canon.get("canon_hash", "")).strip()
    if str(cached_qa.get("visual_canon_hash", "")).strip() != canon_hash:
        return None
    expected_ids = sorted(
        str(record.get("agent_id", "")).strip()
        for record in agent_records
        if str(record.get("agent_id", "")).strip()
    )
    cached_agents = [
        entry
        for entry in cached_qa.get("agents", [])
        if isinstance(entry, dict)
    ]
    cached_ids = sorted(
        str(entry.get("agent_id", "")).strip()
        for entry in cached_agents
        if str(entry.get("agent_id", "")).strip()
    )
    if cached_ids != expected_ids or not all(
        entry.get("pass_qa") is True for entry in cached_agents
    ):
        return None

    cached_fingerprint = str(cached_qa.get("input_fingerprint", "")).strip()
    if cached_fingerprint:
        if cached_fingerprint != input_fingerprint:
            return None
        cache_source = "fingerprint_match"
    else:
        legacy_reuse_is_verifiable = all(
            record.get("quality_summary", {}).get("pass_qa") is True
            and str(
                record.get("asset_bundle", {})
                .get("sprite_summary", {})
                .get("mode", "")
            ).strip()
            == "reused_latest_raw_sheet"
            for record in agent_records
        )
        if not legacy_reuse_is_verifiable:
            return None
        cache_source = "verified_legacy_migration"

    return {
        **cached_qa,
        "qa_contract_version": SPRITE_BATCH_QA_CONTRACT_VERSION,
        "input_fingerprint": input_fingerprint,
        "cache": {
            "hit": True,
            "source": cache_source,
        },
    }


def _direction_mirror_evidence(agent_record: dict[str, Any]) -> dict[str, Any]:
    bundle_path = Path(str(agent_record.get("asset_bundle_path", "")))
    raw_path = bundle_path.parent / "raw_character_128.png"
    from asset_pipeline.sprite_qa_programmatic import directional_sheet_qa

    return directional_sheet_qa(raw_path)


def _run_sprite_batch_vision_qa(
    *,
    world_config: dict[str, Any],
    agent_records: list[dict[str, Any]],
    batch_root: Path,
    cached_qa: dict[str, Any] | None = None,
) -> dict[str, Any]:
    visual_canon = world_config.get("pixel_asset_pipeline", {}).get("visual_canon", {})
    enabled = str(os.environ.get("AGORA_ENABLE_SPRITE_BATCH_VISION_QA", "0")).strip().lower() not in {"0", "false", "no"}
    if not enabled or not isinstance(visual_canon, dict) or not visual_canon:
        return {"status": "skipped", "reason": "Batch sprite vision QA is disabled or no mature visual canon is present."}

    preview_path, agent_ids = _sprite_batch_preview(
        agent_records,
        batch_root / "sprite_batch_vision_qa_preview.png",
    )
    input_fingerprint = _sprite_batch_input_fingerprint(
        visual_canon=visual_canon,
        agent_records=agent_records,
    )
    reusable_qa = _validated_cached_sprite_batch_qa(
        cached_qa=cached_qa,
        visual_canon=visual_canon,
        agent_records=agent_records,
        input_fingerprint=input_fingerprint,
    )
    if reusable_qa is not None:
        reusable_qa["preview_path"] = str(preview_path)
        _write_json(batch_root / "sprite_batch_vision_qa.json", reusable_qa)
        return reusable_qa

    VertexJsonClient, _ = _load_runtime_clients()
    qa_model = (
        str(os.environ.get("AGORA_SPRITE_BATCH_QA_MODEL", "")).strip()
        or str(os.environ.get("AGORA_WORLD_CREATOR_LITE_MODEL", "")).strip()
        or "gemini-3.1-flash-lite-preview"
    )
    qa_config = {
        "vertex_api": {
            "backend": "ai_studio",
            "model": qa_model,
            "api_key_env": "AGORA_AISTUDIO_API_KEY",
            "temperature": 0.0,
            "max_output_tokens": 2048,
            "thinking_level": "low",
            "thinking_budget": 128,
            "timeout_seconds": 180,
            "retry": {
                "max_attempts": 3,
                "initial_sleep_seconds": 5.0,
                "max_sleep_seconds": 30.0,
                "backoff_multiplier": 2.0,
                "status_codes": [408, 429, 500, 502, 503, 504],
            },
            "stages": {
                "sprite_batch_vision_qa": {
                    "model": qa_model,
                    "max_output_tokens": 2048,
                    "thinking_level": "low",
                    "thinking_budget": 128,
                    "temperature": 0.0,
                }
            },
        }
    }
    client = VertexJsonClient(qa_config)
    client.temperature = 0.0
    client.max_output_tokens = 2048
    client.thinking_level = "low"
    client.thinking_budget = 128
    if isinstance(getattr(client, "stages", None), dict):
        client.stages["sprite_batch_vision_qa"] = {
            "max_output_tokens": 2048,
            "thinking_level": "low",
            "thinking_budget": 128,
            "temperature": 0.0,
        }
    schema = {
        "type": "object",
        "required": ["overall_pass", "agents"],
        "properties": {
            "overall_pass": {"type": "boolean"},
            "agents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "agent_id",
                        "pass_qa",
                        "anatomy_clean",
                        "identity_consistent",
                        "motion_visible",
                        "single_human_subject",
                        "silhouette_readable",
                        "palette_readable",
                        "issue",
                    ],
                    "properties": {
                        "agent_id": {"type": "string"},
                        "pass_qa": {"type": "boolean"},
                        "anatomy_clean": {"type": "boolean"},
                        "identity_consistent": {"type": "boolean"},
                        "motion_visible": {"type": "boolean"},
                        "single_human_subject": {"type": "boolean"},
                        "silhouette_readable": {"type": "boolean"},
                        "palette_readable": {"type": "boolean"},
                        "issue": {"type": "string"},
                    },
                },
            },
        },
    }
    result = client.generate_multimodal_json(
        system_instruction=(
            "You are a strict game-sprite batch QA reviewer. Judge visible production defects, "
            "not subjective taste. Return only schema-valid JSON."
        ),
        prompt=(
            f"The contact sheet contains these agent IDs in reading order: {agent_ids}. "
            "Each cell is one 4x4 sprite sheet over a checkerboard. Row 1 is idle; rows 2-4 are walk-down, "
            "walk-left, and walk-right. Small one-pixel gait deformation is valid motion at 32x32 gameplay scale. "
            "Pass only production-ready field characters. Every frame must contain exactly one humanoid with one "
            "head, one torso, two arms, and two separated legs. The human body must be the dominant visual subject. "
            "Fail pairs, duplicates, crowds, enclosing circles, wings or backplates larger than the body, portals, "
            "auras, scenery, floor patches, giant props, or disconnected costume pieces. Fail a narrow vertical mark, "
            "an all-black silhouette, muddy clothing with no face/torso/leg separation, or a sprite whose identity is "
            "not readable at the shown gameplay scale. Require at least two clearly separated clothing colors plus a "
            "visible face or head treatment. Left and right walking rows must visibly face different directions from "
            "the front rows; mechanical translation of the same front pose is a failure. Also fail missing body parts, "
            "severe identity drift, blank/corrupt frames, or repeated animated rows. Crunchy pixel edges alone are valid."
        ),
        schema=schema,
        stage="sprite_batch_vision_qa",
        media_parts=[
            {
                "inlineData": {
                    "mimeType": "image/png",
                    "data": base64.b64encode(preview_path.read_bytes()).decode("ascii"),
                }
            }
        ],
    )
    reported = {
        str(entry.get("agent_id", "")).strip(): dict(entry)
        for entry in result.get("agents", [])
        if isinstance(entry, dict) and str(entry.get("agent_id", "")).strip()
    }
    record_by_agent = {
        str(record.get("agent_id", "")).strip(): record
        for record in agent_records
        if isinstance(record, dict) and str(record.get("agent_id", "")).strip()
    }
    normalized_agents: list[dict[str, Any]] = []
    for agent_id in agent_ids:
        entry = reported.get(agent_id)
        if entry is None:
            entry = {
                "agent_id": agent_id,
                "pass_qa": False,
                "anatomy_clean": False,
                "identity_consistent": False,
                "motion_visible": False,
                "single_human_subject": False,
                "silhouette_readable": False,
                "palette_readable": False,
                "issue": "Agent was omitted from the batch QA response.",
            }
        issue = str(entry.get("issue", "")).lower()
        non_direction_checks_pass = all(
            bool(entry.get(key, False))
            for key in (
                "anatomy_clean",
                "identity_consistent",
                "motion_visible",
                "single_human_subject",
                "silhouette_readable",
                "palette_readable",
            )
        )
        direction_only_failure = (
            not bool(entry.get("pass_qa", False))
            and non_direction_checks_pass
            and any(
                phrase in issue
                for phrase in (
                    "walk-left",
                    "face left",
                    "same direction",
                    "both face right",
                )
            )
        )
        if direction_only_failure:
            evidence = _direction_mirror_evidence(record_by_agent.get(agent_id, {}))
            entry["direction_mirror_evidence"] = evidence
            if evidence.get("pass") is True:
                entry["pass_qa"] = True
                entry["issue"] = "none"
                entry["direction_verified_programmatically"] = True
        normalized_agents.append(entry)
    normalized = {
        "status": "ok",
        "overall_pass": all(bool(entry.get("pass_qa", False)) for entry in normalized_agents),
        "qa_contract_version": SPRITE_BATCH_QA_CONTRACT_VERSION,
        "input_fingerprint": input_fingerprint,
        "visual_canon_hash": str(visual_canon.get("canon_hash", "")),
        "preview_path": str(preview_path),
        "cache": {"hit": False, "source": "remote_review"},
        "agents": normalized_agents,
    }
    _write_json(batch_root / "sprite_batch_vision_qa.json", normalized)
    return normalized


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
    parser.add_argument("--skip-agents", action="store_true")
    parser.add_argument("--regenerate-room-id", action="append", dest="regenerate_room_ids", default=[])
    parser.add_argument("--regenerate-room-components", action="store_true")
    parser.add_argument("--preserve-room-floors", action="store_true")
    parser.add_argument("--repair-attempt", type=int, default=1)
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
    manifest_path = batch_root / "world_asset_set_manifest.json"
    existing_manifest = _read_json(manifest_path) if manifest_path.is_file() else {}
    existing_sprite_qa_path = batch_root / "sprite_batch_vision_qa.json"
    existing_sprite_qa = (
        _read_json(existing_sprite_qa_path)
        if existing_sprite_qa_path.is_file()
        else existing_manifest.get("sprite_batch_vision_qa", {})
    )
    known_room_ids = {
        str(room.get("room_id", "")).strip()
        for room in map_grid.get("rooms", [])
        if isinstance(room, dict) and str(room.get("room_id", "")).strip()
    }
    requested_room_repairs = {
        str(room_id).strip()
        for room_id in args.regenerate_room_ids
        if str(room_id).strip() in known_room_ids
    }
    if requested_room_repairs:
        repair_seed_offset = max(1, int(args.repair_attempt)) * 100_000 + sum(
            ord(character)
            for room_id in sorted(requested_room_repairs)
            for character in room_id
        )
        os.environ["AGORA_FLUX_REPAIR_SEED_OFFSET"] = str(repair_seed_offset)
    floor_root = batch_root / "floors"
    for room_id in sorted(requested_room_repairs):
        if not args.preserve_room_floors:
            for suffix in (".png", ".qa.json"):
                (floor_root / f"floor_{room_id}{suffix}").unlink(missing_ok=True)
        if args.regenerate_room_components:
            matching_room = next(
                (
                    room
                    for room in map_grid.get("rooms", [])
                    if isinstance(room, dict) and str(room.get("room_id", "")).strip() == room_id
                ),
                {},
            )
            for component in matching_room.get("visual", {}).get("scene_components", []):
                if not isinstance(component, dict):
                    continue
                component_id = str(component.get("component_id", "")).strip()
                if not component_id:
                    continue
                filename = f"prop_{component_id}.png"
                (batch_root / "component_generation" / "raw" / filename).unlink(missing_ok=True)
                (batch_root / "component_generation" / "icons" / filename).unlink(missing_ok=True)

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
        f"Write one strong image-generation prompt for a top-down persistent-world map key art for {world_name}. "
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
        repair_attempt=max(0, int(args.repair_attempt)) if requested_room_repairs else 0,
    )
    map_config = pipeline.get("map_generation", {})
    overlay_supporting_props = _supporting_prop_overlay_enabled(pipeline)
    local_icon_ids = {
        str(job.get("component_id", "")).strip()
        for job in local_component_manifest.get("jobs", [])
        if isinstance(job, dict)
        and (
            overlay_supporting_props
            or str(job.get("component_type", "")).strip() == "pickup"
        )
    }
    combined_component_icons = {
        component_id: icon_path
        for component_id, icon_path in dict(local_component_manifest.get("icons", {})).items()
        if component_id in local_icon_ids
    }
    combined_component_icons.update(component_generation_manifest.get("icons", {}))
    map_source_path = batch_root / "world_map_source.png"
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
        "supporting_prop_overlay": {
            "enabled": overlay_supporting_props,
            "policy_version": str(
                map_config.get("supporting_prop_policy_version", "legacy_auto_upgrade")
            ),
            "included_local_icon_ids": sorted(local_icon_ids),
        },
        "map_render_result": map_render_result,
        "map_source_path": str(map_source_path),
        "map_asset_url": _browser_asset_url(package_root, map_source_path),
        "agents": [],
        "assets": [],
        "map_repair": {
            "skip_agents": bool(args.skip_agents),
            "regenerated_room_ids": sorted(requested_room_repairs),
        },
    }

    if args.skip_agents:
        if not existing_manifest.get("agents") or not existing_manifest.get("assets"):
            raise RuntimeError("--skip-agents requires an existing successful asset manifest for this revision.")
        for key in (
            "agents",
            "assets",
            "sprite_batch_vision_qa",
            "quality_summary",
            "failed_agent_ids",
            "requested_agent_ids",
            "active_agents_from_manifest",
        ):
            if key in existing_manifest:
                manifest[key] = existing_manifest[key]
        previous_status = str(existing_manifest.get("status", "")).strip()
        manifest["status"] = previous_status if previous_status in {"ok", "partial"} else "ok"
        _write_json(manifest_path, manifest)
        if args.update_current_alias:
            _write_current_alias(package_root, manifest_path)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "revision": args.revision,
                    "manifest": str(manifest_path),
                    "regenerated_room_ids": sorted(requested_room_repairs),
                    "agents_reused": len(manifest.get("agents", [])),
                },
                indent=2,
            )
        )
        return

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{package_root}:{env.get('PYTHONPATH', '')}".rstrip(":")

    def run_agent_generation(
        index: int,
        agent_id: str,
        *,
        force_remote: bool = False,
        repair_attempt: int = 0,
        revision_suffix: str = "",
    ) -> tuple[int, dict[str, Any], dict[str, Any] | None]:
        started_at = datetime.now(timezone.utc).isoformat()
        started_perf = time.perf_counter()
        generation_revision = f"{args.revision}{revision_suffix}"
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
            generation_revision,
        ]
        from asset_pipeline.agent_assets.compositor import _find_latest_raw_sheet
        has_reusable = _find_latest_raw_sheet(package_root, agent_id, exclude_revision=None) is not None

        should_reuse = bool(args.reuse_latest_raw_sheet) and has_reusable and not force_remote
        if should_reuse:
            cmd.append("--reuse-latest-raw-sheet")
        else:
            cmd.append("--invoke-remote")
        if index == 0:
            cmd.append("--write-frontend-bootstrap")
        agent_env = dict(env)
        if repair_attempt > 0:
            agent_env["AGORA_SPRITE_REPAIR_ATTEMPT"] = str(repair_attempt)
        result = subprocess.run(cmd, cwd=str(package_root), env=agent_env, capture_output=True, text=True, check=False)
        agent_record = {
            "agent_id": agent_id,
            "generation_revision": generation_revision,
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
        asset_bundle = package_root / "frontend" / "assets" / "generated" / agent_id / generation_revision / "asset_bundle.json"
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

    event_by_agent = {
        str(event.get("id", "")).strip(): event
        for event in publishable_events
        if isinstance(event, dict) and str(event.get("id", "")).strip()
    }
    agent_generation_repair_history: list[dict[str, Any]] = []
    max_generation_repairs = min(5, max(0, int(args.repair_attempt or 0)))
    for repair_attempt in range(1, max_generation_repairs + 1):
        failed_generation_ids = [
            selected_agent_ids[index]
            for index, record in enumerate(indexed_records)
            if not isinstance(record, dict)
            or int(record.get("returncode", 1)) != 0
            or not bool(record.get("publishable", False))
        ]
        if not failed_generation_ids:
            break
        repair_record = {
            "attempt": repair_attempt,
            "requested_agent_ids": failed_generation_ids,
            "results": [],
        }
        for agent_id in failed_generation_ids:
            index = selected_agent_ids.index(agent_id)
            result_index, agent_record, event_payload = run_agent_generation(
                index,
                agent_id,
                force_remote=True,
                repair_attempt=repair_attempt,
                revision_suffix=f"_generation_repair_{repair_attempt:02d}",
            )
            indexed_records[result_index] = agent_record
            if isinstance(event_payload, dict):
                event_by_agent[agent_id] = event_payload
            repair_record["results"].append(
                {
                    "agent_id": agent_id,
                    "returncode": int(agent_record.get("returncode", 1)),
                    "publishable": bool(agent_record.get("publishable", False)),
                }
            )
        agent_generation_repair_history.append(repair_record)

    manifest["agents"] = [record for record in indexed_records if isinstance(record, dict)]
    manifest["assets"] = [
        event_by_agent[agent_id]
        for agent_id in selected_agent_ids
        if agent_id in event_by_agent
    ]
    manifest["agent_generation_repair_history"] = agent_generation_repair_history
    try:
        sprite_batch_vision_qa = _run_sprite_batch_vision_qa(
            world_config=world_config,
            agent_records=manifest["agents"],
            batch_root=batch_root,
            cached_qa=existing_sprite_qa,
        )
    except Exception as error:
        sprite_batch_vision_qa = {
            "status": "error",
            "overall_pass": False,
            "reason": str(error),
            "agents": [],
        }
        _write_json(batch_root / "sprite_batch_vision_qa.json", sprite_batch_vision_qa)
    sprite_batch_vision_qa_history = [{"attempt": 0, **sprite_batch_vision_qa}]
    max_sprite_repairs = min(
        2,
        max(
            0,
            int(
                world_config.get("pixel_asset_pipeline", {})
                .get("sprite_vision_qa", {})
                .get("max_local_repairs", 2)
                or 2
            ),
        ),
    )
    sprite_repair_attempt = 0
    failed_sprite_vision_ids = [
        str(entry.get("agent_id", "")).strip()
        for entry in sprite_batch_vision_qa.get("agents", [])
        if isinstance(entry, dict)
        and str(entry.get("agent_id", "")).strip()
        and not bool(entry.get("pass_qa", False))
    ]
    while (
        sprite_batch_vision_qa.get("status") == "ok"
        and failed_sprite_vision_ids
        and sprite_repair_attempt < max_sprite_repairs
    ):
        sprite_repair_attempt += 1
        previous_qa_by_agent = {
            str(entry.get("agent_id", "")).strip(): dict(entry)
            for entry in sprite_batch_vision_qa.get("agents", [])
            if isinstance(entry, dict) and str(entry.get("agent_id", "")).strip()
        }
        regenerated_success_ids: list[str] = []
        generation_results: list[dict[str, Any]] = []
        for agent_id in failed_sprite_vision_ids:
            index = selected_agent_ids.index(agent_id)
            result_index, agent_record, event_payload = run_agent_generation(
                index,
                agent_id,
                force_remote=True,
                repair_attempt=sprite_repair_attempt,
                revision_suffix=f"_vision_repair_{sprite_repair_attempt:02d}",
            )
            if isinstance(event_payload, dict):
                indexed_records[result_index] = agent_record
                event_by_agent[agent_id] = event_payload
                regenerated_success_ids.append(agent_id)
            generation_results.append(
                {
                    "agent_id": agent_id,
                    "returncode": int(agent_record.get("returncode", 1)),
                    "publishable": bool(agent_record.get("publishable", False)),
                    "generation_revision": str(agent_record.get("generation_revision", "")),
                }
            )
        manifest["agents"] = [record for record in indexed_records if isinstance(record, dict)]
        manifest["assets"] = [
            event_by_agent[agent_id]
            for agent_id in selected_agent_ids
            if agent_id in event_by_agent
        ]
        try:
            sprite_batch_vision_qa = _run_sprite_batch_vision_qa(
                world_config=world_config,
                agent_records=manifest["agents"],
                batch_root=batch_root,
                cached_qa=None,
            )
        except Exception as error:
            sprite_batch_vision_qa = {
                "status": "error",
                "overall_pass": False,
                "reason": str(error),
                "agents": [],
            }
            _write_json(batch_root / "sprite_batch_vision_qa.json", sprite_batch_vision_qa)
        if sprite_batch_vision_qa.get("status") == "ok":
            reviewed_qa_by_agent = {
                str(entry.get("agent_id", "")).strip(): dict(entry)
                for entry in sprite_batch_vision_qa.get("agents", [])
                if isinstance(entry, dict) and str(entry.get("agent_id", "")).strip()
            }
            merged_agents = []
            for agent_id in selected_agent_ids:
                if agent_id in regenerated_success_ids:
                    entry = reviewed_qa_by_agent.get(agent_id) or previous_qa_by_agent.get(agent_id)
                else:
                    entry = previous_qa_by_agent.get(agent_id) or reviewed_qa_by_agent.get(agent_id)
                if isinstance(entry, dict):
                    merged_agents.append(entry)
            sprite_batch_vision_qa["agents"] = merged_agents
            sprite_batch_vision_qa["overall_pass"] = (
                len(merged_agents) == len(selected_agent_ids)
                and all(bool(entry.get("pass_qa", False)) for entry in merged_agents)
            )
            _write_json(batch_root / "sprite_batch_vision_qa.json", sprite_batch_vision_qa)
        sprite_batch_vision_qa_history.append(
            {
                "attempt": sprite_repair_attempt,
                "requested_agent_ids": list(failed_sprite_vision_ids),
                "regenerated_agent_ids": regenerated_success_ids,
                "generation_results": generation_results,
                **sprite_batch_vision_qa,
            }
        )
        failed_sprite_vision_ids = [
            str(entry.get("agent_id", "")).strip()
            for entry in sprite_batch_vision_qa.get("agents", [])
            if isinstance(entry, dict)
            and str(entry.get("agent_id", "")).strip()
            and not bool(entry.get("pass_qa", False))
        ]
    manifest["sprite_batch_vision_qa"] = sprite_batch_vision_qa
    manifest["sprite_batch_vision_qa_history"] = sprite_batch_vision_qa_history
    vision_by_agent = {
        str(entry.get("agent_id", "")).strip(): dict(entry)
        for entry in sprite_batch_vision_qa.get("agents", [])
        if isinstance(entry, dict) and str(entry.get("agent_id", "")).strip()
    }
    for record in manifest["agents"]:
        agent_id = str(record.get("agent_id", "")).strip()
        if agent_id in vision_by_agent:
            record["sprite_vision_qa"] = vision_by_agent[agent_id]
            bundle_path = Path(str(record.get("asset_bundle_path", "")))
            if bundle_path.is_file():
                bundle_payload = _read_json(bundle_path)
                bundle_payload["sprite_vision_qa"] = {
                    **vision_by_agent[agent_id],
                    "batch_report_path": str(batch_root / "sprite_batch_vision_qa.json"),
                    "visual_canon_hash": str(
                        world_config.get("pixel_asset_pipeline", {}).get("visual_canon", {}).get("canon_hash", "")
                    ),
                }
                _write_json(bundle_path, bundle_payload)
    failed_agent_ids = [
        str(record.get("agent_id", "")).strip()
        for record in manifest["agents"]
        if int(record.get("returncode", 0) or 0) != 0 or not bool(record.get("publishable", False))
    ]
    if sprite_batch_vision_qa.get("status") == "ok":
        failed_agent_ids.extend(
            str(entry.get("agent_id", "")).strip()
            for entry in sprite_batch_vision_qa.get("agents", [])
            if isinstance(entry, dict)
            and not bool(entry.get("pass_qa", False))
            and str(entry.get("agent_id", "")).strip()
        )
    elif sprite_batch_vision_qa.get("status") not in {"skipped", "disabled"} and world_config.get("pixel_asset_pipeline", {}).get("visual_canon"):
        failed_agent_ids.append("SPRITE_BATCH_VISION_QA_ERROR")
    failed_agent_ids = sorted(set(failed_agent_ids))

    quality_summaries = [record.get("quality_summary", {}) for record in manifest["agents"] if isinstance(record.get("quality_summary"), dict)]
    sprite_summaries = [record.get("asset_bundle", {}).get("sprite_summary", {}) for record in manifest["agents"] if isinstance(record.get("asset_bundle"), dict)]
    fallback_count = sum(1 for summary in sprite_summaries if summary.get("status") in {"quality_fallback_procedural", "fallback"})

    manifest["quality_summary"] = {
        "agent_count": len(manifest["agents"]),
        "passing_agents": sum(1 for summary in quality_summaries if summary.get("pass_qa") is True),
        "failing_agents": sum(1 for summary in quality_summaries if summary.get("pass_qa") is False),
        "fallback_agents": fallback_count,
        "remote_agent_ids": sorted(remote_agent_ids),
        "reuse_latest_raw_sheet": bool(args.reuse_latest_raw_sheet),
        "max_workers": max_workers,
        "sprite_batch_vision_qa_pass": (
            bool(sprite_batch_vision_qa.get("overall_pass", False))
            if sprite_batch_vision_qa.get("status") == "ok"
            else None
        ),
        "sprite_batch_vision_qa_status": str(sprite_batch_vision_qa.get("status", "")),
        "sprite_repair_attempts": sprite_repair_attempt,
    }

    if fallback_count > 0:
        print(f"[QA_FAILURE] Strict pipeline forbids fallback sprites ({fallback_count} found).", flush=True)
        manifest["status"] = "failed"
        failed_agent_ids.append("QA_FALLBACK_LIMIT_EXCEEDED")
    elif not manifest.get("assets"):
        manifest["status"] = "failed"
    elif failed_agent_ids and args.allow_partial_success:
        manifest["status"] = "partial"
    else:
        manifest["status"] = "ok" if not failed_agent_ids else "failed"
    manifest["failed_agent_ids"] = failed_agent_ids
    manifest["requested_agent_ids"] = list(selected_agent_ids)
    manifest["active_agents_from_manifest"] = list(scenario_manifest.get("asset_bindings", {}).get("active_agents", []))
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
