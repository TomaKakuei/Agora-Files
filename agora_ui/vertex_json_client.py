from __future__ import annotations

import json
import os
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .flex_api import first_json_value_from_text


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)



class StreamingJsonStringExtractor:
    def __init__(self, key: str):
        self.key = key
        self.key_str = f'"{key}"'
        self.extracted_text = ""
        self.is_completed = False

    def process_chunk(self, accumulated_text: str) -> str:
        if self.is_completed:
            return self.extracted_text
        start_idx = accumulated_text.find(self.key_str)
        if start_idx == -1:
            return self.extracted_text
        colon_idx = accumulated_text.find(':', start_idx + len(self.key_str))
        if colon_idx == -1:
            return self.extracted_text
        quote_idx = accumulated_text.find('"', colon_idx)
        if quote_idx == -1:
            return self.extracted_text
        value_str = accumulated_text[quote_idx+1:]
        
        end_idx = len(value_str)
        escaped = False
        is_closed = False
        for i, c in enumerate(value_str):
            if escaped:
                escaped = False
                continue
            if c == '\\':
                escaped = True
            elif c == '"':
                end_idx = i
                is_closed = True
                self.is_completed = True
                break
                
        safe_str = value_str[:end_idx]
        if not is_closed:
            while safe_str.endswith('\\'):
                safe_str = safe_str[:-1]
                
        safe_str = safe_str.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\').replace('\\t', '\t')
        
        import re
        def replace_unicode(m):
            try:
                return chr(int(m.group(1), 16))
            except Exception:
                return m.group(0)
        safe_str = re.sub(r'\\u([0-9a-fA-F]{4})', replace_unicode, safe_str)
        
        self.extracted_text = safe_str
        return self.extracted_text

class VertexJsonClient:
    """Small JSON client that can target Vertex publisher REST or AI Studio REST."""

    def __init__(self, config: dict[str, Any]) -> None:
        api_config = dict(config.get("vertex_api", {}))
        self.primary_backend = str(api_config.get("backend", "vertex_publisher")).strip().lower() or "vertex_publisher"
        self.default_model = str(api_config.get("model", config.get("runtime", {}).get("vertex_model", ""))).strip()
        if not self.default_model:
            raise RuntimeError("vertex_api.model must be configured")
        self.temperature = float(api_config.get("temperature", 0.45))
        self.max_output_tokens = int(api_config.get("max_output_tokens", 24000))
        self.thinking_level = str(api_config.get("thinking_level", "high"))
        self.thinking_budget = int(api_config.get("thinking_budget", 8192))
        self.timeout_seconds = int(api_config.get("timeout_seconds", 120))
        self.stages = dict(api_config.get("stages", {}))
        self.fallback_after_consecutive_errors = max(
            0,
            int(api_config.get("fallback_after_consecutive_errors", 0)),
        )
        self.fallback_backend = str(api_config.get("fallback_backend", "")).strip().lower()
        self.fallback_model = str(api_config.get("fallback_model", self.default_model)).strip() or self.default_model
        self.fallback_thinking_level = str(api_config.get("fallback_thinking_level", "low")).strip() or "low"
        self.fallback_thinking_budget = int(api_config.get("fallback_thinking_budget", self.thinking_budget))
        self.fallback_timeout_seconds = int(api_config.get("fallback_timeout_seconds", self.timeout_seconds))
        retry_config = dict(api_config.get("retry", {})) if isinstance(api_config.get("retry", {}), dict) else {}
        self.retry_max_attempts = int(retry_config.get("max_attempts", api_config.get("retry_max_attempts", 8)))
        self.retry_initial_sleep_seconds = float(
            retry_config.get("initial_sleep_seconds", api_config.get("retry_initial_sleep_seconds", 5.0))
        )
        self.retry_max_sleep_seconds = float(
            retry_config.get("max_sleep_seconds", api_config.get("retry_max_sleep_seconds", 120.0))
        )
        self.retry_backoff_multiplier = float(
            retry_config.get("backoff_multiplier", api_config.get("retry_backoff_multiplier", 2.0))
        )
        self.retry_status_codes = {
            int(item)
            for item in retry_config.get("status_codes", api_config.get("retry_status_codes", [408, 429, 500, 502, 503, 504]))
        }
        self._consecutive_primary_failures = 0
        self._active_backend_name = "primary"
        self._backend_configs = {
            "primary": self._build_backend_config(
                backend=self.primary_backend,
                api_key_env=str(api_config.get("api_key_env", "AGORA_VERTEX_API_KEY")),
                endpoint_base=str(api_config.get("endpoint_base", "")),
                method=str(api_config.get("method", "")),
                model=self.default_model,
                thinking_level=self.thinking_level,
                thinking_budget=self.thinking_budget,
                timeout_seconds=self.timeout_seconds,
                pacing_sleep_seconds=api_config.get("pacing_sleep_seconds"),
            )
        }
        if self.fallback_backend:
            self._backend_configs["fallback"] = self._build_backend_config(
                backend=self.fallback_backend,
                api_key_env=str(api_config.get("fallback_api_key_env", "AGORA_AISTUDIO_API_KEY")),
                endpoint_base=str(api_config.get("fallback_endpoint_base", "")),
                method=str(api_config.get("fallback_method", "")),
                model=self.fallback_model,
                thinking_level=self.fallback_thinking_level,
                thinking_budget=self.fallback_thinking_budget,
                timeout_seconds=self.fallback_timeout_seconds,
                pacing_sleep_seconds=api_config.get("fallback_pacing_sleep_seconds"),
            )
        self.backend = self._active_backend()["backend"]
        self.api_key_env = self._active_backend()["api_key_env"]
        self.api_key = self._active_backend()["api_key"]
        self.endpoint_base = self._active_backend()["endpoint_base"]
        self.method = self._active_backend()["method"]

    @staticmethod
    def _is_ai_studio_backend(backend: str) -> bool:
        return backend in {"ai_studio", "aistudio", "google_ai_studio"}

    def _build_backend_config(
        self,
        *,
        backend: str,
        api_key_env: str,
        endpoint_base: str,
        method: str,
        model: str,
        thinking_level: str,
        thinking_budget: int,
        timeout_seconds: int,
        pacing_sleep_seconds: Any = None,
    ) -> dict[str, Any]:
        backend_name = str(backend).strip().lower() or "vertex_publisher"
        api_key_name = str(api_key_env).strip() or "AGORA_VERTEX_API_KEY"
        api_key = str(os.environ.get(api_key_name, "")).strip()
        if self._is_ai_studio_backend(backend_name) and not api_key:
            raise RuntimeError(
                f"AI Studio REST API key is not set. Export {api_key_name} before running."
            )
            
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0687399333")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        if location == "global":
            location = "us-central1"
        
        default_endpoint = (
            "https://generativelanguage.googleapis.com/v1beta"
            if self._is_ai_studio_backend(backend_name)
            else f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}"
        )
        default_method = "generateContent" if self._is_ai_studio_backend(backend_name) else "streamGenerateContent"
        
        if pacing_sleep_seconds is None:
            pacing_val = 0.0 if self._is_ai_studio_backend(backend_name) else 1.2
        else:
            try:
                pacing_val = float(pacing_sleep_seconds)
            except (ValueError, TypeError):
                pacing_val = 0.0 if self._is_ai_studio_backend(backend_name) else 1.2

        return {
            "backend": backend_name,
            "api_key_env": api_key_name,
            "api_key": api_key,
            "endpoint_base": str(endpoint_base or default_endpoint).rstrip("/"),
            "method": str(method or default_method).strip() or default_method,
            "model": str(model).strip() or self.default_model,
            "thinking_level": str(thinking_level or self.thinking_level).strip() or self.thinking_level,
            "thinking_budget": int(thinking_budget),
            "timeout_seconds": int(timeout_seconds),
            "pacing_sleep_seconds": pacing_val,
        }

    def _active_backend(self) -> dict[str, Any]:
        return self._backend_configs[self._active_backend_name]

    def safe_config(self) -> dict[str, Any]:
        stages: dict[str, Any] = {}
        for stage, stage_config in self.stages.items():
            if isinstance(stage_config, dict):
                stages[stage] = {
                    "model": str(stage_config.get("model", "")),
                    "max_output_tokens": int(stage_config.get("max_output_tokens", self.max_output_tokens)),
                    "temperature": float(stage_config.get("temperature", self.temperature)),
                }
        return {
            "backend": self._active_backend()["backend"],
            "active_backend_name": self._active_backend_name,
            "api_key_env": self._active_backend()["api_key_env"],
            "endpoint_base": self._active_backend()["endpoint_base"],
            "method": self._active_backend()["method"],
            "default_model": self.default_model,
            "thinking_level": self.thinking_level,
            "thinking_budget": self.thinking_budget,
            "max_output_tokens": self.max_output_tokens,
            "temperature": self.temperature,
            "fallback": (
                {
                    "backend": self._backend_configs["fallback"]["backend"],
                    "api_key_env": self._backend_configs["fallback"]["api_key_env"],
                    "endpoint_base": self._backend_configs["fallback"]["endpoint_base"],
                    "method": self._backend_configs["fallback"]["method"],
                    "model": self._backend_configs["fallback"]["model"],
                    "thinking_level": self._backend_configs["fallback"]["thinking_level"],
                    "thinking_budget": self._backend_configs["fallback"]["thinking_budget"],
                    "switch_after_consecutive_errors": self.fallback_after_consecutive_errors,
                }
                if "fallback" in self._backend_configs
                else None
            ),
            "retry": {
                "max_attempts": self.retry_max_attempts,
                "initial_sleep_seconds": self.retry_initial_sleep_seconds,
                "max_sleep_seconds": self.retry_max_sleep_seconds,
                "backoff_multiplier": self.retry_backoff_multiplier,
                "status_codes": sorted(self.retry_status_codes),
            },
            "stages": stages,
        }

    def _stage_config(self, stage: str) -> dict[str, Any]:
        stage_config = self.stages.get(stage, {})
        return stage_config if isinstance(stage_config, dict) else {}

    def _model_for_stage(self, stage: str) -> str:
        stage_config = self._stage_config(stage)
        if isinstance(stage_config, dict) and str(stage_config.get("model", "")).strip():
            return str(stage_config["model"]).strip()
        if stage in ("main_character_generation", "agent_profile_generation"):
            return "gemini-3.1-flash-lite"
        return str(self._active_backend().get("model", self.default_model)).strip() or self.default_model

    def _temperature_for_stage(self, stage: str) -> float:
        stage_config = self._stage_config(stage)
        if "temperature" in stage_config:
            return float(stage_config.get("temperature", self.temperature))
        return self.temperature

    def _max_output_tokens_for_stage(self, stage: str) -> int:
        stage_config = self._stage_config(stage)
        if "max_output_tokens" in stage_config:
            return int(stage_config.get("max_output_tokens", self.max_output_tokens))
        return self.max_output_tokens

    def _thinking_budget_for_stage(self, stage: str) -> int:
        stage_config = self._stage_config(stage)
        if "thinking_budget" in stage_config:
            return int(stage_config.get("thinking_budget", self.thinking_budget))
        return self.thinking_budget

    def _url(self, model: str, *, backend_name: str) -> str:
        backend_config = self._backend_configs[backend_name]
        quoted_model = urllib.parse.quote(model, safe="")
        if self._is_ai_studio_backend(str(backend_config["backend"])):
            query = urllib.parse.urlencode({"key": backend_config["api_key"]})
            return f"{backend_config['endpoint_base']}/models/{quoted_model}:{backend_config['method']}?{query}"
        return f"{backend_config['endpoint_base']}/publishers/google/models/{quoted_model}:{backend_config['method']}"

    def _headers(self, backend_name: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        backend_config = self._backend_configs[backend_name]
        if not self._is_ai_studio_backend(str(backend_config["backend"])):
            headers["x-goog-api-key"] = os.environ.get("GEMINI_API_KEY", "") or backend_config.get("api_key", "")
        return headers

    def _payload(
        self,
        full_prompt: str,
        *,
        stage: str,
        backend_name: str,
        media_parts: list[dict[str, Any]] | None = None,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        backend_config = self._backend_configs[backend_name]
        model = self._model_for_stage(stage)
        max_out = self._max_output_tokens_for_stage(stage)
        model_name = str(model).strip().lower()
        if "gemini-2.5" in model_name or "gemini-1.5" in model_name:
            max_out = min(max_out, 8192)
        generation_config = {
            "temperature": self._temperature_for_stage(stage),
            "maxOutputTokens": max_out,
        }
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        if True:
            if self._is_ai_studio_backend(str(backend_config["backend"])) and model_name.startswith("gemini-3"):
                generation_config["thinkingConfig"] = {
                    "thinkingLevel": str(backend_config.get("thinking_level", self.thinking_level)).strip().upper() or "LOW",
                }
            else:
                # Set thinking budget explicitly to 1024 per user instruction
                generation_config["thinkingConfig"] = {
                    "thinkingBudget": 1024,
                }
        parts: list[dict[str, Any]] = [{"text": full_prompt}]
        if media_parts:
            parts.extend(media_parts)
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": parts,
                }
            ],
            "generationConfig": generation_config,
        }


    @staticmethod
    def _chunks_from_response(raw_text: str) -> list[dict[str, Any]]:
        cleaned = str(raw_text or "").strip()
        if not cleaned:
            return []
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
            if isinstance(parsed, dict):
                return [parsed]
        except Exception:
            pass
        chunks: list[dict[str, Any]] = []
        for line in cleaned.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("data:"):
                stripped = stripped[5:].strip()
            if stripped == "[DONE]":
                continue
            try:
                parsed = json.loads(stripped)
            except Exception:
                continue
            if isinstance(parsed, dict):
                chunks.append(parsed)
        return chunks

    @staticmethod
    def _text_from_chunks(chunks: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for chunk in chunks:
            for candidate in chunk.get("candidates", []) or []:
                content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
                for part in content.get("parts", []) or []:
                    if isinstance(part, dict) and "text" in part:
                        parts.append(str(part.get("text", "")))
        return "".join(parts).strip()

    def generate_json(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema: dict[str, Any],
        stage: str,
    ) -> dict[str, Any]:
        full_prompt = (
            f"[System]\n{system_instruction}\n\n"
            f"[Required JSON Schema Shape]\n{_json_dumps(schema)}\n\n"
            f"[User]\n{prompt}\n\n"
            f"Use thinking level {self.thinking_level}. Return one minified JSON object only. "
            "No markdown. Keep strings concise."
        )
        return self._generate_json_from_prompt(full_prompt, stage=stage)

    def generate_multimodal_json(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema: dict[str, Any],
        stage: str,
        media_parts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        full_prompt = (
            f"[System]\n{system_instruction}\n\n"
            f"[Required JSON Schema Shape]\n{_json_dumps(schema)}\n\n"
            f"[User]\n{prompt}\n\n"
            f"Use thinking level {self.thinking_level}. Return one minified JSON object only. "
            "No markdown. Keep strings concise."
        )
        return self._generate_json_from_prompt(full_prompt, stage=stage, media_parts=media_parts)

    def _generate_json_from_prompt(
        self,
        full_prompt: str,
        *,
        stage: str,
        media_parts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        active_backend_name = self._active_backend_name
        try:
            parsed = self._generate_json_from_prompt_with_backend(
                full_prompt,
                stage=stage,
                backend_name=active_backend_name,
                media_parts=media_parts,
            )
            if active_backend_name == "primary":
                self._consecutive_primary_failures = 0
            return parsed
        except Exception as primary_exc:
            if active_backend_name != "primary" or "fallback" not in self._backend_configs:
                raise
            self._consecutive_primary_failures += 1
            should_switch = (
                self.fallback_after_consecutive_errors > 0
                and self._consecutive_primary_failures >= self.fallback_after_consecutive_errors
            )
            fallback_backend_name = "fallback"
            if should_switch:
                self._active_backend_name = fallback_backend_name
                print(
                    f"[VERTEX_BACKEND_SWITCH] stage={stage} after_consecutive_primary_failures="
                    f"{self._consecutive_primary_failures} switching_to={self._backend_configs[fallback_backend_name]['backend']}",
                    flush=True,
                )
            else:
                print(
                    f"[VERTEX_BACKEND_FALLBACK] stage={stage} primary_failure_streak={self._consecutive_primary_failures} "
                    f"using={self._backend_configs[fallback_backend_name]['backend']} for_this_call",
                    flush=True,
                )
            try:
                parsed = self._generate_json_from_prompt_with_backend(
                    full_prompt,
                    stage=stage,
                    backend_name=fallback_backend_name,
                    media_parts=media_parts,
                )
                return parsed
            except Exception:
                raise primary_exc

    def _generate_json_from_prompt_with_backend(
        self,
        full_prompt: str,
        *,
        stage: str,
        backend_name: str,
        media_parts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        attempts = max(1, self.retry_max_attempts)
        last_error: Exception | None = None
        last_body = ""
        model = self._model_for_stage(stage)
        backend_config = self._backend_configs[backend_name]
        sleep_seconds = max(0.0, self.retry_initial_sleep_seconds)
        invalid_json_retry = False
        for attempt in range(1, attempts + 1):
            attempt_prompt = full_prompt
            if invalid_json_retry:
                attempt_prompt = (
                    full_prompt
                    + "\n\n[Retry after invalid JSON]\n"
                    "Your previous response was not a complete JSON object. Return a single minified JSON "
                    "object only, with short strings and no pretty-printing. Do not add markdown."
                )
            payload = self._payload(attempt_prompt, stage=stage, backend_name=backend_name, media_parts=media_parts)
            data = json.dumps(payload).encode("utf-8")
            print(f"Payload config: {payload.get('generationConfig')}", file=open("/tmp/vertex_debug.log", "a"), flush=True)
            request = urllib.request.Request(
                self._url(model, backend_name=backend_name),
                data=data,
                headers=self._headers(backend_name),
                method="POST",
            )
            try:
                # Controlled pacing delay to prevent Vertex API 429 rate limit errors
                pacing_sleep = float(backend_config.get("pacing_sleep_seconds", 1.2))
                if pacing_sleep > 0.0:
                    time.sleep(pacing_sleep)
                print(f"Vertex request to {request.full_url} (timeout={backend_config['timeout_seconds']})", file=open("/tmp/vertex_debug.log", "a"), flush=True)
                with urllib.request.urlopen(request, timeout=int(backend_config["timeout_seconds"])) as response:
                    raw_text = response.read().decode("utf-8", errors="replace")
                    print("Vertex request finished", file=open("/tmp/vertex_debug.log", "a"), flush=True)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = exc
                last_body = body
                if int(exc.code) in {427, 429}:
                    if attempt <= 3:
                        sleep_time = 15.0 * attempt
                        print(f"[{'VERTEX_RETRY' if 'vertex' in self.__class__.__name__.lower() else 'IMAGE_RETRY'}] Got {exc.code}. Waiting {sleep_time}s (attempt {attempt}/3).")
                        time.sleep(sleep_time)
                        continue
                    else:
                        raise RuntimeError(f"Vertex API failed after multiple rate limit retries: HTTP {exc.code}: {body}") from exc
                
                retryable = int(exc.code) in self.retry_status_codes and attempt < attempts
                if retryable:
                    if int(exc.code) == 503 and "gemini-3.1" in model:
                        # Massive demand on 3.1 preview. Fallback to 2.5 pro
                        print(f"[VERTEX_FALLBACK] 503 on {model}, falling back to gemini-2.5-pro", flush=True)
                        model = "gemini-2.5-pro"
                        if isinstance(payload, dict) and "model" in payload:
                            payload["model"] = "gemini-2.5-pro"
                        
                    delay = min(self.retry_max_sleep_seconds, sleep_seconds)
                    delay += random.uniform(0.0, min(1.0, max(0.0, delay * 0.15)))
                    print(
                        f"[VERTEX_RETRY] backend={backend_config['backend']} stage={stage} model={model} attempt={attempt}/{attempts} "
                        f"http={exc.code} sleep={delay:.1f}s",
                        flush=True,
                    )
                    time.sleep(delay)
                    sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                    continue
                raise RuntimeError(f"Vertex REST API failed for stage {stage}: HTTP {exc.code}: {body}") from exc
            except (TimeoutError, socket.timeout) as exc:
                last_error = exc
                retryable = attempt < attempts
                if retryable:
                    delay = min(self.retry_max_sleep_seconds, sleep_seconds)
                    delay += random.uniform(0.0, min(1.0, max(0.0, delay * 0.15)))
                    print(
                        f"[VERTEX_RETRY] backend={backend_config['backend']} stage={stage} model={model} attempt={attempt}/{attempts} "
                        f"timeout={exc} sleep={delay:.1f}s",
                        flush=True,
                    )
                    time.sleep(delay)
                    sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                    continue
                raise RuntimeError(f"Vertex REST API failed for stage {stage}: timeout: {exc}") from exc
            except urllib.error.URLError as exc:
                last_error = exc
                retryable = attempt < attempts
                if retryable:
                    delay = min(self.retry_max_sleep_seconds, sleep_seconds)
                    delay += random.uniform(0.0, min(1.0, max(0.0, delay * 0.15)))
                    print(
                        f"[VERTEX_RETRY] backend={backend_config['backend']} stage={stage} model={model} attempt={attempt}/{attempts} "
                        f"url_error={exc.reason} sleep={delay:.1f}s",
                        flush=True,
                    )
                    time.sleep(delay)
                    sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                    continue
                raise RuntimeError(f"Vertex REST API failed for stage {stage}: {exc}") from exc

            chunks = self._chunks_from_response(raw_text)
            
            error_chunk = next((c for c in chunks if "error" in c), None)
            if error_chunk:
                err = error_chunk["error"]
                code = int(err.get("code", 500))
                msg = err.get("message", str(err))
                if code in {427, 429}:
                    if attempt == 1:
                        print(f"[{'VERTEX_RETRY' if 'vertex' in self.__class__.__name__.lower() else 'IMAGE_RETRY'}] Got 427/429 in stream. Waiting exactly 30s as instructed.")
                        time.sleep(30.0)
                        continue
                    else:
                        raise RuntimeError(f"Vertex API failed after 30s wait (in stream): HTTP {code}: {msg}")
                
                last_error = RuntimeError(f"Vertex API error in stream: HTTP {code}: {msg}")
                retryable = code in self.retry_status_codes and attempt < attempts
                if retryable:
                    delay = min(self.retry_max_sleep_seconds, sleep_seconds)
                    delay += random.uniform(0.0, min(1.0, max(0.0, delay * 0.15)))
                    print(
                        f"[VERTEX_RETRY] backend={backend_config['backend']} stage={stage} model={model} attempt={attempt}/{attempts} "
                        f"http={code} (in stream) sleep={delay:.1f}s",
                        flush=True,
                    )
                    time.sleep(delay)
                    sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                    continue
                raise last_error

            text = self._text_from_chunks(chunks)
            with open("/tmp/vertex_debug_raw.log", "a") as f:
                f.write(f"\n--- RAW TEXT START ---\n{raw_text}\n--- RAW TEXT END ---\n")
                f.write(f"\n--- EXTRACTED TEXT START ---\n{text}\n--- EXTRACTED TEXT END ---\n")
            
            parsed = first_json_value_from_text(text)
            if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
                parsed = parsed[0]
            if isinstance(parsed, dict):
                return parsed

            last_error = RuntimeError(
                f"Vertex REST API did not return a JSON object for stage {stage}. Raw text: {text[:1000]}"
            )
            last_body = text[:1000]
            if attempt < attempts:
                invalid_json_retry = True
                delay = min(self.retry_max_sleep_seconds, sleep_seconds)
                delay += random.uniform(0.0, min(1.0, max(0.0, delay * 0.15)))
                print(
                    f"[VERTEX_RETRY] backend={backend_config['backend']} stage={stage} model={model} attempt={attempt}/{attempts} "
                    f"reason=invalid_json raw_chars={len(text)} sleep={delay:.1f}s",
                    flush=True,
                )
                time.sleep(delay)
                sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                continue
            raise last_error
        raise RuntimeError(f"Vertex REST API failed for stage {stage}: {last_error}: {last_body}")

    def generate_compact_json(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema: dict[str, Any],
        stage: str,
    ) -> dict[str, Any]:
        full_prompt = (
            f"{system_instruction}\n"
            f"JSON shape: {_json_dumps(schema)}\n"
            f"{prompt}\n"
            "Return one minified JSON object only, not an array. No markdown. No extra keys."
        )
        return self._generate_json_from_prompt(full_prompt, stage=stage)

    def generate_text(
        self,
        *,
        system_instruction: str,
        prompt: str,
        stage: str,
    ) -> str:
        full_prompt = f"[System]\n{system_instruction}\n\n[User]\n{prompt}\n"
        return self._generate_text_from_prompt(full_prompt, stage=stage)

    def _generate_text_from_prompt(
        self,
        full_prompt: str,
        *,
        stage: str,
    ) -> str:
        active_backend_name = self._active_backend_name
        try:
            text = self._generate_text_from_prompt_with_backend(
                full_prompt,
                stage=stage,
                backend_name=active_backend_name,
            )
            if active_backend_name == "primary":
                self._consecutive_primary_failures = 0
            return text
        except Exception as primary_exc:
            if active_backend_name != "primary" or "fallback" not in self._backend_configs:
                raise
            self._consecutive_primary_failures += 1
            should_switch = (
                self.fallback_after_consecutive_errors > 0
                and self._consecutive_primary_failures >= self.fallback_after_consecutive_errors
            )
            fallback_backend_name = "fallback"
            if should_switch:
                self._active_backend_name = fallback_backend_name
            try:
                text = self._generate_text_from_prompt_with_backend(
                    full_prompt,
                    stage=stage,
                    backend_name=fallback_backend_name,
                )
                return text
            except Exception:
                raise primary_exc

    def _generate_text_from_prompt_with_backend(
        self,
        full_prompt: str,
        *,
        stage: str,
        backend_name: str,
    ) -> str:
        attempts = max(1, self.retry_max_attempts)
        last_error: Exception | None = None
        last_body = ""
        model = self._model_for_stage(stage)
        backend_config = self._backend_configs[backend_name]
        sleep_seconds = max(0.0, self.retry_initial_sleep_seconds)
        for attempt in range(1, attempts + 1):
            payload = self._payload(full_prompt, stage=stage, backend_name=backend_name, json_mode=False)
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                self._url(model, backend_name=backend_name),
                data=data,
                headers=self._headers(backend_name),
                method="POST",
            )
            try:
                # Controlled pacing delay to prevent Vertex API 429 rate limit errors
                pacing_sleep = float(backend_config.get("pacing_sleep_seconds", 1.2))
                if pacing_sleep > 0.0:
                    time.sleep(pacing_sleep)
                print(f"Vertex request to {request.full_url} (timeout={backend_config['timeout_seconds']})", file=open("/tmp/vertex_debug.log", "a"), flush=True)
                with urllib.request.urlopen(request, timeout=int(backend_config["timeout_seconds"])) as response:
                    raw_text = response.read().decode("utf-8", errors="replace")
                    print("Vertex request finished", file=open("/tmp/vertex_debug.log", "a"), flush=True)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = exc
                last_body = body
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
                        f"[VERTEX_RETRY] backend={backend_config['backend']} stage={stage} model={model} attempt={attempt}/{attempts} "
                        f"http={exc.code} sleep={delay:.1f}s",
                        flush=True,
                    )
                    time.sleep(delay)
                    sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                    continue
                raise RuntimeError(f"Vertex REST API failed for stage {stage}: HTTP {exc.code}: {body}") from exc
            except (TimeoutError, socket.timeout) as exc:
                last_error = exc
                retryable = attempt < attempts
                if retryable:
                    delay = min(self.retry_max_sleep_seconds, sleep_seconds)
                    delay += random.uniform(0.0, min(1.0, max(0.0, delay * 0.15)))
                    print(
                        f"[VERTEX_RETRY] backend={backend_config['backend']} stage={stage} model={model} attempt={attempt}/{attempts} "
                        f"timeout={exc} sleep={delay:.1f}s",
                        flush=True,
                    )
                    time.sleep(delay)
                    sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                    continue
                raise RuntimeError(f"Vertex REST API failed for stage {stage}: timeout: {exc}") from exc
            except urllib.error.URLError as exc:
                last_error = exc
                retryable = attempt < attempts
                if retryable:
                    delay = min(self.retry_max_sleep_seconds, sleep_seconds)
                    delay += random.uniform(0.0, min(1.0, max(0.0, delay * 0.15)))
                    print(
                        f"[VERTEX_RETRY] backend={backend_config['backend']} stage={stage} model={model} attempt={attempt}/{attempts} "
                        f"url_error={exc.reason} sleep={delay:.1f}s",
                        flush=True,
                    )
                    time.sleep(delay)
                    sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                    continue
                raise RuntimeError(f"Vertex REST API failed for stage {stage}: {exc}") from exc

            text = self._text_from_chunks(self._chunks_from_response(raw_text))
            return text
        raise RuntimeError(f"Vertex REST API failed for stage {stage}: {last_error}: {last_body}")



    def stream_generate_compact_json_field(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema: dict[str, Any],
        stage: str,
        stream_field: str = "response_text",
    ):
        full_prompt = (
            f"{system_instruction}\n"
            f"JSON shape: {_json_dumps(schema)}\n"
            f"{prompt}\n"
            f"Return one minified JSON object only, not an array. No markdown. No extra keys.\n"
            f"Crucial: The very first key in the JSON object must be \"{stream_field}\" so we can stream it immediately."
        )
        yield from self._stream_json_field_from_prompt(full_prompt, stage=stage, stream_field=stream_field)

    def _stream_json_field_from_prompt(
        self,
        full_prompt: str,
        *,
        stage: str,
        stream_field: str,
    ):
        active_backend_name = self._active_backend_name
        try:
            yield from self._stream_json_field_from_prompt_with_backend(
                full_prompt,
                stage=stage,
                backend_name=active_backend_name,
                stream_field=stream_field,
            )
            if active_backend_name == "primary":
                self._consecutive_primary_failures = 0
        except Exception as primary_exc:
            if active_backend_name != "primary" or "fallback" not in self._backend_configs:
                raise
            self._consecutive_primary_failures += 1
            should_switch = (
                self.fallback_after_consecutive_errors > 0
                and self._consecutive_primary_failures >= self.fallback_after_consecutive_errors
            )
            fallback_backend_name = "fallback"
            if should_switch:
                self._active_backend_name = fallback_backend_name
            try:
                yield from self._stream_json_field_from_prompt_with_backend(
                    full_prompt,
                    stage=stage,
                    backend_name=fallback_backend_name,
                    stream_field=stream_field,
                )
            except Exception:
                raise primary_exc

    def _stream_json_field_from_prompt_with_backend(
        self,
        full_prompt: str,
        *,
        stage: str,
        backend_name: str,
        stream_field: str,
    ):
        attempts = max(1, self.retry_max_attempts)
        last_error: Exception | None = None
        last_body = ""
        model = self._model_for_stage(stage)
        backend_config = self._backend_configs[backend_name]
        sleep_seconds = max(0.0, self.retry_initial_sleep_seconds)
        
        for attempt in range(1, attempts + 1):
            payload = self._payload(full_prompt, stage=stage, backend_name=backend_name, json_mode=True)
            data = json.dumps(payload).encode("utf-8")
            
            url = self._url(model, backend_name=backend_name)
            if "alt=sse" not in url:
                url += "&alt=sse" if "?" in url else "?alt=sse"
            if "streamGenerateContent" not in url:
                url = url.replace("generateContent", "streamGenerateContent")
                
            request = urllib.request.Request(
                url,
                data=data,
                headers=self._headers(backend_name),
                method="POST",
            )
            try:
                pacing_sleep = float(backend_config.get("pacing_sleep_seconds", 1.2))
                if pacing_sleep > 0.0:
                    time.sleep(pacing_sleep)
                
                extractor = StreamingJsonStringExtractor(stream_field)
                accumulated_text = ""
                raw_sse_text = ""
                
                print(f"Vertex request to {request.full_url} (timeout={backend_config['timeout_seconds']})", file=open("/tmp/vertex_debug.log", "a"), flush=True)
                with urllib.request.urlopen(request, timeout=int(backend_config["timeout_seconds"])) as response:
                    for line in response:
                        line_str = line.decode("utf-8", errors="replace").strip()
                        raw_sse_text += line_str + "\n"
                        if line_str.startswith("data:"):
                            chunk_data_str = line_str[5:].strip()
                            if chunk_data_str == "[DONE]":
                                continue
                            try:
                                chunk_json = json.loads(chunk_data_str)
                                for cand in chunk_json.get("candidates", []):
                                    for part in cand.get("content", {}).get("parts", []):
                                        if "text" in part:
                                            accumulated_text += part["text"]
                                            new_text = extractor.process_chunk(accumulated_text)
                                            yield (new_text, False, None)
                            except Exception:
                                continue
                                
                text = self._text_from_chunks(self._chunks_from_response(raw_sse_text))
                parsed = first_json_value_from_text(text)
                if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
                    parsed = parsed[0]
                if isinstance(parsed, dict):
                    # yield the final text just in case, then the parsed dict
                    yield (extractor.extracted_text, True, parsed)
                    return
                
                with open("vertex_error_raw_text_dump.txt", "w") as f:
                    f.write(text)
                last_error = RuntimeError(f"Vertex REST API did not return a JSON object for stage {stage}. Raw text dumped to vertex_error_raw_text_dump.txt")
                last_body = text

            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = exc
                last_body = body
            except (TimeoutError, socket.timeout) as exc:
                last_error = exc
            except urllib.error.URLError as exc:
                last_error = exc
                
            retryable = attempt < attempts
            if retryable:
                delay = min(self.retry_max_sleep_seconds, sleep_seconds)
                delay += random.uniform(0.0, min(1.0, max(0.0, delay * 0.15)))
                time.sleep(delay)
                sleep_seconds = max(delay, sleep_seconds) * max(1.0, self.retry_backoff_multiplier)
                continue
            
        raise RuntimeError(f"Vertex REST API streaming failed for stage {stage}: {last_error}: {last_body}")

