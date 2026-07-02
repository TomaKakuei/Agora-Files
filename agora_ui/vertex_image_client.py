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


def _image_generation_config(config: dict[str, Any]) -> dict[str, Any]:
    image_generation = config.get("image_generation", {})
    return image_generation if isinstance(image_generation, dict) else {}


SCRIPT_DIR = Path(__file__).resolve().parent.parent


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
    """Image client for agent-requested still image artifacts."""

    def __init__(self, config: dict[str, Any]) -> None:
        image_config = _image_generation_config(config)
        runtime = config.get("runtime", {})
        self.backend = str(image_config.get("backend", "vertex_sdk")).strip().lower() or "vertex_sdk"
        cred_file = image_config.get("vertex_cred_file", runtime.get("vertex_cred_file", ""))
        self.cred_file = _resolve(cred_file) if str(cred_file).strip() else None
        self.project_id = ""
        self.location = ""
        self.model_name = str(image_config.get("model", "gemini-3.1-flash-image")).strip()
        self.temperature = float(image_config.get("temperature", 0.35))
        self.max_output_tokens = int(image_config.get("max_output_tokens", 1024))
        self.thinking_budget = int(image_config.get("thinking_budget", 0))
        self.ai_studio_thinking_level = self._normalize_ai_studio_thinking_level(
            image_config.get("thinking_level", self._default_ai_studio_thinking_level(self.model_name))
        )
        self.response_modalities = [str(item) for item in image_config.get("response_modalities", ["TEXT", "IMAGE"])]
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
        self.pacing_sleep_seconds = float(image_config.get("pacing_sleep_seconds", 1.2))
        self._genai_types = None
        self._client = None
        parts: list[dict[str, Any]] = [{"text": full_prompt}]
        if source_image_path is not None and source_image_path.is_file():
            parts.append(self._path_to_inline_data(source_image_path))
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": self._ai_studio_generation_config(response_modalities=self.response_modalities),
        }
        data = json.dumps(payload).encode("utf-8")
        
        is_ai_studio = self.backend in {"ai_studio", "aistudio", "google_ai_studio"}
        url = self._ai_studio_url() if is_ai_studio else self._vertex_url()
        headers = {"Content-Type": "application/json"}
        if not is_ai_studio:
            headers["x-goog-api-key"] = self.api_key
            
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST",
        )
        attempts = max(1, self.retry_max_attempts)
        sleep_seconds = max(0.0, self.retry_initial_sleep_seconds)
        last_error = None
        raw_payload = {}
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=300) as response:
                    raw_payload = json.loads(response.read().decode("utf-8", errors="replace"))
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = exc
                if int(exc.code) in {427, 429}:
                    if attempt == 1:
                        print(f"[{'VERTEX_RETRY' if 'vertex' in self.__class__.__name__.lower() else 'IMAGE_RETRY'}] Got 427/429. Waiting exactly 30s as instructed.")
                        time.sleep(30.0)
                        continue
                    else:
                        raise RuntimeError(f"Vertex API failed after 30s wait: HTTP {exc.code}: {body}") from exc
                
                retryable = int(exc.code) in self.retry_status_codes and attempt < attempts
                if retryable:
                    delay = min(self.retry_max_sleep_seconds, sleep_seconds)
                    delay += random.uniform(0.0, min(1.0, max(0.0, delay * 0.15)))
                    print(
                        f"[IMAGE_RETRY] backend={self.backend} model={self.model_name} attempt={attempt}/{attempts} "
                        f"http={exc.code} sleep={delay:.1f}s",
                        flush=True,
                    )
                    time.sleep(delay)
                    sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                    continue
                raise RuntimeError(f"AI Studio image generation failed: HTTP {exc.code}: {body[:500]}") from exc
            except (TimeoutError, socket.timeout) as exc:
                last_error = exc
                retryable = attempt < attempts
                if retryable:
                    delay = min(self.retry_max_sleep_seconds, sleep_seconds)
                    delay += random.uniform(0.0, min(1.0, max(0.0, delay * 0.15)))
                    print(
                        f"[IMAGE_RETRY] backend={self.backend} model={self.model_name} attempt={attempt}/{attempts} "
                        f"timeout={exc} sleep={delay:.1f}s",
                        flush=True,
                    )
                    time.sleep(delay)
                    sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                    continue
                raise RuntimeError(f"AI Studio image generation failed: timeout: {exc}") from exc
            except urllib.error.URLError as exc:
                last_error = exc
                retryable = attempt < attempts
                if retryable:
                    delay = min(self.retry_max_sleep_seconds, sleep_seconds)
                    delay += random.uniform(0.0, min(1.0, max(0.0, delay * 0.15)))
                    print(
                        f"[IMAGE_RETRY] backend={self.backend} model={self.model_name} attempt={attempt}/{attempts} "
                        f"url_error={exc.reason} sleep={delay:.1f}s",
                        flush=True,
                    )
                    time.sleep(delay)
                    sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                    continue
                raise RuntimeError(f"AI Studio image generation failed: {exc}") from exc
            except Exception as exc:
                last_error = exc
                retryable = attempt < attempts
                if retryable:
                    delay = min(self.retry_max_sleep_seconds, sleep_seconds)
                    delay += random.uniform(0.0, min(1.0, max(0.0, delay * 0.15)))
                    print(
                        f"[IMAGE_RETRY] backend={self.backend} model={self.model_name} attempt={attempt}/{attempts} "
                        f"error={exc} sleep={delay:.1f}s",
                        flush=True,
                    )
                    time.sleep(delay)
                    sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                    continue
                raise RuntimeError(f"AI Studio image generation failed: {exc}") from exc

        raw_text, images = self._extract_text_and_images_from_payload(raw_payload)
        if not images:
            raise RuntimeError(f"AI Studio image generation returned no image. Text: {raw_text[:500]}")
        first = images[0]
        mime_type = str(first.get("mime_type", "image/png"))
        image_path = job_dir / f"{filename_stem}{self._extension_for_mime(mime_type)}"
        image_path.write_bytes(first["data"])
        return {
            "status": "ok",
            "image_path": str(image_path),
            "image_mime_type": mime_type,
            "raw_text": raw_text,
            "model": self.model_name,
            "backend": self.backend,
        }


