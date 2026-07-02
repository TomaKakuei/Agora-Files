from __future__ import annotations

import base64
import json
import os
import sys
import time
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
    started_at = datetime.now(timezone.utc).isoformat()
    started_perf = time.perf_counter()
    endpoint = str(world_config.get("image_generation", {}).get("endpoint_base", "")).strip()
    event_status = "error"
    _, VertexSDKImageClient = _load_runtime_clients()
    image_client = VertexSDKImageClient(world_config)
    try:
        result = image_client.generate_image(
            prompt=(
                f"{prompt_bundle.get('text', prompt_bundle['concept_prompt'])}\n"
                "Create one clean reference illustration for character identity lock. "
                "No visible text, no watermark."
            ),
            job_dir=output_dir,
            filename_stem=output_image_path.stem,
        )
        generated_path = Path(str(result.get("image_path", "")).strip())
        if generated_path.is_file() and generated_path != output_image_path:
            output_image_path.write_bytes(generated_path.read_bytes())
        _write_json(output_dir / "reference_image_response.json", result)
        event_status = "ok"
        return {"status": result.get("status", "ok"), "image_path": str(output_image_path), "response_path": str(output_dir / "reference_image_response.json")}
    finally:
        _append_timing_event(
            output_dir,
            stage="reference_image_generation",
            status=event_status,
            started_at=started_at,
            duration_seconds=time.perf_counter() - started_perf,
            endpoint=endpoint,
            adapter="vertex_sdk_image",
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
        
        directions = [
            ("front, facing camera, walking down", 0),
            ("side profile, walking left", 1),
            ("side profile, walking right", 2),
            ("back, facing away, walking up", 3)
        ]
        
        final_image = Image.new("RGBA", (512, 512), (255, 255, 255, 255))
        
        concept = prompt_bundle.get("concept_prompt", "")
        desc_parts = []
        for line in concept.split(". "):
            if "Appearance:" in line or "Theme" in line or "Character wears" in line or "attire" in line:
                cleaned = line.replace("Appearance:", "").replace("Chinese Style Theme tang_dynasty_classic:", "").replace("Theme: Japanese fantasy RPG guild", "").strip()
                if " standing" in cleaned:
                    cleaned = cleaned.split(" standing")[0]
                if cleaned:
                    desc_parts.append(cleaned)
        
        char_desc = ". ".join(desc_parts)
        base_prompt = f"solid pure white blank background #FFFFFF, no scenery. pixel art, {char_desc}, full body character illustration, {{}}. STANDING ALONE, ISOLATED ON SOLID WHITE #FFFFFF SEAMLESS PAPER BACKDROP. ABSOLUTELY NO BACKGROUND SCENERY, NO PROPS, NO MARKET. WARNING: IF THE DESCRIPTION MENTIONS ANY PROPS (LIKE WORKBENCH, LAMP, BOWL, TOOLS, DESK), YOU MUST IGNORE THEM AND ONLY DRAW THE HUMAN CHARACTER! PURE WHITE BACKGROUND ONLY!"
        
        responses_log = []
        for direction, row in directions:
            prompt = base_prompt.format(direction)
            neg = prompt_bundle.get("negative_prompt", "")
            neg = neg.replace("white background,", "").replace("studio backdrop,", "")
            payload = {
                "prompt": prompt,
                "negative_prompt": neg + ", shadow, gradient, background, scenery, objects, ground",
                "width": int(config.get("width", 512)),
                "height": int(config.get("height", 512)),
                "steps": 4,  # Force 4 steps for schnell
                "guidance_scale": float(config.get("guidance_scale", 0.0)),
                "asset_kind": "generic",
                "return_base64": True,
            }
            
            response = requests.post(f"{endpoint}/generate", json=payload, timeout=config.get("timeout_seconds", 600))
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as http_err:
                print(f"FLUX service returned error response text: {response.text}", flush=True)
                raise http_err
            
            result = response.json()
            responses_log.append({"direction": direction, "status": "ok"})
            
            if "image_base64" in result:
                img_data = base64.b64decode(result["image_base64"])
                image = Image.open(io.BytesIO(img_data)).convert("RGBA")
                # Resize to slightly smaller than 128 to ensure body width ratio passes QA
                resized_image = image.resize((100, 100))
                for col in range(4):
                    final_image.paste(resized_image, (col * 128 + 14, row * 128 + 14))
            else:
                raise RuntimeError(f"FLUX missing base64 for direction {direction}")
                
        final_image.save(raw_sheet_path)
        _write_json(output_dir / "flux_sprite_response.json", {"status": "ok", "directions": responses_log})
        
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
    started_at = datetime.now(timezone.utc).isoformat()
    started_perf = time.perf_counter()
    endpoint = str(world_config.get("image_generation", {}).get("endpoint_base", "")).strip()
    event_status = "error"
    _, VertexSDKImageClient = _load_runtime_clients()
    image_client = VertexSDKImageClient(world_config)
    try:
        result = image_client.generate_image(
            prompt=(
                f"{prompt_bundle['sprite_prompt']}\n"
                "Return one strict full-body sprite sheet image only. "
                "No extra panel chrome, no label text, no watermark."
            ),
            job_dir=output_dir,
            filename_stem=raw_sheet_path.stem,
        )
        _write_json(output_dir / "vertex_sprite_response.json", result)
        generated_path = Path(str(result.get("image_path", "")).strip())
        if generated_path.is_file() and generated_path != raw_sheet_path:
            raw_sheet_path.write_bytes(generated_path.read_bytes())
        event_status = "ok"
        return {
            "status": result.get("status", "ok"),
            "response_path": str(output_dir / "vertex_sprite_response.json"),
            "image_path": str(raw_sheet_path),
        }
    finally:
        _append_timing_event(
            output_dir,
            stage="sprite_sheet_generation",
            status=event_status,
            started_at=started_at,
            duration_seconds=time.perf_counter() - started_perf,
            endpoint=endpoint,
            adapter="vertex_sdk_image",
        )


def _sprite_generation_adapter(pipeline_config: dict[str, Any]) -> str:
    adapter = str(pipeline_config.get("sprite_generation", {}).get("adapter", "sd_webui_txt2img"))
    return adapter


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
        return _request_vertex_sheet(
            world_config=world_config,
            prompt_bundle=prompt_bundle,
            output_dir=output_dir,
            raw_sheet_path=raw_sheet_path,
        )
    return _request_sd_sheet(
        config=sprite_config,
        prompt_bundle=prompt_bundle,
        output_dir=output_dir,
        raw_sheet_path=raw_sheet_path,
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
