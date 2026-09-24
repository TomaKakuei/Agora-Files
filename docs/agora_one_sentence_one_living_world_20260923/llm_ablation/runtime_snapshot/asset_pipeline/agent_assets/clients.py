from __future__ import annotations

import base64
import colorsys
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter, deque
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image
import requests


def _locate_package_root(config_path: Path) -> Path:
    current = config_path.resolve()
    for candidate in [current.parent, *current.parents]:
        if (candidate / "agora_ui").is_dir() and (candidate / "asset_pipeline").is_dir():
            return candidate
    raise RuntimeError(f"Could not locate Agora_UI package root from config path: {config_path}")


def _load_runtime_clients():
    package_root = _locate_package_root(Path(__file__).resolve())
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from agora_ui.run_interaction_simulation import VertexJsonClient, VertexSDKImageClient
    return VertexJsonClient, VertexSDKImageClient


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _endpoint_port(endpoint: str) -> int | None:
    parsed = urlparse(str(endpoint or "").strip())
    if parsed.port is not None:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    return None


def _append_timing_event(
    output_dir: Path,
    *,
    stage: str,
    status: str,
    started_at: str,
    duration_seconds: float,
    endpoint: str = "",
    adapter: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    payload = {
        "stage": stage,
        "status": status,
        "started_at": started_at,
        "duration_seconds": round(float(duration_seconds), 3),
        "endpoint": str(endpoint or "").strip(),
        "port": _endpoint_port(endpoint),
        "adapter": str(adapter or "").strip(),
        "details": details or {},
    }
    path = output_dir / "timing_trace.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _normalize_vertex_model_name(model_name: str) -> str:
    text = str(model_name).strip()
    if text == "gemini-3.1-flash-lite-preview":
        return "gemini-3.1-flash-lite"
    return text


def _normalize_world_config_models(world_config: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(world_config))
    runtime = normalized.get("runtime")
    if isinstance(runtime, dict) and runtime.get("vertex_model"):
        runtime["vertex_model"] = _normalize_vertex_model_name(runtime["vertex_model"])
    vertex_api = normalized.get("vertex_api")
    if isinstance(vertex_api, dict):
        if vertex_api.get("model"):
            vertex_api["model"] = _normalize_vertex_model_name(vertex_api["model"])
        if vertex_api.get("fallback_model"):
            vertex_api["fallback_model"] = _normalize_vertex_model_name(vertex_api["fallback_model"])
        stages = vertex_api.get("stages")
        if isinstance(stages, dict):
            for stage_config in stages.values():
                if isinstance(stage_config, dict) and stage_config.get("model"):
                    stage_config["model"] = _normalize_vertex_model_name(stage_config["model"])
    image_generation = normalized.get("image_generation")
    if isinstance(image_generation, dict) and image_generation.get("model"):
        image_generation["model"] = _normalize_vertex_model_name(image_generation["model"])
    return normalized


def _decode_base64_image(raw_value: str) -> Image.Image:
    binary = base64.b64decode(raw_value)
    return Image.open(BytesIO(binary)).convert("RGBA")


def _request_gemini_prompt(
    *,
    world_config: dict[str, Any],
    prompt_bundle: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    started_perf = time.perf_counter()
    endpoint = str(world_config.get("vertex_api", {}).get("endpoint_base", "")).strip()
    event_status = "error"
    VertexJsonClient, _ = _load_runtime_clients()
    client = VertexJsonClient(world_config)
    schema = {"prompt_text": "string, one polished visual prompt suitable for creating a concept illustration"}
    try:
        generated = client.generate_compact_json(
            system_instruction="You generate one clean art prompt as strict JSON.",
            prompt=(
                "Write one polished visual prompt for a character concept illustration. "
                "Keep it concrete, descriptive, and useful for a downstream image generator.\n"
                f"context: {json.dumps(prompt_bundle, ensure_ascii=False)}"
            ),
            schema=schema,
            stage="image_prompt_generation",
        )
        _write_json(output_dir / "concept_response.json", generated)
        extracted_text = str(generated.get("prompt_text", "")).strip() or prompt_bundle["concept_prompt"]
        (output_dir / "concept_response.txt").write_text(extracted_text.strip() + "\n", encoding="utf-8")
        event_status = "ok"
        return {"status": "ok", "text": extracted_text.strip(), "response_path": str(output_dir / "concept_response.json")}
    finally:
        _append_timing_event(
            output_dir,
            stage="concept_prompt_generation",
            status=event_status,
            started_at=started_at,
            duration_seconds=time.perf_counter() - started_perf,
            endpoint=endpoint,
            adapter="gemini_image_prompt",
        )


def _request_gemini_reference_image(
    *,
    world_config: dict[str, Any],
    prompt_bundle: dict[str, Any],
    output_dir: Path,
    output_image_path: Path,
) -> dict[str, Any]:
    raise RuntimeError(
        "Gemini/Vertex reference image generation is disabled; agent art must use the FLUX sprite pipeline."
    )


def _request_sd_sheet(
    *,
    config: dict[str, Any],
    prompt_bundle: dict[str, Any],
    output_dir: Path,
    raw_sheet_path: Path,
) -> dict[str, Any]:
    endpoint = config.get("endpoint", "")
    if not endpoint:
        return {"status": "skipped", "reason": "Missing Stable Diffusion endpoint."}
    started_at = datetime.now(timezone.utc).isoformat()
    started_perf = time.perf_counter()
    event_status = "error"
    payload = {
        "prompt": prompt_bundle["sprite_prompt"],
        "negative_prompt": prompt_bundle["negative_prompt"],
        "width": config.get("width", 512),
        "height": config.get("height", 512),
        "steps": config.get("steps", 28),
        "cfg_scale": config.get("cfg_scale", 7.0),
        "sampler_name": config.get("sampler_name", "DPM++ 2M Karras"),
    }
    lora_tag = config.get("lora_tag", "")
    if lora_tag:
        payload["prompt"] = f"{lora_tag}, {payload['prompt']}"
    try:
        response = requests.post(endpoint, json=payload, timeout=config.get("timeout_seconds", 300))
        response.raise_for_status()
        result = response.json()
        _write_json(output_dir / "sprite_response.json", result)
        images = result.get("images", [])
        if not images:
            raise RuntimeError("Stable Diffusion response did not contain images.")
        image = _decode_base64_image(images[0])
        image.save(raw_sheet_path)
        event_status = "ok"
        return {"status": "ok", "response_path": str(output_dir / "sprite_response.json")}
    finally:
        _append_timing_event(
            output_dir,
            stage="sprite_sheet_generation",
            status=event_status,
            started_at=started_at,
            duration_seconds=time.perf_counter() - started_perf,
            endpoint=str(endpoint),
            adapter="sd_webui_txt2img",
        )


def _compact_prompt_phrase(value: Any, *, max_words: int) -> str:
    words = re.findall(r"[A-Za-z0-9#][A-Za-z0-9#'_-]*", str(value or ""))
    return " ".join(words[:max_words])


def _plain_color_name(value: str) -> str:
    red, green, blue = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    hue, saturation, brightness = colorsys.rgb_to_hsv(red, green, blue)
    if saturation < 0.14:
        name = "gray"
    else:
        names = ("red", "orange", "gold", "lime", "green", "emerald", "teal", "cyan", "blue", "violet", "magenta", "crimson")
        name = names[round(hue * len(names)) % len(names)]
    return name


def _flux_sprite_prompt(
    *,
    prompt_bundle: dict[str, Any],
    direction: str,
    readable_palette: str,
) -> str:
    """Keep every production-critical cue inside FLUX's short text window."""
    sprite_prompt = str(prompt_bundle.get("sprite_prompt", ""))
    role_match = re.search(r"Role identity:\s*([^.]*)", sprite_prompt, re.IGNORECASE)
    wardrobe_match = re.search(r"Character wears\s*([^,.;]*)", sprite_prompt, re.IGNORECASE)
    lowered_prompt = sprite_prompt.lower()
    if "respirator" in lowered_prompt:
        headgear = "same hooded respirator"
    elif "helmet" in lowered_prompt:
        headgear = "same helmet"
    elif "hood" in lowered_prompt:
        headgear = "same hood"
    elif "hat" in lowered_prompt:
        headgear = "same hat"
    else:
        headgear = "same face and hair"

    role = _compact_prompt_phrase(role_match.group(1) if role_match else "world specialist", max_words=5)
    wardrobe = _compact_prompt_phrase(
        wardrobe_match.group(1) if wardrobe_match else "distinctive role clothing",
        max_words=5,
    )
    palette = _compact_prompt_phrase(readable_palette, max_words=2)
    presentation = _compact_prompt_phrase(
        prompt_bundle.get("gender_presentation", "androgynous"),
        max_words=1,
    )

    # FLUX's CLIP encoder has a 77-token window. Identity, proportions, and
    # exclusions must all precede the cut; word count alone underestimates BPEs.
    return (
        f"{direction}. ONE unarmed {presentation} adult {role}. {headgear}; same {wardrobe}; {palette} clothes. "
        "Compact four-head adult: large head, broad torso, low waist, short thick legs, large boots. "
        "Chunky JRPG pixel sprite; full body, flat background. "
        "No backpack, carried object, text, scenery, shadow, duplicate."
    )


def _flux2_identity_edit_prompt(base_prompt: str) -> str:
    return (
        "Edit the input character. Preserve the exact face, hood, respirator, clothing, "
        "colors, chest gear, body proportions, and pixel-art style. Change only pose and view. "
        + base_prompt
    )


def _flat_border_summary(source: Image.Image, *, tolerance: int = 20) -> dict[str, Any]:
    rgb = source.convert("RGB")
    band = max(8, min(rgb.width, rgb.height) // 12)
    border = list(rgb.crop((0, 0, rgb.width, band)).getdata())
    border += list(rgb.crop((0, rgb.height - band, rgb.width, rgb.height)).getdata())
    border += list(rgb.crop((0, 0, band, rgb.height)).getdata())
    border += list(rgb.crop((rgb.width - band, 0, rgb.width, rgb.height)).getdata())
    quantized = Counter((red // 8, green // 8, blue // 8) for red, green, blue in border)
    dominant_bin, _ = quantized.most_common(1)[0]
    candidates = [
        pixel
        for pixel in border
        if tuple(channel // 8 for channel in pixel) == dominant_bin
    ]
    background = tuple(
        sorted(pixel[channel] for pixel in candidates)[len(candidates) // 2]
        for channel in range(3)
    )
    matching = sum(
        1
        for pixel in border
        if max(abs(pixel[channel] - background[channel]) for channel in range(3)) <= tolerance
    )
    return {
        "background_rgb": list(background),
        "flat_border_ratio": matching / max(1, len(border)),
    }


def _remove_flat_border_background(
    source: Image.Image,
    *,
    tolerance: int = 28,
    local_tolerance: int = 5,
) -> Image.Image:
    rgba = source.convert("RGBA")
    width, height = rgba.size
    pixels = list(rgba.getdata())
    background = tuple(_flat_border_summary(rgba)["background_rgb"])

    def is_background(index: int) -> bool:
        pixel = pixels[index]
        return max(abs(pixel[channel] - background[channel]) for channel in range(3)) <= tolerance

    queued = set()
    queue = deque()
    for x in range(width):
        for index in (x, (height - 1) * width + x):
            if index not in queued and is_background(index):
                queued.add(index)
                queue.append(index)
    for y in range(height):
        for index in (y * width, y * width + width - 1):
            if index not in queued and is_background(index):
                queued.add(index)
                queue.append(index)

    while queue:
        index = queue.popleft()
        x, y = index % width, index // width
        for neighbor in (index - 1, index + 1, index - width, index + width):
            if neighbor < 0 or neighbor >= width * height or neighbor in queued:
                continue
            nx, ny = neighbor % width, neighbor // width
            local_delta = max(
                abs(pixels[neighbor][channel] - pixels[index][channel])
                for channel in range(3)
            )
            if (
                abs(nx - x) + abs(ny - y) != 1
                or not is_background(neighbor)
                or local_delta > local_tolerance
            ):
                continue
            queued.add(neighbor)
            queue.append(neighbor)

    rgba.putdata([
        (*pixel[:3], 0) if index in queued else pixel
        for index, pixel in enumerate(pixels)
    ])
    return rgba


def _align_foreground_hue(source: Image.Image, reference: Image.Image) -> tuple[Image.Image, float]:
    def mean_hue(image: Image.Image) -> float | None:
        isolated = _remove_flat_border_background(image)
        width, height = isolated.size
        x_total = 0.0
        y_total = 0.0
        weight_total = 0.0
        for index, (red, green, blue, alpha) in enumerate(isolated.getdata()):
            if alpha <= 8 or index // width < int(height * 0.15):
                continue
            hue, saturation, brightness = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
            if saturation < 0.35 or brightness < 0.10:
                continue
            weight = saturation * max(0.2, brightness)
            x_total += math.cos(hue * math.tau) * weight
            y_total += math.sin(hue * math.tau) * weight
            weight_total += weight
        if weight_total <= 0:
            return None
        return (math.atan2(y_total, x_total) / math.tau) % 1.0

    source_hue = mean_hue(source)
    reference_hue = mean_hue(reference)
    if source_hue is None or reference_hue is None:
        return source.convert("RGBA"), 0.0
    hue_shift = ((reference_hue - source_hue + 0.5) % 1.0) - 0.5
    if abs(hue_shift) < 0.015:
        return source.convert("RGBA"), round(hue_shift * 360, 3)

    isolated = _remove_flat_border_background(source)
    output = source.convert("RGBA")
    output_pixels = list(output.getdata())
    width, height = output.size
    for index, (red, green, blue, alpha) in enumerate(isolated.getdata()):
        if alpha <= 8 or index // width < int(height * 0.15):
            continue
        hue, saturation, brightness = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        if saturation < 0.35 or brightness < 0.10:
            continue
        aligned = colorsys.hsv_to_rgb((hue + hue_shift) % 1.0, saturation, brightness)
        original_alpha = output_pixels[index][3]
        output_pixels[index] = tuple(round(channel * 255) for channel in aligned) + (original_alpha,)
    output.putdata(output_pixels)
    return output, round(hue_shift * 360, 3)


def _compact_sprite_proportions(
    source: Image.Image,
    *,
    target_aspect: float,
    leg_start_ratio: float = 0.60,
) -> tuple[Image.Image, dict[str, float]]:
    """Turn an overly tall generated figure into a compact field-sprite body.

    The transform is conditional and piecewise: it shortens only the lower-body
    band and gives the head a small relative width increase. Final sizing later
    establishes the target front/profile aspect without stretching empty space.
    """

    rgba = source.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("Cannot compact an empty sprite")
    cropped = rgba.crop(bbox)
    width, height = cropped.size
    source_aspect = width / max(1, height)
    target_aspect = max(0.42, min(0.72, float(target_aspect)))
    severity = max(0.0, min(1.0, ((target_aspect / max(0.01, source_aspect)) - 1.0) / 0.55))
    if severity <= 0.02:
        return cropped, {
            "source_aspect": round(source_aspect, 4),
            "compacted_aspect": round(source_aspect, 4),
            "compact_severity": 0.0,
            "leg_vertical_scale": 1.0,
            "head_width_scale": 1.0,
        }

    split_y = max(1, min(height - 1, round(height * leg_start_ratio)))
    leg_vertical_scale = 1.0 - (0.22 * severity)
    upper = cropped.crop((0, 0, width, split_y))
    lower = cropped.crop((0, split_y, width, height))
    lower_height = max(1, round(lower.height * leg_vertical_scale))
    lower = lower.resize((width, lower_height), Image.Resampling.NEAREST)
    compacted = Image.new("RGBA", (width, upper.height + lower.height), (0, 0, 0, 0))
    compacted.alpha_composite(upper, (0, 0))
    compacted.alpha_composite(lower, (0, upper.height))

    # Increase only the head band relative to shoulders; the whole-body target
    # aspect is applied after this operation.
    head_height = max(1, round(compacted.height * 0.27))
    head_width_scale = 1.0 + (0.12 * severity)
    head = compacted.crop((0, 0, compacted.width, head_height))
    enlarged_head_width = max(head.width, round(head.width * head_width_scale))
    head = head.resize((enlarged_head_width, head.height), Image.Resampling.NEAREST)
    output_width = max(compacted.width, enlarged_head_width)
    output = Image.new("RGBA", (output_width, compacted.height), (0, 0, 0, 0))
    body_x = (output_width - compacted.width) // 2
    head_x = (output_width - head.width) // 2
    output.alpha_composite(compacted, (body_x, 0))
    output.alpha_composite(head, (head_x, 0))
    output_bbox = output.getchannel("A").getbbox()
    output = output.crop(output_bbox) if output_bbox else output
    compacted_aspect = output.width / max(1, output.height)
    return output, {
        "source_aspect": round(source_aspect, 4),
        "compacted_aspect": round(compacted_aspect, 4),
        "compact_severity": round(severity, 4),
        "leg_vertical_scale": round(leg_vertical_scale, 4),
        "head_width_scale": round(head_width_scale, 4),
    }


def _natural_walk_cycle(character: Image.Image, *, hip_ratio: float = 0.61) -> list[Image.Image]:
    """Build contact/passing/opposite-contact frames from one authored stride."""

    base = character.convert("RGBA")
    width, height = base.size
    split = max(1, min(height - 2, round(height * hip_ratio)))
    overlap = max(2, round(height * 0.025))

    def opposite_contact(source: Image.Image) -> Image.Image:
        frame = Image.new("RGBA", source.size, (0, 0, 0, 0))
        lower = source.crop((0, split - overlap, width, height)).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        frame.alpha_composite(lower, (0, split - overlap))
        frame.alpha_composite(source.crop((0, 0, width, split + overlap)), (0, 0))
        return frame

    def passing_pose(source: Image.Image, *, shift: int) -> Image.Image:
        frame = Image.new("RGBA", source.size, (0, 0, 0, 0))
        upper = source.crop((0, 0, width, split + overlap))
        lower = source.crop((0, split - overlap, width, height))
        narrowed_width = max(1, round(lower.width * 0.88))
        lower = lower.resize((narrowed_width, lower.height), Image.Resampling.NEAREST)
        frame.alpha_composite(lower, ((width - narrowed_width) // 2 - shift, split - overlap))
        frame.alpha_composite(upper, (shift, 2))
        return frame

    opposite = opposite_contact(base)
    return [
        base,
        passing_pose(base, shift=1),
        opposite,
        passing_pose(opposite, shift=-1),
    ]


def _request_flux_sheet(
    *,
    config: dict[str, Any],
    prompt_bundle: dict[str, Any],
    output_dir: Path,
    raw_sheet_path: Path,
) -> dict[str, Any]:
    endpoint = str(config.get("endpoint", "")).rstrip("/")
    if not endpoint:
        return {"status": "skipped", "reason": "Missing FLUX endpoint."}
    started_at = datetime.now(timezone.utc).isoformat()
    started_perf = time.perf_counter()
    event_status = "error"
    
    try:
        import io
        import base64
        from PIL import Image

        service_metadata: dict[str, Any] = {"model": "unknown", "pipeline_family": "unknown"}
        try:
            health_response = requests.get(f"{endpoint}/health", timeout=10)
            health_response.raise_for_status()
            health_payload = health_response.json()
            service_metadata = {
                "model": str(health_payload.get("model", "unknown")),
                "pipeline_family": str(health_payload.get("pipeline_family", "unknown")),
                "dtype": str(health_payload.get("dtype", "unknown")),
            }
        except (requests.RequestException, ValueError):
            pass
        is_flux2 = service_metadata["pipeline_family"] == "flux2_klein"
        
        # Establish identity once, then condition one forward and one profile
        # pose. Pixel motion expands each stable pose into a four-frame cycle.
        state_requests = [
            ("idle_down", "Front-facing neutral stand", 0, False),
            (
                "walk_down_a",
                "Front-facing walk, left boot forward, right boot back",
                1,
                True,
            ),
            (
                "walk_left_a",
                "Strict left side-profile walk, nose left, front boot extended",
                3,
                True,
            ),
        ]
        
        final_image = Image.new("RGBA", (512, 512), (255, 255, 255, 255))
        
        repair_attempt = max(0, int(os.environ.get("AGORA_SPRITE_REPAIR_ATTEMPT", "0") or "0"))
        authored_colors = re.findall(r"#[0-9A-Fa-f]{6}", str(prompt_bundle.get("sprite_prompt", "")))[:3]

        def lift_dark_hex(value: str) -> str:
            channels = [int(value[index:index + 2], 16) for index in (1, 3, 5)]
            if sum(channels) / 3 >= 92:
                return value.upper()
            lifted = [round(channel + (255 - channel) * 0.34) for channel in channels]
            return "#" + "".join(f"{channel:02X}" for channel in lifted)

        readable_palette = ", ".join(_plain_color_name(lift_dark_hex(value)) for value in authored_colors) or "navy, teal, gold"
        def keep_largest_alpha_component(source: Image.Image) -> Image.Image:
            rgba = source.convert("RGBA")
            alpha = rgba.getchannel("A")
            width, height = rgba.size
            active = {index for index, value in enumerate(alpha.getdata()) if value > 8}
            components: list[list[int]] = []
            while active:
                start = active.pop()
                queue = deque([start])
                component = [start]
                while queue:
                    index = queue.popleft()
                    x, y = index % width, index // width
                    for neighbor in (index - 1, index + 1, index - width, index + width):
                        if neighbor not in active:
                            continue
                        nx, ny = neighbor % width, neighbor // width
                        if abs(nx - x) + abs(ny - y) != 1:
                            continue
                        active.remove(neighbor)
                        queue.append(neighbor)
                        component.append(neighbor)
                components.append(component)
            if not components:
                return rgba
            keep = set(max(components, key=len))
            pixels = list(rgba.getdata())
            rgba.putdata([pixel if index in keep else (*pixel[:3], 0) for index, pixel in enumerate(pixels)])
            return rgba

        def motion_cycle(
            source: Image.Image,
            animated: bool,
            *,
            target_aspect: float,
        ) -> tuple[list[Image.Image], dict[str, float]]:
            border_background = tuple(_flat_border_summary(source)["background_rgb"])
            isolated = _remove_flat_border_background(source)
            bbox = isolated.getchannel("A").getbbox()
            if bbox is None:
                raise RuntimeError("FLUX returned an empty character after background removal")
            preliminary_crop = isolated.crop(bbox)
            from asset_pipeline.sprite_qa_programmatic import _alpha_component_summary
            component_summary = _alpha_component_summary(preliminary_crop, 8, 0.04)
            if (
                int(component_summary["major_component_count"]) > 2
                or float(component_summary["largest_component_ratio"]) < 0.78
            ):
                raise RuntimeError(
                    "FLUX foreground is not one dominant connected character "
                    f"(major={component_summary['major_component_count']}, "
                    f"largest={component_summary['largest_component_ratio']:.3f})"
                )
            cropped = keep_largest_alpha_component(preliminary_crop)
            cleaned_bbox = cropped.getchannel("A").getbbox()
            if cleaned_bbox is None:
                raise RuntimeError("FLUX character was empty after detached-artifact cleanup")
            cropped = cropped.crop(cleaned_bbox)
            pixels = list(cropped.getdata())
            foot_band_start = int(cropped.height * 0.80)
            cleaned_pixels = []
            for index, (red, green, blue, alpha) in enumerate(pixels):
                y = index // cropped.width
                low_saturation_bright = (
                    max(red, green, blue) - min(red, green, blue) < 28
                    and (red + green + blue) / 3 > 50
                    and max(
                        abs(channel - background_channel)
                        for channel, background_channel in zip(
                            (red, green, blue),
                            border_background,
                        )
                    ) < 60
                )
                cleaned_pixels.append((red, green, blue, 0) if y >= foot_band_start and low_saturation_bright else (red, green, blue, alpha))
            cropped.putdata(cleaned_pixels)
            shadow_cleaned_bbox = cropped.getchannel("A").getbbox()
            if shadow_cleaned_bbox is None:
                raise RuntimeError("FLUX character was empty after floor-shadow cleanup")
            cropped = cropped.crop(shadow_cleaned_bbox)
            source_aspect = cropped.width / max(1, cropped.height)
            max_source_aspect = 0.86 if animated else 0.74
            if source_aspect > max_source_aspect:
                raise RuntimeError(
                    "FLUX character silhouette is too wide for one human pose "
                    f"(bbox aspect {source_aspect:.3f} > {max_source_aspect:.3f}); "
                    "likely multiple people or scenery"
                )
            opaque_pixels = [pixel for pixel in cropped.getdata() if pixel[3] > 8]
            bbox_fill_ratio = len(opaque_pixels) / max(1, cropped.width * cropped.height)
            min_fill_ratio = 0.20 if animated else 0.28
            if bbox_fill_ratio < min_fill_ratio:
                raise RuntimeError(
                    f"FLUX foreground fill ratio {bbox_fill_ratio:.3f} < {min_fill_ratio:.3f}; "
                    "likely text, floor marks, or detached props"
                )
            dark_ratio = sum(1 for r, g, b, _ in opaque_pixels if (r + g + b) / 3 < 52) / max(1, len(opaque_pixels))
            bright_ratio = sum(1 for r, g, b, _ in opaque_pixels if (r + g + b) / 3 > 105) / max(1, len(opaque_pixels))
            max_dark_ratio = 0.82 if animated else 0.70
            min_bright_ratio = 0.04 if animated else 0.10
            if dark_ratio > max_dark_ratio or bright_ratio < min_bright_ratio:
                raise RuntimeError(
                    "FLUX palette is unreadably dark at gameplay scale "
                    f"(dark={dark_ratio:.3f}, bright={bright_ratio:.3f}; "
                    f"limits={max_dark_ratio:.3f}/{min_bright_ratio:.3f})"
                )
            cropped, proportion_metrics = _compact_sprite_proportions(
                cropped,
                target_aspect=target_aspect,
            )
            target_height = 108
            # The old successful field sprites occupy 0.52-0.63 body-width per
            # body-height. Establish that grammar after conditional regional
            # compaction instead of preserving a fashion-model source aspect.
            target_width = max(54, min(78, round(target_height * target_aspect)))
            fitted = cropped.resize((target_width, target_height), Image.Resampling.NEAREST)
            character = Image.new("RGBA", (112, 112), (0, 0, 0, 0))
            character.alpha_composite(fitted, ((112 - target_width) // 2, 2))
            proportion_metrics.update(
                {
                    "target_aspect": round(target_aspect, 4),
                    "target_width": float(target_width),
                    "target_height": float(target_height),
                }
            )
            if not animated:
                return [character.copy() for _ in range(4)], proportion_metrics
            return _natural_walk_cycle(character), proportion_metrics

        responses_log = []
        canonical_reference_b64 = ""
        stable_seed = int(
            hashlib.sha256(str(prompt_bundle.get("agent_id", prompt_bundle.get("concept_prompt", "agent"))).encode("utf-8")).hexdigest()[:8],
            16,
        )
        stable_seed += repair_attempt * 100_000
        generated_sources: dict[str, Image.Image] = {}
        for state_name, direction, seed_offset, animated in state_requests:
            prompt = _flux_sprite_prompt(
                prompt_bundle=prompt_bundle,
                direction=direction,
                readable_palette=readable_palette,
            )
            if canonical_reference_b64 and is_flux2:
                prompt = _flux2_identity_edit_prompt(prompt)
            neg = prompt_bundle.get("negative_prompt", "")
            neg = neg.replace("white background,", "").replace("studio backdrop,", "")
            neg = (
                "text, letters, logo, seal graphic, circular stamp, shadow, held object, detached prop, "
                "scenery, duplicate person, tall fashion model, long legs, narrow body, realistic anatomy, "
                "seven heads tall, eight heads tall, pixelated photograph, " + neg
            )
            payload = {
                "prompt": prompt,
                "negative_prompt": neg + ", shadow, gradient, background, scenery, objects, ground",
                "width": int(config.get("width", 512)),
                "height": int(config.get("height", 512)),
                "steps": int(config.get("steps", 4) or 4),
                "guidance_scale": float(config.get("guidance_scale", 0.0)),
                "asset_kind": "agent_sheet",
                "return_base64": True,
                "seed": stable_seed + seed_offset,
            }
            if canonical_reference_b64:
                payload["init_image_base64"] = canonical_reference_b64
                if not is_flux2:
                    payload["strength"] = 0.86 if state_name.startswith("walk_left") else 0.58
            response = requests.post(f"{endpoint}/generate", json=payload, timeout=config.get("timeout_seconds", 600))
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as http_err:
                print(f"FLUX service returned error response text: {response.text}", flush=True)
                raise http_err
            
            result = response.json()
            responses_log.append(
                {
                    "state": state_name,
                    "direction": direction,
                    "status": "ok",
                    "identity_conditioned": bool(canonical_reference_b64),
                    "prompt": prompt,
                    "prompt_word_count": len(prompt.split()),
                }
            )
            
            if "image_base64" in result:
                img_data = base64.b64decode(result["image_base64"])
                image = Image.open(io.BytesIO(img_data)).convert("RGBA")
                image.save(output_dir / f"flux_source_{state_name}.png")
                border_summary = _flat_border_summary(image)
                responses_log[-1]["border_background_rgb"] = border_summary["background_rgb"]
                responses_log[-1]["flat_border_ratio"] = round(border_summary["flat_border_ratio"], 4)
                if border_summary["flat_border_ratio"] < 0.82:
                    raise RuntimeError(
                        f"FLUX {state_name} produced a non-flat border or scenery "
                        f"(flat border ratio {border_summary['flat_border_ratio']:.3f} < 0.820)"
                    )
                if state_name == "idle_down":
                    canonical_reference_b64 = result["image_base64"]
                generated_sources[state_name] = image
            else:
                raise RuntimeError(f"FLUX missing base64 for direction {direction}")

        canonical = generated_sources["idle_down"]
        aligned_down, down_hue_shift = _align_foreground_hue(generated_sources["walk_down_a"], canonical)
        aligned_left, left_hue_shift = _align_foreground_hue(generated_sources["walk_left_a"], canonical)
        idle_frames, idle_proportions = motion_cycle(canonical, False, target_aspect=0.61)
        down_frames, down_proportions = motion_cycle(aligned_down, True, target_aspect=0.60)
        left_frames, left_proportions = motion_cycle(aligned_left, True, target_aspect=0.52)
        proportions_by_state = {
            "idle_down": idle_proportions,
            "walk_down_a": down_proportions,
            "walk_left_a": left_proportions,
        }
        for response_entry in responses_log:
            state = str(response_entry.get("state", ""))
            if state in proportions_by_state:
                response_entry["proportion_normalization"] = proportions_by_state[state]
        derived_rows = {
            "idle_down": (0, idle_frames),
            "walk_down": (1, down_frames),
            "walk_left": (2, left_frames),
            "walk_right": (
                3,
                [frame.transpose(Image.Transpose.FLIP_LEFT_RIGHT) for frame in left_frames],
            ),
        }
        generated_sources["walk_left_a"].transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(
            output_dir / "flux_source_walk_right.png"
        )
        responses_log.extend(
            [
                {
                    "state": "palette_alignment",
                    "status": "ok",
                    "walk_down_hue_shift_degrees": down_hue_shift,
                    "walk_left_hue_shift_degrees": left_hue_shift,
                },
                {
                    "state": "walk_down",
                    "status": "motion_frames_derived_from_conditioned_pose",
                    "method": "conditioned_flux_pose_compact_contact_cycle_v2",
                },
                {
                    "state": "walk_left",
                    "status": "motion_frames_derived_from_conditioned_pose",
                    "method": "conditioned_flux_pose_compact_contact_cycle_v2",
                },
                {
                    "state": "walk_right",
                    "status": "derived_from_walk_left",
                    "method": "identity_preserving_mirror",
                },
            ]
        )
        for _, (row, frames) in derived_rows.items():
            for col, frame in enumerate(frames):
                final_image.paste(frame, (col * 128 + 8, row * 128 + 8), frame)
                
        final_image.save(raw_sheet_path)
        _write_json(
            output_dir / "flux_sprite_response.json",
            {
                "status": "ok",
                "service": service_metadata,
                "directions": responses_log,
            },
        )
        
        if not raw_sheet_path.is_file():
            raise RuntimeError("FLUX service did not write the expected raw sheet.")
        event_status = "ok"
        return {"status": "ok", "response_path": str(output_dir / "flux_sprite_response.json")}

    finally:
        _append_timing_event(
            output_dir,
            stage="sprite_sheet_generation",
            status=event_status,
            started_at=started_at,
            duration_seconds=time.perf_counter() - started_perf,
            endpoint=endpoint,
            adapter="flux_local_service",
        )


def _request_vertex_sheet(
    *,
    world_config: dict[str, Any],
    prompt_bundle: dict[str, Any],
    output_dir: Path,
    raw_sheet_path: Path,
) -> dict[str, Any]:
    raise RuntimeError(
        "Gemini/Vertex sprite sheet generation is disabled; set sprite_generation.adapter='flux_local_service'."
    )


def _sprite_generation_adapter(pipeline_config: dict[str, Any]) -> str:
    adapter = str(
        pipeline_config.get("sprite_generation", {}).get("adapter", "flux_local_service")
    ).strip().lower()
    return adapter or "flux_local_service"


def _is_local_sprite_adapter(adapter: str) -> bool:
    return adapter in {"flux_local_service", "sd_webui_txt2img"}


def _run_prompt_reference_generation(
    *,
    world_config: dict[str, Any],
    prompt_bundle: dict[str, Any],
    output_dir: Path,
    reference_image_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        concept_summary = _request_gemini_prompt(
            world_config=world_config,
            prompt_bundle=prompt_bundle,
            output_dir=output_dir,
        )
        # DISABLED to save tokens
        reference_image_summary = {"status": "skipped", "reason": "Disabled by user request"}
    except Exception as prompt_error:
        concept_summary = {"status": "skipped", "reason": str(prompt_error)}
        reference_image_summary = {"status": "skipped", "reason": "Concept/reference stage unavailable."}
    return concept_summary, reference_image_summary


def _request_sprite_summary(
    *,
    world_config: dict[str, Any],
    pipeline_config: dict[str, Any],
    prompt_bundle: dict[str, Any],
    output_dir: Path,
    raw_sheet_path: Path,
) -> dict[str, Any]:
    sprite_config = pipeline_config.get("sprite_generation", {})
    adapter = _sprite_generation_adapter(pipeline_config)
    if adapter == "flux_local_service":
        return _request_flux_sheet(
            config=sprite_config,
            prompt_bundle=prompt_bundle,
            output_dir=output_dir,
            raw_sheet_path=raw_sheet_path,
        )
    if adapter == "vertex_sdk_image":
        raise RuntimeError(
            "sprite_generation.adapter='vertex_sdk_image' is forbidden; Gemini/Vertex direct image generation is disabled."
        )
    if adapter == "sd_webui_txt2img":
        return _request_sd_sheet(
            config=sprite_config,
            prompt_bundle=prompt_bundle,
            output_dir=output_dir,
            raw_sheet_path=raw_sheet_path,
        )
    raise ValueError(
        "Unsupported sprite_generation.adapter="
        f"{adapter!r}; expected 'flux_local_service' or 'sd_webui_txt2img'."
    )


def _run_remote_generation_attempt(
    *,
    world_config: dict[str, Any],
    pipeline_config: dict[str, Any],
    prompt_bundle: dict[str, Any],
    output_dir: Path,
    raw_sheet_path: Path,
    reference_image_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    concept_summary = {"status": "skipped_by_user"}
    reference_image_summary = {"status": "skipped_by_user"}
    sprite_summary = _request_sprite_summary(
        world_config=world_config,
        pipeline_config=pipeline_config,
        prompt_bundle=prompt_bundle,
        output_dir=output_dir,
        raw_sheet_path=raw_sheet_path,
    )
    return concept_summary, reference_image_summary, sprite_summary


def _remote_backend_label(world_config: dict[str, Any], sprite_adapter: str) -> str:
    if sprite_adapter == "vertex_sdk_image":
        backend = str(world_config.get("image_generation", {}).get("backend", "vertex_sdk")).strip().lower()
        return backend or "vertex_sdk"
    return sprite_adapter
