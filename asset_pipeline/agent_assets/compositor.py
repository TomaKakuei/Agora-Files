from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from agora_ui.boundary_schemas import BootstrapAgentsSpec
from asset_pipeline.process_sprite import DEFAULT_ANIMATION_STATES, AnimationState, build_phaser_atlas
from asset_pipeline.sprite_qa import run_combined_qa, strict_programmatic_qa

from .image_processing import (
    _alpha_components,
    _cluster_component_centers,
    _pad_image_to_aspect_ratio,
    _strip_dominant_border_background,
)
from .schemas import PipelinePaths


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_room_lookup(map_grid: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {room["room_id"]: room for room in map_grid.get("rooms", [])}


def _normalize_remote_raw_sheet(
    *,
    raw_sheet_path: Path,
    animation_states: list[AnimationState],
    raw_frame_width: int,
    raw_frame_height: int,
) -> dict[str, Any]:
    source = Image.open(raw_sheet_path).convert("RGBA")
    cleaned = _strip_dominant_border_background(source)
    alpha = np.array(cleaned.getchannel("A"), dtype=np.uint8) >= 8
    components = _alpha_components(alpha, min_area=max(32, (raw_frame_width * raw_frame_height) // 64))
    target_rows = max((state.row + 1 for state in animation_states), default=4)
    target_cols = max((state.start_col + state.frame_count for state in animation_states), default=4)
    if len(components) < target_rows * target_cols:
        return {"status": "skipped", "reason": f"insufficient_components:{len(components)}"}

    max_component_width = max(raw_frame_width * 1.8, (source.width / float(max(1, target_cols))) * 0.9)
    max_component_height = max(raw_frame_height * 1.8, (source.height / float(max(1, target_rows))) * 1.2)
    filtered_components: list[dict[str, Any]] = []
    rejected_components = 0
    for component in components:
        left, top, right, bottom = component["bbox"]
        width = right - left
        height = bottom - top
        touches_full_frame = left <= 1 and top <= 1 and right >= (source.width - 1) and bottom >= (source.height - 1)
        too_large = width > max_component_width or height > max_component_height
        if touches_full_frame or too_large:
            rejected_components += 1
            continue
        filtered_components.append(component)
    if len(filtered_components) >= target_rows * target_cols:
        components = filtered_components

    row_centers = _cluster_component_centers(
        [component["center_y"] for component in components],
        max_gap=max(8.0, source.height / float(max(1, target_rows * 3))),
    )
    col_centers = _cluster_component_centers(
        [component["center_x"] for component in components],
        max_gap=max(8.0, source.width / float(max(1, target_cols * 4))),
    )
    if len(row_centers) < target_rows or len(col_centers) < target_cols:
        return {
            "status": "skipped",
            "reason": f"insufficient_clusters:rows={len(row_centers)} cols={len(col_centers)}",
        }

    selected_row_centers = row_centers[:target_rows]
    if len(col_centers) == target_cols:
        selected_col_centers = col_centers
    else:
        selected_col_centers = []
        for index in range(target_cols):
            selected_index = round(index * (len(col_centers) - 1) / float(max(1, target_cols - 1)))
            selected_col_centers.append(col_centers[int(selected_index)])

    normalized = Image.new("RGBA", (target_cols * raw_frame_width, target_rows * raw_frame_height), (0, 0, 0, 0))
    selections: list[dict[str, Any]] = []
    row_component_groups: list[list[tuple[int, dict[str, Any]]]] = [[] for _ in selected_row_centers]
    for component_index, component in enumerate(components):
        nearest_row_index = min(
            range(len(selected_row_centers)),
            key=lambda index: abs(component["center_y"] - selected_row_centers[index]),
        )
        row_component_groups[nearest_row_index].append((component_index, component))
    if any(len(group) < target_cols for group in row_component_groups):
        row_counts = [len(group) for group in row_component_groups]
        return {
            "status": "skipped",
            "reason": f"insufficient_row_components:{row_counts}",
            "source_size": {"width": int(source.width), "height": int(source.height)},
            "detected_rows": len(row_centers),
            "detected_cols": len(col_centers),
            "selected_rows": len(selected_row_centers),
            "selected_cols": len(selected_col_centers),
            "component_count": len(components),
            "rejected_component_count": int(rejected_components),
        }
    used_component_indices: set[int] = set()
    reused_component_assignments = 0
    for row_index, row_center in enumerate(selected_row_centers):
        for col_index, col_center in enumerate(selected_col_centers):
            available_components = [
                (component_index, component)
                for component_index, component in row_component_groups[row_index]
                if component_index not in used_component_indices
            ]
            if not available_components:
                available_components = list(row_component_groups[row_index])
            component_index, component = min(
                available_components,
                key=lambda entry: abs(entry[1]["center_x"] - col_center),
            )
            if component_index in used_component_indices:
                reused_component_assignments += 1
            used_component_indices.add(component_index)
            left, top, right, bottom = component["bbox"]
            crop = cleaned.crop((max(0, left - 8), max(0, top - 8), min(source.width, right + 8), min(source.height, bottom + 8)))
            crop = _pad_image_to_aspect_ratio(crop, target_aspect_ratio=1.0)
            fitted = ImageOps.contain(
                crop,
                (raw_frame_width - 12, raw_frame_height - 12),
                Image.Resampling.NEAREST,
            )
            cell = Image.new("RGBA", (raw_frame_width, raw_frame_height), (0, 0, 0, 0))
            paste_x = (raw_frame_width - fitted.width) // 2
            paste_y = raw_frame_height - fitted.height - 6
            cell.paste(fitted, (paste_x, paste_y), fitted)
            normalized.paste(cell, (col_index * raw_frame_width, row_index * raw_frame_height), cell)
            selections.append(
                {
                    "row": row_index,
                    "col": col_index,
                    "source_bbox": {
                        "left": int(left),
                        "top": int(top),
                        "right": int(right - 1),
                        "bottom": int(bottom - 1),
                    },
                }
            )

    normalized.save(raw_sheet_path)
    return {
        "status": "ok",
        "source_size": {"width": int(source.width), "height": int(source.height)},
        "detected_rows": len(row_centers),
        "detected_cols": len(col_centers),
        "selected_rows": len(selected_row_centers),
        "selected_cols": len(selected_col_centers),
        "component_count": len(components),
        "rejected_component_count": int(rejected_components),
        "reused_component_assignments": int(reused_component_assignments),
        "selections": selections,
    }



def _write_raw_sheet_qa_report(
    *,
    raw_sheet_path: Path,
    sheet_layout: dict[str, Any],
    processing: dict[str, Any],
    animation_states: list[AnimationState],
    output_path: Path,
) -> dict[str, Any]:
    report = strict_programmatic_qa(
        image_path=str(raw_sheet_path),
        sheet_layout=sheet_layout,
        processing=processing,
        animation_states=animation_states,
    )
    report["raw_sheet_path"] = str(raw_sheet_path)
    _write_json(output_path, report)
    return report


def _relative_url(root: Path, target: Path) -> str:
    return "./" + str(target.relative_to(root)).replace(os.sep, "/")


def _find_latest_raw_sheet(package_root: Path, agent_id: str, *, exclude_revision: str | None = None) -> Path | None:
    agent_root = package_root / "frontend" / "assets" / "generated" / agent_id
    if not agent_root.is_dir():
        return None
    candidates = []
    for path in agent_root.glob("*/raw_character_128.png"):
        revision = path.parent.name
        if exclude_revision and revision == exclude_revision:
            continue
        if path.is_file():
            # Only consider reusable if the bundle actually passed QA
            bundle_path = path.parent / "asset_bundle.json"
            if bundle_path.is_file():
                try:
                    import json
                    bundle_data = json.loads(bundle_path.read_text(encoding="utf-8"))
                    if bundle_data.get("overall_status") != "pass":
                        continue
                except Exception:
                    continue
            else:
                continue
            candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.parent.name))



def _reuse_latest_raw_sheet(package_root: Path, agent_id: str, revision: str, destination: Path) -> dict[str, Any]:
    source = _find_latest_raw_sheet(package_root, agent_id, exclude_revision=None)
    if source is None:
        raise FileNotFoundError(f"No reusable raw sheet found for {agent_id}")
    if source.resolve() == destination.resolve():
        return {"status": "ok", "source": str(source), "mode": "reused_latest_raw_sheet"}
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return {"status": "ok", "source": str(source), "mode": "reused_latest_raw_sheet"}


def _build_atlas_outputs(
    *,
    raw_sheet_path: Path,
    atlas_png: Path,
    atlas_json: Path,
    quality_report_path: Path,
    sheet_layout: dict[str, Any],
    processing: dict[str, Any],
    animation_states: list[AnimationState],
) -> tuple[dict[str, Any], dict[str, Any]]:
    atlas = build_phaser_atlas(
        input_path=str(raw_sheet_path),
        output_sheet_path=str(atlas_png),
        output_atlas_json_path=str(atlas_json),
        raw_frame_width=sheet_layout.get("raw_frame_width", 128),
        raw_frame_height=sheet_layout.get("raw_frame_height", 128),
        target_frame_width=processing.get("target_frame_width", 32),
        target_frame_height=processing.get("target_frame_height", 32),
        palette_size=processing.get("palette_size", 24),
        alpha_threshold=processing.get("alpha_threshold", 8),
        remove_near_white_background=bool(processing.get("remove_near_white_background", True)),
        near_white_threshold=int(processing.get("near_white_threshold", 246)),
        neutral_tolerance=int(processing.get("neutral_tolerance", 12)),
        animation_states=animation_states,
        alignment_policy=processing.get("alignment_policy", {}),
    )
    quality_report = {
        "quality_summary": atlas.get("meta", {}).get("quality_summary", {}),
        "quality_report": atlas.get("meta", {}).get("quality_report", {}),
        "alignment_policy": atlas.get("meta", {}).get("alignment_policy", {}),
    }
    _write_json(quality_report_path, quality_report)
    return atlas, quality_report





def _build_ai_studio_retry_world_config(base_config: dict[str, Any]) -> dict[str, Any]:
    config = json.loads(json.dumps(base_config))
    vertex_api = dict(config.get("vertex_api", {}))
    vertex_api["backend"] = "ai_studio"
    vertex_api["api_key_env"] = "AGORA_AISTUDIO_API_KEY"
    vertex_api["endpoint_base"] = "https://generativelanguage.googleapis.com/v1beta"
    vertex_api["method"] = "generateContent"
    config["vertex_api"] = vertex_api

    image_generation = dict(config.get("image_generation", {}))
    image_generation["backend"] = "ai_studio"
    image_generation["api_key_env"] = "AGORA_AISTUDIO_API_KEY"
    image_generation["endpoint_base"] = "https://generativelanguage.googleapis.com/v1beta"
    image_generation["method"] = "generateContent"
    image_generation["thinking_level"] = "minimal"
    image_generation["image_aspect_ratio"] = "1:1"
    image_generation["image_size"] = "512x512"
    config["image_generation"] = image_generation

    concept_generation = dict(config.get("pixel_asset_pipeline", {}).get("concept_generation", {}))
    concept_generation["api_key_env"] = "AGORA_AISTUDIO_API_KEY"
    concept_generation["endpoint_base"] = "https://generativelanguage.googleapis.com/v1beta"
    concept_generation["response_modalities"] = ["TEXT"]
    config.setdefault("pixel_asset_pipeline", {})["concept_generation"] = concept_generation
    return config


def _build_ai_studio_retry_pipeline_config(base_pipeline_config: dict[str, Any]) -> dict[str, Any]:
    pipeline = json.loads(json.dumps(base_pipeline_config))
    sprite_generation = dict(pipeline.get("sprite_generation", {}))
    sprite_generation["adapter"] = "vertex_sdk_image"
    pipeline["sprite_generation"] = sprite_generation
    return pipeline


def _publishable_generated_asset(
    # [CRITICAL SECURITY/COMPLIANCE RULE]: 
    # Procedural fallbacks (e.g. generating gray placeholder boxes on failure) 
    # are STRICTLY FORBIDDEN by readmeforllm guidelines. The asset pipeline must 
    # explicitly HARD-FAIL if Vertex/FLUX generations fail or are blocked. 
    # This prevents deploying polluted, low-quality sprite sheets to the live world.
    *,
    sprite_summary: dict[str, Any],
    reused_raw_summary: dict[str, Any],
    overall_status: str,
    atlas_transparency_check: dict[str, Any],
    raw_sheet_supplied: bool,
) -> bool:
    sprite_status = str(sprite_summary.get("status", "")).strip().lower()
    sprite_source = str(sprite_summary.get("source", "")).strip().lower()
    reused_status = str(reused_raw_summary.get("status", "")).strip().lower()
    if raw_sheet_supplied:
        return False
    if overall_status.strip().lower() != "pass":
        return False
    if not bool(atlas_transparency_check.get("pass", True)):
        return False
    if reused_status not in {"", "not_used", "ok"}:
        return False
    if sprite_status in {"quality_fallback_procedural", "fallback", "quality_warning_retained_source"}:
        return False
    return True


def _quality_report_from_atlas_failure(error: Exception, processing: dict[str, Any]) -> dict[str, Any]:
    return {
        "quality_summary": {
            "pass": False,
            "total_empty_frames": 0,
            "total_clipped_frames": 0,
            "failing_states": [],
        },
        "quality_report": {
            "states": [],
            "frames": [],
        },
        "alignment_policy": processing.get("alignment_policy", {}),
        "atlas_build_error": str(error),
    }


def _write_event_feeds(paths: PipelinePaths, event: dict[str, Any]) -> None:
    latest_path = paths.event_root / "latest.json"
    bootstrap_path = paths.event_root / "bootstrap_assets.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(latest_path, event)
    if bootstrap_path.exists():
        bootstrap = _read_json(bootstrap_path)
        assets = bootstrap.get("assets", [])
    else:
        bootstrap = {"generated_at": "", "assets": []}
        assets = bootstrap["assets"]
    assets = [entry for entry in assets if entry.get("id") != event["id"]]
    assets.append(event)
    bootstrap["generated_at"] = datetime.now(timezone.utc).isoformat()
    bootstrap["assets"] = sorted(assets, key=lambda entry: entry["id"])
    _write_json(bootstrap_path, bootstrap)


def _write_frontend_manifest(
    *,
    scenario_dir: Path,
    map_grid: dict[str, Any],
    manifest: dict[str, Any],
    output_path: Path,
    package_root: Path,
) -> None:
    room_lookup = _load_room_lookup(map_grid)
    agent_entries = []
    for index, agent_ref in enumerate(manifest.get("asset_bindings", {}).get("active_agents", []), start=1):
        agent_path = (scenario_dir / agent_ref).resolve() if agent_ref.startswith(".") else (scenario_dir / agent_ref).resolve()
        profile = _read_json(agent_path)
        room = room_lookup.get(profile.get("room_id", ""))
        public_state = profile.get("public_state", {}) if isinstance(profile.get("public_state", {}), dict) else {}
        raw_agent_number = public_state.get("agent_number", profile.get("agent_number", index))
        try:
            agent_number = int(raw_agent_number)
        except Exception:
            agent_number = index
        agent_entries.append(
            {
                "agent_id": profile["agent_id"],
                "display_name": profile.get("display_name", profile["agent_id"]),
                "room_id": profile.get("room_id", ""),
                "coordinates": profile.get("coordinates", {}),
                "main_character": bool(public_state.get("main_character")),
                "role_name": public_state.get("role_name", ""),
                "activity_directive": public_state.get("activity_directive", ""),
                "appearance_prompt": profile.get("appearance_prompt", ""),
                "room_visual": (room or {}).get("visual", {}),
                "agent_number": agent_number,
            }
        )
    payload = BootstrapAgentsSpec.model_validate({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_count": len(agent_entries),
        "agents": agent_entries,
    }).model_dump()
    _write_json(output_path, payload)
