#!/usr/bin/env python3
"""Audit cross-modal grounding and visual production in strict Agora worlds."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "docs" / "benchmark_20260724"
AUDIT_JSON = OUT_ROOT / "multimodal_audit_20260727.json"
AUDIT_MD = OUT_ROOT / "multimodal_audit_20260727.md"

WORLD_SPECS = [
    {
        "world_name": "Clockwork Rain Conservatory",
        "draft_id": "creator_20260706_053251_1ad0b086",
        "revision_id": "r001",
        "access_code": "a0d595161b975dd0",
    },
    {
        "world_name": "Aurora Court of Migrating Cities",
        "draft_id": "creator_20260724_203817_f86ae13e",
        "revision_id": "r001",
        "access_code": "cfa9e1aa1ed06a38",
    },
    {
        "world_name": "Mycelium Patent Bazaar",
        "draft_id": "creator_20260724_211037_1c17ca96",
        "revision_id": "r001",
        "access_code": "995cad4cf9d281d9",
    },
    {
        "world_name": "Tidal Embassy of Lost Languages",
        "draft_id": "creator_20260724_215709_f5f54ceb",
        "revision_id": "r001",
        "access_code": "21c6573255c5933f",
    },
    {
        "world_name": "Sunken Satellite Monastery",
        "draft_id": "creator_20260724_224121_43ca9360",
        "revision_id": "r001",
        "access_code": "82f0356e41af144a",
    },
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_map(package_root: Path) -> Path:
    candidates = sorted(package_root.glob("materialized/assets/generated/world_asset_sets/*/world_map_source.png"))
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one packaged map under {package_root}, found {len(candidates)}")
    return candidates[0]


def _find_existing_screenshot(payload: Any) -> str:
    candidates: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "screenshot_path" and isinstance(child, str) and child.strip():
                    candidates.append(child.strip())
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    for candidate in reversed(candidates):
        if Path(candidate).is_file():
            return candidate
    return ""


def _frame_digest(atlas: Image.Image, frame: dict[str, Any]) -> str:
    box = frame.get("frame", {})
    x = int(box.get("x", 0))
    y = int(box.get("y", 0))
    width = int(box.get("w", 0))
    height = int(box.get("h", 0))
    crop = atlas.crop((x, y, x + width, y + height)).convert("RGBA")
    return hashlib.sha256(crop.tobytes()).hexdigest()


def _atlas_animation_audit(atlas_path: Path, atlas_json_path: Path) -> dict[str, Any]:
    atlas_data = _read_json(atlas_json_path)
    frames = atlas_data.get("frames", {})
    animations = atlas_data.get("animations", {})
    duplicate_animated_states = 0
    animated_states = 0
    state_unique_frames: dict[str, int] = {}
    with Image.open(atlas_path) as atlas_image:
        atlas = atlas_image.convert("RGBA")
        for state_name, animation in animations.items():
            frame_names = list(animation.get("frames", [])) if isinstance(animation, dict) else []
            if len(frame_names) <= 1:
                continue
            animated_states += 1
            digests = {
                _frame_digest(atlas, frames[frame_name])
                for frame_name in frame_names
                if frame_name in frames
            }
            state_unique_frames[state_name] = len(digests)
            if len(digests) <= 1:
                duplicate_animated_states += 1
    return {
        "animated_states": animated_states,
        "duplicate_animated_states": duplicate_animated_states,
        "state_unique_frames": state_unique_frames,
    }


def _world_audit(spec: dict[str, str]) -> dict[str, Any]:
    draft_root = ROOT / "output" / "world_creator_drafts" / spec["draft_id"]
    revision_root = draft_root / "revisions" / spec["revision_id"]
    package_root = ROOT / "output" / "package_exports" / spec["access_code"]
    world_config = _read_json(revision_root / "world_config.json")
    map_grid = _read_json(revision_root / "scenario" / "map_grid.json")
    builder_spec = _read_json(revision_root / "builder_spec.json")
    draft_manifest = _read_json(draft_root / "draft_manifest.json")
    art_status_path = revision_root / "art_status.json"
    art_status = _read_json(art_status_path) if art_status_path.is_file() else {}

    rooms = list(builder_spec.get("rooms", []))
    prompt_room_count = sum(
        1
        for room in rooms
        if isinstance(room, dict)
        and str(room.get("room_scene_prompt") or room.get("flux_floor_prompt") or "").strip()
    )
    map_path = _find_map(package_root)
    with Image.open(map_path) as map_image:
        map_size = {"width": map_image.width, "height": map_image.height}

    map_visual = map_grid.get("map_visual", {})
    tile_width = int(map_visual.get("tile_width", 32) or 32)
    tile_height = int(map_visual.get("tile_height", 32) or 32)
    grid_shape = map_grid.get("grid_shape", {})
    expected_map_size = {
        "width": int(grid_shape.get("x", 0)) * tile_width,
        "height": int(grid_shape.get("y", 0)) * tile_height,
    }
    map_generation = world_config.get("pixel_asset_pipeline", {}).get("map_generation", {})
    configured_margin = int(map_generation.get("margin_px", 0) or 0)
    frontend_world_size = {
        "width": expected_map_size["width"] + configured_margin * 2,
        "height": expected_map_size["height"] + configured_margin * 2,
    }
    map_dimension_contract_match = map_size == frontend_world_size

    all_floor_paths = sorted(map_path.parent.glob("floors/floor_*.png"))
    packaged_floor_paths = [path for path in all_floor_paths if ".rejected" not in path.name]
    rejected_floor_paths = [path for path in all_floor_paths if ".rejected" in path.name]
    packaged_agent_roots = sorted(
        path
        for path in (package_root / "materialized" / "assets" / "generated").glob("*/*")
        if (path / "character_atlas.png").is_file() and (path / "character_atlas.json").is_file()
    )

    animated_states = 0
    duplicate_animated_states = 0
    vision_qa_reports = 0
    policy_prompt_count = 0
    atlas_audits: list[dict[str, Any]] = []
    for agent_root in packaged_agent_roots:
        atlas_audit = _atlas_animation_audit(
            agent_root / "character_atlas.png",
            agent_root / "character_atlas.json",
        )
        animated_states += int(atlas_audit["animated_states"])
        duplicate_animated_states += int(atlas_audit["duplicate_animated_states"])
        atlas_audits.append(
            {
                "agent_id": agent_root.parent.name,
                **atlas_audit,
            }
        )
        source_agent_root = ROOT / "frontend" / "assets" / "generated" / agent_root.parent.name / agent_root.name
        if (source_agent_root / "vision_qa_response.json").is_file():
            vision_qa_reports += 1
        prompt_bundle_path = source_agent_root / "prompt_bundle.json"
        if prompt_bundle_path.is_file():
            prompt_bundle = _read_json(prompt_bundle_path)
            combined_prompt = " ".join(
                [
                    str(prompt_bundle.get("concept_prompt", "")),
                    str(prompt_bundle.get("sprite_prompt", "")),
                ]
            )
            if "World-authored wardrobe policy" in combined_prompt:
                policy_prompt_count += 1

    policy = world_config.get("pixel_asset_pipeline", {}).get("agent_visual_policy", {})
    component_generation = map_generation.get("component_generation", {})
    image_jobs = list(revision_root.glob("**/image_jobs/*"))
    video_jobs = list(revision_root.glob("**/longlive_jobs/*"))

    return {
        **spec,
        "world_id": str(world_config.get("scenario_meta", {}).get("world_id", "")),
        "room_count": len(rooms),
        "room_prompt_count": prompt_room_count,
        "room_prompt_coverage": prompt_room_count / len(rooms) if rooms else 0.0,
        "floor_plate_count": len(packaged_floor_paths),
        "floor_plate_coverage": len(packaged_floor_paths) / len(rooms) if rooms else 0.0,
        "rejected_floor_attempt_count": len(rejected_floor_paths),
        "wardrobe_policy_present": bool(policy),
        "wardrobe_policy_id": str(policy.get("policy_id", "")) if isinstance(policy, dict) else "",
        "agent_atlas_count": len(packaged_agent_roots),
        "agent_policy_prompt_count": policy_prompt_count,
        "agent_policy_prompt_coverage": (
            policy_prompt_count / len(packaged_agent_roots) if packaged_agent_roots else 0.0
        ),
        "animated_state_count": animated_states,
        "duplicate_animated_state_count": duplicate_animated_states,
        "duplicate_animated_state_rate": (
            duplicate_animated_states / animated_states if animated_states else 0.0
        ),
        "sprite_vision_qa_report_count": vision_qa_reports,
        "map_path": str(map_path),
        "map_size": map_size,
        "expected_grid_image_size": expected_map_size,
        "configured_margin_px": configured_margin,
        "frontend_world_size_from_config": frontend_world_size,
        "map_dimension_contract_match": map_dimension_contract_match,
        "map_qa_verdict_persisted": any(
            key in art_status for key in ("map_qa", "map_qa_result", "gemini_map_qa")
        ),
        "component_generation_enabled": bool(component_generation.get("enabled", False)),
        "interaction_image_artifact_count": len(image_jobs),
        "interaction_video_artifact_count": len(video_jobs),
        "screenshot_path": _find_existing_screenshot(draft_manifest),
        "atlas_audits": atlas_audits,
    }


def _summary(worlds: list[dict[str, Any]]) -> dict[str, Any]:
    total_rooms = sum(int(world["room_count"]) for world in worlds)
    total_room_prompts = sum(int(world["room_prompt_count"]) for world in worlds)
    total_floors = sum(int(world["floor_plate_count"]) for world in worlds)
    total_rejected_floors = sum(int(world["rejected_floor_attempt_count"]) for world in worlds)
    total_atlases = sum(int(world["agent_atlas_count"]) for world in worlds)
    total_policy_prompts = sum(int(world["agent_policy_prompt_count"]) for world in worlds)
    total_animated_states = sum(int(world["animated_state_count"]) for world in worlds)
    total_duplicate_states = sum(int(world["duplicate_animated_state_count"]) for world in worlds)
    return {
        "world_count": len(worlds),
        "room_count": total_rooms,
        "room_prompt_coverage": total_room_prompts / total_rooms if total_rooms else 0.0,
        "floor_plate_coverage": total_floors / total_rooms if total_rooms else 0.0,
        "rejected_floor_attempt_count": total_rejected_floors,
        "wardrobe_policy_worlds": sum(bool(world["wardrobe_policy_present"]) for world in worlds),
        "agent_atlas_count": total_atlases,
        "agent_policy_prompt_coverage": total_policy_prompts / total_atlases if total_atlases else 0.0,
        "duplicate_animated_state_rate": (
            total_duplicate_states / total_animated_states if total_animated_states else 0.0
        ),
        "sprite_vision_qa_coverage": (
            sum(int(world["sprite_vision_qa_report_count"]) for world in worlds) / total_atlases
            if total_atlases
            else 0.0
        ),
        "map_dimension_contract_matches": sum(
            bool(world["map_dimension_contract_match"]) for world in worlds
        ),
        "map_qa_verdicts_persisted": sum(bool(world["map_qa_verdict_persisted"]) for world in worlds),
        "component_generation_enabled_worlds": sum(
            bool(world["component_generation_enabled"]) for world in worlds
        ),
        "interaction_image_artifact_count": sum(
            int(world["interaction_image_artifact_count"]) for world in worlds
        ),
        "interaction_video_artifact_count": sum(
            int(world["interaction_video_artifact_count"]) for world in worlds
        ),
    }


def _markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Agora Multimodal Capability Audit",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "This audit distinguishes implemented cross-modal conditioning from visual quality and from declared-but-unobserved runtime media paths.",
        "",
        "## Aggregate Findings",
        "",
        f"- Worlds audited: `{summary['world_count']}`",
        f"- Room prompt coverage: `{summary['room_prompt_coverage']:.3f}`",
        f"- Packaged room-floor coverage: `{summary['floor_plate_coverage']:.3f}`",
        f"- Retained rejected floor attempts: `{summary['rejected_floor_attempt_count']}`",
        f"- Worlds with generated wardrobe policy: `{summary['wardrobe_policy_worlds']}/{summary['world_count']}`",
        f"- Packaged agent atlases: `{summary['agent_atlas_count']}`",
        f"- Agent prompts carrying the generated wardrobe policy: `{summary['agent_policy_prompt_coverage']:.3f}`",
        f"- Animated states with only one unique frame: `{summary['duplicate_animated_state_rate']:.3f}`",
        f"- Agent atlases with persisted sprite vision QA: `{summary['sprite_vision_qa_coverage']:.3f}`",
        f"- Maps matching the frontend margin-derived dimensions: `{summary['map_dimension_contract_matches']}/{summary['world_count']}`",
        f"- Persisted map-QA verdicts: `{summary['map_qa_verdicts_persisted']}/{summary['world_count']}`",
        f"- Worlds with component generation enabled: `{summary['component_generation_enabled_worlds']}/{summary['world_count']}`",
        f"- Observed interaction image/video artifacts: `{summary['interaction_image_artifact_count']}/{summary['interaction_video_artifact_count']}`",
        "",
        "## Per-World Evidence",
        "",
        "| World | Rooms | Floor plates | Atlases | Policy prompts | Duplicate animated states | Map contract |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for world in payload["worlds"]:
        lines.append(
            f"| {world['world_name']} | {world['room_count']} | {world['floor_plate_count']} | "
            f"{world['agent_atlas_count']} | {world['agent_policy_prompt_count']} | "
            f"{world['duplicate_animated_state_count']}/{world['animated_state_count']} | "
            f"{'match' if world['map_dimension_contract_match'] else 'mismatch'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The system has real semantic-to-visual conditioning: every audited room carries a room-specific prompt and packaged floor plate, and every world carries a generated wardrobe policy. The audit does not show corresponding production quality. Current character atlases expose static repeated frames under animated labels, sprite vision QA is not connected to the production path, map dimensions disagree with the frontend's configured margin, and map-QA verdicts are not persisted with the final revision. Component/icon generation and interaction-time image/video paths are configured or implemented in code but are not evidenced by the audited artifacts.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    worlds = [_world_audit(spec) for spec in WORLD_SPECS]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "scope": "five current strict-pipeline worlds",
            "animation_duplicate_test": "SHA-256 equality over atlas frame RGBA bytes within declared animated states",
            "map_contract_test": "packaged map dimensions compared with grid_size * tile_size + 2 * configured frontend margin",
            "qa_persistence_test": "final art_status contains an explicit map-QA verdict and per-agent source directory contains vision_qa_response.json",
        },
        "summary": _summary(worlds),
        "worlds": worlds,
    }
    AUDIT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    AUDIT_MD.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps({"json": str(AUDIT_JSON), "markdown": str(AUDIT_MD), "summary": payload["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
