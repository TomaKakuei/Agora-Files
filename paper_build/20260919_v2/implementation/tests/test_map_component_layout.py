from __future__ import annotations

import unittest

from asset_pipeline.map_rendering.compositor import (
    _boxes_overlap,
    _component_box,
    _room_component_placements,
)
from asset_pipeline.generate_world_asset_set_full import (
    _sprite_batch_input_fingerprint,
    _supporting_prop_overlay_enabled,
    _validated_cached_sprite_batch_qa,
)


class MapComponentLayoutTest(unittest.TestCase):
    def test_legacy_canon_config_respects_explicit_support_disable(self) -> None:
        pipeline = {
            "visual_canon": {"canon_hash": "legacy"},
            "map_generation": {"overlay_supporting_props": False},
        }

        self.assertFalse(_supporting_prop_overlay_enabled(pipeline))

    def test_unversioned_config_does_not_silently_enable_support(self) -> None:
        pipeline = {
            "visual_canon": {"canon_hash": "legacy"},
            "map_generation": {},
        }

        self.assertFalse(_supporting_prop_overlay_enabled(pipeline))

    def test_versioned_config_respects_explicit_support_disable(self) -> None:
        pipeline = {
            "visual_canon": {"canon_hash": "current"},
            "map_generation": {
                "overlay_supporting_props": False,
                "supporting_prop_policy_version": "collision_aware_v2",
            },
        }

        self.assertFalse(_supporting_prop_overlay_enabled(pipeline))

    def test_versioned_config_enables_support_by_default(self) -> None:
        pipeline = {
            "map_generation": {
                "supporting_prop_policy_version": "collision_aware_v2",
            },
        }

        self.assertTrue(_supporting_prop_overlay_enabled(pipeline))

    def test_semantic_component_keeps_anchor_and_supporting_prop_relocates(self) -> None:
        room = {
            "room_id": "room_01",
            "visual": {"decor_tags": ["supporting_table"]},
            "metadata": {},
        }
        component_library = {
            "props": {
                "supporting_table": {
                    "anchor": "center",
                    "size_tiles": {"w": 2, "h": 2},
                },
                "semantic_machine": {
                    "anchor": "center",
                    "size_tiles": {"w": 3, "h": 3},
                    "semantic_generated": True,
                },
            },
            "room_layout_presets": {
                "room_01": {
                    "supplemental_props": [
                        {"component_id": "semantic_machine", "anchor": "center"},
                    ],
                },
            },
            "room_archetype_presets": {},
        }
        room_box = (0, 0, 320, 320)

        placements = _room_component_placements(
            room,
            component_library=component_library,
            tile_px=32,
            room_box=room_box,
        )

        placement_by_id = {
            component_id: box
            for component_id, _spec, box in placements
        }
        semantic_box = placement_by_id["semantic_machine"]
        supporting_box = placement_by_id["supporting_table"]
        self.assertEqual(semantic_box, (117, 117, 203, 203))
        self.assertFalse(_boxes_overlap(semantic_box, supporting_box, gap=4))

    def test_semantic_components_are_never_dropped_when_authored_anchors_overlap(self) -> None:
        room = {
            "room_id": "room_01",
            "visual": {"decor_tags": []},
            "metadata": {},
        }
        component_library = {
            "props": {
                "machine_a": {
                    "anchor": "center",
                    "size_tiles": {"w": 2, "h": 2},
                    "semantic_generated": True,
                },
                "machine_b": {
                    "anchor": "center",
                    "size_tiles": {"w": 2, "h": 2},
                    "semantic_generated": True,
                },
            },
            "room_layout_presets": {
                "room_01": {
                    "supplemental_props": [
                        {"component_id": "machine_a", "anchor": "center"},
                        {"component_id": "machine_b", "anchor": "center"},
                    ],
                },
            },
            "room_archetype_presets": {},
        }

        placements = _room_component_placements(
            room,
            component_library=component_library,
            tile_px=32,
            room_box=(0, 0, 320, 320),
        )

        self.assertEqual(
            [component_id for component_id, _spec, _box in placements],
            ["machine_a", "machine_b"],
        )
        self.assertFalse(_boxes_overlap(placements[0][2], placements[1][2], gap=4))

    def test_square_generated_icon_gets_readable_semantic_footprint(self) -> None:
        box = _component_box(
            {
                "anchor": "north_mid",
                "size_tiles": {"w": 3, "h": 1},
                "semantic_generated": True,
            },
            room_box=(0, 0, 320, 320),
            tile_px=32,
        )

        self.assertEqual(box, (117, 8, 203, 94))

    def test_sprite_qa_cache_requires_matching_input_fingerprint(self) -> None:
        visual_canon = {"canon_hash": "canon-1", "palette": ["#111111"]}
        records = [
            {
                "agent_id": "agent-1",
                "asset_bundle_path": "/missing/asset_bundle.json",
            }
        ]
        fingerprint = _sprite_batch_input_fingerprint(
            visual_canon=visual_canon,
            agent_records=records,
        )
        cached = {
            "status": "ok",
            "overall_pass": True,
            "visual_canon_hash": "canon-1",
            "input_fingerprint": fingerprint,
            "agents": [{"agent_id": "agent-1", "pass_qa": True}],
        }

        self.assertIsNotNone(
            _validated_cached_sprite_batch_qa(
                cached_qa=cached,
                visual_canon=visual_canon,
                agent_records=records,
                input_fingerprint=fingerprint,
            )
        )
        self.assertIsNone(
            _validated_cached_sprite_batch_qa(
                cached_qa=cached,
                visual_canon=visual_canon,
                agent_records=records,
                input_fingerprint="changed",
            )
        )


if __name__ == "__main__":
    unittest.main()
