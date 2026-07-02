from __future__ import annotations

from PIL import Image, ImageDraw
from .constants import (
    _TEXTURE_CACHE,
    _hex_to_rgb,
    _tile_image,
    _mix,
    _rgb_to_hex,
)


def _get_pattern_texture(pattern: str, base_color: str, tile_px: int) -> Image.Image:
    cache_key = f"{pattern}:{base_color}:{tile_px}"
    if cache_key in _TEXTURE_CACHE:
        return _TEXTURE_CACHE[cache_key]

    im = Image.new("RGBA", (tile_px, tile_px))
    draw = ImageDraw.Draw(im)
    
    if pattern == "red_brick":
        base_rgb = _hex_to_rgb(base_color)
        draw.rectangle((0, 0, tile_px, tile_px), fill=base_rgb)
        half = tile_px // 2
        grout_color = (186, 167, 144)
        draw.line((0, half - 1, tile_px, half - 1), fill=grout_color, width=1)
        draw.line((0, tile_px - 1, tile_px, tile_px - 1), fill=grout_color, width=1)
        draw.line((half - 1, 0, half - 1, half - 1), fill=grout_color, width=1)
        draw.line((0, half, 0, tile_px - 1), fill=grout_color, width=1)
        draw.line((tile_px - 1, half, tile_px - 1, tile_px - 1), fill=grout_color, width=1)
        hl_color = (214, 112, 96)
        sd_color = (90, 31, 24)
        draw.line((1, 1, half - 2, 1), fill=hl_color, width=1)
        draw.line((1, 1, 1, half - 2), fill=hl_color, width=1)
        draw.line((1, half - 2, half - 2, half - 2), fill=sd_color, width=1)
        draw.line((half - 2, 1, half - 2, half - 2), fill=sd_color, width=1)
        draw.line((half + 1, 1, tile_px - 2, 1), fill=hl_color, width=1)
        draw.line((half + 1, 1, half + 1, half - 2), fill=hl_color, width=1)
        draw.line((half + 1, half - 2, tile_px - 2, half - 2), fill=sd_color, width=1)
        draw.line((tile_px - 2, half + 1, tile_px - 2, half - 2), fill=sd_color, width=1)
        draw.line((1, half + 1, tile_px - 2, half + 1), fill=hl_color, width=1)
        draw.line((1, half + 1, 1, tile_px - 2), fill=hl_color, width=1)
        draw.line((1, tile_px - 2, tile_px - 2, tile_px - 2), fill=sd_color, width=1)
        draw.line((tile_px - 2, half + 1, tile_px - 2, half - 2), fill=sd_color, width=1)

    elif pattern == "jade_tile":
        draw.rectangle((0, 0, tile_px, tile_px), fill=(45, 122, 87))
        hl_green = (118, 212, 165)
        sd_green = (26, 77, 52)
        accent_gold = (218, 165, 32)
        half = tile_px // 2
        for offset_y in (0, half):
            draw.arc((0, offset_y - 2, half, offset_y + half - 2), start=180, end=360, fill=hl_green, width=2)
            draw.arc((0, offset_y, half, offset_y + half), start=180, end=360, fill=sd_green, width=2)
            draw.arc((half, offset_y - 2, tile_px, offset_y + half - 2), start=180, end=360, fill=hl_green, width=2)
            draw.arc((half, offset_y, tile_px, offset_y + half), start=180, end=360, fill=sd_green, width=2)
            draw.ellipse((half // 2 - 2, offset_y + half - 4, half // 2 + 2, offset_y + half), fill=accent_gold)
            draw.ellipse((half + half // 2 - 2, offset_y + half - 4, half + half // 2 + 2, offset_y + half), fill=accent_gold)

    elif pattern == "bamboo_planks":
        stalk_w = tile_px // 4
        hl_color = (230, 240, 180)
        sd_color = (82, 76, 43)
        for i in range(4):
            x_left = i * stalk_w
            x_right = (i + 1) * stalk_w
            for offset_x in range(stalk_w):
                factor = abs(offset_x - stalk_w // 2) / (stalk_w // 2)
                col = _mix("#c4cc81", "#808a40" if offset_x > stalk_w // 2 else "#e6efa6", factor)
                draw.line((x_left + offset_x, 0, x_left + offset_x, tile_px), fill=col, width=1)
            joint_y = (i * 7 + 11) % tile_px
            draw.line((x_left + 1, joint_y - 1, x_right - 1, joint_y - 1), fill=hl_color, width=1)
            draw.line((x_left + 1, joint_y, x_right - 1, joint_y), fill=sd_color, width=1)
            draw.line((x_left, 0, x_left, tile_px), fill=(60, 55, 30), width=1)

    elif pattern == "courtyard_brick_wall":
        draw.rectangle((0, 0, tile_px, tile_px), fill=(90, 97, 102))
        draw.ellipse((4, 6, 12, 10), fill=(76, 89, 67, 150))
        draw.ellipse((tile_px - 14, tile_px - 12, tile_px - 6, tile_px - 8), fill=(76, 89, 67, 150))
        grout = (46, 49, 51)
        hl = (147, 155, 163)
        half = tile_px // 2
        draw.line((0, half - 1, tile_px, half - 1), fill=grout, width=1)
        draw.line((0, tile_px - 1, tile_px, tile_px - 1), fill=grout, width=1)
        draw.line((half - 1, 0, half - 1, half - 1), fill=grout, width=1)
        draw.line((half // 2 - 1, half, half // 2 - 1, tile_px - 1), fill=grout, width=1)
        draw.line((half + half // 2 - 1, half, half + half // 2 - 1, tile_px - 1), fill=grout, width=1)
        for bx, by, bw, bh in [(1, 1, half - 2, half - 2), (half + 1, 1, half - 2, half - 2),
                               (1, half + 1, half // 2 - 2, half - 2), (half // 2 + 1, half + 1, half - 2, half - 2),
                               (half + half // 2 + 1, half + 1, half // 2 - 2, half - 2)]:
            draw.line((bx, by, bx + bw, by), fill=hl, width=1)
            draw.line((bx, by, bx, by + bh), fill=hl, width=1)
            draw.line((bx, by + bh, bx + bw, by + bh), fill=grout, width=1)
            draw.line((bx + bw, by, bx + bw, by + bh), fill=grout, width=1)

    elif pattern == "red_pillar_wall":
        draw.rectangle((0, 0, tile_px, tile_px), fill=(158, 27, 27))
        gold_color = (229, 193, 88)
        gold_shadow = (148, 120, 30)
        draw.rectangle((0, 2, tile_px, 6), fill=gold_color, outline=gold_shadow, width=1)
        draw.rectangle((0, tile_px - 7, tile_px, tile_px - 3), fill=gold_color, outline=gold_shadow, width=1)
        for offset_x in range(tile_px):
            factor = abs(offset_x - tile_px // 2) / (tile_px // 2)
            alpha = int((1.0 - factor) * 45) if offset_x < tile_px // 2 else int(factor * 75)
            overlay_color = (230, 92, 92, alpha) if offset_x < tile_px // 2 else (74, 9, 9, alpha)
            temp_im = Image.new("RGBA", (1, tile_px))
            temp_draw = ImageDraw.Draw(temp_im)
            temp_draw.line((0, 0, 0, tile_px), fill=overlay_color, width=1)
            im.alpha_composite(temp_im, (offset_x, 0))

    elif pattern == "bamboo_wall":
        draw.rectangle((0, 0, tile_px, tile_px), fill=(138, 154, 91))
        stalk_w = tile_px // 4
        for i in range(4):
            x = i * stalk_w
            color = (138, 154, 91) if i % 2 == 0 else (184, 175, 118)
            draw.rectangle((x + 1, 0, x + stalk_w - 1, tile_px), fill=color)
            draw.line((x + 2, 0, x + 2, tile_px), fill=(230, 240, 180, 100), width=1)
            draw.line((x + stalk_w - 2, 0, x + stalk_w - 2, tile_px), fill=(50, 60, 30, 120), width=1)
        twine = (82, 76, 43)
        draw.line((0, 6, tile_px, 6), fill=twine, width=1)
        draw.line((0, tile_px - 7, tile_px, tile_px - 7), fill=twine, width=1)
        for i in range(4):
            x = i * stalk_w + stalk_w // 2
            draw.line((x - 2, 4, x + 2, 8), fill=twine, width=1)
            draw.line((x + 2, 4, x - 2, 8), fill=twine, width=1)
            draw.line((x - 2, tile_px - 9, x + 2, tile_px - 5), fill=twine, width=1)
            draw.line((x + 2, tile_px - 9, x - 2, tile_px - 5), fill=twine, width=1)

    else:
        draw.rectangle((0, 0, tile_px, tile_px), fill=_hex_to_rgb(base_color))

    _TEXTURE_CACHE[cache_key] = im
    return im


def _draw_floor_pattern(
    draw: ImageDraw.ImageDraw,
    tile_box: tuple[int, int, int, int],
    *,
    pattern: str,
    base: str,
    highlight: str,
    outline: str,
    room_visual: dict[str, Any] | None = None,
) -> None:
    left, top, right, bottom = tile_box
    underlying_image = getattr(draw, "image", None)
    if underlying_image is not None and pattern in {"red_brick", "jade_tile", "bamboo_planks"}:
        texture = _get_pattern_texture(pattern, base, right - left)
        _tile_image(underlying_image, texture, tile_box)
        return

    draw.rectangle(tile_box, fill=base)
    if pattern == "wood_planks" or pattern == "library_planks" or pattern == "dorm_planks":
        for offset in range(top + 4, bottom, 8):
            draw.line((left + 2, offset, right - 2, offset), fill=outline, width=1)
        draw.line((left + (right - left) // 2, top + 3, left + (right - left) // 2, bottom - 3), fill=highlight, width=1)
    elif pattern == "paper_grid":
        draw.rectangle(tile_box, fill=highlight)
        for offset in range(left + 5, right, 8):
            draw.line((offset, top + 2, offset, bottom - 2), fill=base, width=1)
        for offset in range(top + 5, bottom, 8):
            draw.line((left + 2, offset, right - 2, offset), fill=base, width=1)
    elif pattern == "forge_slate":
        draw.rectangle(tile_box, fill=outline)
        draw.rectangle((left + 2, top + 2, right - 2, bottom - 2), fill=base)
        draw.line((left + 4, bottom - 6, right - 4, bottom - 6), fill=highlight, width=2)
    elif pattern == "yard_pavers":
        inset = 3
        draw.rectangle((left + inset, top + inset, right - inset, bottom - inset), fill=base, outline=outline, width=1)
        draw.line((left + 6, top + 6, right - 6, bottom - 6), fill=highlight, width=1)
    elif pattern == "war_room_inlay":
        draw.rectangle(tile_box, fill=base)
        draw.rectangle((left + 3, top + 3, right - 3, bottom - 3), outline=highlight, width=2)
        draw.line((left + 6, top + 6, right - 6, bottom - 6), fill=outline, width=1)
    elif pattern == "bamboo_planks":
        draw.rectangle(tile_box, fill=_mix(base, "#a3b86c", 0.6))
        for offset in range(left + 4, right, 6):
            draw.line((offset, top + 1, offset, bottom - 1), fill=outline, width=1)
            if (offset // 6) % 2 == 0:
                draw.line((offset - 2, top + 8, offset + 2, top + 8), fill=highlight, width=1)
                draw.line((offset - 2, bottom - 8, offset + 2, bottom - 8), fill=highlight, width=1)
    elif pattern == "red_brick":
        draw.rectangle(tile_box, fill=_mix(base, "#b04434", 0.8))
        draw.rectangle(tile_box, outline=outline, width=1)
        for offset in range(top + 8, bottom, 8):
            draw.line((left, offset, right, offset), fill=outline, width=1)
            draw.line((left + ((offset // 8) % 2) * 8 + 8, offset - 8, left + ((offset // 8) % 2) * 8 + 8, offset), fill=outline, width=1)
    elif pattern == "jade_tile":
        draw.rectangle(tile_box, fill=_mix(base, "#6eb897", 0.7))
        draw.rectangle((left + 2, top + 2, right - 2, bottom - 2), fill=_mix(highlight, "#8fd4b5", 0.7), outline=_mix(outline, "#3c7a5f", 0.8))
        draw.polygon([(left + 2, top + 2), (left + 6, top + 6), (left + 2, top + 10)], fill=_mix(highlight, "#ffffff", 0.5))
        draw.polygon([(right - 2, bottom - 2), (right - 6, bottom - 6), (right - 2, bottom - 10)], fill=_mix(outline, "#2a5c45", 0.8))
    else:
        inset = 2 if pattern == "clean_tile" else 1
        draw.rectangle((left + inset, top + inset, right - inset, bottom - inset), fill=highlight if pattern == "clean_tile" else base)
        draw.rectangle((left + inset, top + inset, right - inset, bottom - inset), outline=outline, width=1)
        if pattern == "clean_tile" and room_visual and room_visual.get("reflection_glares", False):
            # Draw diagonal glossy highlight lines representing polished glass/marble
            glare_color = (255, 255, 255, 120)
            draw.line((left + 3, top + 3, left + 10, top + 10), fill=glare_color, width=1)
            draw.line((left + 12, top + 3, left + 15, top + 6), fill=glare_color, width=1)
            # Add a subtle bevel highlight line on top and left inner border
            draw.line((left + inset + 1, top + inset + 1, right - inset - 2, top + inset + 1), fill=(255, 255, 255, 150), width=1)
            draw.line((left + inset + 1, top + inset + 1, left + inset + 1, bottom - inset - 2), fill=(255, 255, 255, 150), width=1)
        elif pattern in {"stone_checker", "stone_slabs"}:
            draw.line((left + 4, top + 4, right - 4, top + 4), fill=highlight, width=1)
            draw.line((left + 4, bottom - 4, right - 4, bottom - 4), fill=outline, width=1)
