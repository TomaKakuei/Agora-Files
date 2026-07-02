from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image, ImageDraw

from asset_pipeline.build_live_ready_feed import _best_existing_ready_event, _raw_sheet_passes, validate_sprite_integrity
from asset_pipeline.generate_agent_assets import _build_prompt_bundle, main as generate_agent_assets_main
from asset_pipeline.process_sprite import AnimationState, build_phaser_atlas
from asset_pipeline.sprite_qa import final_atlas_transparency_qa, run_combined_qa, run_visual_qa, strict_programmatic_qa


ROOT = Path(__file__).resolve().parents[1]


def _default_states() -> list[AnimationState]:
    return [
        AnimationState(name="idle_down", row=0, frame_count=4, frame_rate=4, repeat=0, static_frame_index=0),
        AnimationState(name="walk_down", row=1, frame_count=4, frame_rate=7, repeat=-1),
        AnimationState(name="walk_left", row=2, frame_count=4, frame_rate=7, repeat=-1),
        AnimationState(name="walk_right", row=3, frame_count=4, frame_rate=7, repeat=-1),
    ]


def _draw_sprite_body(draw: ImageDraw.ImageDraw, *, origin_x: int, origin_y: int, accent: tuple[int, int, int, int]) -> None:
    draw.rectangle((origin_x + 20, origin_y + 12, origin_x + 43, origin_y + 31), fill=(255, 232, 189, 255))
    draw.rectangle((origin_x + 18, origin_y + 32, origin_x + 45, origin_y + 70), fill=accent)
    draw.rectangle((origin_x + 10, origin_y + 38, origin_x + 17, origin_y + 62), fill=accent)
    draw.rectangle((origin_x + 46, origin_y + 38, origin_x + 53, origin_y + 62), fill=accent)
    draw.rectangle((origin_x + 23, origin_y + 71, origin_x + 31, origin_y + 104), fill=(56, 44, 44, 255))
    draw.rectangle((origin_x + 33, origin_y + 71, origin_x + 41, origin_y + 104), fill=(56, 44, 44, 255))
    draw.rectangle((origin_x + 20, origin_y + 104, origin_x + 31, origin_y + 110), fill=(26, 26, 26, 255))
    draw.rectangle((origin_x + 33, origin_y + 104, origin_x + 44, origin_y + 110), fill=(26, 26, 26, 255))


def _make_sheet(
    output_path: Path,
    *,
    columns: int,
    rows: int,
    raw_frame_width: int,
    raw_frame_height: int,
    states: list[AnimationState],
    opaque_background: bool = False,
    clip_first_frame: bool = False,
) -> None:
    background = (248, 248, 248, 255) if opaque_background else (0, 0, 0, 0)
    image = Image.new("RGBA", (columns * raw_frame_width, rows * raw_frame_height), background)
    draw = ImageDraw.Draw(image)
    for state_index, state in enumerate(states):
        for frame_index in range(state.frame_count):
            cell_x = (state.start_col + frame_index) * raw_frame_width
            cell_y = state.row * raw_frame_height
            base_x = cell_x + 32
            base_y = cell_y + 10
            shift_x = [0, 2, -2, 1][frame_index % 4]
            if "left" in state.name:
                shift_x -= 4
            elif "right" in state.name:
                shift_x += 4
            if "up" in state.name:
                base_y -= 3
            accent = (80 + (state_index * 20), 120, 180, 255)
            if clip_first_frame and state_index == 0 and frame_index == 0:
                base_x = cell_x - 24
            _draw_sprite_body(draw, origin_x=base_x + shift_x, origin_y=base_y, accent=accent)
    image.save(output_path)


def _make_incomplete_concept_sheet(output_path: Path) -> None:
    image = Image.new("RGBA", (512, 512), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    quadrants = [
        (0, 0, (220, 120, 70, 255)),
        (1, 0, (180, 100, 120, 255)),
        (0, 1, (140, 130, 200, 255)),
        (1, 1, (110, 180, 130, 255)),
    ]
    for col, row, accent in quadrants:
        origin_x = col * 128 + 32
        origin_y = row * 128 + 8
        _draw_sprite_body(draw, origin_x=origin_x, origin_y=origin_y, accent=accent)
    image.save(output_path)


def _make_disconnected_body_sheet(output_path: Path, states: list[AnimationState]) -> None:
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for state in states:
        for frame_index in range(state.frame_count):
            cell_x = (state.start_col + frame_index) * 128
            cell_y = state.row * 128
            draw.rectangle((cell_x + 46, cell_y + 10, cell_x + 82, cell_y + 54), fill=(190, 92, 120, 255))
            draw.rectangle((cell_x + 44, cell_y + 72, cell_x + 84, cell_y + 118), fill=(54, 48, 68, 255))
    image.save(output_path)


def _make_torso_jitter_sheet(output_path: Path, states: list[AnimationState]) -> None:
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    torso_shifts = [0, 14, -14, 10]
    for state_index, state in enumerate(states):
        for frame_index in range(state.frame_count):
            cell_x = (state.start_col + frame_index) * 128
            cell_y = state.row * 128
            base_x = cell_x + 32
            base_y = cell_y + 10
            accent = (80 + (state_index * 20), 120, 180, 255)
            torso_shift = torso_shifts[frame_index % len(torso_shifts)]
            leg_shift = 0
            draw.rectangle((base_x + 20 + torso_shift, base_y + 12, base_x + 43 + torso_shift, base_y + 31), fill=(255, 232, 189, 255))
            draw.rectangle((base_x + 18 + torso_shift, base_y + 32, base_x + 45 + torso_shift, base_y + 70), fill=accent)
            draw.rectangle((base_x + 10 + torso_shift, base_y + 38, base_x + 17 + torso_shift, base_y + 62), fill=accent)
            draw.rectangle((base_x + 46 + torso_shift, base_y + 38, base_x + 53 + torso_shift, base_y + 62), fill=accent)
            draw.rectangle((base_x + 23 + leg_shift, base_y + 71, base_x + 31 + leg_shift, base_y + 104), fill=(56, 44, 44, 255))
            draw.rectangle((base_x + 33 + leg_shift, base_y + 71, base_x + 41 + leg_shift, base_y + 104), fill=(56, 44, 44, 255))
            draw.rectangle((base_x + 20 + leg_shift, base_y + 104, base_x + 31 + leg_shift, base_y + 110), fill=(26, 26, 26, 255))
            draw.rectangle((base_x + 33 + leg_shift, base_y + 104, base_x + 44 + leg_shift, base_y + 110), fill=(26, 26, 26, 255))
    image.save(output_path)


def _make_cross_cell_overflow_sheet(output_path: Path, states: list[AnimationState]) -> None:
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for state_index, state in enumerate(states):
        for frame_index in range(state.frame_count):
            cell_x = (state.start_col + frame_index) * 128
            cell_y = state.row * 128
            base_x = cell_x + 32
            if state_index == 0 and frame_index == 0:
                base_x = cell_x + 90
            accent = (80 + (state_index * 20), 120, 180, 255)
            _draw_sprite_body(draw, origin_x=base_x, origin_y=cell_y + 10, accent=accent)
    image.save(output_path)


def _make_bad_edge_atlas(output_path: Path) -> None:
    atlas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(atlas)
    draw.rectangle((0, 8, 12, 24), fill=(255, 120, 120, 255))
    atlas.save(output_path)


class _VisionSuccessClient:
    def __init__(self, config: dict) -> None:
        self.config = config

    def generate_multimodal_json(self, **_: dict) -> dict:
        return {
            "pass_qa": True,
            "anatomy_check": "Pass - anatomy is readable",
            "animation_frames_check": "Pass - rows and frames are present",
            "consistency_check": "Pass - proportions remain stable",
            "background_check": "Pass - background is clean",
            "final_suggestion": "none",
        }


class _VisionTimeoutClient:
    def __init__(self, config: dict) -> None:
        self.config = config

    def generate_multimodal_json(self, **_: dict) -> dict:
        raise TimeoutError("vision timeout")


class _VisionBackgroundFailClient:
    def __init__(self, config: dict) -> None:
        self.config = config

    def generate_multimodal_json(self, **_: dict) -> dict:
        return {
            "pass_qa": False,
            "anatomy_check": "Pass - anatomy is readable",
            "animation_frames_check": "Pass - rows and frames are present",
            "consistency_check": "Pass - proportions remain stable",
            "background_check": "Fail - background is not clean enough",
            "final_suggestion": "Background cleanup would help, but the structure is solid.",
        }


class SpriteQATest(unittest.TestCase):
    def test_build_prompt_bundle_injects_anti_crop_guardrails(self) -> None:
        bundle = _build_prompt_bundle(
            world_config={"scenario_meta": {"world_name": "Test World", "world_id": "w1"}, "runner": {"domain_label": "fantasy"}},
            agent_profile={
                "agent_id": "agent_001",
                "display_name": "Mina",
                "core_values": ["care"],
                "appearance_prompt": "blue cloak",
                "public_state": {"role_name": "Scout", "personality_tags": ["kind"], "activity_directive": "watch the gate"},
            },
            room={"name": "North Gate", "visual": {"biome": "castle", "decor_tags": ["banner"], "ambient_palette": "royal_blue"}},
            pipeline_config={
                "sheet_layout": {"columns": 4, "rows": 4, "raw_frame_width": 128, "raw_frame_height": 128, "animation_states": [state.__dict__ for state in _default_states()]},
                "processing": {"target_frame_width": 32, "target_frame_height": 32},
                "sprite_generation": {},
            },
        )
        self.assertIn("Extreme Chibi style", bundle["sprite_prompt"])
        self.assertIn("1:1 perfect square bounding box", bundle["sprite_prompt"])
        self.assertIn("Massive empty transparent padding", bundle["sprite_prompt"])
        self.assertIn("dead-center in invisible grid cells", bundle["sprite_prompt"])
        self.assertIn("cropped head", bundle["negative_prompt"])
        self.assertIn("boundary crossing", bundle["negative_prompt"])

    def test_strict_programmatic_qa_passes_default_sheet(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "sheet.png"
            states = _default_states()
            _make_sheet(
                image_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
            )
            result = strict_programmatic_qa(
                image_path=str(image_path),
                sheet_layout={
                    "columns": 4,
                    "rows": 4,
                    "raw_frame_width": 128,
                    "raw_frame_height": 128,
                },
                processing={"target_frame_width": 32, "target_frame_height": 32},
                animation_states=states,
            )
            self.assertTrue(result["pass_qa"])
            self.assertTrue(result["checks"]["size"]["pass"])
            self.assertTrue(result["checks"]["background_transparency"]["pass"])

    def test_strict_programmatic_qa_rejects_opaque_background(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "sheet_opaque.png"
            states = _default_states()
            _make_sheet(
                image_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
                opaque_background=True,
            )
            result = strict_programmatic_qa(
                image_path=str(image_path),
                sheet_layout={
                    "columns": 4,
                    "rows": 4,
                    "raw_frame_width": 128,
                    "raw_frame_height": 128,
                },
                processing={"target_frame_width": 32, "target_frame_height": 32},
                animation_states=states,
            )
            self.assertFalse(result["pass_qa"])
            self.assertFalse(result["checks"]["background_transparency"]["pass"])

    def test_live_ready_scan_requires_raw_sheet_for_existing_revision(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            revision_dir = Path(tmp_dir) / "rev_missing_raw"
            revision_dir.mkdir(parents=True, exist_ok=True)
            passed, report = _raw_sheet_passes(
                revision_dir,
                sheet_layout={
                    "columns": 4,
                    "rows": 4,
                    "raw_frame_width": 128,
                    "raw_frame_height": 128,
                    "animation_states": [state.__dict__ for state in _default_states()],
                },
                processing={"target_frame_width": 32, "target_frame_height": 32},
            )
            self.assertFalse(passed)
            self.assertEqual(report["reason"], "raw_sheet_missing")

    def test_build_phaser_atlas_recenters_cross_cell_overflow(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            raw_path = Path(tmp_dir) / "overflow_sheet.png"
            atlas_path = Path(tmp_dir) / "atlas.png"
            atlas_json_path = Path(tmp_dir) / "atlas.json"
            states = _default_states()
            _make_cross_cell_overflow_sheet(raw_path, states)
            build_phaser_atlas(
                input_path=str(raw_path),
                output_sheet_path=str(atlas_path),
                output_atlas_json_path=str(atlas_json_path),
                raw_frame_width=128,
                raw_frame_height=128,
                target_frame_width=32,
                target_frame_height=32,
                palette_size=24,
                alpha_threshold=8,
                near_white_threshold=246,
                neutral_tolerance=12,
                animation_states=states,
            )
            atlas_meta = json.loads(atlas_json_path.read_text(encoding="utf-8")).get("meta", {})
            first_frame = next(
                frame
                for frame in atlas_meta.get("quality_report", {}).get("frames", [])
                if frame.get("state") == "idle_down" and frame.get("frame_index") == 0
            )
            self.assertGreater(
                first_frame["expanded_search_window"]["right"],
                first_frame["search_window"]["right"],
            )
            self.assertTrue(first_frame["integrity_pass"])
            self.assertAlmostEqual(float(first_frame["placement_center_x"]), 15.5, delta=1.5)
            self.assertEqual(int(round(float(first_frame["placement_bottom_y"]))), 30)

    def test_validate_sprite_integrity_rejects_edge_bleed(self) -> None:
        frame = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((0, 8, 10, 24), fill=(255, 120, 120, 255))
        result = validate_sprite_integrity(frame)
        self.assertFalse(result["pass"])
        self.assertTrue(result["edge_bleed"])

    def test_validate_sprite_integrity_rejects_detached_fragment(self) -> None:
        frame = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((10, 6, 20, 24), fill=(255, 120, 120, 255))
        draw.rectangle((2, 2, 5, 5), fill=(255, 220, 120, 255))
        result = validate_sprite_integrity(frame)
        self.assertFalse(result["pass"])
        self.assertTrue(any("Secondary component" in failure or "Largest component ratio" in failure for failure in result["failures"]))

    def test_validate_sprite_integrity_ignores_tiny_noise(self) -> None:
        frame = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((10, 6, 20, 24), fill=(255, 120, 120, 255))
        draw.point((2, 2), fill=(255, 255, 255, 255))
        draw.point((29, 4), fill=(255, 255, 255, 255))
        result = validate_sprite_integrity(frame)
        self.assertTrue(result["pass"])

    def test_best_existing_ready_event_rejects_bad_atlas_frame_integrity(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            revision_dir = repo_root / "frontend" / "assets" / "generated" / "agent_001" / "rev_a"
            revision_dir.mkdir(parents=True, exist_ok=True)
            raw_path = revision_dir / "raw_character_128.png"
            atlas_path = revision_dir / "agent_atlas.png"
            atlas_json_path = revision_dir / "agent_atlas.json"
            asset_bundle_path = revision_dir / "asset_bundle.json"
            states = _default_states()
            _make_sheet(
                raw_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
            )
            _make_bad_edge_atlas(atlas_path)
            atlas_json_path.write_text("{}", encoding="utf-8")
            asset_bundle_path.write_text(
                json.dumps(
                    {
                        "atlas_png": str(atlas_path),
                        "atlas_json": str(atlas_json_path),
                        "event": {
                            "id": "agent_001",
                            "display_name": "Agent 001",
                            "revision": "rev_a",
                            "generated_at": "2026-05-23T00:00:00+00:00",
                        },
                    }
                ),
                encoding="utf-8",
            )
            event, report = _best_existing_ready_event(
                repo_root,
                "agent_001",
                {
                    "columns": 4,
                    "rows": 4,
                    "raw_frame_width": 128,
                    "raw_frame_height": 128,
                    "animation_states": [state.__dict__ for state in states],
                },
                {"target_frame_width": 32, "target_frame_height": 32, "alpha_threshold": 8},
            )
            self.assertIsNone(event)
            self.assertIsNone(report)

    def test_best_existing_ready_event_rejects_non_remote_or_reused_revision(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            revision_dir = repo_root / "frontend" / "assets" / "generated" / "agent_001" / "rev_b"
            revision_dir.mkdir(parents=True, exist_ok=True)
            raw_path = revision_dir / "raw_character_128.png"
            atlas_path = revision_dir / "agent_atlas.png"
            atlas_json_path = revision_dir / "agent_atlas.json"
            asset_bundle_path = revision_dir / "asset_bundle.json"
            states = _default_states()
            _make_sheet(
                raw_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
            )
            build_phaser_atlas(
                input_path=str(raw_path),
                output_sheet_path=str(atlas_path),
                output_atlas_json_path=str(atlas_json_path),
                raw_frame_width=128,
                raw_frame_height=128,
                target_frame_width=32,
                target_frame_height=32,
                palette_size=24,
                alpha_threshold=8,
                near_white_threshold=246,
                neutral_tolerance=12,
                animation_states=states,
            )
            asset_bundle_path.write_text(
                json.dumps(
                    {
                        "atlas_png": str(atlas_path),
                        "atlas_json": str(atlas_json_path),
                        "sprite_summary": {"status": "ok", "source": "procedural_demo_sheet"},
                        "reused_raw_summary": {"status": "ok", "source": "/tmp/older.png"},
                        "event": {
                            "id": "agent_001",
                            "display_name": "Agent 001",
                            "revision": "rev_b",
                            "generated_at": "2026-05-23T00:00:00+00:00",
                        },
                    }
                ),
                encoding="utf-8",
            )
            event, report = _best_existing_ready_event(
                repo_root,
                "agent_001",
                {
                    "columns": 4,
                    "rows": 4,
                    "raw_frame_width": 128,
                    "raw_frame_height": 128,
                    "animation_states": [state.__dict__ for state in states],
                },
                {"target_frame_width": 32, "target_frame_height": 32, "alpha_threshold": 8},
            )
            self.assertIsNone(event)
            self.assertIsNone(report)

    def test_border_flood_cleanup_preserves_interior_white_details(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            raw_path = Path(tmp_dir) / "sheet_offwhite.png"
            atlas_path = Path(tmp_dir) / "atlas.png"
            atlas_json_path = Path(tmp_dir) / "atlas.json"
            states = _default_states()
            _make_sheet(
                raw_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
                opaque_background=True,
            )
            image = Image.open(raw_path).convert("RGBA")
            draw = ImageDraw.Draw(image)
            draw.rectangle((58, 58, 68, 68), fill=(255, 255, 255, 255))
            image.save(raw_path)
            build_phaser_atlas(
                input_path=str(raw_path),
                output_sheet_path=str(atlas_path),
                output_atlas_json_path=str(atlas_json_path),
                raw_frame_width=128,
                raw_frame_height=128,
                target_frame_width=32,
                target_frame_height=32,
                palette_size=24,
                alpha_threshold=8,
                near_white_threshold=246,
                neutral_tolerance=12,
                animation_states=states,
            )
            atlas = Image.open(atlas_path).convert("RGBA")
            pixels = list(atlas.getdata())
            near_white_opaque = sum(
                1
                for red, green, blue, alpha in pixels
                if alpha >= 8 and red >= 246 and green >= 246 and blue >= 246 and max(red, green, blue) - min(red, green, blue) <= 12
            )
            self.assertGreater(near_white_opaque, 0)
            self.assertLess(near_white_opaque / float(atlas.width * atlas.height), 0.005)
            self.assertEqual(atlas.getpixel((0, 0))[3], 0)

    def test_build_phaser_atlas_uses_shared_scale_factor(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            raw_path = Path(tmp_dir) / "sheet.png"
            atlas_path = Path(tmp_dir) / "atlas.png"
            atlas_json_path = Path(tmp_dir) / "atlas.json"
            states = _default_states()
            _make_sheet(
                raw_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
            )
            build_phaser_atlas(
                input_path=str(raw_path),
                output_sheet_path=str(atlas_path),
                output_atlas_json_path=str(atlas_json_path),
                raw_frame_width=128,
                raw_frame_height=128,
                target_frame_width=32,
                target_frame_height=32,
                palette_size=24,
                alpha_threshold=8,
                near_white_threshold=246,
                neutral_tolerance=12,
                animation_states=states,
            )
            atlas_meta = json.loads(atlas_json_path.read_text(encoding="utf-8")).get("meta", {})
            quality_report = atlas_meta.get("quality_report", {})
            self.assertIn("shared_scale_factor", atlas_meta)
            factors = {
                round(float(frame.get("shared_scale_factor", 0.0)), 4)
                for frame in quality_report.get("frames", [])
                if frame.get("shared_scale_factor") is not None
            }
            self.assertEqual(len(factors), 1)

    def test_final_atlas_transparency_qa_rejects_white_background(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            atlas_path = Path(tmp_dir) / "bad_atlas.png"
            Image.new("RGBA", (128, 128), (248, 248, 248, 255)).save(atlas_path)
            result = final_atlas_transparency_qa(image_path=str(atlas_path))
            self.assertFalse(result["pass"])
            self.assertGreater(result["near_white_opaque_ratio"], 0.99)

    def test_strict_programmatic_qa_detects_size_mismatch(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "sheet_bad_size.png"
            states = _default_states()
            _make_sheet(
                image_path,
                columns=4,
                rows=4,
                raw_frame_width=96,
                raw_frame_height=128,
                states=states,
            )
            result = strict_programmatic_qa(
                image_path=str(image_path),
                sheet_layout={
                    "columns": 4,
                    "rows": 4,
                    "raw_frame_width": 128,
                    "raw_frame_height": 128,
                },
                processing={"target_frame_width": 32, "target_frame_height": 32},
                animation_states=states,
            )
            self.assertFalse(result["pass_qa"])
            self.assertFalse(result["checks"]["size"]["pass"])

    def test_strict_programmatic_qa_rejects_disconnected_body_parts(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "split_body.png"
            states = _default_states()
            _make_disconnected_body_sheet(image_path, states)
            result = strict_programmatic_qa(
                image_path=str(image_path),
                sheet_layout={
                    "columns": 4,
                    "rows": 4,
                    "raw_frame_width": 128,
                    "raw_frame_height": 128,
                },
                processing={"target_frame_width": 32, "target_frame_height": 32},
                animation_states=states,
            )
            self.assertFalse(result["pass_qa"])
            self.assertFalse(result["checks"]["component_integrity"]["pass"])
            self.assertTrue(result["checks"]["component_integrity"]["failures"])

    def test_strict_programmatic_qa_rejects_torso_jitter(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "torso_jitter.png"
            states = _default_states()
            _make_torso_jitter_sheet(image_path, states)
            result = strict_programmatic_qa(
                image_path=str(image_path),
                sheet_layout={
                    "columns": 4,
                    "rows": 4,
                    "raw_frame_width": 128,
                    "raw_frame_height": 128,
                },
                processing={"target_frame_width": 32, "target_frame_height": 32},
                animation_states=states,
            )
            self.assertFalse(result["pass_qa"])
            self.assertFalse(result["checks"]["consistency"]["pass"])
            self.assertTrue(any("torso jitter" in failure.lower() for failure in result["checks"]["consistency"]["failures"]))

    def test_strict_programmatic_qa_rejects_border_contact_when_it_breaks_alignment(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "sheet_clipped.png"
            states = _default_states()
            _make_sheet(
                image_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
                clip_first_frame=True,
            )
            result = strict_programmatic_qa(
                image_path=str(image_path),
                sheet_layout={
                    "columns": 4,
                    "rows": 4,
                    "raw_frame_width": 128,
                    "raw_frame_height": 128,
                },
                processing={"target_frame_width": 32, "target_frame_height": 32},
                animation_states=states,
            )
            self.assertFalse(result["pass_qa"])
            self.assertTrue(result["checks"]["frame_bounds"]["pass"])
            self.assertFalse(result["checks"]["consistency"]["pass"])
            self.assertGreater(
                sum(1 for frame in result["frame_reports"] if frame.get("border_contact")),
                0,
            )

    def test_strict_programmatic_qa_supports_extended_animation_states(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "sheet_extended.png"
            states = [
                AnimationState(name="idle_down", row=0, frame_count=4, frame_rate=4, repeat=0, static_frame_index=0),
                AnimationState(name="walk_down", row=1, frame_count=4, frame_rate=7, repeat=-1),
                AnimationState(name="walk_left", row=2, frame_count=4, frame_rate=7, repeat=-1),
                AnimationState(name="walk_right", row=3, frame_count=4, frame_rate=7, repeat=-1),
                AnimationState(name="attack_down", row=4, frame_count=3, frame_rate=8, repeat=0),
                AnimationState(name="walk_up", row=5, frame_count=4, frame_rate=7, repeat=-1),
            ]
            _make_sheet(
                image_path,
                columns=4,
                rows=6,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
            )
            result = strict_programmatic_qa(
                image_path=str(image_path),
                sheet_layout={
                    "columns": 4,
                    "rows": 6,
                    "raw_frame_width": 128,
                    "raw_frame_height": 128,
                },
                processing={"target_frame_width": 32, "target_frame_height": 32},
                animation_states=states,
            )
            self.assertTrue(result["pass_qa"])
            self.assertEqual(result["expected_sheet_size"], {"width": 512, "height": 768})

    @patch("asset_pipeline.sprite_qa._load_runtime_clients", return_value=_VisionSuccessClient)
    def test_run_visual_qa_normalizes_success_response(self, _: object) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "sheet.png"
            states = _default_states()
            _make_sheet(
                image_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
            )
            result = run_visual_qa(
                world_config={"vertex_api": {"model": "gemini-3.1-flash"}},
                image_path=str(image_path),
                sheet_layout={"columns": 4, "rows": 4, "raw_frame_width": 128, "raw_frame_height": 128},
                processing={"target_frame_width": 32, "target_frame_height": 32},
                animation_states=states,
            )
            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["pass_qa"])
            self.assertIn("response_path", result)

    @patch("asset_pipeline.sprite_qa._load_runtime_clients", return_value=_VisionBackgroundFailClient)
    def test_run_visual_qa_requires_background_to_pass(self, _: object) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "sheet.png"
            states = _default_states()
            _make_sheet(
                image_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
            )
            result = run_visual_qa(
                world_config={"vertex_api": {"model": "gemini-3.1-flash"}},
                image_path=str(image_path),
                sheet_layout={"columns": 4, "rows": 4, "raw_frame_width": 128, "raw_frame_height": 128},
                processing={"target_frame_width": 32, "target_frame_height": 32},
                animation_states=states,
            )
            self.assertEqual(result["status"], "ok")
            self.assertFalse(result["model_pass_qa"])
            self.assertFalse(result["pass_qa"])
            self.assertFalse(result["structural_pass_qa"])
            self.assertFalse(result["background_pass"])

    @patch("asset_pipeline.sprite_qa._load_runtime_clients", return_value=_VisionTimeoutClient)
    def test_run_combined_qa_marks_needs_review_on_vision_error(self, _: object) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "sheet.png"
            states = _default_states()
            _make_sheet(
                image_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
            )
            result = run_combined_qa(
                world_config={"vertex_api": {"model": "gemini-3.1-flash"}},
                image_path=str(image_path),
                sheet_layout={"columns": 4, "rows": 4, "raw_frame_width": 128, "raw_frame_height": 128},
                processing={"target_frame_width": 32, "target_frame_height": 32},
                animation_states=states,
                atlas_quality_summary={"pass": True, "failing_states": []},
            )
            self.assertEqual(result["overall_status"], "needs_review")
            self.assertEqual(result["vision_qa"]["status"], "needs_review")

    @patch("asset_pipeline.sprite_qa._load_runtime_clients", return_value=_VisionBackgroundFailClient)
    def test_run_combined_qa_fails_when_background_qa_fails(self, _: object) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "sheet.png"
            states = _default_states()
            _make_sheet(
                image_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
            )
            result = run_combined_qa(
                world_config={"vertex_api": {"model": "gemini-3.1-flash"}},
                image_path=str(image_path),
                sheet_layout={"columns": 4, "rows": 4, "raw_frame_width": 128, "raw_frame_height": 128},
                processing={"target_frame_width": 32, "target_frame_height": 32},
                animation_states=states,
                atlas_quality_summary={"pass": True, "failing_states": []},
            )
            self.assertEqual(result["vision_qa"]["status"], "ok")
            self.assertFalse(result["vision_qa"]["pass_qa"])
            self.assertEqual(result["overall_status"], "fail")

    def test_run_combined_qa_fails_when_final_atlas_has_white_background(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "sheet.png"
            atlas_path = Path(tmp_dir) / "bad_atlas.png"
            states = _default_states()
            _make_sheet(
                image_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
            )
            Image.new("RGBA", (128, 128), (248, 248, 248, 255)).save(atlas_path)
            result = run_combined_qa(
                world_config={"vertex_api": {"model": "gemini-3.1-flash"}},
                image_path=str(image_path),
                atlas_image_path=str(atlas_path),
                sheet_layout={"columns": 4, "rows": 4, "raw_frame_width": 128, "raw_frame_height": 128},
                processing={"target_frame_width": 32, "target_frame_height": 32},
                animation_states=states,
                atlas_quality_summary={"pass": True, "failing_states": []},
            )
            self.assertEqual(result["overall_status"], "fail")
            self.assertFalse(result["programmatic_qa"]["checks"]["atlas_transparency"]["pass"])

    @patch("asset_pipeline.generate_agent_assets.run_combined_qa")
    def test_generate_agent_assets_backfills_incomplete_raw_sheet(self, mock_run_combined_qa: object) -> None:
        mock_run_combined_qa.return_value = {
            "programmatic_qa": {"pass_qa": True},
            "vision_qa": {"status": "ok", "pass_qa": True},
            "overall_status": "pass",
        }
        frontend_root = ROOT / "frontend"
        with TemporaryDirectory(dir=frontend_root) as tmp_dir:
            temp_root = Path(tmp_dir)
            output_root = temp_root / "assets" / "generated"
            event_root = output_root / "events"
            raw_sheet_path = temp_root / "incomplete_raw_character_128.png"
            config_path = temp_root / "world_config_backfill.json"
            _make_incomplete_concept_sheet(raw_sheet_path)
            config = json.loads((ROOT / "sample_json/world_config.json").read_text(encoding="utf-8"))
            config["pixel_asset_pipeline"]["processing"]["procedural_fallback_on_quality_failure"] = True
            config["vertex_api"]["model"] = "gemini-3.1-flash-lite"
            config["vertex_api"]["fallback_model"] = "gemini-3.1-flash-lite"
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            argv = [
                "generate_agent_assets.py",
                "--config",
                str(config_path),
                "--scenario-dir",
                str(ROOT / "sample_json/scenario"),
                "--agent-id",
                "guild_main_princess",
                "--raw-sheet",
                str(raw_sheet_path),
                "--output-root",
                str(output_root),
                "--event-root",
                str(event_root),
                "--revision",
                "qa_test_revision",
            ]
            with patch.object(sys, "argv", argv):
                generate_agent_assets_main()
            asset_dir = output_root / "guild_main_princess" / "qa_test_revision"
            quality_report_path = asset_dir / "quality_report.json"
            raw_sheet_qa_path = asset_dir / "raw_sheet_quality_report.json"
            bundle_path = asset_dir / "asset_bundle.json"
            payload = json.loads(quality_report_path.read_text(encoding="utf-8"))
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            raw_sheet_report = json.loads(raw_sheet_qa_path.read_text(encoding="utf-8"))
            self.assertTrue(raw_sheet_report["pass_qa"])
            self.assertIn("programmatic_qa", payload)
            self.assertIn("vision_qa", payload)
            self.assertIn("overall_status", payload)
            self.assertIn(payload["overall_status"], {"pass", "fail", "needs_review"})
            self.assertIn("quality_summary", payload)
            self.assertEqual(bundle["sprite_summary"]["status"], "quality_fallback_procedural")
            self.assertTrue(Path(bundle["raw_sheet_quality_report_path"]).is_file())

    @patch("asset_pipeline.generate_agent_assets.run_combined_qa")
    def test_generate_agent_assets_keeps_failed_raw_when_procedural_fallback_disabled(self, mock_run_combined_qa: object) -> None:
        mock_run_combined_qa.return_value = {
            "programmatic_qa": {"pass_qa": False},
            "vision_qa": {"status": "skipped", "pass_qa": None},
            "overall_status": "fail",
        }
        frontend_root = ROOT / "frontend"
        with TemporaryDirectory(dir=frontend_root) as tmp_dir:
            temp_root = Path(tmp_dir)
            output_root = temp_root / "assets" / "generated"
            event_root = output_root / "events"
            raw_sheet_path = temp_root / "incomplete_raw_character_128.png"
            config_path = temp_root / "world_config_no_backfill.json"
            _make_incomplete_concept_sheet(raw_sheet_path)
            config = json.loads((ROOT / "sample_json/world_config.json").read_text(encoding="utf-8"))
            config["pixel_asset_pipeline"]["processing"]["procedural_fallback_on_quality_failure"] = False
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            argv = [
                "generate_agent_assets.py",
                "--config",
                str(config_path),
                "--scenario-dir",
                str(ROOT / "sample_json/scenario"),
                "--agent-id",
                "guild_main_princess",
                "--raw-sheet",
                str(raw_sheet_path),
                "--output-root",
                str(output_root),
                "--event-root",
                str(event_root),
                "--revision",
                "qa_no_backfill",
            ]
            with patch.object(sys, "argv", argv):
                generate_agent_assets_main()
            bundle = json.loads((output_root / "guild_main_princess" / "qa_no_backfill" / "asset_bundle.json").read_text(encoding="utf-8"))
            self.assertEqual(bundle["sprite_summary"]["status"], "quality_warning_retained_source")
            self.assertFalse((event_root / "latest.json").exists())

    @patch("asset_pipeline.generate_agent_assets.run_combined_qa")
    def test_generate_agent_assets_bootstrap_procedural_skips_vision(self, mock_run_combined_qa: object) -> None:
        mock_run_combined_qa.return_value = {
            "programmatic_qa": {"pass_qa": True},
            "vision_qa": {"status": "skipped", "pass_qa": None},
            "overall_status": "pass",
        }
        frontend_root = ROOT / "frontend"
        with TemporaryDirectory(dir=frontend_root) as tmp_dir:
            temp_root = Path(tmp_dir)
            output_root = temp_root / "assets" / "generated"
            event_root = output_root / "events"
            config_path = temp_root / "world_config_procedural.json"
            config = json.loads((ROOT / "sample_json/world_config.json").read_text(encoding="utf-8"))
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            argv = [
                "generate_agent_assets.py",
                "--config",
                str(config_path),
                "--scenario-dir",
                str(ROOT / "sample_json/scenario"),
                "--agent-id",
                "guild_main_princess",
                "--bootstrap-procedural-sheet",
                "--output-root",
                str(output_root),
                "--event-root",
                str(event_root),
                "--revision",
                "qa_bootstrap_procedural",
            ]
            with patch.object(sys, "argv", argv):
                generate_agent_assets_main()
            self.assertFalse(mock_run_combined_qa.call_args.kwargs["vision_enabled"])

    @patch("asset_pipeline.generate_agent_assets.run_combined_qa")
    def test_generate_agent_assets_does_not_publish_failed_final_atlas(self, mock_run_combined_qa: object) -> None:
        mock_run_combined_qa.return_value = {
            "programmatic_qa": {
                "pass_qa": False,
                "checks": {"atlas_transparency": {"pass": False, "failures": ["white background"]}},
                "failures": ["white background"],
            },
            "vision_qa": {"status": "skipped", "pass_qa": None},
            "overall_status": "fail",
        }
        frontend_root = ROOT / "frontend"
        with TemporaryDirectory(dir=frontend_root) as tmp_dir:
            temp_root = Path(tmp_dir)
            output_root = temp_root / "assets" / "generated"
            event_root = output_root / "events"
            raw_sheet_path = temp_root / "raw_character_128.png"
            config_path = temp_root / "world_config_block_publish.json"
            states = _default_states()
            _make_sheet(
                raw_sheet_path,
                columns=4,
                rows=4,
                raw_frame_width=128,
                raw_frame_height=128,
                states=states,
            )
            config = json.loads((ROOT / "sample_json/world_config.json").read_text(encoding="utf-8"))
            config["pixel_asset_pipeline"]["processing"]["procedural_fallback_on_quality_failure"] = False
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            argv = [
                "generate_agent_assets.py",
                "--config",
                str(config_path),
                "--scenario-dir",
                str(ROOT / "sample_json/scenario"),
                "--agent-id",
                "guild_main_princess",
                "--raw-sheet",
                str(raw_sheet_path),
                "--output-root",
                str(output_root),
                "--event-root",
                str(event_root),
                "--revision",
                "qa_block_publish",
            ]
            with patch.object(sys, "argv", argv):
                generate_agent_assets_main()
            self.assertFalse((event_root / "latest.json").exists())
            self.assertFalse((event_root / "bootstrap_assets.json").exists())
