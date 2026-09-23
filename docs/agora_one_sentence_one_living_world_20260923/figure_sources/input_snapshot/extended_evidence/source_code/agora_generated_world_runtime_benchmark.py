#!/usr/bin/env python3
"""Run and score 24-round model policies inside generated Agora worlds."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict, deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora_ui.adjudicator_schemas import (  # noqa: E402
    ActionIntentSpec,
    AdjudicatorControlSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    InventoryItemSpec,
    WalletSpec,
    WorldRulesSpec,
)
from agora_ui.foundation_schemas import GridPosition  # noqa: E402
from agora_ui.run_interaction_simulation.core import materialize_scenario  # noqa: E402
from agora_ui.universal_adjudicator.handlers_custom import _handle_custom  # noqa: E402
from agora_ui.vertex_json_client import VertexJsonClient  # noqa: E402
from agora_ui.openai_responses_client import OpenAIResponsesJsonClient  # noqa: E402
from agora_ui.world_coordinator import evaluate_open_action  # noqa: E402


BENCHMARK_ROOT = ROOT / "docs" / "living_world_benchmark_20260825_hidden"
RUN_ROOT = BENCHMARK_ROOT / "confirmatory_runs"
DEFAULT_OUTPUT = BENCHMARK_ROOT / "generated_world_runtime_results.json"
PROMPT_ID = "lwb_hidden_v2_01"
MODELS = {
    "gemini-2.5-flash": "gemini_2_5_flash",
    "gemini-3.1-flash-lite": "gemini_3_1_flash_lite",
    "gemini-3.5-flash-lite": "gemini_3_5_flash_lite",
    "gemini-3.7-flash": "gemini_3_7_flash",
    "gemini-3.1-pro-preview": "gemini_3_1_pro_preview",
    "gpt-5.6-sol": "gpt_5_6_sol",
    "gpt-5.6-terra": "gpt_5_6_terra",
    "gpt-5.6-luna": "gpt_5_6_luna",
}
CHECKPOINTS = (1, 5, 9, 13, 17, 21)
SCORING_VERSION = "agwre_v1.0"
AXIS_WEIGHTS = {
    "executable_grounding": 0.14,
    "spatial_mobility": 0.10,
    "persistent_consequences": 0.16,
    "social_continuity": 0.14,
    "human_integration": 0.12,
    "open_action_recovery": 0.14,
    "institutional_integrity": 0.12,
    "temporal_progression": 0.08,
}


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _mean(values: Iterable[float]) -> float:
    rows = list(values)
    return sum(rows) / len(rows) if rows else 0.0


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def _state_hash(state: AgentStateBundleSpec) -> str:
    raw = json.dumps(state.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _plan_schema() -> dict[str, Any]:
    effect = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["speech", "transfer", "create_item", "status"]},
            "source_agent_id": {"type": "string"},
            "target_agent_id": {"type": "string"},
            "item_id": {"type": "string"},
            "quantity": {"type": "integer"},
            "item_name": {"type": "string"},
            "item_description": {"type": "string"},
            "input_item_ids": {"type": "array", "items": {"type": "string"}},
            "status_effect": {"type": "string"},
            "duration_steps": {"type": "integer"},
            "content": {"type": "string"},
        },
        "required": ["kind"],
    }
    proposal = {
        "type": "object",
        "properties": {
            "action_name": {"type": "string"},
            "action_text": {"type": "string"},
            "target_agent_id": {"type": "string"},
            "rationale": {"type": "string"},
            "target_response": {
                "type": "string",
                "enum": ["accept", "reject", "counter", "not_required", "unknown"],
            },
            "effects": {"type": "array", "items": effect},
        },
        "required": ["action_name", "action_text", "target_agent_id", "target_response", "effects"],
    }
    action = {
        "type": "object",
        "properties": {
            "round_offset": {"type": "integer", "enum": [0, 1, 2, 3]},
            "actor_id": {"type": "string"},
            "action_type": {"type": "string", "enum": ["catalog", "propose", "move"]},
            "target_id": {"type": "string"},
            "route_id": {"type": "string"},
            "destination_room_id": {"type": "string"},
            "thread_id": {"type": "string"},
            "responds_to_event_ids": {"type": "array", "items": {"type": "string"}},
            "intent_text": {"type": "string"},
            "expected_world_consequence": {"type": "string"},
            "proposal": proposal,
        },
        "required": [
            "round_offset",
            "actor_id",
            "action_type",
            "target_id",
            "route_id",
            "destination_room_id",
            "thread_id",
            "responds_to_event_ids",
            "intent_text",
            "expected_world_consequence",
        ],
    }
    return {
        "type": "object",
        "properties": {
            "actions": {"type": "array", "items": action},
        },
        "required": ["actions"],
    }


def _client_config(model: str, api_key_env: str, thinking_level: str) -> dict[str, Any]:
    return {
        "vertex_api": {
            "backend": "ai_studio",
            "api_key_env": api_key_env,
            "endpoint_base": "https://generativelanguage.googleapis.com/v1beta",
            "method": "generateContent",
            "model": model,
            "temperature": 0.75,
            "max_output_tokens": 12288,
            "thinking_level": thinking_level,
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
                "generated_world_runtime": {
                    "model": model,
                    "temperature": 0.75,
                    "max_output_tokens": 12288,
                    "thinking_level": thinking_level,
                    "thinking_budget": 1024,
                }
            },
        }
    }


def _openai_client_config(model: str, api_key_env: str, thinking_level: str) -> dict[str, Any]:
    return {
        "openai_api": {
            "api_key_env": api_key_env,
            "endpoint_base": os.environ.get("AGORA_GPT_BASE_URL", "https://api.openai.com/v1"),
            "model": model,
            "temperature": 0.75,
            "max_output_tokens": 12288,
            "thinking_level": thinking_level,
            "timeout_seconds": 300,
            "retry": {
                "max_attempts": 3,
                "initial_sleep_seconds": 2.0,
                "max_sleep_seconds": 12.0,
                "backoff_multiplier": 2.0,
                "status_codes": [408, 409, 429, 500, 502, 503, 504],
            },
            "stages": {
                "generated_world_runtime": {
                    "model": model,
                    "max_output_tokens": 12288,
                    "thinking_level": thinking_level,
                }
            },
        }
    }


def _room_center(room: dict[str, Any]) -> GridPosition:
    return GridPosition(
        x=int(room.get("x", 0)) + max(0, int(room.get("width_tiles", 1)) // 2),
        y=int(room.get("y", 0)) + max(0, int(room.get("height_tiles", 1)) // 2),
        z=int(room.get("z", 0)),
    )


def _load_runtime(config: dict[str, Any], scenario_dir: Path) -> tuple[AgentStateBundleSpec, WorldRulesSpec]:
    paths = materialize_scenario(config, scenario_dir)
    rooms = {str(room["room_id"]): room for room in config.get("space", {}).get("rooms", [])}
    agents = []
    for path in sorted(paths["agents_dir"].glob("*.json")):
        agent = AgentRuntimeProfileSpec.model_validate(_read(path))
        if agent.room_id in rooms:
            agent.coordinates = _room_center(rooms[agent.room_id])
        agents.append(agent)
    human_cfg = config.get("human_interaction", {})
    human_id = str(human_cfg.get("runtime_human_agent_id", "human_interactor"))
    human_room = str(human_cfg.get("default_room_id", next(iter(rooms), "")))
    human = AgentRuntimeProfileSpec(
        agent_id=human_id,
        display_name=str(human_cfg.get("display_name", "Human Player")),
        role_name="Human Player",
        room_id=human_room,
        coordinates=_room_center(rooms[human_room]),
        wallet=WalletSpec(amount_minor=5000),
        inventory=[
            InventoryItemSpec(
                item_id="human_field_kit",
                name="Human Field Kit",
                description="A bounded kit brought by the human player.",
                quantity=1,
            )
        ],
    )
    agents.append(human)
    return AgentStateBundleSpec(agents=agents), WorldRulesSpec.model_validate(_read(paths["world_rules"]))


def _neighbors(config: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for room in config.get("space", {}).get("rooms", []):
        room_id = str(room.get("room_id", ""))
        for door in room.get("doorways", []):
            target = str(door.get("connects_to_room_id", ""))
            if target:
                result[room_id].add(target)
                result[target].add(room_id)
    return result


def _agent_summary(agent: AgentRuntimeProfileSpec) -> dict[str, Any]:
    return {
        "agent_id": agent.agent_id,
        "name": agent.display_name,
        "role": agent.role_name,
        "room_id": agent.room_id,
        "inventory": [
            {"item_id": item.item_id, "quantity": item.quantity, "name": item.name}
            for item in agent.inventory
            if item.quantity > 0
        ][:10],
        "status_effects": [item.effect for item in agent.status_effects[-4:]],
    }


def _catalog(config: dict[str, Any]) -> list[dict[str, Any]]:
    supported = {"custom", "cinematic", "move"}
    return [
        {
            "route_id": str(item.get("route_id", "")),
            "kind": str(item.get("kind", "")),
            "label": str(item.get("label", "")),
            "description": str(item.get("description", ""))[:360],
            "status_effect": str(item.get("status_effect", "")),
            "same_room": bool(item.get("preconditions", {}).get("same_room", False)),
        }
        for item in config.get("actions", {}).get("interaction_affordance_catalog", [])
        if str(item.get("kind", "")) in supported
    ]


def _intervention(
    round_index: int,
    *,
    state: AgentStateBundleSpec,
    config: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    agents = {agent.agent_id: agent for agent in state.agents}
    human_id = str(config.get("human_interaction", {}).get("runtime_human_agent_id", "human_interactor"))
    hooks = [str(item) for item in config.get("scenario_meta", {}).get("creator_conflict_hooks", [])]
    if round_index in {5, 9, 21}:
        human = agents[human_id]
        local_targets = [
            agent for agent in state.agents
            if agent.agent_id != human_id and agent.room_id == human.room_id
        ]
        if not local_targets:
            occupancy = Counter(
                agent.room_id for agent in state.agents if agent.agent_id != human_id
            )
            destination = sorted(occupancy, key=lambda room_id: (-occupancy[room_id], room_id))[0]
            anchor = next(
                agent for agent in state.agents
                if agent.agent_id != human_id and agent.room_id == destination
            )
            before = _state_hash(state)
            origin = human.room_id
            human.room_id = destination
            human.coordinates = anchor.coordinates.model_copy()
            events.append({
                "event_id": f"human_arrival_r{round_index:02d}",
                "round_index": round_index,
                "event_type": "human_movement",
                "actor_id": human_id,
                "status": "committed",
                "content": f"The human player travels from {origin} to occupied room {destination} before speaking.",
                "origin_room_id": origin,
                "destination_room_id": destination,
                "mutation_kinds": ["location"],
                "before_state_hash": before,
                "after_state_hash": _state_hash(state),
                "state_changed": True,
            })
    if round_index == 5:
        event = {
            "event_id": "human_request_r05",
            "round_index": 5,
            "event_type": "human_request",
            "actor_id": human_id,
            "status": "active",
            "content": hooks[0] if hooks else "Help me resolve the most urgent local conflict with a visible consequence.",
        }
    elif round_index == 9:
        human = agents[human_id]
        local_targets = [
            agent for agent in state.agents
            if agent.agent_id != human_id and agent.room_id == human.room_id
        ]
        target = local_targets[0]
        proposal = {
            "action_name": "Take Unowned Emergency Stock",
            "action_text": "Transfer stock the human does not possess to the nearby agent.",
            "target_agent_id": target.agent_id,
            "target_response": "accept",
            "effects": [{
                "kind": "transfer",
                "source_agent_id": human_id,
                "target_agent_id": target.agent_id,
                "item_id": "missing_emergency_stock",
                "quantity": 1,
            }],
        }
        before = _state_hash(state)
        decision = evaluate_open_action(proposal, actor=human, target=target, state=state, config=config)
        event = {
            "event_id": "coordinator_rejection_r09",
            "round_index": 9,
            "event_type": "coordinator_rejection",
            "actor_id": human_id,
            "target_id": target.agent_id,
            "status": decision.status,
            "content": decision.reason,
            "decision": decision.model_dump(mode="json"),
            "before_state_hash": before,
            "after_state_hash": _state_hash(state),
            "state_changed": before != _state_hash(state),
        }
    elif round_index == 13:
        owner = next(
            agent for agent in state.agents
            if agent.agent_id != human_id and any(item.quantity > 0 for item in agent.inventory)
        )
        item = next(item for item in owner.inventory if item.quantity > 0)
        before = _state_hash(state)
        item.quantity -= 1
        event = {
            "event_id": "resource_shock_r13",
            "round_index": 13,
            "event_type": "world_shock",
            "actor_id": "world",
            "target_id": owner.agent_id,
            "status": "committed",
            "content": f"A breakdown consumes one {item.item_id} from {owner.agent_id}; adapt without inventing ownership.",
            "mutation_kinds": ["inventory"],
            "before_state_hash": before,
            "after_state_hash": _state_hash(state),
            "state_changed": True,
        }
    elif round_index == 17:
        event = {
            "event_id": "cross_room_request_r17",
            "round_index": 17,
            "event_type": "world_request",
            "actor_id": "world",
            "status": "active",
            "content": "Connect work in at least two rooms and carry one established thread across the room graph.",
        }
    elif round_index == 21:
        event = {
            "event_id": "human_followup_r21",
            "round_index": 21,
            "event_type": "human_followup",
            "actor_id": human_id,
            "status": "active",
            "content": "Show me what changed because of our earlier request and complete one unfinished thread.",
        }
    else:
        return None
    events.append(event)
    return event


def _runtime_prompt(
    *,
    config: dict[str, Any],
    state: AgentStateBundleSpec,
    events: list[dict[str, Any]],
    checkpoint: int,
    intervention: dict[str, Any] | None,
) -> str:
    rooms = []
    adjacency = _neighbors(config)
    for room in config.get("space", {}).get("rooms", []):
        rooms.append({
            "room_id": room.get("room_id", ""),
            "name": room.get("name", ""),
            "purpose": str(room.get("metadata", {}).get("purpose", ""))[:360],
            "neighbors": sorted(adjacency.get(str(room.get("room_id", "")), set())),
        })
    payload = {
        "checkpoint_round": checkpoint,
        "covered_rounds": list(range(checkpoint, checkpoint + 4)),
        "world": {
            "name": config.get("scenario_meta", {}).get("world_name", ""),
            "description": config.get("scenario_meta", {}).get("description", ""),
            "objective": config.get("scenario_meta", {}).get("simulation_objective", ""),
            "conflict_hooks": config.get("scenario_meta", {}).get("creator_conflict_hooks", []),
        },
        "rooms": rooms,
        "agents": [_agent_summary(agent) for agent in state.agents],
        "catalog": _catalog(config),
        "open_action_examples": config.get("actions", {}).get("open_action_examples", [])[:4],
        "intervention": intervention or {},
        "recent_events": events[-24:],
    }
    return (
        "Plan exactly 12 executable actions: exactly three actions for each round_offset 0,1,2,3. "
        "An AI actor may act at most once per round; the human is a target, never an actor. Use only exact IDs. "
        "Catalog and proposed physical actions require actor and target in the same room at that point. A move "
        "may go only to a listed neighboring room and takes effect before later round offsets. Keep at least one "
        "thread alive across this four-round block and reuse earlier thread IDs when continuing them. Reference "
        "event IDs only when the action substantively responds to them. Prefer world-specific catalog routes. "
        "Use one or two propose actions for bounded speech/status, an actor-owned transfer, or creation from "
        "actor-owned inputs. Never claim an outcome: describe intent and let the coordinator decide. For a transfer "
        "from the target or into the actor, target_response must be accept. Fill target_id for catalog/propose, "
        "route_id only for catalog/move, destination_room_id only for move, and proposal only for propose. "
        "At round 5 answer the human request; after round 9 replace the rejected action with a legal alternative; "
        "at round 21 report a concrete follow-through to the human.\n\nSTATE:\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )


def _mutations() -> dict[str, list[Any]]:
    return {
        "action_results": [],
        "profile_updates": [],
        "relationship_updates": [],
        "relationship_tensor_updates": [],
        "inventory_updates": [],
    }


def _mutation_kinds(mutations: dict[str, list[Any]]) -> list[str]:
    result = []
    if mutations["profile_updates"]:
        result.append("status")
    if mutations["relationship_tensor_updates"]:
        result.append("relationship")
    if mutations["inventory_updates"]:
        result.append("inventory")
    return result


def _failed_event(
    *,
    event_id: str,
    round_index: int,
    raw: dict[str, Any],
    reason: str,
    before_hash: str,
    violations: list[str],
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "round_index": round_index,
        "event_type": "model_action",
        "status": "failed",
        "action_type": str(raw.get("action_type", "")),
        "actor_id": str(raw.get("actor_id", "")),
        "target_id": str(raw.get("target_id", "")),
        "route_id": str(raw.get("route_id", "")),
        "thread_id": str(raw.get("thread_id", "")),
        "responds_to_event_ids": raw.get("responds_to_event_ids", []),
        "intent_text": str(raw.get("intent_text", "")),
        "expected_world_consequence": str(raw.get("expected_world_consequence", "")),
        "reason": reason,
        "violations": violations,
        "before_state_hash": before_hash,
        "after_state_hash": before_hash,
        "state_changed": False,
        "mutation_kinds": [],
    }


def execute_action(
    raw: dict[str, Any],
    *,
    event_id: str,
    round_index: int,
    state: AgentStateBundleSpec,
    config: dict[str, Any],
    world_rules: WorldRulesSpec,
    known_event_ids: set[str],
    acted: set[tuple[int, str]],
) -> dict[str, Any]:
    before = _state_hash(state)
    actor_id = str(raw.get("actor_id", ""))
    target_id = str(raw.get("target_id", ""))
    action_type = str(raw.get("action_type", ""))
    agents = {agent.agent_id: agent for agent in state.agents}
    human_id = str(config.get("human_interaction", {}).get("runtime_human_agent_id", "human_interactor"))
    violations = []
    if actor_id not in agents or actor_id == human_id:
        violations.append("invalid_actor")
    if (round_index, actor_id) in acted:
        violations.append("duplicate_actor_in_round")
    if action_type not in {"catalog", "propose", "move"}:
        violations.append("invalid_action_type")
    references = raw.get("responds_to_event_ids", [])
    if not isinstance(references, list) or any(str(item) not in known_event_ids for item in references):
        violations.append("invalid_event_reference")
    if action_type in {"catalog", "propose"} and target_id not in agents:
        violations.append("invalid_target")
    if violations:
        return _failed_event(
            event_id=event_id,
            round_index=round_index,
            raw=raw,
            reason=", ".join(violations),
            before_hash=before,
            violations=violations,
        )
    actor = agents[actor_id]
    acted.add((round_index, actor_id))
    base = {
        "event_id": event_id,
        "round_index": round_index,
        "event_type": "model_action",
        "action_type": action_type,
        "actor_id": actor_id,
        "target_id": target_id,
        "route_id": str(raw.get("route_id", "")),
        "thread_id": str(raw.get("thread_id", "")),
        "responds_to_event_ids": [str(item) for item in references],
        "intent_text": str(raw.get("intent_text", "")),
        "expected_world_consequence": str(raw.get("expected_world_consequence", "")),
        "before_state_hash": before,
        "violations": [],
    }
    if action_type == "move":
        destination = str(raw.get("destination_room_id", ""))
        adjacency = _neighbors(config)
        if destination not in adjacency.get(actor.room_id, set()):
            return {**_failed_event(
                event_id=event_id,
                round_index=round_index,
                raw=raw,
                reason="destination is not adjacent",
                before_hash=before,
                violations=["illegal_move"],
            ), "destination_room_id": destination}
        room = next(room for room in config.get("space", {}).get("rooms", []) if room.get("room_id") == destination)
        origin = actor.room_id
        actor.room_id = destination
        actor.coordinates = _room_center(room)
        return {
            **base,
            "status": "success",
            "reason": "adjacent room transition committed",
            "origin_room_id": origin,
            "destination_room_id": destination,
            "after_state_hash": _state_hash(state),
            "state_changed": True,
            "mutation_kinds": ["location"],
        }

    target = agents[target_id]
    if actor.room_id != target.room_id:
        return _failed_event(
            event_id=event_id,
            round_index=round_index,
            raw=raw,
            reason="physical target is not in the actor room",
            before_hash=before,
            violations=["not_same_room"],
        )
    mutations = _mutations()
    decision_payload: dict[str, Any] = {}
    if action_type == "catalog":
        route = next(
            (item for item in _catalog(config) if item["route_id"] == str(raw.get("route_id", "")) and item["kind"] != "move"),
            None,
        )
        if route is None:
            return _failed_event(
                event_id=event_id,
                round_index=round_index,
                raw=raw,
                reason="route is absent or unsupported",
                before_hash=before,
                violations=["invalid_route"],
            )
        action_name = route["label"]
        metadata = {
            "status_effect": route["status_effect"] or _slug(action_name),
            "duration_steps": 2,
        }
    else:
        proposal = raw.get("proposal")
        if not isinstance(proposal, dict):
            return _failed_event(
                event_id=event_id,
                round_index=round_index,
                raw=raw,
                reason="proposal object is required",
                before_hash=before,
                violations=["missing_proposal"],
            )
        try:
            decision = evaluate_open_action(proposal, actor=actor, target=target, state=state, config=config)
        except Exception as exc:
            return _failed_event(
                event_id=event_id,
                round_index=round_index,
                raw=raw,
                reason=f"proposal schema rejected: {exc}",
                before_hash=before,
                violations=["invalid_proposal_schema"],
            )
        decision_payload = decision.model_dump(mode="json")
        if decision.status != "approved":
            return {
                **_failed_event(
                    event_id=event_id,
                    round_index=round_index,
                    raw=raw,
                    reason=decision.reason,
                    before_hash=before,
                    violations=[f"coordinator_{decision.status}"],
                ),
                "coordinator_decision": decision_payload,
                "proposal_name": str(proposal.get("action_name", "")),
                "proposal_effect_kinds": [str(item.get("kind", "")) for item in proposal.get("effects", []) if isinstance(item, dict)],
            }
        action_name = str(proposal.get("action_name", ""))
        metadata = {
            "open_action_proposal": decision.proposal.model_dump(mode="json"),
            "coordinator_decision": decision_payload,
        }
    intent = ActionIntentSpec(
        intent_id=event_id,
        agent_id=actor_id,
        target_agent_id=target_id,
        call="Custom",
        action=action_name,
        intent_text=str(raw.get("intent_text", "")),
        metadata=metadata,
    )
    _handle_custom(
        control=AdjudicatorControlSpec(
            world_description=str(config.get("scenario_meta", {}).get("description", "generated world")),
            simulation_objective=str(config.get("scenario_meta", {}).get("simulation_objective", "continue the world")),
            timestep_index=round_index,
        ),
        world_rules=world_rules,
        state=state,
        agents=agents,
        start_positions={agent.agent_id: agent.coordinates.model_copy() for agent in state.agents},
        moved_agent_ids=set(),
        intent=intent,
        broadcasts=[],
        mutations=mutations,
        rule_appendices=[],
    )
    success = bool(mutations["action_results"] and mutations["action_results"][-1].get("status") == "success")
    after = _state_hash(state)
    event = {
        **base,
        "status": "success" if success else "failed",
        "reason": str(mutations["action_results"][-1].get("reason", "")) if mutations["action_results"] else "no action result",
        "after_state_hash": after,
        "state_changed": before != after,
        "mutation_kinds": _mutation_kinds(mutations),
        "mutations": mutations,
    }
    if action_type == "propose":
        proposal = raw["proposal"]
        event.update({
            "coordinator_decision": decision_payload,
            "proposal_name": str(proposal.get("action_name", "")),
            "proposal_effect_kinds": [str(item.get("kind", "")) for item in proposal.get("effects", []) if isinstance(item, dict)],
        })
    return event


def _largest_component(edges: set[tuple[str, str]], nodes: set[str]) -> int:
    graph: dict[str, set[str]] = defaultdict(set)
    for left, right in edges:
        graph[left].add(right)
        graph[right].add(left)
    largest = 0
    unseen = set(nodes)
    while unseen:
        root = unseen.pop()
        queue = deque([root])
        size = 0
        while queue:
            current = queue.popleft()
            size += 1
            for neighbor in graph.get(current, set()):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        largest = max(largest, size)
    return largest


def score_trajectory(
    trajectory: dict[str, Any],
    *,
    baseline_probe_score: float = 100.0,
) -> dict[str, Any]:
    events = [item for item in trajectory.get("events", []) if isinstance(item, dict)]
    actions = [item for item in events if item.get("event_type") == "model_action"]
    successes = [item for item in actions if item.get("status") == "success"]
    failures = [item for item in actions if item.get("status") != "success"]
    ai_ids = set(str(item) for item in trajectory.get("ai_agent_ids", []))
    human_id = str(trajectory.get("human_agent_id", "human_interactor"))
    success_rate = _ratio(len(successes), len(actions))
    reference_total = sum(len(item.get("responds_to_event_ids", [])) for item in actions)
    valid_reference_total = sum(
        len(item.get("responds_to_event_ids", []))
        for item in actions
        if "invalid_event_reference" not in item.get("violations", [])
    )
    route_valid_rate = _ratio(
        sum(not any(code in item.get("violations", []) for code in ("invalid_actor", "invalid_target", "invalid_route", "illegal_move")) for item in actions),
        len(actions),
    )
    generic_routes = {"creator_world_chat", "ease_world_tension", "model_cinematic_interaction"}
    grounded = [
        item for item in successes
        if item.get("action_type") == "propose"
        or (item.get("action_type") == "catalog" and item.get("route_id") not in generic_routes)
        or item.get("action_type") == "move"
    ]
    actors = {str(item.get("actor_id", "")) for item in successes if item.get("actor_id") in ai_ids}
    executable = _mean([
        success_rate,
        route_valid_rate,
        _clip(_ratio(len(actors), min(10, len(ai_ids)))),
        _ratio(len(grounded), len(successes)),
    ])

    moves = [item for item in actions if item.get("action_type") == "move"]
    move_successes = [item for item in moves if item.get("status") == "success"]
    destinations = {str(item.get("destination_room_id", "")) for item in move_successes}
    mobile_actors = {str(item.get("actor_id", "")) for item in move_successes}
    room_count = int(trajectory.get("room_count", 0))
    spatial = _mean([
        _ratio(len(move_successes), len(moves)) if moves else 0.0,
        _clip(_ratio(len(destinations), min(4, room_count))),
        _clip(_ratio(len(mobile_actors), min(6, len(ai_ids)))),
    ])

    mutation_kinds = {kind for item in successes for kind in item.get("mutation_kinds", [])}
    changed_rounds = {int(item.get("round_index", 0)) for item in successes if item.get("state_changed")}
    serialization_ok = bool(trajectory.get("persistence_check", {}).get("roundtrip_equal"))
    persistent = _mean([
        _ratio(sum(bool(item.get("state_changed")) for item in successes), len(successes)),
        _clip(_ratio(len(mutation_kinds), 4)),
        float(serialization_ok),
        _clip(_ratio(len(changed_rounds), 18)),
    ])

    dyad_counts: Counter[tuple[str, str]] = Counter()
    edges: set[tuple[str, str]] = set()
    for item in successes:
        actor, target = str(item.get("actor_id", "")), str(item.get("target_id", ""))
        if actor and target and actor != target:
            pair = tuple(sorted((actor, target)))
            dyad_counts[pair] += 1
            edges.add(pair)
    repeated = sum(count >= 2 for count in dyad_counts.values())
    social_nodes = ai_ids | {human_id}
    relation_edges = int(trajectory.get("final_observations", {}).get("relationship_edge_count", 0))
    social = _mean([
        _clip(_ratio(len(actors), min(10, len(ai_ids)))),
        _clip(_ratio(len(dyad_counts), 14)),
        _clip(_ratio(repeated, 6)),
        _ratio(_largest_component(edges, social_nodes), len(social_nodes)),
        _clip(_ratio(relation_edges, 10)),
    ])

    human_actions = [item for item in successes if item.get("target_id") == human_id]
    human_refs = [
        item for item in human_actions
        if set(item.get("responds_to_event_ids", [])) & {"human_request_r05", "human_followup_r21"}
    ]
    human_mutations = [item for item in human_actions if item.get("state_changed")]
    late_human = [item for item in human_refs if int(item.get("round_index", 0)) >= 21]
    human = _mean([
        _clip(_ratio(len(human_actions), 4)),
        _clip(_ratio(len(human_refs), 2)),
        _clip(_ratio(len(human_mutations), 2)),
        float(bool(late_human)),
    ])

    proposals = [item for item in actions if item.get("action_type") == "propose"]
    approved = [item for item in proposals if item.get("status") == "success" and item.get("coordinator_decision", {}).get("status") == "approved"]
    proposal_names = {_slug(str(item.get("proposal_name", ""))) for item in approved if item.get("proposal_name")}
    proposal_effects = {kind for item in approved for kind in item.get("proposal_effect_kinds", [])}
    recovered = [
        item for item in successes
        if "coordinator_rejection_r09" in item.get("responds_to_event_ids", [])
        and 9 <= int(item.get("round_index", 0)) <= 16
    ]
    open_action = _mean([
        _clip(_ratio(len(approved), 5)),
        _clip(_ratio(len(proposal_names), 4)),
        _clip(_ratio(len(proposal_effects), 3)),
        float(bool(recovered)),
    ])

    rejected = [item for item in events if item.get("status") in {"rejected", "revise"} or "coordinator_rejected" in item.get("violations", [])]
    rejected_unchanged = all(not item.get("state_changed") for item in rejected)
    illegal_accepts = [
        item for item in approved
        if item.get("coordinator_decision")
        and not all(item.get("coordinator_decision", {}).get("checks", {}).values())
    ]
    invalid_reference_actions = [
        item for item in actions
        if any(code in item.get("violations", []) for code in ("invalid_actor", "invalid_target", "invalid_route", "illegal_move"))
    ]
    integrity = _mean([
        float(rejected_unchanged),
        float(not illegal_accepts),
        1.0 - _ratio(len(invalid_reference_actions), len(actions)),
        _clip(baseline_probe_score / 100.0),
    ])

    active_rounds = {int(item.get("round_index", 0)) for item in successes}
    late_rounds = {round_index for round_index in active_rounds if round_index >= 17}
    threads: dict[str, set[int]] = defaultdict(set)
    thread_dyads: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for item in successes:
        thread_id = str(item.get("thread_id", ""))
        if thread_id:
            threads[thread_id].add((int(item.get("round_index", 0)) - 1) // 4)
            if item.get("target_id"):
                thread_dyads[thread_id].add(tuple(sorted((str(item.get("actor_id", "")), str(item.get("target_id", ""))))))
    spanning_threads = sum(len(blocks) >= 2 for blocks in threads.values())
    cross_dyad_threads = sum(len(pairs) >= 2 for pairs in thread_dyads.values())
    temporal = _mean([
        _ratio(len(active_rounds), 24),
        _ratio(len(late_rounds), 8),
        _clip(_ratio(spanning_threads, 3)),
        _clip(_ratio(valid_reference_total, max(1, reference_total))) if reference_total else 0.0,
        _clip(_ratio(cross_dyad_threads, 2)),
    ])

    raw_axes = {
        "executable_grounding": executable,
        "spatial_mobility": spatial,
        "persistent_consequences": persistent,
        "social_continuity": social,
        "human_integration": human,
        "open_action_recovery": open_action,
        "institutional_integrity": integrity,
        "temporal_progression": temporal,
    }
    score = 100.0 * math.exp(sum(weight * math.log(max(0.0001, raw_axes[name])) for name, weight in AXIS_WEIGHTS.items()))
    cap = 100.0
    cap_reasons = []
    completed_checkpoints = int(trajectory.get("completed_checkpoints", 0))
    if completed_checkpoints < len(CHECKPOINTS) or len(actions) < 48:
        cap = min(cap, 49.0)
        cap_reasons.append("incomplete_24_round_policy")
    if not human_refs:
        cap = min(cap, 59.0)
        cap_reasons.append("no_substantive_human_uptake")
    if not approved:
        cap = min(cap, 59.0)
        cap_reasons.append("no_approved_open_action")
    if not rejected_unchanged or illegal_accepts or not serialization_ok:
        cap = min(cap, 49.0)
        cap_reasons.append("institutional_or_persistence_failure")
    if success_rate < 0.5:
        cap = min(cap, 59.0)
        cap_reasons.append("fewer_than_half_actions_executed")
    return {
        "score": round(min(score, cap), 2),
        "uncapped_score": round(score, 2),
        "score_cap": cap,
        "cap_reasons": cap_reasons,
        "axes": {name: round(100.0 * value, 2) for name, value in raw_axes.items()},
        "observations": {
            "actions_planned": len(actions),
            "actions_succeeded": len(successes),
            "actions_failed": len(failures),
            "success_rate": round(success_rate, 4),
            "active_round_count": len(active_rounds),
            "participating_ai_agents": len(actors),
            "unique_dyads": len(dyad_counts),
            "repeated_dyads": repeated,
            "relationship_edge_count": relation_edges,
            "successful_moves": len(move_successes),
            "visited_destinations": len(destinations),
            "mutation_kinds": sorted(mutation_kinds),
            "human_target_actions": len(human_actions),
            "human_event_responses": len(human_refs),
            "open_proposals": len(proposals),
            "approved_open_proposals": len(approved),
            "recovery_actions": len(recovered),
            "spanning_threads": spanning_threads,
            "rejected_actions_state_unchanged": rejected_unchanged,
            "illegal_approved_actions": len(illegal_accepts),
        },
    }


def run_model(
    model: str,
    *,
    config: dict[str, Any],
    output_root: Path,
    api_key_env: str,
    thinking_level: str,
    provider: str = "gemini",
) -> dict[str, Any]:
    slug = MODELS[model]
    model_root = output_root / slug
    state, world_rules = _load_runtime(config, model_root / "scenario")
    human_id = str(config.get("human_interaction", {}).get("runtime_human_agent_id", "human_interactor"))
    ai_ids = [agent.agent_id for agent in state.agents if agent.agent_id != human_id]
    initial_hash = _state_hash(state)
    events: list[dict[str, Any]] = []
    plans = []
    client = (
        OpenAIResponsesJsonClient(_openai_client_config(model, api_key_env, thinking_level))
        if provider == "openai"
        else VertexJsonClient(_client_config(model, api_key_env, thinking_level))
    )
    acted: set[tuple[int, str]] = set()
    completed = 0
    started = time.perf_counter()
    for checkpoint in CHECKPOINTS:
        intervention = _intervention(checkpoint, state=state, config=config, events=events)
        before_calls = len(client.call_history)
        call_started = time.perf_counter()
        try:
            plan = client.generate_json(
                system_instruction=(
                    "You are the multi-agent policy for a persistent typed world. Plan grounded intentions for AI "
                    "characters; the world coordinator validates legality and alone commits effects. Preserve identity, "
                    "ownership, locality, prior events, and the human player's agency while advancing specific threads."
                ),
                prompt=_runtime_prompt(
                    config=config,
                    state=state,
                    events=events,
                    checkpoint=checkpoint,
                    intervention=intervention,
                ),
                schema=_plan_schema(),
                stage="generated_world_runtime",
            )
            actions = plan.get("actions", []) if isinstance(plan, dict) else []
            offset_counts = Counter(
                int(item.get("round_offset", -1))
                for item in actions
                if isinstance(item, dict)
            )
            policy_shape_valid = len(actions) == 12 and all(offset_counts[index] == 3 for index in range(4))
            plans.append({
                "checkpoint": checkpoint,
                "status": "ok",
                "policy_shape_valid": policy_shape_valid,
                "latency_seconds": round(time.perf_counter() - call_started, 3),
                "plan": plan,
                "telemetry": client.call_history[before_calls:],
            })
            for index, raw in enumerate(sorted(
                (item for item in actions if isinstance(item, dict)),
                key=lambda item: int(item.get("round_offset", 99)),
            )):
                round_index = checkpoint + int(raw.get("round_offset", 0))
                event = execute_action(
                    raw,
                    event_id=f"model_r{round_index:02d}_{index + 1:02d}",
                    round_index=round_index,
                    state=state,
                    config=config,
                    world_rules=world_rules,
                    known_event_ids={str(item.get("event_id", "")) for item in events},
                    acted=acted,
                )
                events.append(event)
            completed += int(policy_shape_valid)
        except Exception as exc:
            plans.append({
                "checkpoint": checkpoint,
                "status": "error",
                "latency_seconds": round(time.perf_counter() - call_started, 3),
                "error": str(exc)[:2000],
                "telemetry": client.call_history[before_calls:],
            })
    final_dump = state.model_dump(mode="json")
    restored = AgentStateBundleSpec.model_validate(deepcopy(final_dump))
    persistence = {
        "roundtrip_equal": restored.model_dump(mode="json") == final_dump,
        "final_state_hash": _state_hash(state),
        "restored_state_hash": _state_hash(restored),
    }
    final_observations = {
        "relationship_edge_count": sum(len(targets) for targets in state.relationship_tensor.values()),
        "status_effect_count": sum(len(agent.status_effects) for agent in state.agents),
        "inventory_unit_count": sum(item.quantity for agent in state.agents for item in agent.inventory),
        "room_occupancy": dict(Counter(agent.room_id for agent in state.agents)),
    }
    trajectory = {
        "benchmark": "Agora Generated-World Runtime Evaluation",
        "scoring_version": SCORING_VERSION,
        "model": model,
        "world_name": config.get("scenario_meta", {}).get("world_name", ""),
        "prompt_id": PROMPT_ID,
        "round_count": 24,
        "checkpoints": list(CHECKPOINTS),
        "completed_checkpoints": completed,
        "initial_state_hash": initial_hash,
        "ai_agent_ids": ai_ids,
        "human_agent_id": human_id,
        "room_count": len(config.get("space", {}).get("rooms", [])),
        "plans": plans,
        "events": events,
        "persistence_check": persistence,
        "final_observations": final_observations,
        "final_state": final_dump,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    _write(model_root / "trajectory.json", trajectory)
    return trajectory


def _baseline_probe(benchmark_root: Path, model: str) -> float:
    manifest = _read(benchmark_root / "visual_cases" / "case_manifest.json")
    row = next((item for item in manifest.get("models", []) if item.get("model") == model), {})
    return float(row.get("interaction_score", 0.0) or 0.0)


def aggregate_replicate_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    if not scores:
        raise ValueError("at least one replicate score is required")
    count_keys = {
        "actions_planned",
        "actions_succeeded",
        "actions_failed",
        "active_round_count",
        "human_target_actions",
        "human_event_responses",
        "open_proposals",
        "approved_open_proposals",
        "recovery_actions",
        "illegal_approved_actions",
    }
    mean_keys = {
        "participating_ai_agents",
        "unique_dyads",
        "repeated_dyads",
        "relationship_edge_count",
        "successful_moves",
        "visited_destinations",
        "spanning_threads",
    }
    observations: dict[str, Any] = {}
    for key in count_keys:
        observations[key] = sum(int(score.get("observations", {}).get(key, 0) or 0) for score in scores)
    for key in mean_keys:
        observations[key] = round(_mean(float(score.get("observations", {}).get(key, 0) or 0) for score in scores), 2)
    observations["success_rate"] = round(
        _ratio(observations["actions_succeeded"], observations["actions_planned"]),
        4,
    )
    observations["mutation_kinds"] = sorted({
        kind
        for score in scores
        for kind in score.get("observations", {}).get("mutation_kinds", [])
    })
    observations["rejected_actions_state_unchanged"] = all(
        score.get("observations", {}).get("rejected_actions_state_unchanged") is True
        for score in scores
    )
    observations["human_successful_replicates"] = sum(
        int(score.get("observations", {}).get("human_event_responses", 0) or 0) > 0
        for score in scores
    )
    observations["recovery_successful_replicates"] = sum(
        int(score.get("observations", {}).get("recovery_actions", 0) or 0) > 0
        for score in scores
    )
    values = [float(score["score"]) for score in scores]
    return {
        "score": round(_mean(values), 2),
        "score_stddev": round(statistics.pstdev(values), 2),
        "score_min": round(min(values), 2),
        "score_max": round(max(values), 2),
        "uncapped_score": round(_mean(float(score["uncapped_score"]) for score in scores), 2),
        "replicate_count": len(scores),
        "replicate_scores": values,
        "cap_reasons_by_replicate": [list(score.get("cap_reasons", [])) for score in scores],
        "axes": {
            axis: round(_mean(float(score.get("axes", {}).get(axis, 0.0)) for score in scores), 2)
            for axis in AXIS_WEIGHTS
        },
        "observations": observations,
    }


def run_suite(
    *,
    benchmark_root: Path,
    models: list[str],
    api_key_env: str,
    thinking_level: str,
    output: Path,
    replicates: int = 1,
    provider: str = "gemini",
) -> dict[str, Any]:
    if not os.environ.get(api_key_env):
        raise RuntimeError(f"{api_key_env} is not set")
    if replicates < 1:
        raise ValueError("replicates must be at least one")
    trajectory_root = benchmark_root / ("runtime_trajectories" if replicates == 1 else "runtime_trajectories_v2")
    model_runs = []
    for model in models:
        slug = MODELS[model]
        config_path = (
            benchmark_root / "confirmatory_runs" / slug / PROMPT_ID /
            f"{PROMPT_ID}_r01_decomposed_world_config.json"
        )
        config = _read(config_path)
        replicate_rows = []
        for replicate_index in range(1, replicates + 1):
            replicate_root = trajectory_root if replicates == 1 else trajectory_root / f"replicate_{replicate_index:02d}"
            trajectory = run_model(
                model,
                config=config,
                output_root=replicate_root,
                api_key_env=api_key_env,
                thinking_level=thinking_level,
                provider=provider,
            )
            score = score_trajectory(trajectory, baseline_probe_score=_baseline_probe(benchmark_root, model))
            replicate_rows.append({
                "replicate_index": replicate_index,
                "score": score,
                "trajectory_path": str((replicate_root / slug / "trajectory.json").relative_to(benchmark_root)),
                "elapsed_seconds": trajectory["elapsed_seconds"],
                "completed_checkpoints": trajectory["completed_checkpoints"],
            })
            print(f"[runtime] {model} replicate {replicate_index}: {score['score']:.2f}", flush=True)
        aggregate = aggregate_replicate_scores([row["score"] for row in replicate_rows])
        model_runs.append({
            "model": model,
            "score": aggregate if replicates > 1 else replicate_rows[0]["score"],
            "trajectory_path": replicate_rows[0]["trajectory_path"],
            "trajectory_paths": [row["trajectory_path"] for row in replicate_rows],
            "replicates": replicate_rows,
            "elapsed_seconds": round(sum(float(row["elapsed_seconds"]) for row in replicate_rows), 3),
            "completed_checkpoints": sum(int(row["completed_checkpoints"]) for row in replicate_rows),
        })
    ranking = sorted(model_runs, key=lambda item: item["score"]["score"], reverse=True)
    payload = {
        "benchmark": "Agora Generated-World Runtime Evaluation",
        "scoring_version": SCORING_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "prompt_id": PROMPT_ID,
            "rounds": 24,
            "replicate_count": replicates,
            "total_rounds_per_model": 24 * replicates,
            "checkpoint_rounds": list(CHECKPOINTS),
            "actions_per_checkpoint": 12,
            "api_calls_per_model_per_replicate": 6,
            "api_calls_per_model_total": 6 * replicates,
            "temperature": 0.75,
            "thinking_level": thinking_level,
            "api_backend": "OpenAI Responses API" if provider == "openai" else "Gemini Developer API generateContent",
            "score_method": "deterministic execution trace rubric; no LLM judge",
            "state_commit": "Agora coordinator and universal custom-action handler",
            "interventions": ["human request", "coordinator rejection", "resource shock", "cross-room request", "human follow-up"],
        },
        "axis_weights": AXIS_WEIGHTS,
        "ranking": ranking,
    }
    _write(output, payload)
    return payload


def rescore(*, benchmark_root: Path, input_path: Path, output: Path) -> dict[str, Any]:
    prior = _read(input_path)
    for row in prior.get("ranking", []):
        replicate_rows = row.get("replicates", []) if isinstance(row.get("replicates"), list) else []
        if replicate_rows:
            scores = []
            for replicate in replicate_rows:
                trajectory = _read(benchmark_root / str(replicate["trajectory_path"]))
                replicate["score"] = score_trajectory(
                    trajectory,
                    baseline_probe_score=_baseline_probe(benchmark_root, str(row["model"])),
                )
                scores.append(replicate["score"])
            row["score"] = aggregate_replicate_scores(scores)
        else:
            trajectory = _read(benchmark_root / str(row["trajectory_path"]))
            row["score"] = score_trajectory(
                trajectory,
                baseline_probe_score=_baseline_probe(benchmark_root, str(row["model"])),
            )
    prior["ranking"] = sorted(prior.get("ranking", []), key=lambda item: item["score"]["score"], reverse=True)
    prior["scoring_version"] = SCORING_VERSION
    prior["axis_weights"] = AXIS_WEIGHTS
    replicate_count = int(prior.get("protocol", {}).get("replicate_count", 1) or 1)
    prior.setdefault("protocol", {}).pop("api_calls_per_model", None)
    prior["protocol"]["api_calls_per_model_per_replicate"] = 6
    prior["protocol"]["api_calls_per_model_total"] = 6 * replicate_count
    _write(output, prior)
    return prior


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--benchmark-root", type=Path, default=BENCHMARK_ROOT)
    run_parser.add_argument("--models", nargs="+", choices=tuple(MODELS), default=list(MODELS))
    run_parser.add_argument("--api-key-env", default="AGORA_AISTUDIO_API_KEY")
    run_parser.add_argument("--provider", choices=("gemini", "openai"), default="gemini")
    run_parser.add_argument("--thinking-level", choices=("minimal", "low", "medium", "high"), default="low")
    run_parser.add_argument("--replicates", type=int, default=1)
    run_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    score_parser = subparsers.add_parser("rescore")
    score_parser.add_argument("--benchmark-root", type=Path, default=BENCHMARK_ROOT)
    score_parser.add_argument("--input", type=Path, default=DEFAULT_OUTPUT)
    score_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.command == "run":
        run_suite(
            benchmark_root=args.benchmark_root.resolve(),
            models=list(args.models),
            api_key_env=args.api_key_env,
            thinking_level=args.thinking_level,
            output=args.output.resolve(),
            replicates=args.replicates,
            provider=args.provider,
        )
    else:
        rescore(
            benchmark_root=args.benchmark_root.resolve(),
            input_path=args.input.resolve(),
            output=args.output.resolve(),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
