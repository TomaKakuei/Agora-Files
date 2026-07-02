from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from .constants import (
    PALETTE,
    DEFAULT_COMPONENT_LIBRARY,
    DEFAULT_WORLD_TERRAIN,
    _hex_to_rgb,
    _stable_noise,
    _mix,
    _tile_image,
    highlight_color,
    _tile_box,
    _room_bounds,
    _room_tiles,
    _doorway_exit_direction,
)
from .tiles_floor import _draw_floor_pattern
from .tiles_wall import _draw_room_boundaries


def _merge_component_library(component_library: dict[str, Any] | None) -> dict[str, Any]:
    merged = json.loads(json.dumps(DEFAULT_COMPONENT_LIBRARY))
    if not isinstance(component_library, dict):
        return merged
    for section, value in component_library.items():
        if isinstance(value, dict):
            merged.setdefault(section, {})
            for item_key, item_value in value.items():
                if isinstance(item_value, dict) and isinstance(merged[section].get(item_key), dict):
                    merged[section][item_key].update(item_value)
                else:
                    merged[section][item_key] = item_value
    return merged


def _merge_world_terrain(world_terrain: dict[str, Any] | None) -> dict[str, Any]:
    merged = json.loads(json.dumps(DEFAULT_WORLD_TERRAIN))
    if not isinstance(world_terrain, dict):
        return merged
    for key, value in world_terrain.items():
        merged[key] = value
    return merged


def _collect_room_tile_set(map_grid: dict[str, Any], *, fallback_width: int, fallback_height: int) -> set[tuple[int, int]]:
    tiles: set[tuple[int, int]] = set()
    for room in map_grid.get("rooms", []):
        tiles.update(_room_tiles(room, fallback_width, fallback_height))
    return tiles


def _find_non_room_hub(
    *,
    room_tiles: set[tuple[int, int]],
    width: int,
    height: int,
    anchors: list[tuple[int, int]],
) -> tuple[int, int]:
    if anchors:
        guess_x = round(sum(tile_x for tile_x, _ in anchors) / len(anchors))
        guess_y = round(sum(tile_y for _, tile_y in anchors) / len(anchors))
    else:
        guess_x = width // 2
        guess_y = height // 2
    for radius in range(max(width, height)):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                tile_x = guess_x + dx
                tile_y = guess_y + dy
                if not (0 <= tile_x < width and 0 <= tile_y < height):
                    continue
                if (tile_x, tile_y) not in room_tiles:
                    return tile_x, tile_y
    return width // 2, height // 2


def _walk_axis_path(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    room_tiles: set[tuple[int, int]],
    width: int,
    height: int,
) -> set[tuple[int, int]]:
    current_x, current_y = start
    target_x, target_y = end
    path_tiles: set[tuple[int, int]] = set()
    max_steps = width * height * 2
    for _ in range(max_steps):
        if (current_x, current_y) == (target_x, target_y):
            break
        moved = False
        primary_axes = [("x", target_x - current_x), ("y", target_y - current_y)]
        primary_axes.sort(key=lambda entry: abs(entry[1]), reverse=True)
        for axis, delta in primary_axes:
            if delta == 0:
                continue
            next_x = current_x + (1 if axis == "x" and delta > 0 else -1 if axis == "x" else 0)
            next_y = current_y + (1 if axis == "y" and delta > 0 else -1 if axis == "y" else 0)
            if not (0 <= next_x < width and 0 <= next_y < height):
                continue
            if (next_x, next_y) in room_tiles:
                continue
            current_x, current_y = next_x, next_y
            path_tiles.add((current_x, current_y))
            moved = True
            break
        if not moved:
            break
    return path_tiles


def _compute_outdoor_layout(
    *,
    map_grid: dict[str, Any],
    width: int,
    height: int,
    fallback_width: int,
    fallback_height: int,
    world_terrain: dict[str, Any],
) -> dict[str, set[tuple[int, int]] | tuple[int, int]]:
    room_tiles = _collect_room_tile_set(map_grid, fallback_width=fallback_width, fallback_height=fallback_height)
    edge_tiles: set[tuple[int, int]] = set()
    edge_band_tiles = max(1, int(world_terrain.get("edge_band_tiles", 1)))
    for tile_x, tile_y in room_tiles:
        for dy in range(-edge_band_tiles, edge_band_tiles + 1):
            for dx in range(-edge_band_tiles, edge_band_tiles + 1):
                if abs(dx) + abs(dy) == 0 or abs(dx) + abs(dy) > edge_band_tiles:
                    continue
                nx = tile_x + dx
                ny = tile_y + dy
                if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in room_tiles:
                    edge_tiles.add((nx, ny))

    door_tiles: set[tuple[int, int]] = set()
    path_tiles: set[tuple[int, int]] = set()
    anchors: list[tuple[int, int]] = []
    doorstep_length = max(1, int(world_terrain.get("doorstep_length_tiles", 3)))
    for room in map_grid.get("rooms", []):
        for doorway in room.get("doorways", []):
            pos = doorway.get("position", {})
            doorway_tile = (int(pos.get("x", 0)), int(pos.get("y", 0)))
            door_tiles.add(doorway_tile)
            step_dx, step_dy = _doorway_exit_direction(doorway_tile, room_tiles=room_tiles, width=width, height=height)
            current_x, current_y = doorway_tile
            last_outdoor = doorway_tile
            for _ in range(doorstep_length):
                current_x += step_dx
                current_y += step_dy
                if not (0 <= current_x < width and 0 <= current_y < height):
                    break
                if (current_x, current_y) in room_tiles:
                    break
                path_tiles.add((current_x, current_y))
                last_outdoor = (current_x, current_y)
            anchors.append(last_outdoor)

    hub_tile = _find_non_room_hub(room_tiles=room_tiles, width=width, height=height, anchors=anchors)
    courtyard_tiles: set[tuple[int, int]] = set()
    courtyard_radius = max(1, int(world_terrain.get("courtyard_radius_tiles", 2)))
    for tile_y in range(hub_tile[1] - courtyard_radius, hub_tile[1] + courtyard_radius + 1):
        for tile_x in range(hub_tile[0] - courtyard_radius, hub_tile[0] + courtyard_radius + 1):
            if not (0 <= tile_x < width and 0 <= tile_y < height):
                continue
            if (tile_x, tile_y) in room_tiles:
                continue
            if abs(tile_x - hub_tile[0]) + abs(tile_y - hub_tile[1]) <= courtyard_radius + 1:
                courtyard_tiles.add((tile_x, tile_y))

    for anchor in anchors:
        path_tiles.update(_walk_axis_path(anchor, hub_tile, room_tiles=room_tiles, width=width, height=height))

    entry_anchor = (width // 2, height - 1)
    if entry_anchor not in room_tiles:
        path_tiles.update(_walk_axis_path(entry_anchor, hub_tile, room_tiles=room_tiles, width=width, height=height))
        anchors.append(entry_anchor)
    path_tiles.difference_update(courtyard_tiles)

    return {
        "room_tiles": room_tiles,
        "edge_tiles": edge_tiles,
        "door_tiles": door_tiles,
        "path_tiles": path_tiles,
        "courtyard_tiles": courtyard_tiles,
        "hub_tile": hub_tile,
    }


def _draw_grass_tile(
    draw: ImageDraw.ImageDraw,
    tile_box: tuple[int, int, int, int],
    *,
    tile_x: int,
    tile_y: int,
    world_terrain: dict[str, Any],
) -> None:
    base = world_terrain["grass_base_hex"]
    alt = world_terrain["grass_alt_hex"]
    shadow = world_terrain["grass_shadow_hex"]
    leaf = world_terrain["grass_leaf_hex"]
    flower = world_terrain["grass_flower_hex"]
    noise = _stable_noise(tile_x, tile_y)
    fill = _mix(base, alt, 0.15 + 0.7 * noise)
    left, top, right, bottom = tile_box
    draw.rectangle(tile_box, fill=fill)
    draw.line((left, top, right, top), fill=_mix(alt, "#ffffff", 0.18), width=1)
    draw.line((left, bottom, right, bottom), fill=_mix(shadow, "#000000", 0.15), width=1)
    draw.line((left + 5, bottom - 9, left + 8, bottom - 14), fill=leaf, width=2)
    draw.line((left + 14, bottom - 6, left + 18, bottom - 13), fill=leaf, width=2)
    draw.line((right - 9, bottom - 8, right - 6, bottom - 14), fill=shadow, width=2)
    if noise < float(world_terrain.get("flower_density", 0.16)):
        draw.ellipse((left + 9, top + 8, left + 13, top + 12), fill=flower)
        draw.ellipse((left + 12, top + 10, left + 16, top + 14), fill="#ffffff")
    elif noise < float(world_terrain.get("flower_density", 0.16)) + float(world_terrain.get("shrub_density", 0.08)):
        draw.rounded_rectangle((left + 7, top + 10, right - 9, bottom - 9), radius=4, fill=_mix(shadow, base, 0.35))
    elif noise > 1.0 - float(world_terrain.get("pebble_density", 0.12)):
        draw.ellipse((left + 7, top + 11, left + 11, top + 15), fill="#d4cfbd")
        draw.ellipse((left + 15, top + 14, left + 18, top + 17), fill="#bab39f")


def _draw_path_tile(
    draw: ImageDraw.ImageDraw,
    tile_box: tuple[int, int, int, int],
    *,
    tile_x: int,
    tile_y: int,
    world_terrain: dict[str, Any],
    edge_blend: bool = False,
) -> None:
    base_hex = world_terrain["path_base_hex"]
    highlight_hex = world_terrain["path_highlight_hex"]
    shadow_hex = world_terrain["path_shadow_hex"]
    left, top, right, bottom = tile_box
    blend = 0.24 + _stable_noise(tile_x, tile_y, seed=11) * (0.22 if edge_blend else 0.12)
    draw.rectangle(tile_box, fill=_mix(base_hex, highlight_hex, blend))
    inset = 2 if edge_blend else 1
    draw.rounded_rectangle((left + inset, top + inset, right - inset, bottom - inset), radius=5, outline=_mix(shadow_hex, "#000000", 0.12), width=1)
    draw.line((left + 5, top + 6, right - 6, top + 4), fill=_mix(highlight_hex, "#ffffff", 0.14), width=1)
    draw.line((left + 6, bottom - 5, right - 5, bottom - 4), fill=_mix(shadow_hex, "#000000", 0.16), width=1)
    if _stable_noise(tile_x, tile_y, seed=21) > 0.68:
        draw.ellipse((left + 10, top + 9, left + 14, top + 13), fill="#d7d2c0")
    if _stable_noise(tile_x, tile_y, seed=35) > 0.78:
        draw.ellipse((left + 18, top + 16, left + 21, top + 19), fill="#8d7b61")


def _draw_courtyard_tile(
    draw: ImageDraw.ImageDraw,
    tile_box: tuple[int, int, int, int],
    *,
    tile_x: int,
    tile_y: int,
    world_terrain: dict[str, Any],
) -> None:
    base_hex = world_terrain["courtyard_base_hex"]
    highlight_hex = world_terrain["courtyard_highlight_hex"]
    shadow_hex = world_terrain["courtyard_shadow_hex"]
    left, top, right, bottom = tile_box
    draw.rectangle(tile_box, fill=_mix(base_hex, highlight_hex, 0.18 + 0.18 * _stable_noise(tile_x, tile_y, seed=7)))
    inset = 3
    draw.rounded_rectangle((left + inset, top + inset, right - inset, bottom - inset), radius=4, fill=_mix(base_hex, highlight_hex, 0.25), outline=shadow_hex, width=1)
    draw.line((left + 6, top + 6, right - 6, bottom - 6), fill=_mix(highlight_hex, "#ffffff", 0.1), width=1)
    draw.line((left + 6, bottom - 6, right - 6, top + 6), fill=_mix(shadow_hex, "#000000", 0.06), width=1)


def _draw_global_ground(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    *,
    canvas_w: int,
    tile_px: int,
    margin_px: int,
    outdoor_layout: dict[str, set[tuple[int, int]] | tuple[int, int]],
    world_terrain: dict[str, Any],
) -> None:
    room_tiles = set(outdoor_layout.get("room_tiles", set()))
    edge_tiles = set(outdoor_layout.get("edge_tiles", set()))
    path_tiles = set(outdoor_layout.get("path_tiles", set()))
    courtyard_tiles = set(outdoor_layout.get("courtyard_tiles", set()))
    for y in range(height):
        for x in range(width):
            tile_box = _tile_box(x, y, tile_px=tile_px, margin_px=margin_px)
            tile = (x, y)
            if tile in courtyard_tiles:
                _draw_courtyard_tile(draw, tile_box, tile_x=x, tile_y=y, world_terrain=world_terrain)
            elif tile in path_tiles:
                _draw_path_tile(draw, tile_box, tile_x=x, tile_y=y, world_terrain=world_terrain)
            elif tile in edge_tiles:
                _draw_path_tile(draw, tile_box, tile_x=x, tile_y=y, world_terrain=world_terrain, edge_blend=True)
            else:
                _draw_grass_tile(draw, tile_box, tile_x=x, tile_y=y, world_terrain=world_terrain)
            if tile not in room_tiles and tile not in courtyard_tiles:
                left, top, right, bottom = tile_box
                draw.line((left, top, right, top), fill=(255, 255, 255, 18), width=1)
                draw.line((left, top, left, bottom), fill=(255, 255, 255, 14), width=1)
                draw.line((right, top, right, bottom), fill=(46, 34, 20, 18), width=1)
                draw.line((left, bottom, right, bottom), fill=(46, 34, 20, 20), width=1)


def _anchor_position(
    anchor: str,
    *,
    left: int,
    top: int,
    right: int,
    bottom: int,
    width: int,
    height: int,
    tile_px: int,
) -> tuple[int, int, int, int]:
    pad = max(6, tile_px // 4)
    positions = {
        "north_west": (left + pad, top + pad),
        "north_mid": (((left + right - width) // 2), top + pad),
        "north_east": (right - width - pad, top + pad),
        "west_mid": (left + pad, ((top + bottom - height) // 2)),
        "center": (((left + right - width) // 2), ((top + bottom - height) // 2)),
        "east_mid": (right - width - pad, ((top + bottom - height) // 2)),
        "south_west": (left + pad, bottom - height - pad),
        "south_mid": (((left + right - width) // 2), bottom - height - pad),
        "south_east": (right - width - pad, bottom - height - pad),
    }
    anchor_left, anchor_top = positions.get(anchor, positions["center"])
    return anchor_left, anchor_top, anchor_left + width, anchor_top + height


def _alpha_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value >= 8 else 0)
    return mask.getbbox()


def _paste_component_icon(
    image: Image.Image,
    *,
    icon_path: Path,
    box: tuple[int, int, int, int],
) -> bool:
    if not icon_path.is_file():
        return False
    icon = Image.open(icon_path).convert("RGBA")
    bbox = _alpha_bbox(icon)
    if bbox is not None:
        icon = icon.crop(bbox)
    width = max(1, box[2] - box[0])
    height = max(1, box[3] - box[1])
    fitted = ImageOps.contain(icon, (width, height), Image.Resampling.LANCZOS)
    paste_left = box[0] + max(0, (width - fitted.width) // 2)
    paste_top = box[1] + max(0, (height - fitted.height) // 2)
    image.paste(fitted, (paste_left, paste_top), fitted)
    return True


def _draw_component_preset(
    draw: ImageDraw.ImageDraw,
    *,
    render_name: str,
    box: tuple[int, int, int, int],
    color: str,
    accent: str,
) -> None:
    left, top, right, bottom = box
    cx = (left + right) // 2
    cy = (top + bottom) // 2
    if render_name in {"table_notice", "table_scroll", "table_map"}:
        draw.rounded_rectangle(box, radius=8, fill=accent, outline=color, width=2)
        if render_name == "table_notice":
            draw.rectangle((left + 7, top + 6, right - 7, bottom - 8), fill="#fff0c7", outline=color, width=1)
        elif render_name == "table_scroll":
            draw.ellipse((left + 7, cy - 6, left + 17, cy + 6), fill=color)
            draw.ellipse((right - 17, cy - 6, right - 7, cy + 6), fill=color)
        else:
            draw.rectangle((left + 6, top + 6, right - 6, bottom - 6), outline=color, width=2)
            draw.line((left + 8, bottom - 8, right - 8, top + 8), fill=color, width=2)
    elif render_name == "round_table":
        draw.ellipse(box, fill=accent, outline=color, width=3)
        draw.ellipse((left + 8, top + 8, right - 8, bottom - 8), outline=color, width=2)
    elif render_name == "crate_stack":
        draw.rectangle((left + 2, top + 8, right - 8, bottom - 2), fill=accent, outline=color, width=2)
        draw.rectangle((left + 10, top + 2, right - 2, bottom - 10), fill=highlight_color(accent), outline=color, width=2)
    elif render_name == "coil":
        draw.ellipse(box, outline=color, width=3)
        draw.ellipse((left + 8, top + 8, right - 8, bottom - 8), outline=accent, width=2)
    elif render_name == "furnace":
        draw.rounded_rectangle(box, radius=8, fill=color, outline=accent, width=2)
        flame = [(cx, top + 6), (right - 8, cy + 2), (cx, bottom - 6), (left + 8, cy + 2)]
        draw.polygon(flame, fill=accent)
    elif render_name == "anvil":
        draw.rectangle((left + 6, cy - 4, right - 6, cy + 6), fill=accent, outline=color, width=2)
        draw.polygon([(left + 6, cy - 8), (right - 6, top + 8), (right - 4, cy - 2), (left + 10, cy)], fill=color)
    elif render_name in {"bed", "bunks"}:
        draw.rounded_rectangle(box, radius=6, fill=accent, outline=color, width=2)
        draw.rectangle((left + 5, top + 5, left + 16, top + 16), fill=color)
        if render_name == "bunks":
            draw.line((left + 2, cy, right - 2, cy), fill=color, width=2)
    elif render_name == "dummy":
        draw.line((cx, top + 6, cx, bottom - 6), fill=color, width=3)
        draw.ellipse((cx - 6, top + 4, cx + 6, top + 16), fill=accent, outline=color, width=2)
        draw.line((left + 8, cy, right - 8, cy), fill=color, width=3)
    elif render_name == "rack":
        draw.line((left + 6, bottom - 4, right - 6, bottom - 4), fill=color, width=3)
        for offset in (10, 18, 26):
            draw.line((left + offset, top + 4, left + offset, bottom - 4), fill=accent, width=2)
    elif render_name == "board":
        draw.rectangle(box, fill=accent, outline=color, width=2)
        for offset in range(top + 8, bottom - 4, 8):
            draw.line((left + 6, offset, right - 6, offset), fill=color, width=1)
    elif render_name == "scroll_stack":
        draw.rounded_rectangle(box, radius=10, fill=accent, outline=color, width=2)
        draw.ellipse((left + 3, cy - 6, left + 13, cy + 6), fill=color)
        draw.ellipse((right - 13, cy - 6, right - 3, cy + 6), fill=color)
    elif render_name == "shelf":
        draw.rectangle(box, fill=accent, outline=color, width=2)
        draw.line((left + 4, cy - 5, right - 4, cy - 5), fill=color, width=2)
        draw.line((left + 4, cy + 5, right - 4, cy + 5), fill=color, width=2)
    elif render_name == "runes":
        draw.ellipse(box, outline=accent, width=3)
        draw.line((cx, top + 4, cx, bottom - 4), fill=color, width=2)
        draw.line((left + 4, cy, right - 4, cy), fill=color, width=2)
        draw.line((left + 7, top + 7, right - 7, bottom - 7), fill=accent, width=2)
    elif render_name == "map_stand":
        draw.rectangle(box, fill=accent, outline=color, width=2)
        draw.line((left + 6, top + 6, right - 6, bottom - 6), fill=color, width=2)
        draw.line((left + 6, bottom - 6, right - 6, top + 6), fill=color, width=2)
    elif render_name == "banner":
        draw.rectangle((cx - 3, top + 2, cx + 3, bottom - 2), fill=color)
        draw.polygon([(cx + 3, top + 6), (right - 2, top + 14), (cx + 3, top + 22)], fill=accent)
    elif render_name == "nightstand":
        draw.rounded_rectangle(box, radius=5, fill=accent, outline=color, width=2)
        draw.line((left + 5, cy, right - 5, cy), fill=color, width=2)
    elif render_name == "potion_red":
        draw.ellipse((left + 8, top + 9, right - 8, bottom - 4), fill="#c23d4f", outline=color, width=2)
        draw.rectangle((cx - 3, top + 4, cx + 3, top + 12), fill="#f6dfb8", outline=color, width=1)
    elif render_name == "map_scroll":
        draw.rounded_rectangle(box, radius=8, fill="#f3deb2", outline=color, width=2)
        draw.line((left + 6, top + 7, right - 6, bottom - 7), fill=color, width=2)
    elif render_name == "quest_notice":
        draw.rectangle(box, fill="#f4e4b8", outline=color, width=2)
        draw.line((left + 6, top + 10, right - 6, top + 10), fill=color, width=2)
        draw.line((left + 6, top + 18, right - 8, top + 18), fill=color, width=1)
    elif render_name == "toolkit":
        draw.rounded_rectangle(box, radius=6, fill="#7c8f9f", outline=color, width=2)
        draw.rectangle((left + 6, top + 8, right - 6, top + 14), fill="#d2c3a0", outline=color, width=1)
    elif render_name == "food_pack":
        draw.rounded_rectangle(box, radius=6, fill="#b88a52", outline=color, width=2)
        draw.line((left + 8, top + 6, right - 8, bottom - 6), fill="#e9d0a4", width=2)
    elif render_name == "travel_pack":
        draw.rounded_rectangle(box, radius=6, fill="#7d5b3a", outline=color, width=2)
        draw.rectangle((left + 5, top + 7, right - 5, bottom - 7), outline="#d6b07b", width=2)
        draw.line((left + 9, top + 5, left + 9, bottom - 5), fill="#d6b07b", width=2)
        draw.line((right - 9, top + 5, right - 9, bottom - 5), fill="#d6b07b", width=2)
    elif render_name == "herb_bundle":
        draw.ellipse((left + 6, top + 8, right - 6, bottom - 6), fill="#4f9c57", outline=color, width=2)
        draw.line((cx, top + 4, cx, bottom - 8), fill="#d9c28e", width=2)
        draw.line((left + 10, cy + 2, right - 10, cy - 3), fill="#5fc86a", width=2)
    elif render_name == "iron_ingot":
        draw.rounded_rectangle((left + 4, top + 10, right - 4, bottom - 6), radius=4, fill="#7d8793", outline=color, width=2)
        draw.line((left + 8, top + 14, right - 8, top + 14), fill="#bcc7d4", width=2)
    else:
        draw.ellipse(box, fill=accent, outline=color, width=2)


def render_component_icon(
    *,
    render_name: str,
    output_path: Path,
    icon_px: int = 96,
    base_color: str = "#5f4634",
    accent_color: str = "#f4d3a3",
) -> Path:
    image = Image.new("RGBA", (icon_px, icon_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    pad = max(8, icon_px // 12)
    _draw_component_preset(
        draw,
        render_name=render_name,
        box=(pad, pad, icon_px - pad, icon_px - pad),
        color=base_color,
        accent=accent_color,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def _component_box(
    component_spec: dict[str, Any],
    *,
    room_box: tuple[int, int, int, int],
    tile_px: int,
    anchor_override: str | None = None,
) -> tuple[int, int, int, int]:
    width_tiles = int(component_spec.get("size_tiles", {}).get("w", 1))
    height_tiles = int(component_spec.get("size_tiles", {}).get("h", 1))
    width = max(tile_px - 8, width_tiles * tile_px - 10)
    height = max(tile_px - 8, height_tiles * tile_px - 10)
    return _anchor_position(
        anchor_override or str(component_spec.get("anchor", "center")),
        left=room_box[0],
        top=room_box[1],
        right=room_box[2],
        bottom=room_box[3],
        width=width,
        height=height,
        tile_px=tile_px,
    )


def _room_component_placements(
    room: dict[str, Any],
    *,
    component_library: dict[str, Any],
    tile_px: int,
    room_box: tuple[int, int, int, int],
) -> list[tuple[str, dict[str, Any], tuple[int, int, int, int]]]:
    props = component_library.get("props", {})
    room_presets = component_library.get("room_layout_presets", {})
    archetype_presets = component_library.get("room_archetype_presets", {})
    placements: list[tuple[str, dict[str, Any], tuple[int, int, int, int]]] = []
    seen: set[tuple[str, str]] = set()
    for component_id in room.get("visual", {}).get("decor_tags", []):
        spec = props.get(component_id)
        if not isinstance(spec, dict):
            continue
        box = _component_box(spec, room_box=room_box, tile_px=tile_px)
        placements.append((component_id, spec, box))
        seen.add((component_id, spec.get("anchor", "center")))
    metadata = room.get("metadata", {}) if isinstance(room.get("metadata", {}), dict) else {}
    archetype = str(metadata.get("room_archetype", "")).strip()
    preset_entries: list[dict[str, Any]] = []
    if archetype and isinstance(archetype_presets.get(archetype), dict):
        preset_entries.extend(archetype_presets.get(archetype, {}).get("supplemental_props", []))
    room_preset = room_presets.get(room.get("room_id", ""), {})
    preset_entries.extend(room_preset.get("supplemental_props", []))
    for entry in preset_entries:
        component_id = str(entry.get("component_id", "")).strip()
        spec = props.get(component_id)
        if not isinstance(spec, dict):
            continue
        anchor = str(entry.get("anchor", spec.get("anchor", "center")))
        if (component_id, anchor) in seen:
            continue
        box = _component_box(spec, room_box=room_box, tile_px=tile_px, anchor_override=anchor)
        placements.append((component_id, spec, box))
    return placements


def render_map_asset(
    *,
    map_grid: dict[str, Any],
    output_path: Path,
    tile_px: int,
    margin_px: int,
    background_hex: str = "#efe1c4",
    component_library: dict[str, Any] | None = None,
    world_terrain: dict[str, Any] | None = None,
    room_loot: list[dict[str, Any]] | None = None,
    component_icons: dict[str, str] | None = None,
) -> Path:
    space = map_grid.get("space", map_grid) # Support both nested and flat structure
    width = int(space.get("width_tiles", space.get("grid_shape", {}).get("x", 100)))
    height = int(space.get("height_tiles", space.get("grid_shape", {}).get("y", 100)))
    margin_px = 0  # Force margin to 0 to maintain 32x32 per-tile contract with Phaser
    canvas_w = width * tile_px + margin_px * 2
    canvas_h = height * tile_px + margin_px * 2

    # Import the FLUX generator
    from .flux_floor_generator import generate_flux_floor
    # We will save floors to the same directory as the map
    floor_dir = output_path.parent / "floors"
    floor_dir.mkdir(parents=True, exist_ok=True)

    # Calculate terrain style
    outdoor_terrain_style = space.get("outdoor_terrain", "dirt").lower()
    custom_terrain = _merge_world_terrain(world_terrain)
    if outdoor_terrain_style == "concrete":
        custom_terrain.update({
            "grass_base_hex": "#8a8a8a",
            "grass_alt_hex": "#9c9c9c",
            "grass_shadow_hex": "#757575",
            "grass_leaf_hex": "#8a8a8a",
            "grass_flower_hex": "#9c9c9c",
            "path_base_hex": "#757575",
            "path_highlight_hex": "#8a8a8a",
            "path_shadow_hex": "#636363",
            "courtyard_base_hex": "#9c9c9c",
            "courtyard_highlight_hex": "#adadad",
            "courtyard_shadow_hex": "#8a8a8a"
        })
    else:  # dirt
        custom_terrain.update({
            "grass_base_hex": "#6b543a",
            "grass_alt_hex": "#7d6344",
            "grass_shadow_hex": "#594530",
            "grass_leaf_hex": "#7d6344",
            "grass_flower_hex": "#6b543a",
            "path_base_hex": "#594530",
            "path_highlight_hex": "#6b543a",
            "path_shadow_hex": "#473626",
            "courtyard_base_hex": "#7d6344",
            "courtyard_highlight_hex": "#8f724e",
            "courtyard_shadow_hex": "#6b543a"
        })

    image = Image.new("RGBA", (canvas_w, canvas_h), background_hex)
    draw = ImageDraw.Draw(image)

    # 0. Draw global outdoor terrain
    outdoor_layout = _compute_outdoor_layout(
        map_grid=map_grid,
        width=width,
        height=height,
        fallback_width=width,
        fallback_height=height,
        world_terrain=custom_terrain,
    )
    _draw_global_ground(
        draw,
        width=width,
        height=height,
        canvas_w=canvas_w,
        tile_px=tile_px,
        margin_px=margin_px,
        outdoor_layout=outdoor_layout,
        world_terrain=custom_terrain,
    )

    rooms = space.get("rooms", [])
    
    # 1. Paste FLUX floors and draw boundaries
    for room in rooms:
        # Paste FLUX floor
        floor_path_str = generate_flux_floor(room, floor_dir, tile_px=tile_px)
        floor_path = Path(floor_path_str)
        if floor_path.exists():
            floor_img = Image.open(floor_path).convert("RGBA")
            room_x = int(room.get("x_pos", room.get("x", 0)))
            room_y = int(room.get("y_pos", room.get("y", 0)))
            
            paste_x = margin_px + room_x * tile_px
            paste_y = margin_px + room_y * tile_px
            image.paste(floor_img, (paste_x, paste_y), floor_img)

        # Draw interior boundaries (DISABLED: User requested "内墙自由穿透" - free inner wall penetration)
        # room_tile_set = _room_tiles(room, fallback_width=width, fallback_height=height)
        # wall_spec = room.get("visual", {})
        # _draw_room_boundaries(
        #     draw,
        #     room,
        #     room_tile_set=room_tile_set,
        #     wall_spec=wall_spec,
        #     tile_px=tile_px,
        #     margin_px=margin_px,
        #     width=width,
        #     height=height,
        #     base="#8e6d4f",
        #     highlight="#dbc39b",
        #     outline="#333333",
        # )

    # 2. Draw grid overlay (subtle 1px grid, matched to tile_px)
    # We draw lines every tile_px pixels starting from margin_px
    grid_color = (0, 0, 0, 40) # subtle black
    for y in range(height + 1):
        line_y = margin_px + y * tile_px
        draw.line((margin_px, line_y, canvas_w - margin_px, line_y), fill=grid_color, width=1)
    for x in range(width + 1):
        line_x = margin_px + x * tile_px
        draw.line((line_x, margin_px, line_x, canvas_h - margin_px), fill=grid_color, width=1)

    # 3. Draw thin walls & outer walls
    thin_walls = space.get("thin_walls", [])
    outer_walls = space.get("outer_walls", [])
    
    # Simple color mapping for theme
    theme = str(space.get("wall_color_theme", "dark_brick")).lower()
    wall_color = "#333333"
    if "white" in theme or "plaster" in theme or "glass" in theme:
        wall_color = "#dddddd"
    elif "red" in theme:
        wall_color = "#8b0000"
    elif "wood" in theme:
        wall_color = "#5c4033"

    # Thin walls (passable) - 2px
    for wall in thin_walls:
        wx = margin_px + wall["x"] * tile_px
        wy = margin_px + wall["y"] * tile_px
        if wall["dir"] == "bottom":
            draw.line((wx, wy + tile_px, wx + tile_px, wy + tile_px), fill=wall_color, width=2)
        elif wall["dir"] == "right":
            draw.line((wx + tile_px, wy, wx + tile_px, wy + tile_px), fill=wall_color, width=2)

    # Thick outer boundary (impassable) - 4px black
    outer_color = "#000000"
    for wall in outer_walls:
        wx = margin_px + wall["x"] * tile_px
        wy = margin_px + wall["y"] * tile_px
        if wall["dir"] == "top":
            draw.line((wx, wy, wx + tile_px, wy), fill=outer_color, width=4)
        elif wall["dir"] == "bottom":
            draw.line((wx, wy + tile_px, wx + tile_px, wy + tile_px), fill=outer_color, width=4)
        elif wall["dir"] == "left":
            draw.line((wx, wy, wx, wy + tile_px), fill=outer_color, width=4)
        elif wall["dir"] == "right":
            draw.line((wx + tile_px, wy, wx + tile_px, wy + tile_px), fill=outer_color, width=4)

    # Note: No internal components/furniture are drawn as per constraints.
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output_path)
    return output_path
