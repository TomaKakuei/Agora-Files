from __future__ import annotations

import unittest

from agora_ui.agent_factory import _room_spawn_cells
from agora_ui.live_world.geometry import (
    _room_interior_tiles,
    _room_walk_path,
    _safe_room_spawn,
)


class LiveWorldSpawnGeometryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.room = {
            "room_id": "room_condensation_commons",
            "x": 10,
            "y": 26,
            "z": 0,
            "width_tiles": 12,
            "height_tiles": 10,
            "footprint_tiles": [],
            "doorways": [
                {"position": {"x": 15, "y": 26, "z": 0}},
                {"position": {"x": 10, "y": 28, "z": 0}},
            ],
            "obstacles": [],
        }

    def test_factory_prefers_interior_spawn_cells(self) -> None:
        cells = _room_spawn_cells(self.room)
        self.assertTrue(cells)
        self.assertTrue(all(10 < cell.x < 21 for cell in cells))
        self.assertTrue(all(26 < cell.y < 35 for cell in cells))

    def test_safe_spawn_preserves_mobile_boundary_coordinate(self) -> None:
        requested = {"x": 10, "y": 32, "z": 0}
        self.assertEqual(
            _safe_room_spawn(self.room, "agent_07", requested),
            requested,
        )

    def test_safe_spawn_relocates_trapped_corner(self) -> None:
        requested = {"x": 10, "y": 35, "z": 0}
        relocated = _safe_room_spawn(self.room, "agent_10", requested)
        self.assertNotEqual(relocated, requested)
        self.assertIn(relocated, _room_interior_tiles(self.room))

    def test_roaming_path_avoids_wall_boundary(self) -> None:
        path = _room_walk_path(self.room, "agent_10")
        self.assertTrue(path)
        self.assertTrue(all(10 < tile["x"] < 21 for tile in path))
        self.assertTrue(all(26 < tile["y"] < 35 for tile in path))

    def test_small_room_roaming_falls_back_when_interior_has_one_tile(self) -> None:
        room = {
            "room_id": "room_small",
            "x": 0,
            "y": 0,
            "z": 0,
            "width_tiles": 3,
            "height_tiles": 3,
            "footprint_tiles": [],
            "doorways": [],
            "obstacles": [],
        }
        self.assertEqual(len(_room_interior_tiles(room)), 1)
        self.assertGreater(len(_room_walk_path(room, "agent_small")), 1)

    def test_explicit_spawn_points_remain_authoritative(self) -> None:
        room = {
            **self.room,
            "spawn_points": [{"x": 10, "y": 28, "z": 0}],
        }
        cells = _room_spawn_cells(room)
        self.assertEqual(
            [cell.model_dump() for cell in cells],
            [{"x": 10, "y": 28, "z": 0}],
        )


if __name__ == "__main__":
    unittest.main()
