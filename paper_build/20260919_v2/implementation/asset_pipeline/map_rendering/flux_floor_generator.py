import base64
import hashlib
import io
import json
import os
import random
from pathlib import Path
from typing import Any, Dict, List
import requests
import time
from PIL import Image, ImageDraw

# FLUX endpoint configuration
FLUX_ENDPOINT = "http://127.0.0.1:8135/generate"


def _hex_color(value: Any, default: str) -> str:
    text = str(value or "").strip()
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
            return text
        except ValueError:
            pass
    return default


def _geometry_guide(
    room: Dict[str, Any],
    *,
    width: int,
    height: int,
    tile_px: int,
) -> Image.Image:
    canon = room.get("visual_canon", {}) if isinstance(room.get("visual_canon", {}), dict) else {}
    palette = canon.get("palette", {}) if isinstance(canon.get("palette", {}), dict) else {}
    floor_color = _hex_color(palette.get("dominant"), "#48556a")
    wall_color = _hex_color(palette.get("shadow"), "#171a22")
    path_color = _hex_color(palette.get("secondary"), "#71859a")
    highlight_color = _hex_color(palette.get("highlight"), "#e9edf2")

    guide = Image.new("RGB", (width, height), floor_color)
    draw = ImageDraw.Draw(guide)
    wall_width = max(5, min(width, height) // 24)
    draw.rectangle((0, 0, width - 1, height - 1), outline=wall_color, width=wall_width)
    draw.rectangle(
        (wall_width, wall_width, width - wall_width - 1, height - wall_width - 1),
        outline=path_color,
        width=max(2, wall_width // 3),
    )

    room_x = int(room.get("x_pos", room.get("x", 0)))
    room_y = int(room.get("y_pos", room.get("y", 0)))
    room_w_tiles = max(1, int(room.get("width_tiles", 1)))
    room_h_tiles = max(1, int(room.get("height_tiles", 1)))
    for doorway in room.get("doorways", []):
        position = doorway.get("position", {}) if isinstance(doorway.get("position", {}), dict) else {}
        local_x = int(position.get("x", room_x)) - room_x
        local_y = int(position.get("y", room_y)) - room_y
        edge_dir = str(doorway.get("edge_dir", "")).strip().lower()
        center_x = int((local_x + 0.5) * width / room_w_tiles)
        center_y = int((local_y + 0.5) * height / room_h_tiles)
        opening = max(wall_width * 3, min(width, height) // 10)
        if edge_dir in {"top", "bottom"}:
            top = 0 if edge_dir == "top" else height - wall_width
            draw.rectangle(
                (max(0, center_x - opening // 2), top, min(width - 1, center_x + opening // 2), top + wall_width),
                fill=highlight_color,
            )
        elif edge_dir in {"left", "right"}:
            left = 0 if edge_dir == "left" else width - wall_width
            draw.rectangle(
                (left, max(0, center_y - opening // 2), left + wall_width, min(height - 1, center_y + opening // 2)),
                fill=highlight_color,
            )

    return guide


def _rgb(value: Any, default: str) -> tuple[int, int, int]:
    normalized = _hex_color(value, default)
    return tuple(int(normalized[index : index + 2], 16) for index in (1, 3, 5))


def _mix(
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    ratio = max(0.0, min(1.0, float(amount)))
    return tuple(
        max(0, min(255, round(first[index] * (1.0 - ratio) + second[index] * ratio)))
        for index in range(3)
    )


def _procedural_flat_floor(
    room: Dict[str, Any],
    *,
    width: int,
    height: int,
    tile_px: int,
) -> Image.Image:
    """Render a canon-colored collision substrate with no semantic silhouettes."""
    canon = room.get("visual_canon", {}) if isinstance(room.get("visual_canon", {}), dict) else {}
    palette = canon.get("palette", {}) if isinstance(canon.get("palette", {}), dict) else {}
    dominant = _rgb(palette.get("dominant"), "#48556a")
    secondary = _rgb(palette.get("secondary"), "#71859a")
    accent = _rgb(palette.get("accent"), "#d7b66f")
    shadow = _rgb(palette.get("shadow"), "#171a22")
    highlight = _rgb(palette.get("highlight"), "#e9edf2")
    floor_base = _mix(dominant, secondary, 0.08 if _near_blank_background(dominant) else 0.04)
    grout = _mix(floor_base, shadow, 0.2)
    border = _mix(shadow, secondary, 0.24)
    border_highlight = _mix(secondary, highlight, 0.34)
    motif = _mix(floor_base, accent, 0.2)

    seed_offset = int(os.environ.get("AGORA_FLUX_REPAIR_SEED_OFFSET", "0") or "0")
    stable_seed = int(
        hashlib.sha256(
            f"flat-floor:{canon.get('canon_hash', '')}:{room.get('room_id', '')}:{seed_offset}".encode("utf-8")
        ).hexdigest()[:16],
        16,
    )
    rng = random.Random(stable_seed)
    image = Image.new("RGB", (width, height), floor_base)
    draw = ImageDraw.Draw(image)

    room_w_tiles = max(1, int(room.get("width_tiles", max(1, width // max(1, tile_px)))))
    room_h_tiles = max(1, int(room.get("height_tiles", max(1, height // max(1, tile_px)))))
    for tile_y in range(room_h_tiles):
        for tile_x in range(room_w_tiles):
            left = round(tile_x * width / room_w_tiles)
            top = round(tile_y * height / room_h_tiles)
            right = round((tile_x + 1) * width / room_w_tiles) - 1
            bottom = round((tile_y + 1) * height / room_h_tiles) - 1
            variation = rng.uniform(0.018, 0.075)
            target = highlight if (tile_x + tile_y + stable_seed) % 3 else secondary
            tile_color = _mix(floor_base, target, variation)
            draw.rectangle((left, top, right, bottom), fill=tile_color)
            draw.line((left, top, right, top), fill=grout, width=1)
            draw.line((left, top, left, bottom), fill=grout, width=1)

    texture_targets = (secondary, accent, shadow, highlight)
    for _ in range(max(24, (width * height) // 22)):
        x = rng.randrange(width)
        y = rng.randrange(height)
        texture_color = _mix(
            floor_base,
            rng.choice(texture_targets),
            rng.uniform(0.035, 0.18),
        )
        image.putpixel((x, y), texture_color)

    inset = max(8, min(width, height) // 8)
    motif_kind = stable_seed % 4
    if motif_kind == 0:
        draw.rectangle(
            (inset, inset, width - inset - 1, height - inset - 1),
            outline=motif,
            width=max(2, tile_px // 10),
        )
    elif motif_kind == 1:
        band = max(3, tile_px // 7)
        center_x = width // 2
        center_y = height // 2
        draw.rectangle((center_x - band, inset, center_x + band, height - inset), fill=motif)
        draw.rectangle((inset, center_y - band, width - inset, center_y + band), fill=motif)
    elif motif_kind == 2:
        wave_color = _mix(floor_base, highlight, 0.24)
        step = max(18, tile_px)
        for offset in range(-height, width + height, step):
            draw.line((offset, height - inset, offset + height, inset), fill=wave_color, width=2)
    else:
        panel = max(2, tile_px // 12)
        draw.rectangle(
            (inset, inset, width - inset - 1, height - inset - 1),
            outline=motif,
            width=panel,
        )
        draw.rectangle(
            (inset + tile_px, inset + tile_px, width - inset - tile_px, height - inset - tile_px),
            outline=_mix(motif, highlight, 0.24),
            width=1,
        )

    for _ in range(max(4, (width * height) // 16000)):
        x = rng.randint(inset, max(inset, width - inset - 1))
        y = rng.randint(inset, max(inset, height - inset - 1))
        length = rng.randint(3, max(4, tile_px // 3))
        draw.line((x, y, min(width - 1, x + length), min(height - 1, y + rng.choice((-2, -1, 1, 2)))), fill=grout)

    wall_width = max(5, min(width, height) // 28)
    draw.rectangle((0, 0, width - 1, height - 1), outline=border, width=wall_width)
    draw.rectangle(
        (wall_width, wall_width, width - wall_width - 1, height - wall_width - 1),
        outline=border_highlight,
        width=max(2, wall_width // 3),
    )
    room_x = int(room.get("x_pos", room.get("x", 0)))
    room_y = int(room.get("y_pos", room.get("y", 0)))
    for doorway in room.get("doorways", []):
        position = doorway.get("position", {}) if isinstance(doorway.get("position", {}), dict) else {}
        local_x = int(position.get("x", room_x)) - room_x
        local_y = int(position.get("y", room_y)) - room_y
        edge_dir = str(doorway.get("edge_dir", "")).strip().lower()
        center_x = int((local_x + 0.5) * width / room_w_tiles)
        center_y = int((local_y + 0.5) * height / room_h_tiles)
        opening = max(tile_px, wall_width * 3)
        if edge_dir in {"top", "bottom"}:
            top = 0 if edge_dir == "top" else height - wall_width
            draw.rectangle(
                (max(0, center_x - opening // 2), top, min(width - 1, center_x + opening // 2), top + wall_width),
                fill=floor_base,
            )
        elif edge_dir in {"left", "right"}:
            left = 0 if edge_dir == "left" else width - wall_width
            draw.rectangle(
                (left, max(0, center_y - opening // 2), left + wall_width, min(height - 1, center_y + opening // 2)),
                fill=floor_base,
            )
    return image


def _canon_prompt(room: Dict[str, Any]) -> str:
    canon = room.get("visual_canon", {}) if isinstance(room.get("visual_canon", {}), dict) else {}
    if not canon:
        return ""
    materials = [
        " ".join(str(value).strip().split()[:3])
        for value in canon.get("materials", [])
        if str(value).strip()
    ][:3]
    return ", ".join(materials)


def _compact_room_prompt(
    room: Dict[str, Any],
    *,
    base_prompt: str,
    component_cues: list[str],
    max_words: int = 96,
) -> str:
    """Front-load hard spatial constraints while retaining room-specific identity."""
    scene = " ".join(base_prompt.split()[:28])
    fixtures = " ".join(" ".join(component_cues).split()[:18])
    canon_materials = _canon_prompt(room) or "world-specific tile, metal, glass"
    prompt = (
        "ORTHOGRAPHIC 90-DEGREE OVERHEAD 2D PIXEL TILEMAP. "
        "Vacant unoccupied architecture-only environment plate. "
        "Flat floor plan with thin overhead wall-cap outlines only; zero visible wall faces, horizon, depth, or camera tilt. "
        "Furnishings and inanimate machinery only. Symbol-free and lettering-free. "
        "Full-bleed rectangle reaching every image edge. "
        f"Room identity: {scene}. "
        f"Shared materials: {canon_materials}. "
        f"Distinctive fixtures: {fixtures or 'large readable world-specific machinery'}."
    )
    return " ".join(prompt.split()[: max(64, int(max_words))])


def _light_low_saturation(rgb: tuple[int, int, int]) -> bool:
    red, green, blue = rgb
    high = max(red, green, blue)
    low = min(red, green, blue)
    return high >= 205 and (high - low) <= 45


def _near_blank_background(rgb: tuple[int, int, int]) -> bool:
    red, green, blue = rgb
    high = max(red, green, blue)
    low = min(red, green, blue)
    return high >= 235 and (high - low) <= 24


def _edge_connected_blank_to_alpha(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    visited: set[tuple[int, int]] = set()
    stack: list[tuple[int, int]] = []

    for x in range(width):
        stack.append((x, 0))
        stack.append((x, height - 1))
    for y in range(height):
        stack.append((0, y))
        stack.append((width - 1, y))

    while stack:
        x, y = stack.pop()
        if (x, y) in visited or not (0 <= x < width and 0 <= y < height):
            continue
        visited.add((x, y))
        red, green, blue, alpha = pixels[x, y]
        if alpha < 8 or _near_blank_background((red, green, blue)):
            pixels[x, y] = (red, green, blue, 0)
            stack.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))

    return rgba


def _floor_quality_report(
    image: Image.Image,
    *,
    expected_size: tuple[int, int],
    allow_light_floor: bool = False,
) -> dict[str, Any]:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    transparent_ratio = sum(1 for value in alpha.getdata() if value < 8) / max(1, rgba.width * rgba.height)
    rgb = rgba.convert("RGB")
    width, height = rgb.size
    pixels = list(rgb.getdata())
    light_low_ratio = sum(1 for pixel in pixels if _light_low_saturation(pixel)) / max(1, len(pixels))
    blank_ratio = sum(1 for pixel in pixels if _near_blank_background(pixel)) / max(1, len(pixels))

    band_w = max(2, width // 16)
    band_h = max(2, height // 16)
    edge_pixels = []
    corner_pixels = []
    for y in range(height):
        for x in range(width):
            if x < band_w or x >= width - band_w or y < band_h or y >= height - band_h:
                edge_pixels.append(rgb.getpixel((x, y)))
            if (x < band_w or x >= width - band_w) and (y < band_h or y >= height - band_h):
                corner_pixels.append(rgb.getpixel((x, y)))
    edge_light_ratio = sum(1 for pixel in edge_pixels if _light_low_saturation(pixel)) / max(1, len(edge_pixels))
    edge_blank_ratio = sum(1 for pixel in edge_pixels if _near_blank_background(pixel)) / max(1, len(edge_pixels))
    corner_blank_ratio = sum(1 for pixel in corner_pixels if _near_blank_background(pixel)) / max(1, len(corner_pixels))

    max_blank_row_ratio = 0.0
    for y in range(height):
        row_ratio = sum(1 for x in range(width) if _near_blank_background(rgb.getpixel((x, y)))) / max(1, width)
        max_blank_row_ratio = max(max_blank_row_ratio, row_ratio)
    max_blank_col_ratio = 0.0
    for x in range(width):
        col_ratio = sum(1 for y in range(height) if _near_blank_background(rgb.getpixel((x, y)))) / max(1, height)
        max_blank_col_ratio = max(max_blank_col_ratio, col_ratio)

    background = rgb.getpixel((0, 0))
    changed_x: list[int] = []
    changed_y: list[int] = []
    for y in range(height):
        for x in range(width):
            pixel = rgb.getpixel((x, y))
            if sum(abs(pixel[channel] - background[channel]) for channel in range(3)) > 55:
                changed_x.append(x)
                changed_y.append(y)
    if changed_x:
        bbox = (min(changed_x), min(changed_y), max(changed_x) + 1, max(changed_y) + 1)
        bbox_area_ratio = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / max(1, width * height)
    else:
        bbox = None
        bbox_area_ratio = 0.0

    poster_card_background = not allow_light_floor and (
        edge_light_ratio > 0.88
        and (
            light_low_ratio > 0.35
            or bbox_area_ratio < 0.82
            or max_blank_row_ratio > 0.45
            or max_blank_col_ratio > 0.45
        )
        and (bbox_area_ratio < 0.88 or edge_light_ratio > 0.96)
    )
    blank_margin_background = not allow_light_floor and (
        blank_ratio > 0.12
        and (
            edge_blank_ratio > 0.22
            or corner_blank_ratio > 0.45
            or max_blank_row_ratio > 0.58
            or max_blank_col_ratio > 0.58
        )
    )
    transparent_card_background = transparent_ratio > 0.01
    visual_entropy = float(rgb.entropy())
    low_detail_background = visual_entropy < 5.2
    size_ok = (width, height) == expected_size
    pass_quality = (
        size_ok
        and not poster_card_background
        and not blank_margin_background
        and not transparent_card_background
        and not low_detail_background
    )
    return {
        "pass": pass_quality,
        "size_ok": size_ok,
        "width": width,
        "height": height,
        "expected_width": expected_size[0],
        "expected_height": expected_size[1],
        "light_low_saturation_ratio": round(light_low_ratio, 4),
        "blank_background_ratio": round(blank_ratio, 4),
        "edge_light_low_saturation_ratio": round(edge_light_ratio, 4),
        "edge_blank_background_ratio": round(edge_blank_ratio, 4),
        "corner_blank_background_ratio": round(corner_blank_ratio, 4),
        "max_blank_row_ratio": round(max_blank_row_ratio, 4),
        "max_blank_col_ratio": round(max_blank_col_ratio, 4),
        "transparent_ratio": round(transparent_ratio, 4),
        "visual_entropy": round(visual_entropy, 4),
        "foreground_bbox_area_ratio": round(bbox_area_ratio, 4),
        "foreground_bbox": bbox,
        "poster_card_background": poster_card_background,
        "blank_margin_background": blank_margin_background,
        "transparent_card_background": transparent_card_background,
        "low_detail_background": low_detail_background,
        "allow_light_floor": allow_light_floor,
    }


def _reject_floor(path: Path, report: dict[str, Any]) -> None:
    if not path.exists():
        return
    stamp = int(time.time())
    rejected_path = path.with_name(f"{path.stem}.rejected_{stamp}{path.suffix}")
    try:
        path.replace(rejected_path)
        report_path = rejected_path.with_suffix(".qa.json")
        report_path.write_text(
            __import__("json").dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        path.unlink(missing_ok=True)


def _fallback_room_prompt(room: Dict[str, Any]) -> str:
    room_id = str(room.get("room_id", "room")).strip()
    room_name = str(room.get("name", room_id) or room_id).strip()
    metadata = room.get("metadata", {}) if isinstance(room.get("metadata"), dict) else {}
    visual = room.get("visual", {}) if isinstance(room.get("visual"), dict) else {}
    purpose = str(metadata.get("purpose", "") or "active room interaction space").strip()
    biome = str(visual.get("biome", "") or "fictional interior").strip()
    decor = ", ".join(str(tag).strip() for tag in visual.get("decor_tags", []) if str(tag).strip())
    palette = str(visual.get("ambient_palette", "") or "coherent readable palette").strip()
    return (
        f"Top-down pixel art room plate for {room_name}, a {biome} location. "
        f"Purpose: {purpose}. "
        f"Decor and materials: {decor or 'room-specific fixtures, worn floor material, readable props'}. "
        f"Palette: {palette}. "
        "The room must fill the entire rectangular image from edge to edge with floor, walls, and props."
    )

def generate_flux_floor(
    room: Dict[str, Any],
    output_dir: Path,
    provider: Any = None,
    tile_px: int = 32
) -> str:
    """
    Generate a room-scale top-down plate using FLUX2 and downscale using
    nearest-neighbor so it fits the authored room footprint exactly.
    """
    room_id = room.get("room_id", "unknown_room")
    room_name = str(room.get("name", room_id) or room_id).strip()
    purpose = str(((room.get("metadata") or {}).get("purpose") if isinstance(room.get("metadata"), dict) else "") or "").strip()
    visual = room.get("visual", {}) if isinstance(room.get("visual", {}), dict) else {}
    decor_tags = ", ".join(str(tag).strip() for tag in visual.get("decor_tags", []) if str(tag).strip())
    base_prompt = str(
        room.get("room_scene_prompt")
        or room.get("flux_floor_prompt")
        or ""
    ).strip() or _fallback_room_prompt(room)
    w_tiles = int(room.get("width_tiles", 5))
    h_tiles = int(room.get("height_tiles", 5))

    # Calculate aspect ratio
    aspect = w_tiles / h_tiles

    # Typical FLUX max dimension is 1024, so let's scale it while keeping aspect ratio
    if aspect >= 1.0:
        flux_w = 1024
        flux_h = int(1024 / aspect)
    else:
        flux_h = 1024
        flux_w = int(1024 * aspect)

    # Ensure they are multiples of 32 (often required by image models)
    flux_w = (flux_w // 32) * 32
    flux_h = (flux_h // 32) * 32

    # The actual FLUX call (using our compositor fallback which wraps vertex/flux logic)
    # Note: If generate_image_with_fallback doesn't support width/height, we might need a custom call.
    # For now we pass width/height as kwargs if the underlying client supports it,
    # but the primary prompt is what matters for the style.
    # To enforce the LORA pixel art, we append our trigger words just in case.
    component_cues = [
        str(component.get("description", "")).strip()[:90]
        for component in visual.get("scene_components", [])
        if isinstance(component, dict) and str(component.get("description", "")).strip()
    ]
    full_prompt = _compact_room_prompt(
        room,
        base_prompt=base_prompt,
        component_cues=[
            *component_cues,
            f"decor: {decor_tags}" if decor_tags else "",
            f"function: {purpose}" if purpose else "",
        ],
    )

    out_path = output_dir / f"floor_{room_id}.png"
    final_w = w_tiles * tile_px
    final_h = h_tiles * tile_px
    expected_size = (final_w, final_h)
    visual_canon = room.get("visual_canon", {}) if isinstance(room.get("visual_canon", {}), dict) else {}
    canon_palette = (
        visual_canon.get("palette", {})
        if isinstance(visual_canon.get("palette", {}), dict)
        else {}
    )
    dominant_hex = _hex_color(canon_palette.get("dominant"), "#48556a")
    allow_light_floor = _near_blank_background(
        tuple(int(dominant_hex[index : index + 2], 16) for index in (1, 3, 5))
    )
    # With the 8-step Schnell schedule, values below 0.875 quantize to too few
    # denoising steps and can reproduce the guide almost unchanged.
    default_geometry_strength = 0.88
    if out_path.exists():
        if out_path.stat().st_size > 1024:
            try:
                with Image.open(out_path) as img:
                    quality_report = _floor_quality_report(
                        img,
                        expected_size=expected_size,
                        allow_light_floor=allow_light_floor,
                    )
                    if quality_report.get("pass") is True:
                        return str(out_path)
                    print(f"[FLOOR_QA] Rejecting cached floor for {room_id}: {quality_report}", flush=True)
                    _reject_floor(out_path, quality_report)
            except Exception:
                pass
        out_path.unlink(missing_ok=True)

    render_mode = str(
        os.environ.get(
            "AGORA_FLUX_FLOOR_RENDER_MODE",
            "layered" if visual_canon else "generative",
        )
    ).strip().lower()
    if render_mode in {"layered", "procedural", "flat"}:
        image = _procedural_flat_floor(
            room,
            width=final_w,
            height=final_h,
            tile_px=tile_px,
        ).convert("RGBA")
        quality_report = _floor_quality_report(
            image,
            expected_size=expected_size,
            allow_light_floor=allow_light_floor,
        )
        layered_pass = bool(
            quality_report.get("size_ok")
            and not quality_report.get("poster_card_background")
            and not quality_report.get("blank_margin_background")
            and not quality_report.get("transparent_card_background")
            and float(quality_report.get("visual_entropy", 0.0) or 0.0) >= 4.2
        )
        quality_report["pass"] = layered_pass
        quality_report["layered_min_entropy"] = 4.2
        if not layered_pass:
            raise RuntimeError(f"Layered floor QA failed for {room_id}: {quality_report}")
        image.save(out_path)
        quality_report.update(
            {
                "room_id": room_id,
                "visual_canon_hash": str(visual_canon.get("canon_hash", "")),
                "geometry_conditioning": "procedural_visual_canon_floor",
                "render_mode": "layered",
            }
        )
        out_path.with_suffix(".qa.json").write_text(
            json.dumps(quality_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[FLOOR_LAYER] Rendered flat canon substrate for {room_id}", flush=True)
        return str(out_path)

    print(f"Generating FLUX floor for room {room_id} ({w_tiles}x{h_tiles} tiles). Native res: {flux_w}x{flux_h}")
    # We call the generation (assuming the client can parse width/height if we pass it,
    # or it generates 1024x1024 and we crop/resize it later)
    # For robust integration we just use the prompt and then rigorously resize.
    temp_img_path = output_dir / f"temp_{room_id}.png"
    geometry_guide = _geometry_guide(room, width=flux_w, height=flux_h, tile_px=tile_px)
    geometry_guide_path = output_dir / f"guide_{room_id}.png"
    geometry_guide.save(geometry_guide_path)
    guide_buffer = io.BytesIO()
    geometry_guide.save(guide_buffer, format="PNG")
    guide_b64 = base64.b64encode(guide_buffer.getvalue()).decode("ascii")
    stable_seed = int(
        hashlib.sha256(
            f"{room.get('visual_canon', {}).get('canon_hash', '')}:{room_id}".encode("utf-8")
        ).hexdigest()[:8],
        16,
    )

    # Check FLUX health first
    try:
        health_resp = requests.get(FLUX_ENDPOINT.replace("/generate", "/health"), timeout=5)
        health_resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"FLUX service is DOWN or unreachable at {FLUX_ENDPOINT}: {e}")

    # Make request to the local FLUX service with retry, then QA the resized tile plate.
    max_retries = int(os.environ.get("AGORA_FLUX_FLOOR_MAX_RETRIES", "2") or "2")
    last_quality_report: dict[str, Any] | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                FLUX_ENDPOINT,
                json={
                    "prompt": full_prompt,
                    "negative_prompt": (
                        "text, label, caption, room name, title, watermark, logo, poster border, "
                        "letters, words, numbers, signage, legible glyphs, pseudo-text, "
                        "people, person, human, character, humanoid, face, body, portrait, statue, "
                        "eye-level view, horizon, vanishing point, perspective corridor, tall walls, "
                        "visible wall faces, raised room box, cutaway room, interior elevation, "
                        "isometric camera, three-quarter camera, deep perspective, "
                        "concept art sheet, reference card, white background, beige blank background, "
                        "rounded room on white page, isolated room floating on page, empty margins, "
                        "blank corners, vignette, soft photo render"
                    ),
                    "width": flux_w,
                    "height": flux_h,
                    "steps": 8,
                    "asset_kind": "map_asset",
                    "output_path": str(temp_img_path),
                    "init_image_base64": guide_b64,
                    "strength": float(
                        os.environ.get("AGORA_FLUX_GEOMETRY_STRENGTH", str(default_geometry_strength))
                        or str(default_geometry_strength)
                    ),
                    "seed": (
                        stable_seed
                        + attempt
                        + int(os.environ.get("AGORA_FLUX_REPAIR_SEED_OFFSET", "0") or "0")
                    ),
                },
                timeout=600
            )
            resp.raise_for_status()
        except Exception as e:
            if attempt < max_retries:
                print(f"Error calling FLUX service, retrying: {e}")
                time.sleep(2)
                continue
            else:
                raise RuntimeError(f"FLUX generation failed for {room_id} after {max_retries} retries: {e}")

        if not temp_img_path.exists():
            raise RuntimeError(f"FLUX service returned OK but {temp_img_path} was not created.")

        img = Image.open(temp_img_path).convert("RGBA")
        temp_img_path.unlink(missing_ok=True)

        # We first crop to exact aspect ratio if FLUX didn't respect the requested dimensions.
        actual_aspect = img.width / img.height
        target_aspect = final_w / final_h
        if abs(actual_aspect - target_aspect) > 0.05:
            if actual_aspect > target_aspect:
                new_w = int(img.height * target_aspect)
                left = (img.width - new_w) // 2
                img = img.crop((left, 0, left + new_w, img.height))
            else:
                new_h = int(img.width / target_aspect)
                top = (img.height - new_h) // 2
                img = img.crop((0, top, img.width, top + new_h))

        img = img.resize((final_w, final_h), resample=Image.NEAREST)
        if not allow_light_floor:
            img = _edge_connected_blank_to_alpha(img)
        quality_report = _floor_quality_report(
            img,
            expected_size=expected_size,
            allow_light_floor=allow_light_floor,
        )
        if quality_report.get("pass") is True:
            img.save(out_path)
            quality_report.update(
                {
                    "room_id": room_id,
                    "visual_canon_hash": str(room.get("visual_canon", {}).get("canon_hash", "")),
                    "geometry_guide_path": str(geometry_guide_path),
                    "geometry_conditioning": "flux_img2img",
                }
            )
            out_path.with_suffix(".qa.json").write_text(
                json.dumps(quality_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return str(out_path)
        last_quality_report = quality_report
        rejected_path = output_dir / f"floor_{room_id}.rejected_attempt_{attempt + 1}.png"
        img.save(rejected_path)
        rejected_path.with_suffix(".qa.json").write_text(
            json.dumps(quality_report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[FLOOR_QA] Rejecting generated floor for {room_id}: {quality_report}", flush=True)
        if attempt < max_retries:
            time.sleep(1)

    raise RuntimeError(f"FLUX floor QA failed for {room_id}: {last_quality_report}")

def generate_all_floors(config: Dict[str, Any], output_dir: Path, provider: Any = None):
    output_dir.mkdir(parents=True, exist_ok=True)
    rooms = config.get("space", {}).get("rooms", [])
    for room in rooms:
        generate_flux_floor(room, output_dir, provider)
