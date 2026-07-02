from __future__ import annotations

from typing import Any

try:
    import cv2  # type: ignore
except ImportError:
    cv2 = None
import numpy as np
from PIL import Image, ImageOps


def _strip_dominant_border_background(image: Image.Image, *, tolerance: int = 18) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = np.array(rgba, dtype=np.uint8)
    height, width = pixels.shape[:2]
    border = np.concatenate(
        (
            pixels[0, :, :3],
            pixels[-1, :, :3],
            pixels[:, 0, :3],
            pixels[:, -1, :3],
        ),
        axis=0,
    )
    if border.size == 0:
        return rgba
    bins = {}
    for red, green, blue in border:
        key = (int(red) // 16, int(green) // 16, int(blue) // 16)
        bins[key] = bins.get(key, 0) + 1
    dominant_bins = {key for key, _count in sorted(bins.items(), key=lambda item: item[1], reverse=True)[:4]}
    if not dominant_bins:
        return rgba

    def is_background(rgb: np.ndarray) -> bool:
        key = (int(rgb[0]) // 16, int(rgb[1]) // 16, int(rgb[2]) // 16)
        if key not in dominant_bins:
            channel_min = int(min(rgb[0], rgb[1], rgb[2]))
            channel_max = int(max(rgb[0], rgb[1], rgb[2]))
            neutral_mid = 72 <= int((int(rgb[0]) + int(rgb[1]) + int(rgb[2])) / 3) <= 248
            return (channel_max - channel_min) <= (tolerance + 6) and neutral_mid
        return True

    visited = np.zeros((height, width), dtype=bool)
    queue: list[tuple[int, int]] = [(x, 0) for x in range(width)]
    queue += [(x, height - 1) for x in range(width)]
    queue += [(0, y) for y in range(height)]
    queue += [(width - 1, y) for y in range(height)]
    while queue:
        x, y = queue.pop()
        if x < 0 or y < 0 or x >= width or y >= height or visited[y, x]:
            continue
        visited[y, x] = True
        if not is_background(pixels[y, x, :3]):
            continue
        pixels[y, x, 3] = 0
        queue.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
    return Image.fromarray(pixels, mode="RGBA")


def _alpha_components(mask: np.ndarray, *, min_area: int) -> list[dict[str, Any]]:
    if cv2 is None:
        return []
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    closed_mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
    labels_count, labels, stats, centroids = cv2.connectedComponentsWithStats(closed_mask, 8)
    
    components: list[dict[str, Any]] = []
    for label in range(1, labels_count):
        component_mask = (labels == label)
        original_mask_overlap = component_mask & mask.astype(bool)
        area = int(np.sum(original_mask_overlap))
        if area < min_area:
            continue
            
        rows, cols = np.where(original_mask_overlap)
        if len(rows) == 0:
            continue
            
        components.append(
            {
                "bbox": (int(np.min(cols)), int(np.min(rows)), int(np.max(cols)) + 1, int(np.max(rows)) + 1),
                "center_x": float(np.mean(cols)),
                "center_y": float(np.mean(rows)),
                "area": area,
            }
        )
    
    components.sort(key=lambda entry: entry["area"], reverse=True)
    return components


def _cluster_component_centers(values: list[float], *, max_gap: float) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    clusters: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if abs(value - clusters[-1][-1]) <= max_gap:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [sum(cluster) / float(len(cluster)) for cluster in clusters]


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
