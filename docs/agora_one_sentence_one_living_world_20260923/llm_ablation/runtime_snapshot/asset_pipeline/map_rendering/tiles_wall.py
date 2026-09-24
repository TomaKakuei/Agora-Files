from __future__ import annotations

from typing import Any
from PIL import Image, ImageDraw
from .constants import (
    _mix,
    _rgb_to_hex,
    _tile_box,
    _tile_image,
    _room_tiles,
    _doorway_exit_direction,
)
from .tiles_floor import _get_pattern_texture


def _draw_maybe_tiled_rect(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    *,
    fill_color: str,
    outline_color: str,
    width: int,
    trim: str,
    tile_px: int,
    room_visual: dict[str, Any] | None = None,
) -> None:
    left, top, right, bottom = rect
    if right <= left or bottom <= top:
        return

    if trim == "clean_trim":
        # Draw a sleek modern glass showcase counter
        glass_fill = (205, 235, 245, 190)  # semi-translucent glass blue/cyan
        draw.rectangle(rect, fill=glass_fill)
        draw.rectangle(rect, outline=outline_color, width=1)
        # Glare highlight line
        draw.line((left + 2, top + 2, right - 2, bottom - 2), fill=(255, 255, 255, 150), width=1)
        
        if room_visual and room_visual.get("showcase_shelf", False):
            cx = (left + right) // 2
            cy = (top + bottom) // 2
            if bottom - top > 6:
                # Draw the showcase shelf line
                draw.line((left + 2, cy, right - 2, cy), fill=outline_color, width=1)
                # Draw tiny oval spectacles using custom colors
                colors = room_visual.get("showcase_item_colors", [])
                if not colors:
                    colors = ["#ca6c3a", "#7fb8a3"]
                if len(colors) >= 1:
                    draw.ellipse((cx - 4, cy - 3, cx - 1, cy - 1), fill=colors[0])
                if len(colors) >= 2:
                    draw.ellipse((cx + 1, cy - 3, cx + 4, cy - 1), fill=colors[1])
        return

    underlying_image = getattr(draw, "image", None)
    wall_pattern = None
    if trim == "red_pillar_trim":
        wall_pattern = "red_pillar_wall"
    elif trim == "bamboo_trim":
        wall_pattern = "bamboo_wall"
    elif trim == "yard_trim":
        wall_pattern = "courtyard_brick_wall"

    if underlying_image is not None and wall_pattern is not None:
        texture = _get_pattern_texture(wall_pattern, fill_color, tile_px)
        _tile_image(underlying_image, texture, rect)
        draw.rectangle(rect, outline=outline_color, width=width)
    else:
        draw.rectangle(rect, fill=fill_color, outline=outline_color, width=width)


def _wall_style(trim: str, *, base: str, highlight: str, outline: str) -> dict[str, str]:
    styles = {
        "wood_beam": {
            "face": "#8e6d4f",
            "beam": "#5a3d29",
            "cap": "#dbc39b",
            "door": "#7a5335",
            "threshold": "#c7b38d",
        },
        "notice_trim": {
            "face": "#d4bf8e",
            "beam": "#7b5921",
            "cap": "#f6e7b8",
            "door": "#9f7a43",
            "threshold": "#ead5aa",
        },
        "tavern_trim": {
            "face": "#8f613f",
            "beam": "#51301f",
            "cap": "#d7b084",
            "door": "#6d4027",
            "threshold": "#c59a66",
        },
        "storage_trim": {
            "face": "#8b745d",
            "beam": "#503a29",
            "cap": "#d4c0a4",
            "door": "#6c533d",
            "threshold": "#baa489",
        },
        "forge_trim": {
            "face": "#67524c",
            "beam": "#321d18",
            "cap": "#cfa37a",
            "door": "#57413a",
            "threshold": "#8c725f",
        },
        "clean_trim": {
            "face": "#c9e7df",
            "beam": "#4f8176",
            "cap": "#eefaf5",
            "door": "#84b4aa",
            "threshold": "#d8f0ea",
        },
        "yard_trim": {
            "face": "#8a7a5d",
            "beam": "#4b5d3d",
            "cap": "#d6cda9",
            "door": "#7a6a4f",
            "threshold": "#b7b08d",
        },
        "library_trim": {
            "face": "#6b4f45",
            "beam": "#38231e",
            "cap": "#d9bf9e",
            "door": "#52372f",
            "threshold": "#a6846b",
        },
        "war_trim": {
            "face": "#5c6780",
            "beam": "#243449",
            "cap": "#d8e2f3",
            "door": "#3e4d62",
            "threshold": "#8ea3be",
        },
        "dorm_trim": {
            "face": "#8e7d68",
            "beam": "#4d4336",
            "cap": "#e3d2bc",
            "door": "#72614c",
            "threshold": "#b7a48d",
        },
        "red_pillar_trim": {
            "face": "#b22222",
            "beam": "#8b0000",
            "cap": "#ffd700",
            "door": "#800000",
            "threshold": "#daa520",
        },
        "bamboo_trim": {
            "face": "#6b8e23",
            "beam": "#556b2f",
            "cap": "#9acd32",
            "door": "#8fbc8f",
            "threshold": "#adff2f",
        },
    }
    style = styles.get(trim, {})
    return {
        "face": str(style.get("face", _rgb_to_hex(_mix(base, outline, 0.28)))),
        "beam": str(style.get("beam", outline)),
        "cap": str(style.get("cap", highlight)),
        "door": str(style.get("door", _rgb_to_hex(_mix(base, outline, 0.45)))),
        "threshold": str(style.get("threshold", _rgb_to_hex(_mix(highlight, "#ffffff", 0.1)))),
    }


def _room_door_sides(room: dict[str, Any], *, room_tile_set: set[tuple[int, int]], width: int, height: int) -> dict[tuple[int, int], set[str]]:
    sides: dict[tuple[int, int], set[str]] = {}
    side_name = {
        (0, -1): "north",
        (0, 1): "south",
        (-1, 0): "west",
        (1, 0): "east",
    }
    for doorway in room.get("doorways", []):
        pos = doorway.get("position", {})
        tile = (int(pos.get("x", 0)), int(pos.get("y", 0)))
        direction = _doorway_exit_direction(tile, room_tiles=room_tile_set, width=width, height=height)
        name = side_name.get(direction)
        if name:
            sides.setdefault(tile, set()).add(name)
    return sides


def _draw_wall_segment(
    draw: ImageDraw.ImageDraw,
    tile_box: tuple[int, int, int, int],
    *,
    side: str,
    style: dict[str, str],
    tile_px: int,
    trim: str = "wood_beam",
    room_visual: dict[str, Any] | None = None,
) -> None:
    left, top, right, bottom = tile_box
    thickness = max(6, tile_px // 4)
    beam = style["beam"]
    face = style["face"]
    cap = style["cap"]
    if side == "north":
        wall_box = (left + 1, top + 1, right - 1, top + thickness)
        _draw_maybe_tiled_rect(draw, wall_box, fill_color=face, outline_color=beam, width=1, trim=trim, tile_px=tile_px, room_visual=room_visual)
        draw.line((left + 3, top + thickness - 2, right - 3, top + thickness - 2), fill=beam, width=2)
        draw.line((left + 3, top + 3, right - 3, top + 3), fill=cap, width=1)
    elif side == "south":
        wall_box = (left + 1, bottom - thickness, right - 1, bottom - 1)
        _draw_maybe_tiled_rect(draw, wall_box, fill_color=face, outline_color=beam, width=1, trim=trim, tile_px=tile_px, room_visual=room_visual)
        draw.line((left + 3, bottom - thickness + 2, right - 3, bottom - thickness + 2), fill=cap, width=1)
        draw.line((left + 3, bottom - 3, right - 3, bottom - 3), fill=beam, width=2)
    elif side == "west":
        wall_box = (left + 1, top + 1, left + thickness, bottom - 1)
        _draw_maybe_tiled_rect(draw, wall_box, fill_color=face, outline_color=beam, width=1, trim=trim, tile_px=tile_px, room_visual=room_visual)
        draw.line((left + thickness - 2, top + 3, left + thickness - 2, bottom - 3), fill=beam, width=2)
        draw.line((left + 3, top + 3, left + 3, bottom - 3), fill=cap, width=1)
    elif side == "east":
        wall_box = (right - thickness, top + 1, right - 1, bottom - 1)
        _draw_maybe_tiled_rect(draw, wall_box, fill_color=face, outline_color=beam, width=1, trim=trim, tile_px=tile_px, room_visual=room_visual)
        draw.line((right - thickness + 2, top + 3, right - thickness + 2, bottom - 3), fill=cap, width=1)
        draw.line((right - 3, top + 3, right - 3, bottom - 3), fill=beam, width=2)


def _draw_doorway(
    draw: ImageDraw.ImageDraw,
    tile_box: tuple[int, int, int, int],
    *,
    side: str,
    style: dict[str, str],
    tile_px: int,
    trim: str = "wood_beam",
    room_visual: dict[str, Any] | None = None,
) -> None:
    left, top, right, bottom = tile_box
    thickness = max(6, tile_px // 4)
    post = max(4, tile_px // 7)
    beam = style["beam"]
    face = style["face"]
    cap = style["cap"]
    door = style["door"]
    threshold = style["threshold"]
    if side in {"north", "south"}:
        door_width = max(10, tile_px - post * 2 - 8)
        door_left = left + (tile_px - door_width) // 2
        door_right = door_left + door_width
        if side == "north":
            _draw_maybe_tiled_rect(draw, (left + 1, top + 1, door_left, top + thickness), fill_color=face, outline_color=beam, width=1, trim=trim, tile_px=tile_px, room_visual=room_visual)
            _draw_maybe_tiled_rect(draw, (door_right, top + 1, right - 1, top + thickness), fill_color=face, outline_color=beam, width=1, trim=trim, tile_px=tile_px, room_visual=room_visual)
            draw.rectangle((door_left + 1, top + 3, door_right - 1, top + thickness + 7), fill=door, outline=beam, width=1)
            draw.line((door_left + 3, top + 5, door_right - 3, top + 5), fill=cap, width=1)
            draw.rectangle((door_left + 2, top + thickness + 3, door_right - 2, top + thickness + 6), fill=threshold, outline=beam, width=1)
            draw.ellipse((door_right - 7, top + thickness // 2, door_right - 4, top + thickness // 2 + 3), fill="#d9c36f")
        else:
            _draw_maybe_tiled_rect(draw, (left + 1, bottom - thickness, door_left, bottom - 1), fill_color=face, outline_color=beam, width=1, trim=trim, tile_px=tile_px, room_visual=room_visual)
            _draw_maybe_tiled_rect(draw, (door_right, bottom - thickness, right - 1, bottom - 1), fill_color=face, outline_color=beam, width=1, trim=trim, tile_px=tile_px, room_visual=room_visual)
            draw.rectangle((door_left + 1, bottom - thickness - 7, door_right - 1, bottom - 3), fill=door, outline=beam, width=1)
            draw.line((door_left + 3, bottom - thickness - 5, door_right - 3, bottom - thickness - 5), fill=cap, width=1)
            draw.rectangle((door_left + 2, bottom - thickness - 6, door_right - 2, bottom - thickness - 3), fill=threshold, outline=beam, width=1)
            draw.ellipse((door_right - 7, bottom - thickness // 2 - 3, door_right - 4, bottom - thickness // 2), fill="#d9c36f")
    else:
        door_height = max(10, tile_px - post * 2 - 8)
        door_top = top + (tile_px - door_height) // 2
        door_bottom = door_top + door_height
        if side == "west":
            _draw_maybe_tiled_rect(draw, (left + 1, top + 1, left + thickness, door_top), fill_color=face, outline_color=beam, width=1, trim=trim, tile_px=tile_px, room_visual=room_visual)
            _draw_maybe_tiled_rect(draw, (left + 1, door_bottom, left + thickness, bottom - 1), fill_color=face, outline_color=beam, width=1, trim=trim, tile_px=tile_px, room_visual=room_visual)
            draw.rectangle((left + 3, door_top + 1, left + thickness + 7, door_bottom - 1), fill=door, outline=beam, width=1)
            draw.line((left + 5, door_top + 3, left + 5, door_bottom - 3), fill=cap, width=1)
            draw.rectangle((left + thickness + 3, door_top + 2, left + thickness + 6, door_bottom - 2), fill=threshold, outline=beam, width=1)
            draw.ellipse((left + thickness // 2, door_bottom - 7, left + thickness // 2 + 3, door_bottom - 4), fill="#d9c36f")
        else:
            _draw_maybe_tiled_rect(draw, (right - thickness, top + 1, right - 1, door_top), fill_color=face, outline_color=beam, width=1, trim=trim, tile_px=tile_px, room_visual=room_visual)
            _draw_maybe_tiled_rect(draw, (right - thickness, door_bottom, right - 1, bottom - 1), fill_color=face, outline_color=beam, width=1, trim=trim, tile_px=tile_px, room_visual=room_visual)
            draw.rectangle((right - thickness - 7, door_top + 1, right - 3, door_bottom - 1), fill=door, outline=beam, width=1)
            draw.line((right - 5, door_top + 3, right - 5, door_bottom - 3), fill=cap, width=1)
            draw.rectangle((right - thickness - 6, door_top + 2, right - thickness - 3, door_bottom - 2), fill=threshold, outline=beam, width=1)
            draw.ellipse((right - thickness // 2 - 3, door_bottom - 7, right - thickness // 2, door_bottom - 4), fill="#d9c36f")


def _draw_room_boundaries(
    draw: ImageDraw.ImageDraw,
    room: dict[str, Any],
    *,
    room_tile_set: set[tuple[int, int]],
    wall_spec: dict[str, Any],
    tile_px: int,
    margin_px: int,
    width: int,
    height: int,
    base: str,
    highlight: str,
    outline: str,
) -> None:
    trim = str(wall_spec.get("trim", "wood_beam"))
    style = _wall_style(trim, base=base, highlight=highlight, outline=outline)
    doorway_sides = _room_door_sides(room, room_tile_set=room_tile_set, width=width, height=height)
    room_visual = room.get("visual", {})
    neighbor_for_side = {
        "north": (0, -1),
        "south": (0, 1),
        "west": (-1, 0),
        "east": (1, 0),
    }
    for tile_x, tile_y in room_tile_set:
        tile_box = _tile_box(tile_x, tile_y, tile_px=tile_px, margin_px=margin_px)
        for side, (dx, dy) in neighbor_for_side.items():
            neighbor = (tile_x + dx, tile_y + dy)
            if neighbor in room_tile_set:
                continue
            if side in doorway_sides.get((tile_x, tile_y), set()):
                _draw_doorway(draw, tile_box, side=side, style=style, tile_px=tile_px, trim=trim, room_visual=room_visual)
            else:
                _draw_wall_segment(draw, tile_box, side=side, style=style, tile_px=tile_px, trim=trim, room_visual=room_visual)
