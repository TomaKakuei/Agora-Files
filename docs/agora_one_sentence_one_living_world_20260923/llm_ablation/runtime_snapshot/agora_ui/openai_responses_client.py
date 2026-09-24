from __future__ import annotations

import json
import os
import random
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .flex_api import first_json_value_from_text


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _native_json_schema(value: Any) -> Any:
    """Remove null schema hints rejected by the Responses API validator."""
    if isinstance(value, dict):
        return {
            str(key): _native_json_schema(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_native_json_schema(item) for item in value]
    return value


class OpenAIResponsesJsonClient:
    """JSON/text client compatible with Agora's world-generation providers."""

    def __init__(self, config: dict[str, Any]) -> None:
        api_config = dict(config.get("openai_api", {}))
        self.api_key_env = str(api_config.get("api_key_env", "OPENAI_API_KEY")).strip()
        self.api_key = str(os.environ.get(self.api_key_env, "")).strip()
        if not self.api_key:
            raise RuntimeError(f"OpenAI API key is not set. Export {self.api_key_env} before running.")

        self.endpoint_base = str(
            api_config.get("endpoint_base", "https://api.openai.com/v1")
        ).strip().rstrip("/")
        self.default_model = str(api_config.get("model", "")).strip()
        if not self.default_model:
            raise RuntimeError("openai_api.model must be configured")

        self.temperature = float(api_config.get("temperature", 1.0))
        self.max_output_tokens = int(api_config.get("max_output_tokens", 8192))
        self.thinking_level = str(api_config.get("thinking_level", "low")).strip().lower()
        self.thinking_budget = int(api_config.get("thinking_budget", 0))
        self.timeout_seconds = int(api_config.get("timeout_seconds", 240))
        self.stages = dict(api_config.get("stages", {}))
        retry = dict(api_config.get("retry", {}))
        self.retry_max_attempts = max(1, int(retry.get("max_attempts", 3)))
        self.retry_initial_sleep_seconds = max(0.0, float(retry.get("initial_sleep_seconds", 2.0)))
        self.retry_max_sleep_seconds = max(0.0, float(retry.get("max_sleep_seconds", 20.0)))
        self.retry_backoff_multiplier = max(1.0, float(retry.get("backoff_multiplier", 2.0)))
        self.retry_status_codes = {
            int(value)
            for value in retry.get("status_codes", [408, 409, 429, 500, 502, 503, 504])
        }
        self.call_history: list[dict[str, Any]] = []
        self.telemetry_path = str(
            os.environ.get("AGORA_LLM_TELEMETRY_PATH", "")
            or os.environ.get("AGORA_VERTEX_TELEMETRY_PATH", "")
        ).strip()
        self.telemetry_run_id = str(
            os.environ.get("AGORA_LLM_TELEMETRY_RUN_ID", "")
            or os.environ.get("AGORA_VERTEX_TELEMETRY_RUN_ID", "")
        ).strip()
        self.telemetry_treatment = str(
            os.environ.get("AGORA_LLM_TELEMETRY_TREATMENT", "")
            or os.environ.get("AGORA_VERTEX_TELEMETRY_TREATMENT", "")
        ).strip()

    def safe_config(self) -> dict[str, Any]:
        return {
            "backend": "openai_responses",
            "api_key_env": self.api_key_env,
            "endpoint_base": self.endpoint_base,
            "default_model": self.default_model,
            "thinking_level": self.thinking_level,
            "max_output_tokens": self.max_output_tokens,
            "temperature": self.temperature,
            "store": False,
            "retry": {
                "max_attempts": self.retry_max_attempts,
                "status_codes": sorted(self.retry_status_codes),
            },
            "stages": self.stages,
        }

    def _stage_config(self, stage: str) -> dict[str, Any]:
        stage_config = self.stages.get(stage, {})
        return stage_config if isinstance(stage_config, dict) else {}

    def _model_for_stage(self, stage: str) -> str:
        return str(self._stage_config(stage).get("model", self.default_model)).strip() or self.default_model

    def _max_output_tokens_for_stage(self, stage: str) -> int:
        return max(1, int(self._stage_config(stage).get("max_output_tokens", self.max_output_tokens)))

    def _thinking_level_for_stage(self, stage: str) -> str:
        raw = str(self._stage_config(stage).get("thinking_level", self.thinking_level)).strip().lower()
        aliases = {"off": "none", "minimal": "minimal"}
        normalized = aliases.get(raw, raw)
        if normalized not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError(f"unsupported OpenAI reasoning effort: {raw}")
        return normalized

    @staticmethod
    def _output_text(body: dict[str, Any]) -> str:
        chunks: list[str] = []
        for item in body.get("output", []) or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content", []) or []:
                if not isinstance(content, dict):
                    continue
                if content.get("type") == "output_text" and str(content.get("text", "")).strip():
                    chunks.append(str(content["text"]).strip())
        return "\n".join(chunks).strip()

    @staticmethod
    def _usage(body: dict[str, Any]) -> dict[str, int]:
        usage = body.get("usage", {}) if isinstance(body.get("usage"), dict) else {}
        details = (
            usage.get("output_tokens_details", {})
            if isinstance(usage.get("output_tokens_details"), dict)
            else {}
        )
        result: dict[str, int] = {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            try:
                result[key] = int(usage.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
        try:
            result["reasoning_tokens"] = int(details.get("reasoning_tokens", 0) or 0)
        except (TypeError, ValueError):
            pass
        return result

    def _record(
        self,
        *,
        kind: str,
        stage: str,
        model: str,
        attempt: int,
        status: str,
        elapsed_seconds: float,
        input_chars: int,
        max_output_tokens: int,
        thinking_level: str,
        body: dict[str, Any] | None = None,
        output_chars: int = 0,
        error: str = "",
    ) -> None:
        record = {
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run_id": self.telemetry_run_id,
            "treatment": self.telemetry_treatment,
            "kind": kind,
            "stage": stage,
            "backend": "openai_responses",
            "model": model,
            "response_model": str(body.get("model", "")) if body else "",
            "attempt": attempt,
            "status": status,
            "elapsed_seconds": round(max(0.0, elapsed_seconds), 4),
            "input_chars": max(0, input_chars),
            "output_chars": max(0, output_chars),
            "generation_config": {
                "max_output_tokens": max_output_tokens,
                "reasoning_effort": thinking_level,
                "store": False,
            },
            "finish_reasons": [str(body.get("status", ""))] if body else [],
            "usage_metadata": self._usage(body or {}),
            "error": str(error)[:1000],
        }
        self.call_history.append(record)
        if self.telemetry_path:
            path = Path(self.telemetry_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _request(
        self,
        *,
        kind: str,
        system_instruction: str,
        prompt: str,
        stage: str,
        schema: dict[str, Any] | None,
    ) -> str:
        model = self._model_for_stage(stage)
        max_output_tokens = self._max_output_tokens_for_stage(stage)
        thinking_level = self._thinking_level_for_stage(stage)
        instructions = system_instruction.strip()
        if schema:
            instructions = (
                instructions
                + "\n\nReturn exactly one JSON object matching the supplied schema. "
                "Do not use markdown fences or add commentary. Keep strings concise."
            ).strip()
        payload: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": prompt,
            "max_output_tokens": max_output_tokens,
            "reasoning": {"effort": thinking_level},
            "store": False,
            "text": {"format": {"type": "text"}},
        }
        if schema:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "agora_" + "".join(c if c.isalnum() else "_" for c in stage)[:48],
                    "schema": _native_json_schema(schema),
                    "strict": False,
                }
            }

        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint_base}/responses",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        sleep_seconds = self.retry_initial_sleep_seconds
        last_error = "unknown error"
        for attempt in range(1, self.retry_max_attempts + 1):
            started = time.perf_counter()
            body: dict[str, Any] = {}
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                parsed_body = json.loads(raw)
                if not isinstance(parsed_body, dict):
                    raise RuntimeError("OpenAI Responses API returned a non-object payload")
                body = parsed_body
                text = self._output_text(body)
                if not text:
                    detail = body.get("incomplete_details", {})
                    raise RuntimeError(f"OpenAI Responses API returned no output text: {detail}")
                self._record(
                    kind=kind,
                    stage=stage,
                    model=model,
                    attempt=attempt,
                    status="ok",
                    elapsed_seconds=time.perf_counter() - started,
                    input_chars=len(prompt) + len(instructions),
                    max_output_tokens=max_output_tokens,
                    thinking_level=thinking_level,
                    body=body,
                    output_chars=len(text),
                )
                return text
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = f"HTTP {exc.code}: {detail[:800]}"
                status = f"http_{exc.code}"
                retryable = int(exc.code) in self.retry_status_codes
            except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
                last_error = str(exc)
                status = "transport_error"
                retryable = True
            except (json.JSONDecodeError, RuntimeError) as exc:
                last_error = str(exc)
                status = "invalid_response"
                retryable = True
            self._record(
                kind=kind,
                stage=stage,
                model=model,
                attempt=attempt,
                status=status,
                elapsed_seconds=time.perf_counter() - started,
                input_chars=len(prompt) + len(instructions),
                max_output_tokens=max_output_tokens,
                thinking_level=thinking_level,
                body=body,
                error=last_error,
            )
            if not retryable or attempt >= self.retry_max_attempts:
                break
            delay = min(self.retry_max_sleep_seconds, sleep_seconds)
            delay += random.uniform(0.0, min(1.0, delay * 0.15))
            time.sleep(delay)
            sleep_seconds = max(delay, sleep_seconds) * self.retry_backoff_multiplier
        raise RuntimeError(f"OpenAI Responses API failed for stage {stage}: {last_error}")

    def generate_json(
        self,
        *,
        system_instruction: str,
        prompt: str,
        schema: dict[str, Any],
        stage: str,
    ) -> dict[str, Any]:
        text = self._request(
            kind="json",
            system_instruction=system_instruction,
            prompt=prompt,
            stage=stage,
            schema=schema,
        )
        parsed = first_json_value_from_text(text)
        if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
            parsed = parsed[0]
        if not isinstance(parsed, dict):
            raise RuntimeError(f"OpenAI Responses API did not return a JSON object for stage {stage}")
        return parsed

    def generate_text(
        self,
        *,
        system_instruction: str,
        prompt: str,
        stage: str = "world_creator_text_generation",
    ) -> str:
        return self._request(
            kind="text",
            system_instruction=system_instruction,
            prompt=prompt,
            stage=stage,
            schema=None,
        )
