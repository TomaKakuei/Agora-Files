from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

from agora_ui.vertex_json_client import VertexJsonClient


def test_vertex_headers_use_configured_service_account_without_exposing_token() -> None:
    credentials = Mock(valid=True, token="secret-token")
    config = {
        "runtime": {"vertex_model": "gemini-test", "vertex_cred_file": "/tmp/service-account.json"},
        "vertex_api": {"backend": "vertex_publisher"},
    }
    with patch(
        "agora_ui.vertex_json_client.service_account.Credentials.from_service_account_file",
        return_value=credentials,
    ):
        client = VertexJsonClient(config)

    assert client._headers("primary")["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in str(client.safe_config())


def test_global_vertex_endpoint_uses_runtime_project_and_global_host() -> None:
    config = {
        "runtime": {
            "vertex_model": "gemini-test",
            "vertex_project_id": "paper-project",
            "vertex_location": "global",
        },
        "vertex_api": {"backend": "vertex_publisher"},
    }
    client = VertexJsonClient(config)

    assert client.endpoint_base == (
        "https://aiplatform.googleapis.com/v1/projects/paper-project/locations/global"
    )


def _client() -> VertexJsonClient:
    return VertexJsonClient(
        {
            "vertex_api": {
                "backend": "vertex_publisher",
                "model": "gemini-test-model",
            }
        }
    )


def test_usage_and_finish_reason_extraction() -> None:
    chunks = [
        {
            "candidates": [{"finishReason": "STOP"}],
            "usageMetadata": {
                "promptTokenCount": 12,
                "candidatesTokenCount": 7,
                "thoughtsTokenCount": 3,
                "totalTokenCount": 22,
            },
        }
    ]
    assert VertexJsonClient._usage_from_chunks(chunks) == {
        "promptTokenCount": 12,
        "candidatesTokenCount": 7,
        "thoughtsTokenCount": 3,
        "totalTokenCount": 22,
    }
    assert VertexJsonClient._finish_reasons_from_chunks(chunks) == ["STOP"]


def test_generation_attempt_telemetry_is_safe_and_persisted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    telemetry_path = tmp_path / "calls.jsonl"
    monkeypatch.setenv("AGORA_VERTEX_TELEMETRY_PATH", str(telemetry_path))
    monkeypatch.setenv("AGORA_VERTEX_TELEMETRY_RUN_ID", "trial_01")
    monkeypatch.setenv("AGORA_VERTEX_TELEMETRY_TREATMENT", "decomposed")
    client = _client()
    client._record_generation_attempt(
        kind="json",
        stage="world_creator_generation",
        backend_name="primary",
        model="gemini-test-model",
        attempt=1,
        generation_config={
            "temperature": 0.2,
            "maxOutputTokens": 8192,
            "thinkingConfig": {"thinkingLevel": "HIGH"},
        },
        elapsed_seconds=1.25,
        status="ok",
        input_chars=100,
        output_chars=50,
        raw_response_bytes=80,
        chunks=[
            {
                "candidates": [{"finishReason": "STOP"}],
                "usageMetadata": {"totalTokenCount": 42},
            }
        ],
    )

    assert len(client.call_history) == 1
    row = json.loads(telemetry_path.read_text(encoding="utf-8"))
    assert row["run_id"] == "trial_01"
    assert row["treatment"] == "decomposed"
    assert row["usage_metadata"]["totalTokenCount"] == 42
    assert row["generation_config"]["thinkingConfig"] == {
        "thinkingLevel": "HIGH"
    }
    assert "api_key" not in row


def test_gemini_3_none_maps_to_minimal_for_flash() -> None:
    client = VertexJsonClient(
        {
            "vertex_api": {
                "backend": "vertex_publisher",
                "model": "gemini-3-flash-preview",
                "thinking_level": "none",
            }
        }
    )

    payload = client._payload(
        "prompt",
        stage="world_creator_generation",
        backend_name="primary",
    )

    assert payload["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "MINIMAL"
    }


def test_gemini_3_minimal_maps_to_low_for_pro() -> None:
    client = VertexJsonClient(
        {
            "vertex_api": {
                "backend": "vertex_publisher",
                "model": "gemini-3.1-pro-preview",
                "thinking_level": "minimal",
            }
        }
    )

    payload = client._payload(
        "prompt",
        stage="world_creator_generation",
        backend_name="primary",
    )

    assert payload["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "LOW"
    }


def test_json_payload_uses_native_schema_and_removes_null_hints() -> None:
    client = VertexJsonClient(
        {
            "vertex_api": {
                "backend": "vertex_publisher",
                "model": "gemini-3.7-flash",
            }
        }
    )
    payload = client._payload(
        "prompt",
        stage="world_creator_generation",
        backend_name="primary",
        response_schema={
            "type": "object",
            "properties": {
                "rooms": {
                    "type": "array",
                    "minItems": None,
                    "items": {"type": "string"},
                }
            },
        },
    )

    generation = payload["generationConfig"]
    assert generation["responseMimeType"] == "application/json"
    assert generation["responseJsonSchema"] == {
        "type": "object",
        "properties": {
            "rooms": {"type": "array", "items": {"type": "string"}}
        },
    }
