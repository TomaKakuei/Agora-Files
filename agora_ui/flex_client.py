"""HTTP client for the unified Flex API."""

from __future__ import annotations

import asyncio
import functools
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import requests

from .flex_api import FlexExecuteRequest, first_json_value_from_text


class FlexClient:
    """Thin client for `/v1/flex/execute` and its OpenAI-compatible alias."""

    def __init__(self, api_url: str = "http://127.0.0.1:8000/v1") -> None:
        self.api_url = api_url.rstrip("/") if api_url else "http://127.0.0.1:8000/v1"
        self.last_response: dict[str, Any] = {}

    def healthz(self, timeout_seconds: float = 10.0) -> dict[str, Any]:
        response = requests.get(
            f"{self.api_url.rsplit('/v1', 1)[0]}/healthz",
            timeout=max(1.0, float(timeout_seconds)),
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    def list_models(self, timeout_seconds: float = 10.0) -> list[dict[str, Any]]:
        response = requests.get(
            f"{self.api_url}/models",
            timeout=max(1.0, float(timeout_seconds)),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return []
        models = data.get("data")
        return models if isinstance(models, list) else []

    def execute(
        self,
        *,
        task_type: str,
        prompt: str = "",
        messages: Optional[list[dict[str, Any]]] = None,
        system_instruction: str = "",
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_output_tokens: int = 512,
        thinking_level: str = "medium",
        response_schema: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
        timeout_seconds: float = 120.0,
    ) -> dict[str, Any]:
        request = FlexExecuteRequest(
            task_type=task_type,
            prompt=prompt,
            messages=messages or [],
            system_instruction=system_instruction,
            model=model,
            temperature=float(temperature),
            max_output_tokens=int(max_output_tokens),
            thinking_level=thinking_level,
            response_schema=response_schema,
            metadata=metadata or {},
        )
        response = requests.post(
            f"{self.api_url}/flex/execute",
            json=request.model_dump(),
            timeout=max(1.0, float(timeout_seconds)),
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("invalid flex response payload")
        self.last_response = data
        return data

    def generate_text(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        model: Optional[str] = None,
        temperature: float = 0.6,
        max_output_tokens: int = 512,
        thinking_level: str = "medium",
        timeout_seconds: float = 120.0,
    ) -> str:
        payload = self.execute(
            task_type="text",
            prompt=prompt,
            system_instruction=system_instruction,
            model=model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_level=thinking_level,
            timeout_seconds=timeout_seconds,
        )
        return str(payload.get("output_text", "")).strip()

    def generate_json(
        self,
        *,
        prompt: str = "",
        messages: Optional[list[dict[str, Any]]] = None,
        system_instruction: str = "",
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
        thinking_level: str = "medium",
        response_schema: Optional[dict[str, Any]] = None,
        timeout_seconds: float = 120.0,
    ) -> dict[str, Any]:
        payload = self.execute(
            task_type="json",
            prompt=prompt,
            messages=messages or [],
            system_instruction=system_instruction,
            model=model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_level=thinking_level,
            response_schema=response_schema,
            timeout_seconds=timeout_seconds,
        )
        output_json = payload.get("output_json")
        if isinstance(output_json, dict):
            return output_json
        if output_json is not None:
            raise ValueError("flex json response is not an object")
        parsed = first_json_value_from_text(str(payload.get("output_text", "")))
        if not isinstance(parsed, dict):
            raise ValueError("flex json response does not contain a JSON object")
        return parsed

    def chat_completions(
        self,
        *,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        timeout_seconds: float = 120.0,
    ) -> str:
        response = requests.post(
            f"{self.api_url}/chat/completions",
            json={
                "messages": messages,
                "model": model,
                "temperature": float(temperature),
                "max_tokens": int(max_tokens),
            },
            timeout=max(1.0, float(timeout_seconds)),
        )
        response.raise_for_status()
        data = response.json()
        self.last_response = data if isinstance(data, dict) else {}
        try:
            choices = data["choices"]
            message = choices[0]["message"]
            content = message["content"]
        except Exception as exc:
            raise ValueError(f"invalid chat completion payload ({exc})") from exc
        return str(content).strip()

    def dump_last_response_json(self) -> str:
        return json.dumps(self.last_response, ensure_ascii=False, indent=2)


class AsyncFlexClient:
    """Async wrapper around FlexClient with bounded concurrency."""

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8000/v1",
        *,
        concurrency_limit: int = 10,
    ) -> None:
        self.sync_client = FlexClient(api_url=api_url)
        self.api_url = self.sync_client.api_url
        self.concurrency_limit = max(1, int(concurrency_limit))
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._semaphore_loop: Optional[asyncio.AbstractEventLoop] = None
        self._executor = ThreadPoolExecutor(
            max_workers=self.concurrency_limit,
            thread_name_prefix="agora_flex",
        )

    def _get_semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._semaphore_loop is not loop:
            self._semaphore = asyncio.Semaphore(self.concurrency_limit)
            self._semaphore_loop = loop
        return self._semaphore

    async def _run_blocking(
        self,
        func: Any,
        *,
        wait_timeout_seconds: float,
        **kwargs: Any,
    ) -> Any:
        loop = asyncio.get_running_loop()
        call = functools.partial(func, **kwargs)
        return await asyncio.wait_for(
            loop.run_in_executor(self._executor, call),
            timeout=max(1.0, float(wait_timeout_seconds) + 1.0),
        )

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    async def execute(
        self,
        *,
        task_type: str,
        prompt: str = "",
        messages: Optional[list[dict[str, Any]]] = None,
        system_instruction: str = "",
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_output_tokens: int = 512,
        thinking_level: str = "medium",
        response_schema: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
        timeout_seconds: float = 120.0,
    ) -> dict[str, Any]:
        async with self._get_semaphore():
            return await self._run_blocking(
                self.sync_client.execute,
                wait_timeout_seconds=timeout_seconds,
                task_type=task_type,
                prompt=prompt,
                messages=messages,
                system_instruction=system_instruction,
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                thinking_level=thinking_level,
                response_schema=response_schema,
                metadata=metadata,
                timeout_seconds=timeout_seconds,
            )

    async def generate_json(
        self,
        *,
        prompt: str = "",
        messages: Optional[list[dict[str, Any]]] = None,
        system_instruction: str = "",
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
        thinking_level: str = "medium",
        response_schema: Optional[dict[str, Any]] = None,
        timeout_seconds: float = 120.0,
    ) -> dict[str, Any]:
        async with self._get_semaphore():
            return await self._run_blocking(
                self.sync_client.generate_json,
                wait_timeout_seconds=timeout_seconds,
                prompt=prompt,
                messages=messages,
                system_instruction=system_instruction,
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                thinking_level=thinking_level,
                response_schema=response_schema,
                timeout_seconds=timeout_seconds,
            )

    async def generate_text(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        model: Optional[str] = None,
        temperature: float = 0.6,
        max_output_tokens: int = 512,
        thinking_level: str = "medium",
        timeout_seconds: float = 120.0,
    ) -> str:
        async with self._get_semaphore():
            return await self._run_blocking(
                self.sync_client.generate_text,
                wait_timeout_seconds=timeout_seconds,
                prompt=prompt,
                system_instruction=system_instruction,
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                thinking_level=thinking_level,
                timeout_seconds=timeout_seconds,
            )
