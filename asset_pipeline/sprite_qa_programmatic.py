from __future__ import annotations
import base64
import json
import math
from pathlib import Path
from typing import Any
from PIL import Image, ImageChops, ImageStat
from agora_ui.vertex_json_client import VertexJsonClient
from asset_pipeline.process_sprite import AnimationState
from .sprite_qa_utils import *
from collections import deque

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


def _preprocess_for_qa(image: Image.Image, processing: dict[str, Any]) -> Image.Image:
    rgba = image.convert("RGBA")
    if processing.get("remove_near_white_background", True):
        rgba = _strip_near_white_background(
            rgba,
            near_white_threshold=int(processing["near_white_threshold"]),
            neutral_tolerance=int(processing["neutral_tolerance"]),
            alpha_threshold=int(processing["alpha_threshold"]),
        )
    return rgba


def _mask_bbox(image: Image.Image, alpha_threshold: int) -> tuple[int, int, int, int] | None:
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value >= alpha_threshold else 0)
    return mask.getbbox()


def final_atlas_transparency_qa(
    *,
    image_path: str,
    processing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    processing_config = _merged_processing(processing)
    alpha_threshold = int(processing_config["alpha_threshold"])
    near_white_threshold = int(processing_config["near_white_threshold"])
    neutral_tolerance = int(processing_config["neutral_tolerance"])
    min_transparent_ratio = float(processing_config["qa_atlas_min_transparent_ratio"])
    max_near_white_opaque_ratio = float(processing_config["qa_atlas_max_near_white_opaque_ratio"])
    max_edge_opaque_ratio = float(processing_config["qa_atlas_max_edge_opaque_ratio"])

    image = Image.open(image_path).convert("RGBA")
    width, height = image.size
    pixels = list(image.getdata())
    total_pixels = max(1, width * height)
    transparent_pixels = sum(1 for _, _, _, alpha in pixels if alpha < alpha_threshold)
    opaque_pixels = total_pixels - transparent_pixels
    near_white_opaque_pixels = 0
    for red, green, blue, alpha in pixels:
        if alpha < alpha_threshold:
            continue
        channel_min = min(red, green, blue)
        channel_max = max(red, green, blue)
        if (
            red >= near_white_threshold
            and green >= near_white_threshold
            and blue >= near_white_threshold
            and (channel_max - channel_min) <= neutral_tolerance
        ):
            near_white_opaque_pixels += 1

    edge_indices: set[int] = set()
    for x in range(width):
        edge_indices.add(x)
        edge_indices.add((height - 1) * width + x)
    for y in range(height):
        edge_indices.add(y * width)
        edge_indices.add(y * width + width - 1)
    edge_pixels = max(1, len(edge_indices))
    edge_opaque_pixels = sum(1 for index in edge_indices if pixels[index][3] >= alpha_threshold)
    corner_indices = {
        0,
        max(0, width - 1),
        max(0, (height - 1) * width),
        max(0, (height * width) - 1),
    }
    opaque_corners = sum(1 for index in corner_indices if index < len(pixels) and pixels[index][3] >= alpha_threshold)

    transparent_ratio = transparent_pixels / float(total_pixels)
    near_white_opaque_ratio = near_white_opaque_pixels / float(total_pixels)
    edge_opaque_ratio = edge_opaque_pixels / float(edge_pixels)
    failures: list[str] = []
    if transparent_ratio < min_transparent_ratio:
        failures.append(f"Atlas transparent ratio {transparent_ratio:.3f} is below {min_transparent_ratio:.3f}.")
    if near_white_opaque_ratio > max_near_white_opaque_ratio:
        failures.append(
            f"Atlas near-white opaque ratio {near_white_opaque_ratio:.3f} exceeds {max_near_white_opaque_ratio:.3f}."
        )
    if edge_opaque_ratio > max_edge_opaque_ratio:
        failures.append(f"Atlas edge opaque ratio {edge_opaque_ratio:.3f} exceeds {max_edge_opaque_ratio:.3f}.")
    if opaque_corners:
        failures.append(f"Atlas has {opaque_corners} opaque corner pixel(s).")

    return {
        "pass": not failures,
        "image_path": str(image_path),
        "transparent_ratio": float(round(transparent_ratio, 4)),
        "opaque_ratio": float(round(opaque_pixels / float(total_pixels), 4)),
        "near_white_opaque_ratio": float(round(near_white_opaque_ratio, 4)),
        "edge_opaque_ratio": float(round(edge_opaque_ratio, 4)),
        "opaque_corners": int(opaque_corners),
        "minimum_transparent_ratio": float(min_transparent_ratio),
        "maximum_near_white_opaque_ratio": float(max_near_white_opaque_ratio),
        "maximum_edge_opaque_ratio": float(max_edge_opaque_ratio),
        "failures": failures,
    }


def _bbox_to_payload(bounds: tuple[int, int, int, int] | None) -> dict[str, int] | None:
    if bounds is None:
        return None
    left, top, right, bottom = bounds
    return {
        "left": int(left),
        "top": int(top),
        "right": int(right - 1),
        "bottom": int(bottom - 1),
        "width": int(right - left),
        "height": int(bottom - top),
    }


def _alpha_component_summary(frame: Image.Image, alpha_threshold: int, major_min_ratio: float) -> dict[str, Any]:
    rgba = frame.convert("RGBA")
    width, height = rgba.size
    alpha = [pixel[3] for pixel in rgba.getdata()]
    visited = [False] * (width * height)
    component_sizes: list[int] = []
    opaque_pixels = 0
    for index, value in enumerate(alpha):
        if value < alpha_threshold or visited[index]:
            continue
        queue: deque[int] = deque([index])
        visited[index] = True
        size = 0
        while queue:
            current = queue.popleft()
            size += 1
            x = current % width
            y = current // width
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if nx < 0 or ny < 0 or nx >= width or ny >= height:
                    continue
                neighbor = ny * width + nx
                if visited[neighbor] or alpha[neighbor] < alpha_threshold:
                    continue
                visited[neighbor] = True
                queue.append(neighbor)
        component_sizes.append(size)
        opaque_pixels += size
    component_sizes.sort(reverse=True)
    largest_ratio = (component_sizes[0] / float(opaque_pixels)) if opaque_pixels and component_sizes else 0.0
    major_component_count = sum(1 for size in component_sizes if opaque_pixels and (size / float(opaque_pixels)) >= major_min_ratio)
    return {
        "component_count": len(component_sizes),
        "major_component_count": int(major_component_count),
        "largest_component_ratio": float(round(largest_ratio, 4)),
        "component_sizes": component_sizes[:6],
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
    foot_anchor_x = (sum(foot_xs) / float(len(foot_xs))) if foot_xs else (left + (width / 2.0))
    return {
        "torso_center_x": float(torso_center_x),
        "foot_anchor_x": float(foot_anchor_x),
        "bottom_y": float(bottom_y),
    }


def _frame_requirement(state: AnimationState) -> int:
    return 1 if state.static_frame_index is not None else state.frame_count


def _frame_label(state: AnimationState, frame_index: int) -> str:
    return f"{state.name}[{frame_index}]"


def strict_programmatic_qa(
    *,
    image_path: str,
    sheet_layout: dict[str, Any] | None = None,
    processing: dict[str, Any] | None = None,
    animation_states: list[AnimationState] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    states = _normalize_animation_states(animation_states)
    layout = _merged_sheet_layout(sheet_layout, states)
    processing_config = _merged_processing(processing)
    alpha_threshold = int(processing_config["alpha_threshold"])
    raw_frame_width = int(layout["raw_frame_width"])
    raw_frame_height = int(layout["raw_frame_height"])
    columns = int(layout["columns"])
    rows = int(layout["rows"])
    target_frame_width = max(1, int(processing_config["target_frame_width"]))
    target_frame_height = max(1, int(processing_config["target_frame_height"]))
    policy = dict(processing_config["alignment_policy"])

    source = Image.open(image_path).convert("RGBA")
    processed = _preprocess_for_qa(source, processing_config)
    actual_size = {"width": int(source.width), "height": int(source.height)}
    expected_size = {"width": columns * raw_frame_width, "height": rows * raw_frame_height}
    size_pass = actual_size == expected_size

    layout_failures: list[str] = []
    if not states:
        layout_failures.append("No animation states were declared.")
    for state in states:
        if state.frame_count <= 0:
            layout_failures.append(f"{state.name}: frame_count must be positive.")
        if state.row < 0 or state.row >= rows:
            layout_failures.append(f"{state.name}: row {state.row} is outside the declared {rows} rows.")
        if state.start_col < 0 or (state.start_col + state.frame_count) > columns:
            layout_failures.append(
                f"{state.name}: columns {state.start_col}..{state.start_col + state.frame_count - 1} exceed the declared {columns} columns."
            )
        if state.static_frame_index is not None and not (0 <= state.static_frame_index < state.frame_count):
            layout_failures.append(
                f"{state.name}: static_frame_index {state.static_frame_index} is outside frame_count {state.frame_count}."
            )
    layout_pass = not layout_failures

    total_pixels = max(1, source.width * source.height)
    source_transparent_pixels = sum(1 for _, _, _, alpha in source.getdata() if alpha < alpha_threshold)
    source_transparent_ratio = source_transparent_pixels / float(total_pixels)
    transparent_pixels = sum(1 for _, _, _, alpha in processed.getdata() if alpha < alpha_threshold)
    transparent_ratio = transparent_pixels / float(total_pixels)
    min_transparent_ratio = float(processing_config["qa_min_transparent_ratio"])
    background_pass = (source_transparent_ratio >= min_transparent_ratio) or (transparent_ratio >= min_transparent_ratio)

    frame_reports: list[dict[str, Any]] = []
    state_reports: list[dict[str, Any]] = []
    frame_content_failures: list[str] = []
    frame_bounds_failures: list[str] = []
    consistency_failures: list[str] = []
    component_failures: list[str] = []

    horizontal_scale = raw_frame_width / float(target_frame_width)
    vertical_scale = raw_frame_height / float(target_frame_height)
    max_horizontal_jitter_px = max(1.0, float(policy["max_horizontal_jitter_px"]) * horizontal_scale)
    max_bottom_jitter_px = max(1.0, float(policy["max_bottom_jitter_px"]) * vertical_scale)
    min_body_height_ratio = float(policy["min_body_height_ratio"]) * 0.4
    max_body_height_ratio = min(1.0, float(policy["max_body_height_ratio"]) + 0.08)
    max_body_width_ratio = min(1.0, float(policy["max_body_width_ratio"]) + 0.08)
    max_torso_jitter_px = max(1.0, float(policy.get("max_torso_jitter_px", 3)) * horizontal_scale)
    max_foot_anchor_jitter_px = max(1.0, float(policy.get("max_foot_anchor_jitter_px", 4)) * horizontal_scale * 5.0)
    upper_body_ratio = float(policy.get("upper_body_ratio", 0.58))
    foot_band_ratio = float(policy.get("foot_band_ratio", 0.18))
    min_largest_component_ratio = float(processing_config["qa_component_min_largest_ratio"])
    major_component_min_ratio = float(processing_config["qa_component_major_min_ratio"])
    max_major_components = int(processing_config["qa_component_max_major_components"])

    for state in states:
        state_frame_reports: list[dict[str, Any]] = []
        centers: list[float] = []
        bottoms: list[int] = []
        torso_centers: list[float] = []
        foot_anchor_positions: list[float] = []
        height_ratios: list[float] = []
        width_ratios: list[float] = []
        non_empty_frame_indices: list[int] = []
        clipped_frame_indices: list[int] = []
        border_contact_frame_indices: list[int] = []
        disconnected_frame_indices: list[int] = []

        for frame_index in range(state.frame_count):
            left = (state.start_col + frame_index) * raw_frame_width
            top = state.row * raw_frame_height
            right = left + raw_frame_width
            bottom = top + raw_frame_height
            in_bounds = left >= 0 and top >= 0 and right <= source.width and bottom <= source.height

            frame_payload: dict[str, Any] = {
                "state": state.name,
                "frame_index": frame_index,
                "frame_label": _frame_label(state, frame_index),
                "bounds": {"left": left, "top": top, "right": right, "bottom": bottom},
                "in_bounds": bool(in_bounds),
                "empty": True,
                "clipped": False,
                "bbox": None,
            }
            if not in_bounds:
                frame_bounds_failures.append(f"{state.name}[{frame_index}] lies outside the sheet bounds.")
                frame_payload["failure"] = "frame_out_of_bounds"
                state_frame_reports.append(frame_payload)
                frame_reports.append(frame_payload)
                continue

            frame = processed.crop((left, top, right, bottom))
            bbox = _bbox_to_payload(_mask_bbox(frame, alpha_threshold))
            frame_payload["bbox"] = bbox
            frame_payload["empty"] = bbox is None
            if bbox is None:
                frame_content_failures.append(f"{state.name}[{frame_index}] is empty after background cleanup.")
            else:
                non_empty_frame_indices.append(frame_index)
                centers.append(bbox["left"] + (bbox["width"] / 2.0))
                bottoms.append(int(bbox["bottom"]))
                height_ratios.append(bbox["height"] / float(raw_frame_height))
                width_ratios.append(bbox["width"] / float(raw_frame_width))
                anchor_metrics = _frame_anchor_metrics(
                    frame,
                    alpha_threshold=alpha_threshold,
                    upper_body_ratio=upper_body_ratio,
                    foot_band_ratio=foot_band_ratio,
                )
                frame_payload["anchor_metrics"] = anchor_metrics
                if anchor_metrics:
                    torso_centers.append(float(anchor_metrics["torso_center_x"]))
                    foot_anchor_positions.append(float(anchor_metrics["foot_anchor_x"]))
                component_summary = _alpha_component_summary(frame, alpha_threshold, major_component_min_ratio)
                frame_payload["component_integrity"] = component_summary
                disconnected = (
                    int(component_summary["major_component_count"]) > max_major_components
                    and float(component_summary["largest_component_ratio"]) < min_largest_component_ratio
                )
                if disconnected:
                    disconnected_frame_indices.append(frame_index)
                    component_failures.append(
                        f"{state.name}[{frame_index}] has disconnected body components "
                        f"(major={component_summary['major_component_count']}, largest={component_summary['largest_component_ratio']:.3f})."
                    )
                border_contact = (
                    bbox["left"] <= 0
                    or bbox["top"] <= 0
                    or bbox["right"] >= (raw_frame_width - 1)
                    or bbox["bottom"] >= (raw_frame_height - 1)
                )
                frame_payload["border_contact"] = bool(border_contact)
                frame_payload["clipped"] = False
                if border_contact:
                    border_contact_frame_indices.append(frame_index)
            state_frame_reports.append(frame_payload)
            frame_reports.append(frame_payload)

        non_empty_frames = len(non_empty_frame_indices)
        required_non_empty_frames = _frame_requirement(state)
        if state.static_frame_index is not None and state.static_frame_index not in non_empty_frame_indices:
            frame_content_failures.append(
                f"{state.name} requires static frame {state.static_frame_index}, but that frame is empty."
            )

        horizontal_jitter = (max(centers) - min(centers)) if centers else 0.0
        bottom_jitter = (max(bottoms) - min(bottoms)) if bottoms else 0
        torso_jitter = (max(torso_centers) - min(torso_centers)) if torso_centers else 0.0
        foot_anchor_jitter = (max(foot_anchor_positions) - min(foot_anchor_positions)) if foot_anchor_positions else 0.0
        min_height_ratio = min(height_ratios) if height_ratios else 0.0
        max_height_ratio = max(height_ratios) if height_ratios else 0.0
        max_width_ratio_state = max(width_ratios) if width_ratios else 0.0
        state_pass = (
            non_empty_frames >= required_non_empty_frames
            and not clipped_frame_indices
            and min_height_ratio >= min_body_height_ratio
            and max_height_ratio <= max_body_height_ratio
            and max_width_ratio_state <= max_body_width_ratio
            and torso_jitter <= max_torso_jitter_px
            and foot_anchor_jitter <= max_foot_anchor_jitter_px
        )
        if not state_pass:
            reasons: list[str] = []
            if non_empty_frames < required_non_empty_frames:
                reasons.append(f"non-empty frames {non_empty_frames}/{required_non_empty_frames}")
            if clipped_frame_indices:
                reasons.append(f"clipped frames {clipped_frame_indices}")
            if min_height_ratio < min_body_height_ratio:
                reasons.append(f"min body height ratio {min_height_ratio:.3f} < {min_body_height_ratio:.3f}")
            if max_height_ratio > max_body_height_ratio:
                reasons.append(f"max body height ratio {max_height_ratio:.3f} > {max_body_height_ratio:.3f}")
            if max_width_ratio_state > max_body_width_ratio:
                reasons.append(f"max body width ratio {max_width_ratio_state:.3f} > {max_body_width_ratio:.3f}")
            if torso_jitter > max_torso_jitter_px:
                reasons.append(f"torso jitter {torso_jitter:.3f} > {max_torso_jitter_px:.3f}")
            if foot_anchor_jitter > max_foot_anchor_jitter_px:
                reasons.append(f"foot anchor jitter {foot_anchor_jitter:.3f} > {max_foot_anchor_jitter_px:.3f}")
            consistency_failures.append(f"{state.name}: {'; '.join(reasons)}")

        state_reports.append(
            {
                "state": state.name,
                "frame_count": state.frame_count,
                "required_non_empty_frames": required_non_empty_frames,
                "non_empty_frames": non_empty_frames,
                "empty_frames": max(0, state.frame_count - non_empty_frames),
                "clipped_frames": len(clipped_frame_indices),
                "border_contact_frames": border_contact_frame_indices,
                "disconnected_frames": disconnected_frame_indices,
                "static_frame_index": state.static_frame_index,
                "horizontal_jitter_px": float(horizontal_jitter),
                "bottom_jitter_px": int(bottom_jitter),
                "torso_jitter_px": float(torso_jitter),
                "foot_anchor_jitter_px": float(foot_anchor_jitter),
                "min_body_height_ratio": float(min_height_ratio),
                "max_body_height_ratio": float(max_height_ratio),
                "max_body_width_ratio": float(max_width_ratio_state),
                "pass": bool(state_pass),
            }
        )

    checks = {
        "size": {
            "pass": bool(size_pass),
            "expected": expected_size,
            "actual": actual_size,
            "reason": (
                "Sheet size matches the configured grid."
                if size_pass
                else f"Expected {expected_size['width']}x{expected_size['height']}, got {actual_size['width']}x{actual_size['height']}."
            ),
        },
        "layout": {
            "pass": bool(layout_pass),
            "failures": layout_failures,
        },
        "background_transparency": {
            "pass": bool(background_pass),
            "source_transparent_ratio": float(round(source_transparent_ratio, 4)),
            "processed_transparent_ratio": float(round(transparent_ratio, 4)),
            "minimum_ratio": float(min_transparent_ratio),
        },
        "frame_content": {
            "pass": not frame_content_failures,
            "failures": frame_content_failures,
        },
        "frame_bounds": {
            "pass": not frame_bounds_failures,
            "failures": frame_bounds_failures,
        },
        "consistency": {
            "pass": not consistency_failures,
            "failures": consistency_failures,
        },
        "component_integrity": {
            "pass": not component_failures,
            "failures": component_failures,
            "minimum_largest_component_ratio": float(min_largest_component_ratio),
            "major_component_min_ratio": float(major_component_min_ratio),
            "maximum_major_components": int(max_major_components),
        },
    }
    failures = [
        entry
        for bucket in (
            ([] if size_pass else [checks["size"]["reason"]]),
            layout_failures,
            ([] if background_pass else [f"Source transparent ratio {source_transparent_ratio:.3f} and processed transparent ratio {transparent_ratio:.3f} are below {min_transparent_ratio:.3f}."]),
            frame_content_failures,
            frame_bounds_failures,
            consistency_failures,
            component_failures,
        )
        for entry in bucket
    ]
    pass_qa = all(bool(value["pass"]) for value in checks.values())

    return {
        "pass_qa": bool(pass_qa),
        "expected_sheet_size": expected_size,
        "actual_sheet_size": actual_size,
        "checks": checks,
        "state_reports": state_reports,
        "frame_reports": frame_reports,
        "failures": failures,
    }

