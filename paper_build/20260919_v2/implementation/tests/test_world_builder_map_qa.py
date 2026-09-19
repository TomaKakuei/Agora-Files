from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from PIL import Image

from agora_ui.world_builder.art import (
    _map_dimension_contract,
    _map_floor_projection_certificate,
    _map_qa_codes_with_compiler_evidence,
    _map_qa_codes_with_textual_evidence,
    _normalize_map_qa_repair_localization,
    _semantic_component_coverage,
)
from asset_pipeline.generate_world_asset_set_full import (
    _component_prompt,
    _prepare_component_icon,
)


class WorldBuilderMapQaTest(unittest.TestCase):
    def test_component_drift_localizes_room_from_reasoning(self) -> None:
        codes, rooms, scope = _normalize_map_qa_repair_localization(
            error_codes=["component_perspective_drift"],
            failing_room_names=[],
            room_names=["Archive", "Exchange", "Commons"],
            repair_scope="mixed",
            reasoning="The Exchange prop exposes a front face.",
        )

        self.assertEqual(codes, ["component_perspective_drift"])
        self.assertEqual(rooms, ["Exchange"])
        self.assertEqual(scope, "room_asset")

    def test_unlocalized_room_asset_error_expands_to_all_rooms(self) -> None:
        codes, rooms, scope = _normalize_map_qa_repair_localization(
            error_codes=["perspective_drift"],
            failing_room_names=[],
            room_names=["Archive", "Exchange"],
            repair_scope="mixed",
            reasoning="Every semantic prop uses an incompatible projection.",
        )

        self.assertEqual(codes, ["perspective_drift"])
        self.assertEqual(rooms, ["Archive", "Exchange"])
        self.assertEqual(scope, "room_asset")

    def test_compositor_error_does_not_trigger_room_asset_regeneration(self) -> None:
        codes, rooms, scope = _normalize_map_qa_repair_localization(
            error_codes=["door_transition_error"],
            failing_room_names=["Archive"],
            room_names=["Archive", "Exchange"],
            repair_scope="compositor",
            reasoning="A doorway is disconnected.",
        )

        self.assertEqual(codes, ["door_transition_error"])
        self.assertEqual(rooms, ["Archive"])
        self.assertEqual(scope, "compositor")

    def test_semantic_component_prompt_forces_overhead_projection(self) -> None:
        prompt = _component_prompt(
            {
                "component_type": "prop",
                "component_id": "machine",
                "label": "Flow machine",
                "description": "A copper flow regulator.",
            },
            world_name="River Embassy",
            visual_canon={"world_prompt_prefix": "indigo water and salt-white stone"},
        )

        self.assertIn("ORTHOGRAPHIC 90-degree overhead", prompt)
        self.assertIn("no front or side faces", prompt)
        self.assertIn("No person, head, face, body", prompt)
        self.assertIn("Flow machine", prompt)
        self.assertLessEqual(len(prompt.split()), 70)

    def test_projection_repair_compiles_vertical_subject_to_floor_plan(self) -> None:
        prompt = _component_prompt(
            {
                "component_type": "prop",
                "component_id": "crane",
                "label": "Storm Cell Crane",
                "description": "A tall steel crane arm above a loading yard.",
            },
            world_name="Weather Market",
            visual_canon={"world_prompt_prefix": "dark weather machinery with yellow signals"},
            repair_attempt=1,
        )

        self.assertIn("FLAT 2D FLOOR-PLAN SPRITE", prompt)
        self.assertIn("compact horizontal footprint", prompt)
        self.assertIn("collapse height", prompt)
        self.assertNotIn("tall steel crane arm", prompt)
        self.assertLessEqual(len(prompt.split()), 70)

    def test_projection_code_requires_projection_evidence(self) -> None:
        codes = _map_qa_codes_with_textual_evidence(
            ["component_perspective_drift"],
            "The component is an abstract placeholder and should contain more detail.",
        )

        self.assertEqual(codes, ["none"])

    def test_projection_code_keeps_supported_visual_failure(self) -> None:
        codes = _map_qa_codes_with_textual_evidence(
            ["component_perspective_drift"],
            "The crane exposes a deep side face and loses its top-down footprint.",
        )

        self.assertEqual(codes, ["component_perspective_drift"])

    def test_compiler_coverage_rejects_false_semantic_absence_claim(self) -> None:
        codes = _map_qa_codes_with_compiler_evidence(
            ["blank_void"],
            "Two rooms are missing their required semantic components.",
            {
                "status": "ok",
                "expected_count": 10,
                "placed_count": 10,
                "missing_component_ids": [],
                "unreadable_component_ids": [],
            },
        )

        self.assertEqual(codes, ["none"])

    def test_compiler_coverage_does_not_hide_real_empty_layout_claim(self) -> None:
        codes = _map_qa_codes_with_compiler_evidence(
            ["blank_void"],
            "The logistics yard is mostly empty floor with both tiny props clustered at one edge.",
            {
                "status": "ok",
                "expected_count": 10,
                "placed_count": 10,
                "missing_component_ids": [],
                "unreadable_component_ids": [],
            },
        )

        self.assertEqual(codes, ["blank_void"])

    def test_component_cleanup_removes_edge_connected_studio_background(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.png"
            output_path = Path(temp_dir) / "icon.png"
            image = Image.new("RGB", (64, 64), (218, 220, 221))
            for y in range(18, 46):
                for x in range(20, 44):
                    image.putpixel((x, y), (132, 42, 48))
            image.save(source_path)

            _prepare_component_icon(source_path, output_path, icon_px=64)

            cleaned = Image.open(output_path).convert("RGBA")
            self.assertEqual(cleaned.getpixel((0, 0))[3], 0)
            self.assertGreater(cleaned.getpixel((32, 32))[3], 0)

    def test_floor_projection_certificate_requires_all_layered_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            map_path = Path(temp_dir) / "world_map_source.png"
            map_path.touch()
            floor_root = map_path.parent / "floors"
            floor_root.mkdir()
            (floor_root / "floor_room_01.qa.json").write_text(
                (
                    '{"pass": true, "size_ok": true, '
                    '"geometry_conditioning": "procedural_visual_canon_floor", '
                    '"render_mode": "layered"}'
                ),
                encoding="utf-8",
            )

            certificate = _map_floor_projection_certificate(
                map_path,
                ["room_01", "room_02"],
            )

            self.assertEqual(certificate["status"], "incomplete")
            self.assertEqual(certificate["certified_room_count"], 1)

    def test_map_dimension_contract_reports_exact_mismatch(self) -> None:
        config = {
            "space": {"width_tiles": 12, "height_tiles": 8},
            "pixel_asset_pipeline": {
                "map_generation": {"tile_px": 32, "margin_px": 16}
            },
        }

        passed = _map_dimension_contract(config, (416, 288))
        failed = _map_dimension_contract(config, (415, 288))

        self.assertTrue(passed["pass"])
        self.assertFalse(failed["pass"])
        self.assertEqual(failed["error_code"], "margin_contract_mismatch")

    def test_semantic_component_coverage_distinguishes_missing_and_unreadable(self) -> None:
        config = {
            "space": {
                "rooms": [
                    {
                        "visual": {
                            "scene_components": [
                                {"component_id": "tide_clock"},
                                {"component_id": "river_urn"},
                            ]
                        }
                    }
                ]
            }
        }
        sidecar = {
            "schema_version": "agora.map_component_placements.v2",
            "placements": [
                {
                    "component_id": "tide_clock",
                    "semantic_generated": True,
                    "pasted": True,
                    "readability_pass": False,
                }
            ],
        }

        coverage = _semantic_component_coverage(config, sidecar)

        self.assertEqual(coverage["status"], "error")
        self.assertEqual(coverage["missing_component_ids"], ["river_urn"])
        self.assertEqual(coverage["unreadable_component_ids"], ["tide_clock"])


if __name__ == "__main__":
    unittest.main()
