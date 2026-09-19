#!/usr/bin/env python3
"""Generate and validate a connected social graph for an existing world cast."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora_ui.vertex_json_client import VertexJsonClient  # noqa: E402


RELATIONSHIP_TYPES = [
    "alliance",
    "blackmail",
    "contract",
    "depend",
    "dispute",
    "favor",
    "mentor",
    "negotiate",
    "owe",
    "protect",
    "rival",
    "smuggle",
    "supplier",
    "trust",
]


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _schema(count: int) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["characters"],
        "properties": {
            "characters": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "required": ["source_name", "relationships"],
                    "properties": {
                        "source_name": {"type": "string"},
                        "relationships": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "required": ["target_name", "relationship_type", "description"],
                                "properties": {
                                    "target_name": {"type": "string"},
                                    "relationship_type": {"type": "string", "enum": RELATIONSHIP_TYPES},
                                    "description": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            }
        },
    }


def _validate(payload: dict[str, Any], names: list[str]) -> tuple[dict[str, list[dict[str, str]]], dict[str, Any]]:
    allowed = set(names)
    rows = payload.get("characters", [])
    if not isinstance(rows, list):
        raise ValueError("characters must be an array")
    by_source: dict[str, list[dict[str, str]]] = {}
    duplicate_sources: list[str] = []
    duplicate_target_sources: list[str] = []
    invalid_edges: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            invalid_edges.append("non-object character row")
            continue
        source = str(row.get("source_name", "")).strip()
        if source in by_source:
            duplicate_sources.append(source)
            continue
        relationships: list[dict[str, str]] = []
        for edge in row.get("relationships", []):
            if not isinstance(edge, dict):
                invalid_edges.append(f"{source}: non-object relationship")
                continue
            target = str(edge.get("target_name", "")).strip()
            relation_type = str(edge.get("relationship_type", "")).strip()
            description = str(edge.get("description", "")).strip()
            if source not in allowed or target not in allowed or target == source:
                invalid_edges.append(f"{source}->{target}")
                continue
            if relation_type not in RELATIONSHIP_TYPES or not description:
                invalid_edges.append(f"{source}->{target}: incomplete")
                continue
            relationships.append(
                {
                    "target_name": target,
                    "relationship_type": relation_type,
                    "description": description,
                }
            )
        targets = [edge["target_name"] for edge in relationships]
        if len(targets) != len(set(targets)):
            duplicate_target_sources.append(source)
        by_source[source] = relationships

    missing_sources = sorted(allowed - set(by_source))
    extra_sources = sorted(set(by_source) - allowed)
    insufficient_sources = sorted(source for source, edges in by_source.items() if len(edges) < 2)
    adjacency = {name: set() for name in names}
    for source, edges in by_source.items():
        if source not in adjacency:
            continue
        for edge in edges:
            target = edge["target_name"]
            adjacency[source].add(target)
            adjacency[target].add(source)
    reached: set[str] = set()
    frontier = [names[0]] if names else []
    while frontier:
        current = frontier.pop()
        if current in reached:
            continue
        reached.add(current)
        frontier.extend(adjacency[current] - reached)
    disconnected = sorted(allowed - reached)
    diagnostics = {
        "source_count": len(by_source),
        "edge_count": sum(len(edges) for edges in by_source.values()),
        "duplicate_sources": duplicate_sources,
        "duplicate_target_sources": duplicate_target_sources,
        "missing_sources": missing_sources,
        "extra_sources": extra_sources,
        "insufficient_sources": insufficient_sources,
        "invalid_edges": invalid_edges,
        "connected": not disconnected and bool(names),
        "disconnected_sources": disconnected,
        "relationship_type_count": len(
            {
                edge["relationship_type"]
                for edges in by_source.values()
                for edge in edges
            }
        ),
    }
    if any(
        (
            duplicate_sources,
            duplicate_target_sources,
            missing_sources,
            extra_sources,
            insufficient_sources,
            invalid_edges,
            disconnected,
        )
    ):
        raise ValueError(json.dumps(diagnostics, ensure_ascii=False, separators=(",", ":")))
    return by_source, diagnostics


def _client(model: str, api_key_env: str) -> VertexJsonClient:
    return VertexJsonClient(
        {
            "vertex_api": {
                "backend": "ai_studio",
                "api_key_env": api_key_env,
                "endpoint_base": "https://generativelanguage.googleapis.com/v1beta",
                "method": "generateContent",
                "model": model,
                "temperature": 0.4,
                "max_output_tokens": 16384,
                "thinking_level": "low",
                "thinking_budget": 1024,
                "timeout_seconds": 240,
                "retry": {
                    "max_attempts": 3,
                    "initial_sleep_seconds": 2.0,
                    "max_sleep_seconds": 12.0,
                    "backoff_multiplier": 2.0,
                    "status_codes": [408, 429, 500, 502, 503, 504],
                },
                "stages": {
                    "relationship_enrichment": {
                        "model": model,
                        "temperature": 0.4,
                        "max_output_tokens": 16384,
                        "thinking_level": "low",
                        "thinking_budget": 1024,
                    }
                },
            }
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--builder", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-builder", type=Path, required=True)
    parser.add_argument("--output-config", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--telemetry", type=Path, required=True)
    parser.add_argument("--model", default="gemini-3.7-flash")
    parser.add_argument("--api-key-env", default="AGORA_AISTUDIO_API_KEY")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument(
        "--relationship-file",
        type=Path,
        help="Validate and compile a locally reviewed relationship payload instead of calling an API.",
    )
    args = parser.parse_args()

    if not args.relationship_file and not os.environ.get(args.api_key_env):
        raise RuntimeError(f"{args.api_key_env} is not set")
    builder = _read_object(args.builder)
    config = _read_object(args.config)
    characters = [item for item in builder.get("main_characters", []) if isinstance(item, dict)]
    names = [str(item.get("display_name", "")).strip() for item in characters]
    if len(names) < 3 or any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("Builder cast requires at least three unique, non-empty display names")

    cast_context = [
        {
            "display_name": character.get("display_name", ""),
            "role_name": character.get("role_name", ""),
            "activity": character.get("activity", ""),
            "arc_goal": character.get("arc_goal", ""),
            "home_base": character.get("home_base", ""),
            "property_assets": [
                item.get("asset_name", "")
                for item in character.get("property_templates", [])
                if isinstance(item, dict)
            ],
            "knowledge_topics": [
                item.get("topic", "")
                for item in character.get("knowledge_templates", [])
                if isinstance(item, dict)
            ],
        }
        for character in characters
    ]
    prompt = (
        "Build the persistent social graph for this executable multi-agent world. Use every source_name exactly "
        "once and copy all names exactly from CAST. Give each character 2-4 directed relationships to distinct "
        "other characters. Descriptions must name a concrete resource, obligation, secret, institution, or state "
        "change that can drive future interaction. Make the undirected graph connected; bridge roles and locations; "
        "include cooperation, dependence, and conflict without inventing new people.\n\n"
        f"WORLD DYNAMICS:\n{json.dumps(builder.get('world_dynamics', {}), ensure_ascii=False)}\n\n"
        f"CAST:\n{json.dumps(cast_context, ensure_ascii=False)}"
    )
    failures: list[str] = []
    relationships_by_source: dict[str, list[dict[str, str]]] | None = None
    diagnostics: dict[str, Any] = {}
    started = time.perf_counter()
    client: VertexJsonClient | None = None
    if args.relationship_file:
        payload = _read_object(args.relationship_file)
        relationships_by_source, diagnostics = _validate(payload, names)
        diagnostics["successful_attempt"] = 1
    else:
        args.telemetry.parent.mkdir(parents=True, exist_ok=True)
        os.environ["AGORA_VERTEX_TELEMETRY_PATH"] = str(args.telemetry.resolve())
        os.environ["AGORA_VERTEX_TELEMETRY_RUN_ID"] = "nonpreset_relationship_enrichment"
        client = _client(args.model, args.api_key_env)
        for attempt in range(1, max(1, args.attempts) + 1):
            attempt_prompt = prompt
            if failures:
                attempt_prompt += (
                    "\n\nThe previous response failed validation. Regenerate the complete graph and correct this "
                    f"diagnostic: {failures[-1]}"
                )
            try:
                payload = client.generate_json(
                    system_instruction=(
                        "You design causal social networks for persistent agent communities. Return only relationships "
                        "grounded in the supplied cast and world dynamics."
                    ),
                    prompt=attempt_prompt,
                    schema=_schema(len(names)),
                    stage="relationship_enrichment",
                )
                relationships_by_source, diagnostics = _validate(payload, names)
                diagnostics["successful_attempt"] = attempt
                break
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
    if relationships_by_source is None:
        raise RuntimeError(f"Relationship enrichment failed after {len(failures)} attempts: {failures[-1]}")

    for character in characters:
        name = str(character.get("display_name", "")).strip()
        character["relationships"] = relationships_by_source[name]

    config_characters = [item for item in config.get("main_characters", []) if isinstance(item, dict)]
    id_by_name = {
        str(item.get("display_name", "")).strip(): str(item.get("agent_id", "")).strip()
        for item in config_characters
    }
    if set(id_by_name) != set(names) or any(not agent_id for agent_id in id_by_name.values()):
        raise ValueError("Config cast does not match builder cast")
    for character in config_characters:
        source_name = str(character.get("display_name", "")).strip()
        source_id = str(character.get("agent_id", "")).strip()
        character["relationships"] = [
            {
                "target_agent_id": id_by_name[edge["target_name"]],
                **edge,
            }
            for edge in relationships_by_source[source_name]
            if id_by_name[edge["target_name"]] != source_id
        ]

    args.output_builder.parent.mkdir(parents=True, exist_ok=True)
    args.output_config.parent.mkdir(parents=True, exist_ok=True)
    args.output_builder.write_text(json.dumps(builder, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_config.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "model": args.model if client else "codex_expert_local_review",
        "source": "api_generation" if client else "local_expert_review",
        "native_response_json_schema": bool(client),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "provider_call_count": len(client.call_history) if client else 0,
        "validation_failures": failures,
        "diagnostics": diagnostics,
        "output_builder": str(args.output_builder),
        "output_config": str(args.output_config),
    }
    args.output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
