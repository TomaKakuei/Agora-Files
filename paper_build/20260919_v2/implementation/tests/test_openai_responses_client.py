from __future__ import annotations

import json

from agora_ui.openai_responses_client import OpenAIResponsesJsonClient


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _config() -> dict:
    return {
        "openai_api": {
            "api_key_env": "TEST_OPENAI_KEY",
            "model": "gpt-test",
            "max_output_tokens": 12288,
            "thinking_level": "low",
            "retry": {"max_attempts": 1},
        }
    }


def test_generate_json_uses_responses_schema_without_storing(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_OPENAI_KEY", "private-test-key")
    telemetry = tmp_path / "calls.jsonl"
    monkeypatch.setenv("AGORA_LLM_TELEMETRY_PATH", str(telemetry))
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response({
            "status": "completed",
            "model": "gpt-test-2026-01-01",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": '{"actions":[]}'}],
            }],
            "usage": {
                "input_tokens": 20,
                "output_tokens": 10,
                "total_tokens": 30,
                "output_tokens_details": {"reasoning_tokens": 4},
            },
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = OpenAIResponsesJsonClient(_config())
    result = client.generate_json(
        system_instruction="System",
        prompt="Prompt",
        schema={
            "type": "object",
            "properties": {"actions": {"type": "array", "minItems": None}},
        },
        stage="runtime",
    )

    assert result == {"actions": []}
    assert captured["url"].endswith("/v1/responses")
    assert captured["payload"]["store"] is False
    assert captured["payload"]["max_output_tokens"] == 12288
    assert captured["payload"]["reasoning"] == {"effort": "low"}
    assert captured["payload"]["text"]["format"]["type"] == "json_schema"
    assert "minItems" not in captured["payload"]["text"]["format"]["schema"]["properties"]["actions"]
    assert captured["headers"]["Authorization"] == "Bearer private-test-key"
    telemetry_text = telemetry.read_text(encoding="utf-8")
    assert "private-test-key" not in telemetry_text
    telemetry_row = json.loads(telemetry_text)
    assert telemetry_row["usage_metadata"]["reasoning_tokens"] == 4
    assert telemetry_row["response_model"] == "gpt-test-2026-01-01"
    assert telemetry_row["status"] == "ok"


def test_generate_text_extracts_output_message(monkeypatch):
    monkeypatch.setenv("TEST_OPENAI_KEY", "private-test-key")
    monkeypatch.delenv("AGORA_LLM_TELEMETRY_PATH", raising=False)

    def fake_urlopen(_request, timeout):
        assert timeout == 240
        return _Response({
            "status": "completed",
            "output": [
                {"type": "reasoning", "summary": []},
                {"type": "message", "content": [{"type": "output_text", "text": "world summary"}]},
            ],
            "usage": {},
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = OpenAIResponsesJsonClient(_config())
    assert client.generate_text(system_instruction="System", prompt="Prompt") == "world summary"


def test_safe_config_never_contains_key(monkeypatch):
    monkeypatch.setenv("TEST_OPENAI_KEY", "private-test-key")
    client = OpenAIResponsesJsonClient(_config())
    assert "private-test-key" not in json.dumps(client.safe_config())
