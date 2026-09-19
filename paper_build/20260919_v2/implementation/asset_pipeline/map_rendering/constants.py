from __future__ import annotations

import json
from pathlib import Path
from PIL import Image


PALETTE = {
    "warm_lantern": ("#c88d53", "#f4d3a3", "#6e4327"),
    "gold_paper": ("#d3b15a", "#f6e1a4", "#7b5921"),
    "amber_tavern": ("#a96943", "#f0c296", "#5f3223"),
    "dusty_brown": ("#977458", "#dbc2a7", "#573d2d"),
    "ember_orange": ("#ca6c3a", "#ffc98f", "#6c2718"),
    "soft_mint": ("#7fb8a3", "#d8f1e6", "#32685d"),
    "clear_day": ("#8bb171", "#e5f1c5", "#45603a"),
    "violet_arcane": ("#8a73be", "#e1d7fb", "#43305f"),
    "focused_blue": ("#6f99c6", "#d7e9fb", "#27496d"),
    "low_lantern": ("#8e7d68", "#e3d2bc", "#4d4336"),
}

DEFAULT_COMPONENT_LIBRARY = {
    "floor_tiles": {
        "stone_hall": {"pattern": "stone_checker"},
        "quest_parchment": {"pattern": "paper_grid"},
        "market_stone": {"pattern": "stone_checker"},
        "aged_planks": {"pattern": "wood_planks"},
        "courtyard_brick": {"pattern": "yard_pavers"},
        "archive_tile": {"pattern": "library_planks"},
        "tavern_planks": {"pattern": "wood_planks"},
        "storage_stone": {"pattern": "stone_slabs"},
        "forge_slate": {"pattern": "forge_slate"},
        "infirmary_tile": {"pattern": "clean_tile"},
        "yard_pavers": {"pattern": "yard_pavers"},
        "library_wood": {"pattern": "library_planks"},
        "war_room_inlay": {"pattern": "war_room_inlay"},
        "dormitory_planks": {"pattern": "dorm_planks"},
        "bamboo_planks": {"pattern": "bamboo_planks"},
        "red_brick": {"pattern": "red_brick"},
        "jade_tile": {"pattern": "jade_tile"},
    },
    "wall_tiles": {
        "wood_beam_wall": {"trim": "wood_beam"},
        "board_trim_wall": {"trim": "notice_trim"},
        "stall_canvas_wall": {"trim": "notice_trim"},
        "quiet_lane_wall": {"trim": "library_trim"},
        "courtyard_brick_wall": {"trim": "yard_trim"},
        "glass_case_wall": {"trim": "clean_trim"},
        "tavern_wall": {"trim": "tavern_trim"},
        "storage_wall": {"trim": "storage_trim"},
        "forge_wall": {"trim": "forge_trim"},
        "healer_wall": {"trim": "clean_trim"},
        "yard_fence": {"trim": "yard_trim"},
        "library_shelf_wall": {"trim": "library_trim"},
        "war_room_wall": {"trim": "war_trim"},
        "dorm_wall": {"trim": "dorm_trim"},
        "red_pillar_wall": {"trim": "red_pillar_trim"},
        "bamboo_wall": {"trim": "bamboo_trim"},
    },
    "props": {
        "guild_banner": {"render": "banner", "anchor": "east_mid", "size_tiles": {"w": 1, "h": 2}, "label": "Guild Banner"},
        "notice_table": {"render": "table_notice", "anchor": "west_mid", "size_tiles": {"w": 2, "h": 2}, "label": "Notice Table"},
        "quest_board": {"render": "board", "anchor": "north_mid", "size_tiles": {"w": 2, "h": 2}, "label": "Quest Board"},
        "sealed_requests": {"render": "scroll_stack", "anchor": "south_mid", "size_tiles": {"w": 1, "h": 1}, "label": "Sealed Requests"},
        "round_table": {"render": "round_table", "anchor": "center", "size_tiles": {"w": 2, "h": 2}, "label": "Round Table"},
        "mug_shelf": {"render": "shelf", "anchor": "north_east", "size_tiles": {"w": 2, "h": 1}, "label": "Mug Shelf"},
        "supply_crates": {"render": "crate_stack", "anchor": "west_mid", "size_tiles": {"w": 2, "h": 2}, "label": "Supply Crates"},
        "rope_coils": {"render": "coil", "anchor": "south_mid", "size_tiles": {"w": 1, "h": 1}, "label": "Rope Coils"},
        "anvil": {"render": "anvil", "anchor": "west_mid", "size_tiles": {"w": 2, "h": 1}, "label": "Anvil"},
        "glowing_furnace": {"render": "furnace", "anchor": "east_mid", "size_tiles": {"w": 2, "h": 2}, "label": "Glowing Furnace"},
        "medicine_shelf": {"render": "shelf", "anchor": "north_mid", "size_tiles": {"w": 2, "h": 1}, "label": "Medicine Shelf"},
        "rest_bed": {"render": "bed", "anchor": "south_mid", "size_tiles": {"w": 2, "h": 2}, "label": "Rest Bed"},
        "practice_dummy": {"render": "dummy", "anchor": "center", "size_tiles": {"w": 1, "h": 2}, "label": "Practice Dummy"},
        "weapon_rack": {"render": "rack", "anchor": "east_mid", "size_tiles": {"w": 2, "h": 1}, "label": "Weapon Rack"},
        "floating_runes": {"render": "runes", "anchor": "center", "size_tiles": {"w": 2, "h": 2}, "label": "Floating Runes"},
        "scroll_table": {"render": "table_scroll", "anchor": "south_mid", "size_tiles": {"w": 2, "h": 2}, "label": "Scroll Table"},
        "strategy_table": {"render": "table_map", "anchor": "center", "size_tiles": {"w": 2, "h": 2}, "label": "Strategy Table"},
        "region_map": {"render": "map_stand", "anchor": "north_mid", "size_tiles": {"w": 2, "h": 1}, "label": "Region Map"},
        "bunk_beds": {"render": "bunks", "anchor": "west_mid", "size_tiles": {"w": 2, "h": 2}, "label": "Bunk Beds"},
        "nightstand_cluster": {"render": "nightstand", "anchor": "east_mid", "size_tiles": {"w": 1, "h": 1}, "label": "Nightstand Cluster"},
        "travel_packs": {"render": "travel_pack", "anchor": "south_west", "size_tiles": {"w": 2, "h": 1}, "label": "Travel Packs"},
        "display_table": {"render": "table_notice", "anchor": "center", "size_tiles": {"w": 2, "h": 2}, "label": "Display Table"},
        "glass_case": {"render": "shelf", "anchor": "north_mid", "size_tiles": {"w": 2, "h": 1}, "label": "Glass Case"},
        "paper_stack": {"render": "scroll_stack", "anchor": "south_mid", "size_tiles": {"w": 1, "h": 1}, "label": "Paper Stack"},
        "packing_crate": {"render": "crate_stack", "anchor": "west_mid", "size_tiles": {"w": 2, "h": 2}, "label": "Packing Crate"},
        "inspection_lamp": {"render": "nightstand", "anchor": "east_mid", "size_tiles": {"w": 1, "h": 1}, "label": "Inspection Lamp"},
        "ledger_desk": {"render": "table_map", "anchor": "center", "size_tiles": {"w": 2, "h": 2}, "label": "Ledger Desk"},
        "handcart": {"render": "crate_stack", "anchor": "south_west", "size_tiles": {"w": 2, "h": 2}, "label": "Handcart"},
        "repair_bench": {"render": "table_scroll", "anchor": "center", "size_tiles": {"w": 2, "h": 2}, "label": "Repair Bench"},
        "cloth_wraps": {"render": "travel_pack", "anchor": "south_mid", "size_tiles": {"w": 2, "h": 1}, "label": "Cloth Wraps"},
        "tea_stool": {"render": "nightstand", "anchor": "center", "size_tiles": {"w": 1, "h": 1}, "label": "Tea Stool"},
        "tea_shelf": {"render": "shelf", "anchor": "north_east", "size_tiles": {"w": 2, "h": 1}, "label": "Tea Shelf"},
    },
    "pickup_items": {
        "healing_potion": {"render": "potion_red", "label": "Healing Potion"},
        "quest_map": {"render": "map_scroll", "label": "Quest Map"},
        "signed_commission": {"render": "quest_notice", "label": "Signed Commission"},
        "repair_kit": {"render": "toolkit", "label": "Repair Kit"},
        "rations": {"render": "food_pack", "label": "Rations"},
        "herb_bundle": {"render": "herb_bundle", "label": "Herb Bundle"},
        "iron_ingot": {"render": "iron_ingot", "label": "Iron Ingot"},
    },
    "room_layout_presets": {
        "guild_hall": {"supplemental_props": [{"component_id": "guild_banner", "anchor": "north_east"}]},
        "quest_board": {"supplemental_props": [{"component_id": "sealed_requests", "anchor": "south_west"}]},
        "tavern_corner": {"supplemental_props": [{"component_id": "round_table", "anchor": "south_mid"}]},
        "warehouse": {"supplemental_props": [{"component_id": "rope_coils", "anchor": "south_west"}]},
        "forge_workshop": {"supplemental_props": [{"component_id": "anvil", "anchor": "south_west"}]},
        "infirmary": {"supplemental_props": [{"component_id": "rest_bed", "anchor": "south_west"}]},
        "training_yard": {"supplemental_props": [{"component_id": "practice_dummy", "anchor": "center"}]},
        "arcane_library": {"supplemental_props": [{"component_id": "floating_runes", "anchor": "center"}]},
        "strategy_table": {"supplemental_props": [{"component_id": "strategy_table", "anchor": "center"}]},
        "dormitory": {
            "supplemental_props": [
                {"component_id": "nightstand_cluster", "anchor": "south_east"},
                {"component_id": "travel_packs", "anchor": "south_west"},
            ]
        },
    },
    "room_archetype_presets": {
        "market_exchange": {"supplemental_props": [{"component_id": "sealed_requests", "anchor": "south_west"}]},
        "checkpoint": {"supplemental_props": [{"component_id": "region_map", "anchor": "north_mid"}]},
        "logistics_yard": {"supplemental_props": [{"component_id": "rope_coils", "anchor": "south_west"}]},
        "lookout": {"supplemental_props": [{"component_id": "region_map", "anchor": "north_mid"}]},
        "workshop": {"supplemental_props": [{"component_id": "anvil", "anchor": "south_west"}]},
        "archive_ritual": {"supplemental_props": [{"component_id": "floating_runes", "anchor": "center"}]},
        "rest_social": {"supplemental_props": [{"component_id": "round_table", "anchor": "south_mid"}]},
        "training": {"supplemental_props": [{"component_id": "practice_dummy", "anchor": "center"}]},
        "council": {"supplemental_props": [{"component_id": "strategy_table", "anchor": "center"}]},
        "commons": {"supplemental_props": [{"component_id": "notice_table", "anchor": "west_mid"}]},
    },
}

DEFAULT_WORLD_TERRAIN = {
    "default_ground": "meadow_grass",
    "grass_base_hex": "#739d59",
    "grass_alt_hex": "#86ad65",
    "grass_shadow_hex": "#4d6d39",
    "grass_flower_hex": "#f6d885",
    "grass_leaf_hex": "#9ecb75",
    "path_base_hex": "#a78d61",
    "path_highlight_hex": "#ccb487",
    "path_shadow_hex": "#6f5739",
    "courtyard_base_hex": "#8e8163",
    "courtyard_highlight_hex": "#bca883",
    "courtyard_shadow_hex": "#5a4733",
    "edge_band_tiles": 1,
    "doorstep_length_tiles": 3,
    "courtyard_radius_tiles": 2,
    "flower_density": 0.16,
    "shrub_density": 0.08,
    "pebble_density": 0.12,
}


_TEXTURE_CACHE: dict[str, Image.Image] = {}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _hex_to_rgb(color_hex: str) -> tuple[int, int, int]:
    color = color_hex.strip()
    if not color.startswith("#") or len(color) != 7:
        raise ValueError(f"Expected #RRGGBB color, got: {color_hex}")
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _stable_noise(tile_x: int, tile_y: int, *, seed: int = 0) -> float:
    value = (tile_x * 928371 + tile_y * 364479 + seed * 811) % 9973
    return value / 9973.0


def _mix(color_a: str, color_b: str, weight: float) -> tuple[int, int, int]:
    weight = max(0.0, min(1.0, weight))
    red_a, green_a, blue_a = _hex_to_rgb(color_a)
    red_b, green_b, blue_b = _hex_to_rgb(color_b)
    return (
        round(red_a + (red_b - red_a) * weight),
        round(green_a + (green_b - green_a) * weight),
        round(blue_a + (blue_b - blue_a) * weight),
    )


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _tile_image(target_im: Image.Image, texture_im: Image.Image, box: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = box
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return
    tw, th = texture_im.size
    tiled = Image.new("RGBA", (width, height))
    for x in range(0, width, tw):
        for y in range(0, height, th):
            tiled.paste(texture_im, (x, y))
    target_im.paste(tiled, (left, top), tiled)


def highlight_color(color_hex: str) -> str:
    red = int(color_hex[1:3], 16)
    green = int(color_hex[3:5], 16)
    blue = int(color_hex[5:7], 16)
    red = min(255, red + 24)
    green = min(255, green + 24)
    blue = min(255, blue + 24)
    return f"#{red:02x}{green:02x}{blue:02x}"


def _tile_box(tile_x: int, tile_y: int, *, tile_px: int, margin_px: int) -> tuple[int, int, int, int]:
    left = margin_px + tile_x * tile_px
    top = margin_px + tile_y * tile_px
    return left, top, left + tile_px, top + tile_px


def _room_bounds(room: dict[str, Any], fallback_width: int, fallback_height: int) -> tuple[int, int, int, int]:
    footprint = room.get("footprint_tiles") or []
    if footprint:
        xs = [int(tile["x"]) for tile in footprint]
        ys = [int(tile["y"]) for tile in footprint]
        return min(xs), min(ys), max(xs), max(ys)
    x = int(room.get("x", 0))
    y = int(room.get("y", 0))
    width = int(room.get("width_tiles", fallback_width))
    height = int(room.get("height_tiles", fallback_height))
    return x, y, x + width - 1, y + height - 1


def _room_tiles(room: dict[str, Any], fallback_width: int, fallback_height: int) -> list[tuple[int, int]]:
    footprint = room.get("footprint_tiles") or []
    if footprint:
        return sorted({(int(tile["x"]), int(tile["y"])) for tile in footprint})
    x, y, max_x, max_y = _room_bounds(room, fallback_width, fallback_height)
    return [(tile_x, tile_y) for tile_y in range(y, max_y + 1) for tile_x in range(x, max_x + 1)]


def _doorway_exit_direction(
    doorway_tile: tuple[int, int],
    *,
    room_tiles: set[tuple[int, int]],
    width: int,
    height: int,
) -> tuple[int, int]:
    tile_x, tile_y = doorway_tile
    candidates = [(0, -1), (0, 1), (-1, 0), (1, 0)]
    for dx, dy in candidates:
        nx = tile_x + dx
        ny = tile_y + dy
        if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in room_tiles:
            return dx, dy
    return 0, 1

