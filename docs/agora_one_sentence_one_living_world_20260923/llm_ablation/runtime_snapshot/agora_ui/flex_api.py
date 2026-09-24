"""Shared request/response types and app helpers for Flex API servers."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from typing import Any, Optional, Protocol, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FlexExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_type: str = "text"
    model: Optional[str] = None
    system_instruction: str = ""
    prompt: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    temperature: float = 0.7
    max_output_tokens: int = 512
    thinking_level: str = "medium"
    response_schema: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_request(self) -> "FlexExecuteRequest":
        task_type = str(self.task_type or "").strip().lower()
        if task_type not in {"text", "json"}:
            raise ValueError("task_type must be 'text' or 'json'")
        self.task_type = task_type
        if not str(self.prompt).strip() and not self.messages:
            raise ValueError("either prompt or messages must be provided")
        if int(self.max_output_tokens) <= 0:
            raise ValueError("max_output_tokens must be > 0")
        return self


class FlexExecuteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    output_text: str = ""
    output_json: Optional[Any] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ChatCompletionsRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    messages: list[dict[str, Any]] = Field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 512
    think: bool = False
    enable_visual_generation: bool = False
    model: Optional[str] = None
    response_format: Optional[dict[str, Any]] = None


class FlexProvider(Protocol):
    provider_name: str
    default_model: str

    def list_models(self) -> list[dict[str, Any]]:
        ...

    def diagnostics(self) -> dict[str, Any]:
        ...

    def execute(self, request: FlexExecuteRequest) -> FlexExecuteResponse:
        ...


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "")).strip().lower()
            if item_type == "text":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
            elif item_type in {"image_url", "image"}:
                chunks.append("[image attached]")
        return "\n".join(chunks).strip()
    return str(content).strip() if content is not None else ""


def build_messages_from_request(request: FlexExecuteRequest) -> list[dict[str, Any]]:
    messages = [dict(item) for item in request.messages]
    if not messages:
        messages = [{"role": "user", "content": request.prompt}]
    if request.system_instruction.strip():
        first_role = str(messages[0].get("role", "")).strip().lower() if messages else ""
        if first_role == "system":
            existing = extract_text_from_content(messages[0].get("content", ""))
            merged = "\n\n".join(
                part for part in [request.system_instruction.strip(), existing] if part
            )
            messages[0]["content"] = merged
        else:
            messages.insert(
                0,
                {"role": "system", "content": request.system_instruction.strip()},
            )
    return messages


def split_system_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_chunks: list[str] = []
    non_system: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", "user")).strip().lower()
        if role == "system":
            text = extract_text_from_content(message.get("content", ""))
            if text:
                system_chunks.append(text)
            continue
        non_system.append(message)
    if not non_system:
        non_system = [{"role": "user", "content": "Hello."}]
    return "\n\n".join(system_chunks).strip(), non_system


def messages_to_transcript(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role", "user")).strip().lower() or "user"
        text = extract_text_from_content(message.get("content", ""))
        if not text:
            continue
        lines.append(f"{role.upper()}: {text}")
    return "\n\n".join(lines).strip()


def first_json_value_from_text(text: str) -> Optional[Any]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    fence_match = _CODE_FENCE_RE.search(cleaned)
    if fence_match is not None:
        cleaned = fence_match.group(1).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    def _try_balanced_parse(source: str, open_char: str, close_char: str) -> Optional[Any]:
        start = source.find(open_char)
        if start < 0:
            return None
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(source)):
            char = source[index]
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == open_char:
                depth += 1
                continue
            if char == close_char:
                depth -= 1
                if depth == 0:
                    candidate = source[start : index + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        return None
        return None

    first_object = cleaned.find("{")
    first_array = cleaned.find("[")
    parse_order: list[tuple[str, str]] = []
    if first_object >= 0 and (first_array < 0 or first_object <= first_array):
        parse_order = [("{", "}"), ("[", "]")]
    elif first_array >= 0:
        parse_order = [("[", "]"), ("{", "}")]
    for open_char, close_char in parse_order:
        parsed = _try_balanced_parse(cleaned, open_char, close_char)
        if parsed is not None:
            return parsed
    return None


def json_path_lookup(payload: Any, path: str) -> Any:
    current = payload
    for raw_part in [part for part in str(path or "").split(".") if part]:
        if isinstance(current, list):
            index = int(raw_part)
            current = current[index]
            continue
        if isinstance(current, dict):
            current = current[raw_part]
            continue
        raise KeyError(f"cannot descend into {type(current).__name__} at '{raw_part}'")
    return current


def _env_first(keys: Tuple[str, ...], default: str) -> str:
    for key in keys:
        value = os.getenv(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _env_first_int(keys: Tuple[str, ...], default: int) -> int:
    raw = _env_first(keys, str(default))
    try:
        return int(raw)
    except Exception:
        return default


class FlexServerGuard:
    """Shared in-process guard for all provider-backed Flex server entrypoints."""

    _DEFAULT_MAX_IN_FLIGHT_BY_PROVIDER = {
        "vertex_ai": 2,
        "gemini_ai_studio": 10,
        "gpt_api": 5,
        "generic_api_call": 2,
    }
    _PROVIDER_ENV_PREFIXES = {
        "vertex_ai": ("AGORA_VERTEX", "AGORA_VERTEX_AI"),
        "gemini_ai_studio": ("AGORA_AI_STUDIO", "AGORA_GEMINI", "AGORA_GEMINI_AI_STUDIO"),
        "gpt_api": ("AGORA_GPT", "AGORA_OPENAI"),
        "generic_api_call": ("AGORA_GENERIC",),
    }

    def __init__(self, provider_name: str = "") -> None:
        provider_key = str(provider_name or "").strip().lower()
        provider_prefixes = self._PROVIDER_ENV_PREFIXES.get(provider_key, ())
        provider_max_in_flight_envs = tuple(
            f"{prefix}_MAX_IN_FLIGHT" for prefix in provider_prefixes
        ) + tuple(
            f"{prefix}_FLEX_MAX_IN_FLIGHT" for prefix in provider_prefixes
        )
        provider_rpm_envs = tuple(
            f"{prefix}_REQUESTS_PER_MINUTE" for prefix in provider_prefixes
        ) + tuple(
            f"{prefix}_FLEX_REQUESTS_PER_MINUTE" for prefix in provider_prefixes
        )
        default_max_in_flight = self._DEFAULT_MAX_IN_FLIGHT_BY_PROVIDER.get(provider_key, 0)
        max_in_flight = _env_first_int(
            (
                *provider_max_in_flight_envs,
                "AGORA_FLEX_MAX_IN_FLIGHT",
                "AGORA_FLEX_CONCURRENCY_LIMIT",
            ),
            default_max_in_flight,
        )
        requests_per_minute = _env_first_int(
            (
                *provider_rpm_envs,
                "AGORA_FLEX_REQUESTS_PER_MINUTE",
                "AGORA_FLEX_RATE_LIMIT_RPM",
            ),
            0,
        )
        self.provider_name = provider_key
        self.max_in_flight = max(0, int(max_in_flight))
        self.requests_per_minute = max(0, int(requests_per_minute))
        self.bad_request_policy = _env_first(
            ("AGORA_FLEX_BAD_REQUEST_POLICY",),
            "fail",
        ).strip().lower() or "fail"
        self._semaphore = (
            threading.BoundedSemaphore(self.max_in_flight)
            if self.max_in_flight > 0
            else None
        )
        self._rate_lock = threading.Lock()
        self._recent_requests: deque[float] = deque()

    def diagnostics(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "max_in_flight": self.max_in_flight,
            "requests_per_minute": self.requests_per_minute,
            "bad_request_policy": self.bad_request_policy,
        }

    def _rate_limited(self) -> bool:
        if self.requests_per_minute <= 0:
            return False
        now = time.monotonic()
        window_start = now - 60.0
        with self._rate_lock:
            while self._recent_requests and self._recent_requests[0] < window_start:
                self._recent_requests.popleft()
            if len(self._recent_requests) >= self.requests_per_minute:
                return True
            self._recent_requests.append(now)
        return False

    @contextmanager
    def request_slot(self) -> Any:
        if self._rate_limited():
            yield False, "rate_limit_exceeded"
            return
        if self._semaphore is None:
            yield True, ""
            return
        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            yield False, "concurrency_limit_exceeded"
            return
        try:
            yield True, ""
        finally:
            self._semaphore.release()


def create_flex_app(provider: FlexProvider, *, title: Optional[str] = None) -> Any:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    app = FastAPI(title=title or f"{provider.provider_name} Flex Server", version="1.0.0")
    guard = FlexServerGuard(provider.provider_name)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": "bad_request",
                "skipped": False,
                "policy": guard.bad_request_policy,
                "path": str(request.url.path),
                "detail": exc.errors(),
            },
        )

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "provider": provider.provider_name,
            "default_model": provider.default_model,
            "diagnostics": {
                **provider.diagnostics(),
                "server_guard": guard.diagnostics(),
            },
        }

    @app.get("/v1/models")
    def list_models() -> dict[str, Any]:
        return {"object": "list", "data": provider.list_models()}

    @app.post("/v1/flex/execute")
    def flex_execute(request: FlexExecuteRequest) -> dict[str, Any]:
        with guard.request_slot() as (allowed, reason):
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": reason,
                        "skipped": False,
                        "provider": provider.provider_name,
                    },
                )
            try:
                result = provider.execute(request)
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "error": "provider_execute_failed",
                        "skipped": False,
                        "provider": provider.provider_name,
                        "message": str(exc),
                    },
                ) from exc
        return result.model_dump()

    @app.post("/v1/chat/completions")
    def chat_completions(request: ChatCompletionsRequest) -> dict[str, Any]:
        task_type = "text"
        response_format = request.response_format or {}
        if str(response_format.get("type", "")).strip().lower() in {"json_object", "json_schema"}:
            task_type = "json"
        with guard.request_slot() as (allowed, reason):
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": reason,
                        "skipped": False,
                        "provider": provider.provider_name,
                    },
                )
            try:
                result = provider.execute(
                    FlexExecuteRequest(
                        task_type=task_type,
                        model=request.model,
                        messages=request.messages,
                        temperature=float(request.temperature),
                        max_output_tokens=int(request.max_tokens),
                        thinking_level="medium" if bool(request.think) else "none",
                    )
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "error": "chat_alias_failed",
                        "skipped": False,
                        "provider": provider.provider_name,
                        "message": str(exc),
                    },
                ) from exc
        content = result.output_text
        if not content and result.output_json is not None:
            content = json.dumps(result.output_json, ensure_ascii=False)
        created = int(time.time())
        meta = dict(result.meta)
        meta.setdefault("provider", result.provider)
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": created,
            "model": result.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "flex_meta": meta,
            "bagel_meta": meta,
        }

    return app


def run_flex_app(
    app: Any,
    *,
    host_envs: Tuple[str, ...] = ("AGORA_FLEX_HOST", "AGORA_GEMINI_HOST"),
    port_envs: Tuple[str, ...] = ("AGORA_FLEX_PORT", "AGORA_GEMINI_PORT"),
) -> None:
    import uvicorn

    host = _env_first(host_envs, "127.0.0.1")
    port = _env_first_int(port_envs, 8000)
    uvicorn.run(app, host=host, port=port)
