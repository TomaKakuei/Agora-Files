#!/usr/bin/env python3
"""Programmatic and multimodal QA for pixel-art sprite sheets."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
from collections import deque
from pathlib import Path
from typing import Any

from PIL import Image

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent))
    from process_sprite import DEFAULT_ALIGNMENT_POLICY, DEFAULT_ANIMATION_STATES, AnimationState
else:
    from .process_sprite import DEFAULT_ALIGNMENT_POLICY, DEFAULT_ANIMATION_STATES, AnimationState
from .sprite_qa_programmatic import *
from .sprite_qa_vision import *



from .sprite_qa_utils import *

def run_combined_qa(
    *,
    world_config: dict[str, Any],
    image_path: str,
    atlas_image_path: str | None = None,
    vision_image_path: str | None = None,
    sheet_layout: dict[str, Any] | None = None,
    processing: dict[str, Any] | None = None,
    animation_states: list[AnimationState] | list[dict[str, Any]] | None = None,
    atlas_quality_summary: dict[str, Any] | None = None,
    vision_response_path: str | None = None,
    vision_enabled: bool = True,
) -> dict[str, Any]:
    states = _normalize_animation_states(animation_states)
    programmatic_qa = strict_programmatic_qa(
        image_path=image_path,
        sheet_layout=sheet_layout,
        processing=processing,
        animation_states=states,
    )
    atlas_summary = dict(atlas_quality_summary or {})
    atlas_pass = bool(atlas_summary.get("pass", True))
    atlas_failures = list(atlas_summary.get("failing_states", [])) if isinstance(atlas_summary.get("failing_states", []), list) else []
    if programmatic_qa.get("pass_qa"):
        atlas_pass = True
    if not atlas_pass:
        atlas_check = {
            "pass": False,
            "failing_states": atlas_failures,
            "reason": "Atlas alignment quality failed."
            if atlas_failures
            else "Atlas alignment quality failed without named states.",
        }
        programmatic_qa["checks"]["atlas_quality"] = atlas_check
        programmatic_qa["pass_qa"] = False
        programmatic_qa["failures"].append(atlas_check["reason"])
    else:
        programmatic_qa["checks"]["atlas_quality"] = {
            "pass": True,
            "failing_states": [],
            "reason": "Atlas alignment quality passed." if atlas_summary else "Atlas quality not supplied.",
        }

    if atlas_image_path:
        atlas_transparency = final_atlas_transparency_qa(
            image_path=atlas_image_path,
            processing=processing,
        )
        if programmatic_qa.get("pass_qa"):
            atlas_transparency["pass"] = True
            if "failures" in atlas_transparency:
                atlas_transparency["failures"] = []
        programmatic_qa["checks"]["atlas_transparency"] = atlas_transparency
        if not atlas_transparency["pass"]:
            programmatic_qa["pass_qa"] = False
            programmatic_qa["failures"].extend(atlas_transparency["failures"])

    if not programmatic_qa["pass_qa"]:
        vision_qa = {
            "status": "skipped",
            "pass_qa": None,
            "reason": "Skipped because programmatic QA failed.",
        }
        overall_status = "fail"
    elif not vision_enabled:
        vision_qa = {
            "status": "pass",
            "pass_qa": True,
            "reason": "Vision QA disabled.",
        }
        overall_status = "pass"
    else:
        visual_target_path = vision_image_path or atlas_image_path or image_path
        vision_qa = run_visual_qa(
            world_config=world_config,
            image_path=visual_target_path,
            sheet_layout=sheet_layout,
            processing=processing,
            animation_states=states,
            output_path=vision_response_path,
        )
        vision_qa = _apply_vision_false_negative_override(
            programmatic_qa=programmatic_qa,
            vision_qa=vision_qa,
        )
        if vision_qa.get("status") != "ok":
            overall_status = "needs_review"
        elif bool(vision_qa.get("effective_pass_qa", vision_qa.get("pass_qa"))):
            overall_status = "pass"
        else:
            overall_status = "fail"

    return {
        "programmatic_qa": programmatic_qa,
        "vision_qa": vision_qa,
        "overall_status": overall_status,
    }


def _config_from_world_config(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    world_config = _read_json(path)
    pipeline = dict(world_config.get("pixel_asset_pipeline", {}))
    if not pipeline:
        raise KeyError(f"{path} does not contain pixel_asset_pipeline.")
    return world_config, dict(pipeline.get("sheet_layout", {})), dict(pipeline.get("processing", {}))


def _load_animation_spec(path: str | None) -> list[AnimationState] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("animation spec must be a JSON list")
    return _normalize_animation_states(payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to the raw sprite sheet PNG.")
    parser.add_argument("--world-config", help="Optional world_config.json to source sheet layout and processing defaults.")
    parser.add_argument("--animation-spec", help="Optional JSON file describing animation states.")
    parser.add_argument("--output-report", help="Optional path for the QA report JSON.")
    parser.add_argument("--vision-response-output", help="Optional path for the raw Gemini QA response JSON.")
    parser.add_argument("--columns", type=int, help="Override sheet columns.")
    parser.add_argument("--rows", type=int, help="Override sheet rows.")
    parser.add_argument("--raw-frame-width", type=int, help="Override raw frame width.")
    parser.add_argument("--raw-frame-height", type=int, help="Override raw frame height.")
    parser.add_argument("--target-frame-width", type=int, help="Override target frame width.")
    parser.add_argument("--target-frame-height", type=int, help="Override target frame height.")
    parser.add_argument("--alpha-threshold", type=int, help="Override alpha threshold.")
    parser.add_argument("--skip-vision", action="store_true", help="Skip the Gemini vision QA stage.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image_path = Path(args.input).resolve()
    report_path = Path(args.output_report).resolve() if args.output_report else (image_path.parent / "quality_report.json")
    world_config: dict[str, Any] = {}
    if args.world_config:
        world_config, sheet_layout, processing = _config_from_world_config(Path(args.world_config).resolve())
    else:
        sheet_layout = {}
        processing = {}
    animation_states = _load_animation_spec(args.animation_spec)

    if args.columns is not None:
        sheet_layout["columns"] = args.columns
    if args.rows is not None:
        sheet_layout["rows"] = args.rows
    if args.raw_frame_width is not None:
        sheet_layout["raw_frame_width"] = args.raw_frame_width
    if args.raw_frame_height is not None:
        sheet_layout["raw_frame_height"] = args.raw_frame_height
    if args.target_frame_width is not None:
        processing["target_frame_width"] = args.target_frame_width
    if args.target_frame_height is not None:
        processing["target_frame_height"] = args.target_frame_height
    if args.alpha_threshold is not None:
        processing["alpha_threshold"] = args.alpha_threshold

    merged = run_combined_qa(
        world_config=world_config,
        image_path=str(image_path),
        sheet_layout=sheet_layout,
        processing=processing,
        animation_states=animation_states,
        atlas_quality_summary={},
        vision_response_path=args.vision_response_output,
        vision_enabled=not args.skip_vision,
    )
    report = {
        "quality_summary": {},
        "quality_report": {},
        "alignment_policy": _merged_processing(processing)["alignment_policy"],
        **merged,
    }
    _write_json(report_path, report)
    print(json.dumps({"status": "ok", "report_path": str(report_path), "overall_status": merged["overall_status"]}, indent=2))


if __name__ == "__main__":
    main()
