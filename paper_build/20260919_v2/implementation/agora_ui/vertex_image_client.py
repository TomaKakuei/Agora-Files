from __future__ import annotations

import base64
import json
import mimetypes
import os
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import requests


SCRIPT_DIR = Path(__file__).resolve().parent.parent


def _image_generation_config(config: dict[str, Any]) -> dict[str, Any]:
    image_generation = config.get("image_generation", {})
    return image_generation if isinstance(image_generation, dict) else {}


def _resolve(path_like: str | Path, *, base: Path = SCRIPT_DIR) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def _load_project_id_from_cred_file(cred_file: Path) -> str:
    try:
        payload = json.loads(cred_file.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if isinstance(payload, dict):
        return str(payload.get("project_id", "")).strip()
    return ""


class VertexSDKImageClient:
    """Compatibility image client.

    Existing runtime code still constructs VertexSDKImageClient, but Agora image
    generation now renders through FLUX. The class name is retained only to avoid
    breaking older call sites.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        image_config = _image_generation_config(config)
        runtime = config.get("runtime", {})
        pipeline = config.get("pixel_asset_pipeline", {}) if isinstance(config.get("pixel_asset_pipeline", {}), dict) else {}
        sprite_generation = pipeline.get("sprite_generation", {}) if isinstance(pipeline.get("sprite_generation", {}), dict) else {}
        self.backend = str(image_config.get("backend", "flux_local_service")).strip().lower() or "flux_local_service"
        self.flux_endpoint = str(
            image_config.get("endpoint")
            or sprite_generation.get("endpoint")
            or os.environ.get("AGORA_FLUX_ENDPOINT", "")
            or "http://127.0.0.1:8135"
        ).rstrip("/")
        self.width, self.height = self._dimensions(image_config)
        self.steps = int(image_config.get("steps", 8))
        self.guidance_scale = float(image_config.get("guidance_scale", 0.0))
        self.negative_prompt = str(
            image_config.get(
                "negative_prompt",
                "text, watermark, blurry, low quality, malformed hands, extra limbs",
            )
        )
        self.timeout_seconds = int(image_config.get("timeout_seconds", 600))
        self.pacing_sleep_seconds = float(image_config.get("pacing_sleep_seconds", 1.2))

        cred_file = image_config.get("vertex_cred_file", runtime.get("vertex_cred_file", ""))
        self.cred_file = _resolve(cred_file) if str(cred_file).strip() else None
        self.project_id = ""
        self.location = ""
        self.model_name = str(image_config.get("model", "disabled")).strip()
        self.temperature = float(image_config.get("temperature", 0.35))
        self.max_output_tokens = int(image_config.get("max_output_tokens", 1024))
        self.thinking_budget = int(image_config.get("thinking_budget", 0))
        self.ai_studio_thinking_level = self._normalize_ai_studio_thinking_level(
            image_config.get("thinking_level", self._default_ai_studio_thinking_level(self.model_name))
        )
        self.response_modalities = [str(item) for item in image_config.get("response_modalities", ["TEXT"])]
        self.api_key_env = str(image_config.get("api_key_env", runtime.get("api_key_env", "AGORA_AISTUDIO_API_KEY"))).strip()
        self.api_key = str(os.environ.get("GEMINI_API_KEY", "")).strip() or str(os.environ.get(self.api_key_env, "")).strip()
        self.endpoint_base = str(image_config.get("endpoint_base", "https://generativelanguage.googleapis.com/v1beta")).rstrip("/")
        self.method = str(image_config.get("method", "generateContent")).strip() or "generateContent"
        self.image_aspect_ratio = str(image_config.get("image_aspect_ratio", "")).strip()
        self.image_size = str(image_config.get("image_size", "")).strip()
        retry_config = dict(image_config.get("retry", {})) if isinstance(image_config.get("retry", {}), dict) else {}
        self.retry_max_attempts = int(retry_config.get("max_attempts", image_config.get("retry_max_attempts", 8)))
        self.retry_initial_sleep_seconds = float(
            retry_config.get("initial_sleep_seconds", image_config.get("retry_initial_sleep_seconds", 5.0))
        )
        self.retry_max_sleep_seconds = float(
            retry_config.get("max_sleep_seconds", image_config.get("retry_max_sleep_seconds", 120.0))
        )
        self.retry_backoff_multiplier = float(
            retry_config.get("backoff_multiplier", image_config.get("retry_backoff_multiplier", 2.0))
        )
        self.retry_status_codes = {
            int(item)
            for item in retry_config.get("status_codes", image_config.get("retry_status_codes", [408, 429, 500, 502, 503, 504]))
        }

    @staticmethod
    def _dimensions(image_config: dict[str, Any]) -> tuple[int, int]:
        raw_size = str(image_config.get("image_size", "")).lower().replace(" ", "")
        if "x" in raw_size:
            left, right = raw_size.split("x", 1)
            try:
                return max(64, int(left)), max(64, int(right))
            except Exception:
                pass
        return int(image_config.get("width", 1024)), int(image_config.get("height", 1024))

    @staticmethod
    def _normalize_ai_studio_thinking_level(value: Any) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"none", "minimal", "low", "medium", "high"}:
            return raw
        return "minimal"

    @staticmethod
    def _default_ai_studio_thinking_level(model_name: str) -> str:
        lowered = str(model_name).lower()
        if "image" in lowered:
            return "minimal"
        return "low"

    @staticmethod
    def _extension_for_mime(mime_type: str) -> str:
        lowered = mime_type.lower()
        if "jpeg" in lowered or "jpg" in lowered:
            return ".jpg"
        if "webp" in lowered:
            return ".webp"
        return ".png"

    def _path_to_inline_data(self, image_path: Path) -> dict[str, Any]:
        mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
        data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return {"inlineData": {"mimeType": mime_type, "data": data}}

    def _ai_studio_generation_config(self, *, response_modalities: list[str]) -> dict[str, Any]:
        config: dict[str, Any] = {
            "temperature": self.temperature,
            "maxOutputTokens": self.max_output_tokens,
            "responseModalities": response_modalities,
        }
        if self.thinking_budget >= 0:
            config["thinkingConfig"] = {"thinkingBudget": self.thinking_budget}
        if self.image_aspect_ratio:
            config["imageConfig"] = {"aspectRatio": self.image_aspect_ratio}
            if self.image_size:
                config["imageConfig"]["imageSize"] = self.image_size
        return config

    def _ai_studio_url(self) -> str:
        quoted_model = urllib.parse.quote(self.model_name, safe="")
        query = urllib.parse.urlencode({"key": self.api_key})
        return f"{self.endpoint_base}/models/{quoted_model}:{self.method}?{query}"

    def _vertex_url(self) -> str:
        project_id = str(self.project_id or "").strip()
        if not project_id and self.cred_file is not None:
            project_id = _load_project_id_from_cred_file(self.cred_file)
        if not project_id:
            project_id = str(os.environ.get("GOOGLE_CLOUD_PROJECT", "")).strip()
        location = str(self.location or "global").strip() or "global"
        quoted_model = urllib.parse.quote(self.model_name, safe="")
        return (
            f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/"
            f"publishers/google/models/{quoted_model}:streamGenerateContent"
        )

    @staticmethod
    def _extract_text_and_images_from_payload(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        chunks = payload if isinstance(payload, list) else [payload]
        text_parts: list[str] = []
        images: list[dict[str, Any]] = []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            for candidate in chunk.get("candidates", []) or []:
                content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
                for part in content.get("parts", []) or []:
                    if not isinstance(part, dict):
                        continue
                    text_value = part.get("text")
                    if isinstance(text_value, str) and text_value.strip():
                        text_parts.append(text_value.strip())
                    inline_data = part.get("inlineData") or part.get("inline_data")
                    if not isinstance(inline_data, dict):
                        continue
                    raw_data = inline_data.get("data")
                    mime_type = str(inline_data.get("mimeType") or inline_data.get("mime_type") or "image/png")
                    if isinstance(raw_data, str) and raw_data.strip():
                        try:
                            images.append({"mime_type": mime_type, "data": base64.b64decode(raw_data)})
                        except Exception:
                            pass
        return "\n".join(text_parts).strip(), images

    def _generate_flux_image(self, *, prompt: str, job_dir: Path, filename_stem: str) -> dict[str, Any]:
        job_dir.mkdir(parents=True, exist_ok=True)
        output_path = job_dir / f"{filename_stem}.png"
        payload = {
            "prompt": prompt,
            "negative_prompt": self.negative_prompt,
            "width": self.width,
            "height": self.height,
            "steps": self.steps,
            "guidance_scale": self.guidance_scale,
            "output_path": str(output_path),
            "return_base64": True,
            "asset_kind": "runtime_image",
        }
        response = requests.post(f"{self.flux_endpoint}/generate", json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        result = response.json()
        if isinstance(result.get("image_base64"), str) and result["image_base64"].strip():
            output_path.write_bytes(base64.b64decode(result["image_base64"]))
        elif not output_path.is_file() and isinstance(result.get("image_path"), str):
            generated_path = Path(result["image_path"])
            if generated_path.is_file():
                output_path.write_bytes(generated_path.read_bytes())
        if not output_path.is_file():
            raise RuntimeError("FLUX image generation returned no usable image.")
        return {
            "status": "ok",
            "image_path": str(output_path),
            "image_mime_type": "image/png",
            "raw_text": "",
            "model": "flux_local_service",
            "backend": "flux_local_service",
        }

    def _generate_legacy_vertex_image(
        self,
        *,
        prompt: str,
        job_dir: Path,
        filename_stem: str,
        source_image_path: Path | None,
    ) -> dict[str, Any]:
        raise RuntimeError("Legacy Gemini/Vertex direct image generation has been removed; use FLUX.")

    def generate_image(
        self,
        *,
        prompt: str,
        job_dir: Path,
        filename_stem: str,
        source_image_path: Path | None = None,
    ) -> dict[str, Any]:
        return self._generate_flux_image(prompt=prompt, job_dir=job_dir, filename_stem=filename_stem)
