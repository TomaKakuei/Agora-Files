"""Provider implementations for the unified Flex API."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import requests

from .flex_api import (
    FlexExecuteRequest,
    FlexExecuteResponse,
    build_messages_from_request,
    extract_text_from_content,
    first_json_value_from_text,
    json_path_lookup,
    messages_to_transcript,
    split_system_messages,
)
from .jsonc_utils import load_jsonc_path


THINKING_BUDGET_BY_LEVEL = {
    "none": 0,
    "low": 1024,
    "medium": 2048,
    "high": 4096,
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value.strip())
    except Exception:
        return default
    return max(minimum, parsed)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value.strip())
    except Exception:
        return default
    return max(minimum, parsed)


def _json_schema_instruction(response_schema: Optional[dict[str, Any]]) -> str:
    instruction = "Return JSON only with no markdown fences and no extra commentary."
    if response_schema:
        instruction += (
            "\nFollow this target schema as closely as possible:\n"
            + json.dumps(response_schema, ensure_ascii=False, indent=2)
        )
    return instruction


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("Gemini response missing candidates")
    first = candidates[0]
    if not isinstance(first, dict):
        raise RuntimeError("Gemini response candidate is not an object")
    content = first.get("content")
    if not isinstance(content, dict):
        raise RuntimeError("Gemini response missing content")
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise RuntimeError("Gemini response missing parts")
    chunks: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    output = "\n".join(chunks).strip()
    if not output:
        raise RuntimeError("Gemini response returned empty text")
    return output


class BaseFlexProvider:
    provider_name = "base"
    default_model = "unknown"

    def __init__(
        self,
        *,
        default_model: str,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        self.default_model = default_model.strip() or "unknown"
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_retries = max(1, int(max_retries))

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {
                "id": self.default_model,
                "object": "model",
                "created": 0,
                "owned_by": self.provider_name,
            }
        ]

    def diagnostics(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "default_model": self.default_model,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
        }

    def execute(self, request: FlexExecuteRequest) -> FlexExecuteResponse:
        raise NotImplementedError

    def _effective_model(self, request: FlexExecuteRequest) -> str:
        return (request.model or self.default_model).strip() or self.default_model

    def _coerce_json_output(self, text: str) -> Any:
        parsed = first_json_value_from_text(text)
        if parsed is None:
            raise RuntimeError("provider did not return valid JSON text")
        return parsed


class GeminiAIStudioProvider(BaseFlexProvider):
    provider_name = "gemini_ai_studio"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        default_model: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> None:
        super().__init__(
            default_model=default_model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        self.api_key = api_key.strip()
        self.base_url = base_url.strip().rstrip("/")

    @classmethod
    def from_env(cls) -> "GeminiAIStudioProvider":
        return cls(
            api_key=(
                os.getenv("AGORA_AISTUDIO_API_KEY", "").strip()
                or os.getenv("AGORA_GEMINI_API_KEY", "").strip()
                or os.getenv("GEMINI_API_KEY", "").strip()
                or os.getenv("GOOGLE_API_KEY", "").strip()
            ),
            base_url=(
                os.getenv("AGORA_GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
                .strip()
                .rstrip("/")
            ),
            default_model=(
                os.getenv("AGORA_GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
                or "gemini-3.1-flash-lite"
            ),
            timeout_seconds=_env_float("AGORA_GEMINI_TIMEOUT_SECONDS", 120.0, 1.0),
            max_retries=_env_int("AGORA_GEMINI_MAX_RETRIES", 2, 1),
        )

    def diagnostics(self) -> dict[str, Any]:
        data = super().diagnostics()
        data.update({"base_url": self.base_url})
        return data

    def _fallback_model(self, requested_model: str) -> str:
        fallback = (
            os.getenv("AGORA_GEMINI_FALLBACK_MODEL", "").strip()
            or os.getenv("AGORA_GEMINI_MODEL", "").strip()
            or "gemini-3.1-flash-lite"
        )
        fallback = fallback.strip() or "gemini-3.1-flash-lite"
        if fallback == requested_model:
            return ""
        return fallback

    def execute(self, request: FlexExecuteRequest) -> FlexExecuteResponse:
        if not self.api_key:
            raise RuntimeError("Gemini API key is required")

        model = self._effective_model(request)
        messages = build_messages_from_request(request)
        system_instruction, non_system = split_system_messages(messages)
        if request.task_type == "json":
            system_instruction = "\n\n".join(
                part for part in [system_instruction, _json_schema_instruction(request.response_schema)] if part
            )
        contents: list[dict[str, Any]] = []
        for message in non_system:
            role = str(message.get("role", "user")).strip().lower()
            text = extract_text_from_content(message.get("content", ""))
            if not text:
                continue
            gemini_role = "model" if role == "assistant" else "user"
            if contents and contents[-1].get("role") == gemini_role:
                contents[-1].setdefault("parts", []).append({"text": text})
            else:
                contents.append({"role": gemini_role, "parts": [{"text": text}]})
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Hello."}]}]

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": _clamp(float(request.temperature), 0.0, 2.0),
                "maxOutputTokens": max(1, int(request.max_output_tokens)),
            },
        }
        if str(model).strip().lower().startswith("gemini-3"):
            level = str(request.thinking_level).strip().upper() or "LOW"
            payload["generationConfig"]["thinkingConfig"] = {"thinkingLevel": level}
        else:
            budget = THINKING_BUDGET_BY_LEVEL.get(str(request.thinking_level).strip().lower(), 1024)
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": int(budget)}
            
        if request.task_type == "json":
            payload["generationConfig"]["responseMimeType"] = "application/json"
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        last_error = "unknown error"
        attempted_models: list[str] = []
        fallback_model = self._fallback_model(model)
        model_candidates = [model]
        if fallback_model:
            model_candidates.append(fallback_model)
        for model_name in model_candidates:
            endpoint = f"{self.base_url}/models/{model_name}:generateContent"
            attempted_models.append(model_name)
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = requests.post(
                        endpoint,
                        params={"key": self.api_key},
                        json=payload,
                        timeout=self.timeout_seconds,
                    )
                    if response.status_code >= 400:
                        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:400]}")
                    body = response.json()
                    if not isinstance(body, dict):
                        raise RuntimeError("Gemini payload is not an object")
                    output_text = _extract_gemini_text(body)
                    output_json = None
                    if request.task_type == "json":
                        output_json = self._coerce_json_output(output_text)
                    meta = {
                        "endpoint": endpoint,
                        "task_type": request.task_type,
                        "response_mime_type": payload["generationConfig"].get("responseMimeType", "text/plain"),
                    }
                    if model_name != model:
                        meta["fallback_from_model"] = model
                    return FlexExecuteResponse(
                        provider=self.provider_name,
                        model=model_name,
                        output_text=output_text,
                        output_json=output_json,
                        meta=meta,
                    )
                except Exception as exc:
                    last_error = str(exc)
                    not_found = "not found" in last_error.lower() or "not supported" in last_error.lower()
                    if attempt < self.max_retries:
                        time.sleep(0.5 * attempt)
                        continue
                    if model_name != model_candidates[-1] and not_found:
                        break
                    if model_name == model_candidates[-1]:
                        raise RuntimeError(last_error) from exc
                    break
        attempted_text = ", ".join(attempted_models)
        raise RuntimeError(f"{last_error} (attempted models: {attempted_text})")


class VertexAIProvider(BaseFlexProvider):
    provider_name = "vertex_ai"

    def __init__(
        self,
        *,
        project: str,
        location: str,
        default_model: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> None:
        super().__init__(
            default_model=default_model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        self.project = project.strip()
        self.location = location.strip() or "global"
        self._vertex_module: Any = None
        self._generation_config_cls: Any = None
        self._thinking_config_cls: Any = None
        self._model_cls: Any = None
        self._init_vertex()

    @classmethod
    def from_env(cls) -> "VertexAIProvider":
        return cls(
            project=(
                os.getenv("AGORA_VERTEX_PROJECT", "").strip()
                or os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
                or os.getenv("GCLOUD_PROJECT", "").strip()
            ),
            location=os.getenv("AGORA_VERTEX_LOCATION", "global").strip() or "global",
            default_model=(
                os.getenv("AGORA_GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
                or "gemini-3.1-flash-lite"
            ),
            timeout_seconds=_env_float("AGORA_GEMINI_TIMEOUT_SECONDS", 120.0, 1.0),
            max_retries=_env_int("AGORA_GEMINI_MAX_RETRIES", 2, 1),
        )

    def _init_vertex(self) -> None:
        if not self.project:
            raise RuntimeError("Vertex provider requires AGORA_VERTEX_PROJECT")
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
            try:
                from vertexai.generative_models import GenerationConfig
            except Exception:
                GenerationConfig = None
            try:
                from vertexai.generative_models import ThinkingConfig
            except Exception:
                ThinkingConfig = None
        except Exception as exc:
            raise RuntimeError(
                "Vertex provider requires google-cloud-aiplatform / vertexai"
            ) from exc
        vertexai.init(project=self.project, location=self.location)
        self._vertex_module = vertexai
        self._model_cls = GenerativeModel
        self._generation_config_cls = GenerationConfig
        self._thinking_config_cls = ThinkingConfig

    def diagnostics(self) -> dict[str, Any]:
        data = super().diagnostics()
        data.update({"project": self.project, "location": self.location})
        return data

    def _build_generation_config(self, request: FlexExecuteRequest) -> Any:
        kwargs: dict[str, Any] = {
            "temperature": _clamp(float(request.temperature), 0.0, 2.0),
            "max_output_tokens": max(1, int(request.max_output_tokens)),
        }
        if request.task_type == "json":
            kwargs["response_mime_type"] = "application/json"
        budget = THINKING_BUDGET_BY_LEVEL.get(str(request.thinking_level).strip().lower(), 1024)
        thinking_obj = None
        if self._thinking_config_cls is not None:
            try:
                thinking_obj = self._thinking_config_cls(thinking_budget=int(budget))
            except Exception:
                thinking_obj = None
        kwargs["thinking_config"] = thinking_obj if thinking_obj is not None else {"thinking_budget": int(budget)}
        if self._generation_config_cls is None:
            return kwargs
        try:
            return self._generation_config_cls(**kwargs)
        except Exception:
            return kwargs

    def execute(self, request: FlexExecuteRequest) -> FlexExecuteResponse:
        if self._model_cls is None:
            raise RuntimeError("Vertex provider is not initialized")

        model_name = self._effective_model(request)
        messages = build_messages_from_request(request)
        system_instruction, non_system = split_system_messages(messages)
        transcript = messages_to_transcript(non_system)
        if request.task_type == "json":
            system_instruction = "\n\n".join(
                part for part in [system_instruction, _json_schema_instruction(request.response_schema)] if part
            )
        prompt_parts = []
        if system_instruction:
            prompt_parts.append(f"System instruction:\n{system_instruction}")
        if transcript:
            prompt_parts.append(f"Conversation:\n{transcript}")
        prompt_text = "\n\n".join(prompt_parts).strip() or "Hello."

        last_error = "unknown error"
        for attempt in range(1, self.max_retries + 1):
            try:
                model = self._model_cls(model_name)
                response = model.generate_content(
                    prompt_text,
                    generation_config=self._build_generation_config(request),
                )
                output_text = str(getattr(response, "text", "") or "").strip()
                if not output_text:
                    raise RuntimeError("Vertex response returned empty text")
                output_json = None
                if request.task_type == "json":
                    output_json = self._coerce_json_output(output_text)
                return FlexExecuteResponse(
                    provider=self.provider_name,
                    model=model_name,
                    output_text=output_text,
                    output_json=output_json,
                    meta={
                        "project": self.project,
                        "location": self.location,
                        "task_type": request.task_type,
                    },
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(0.5 * attempt)
                    continue
                raise RuntimeError(last_error) from exc
        raise RuntimeError(last_error)


class GptApiProvider(BaseFlexProvider):
    provider_name = "gpt_api"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        default_model: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> None:
        super().__init__(
            default_model=default_model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        self.api_key = api_key.strip()
        self.base_url = base_url.strip().rstrip("/")

    @classmethod
    def from_env(cls) -> "GptApiProvider":
        return cls(
            api_key=(
                os.getenv("AGORA_GPT_API_KEY", "").strip()
                or os.getenv("OPENAI_API_KEY", "").strip()
            ),
            base_url=(
                os.getenv("AGORA_GPT_BASE_URL", "").strip()
                or os.getenv("OPENAI_BASE_URL", "").strip()
                or "https://api.openai.com/v1"
            ),
            default_model=(
                os.getenv("AGORA_GPT_MODEL", "gpt-4o-mini").strip()
                or "gpt-4o-mini"
            ),
            timeout_seconds=_env_float("AGORA_GPT_TIMEOUT_SECONDS", 120.0, 1.0),
            max_retries=_env_int("AGORA_GPT_MAX_RETRIES", 2, 1),
        )

    def diagnostics(self) -> dict[str, Any]:
        data = super().diagnostics()
        data.update({"base_url": self.base_url})
        return data

    def execute(self, request: FlexExecuteRequest) -> FlexExecuteResponse:
        if not self.api_key:
            raise RuntimeError("GPT API key is required")

        model = self._effective_model(request)
        messages = build_messages_from_request(request)
        if request.task_type == "json":
            system_text, non_system = split_system_messages(messages)
            system_text = "\n\n".join(
                part for part in [system_text, _json_schema_instruction(request.response_schema)] if part
            )
            messages = [{"role": "system", "content": system_text}, *non_system]

        endpoint = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": _clamp(float(request.temperature), 0.0, 2.0),
            "max_tokens": max(1, int(request.max_output_tokens)),
        }
        if request.task_type == "json":
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error = "unknown error"
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if response.status_code >= 400:
                    detail = response.text.strip()
                    if request.task_type == "json" and payload.get("response_format"):
                        payload.pop("response_format", None)
                        continue
                    raise RuntimeError(f"HTTP {response.status_code}: {detail[:400]}")
                body = response.json()
                if not isinstance(body, dict):
                    raise RuntimeError("GPT API response is not an object")
                choices = body.get("choices")
                if not isinstance(choices, list) or not choices:
                    raise RuntimeError("GPT API response missing choices")
                first = choices[0] if isinstance(choices[0], dict) else {}
                message = first.get("message") if isinstance(first, dict) else {}
                output_text = extract_text_from_content(
                    message.get("content", "") if isinstance(message, dict) else ""
                )
                if not output_text:
                    raise RuntimeError("GPT API returned empty text")
                output_json = None
                if request.task_type == "json":
                    output_json = self._coerce_json_output(output_text)
                return FlexExecuteResponse(
                    provider=self.provider_name,
                    model=model,
                    output_text=output_text,
                    output_json=output_json,
                    meta={
                        "endpoint": endpoint,
                        "task_type": request.task_type,
                    },
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(0.5 * attempt)
                    continue
                raise RuntimeError(last_error) from exc
        raise RuntimeError(last_error)


class GenericApiProvider(BaseFlexProvider):
    provider_name = "generic_api_call"

    def __init__(
        self,
        *,
        config: dict[str, Any],
        timeout_seconds: float,
        max_retries: int,
    ) -> None:
        default_model = str(config.get("model", "")).strip() or "generic-model"
        super().__init__(
            default_model=default_model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        self.config = config

    @classmethod
    def from_env(cls) -> "GenericApiProvider":
        config_path = os.getenv("AGORA_GENERIC_FLEX_CONFIG", "").strip()
        if not config_path:
            config_path = str(
                Path(__file__).resolve().parent
                .parent
                / "data"
                / "templates"
                / "foundation"
                / "generic_flex_provider.jsonc"
            )
        config = load_jsonc_path(config_path)
        if not isinstance(config, dict):
            raise RuntimeError("generic flex config must be a JSON object")
        return cls(
            config=config,
            timeout_seconds=_env_float(
                "AGORA_GENERIC_FLEX_TIMEOUT_SECONDS",
                float(config.get("timeout_seconds", 120.0) or 120.0),
                1.0,
            ),
            max_retries=_env_int(
                "AGORA_GENERIC_FLEX_MAX_RETRIES",
                int(config.get("max_retries", 2) or 2),
                1,
            ),
        )

    def diagnostics(self) -> dict[str, Any]:
        data = super().diagnostics()
        data.update(
            {
                "base_url": str(self.config.get("base_url", "")).strip(),
                "path": str(self.config.get("path", "")).strip(),
                "method": str(self.config.get("method", "POST")).strip().upper(),
            }
        )
        return data

    def list_models(self) -> list[dict[str, Any]]:
        configured = self.config.get("models")
        if isinstance(configured, list) and configured:
            results: list[dict[str, Any]] = []
            for item in configured:
                name = str(item).strip()
                if not name:
                    continue
                results.append(
                    {
                        "id": name,
                        "object": "model",
                        "created": 0,
                        "owned_by": self.provider_name,
                    }
                )
            if results:
                return results
        return super().list_models()

    def _lookup_placeholder(self, expr: str, context: dict[str, Any]) -> Any:
        if expr.startswith("env:"):
            return os.getenv(expr.split(":", 1)[1], "")
        current: Any = context
        for part in [piece for piece in expr.split(".") if piece]:
            if isinstance(current, dict):
                current = current.get(part)
                continue
            if isinstance(current, list):
                current = current[int(part)]
                continue
            return None
        return current

    def _render_template(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {key: self._render_template(item, context) for key, item in value.items()}
        if isinstance(value, list):
            return [self._render_template(item, context) for item in value]
        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if stripped.startswith("${") and stripped.endswith("}") and stripped.count("${") == 1:
            return self._lookup_placeholder(stripped[2:-1], context)

        result = value
        start = 0
        while True:
            open_index = result.find("${", start)
            if open_index < 0:
                break
            close_index = result.find("}", open_index + 2)
            if close_index < 0:
                break
            expr = result[open_index + 2 : close_index]
            replacement = self._lookup_placeholder(expr, context)
            result = result[:open_index] + str("" if replacement is None else replacement) + result[close_index + 1 :]
            start = open_index
        return result

    def execute(self, request: FlexExecuteRequest) -> FlexExecuteResponse:
        base_url = str(self.config.get("base_url", "")).strip().rstrip("/")
        path = str(self.config.get("path", "")).strip()
        if not base_url or not path:
            raise RuntimeError("generic flex config must define base_url and path")
        endpoint = f"{base_url}{path}"
        method = str(self.config.get("method", "POST")).strip().upper() or "POST"
        request_template = self.config.get("request_template", {})
        response_text_path = str(self.config.get("response_text_path", "")).strip()
        response_json_path = str(self.config.get("response_json_path", "")).strip()

        messages = build_messages_from_request(request)
        model = self._effective_model(request)
        context = {
            "request": {
                **request.model_dump(),
                "model": model,
                "messages": messages,
                "transcript": messages_to_transcript(messages),
                "json_instruction": _json_schema_instruction(request.response_schema)
                if request.task_type == "json"
                else "",
            },
            "provider": {
                "default_model": self.default_model,
            },
        }

        headers_raw = self._render_template(self.config.get("headers", {}), context)
        headers = headers_raw if isinstance(headers_raw, dict) else {}
        auth_env = str(self.config.get("auth_env", "")).strip()
        if auth_env:
            auth_value = os.getenv(auth_env, "").strip()
            if auth_value:
                header_name = str(self.config.get("auth_header_name", "Authorization")).strip() or "Authorization"
                auth_scheme = str(self.config.get("auth_scheme", "Bearer")).strip()
                headers.setdefault(
                    header_name,
                    f"{auth_scheme} {auth_value}".strip(),
                )

        body = self._render_template(request_template, context)
        if request.task_type == "json" and isinstance(body, dict):
            body.setdefault("response_schema", request.response_schema or {})

        last_error = "unknown error"
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.request(
                    method,
                    endpoint,
                    headers=headers,
                    json=body,
                    timeout=self.timeout_seconds,
                )
                if response.status_code >= 400:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:400]}")
                try:
                    parsed_body: Any = response.json()
                except Exception:
                    parsed_body = response.text

                output_text = ""
                output_json = None
                if response_text_path:
                    output_value = json_path_lookup(parsed_body, response_text_path)
                    output_text = extract_text_from_content(output_value)
                elif isinstance(parsed_body, str):
                    output_text = parsed_body.strip()

                if response_json_path:
                    output_json = json_path_lookup(parsed_body, response_json_path)
                    if isinstance(output_json, str):
                        parsed_json = first_json_value_from_text(output_json)
                        if parsed_json is not None:
                            output_json = parsed_json

                if request.task_type == "json" and output_json is None:
                    if isinstance(parsed_body, (dict, list)):
                        output_json = parsed_body
                    else:
                        output_json = self._coerce_json_output(output_text)

                if not output_text and output_json is not None:
                    output_text = json.dumps(output_json, ensure_ascii=False)
                if not output_text and isinstance(parsed_body, (dict, list)):
                    output_text = json.dumps(parsed_body, ensure_ascii=False)
                if not output_text:
                    raise RuntimeError("generic provider response had no extractable text/json")

                return FlexExecuteResponse(
                    provider=self.provider_name,
                    model=model,
                    output_text=output_text,
                    output_json=output_json,
                    meta={
                        "endpoint": endpoint,
                        "task_type": request.task_type,
                        "response_text_path": response_text_path,
                        "response_json_path": response_json_path,
                    },
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(0.5 * attempt)
                    continue
                raise RuntimeError(last_error) from exc
        raise RuntimeError(last_error)
