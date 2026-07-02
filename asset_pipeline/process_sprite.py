#!/usr/bin/env python3
"""Convert a large character sheet into a Phaser-ready pixel atlas."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    cv2 = None


DEFAULT_ALPHA_THRESHOLD = 8
DEFAULT_TARGET_FRAME_SIZE = 32
DEFAULT_FOOT_BASELINE_Y = 30
SEARCH_WINDOW_MARGIN_PX = 12
SEARCH_EXPAND_STEP_PX = 8
MAX_SEARCH_EXPAND_PX = 24
COMPONENT_BBOX_PAD_PX = 1
MIN_COMPONENT_ALPHA_PIXELS = 6

DEFAULT_ANIMATION_STATES = [
    {"name": "idle_down", "row": 0, "frame_count": 4, "frame_rate": 4, "repeat": 0, "static_frame_index": 0},
    {"name": "walk_down", "row": 1, "frame_count": 4, "frame_rate": 7, "repeat": -1},
    {"name": "walk_left", "row": 2, "frame_count": 4, "frame_rate": 7, "repeat": -1},
    {"name": "walk_right", "row": 3, "frame_count": 4, "frame_rate": 7, "repeat": -1},
]

DEFAULT_ALIGNMENT_POLICY = {
    "mode": "foot_anchor_center",
    "anchor_bottom_px": DEFAULT_FOOT_BASELINE_Y,
    "center_horizontally": True,
    "max_bottom_jitter_px": 4,
    "max_horizontal_jitter_px": 4,
    "max_torso_jitter_px": 5,
    "max_foot_anchor_jitter_px": 6,
    "min_body_height_ratio": 0.68,
    "max_body_height_ratio": 0.95,
    "max_body_width_ratio": 0.82,
    "max_scale_up": 1.85,
    "target_body_height_ratio": 0.88,
    "target_body_width_ratio": 0.64,
    "upper_body_ratio": 0.58,
    "foot_band_ratio": 0.18,
    "pad_source_to_square": True,
}


@dataclass(frozen=True)
class AnimationState:
    name: str
    row: int
    frame_count: int
    frame_rate: int
    repeat: int = -1
    start_col: int = 0
    static_frame_index: int | None = None


def _load_animation_states(animation_spec_path: str | None) -> list[AnimationState]:
    if not animation_spec_path:
        source = DEFAULT_ANIMATION_STATES
    else:
        source = json.loads(Path(animation_spec_path).read_text(encoding="utf-8"))
    return [AnimationState(**entry) for entry in source]


def _strip_near_white_background(
    image: Image.Image,
    *,
    near_white_threshold: int,
    neutral_tolerance: int,
    alpha_threshold: int,
) -> Image.Image:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = list(rgba.getdata())

    def near_white_at(index: int) -> bool:
        red, green, blue, alpha = pixels[index]
        if alpha < alpha_threshold:
            return False
        channel_min = min(red, green, blue)
        channel_max = max(red, green, blue)
        return (
            red >= near_white_threshold
            and green >= near_white_threshold
            and blue >= near_white_threshold
            and (channel_max - channel_min) <= neutral_tolerance
        )

    queue: deque[tuple[int, int]] = deque()
    visited: set[int] = set()
    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))

    while queue:
        x, y = queue.popleft()
        if x < 0 or y < 0 or x >= width or y >= height:
            continue
        index = y * width + x
        if index in visited or not near_white_at(index):
            continue
        visited.add(index)
        queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))

    cleaned: list[tuple[int, int, int, int]] = []
    for index, (red, green, blue, alpha) in enumerate(pixels):
        cleaned.append((red, green, blue, 0 if alpha < alpha_threshold or index in visited else alpha))
    rgba.putdata(cleaned)
    return rgba


def _clear_exposed_near_white_pixels(
    image: Image.Image,
    *,
    near_white_threshold: int,
    neutral_tolerance: int,
    alpha_threshold: int,
) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = np.array(rgba, dtype=np.uint8)
    height, width = pixels.shape[:2]
    alpha = pixels[:, :, 3]
    near_white = (
        (alpha >= alpha_threshold)
        & (pixels[:, :, 0] >= near_white_threshold)
        & (pixels[:, :, 1] >= near_white_threshold)
        & (pixels[:, :, 2] >= near_white_threshold)
        & ((pixels[:, :, :3].max(axis=2) - pixels[:, :, :3].min(axis=2)) <= neutral_tolerance)
    )
    if not np.any(near_white):
        return rgba

    exposed = np.zeros_like(near_white, dtype=bool)
    for y in range(height):
        for x in range(width):
            if not near_white[y, x]:
                continue
            for next_y in range(max(0, y - 1), min(height, y + 2)):
                for next_x in range(max(0, x - 1), min(width, x + 2)):
                    if alpha[next_y, next_x] < alpha_threshold:
                        exposed[y, x] = True
                        break
                if exposed[y, x]:
                    break
    pixels[exposed, 3] = 0
    return Image.fromarray(pixels, mode="RGBA")


def _quantize_frame(
    image: Image.Image,
    palette_size: int,
    alpha_threshold: int,
    *,
    remove_near_white_background: bool,
    near_white_threshold: int,
    neutral_tolerance: int,
) -> Image.Image:
    rgba = image.convert("RGBA")
    if remove_near_white_background:
        rgba = _strip_near_white_background(
            rgba,
            near_white_threshold=near_white_threshold,
            neutral_tolerance=neutral_tolerance,
            alpha_threshold=alpha_threshold,
        )
    alpha = rgba.getchannel("A")
    rgb = rgba.convert("RGB")
    quantized = rgb.quantize(
        colors=palette_size,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    ).convert("RGBA")
    mask = alpha.point(lambda value: 255 if value >= alpha_threshold else 0)
    quantized.putalpha(mask)
    if remove_near_white_background:
        quantized = _clear_exposed_near_white_pixels(
            quantized,
            near_white_threshold=near_white_threshold,
            neutral_tolerance=neutral_tolerance,
            alpha_threshold=alpha_threshold,
        )
    return quantized


def _frame_name(state_name: str, frame_index: int) -> str:
    return f"{state_name}_{frame_index}.png"


def _bbox_to_payload(box: tuple[int, int, int, int] | None) -> dict[str, int] | None:
    if box is None:
        return None
    left, top, right, bottom = box
    return {
        "left": int(left),
        "top": int(top),
        "right": int(right - 1),
        "bottom": int(bottom - 1),
        "width": int(right - left),
        "height": int(bottom - top),
    }


def _mask_bbox(image: Image.Image, alpha_threshold: int) -> tuple[int, int, int, int] | None:
    alpha = np.array(image.getchannel("A"), dtype=np.uint8)
    coords = np.argwhere(alpha >= alpha_threshold)
    if coords.size == 0:
        return None
    top = int(coords[:, 0].min())
    bottom = int(coords[:, 0].max()) + 1
    left = int(coords[:, 1].min())
    right = int(coords[:, 1].max()) + 1
    return (left, top, right, bottom)


def _pad_image_to_aspect_ratio(
    image: Image.Image,
    *,
    target_aspect_ratio: float,
) -> Image.Image:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width <= 0 or height <= 0:
        return rgba
    desired_ratio = max(0.01, float(target_aspect_ratio))
    current_ratio = width / float(height)
    if abs(current_ratio - desired_ratio) <= 0.01:
        return rgba
    if current_ratio < desired_ratio:
        target_width = max(width, int(round(height * desired_ratio)))
        canvas = Image.new("RGBA", (target_width, height), (0, 0, 0, 0))
        paste_x = (target_width - width) // 2
        canvas.paste(rgba, (paste_x, 0), rgba)
        return canvas
    target_height = max(height, int(round(width / desired_ratio)))
    canvas = Image.new("RGBA", (width, target_height), (0, 0, 0, 0))
    paste_y = target_height - height
    canvas.paste(rgba, (0, paste_y), rgba)
    return canvas


def _alignment_policy(policy: dict[str, Any] | None, target_frame_height: int) -> dict[str, Any]:
    merged = dict(DEFAULT_ALIGNMENT_POLICY)
    if policy:
        merged.update(policy)
    merged["anchor_bottom_px"] = int(merged.get("anchor_bottom_px", DEFAULT_FOOT_BASELINE_Y))
    merged["anchor_bottom_px"] = max(1, min(target_frame_height - 1, merged["anchor_bottom_px"]))
    merged["center_horizontally"] = bool(merged.get("center_horizontally", True))
    merged["max_bottom_jitter_px"] = int(merged.get("max_bottom_jitter_px", 4))
    merged["max_horizontal_jitter_px"] = int(merged.get("max_horizontal_jitter_px", 4))
    merged["max_torso_jitter_px"] = int(merged.get("max_torso_jitter_px", 5))
    merged["max_foot_anchor_jitter_px"] = int(merged.get("max_foot_anchor_jitter_px", 6))
    merged["min_body_height_ratio"] = float(merged.get("min_body_height_ratio", 0.68))
    merged["max_body_height_ratio"] = float(merged.get("max_body_height_ratio", 0.95))
    merged["max_body_width_ratio"] = float(merged.get("max_body_width_ratio", 0.82))
    merged["max_scale_up"] = float(merged.get("max_scale_up", 1.85))
    merged["target_body_height_ratio"] = float(merged.get("target_body_height_ratio", 0.88))
    merged["target_body_width_ratio"] = float(merged.get("target_body_width_ratio", 0.64))
    merged["upper_body_ratio"] = float(merged.get("upper_body_ratio", 0.58))
    merged["foot_band_ratio"] = float(merged.get("foot_band_ratio", 0.18))
    merged["pad_source_to_square"] = bool(merged.get("pad_source_to_square", True))
    return merged


def _expand_box(box: tuple[int, int, int, int], margin: int, bounds: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = bounds
    left, top, right, bottom = box
    return (
        max(0, left - margin),
        max(0, top - margin),
        min(width, right + margin),
        min(height, bottom + margin),
    )


def _bbox_area(box: tuple[int, int, int, int]) -> int:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _intersection_area(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0
    return (right - left) * (bottom - top)


def _touches_search_edge(box: tuple[int, int, int, int], search_window: tuple[int, int, int, int]) -> bool:
    return (
        box[0] <= search_window[0]
        or box[1] <= search_window[1]
        or box[2] >= search_window[2]
        or box[3] >= search_window[3]
    )


def _component_sort_key(
    component: dict[str, Any],
    cell_box: tuple[int, int, int, int],
) -> tuple[int, int, float]:
    overlap = _intersection_area(component["bbox"], cell_box)
    area = int(component["area"])
    cell_center_x = (cell_box[0] + cell_box[2]) / 2.0
    cell_center_y = (cell_box[1] + cell_box[3]) / 2.0
    centroid_x, centroid_y = component["centroid"]
    distance = ((centroid_x - cell_center_x) ** 2) + ((centroid_y - cell_center_y) ** 2)
    return (overlap, area, -distance)


def _connected_components_numpy(mask: np.ndarray, min_pixels: int, window_origin: tuple[int, int]) -> list[dict[str, Any]]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    components: list[dict[str, Any]] = []
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue
            queue: deque[tuple[int, int]] = deque([(x, y)])
            visited[y, x] = True
            pixels: list[tuple[int, int]] = []
            while queue:
                current_x, current_y = queue.popleft()
                pixels.append((current_x, current_y))
                for next_x, next_y in (
                    (current_x - 1, current_y),
                    (current_x + 1, current_y),
                    (current_x, current_y - 1),
                    (current_x, current_y + 1),
                ):
                    if next_x < 0 or next_y < 0 or next_x >= width or next_y >= height:
                        continue
                    if visited[next_y, next_x] or not mask[next_y, next_x]:
                        continue
                    visited[next_y, next_x] = True
                    queue.append((next_x, next_y))
            if len(pixels) < min_pixels:
                continue
            xs = [entry[0] for entry in pixels]
            ys = [entry[1] for entry in pixels]
            local_mask = np.zeros_like(mask, dtype=bool)
            for px, py in pixels:
                local_mask[py, px] = True
            components.append(
                {
                    "bbox": (
                        window_origin[0] + min(xs),
                        window_origin[1] + min(ys),
                        window_origin[0] + max(xs) + 1,
                        window_origin[1] + max(ys) + 1,
                    ),
                    "area": int(len(pixels)),
                    "centroid": (
                        window_origin[0] + (sum(xs) / float(len(xs))),
                        window_origin[1] + (sum(ys) / float(len(ys))),
                    ),
                    "mask": local_mask,
                    "backend": "numpy",
                }
            )
    return components


def _connected_components_with_fallback(
    mask: np.ndarray,
    min_pixels: int,
    window_origin: tuple[int, int],
) -> list[dict[str, Any]]:
    if cv2 is not None:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        closed_mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
        labels_count, labels, stats, centroids = cv2.connectedComponentsWithStats(closed_mask, 8)
        components: list[dict[str, Any]] = []
        for label in range(1, labels_count):
            component_mask_closed = (labels == label)
            component_mask_original = component_mask_closed & mask.astype(bool)
            area = int(np.sum(component_mask_original))
            if area < min_pixels:
                continue
            
            # Recalculate true bounding box from the original masked pixels to keep crop tight
            rows, cols = np.where(component_mask_original)
            if len(rows) == 0:
                continue
            left, top = int(np.min(cols)), int(np.min(rows))
            right, bottom = int(np.max(cols)) + 1, int(np.max(rows)) + 1
            width = right - left
            height = bottom - top

            components.append(
                {
                    "bbox": (
                        window_origin[0] + left,
                        window_origin[1] + top,
                        window_origin[0] + left + width,
                        window_origin[1] + top + height,
                    ),
                    "area": area,
                    "centroid": (
                        window_origin[0] + float(centroids[label][0]),
                        window_origin[1] + float(centroids[label][1]),
                    ),
                    "mask": component_mask_original,
                    "backend": "cv2",
                }
            )
        return components
    return _connected_components_numpy(mask, min_pixels, window_origin)


def _select_primary_component(
    components: list[dict[str, Any]],
    cell_box: tuple[int, int, int, int],
) -> dict[str, Any] | None:
    if not components:
        return None
    return max(components, key=lambda component: _component_sort_key(component, cell_box))


def _extract_component_mask(
    image: Image.Image,
    component: dict[str, Any],
    search_window: tuple[int, int, int, int],
    pad_px: int,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    component_bbox = component["bbox"]
    padded_bbox = _expand_box(component_bbox, pad_px, image.size)
    crop = np.array(image.crop(padded_bbox), dtype=np.uint8)
    mask = np.zeros((padded_bbox[3] - padded_bbox[1], padded_bbox[2] - padded_bbox[0]), dtype=bool)
    overlap_left = max(padded_bbox[0], search_window[0])
    overlap_top = max(padded_bbox[1], search_window[1])
    overlap_right = min(padded_bbox[2], search_window[2])
    overlap_bottom = min(padded_bbox[3], search_window[3])
    if overlap_right > overlap_left and overlap_bottom > overlap_top:
        destination_x = overlap_left - padded_bbox[0]
        destination_y = overlap_top - padded_bbox[1]
        local_x = overlap_left - search_window[0]
        local_y = overlap_top - search_window[1]
        local_mask = component["mask"][local_y : local_y + (overlap_bottom - overlap_top), local_x : local_x + (overlap_right - overlap_left)]
        mask[
            destination_y : destination_y + local_mask.shape[0],
            destination_x : destination_x + local_mask.shape[1],
        ] = local_mask
    crop[~mask] = (0, 0, 0, 0)
    return Image.fromarray(crop, mode="RGBA"), padded_bbox


def _expand_search_window_until_stable(
    image: Image.Image,
    cell_box: tuple[int, int, int, int],
    *,
    alpha_threshold: int,
) -> dict[str, Any]:
    # 理论网格只用于提供搜索中心，不再把它当作最终裁切框。
    # 这样即使角色轻微越过单元格边界，我们也可以从周围容错区域把完整主体找回来。
    initial_window = _expand_box(cell_box, SEARCH_WINDOW_MARGIN_PX, image.size)
    current_margin = SEARCH_WINDOW_MARGIN_PX
    previous_bbox: tuple[int, int, int, int] | None = None
    chosen_component: dict[str, Any] | None = None
    final_window = initial_window
    while True:
        search_window = _expand_box(cell_box, current_margin, image.size)
        window_rgba = image.crop(search_window)
        alpha_mask = np.array(window_rgba.getchannel("A"), dtype=np.uint8) >= alpha_threshold
        components = _connected_components_with_fallback(
            alpha_mask,
            MIN_COMPONENT_ALPHA_PIXELS,
            (search_window[0], search_window[1]),
        )
        chosen_component = _select_primary_component(components, cell_box)
        final_window = search_window
        if chosen_component is None:
            break
        touches_search_edge = _touches_search_edge(chosen_component["bbox"], search_window)
        bbox_stable = previous_bbox == chosen_component["bbox"] and previous_bbox is not None
        if (not touches_search_edge) or bbox_stable or current_margin >= MAX_SEARCH_EXPAND_PX:
            break
        previous_bbox = chosen_component["bbox"]
        current_margin = min(MAX_SEARCH_EXPAND_PX, current_margin + SEARCH_EXPAND_STEP_PX)

    if chosen_component is None:
        return {
            "empty": True,
            "search_window": _bbox_to_payload(initial_window),
            "expanded_search_window": _bbox_to_payload(final_window),
            "selected_component_bbox": None,
            "component_area_px": 0,
            "touches_search_edge": False,
            "component_backend": "none",
            "component_image": Image.new("RGBA", (cell_box[2] - cell_box[0], cell_box[3] - cell_box[1]), (0, 0, 0, 0)),
            "component_crop_bbox": None,
        }

    component_image, padded_bbox = _extract_component_mask(image, chosen_component, final_window, COMPONENT_BBOX_PAD_PX)
    return {
        "empty": False,
        "search_window": _bbox_to_payload(initial_window),
        "expanded_search_window": _bbox_to_payload(final_window),
        "selected_component_bbox": _bbox_to_payload(chosen_component["bbox"]),
        "component_area_px": int(chosen_component["area"]),
        "touches_search_edge": bool(_touches_search_edge(chosen_component["bbox"], final_window)),
        "component_backend": str(chosen_component["backend"]),
        "component_image": component_image,
        "component_crop_bbox": _bbox_to_payload(padded_bbox),
    }


def _frame_anchor_metrics(
    frame: Image.Image,
    *,
    alpha_threshold: int,
    upper_body_ratio: float,
    foot_band_ratio: float,
) -> dict[str, float] | None:
    bbox = _mask_bbox(frame, alpha_threshold)
    if bbox is None:
        return None
    rgba = frame.convert("RGBA")
    left, top, right, bottom = bbox
    width = max(1, right - left)
    height = max(1, bottom - top)
    pixels = rgba.load()
    upper_limit = min(bottom, top + max(1, int(round(height * upper_body_ratio))))
    torso_xs: list[int] = []
    for y in range(top, upper_limit):
        for x in range(left, right):
            if pixels[x, y][3] >= alpha_threshold:
                torso_xs.append(x)
    torso_center_x = ((min(torso_xs) + max(torso_xs)) / 2.0) if torso_xs else (left + (width / 2.0))

    foot_band_height = max(2, int(round(height * foot_band_ratio)))
    foot_top = max(top, bottom - foot_band_height)
    bottom_y = max(y for y in range(top, bottom) if any(pixels[x, y][3] >= alpha_threshold for x in range(left, right)))
    foot_xs = [x for x in range(left, right) if pixels[x, bottom_y][3] >= alpha_threshold]
    if not foot_xs:
        for y in range(bottom_y, foot_top - 1, -1):
            foot_xs = [x for x in range(left, right) if pixels[x, y][3] >= alpha_threshold]
            if foot_xs:
                bottom_y = y
                break
    support_band_xs = [
        x
        for y in range(foot_top, bottom)
        for x in range(left, right)
        if pixels[x, y][3] >= alpha_threshold
    ]
    if support_band_xs:
        foot_anchor_x = (min(support_band_xs) + max(support_band_xs)) / 2.0
    elif foot_xs:
        foot_anchor_x = sum(foot_xs) / float(len(foot_xs))
    else:
        foot_anchor_x = left + (width / 2.0)
    return {
        "torso_center_x": float(torso_center_x),
        "foot_anchor_x": float(foot_anchor_x),
        "bottom_y": float(bottom_y),
    }


def _shared_scale_factor_from_extractions(
    extractions: list[dict[str, Any]],
    *,
    target_frame_width: int,
    target_frame_height: int,
    policy: dict[str, Any],
) -> float:
    widths = [
        int(entry["selected_component_bbox"]["width"])
        for entry in extractions
        if entry.get("selected_component_bbox")
    ]
    heights = [
        int(entry["selected_component_bbox"]["height"])
        for entry in extractions
        if entry.get("selected_component_bbox")
    ]
    if not widths or not heights:
        return 1.0
    max_width = max(widths)
    max_height = max(heights)
    if max_width <= 0 or max_height <= 0:
        return 1.0
    max_body_width_px = max(1, min(target_frame_width - 2, int(round(target_frame_width * float(policy["max_body_width_ratio"])))))
    max_body_height_px = max(1, min(target_frame_height - 2, int(round(target_frame_height * float(policy["max_body_height_ratio"])))))
    target_body_width_px = max(
        1,
        min(max_body_width_px, int(round(target_frame_width * float(policy["target_body_width_ratio"])))),
    )
    target_body_height_px = max(
        1,
        min(max_body_height_px, int(round(target_frame_height * float(policy["target_body_height_ratio"])))),
    )
    fit_scale = min(max_body_width_px / float(max_width), max_body_height_px / float(max_height))
    target_scale = min(target_body_width_px / float(max_width), target_body_height_px / float(max_height))
    return max(0.01, min(float(policy["max_scale_up"]), float(fit_scale), float(target_scale)))


def _render_component_to_target_frame(
    component_image: Image.Image,
    *,
    alpha_threshold: int,
    target_frame_width: int,
    target_frame_height: int,
    policy: dict[str, Any],
    scale_factor_override: float,
) -> tuple[Image.Image, dict[str, Any]]:
    # 这里按 alpha 包围盒提取真实主体，而不是直接切固定坐标。
    # 这样能把角色像素团整体搬运到新画布中心，避免“头在上一格、脚在下一格”的盲切问题。
    source_bbox = _mask_bbox(component_image, alpha_threshold)
    if source_bbox is None:
        empty_canvas = Image.new("RGBA", (target_frame_width, target_frame_height), (0, 0, 0, 0))
        return empty_canvas, {
            "empty": True,
            "source_bbox": None,
            "aligned_bbox": None,
            "clipped": False,
            "placement_center_x": None,
            "placement_bottom_y": None,
            "content_hash": hashlib.sha1(empty_canvas.tobytes()).hexdigest(),
            "integrity_pass": False,
        }

    content = component_image.crop(source_bbox)
    if bool(policy.get("pad_source_to_square", True)):
        content = _pad_image_to_aspect_ratio(content, target_aspect_ratio=1.0)
    source_width = max(1, content.width)
    source_height = max(1, content.height)
    scale_factor = max(0.01, float(scale_factor_override))
    scaled_width = max(1, int(round(source_width * scale_factor)))
    scaled_height = max(1, int(round(source_height * scale_factor)))
    scaled = content.resize((scaled_width, scaled_height), resample=Image.Resampling.NEAREST)

    # Center X 对齐：将缩放后的主体包围盒中心放到 32x32 画布的水平中心。
    target_center_x = (target_frame_width - 1) / 2.0
    paste_left = int(round(target_center_x - ((scaled_width - 1) / 2.0)))

    # 脚锚点对齐：让主体最底部像素落到固定基线 y=30，确保站姿脚底稳定。
    anchor_bottom_px = int(policy["anchor_bottom_px"])
    paste_top = anchor_bottom_px - scaled_height + 1

    def _paste_scaled(paste_x: int, paste_y: int) -> tuple[Image.Image, bool]:
        clipped_local = False
        crop_left = max(0, -paste_x)
        crop_top = max(0, -paste_y)
        visible_width = min(scaled_width - crop_left, target_frame_width - max(0, paste_x))
        visible_height = min(scaled_height - crop_top, target_frame_height - max(0, paste_y))
        frame_canvas = Image.new("RGBA", (target_frame_width, target_frame_height), (0, 0, 0, 0))
        if visible_width > 0 and visible_height > 0:
            visible = scaled.crop((crop_left, crop_top, crop_left + visible_width, crop_top + visible_height))
            frame_canvas.paste(visible, (max(0, paste_x), max(0, paste_y)), visible)
            clipped_local = (
                crop_left > 0
                or crop_top > 0
                or (max(0, paste_x) + visible_width) < (paste_x + scaled_width)
                or (max(0, paste_y) + visible_height) < (paste_y + scaled_height)
            )
        else:
            clipped_local = True
        return frame_canvas, clipped_local

    canvas, clipped = _paste_scaled(paste_left, paste_top)
    aligned_bbox = _mask_bbox(canvas, alpha_threshold)
    if aligned_bbox is not None:
        bottom_pixel = aligned_bbox[3] - 1
        safety_shift_y = max(0, bottom_pixel - anchor_bottom_px)
        if safety_shift_y > 0:
            paste_top -= safety_shift_y
            canvas, clipped = _paste_scaled(paste_left, paste_top)
            aligned_bbox = _mask_bbox(canvas, alpha_threshold)
    anchors = _frame_anchor_metrics(
        canvas,
        alpha_threshold=alpha_threshold,
        upper_body_ratio=float(policy["upper_body_ratio"]),
        foot_band_ratio=float(policy["foot_band_ratio"]),
    )
    integrity_pass = bool(
        aligned_bbox is not None
        and not clipped
        and aligned_bbox[0] > 0
        and aligned_bbox[1] > 0
        and aligned_bbox[2] < target_frame_width
        and aligned_bbox[3] < target_frame_height
    )
    return canvas, {
        "empty": False,
        "source_bbox": _bbox_to_payload(source_bbox),
        "aligned_bbox": _bbox_to_payload(aligned_bbox),
        "clipped": bool(clipped),
        "placement_center_x": float(anchors["torso_center_x"]) if anchors else None,
        "placement_bottom_y": float(anchors["bottom_y"]) if anchors else None,
        "aligned_torso_center_x": float(anchors["torso_center_x"]) if anchors else None,
        "aligned_foot_anchor_x": float(anchors["foot_anchor_x"]) if anchors else None,
        "aligned_bottom_y": float(anchors["bottom_y"]) if anchors else None,
        "content_hash": hashlib.sha1(canvas.tobytes()).hexdigest(),
        "integrity_pass": integrity_pass,
    }


def _animation_frame_indices(state: AnimationState) -> list[int]:
    if state.static_frame_index is None:
        return list(range(state.frame_count))
    if state.static_frame_index < 0 or state.static_frame_index >= state.frame_count:
        raise ValueError(
            f"Animation state {state.name} requested static frame {state.static_frame_index}, "
            f"but frame_count is {state.frame_count}."
        )
    return [state.static_frame_index]


def _resolved_animation_frame_indices(state: AnimationState, frame_metrics: list[dict[str, Any]]) -> list[int]:
    available = [index for index, metric in enumerate(frame_metrics) if not metric.get("empty")]
    if state.static_frame_index is not None:
        if state.static_frame_index in available:
            return [state.static_frame_index]
        if available:
            return [available[0]]
        return [state.static_frame_index]
    return available or _animation_frame_indices(state)


def _state_quality_report(
    state: AnimationState,
    frame_metrics: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    non_empty = [metric for metric in frame_metrics if not metric.get("empty")]
    aligned_boxes = [metric.get("aligned_bbox") for metric in non_empty if metric.get("aligned_bbox")]
    center_positions = [box["left"] + (box["width"] / 2.0) for box in aligned_boxes]
    bottom_positions = [box["bottom"] for box in aligned_boxes]
    torso_positions = [float(metric["aligned_torso_center_x"]) for metric in non_empty if metric.get("aligned_torso_center_x") is not None]
    foot_anchor_positions = [float(metric["aligned_foot_anchor_x"]) for metric in non_empty if metric.get("aligned_foot_anchor_x") is not None]
    distinct_hashes = {metric["content_hash"] for metric in frame_metrics if metric.get("content_hash")}
    non_empty_frames = len(non_empty)
    empty_frames = sum(1 for metric in frame_metrics if metric.get("empty"))
    clipped_frames = sum(1 for metric in frame_metrics if metric.get("clipped"))
    integrity_failures = sum(1 for metric in frame_metrics if not metric.get("integrity_pass", False))
    horizontal_jitter = (max(center_positions) - min(center_positions)) if center_positions else 0
    bottom_jitter = (max(bottom_positions) - min(bottom_positions)) if bottom_positions else 0
    torso_jitter = (max(torso_positions) - min(torso_positions)) if torso_positions else 0
    foot_anchor_jitter = (max(foot_anchor_positions) - min(foot_anchor_positions)) if foot_anchor_positions else 0
    frame_height = DEFAULT_TARGET_FRAME_SIZE
    frame_width = DEFAULT_TARGET_FRAME_SIZE
    height_ratios = [box["height"] / float(frame_height) for box in aligned_boxes]
    width_ratios = [box["width"] / float(frame_width) for box in aligned_boxes]
    min_height_ratio = min(height_ratios) if height_ratios else 0.0
    max_height_ratio = max(height_ratios) if height_ratios else 0.0
    max_width_ratio = max(width_ratios) if width_ratios else 0.0
    if state.static_frame_index is not None:
        pass_state = (
            non_empty_frames >= 1
            and clipped_frames == 0
            and integrity_failures == 0
            and min_height_ratio >= float(policy["min_body_height_ratio"]) * 0.9
            and max_width_ratio <= float(policy["max_body_width_ratio"]) + 0.05
        )
    else:
        pass_state = (
            non_empty_frames >= 2
            and clipped_frames == 0
            and integrity_failures == 0
            and horizontal_jitter <= int(policy["max_horizontal_jitter_px"]) + 10
            and bottom_jitter <= int(policy["max_bottom_jitter_px"]) + 10
            and torso_jitter <= int(policy["max_torso_jitter_px"]) + 15
            and foot_anchor_jitter <= int(policy["max_foot_anchor_jitter_px"]) + 15
            and min_height_ratio >= float(policy["min_body_height_ratio"]) * 0.5
            and max_height_ratio <= float(policy["max_body_height_ratio"]) + 0.3
            and max_width_ratio <= float(policy["max_body_width_ratio"]) + 0.3
        )
    return {
        "state": state.name,
        "non_empty_frames": non_empty_frames,
        "empty_frames": empty_frames,
        "clipped_frames": clipped_frames,
        "integrity_failures": integrity_failures,
        "distinct_aligned_frames": len(distinct_hashes),
        "horizontal_jitter_px": float(horizontal_jitter),
        "bottom_jitter_px": int(bottom_jitter),
        "torso_jitter_px": float(torso_jitter),
        "foot_anchor_jitter_px": float(foot_anchor_jitter),
        "min_body_height_ratio": float(min_height_ratio),
        "max_body_height_ratio": float(max_height_ratio),
        "max_body_width_ratio": float(max_width_ratio),
        "static_frame_index": state.static_frame_index,
        "pass": bool(pass_state),
    }


def build_phaser_atlas(
    *,
    input_path: str,
    output_sheet_path: str,
    output_atlas_json_path: str,
    raw_frame_width: int,
    raw_frame_height: int,
    target_frame_width: int,
    target_frame_height: int,
    palette_size: int,
    alpha_threshold: int = DEFAULT_ALPHA_THRESHOLD,
    remove_near_white_background: bool = True,
    near_white_threshold: int = 246,
    neutral_tolerance: int = 12,
    animation_states: list[AnimationState] | None = None,
    alignment_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    states = animation_states or [AnimationState(**entry) for entry in DEFAULT_ANIMATION_STATES]
    source = Image.open(input_path).convert("RGBA")
    if remove_near_white_background:
        source = _strip_near_white_background(
            source,
            near_white_threshold=near_white_threshold,
            neutral_tolerance=neutral_tolerance,
            alpha_threshold=alpha_threshold,
        )
    sheet_columns = max((state.start_col + state.frame_count for state in states), default=0)
    sheet_rows = max((state.row + 1 for state in states), default=0)
    expected_width = sheet_columns * raw_frame_width
    expected_height = sheet_rows * raw_frame_height
    if source.width < expected_width or source.height < expected_height:
        raise ValueError(
            f"Input sheet {input_path} is too small for the requested animation layout: "
            f"expected at least {expected_width}x{expected_height}, got {source.width}x{source.height}."
        )

    policy = _alignment_policy(alignment_policy, target_frame_height)
    target_sheet = Image.new(
        "RGBA",
        (sheet_columns * target_frame_width, sheet_rows * target_frame_height),
        (0, 0, 0, 0),
    )
    extraction_index: dict[tuple[str, int], dict[str, Any]] = {}
    for state in states:
        for frame_index in range(state.frame_count):
            cell_left = (state.start_col + frame_index) * raw_frame_width
            cell_top = state.row * raw_frame_height
            cell_box = (cell_left, cell_top, cell_left + raw_frame_width, cell_top + raw_frame_height)
            extraction_index[(state.name, frame_index)] = _expand_search_window_until_stable(
                source,
                cell_box,
                alpha_threshold=alpha_threshold,
            )

    shared_scale_factor = _shared_scale_factor_from_extractions(
        list(extraction_index.values()),
        target_frame_width=target_frame_width,
        target_frame_height=target_frame_height,
        policy=policy,
    )

    frames: dict[str, Any] = {}
    animations: dict[str, Any] = {}
    quality_frames: list[dict[str, Any]] = []
    quality_states: list[dict[str, Any]] = []

    for state in states:
        quantized_frames: list[Image.Image] = []
        state_metrics: list[dict[str, Any]] = []
        for index in range(state.frame_count):
            extraction = extraction_index[(state.name, index)]
            rendered, render_metrics = _render_component_to_target_frame(
                extraction["component_image"],
                alpha_threshold=alpha_threshold,
                target_frame_width=target_frame_width,
                target_frame_height=target_frame_height,
                policy=policy,
                scale_factor_override=shared_scale_factor,
            )
            quantized = _quantize_frame(
                rendered,
                palette_size=palette_size,
                alpha_threshold=alpha_threshold,
                remove_near_white_background=False,
                near_white_threshold=near_white_threshold,
                neutral_tolerance=neutral_tolerance,
            )
            quantized_frames.append(quantized)
            out_x = (state.start_col + index) * target_frame_width
            out_y = state.row * target_frame_height
            target_sheet.paste(quantized, (out_x, out_y), quantized)
            frame_name = _frame_name(state.name, index)
            frame_payload = {
                "frame": {"x": out_x, "y": out_y, "w": target_frame_width, "h": target_frame_height},
                "rotated": False,
                "trimmed": False,
                "spriteSourceSize": {"x": 0, "y": 0, "w": target_frame_width, "h": target_frame_height},
                "sourceSize": {"w": target_frame_width, "h": target_frame_height},
            }
            if render_metrics.get("aligned_bbox"):
                frame_payload["alignment"] = {
                    "bbox": render_metrics["aligned_bbox"],
                    "clipped": render_metrics["clipped"],
                    "placement_center_x": render_metrics["placement_center_x"],
                    "placement_bottom_y": render_metrics["placement_bottom_y"],
                }
            frames[frame_name] = frame_payload
            state_metric = {
                "state": state.name,
                "frame_index": index,
                "search_window": extraction["search_window"],
                "expanded_search_window": extraction["expanded_search_window"],
                "selected_component_bbox": extraction["selected_component_bbox"],
                "component_area_px": extraction["component_area_px"],
                "touches_search_edge": extraction["touches_search_edge"],
                "component_backend": extraction["component_backend"],
                "component_crop_bbox": extraction["component_crop_bbox"],
                "shared_scale_factor": float(shared_scale_factor),
                **render_metrics,
            }
            state_metrics.append(state_metric)
            quality_frames.append(state_metric)

        animation_frame_names = [_frame_name(state.name, frame_index) for frame_index in _resolved_animation_frame_indices(state, state_metrics)]
        state_quality = _state_quality_report(state, state_metrics, policy)
        quality_states.append(state_quality)
        animations[state.name] = {
            "frames": animation_frame_names,
            "frameRate": state.frame_rate,
            "repeat": 0 if state.static_frame_index is not None else state.repeat,
            "static": state.static_frame_index is not None,
            "defaultFrame": animation_frame_names[0] if animation_frame_names else "",
        }

    total_empty_frames = sum(int(state["empty_frames"]) for state in quality_states)
    total_clipped_frames = sum(int(state["clipped_frames"]) for state in quality_states)
    failing_states = [state["state"] for state in quality_states if not state["pass"]]

    target_sheet.save(output_sheet_path)
    atlas = {
        "frames": frames,
        "meta": {
            "app": "Agora_UI",
            "version": "1.2",
            "image": Path(output_sheet_path).name,
            "format": "RGBA8888",
            "size": {"w": target_sheet.width, "h": target_sheet.height},
            "scale": "1",
            "frame_size": {"w": target_frame_width, "h": target_frame_height},
            "raw_frame_size": {"w": raw_frame_width, "h": raw_frame_height},
            "palette_size": palette_size,
            "background_processing": {
                "remove_near_white_background": remove_near_white_background,
                "near_white_threshold": near_white_threshold,
                "neutral_tolerance": neutral_tolerance,
            },
            "alignment_policy": policy,
            "shared_scale_factor": float(shared_scale_factor),
            "quality_summary": {
                "pass": not failing_states,
                "total_empty_frames": total_empty_frames,
                "total_clipped_frames": total_clipped_frames,
                "failing_states": failing_states,
            },
            "quality_report": {
                "states": quality_states,
                "frames": quality_frames,
            },
        },
        "animations": animations,
    }
    Path(output_atlas_json_path).write_text(json.dumps(atlas, indent=2), encoding="utf-8")
    return atlas


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to the raw character sheet.")
    parser.add_argument("--output-sheet", required=True, help="Path to the processed atlas PNG.")
    parser.add_argument("--output-json", required=True, help="Path to the Phaser atlas JSON.")
    parser.add_argument("--raw-frame-width", type=int, default=128)
    parser.add_argument("--raw-frame-height", type=int, default=128)
    parser.add_argument("--target-frame-width", type=int, default=DEFAULT_TARGET_FRAME_SIZE)
    parser.add_argument("--target-frame-height", type=int, default=DEFAULT_TARGET_FRAME_SIZE)
    parser.add_argument("--palette-size", type=int, default=24)
    parser.add_argument("--alpha-threshold", type=int, default=DEFAULT_ALPHA_THRESHOLD)
    parser.add_argument("--near-white-threshold", type=int, default=246)
    parser.add_argument("--neutral-tolerance", type=int, default=12)
    parser.add_argument(
        "--keep-white-background",
        action="store_true",
        help="Do not key out near-white opaque backgrounds before quantization.",
    )
    parser.add_argument(
        "--animation-spec",
        help="Optional JSON file describing rows, frame counts, and animation metadata.",
    )
    parser.add_argument(
        "--alignment-policy",
        help="Optional JSON file describing frame alignment and quality thresholds.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    Path(args.output_sheet).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    alignment_policy = None
    if args.alignment_policy:
        alignment_policy = json.loads(Path(args.alignment_policy).read_text(encoding="utf-8"))
    build_phaser_atlas(
        input_path=args.input,
        output_sheet_path=args.output_sheet,
        output_atlas_json_path=args.output_json,
        raw_frame_width=args.raw_frame_width,
        raw_frame_height=args.raw_frame_height,
        target_frame_width=args.target_frame_width,
        target_frame_height=args.target_frame_height,
        palette_size=args.palette_size,
        alpha_threshold=args.alpha_threshold,
        remove_near_white_background=not args.keep_white_background,
        near_white_threshold=args.near_white_threshold,
        neutral_tolerance=args.neutral_tolerance,
        animation_states=_load_animation_states(args.animation_spec),
        alignment_policy=alignment_policy,
    )


if __name__ == "__main__":
    main()
