"""
Core Universal Adjudicator Module

This module replaces the legacy monolithic `run_universal_adjudicator.py`.
It serves as the main entry point for world orchestration and simulation 
adjudication, adhering to a strict, decoupled package architecture.
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agora_ui.adjudicator_schemas import (
    ActionIntentSpec,
    AdjudicatorControlSpec,
    AdjudicatorManifestSpec,
    AdjudicatorPromptSpec,
    AgentIntentBatchSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    InventoryItemSpec,
    RelationshipVectorSpec,
    StatusEffectSpec,
    WorldRulesSpec,
)
from agora_ui.flex_client import FlexClient
from agora_ui.foundation_schemas import GridPosition, RoomSpec
from agora_ui.jsonc_utils import dump_json, load_jsonc_path

from .geometry import (
    _coord_key,
    _coord_text,
    _room_for_position,
)
from .utils import (
    _add_action_result,
    _add_broadcast,
)
from .handlers_movement import _handle_move
from .handlers_items import _handle_item
from .handlers_custom import _handle_custom
from .handlers_images import _handle_image


SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_TEMPLATE_DIR = SCRIPT_DIR / "data" / "templates" / "foundation"
DEFAULT_CONTROL_FILE = DEFAULT_TEMPLATE_DIR / "adjudicator_control.jsonc"
DEFAULT_WORLD_RULES_FILE = DEFAULT_TEMPLATE_DIR / "world_rules.jsonc"
DEFAULT_AGENT_STATE_FILE = DEFAULT_TEMPLATE_DIR / "adjudicator_agent_profiles.jsonc"
DEFAULT_INTENTS_FILE = DEFAULT_TEMPLATE_DIR / "adjudicator_agent_intents.jsonc"
DEFAULT_OUTPUT_ROOT = SCRIPT_DIR / "output" / "universal_adjudicator"


def _resolve_path(path_like: Path | str) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path.resolve()
    local = (SCRIPT_DIR / path).resolve()
    if local.exists():
        return local
    return (Path.cwd() / path).resolve()


def _now_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _render_prompt(prompt: AdjudicatorPromptSpec, control: AdjudicatorControlSpec) -> str:
    text = "\n".join(prompt.template_lines)
    social_norms = "\n".join(f"- {item}" for item in control.social_norms) or "(none)"
    return (
        text.replace("{{WORLD_DESCRIPTION}}", control.world_description)
        .replace("{{SIMULATION_OBJECTIVE}}", control.simulation_objective)
        .replace("{{SOCIAL_NORMS}}", social_norms)
    )


def _load_prompt(path: Path) -> AdjudicatorPromptSpec:
    return AdjudicatorPromptSpec.model_validate(load_jsonc_path(path))


def _load_control(path: Path) -> AdjudicatorControlSpec:
    return AdjudicatorControlSpec.model_validate(load_jsonc_path(path))


def _load_world_rules(path: Path) -> WorldRulesSpec:
    return WorldRulesSpec.model_validate(load_jsonc_path(path))


def _load_agent_state(path: Path) -> AgentStateBundleSpec:
    return AgentStateBundleSpec.model_validate(load_jsonc_path(path))


def _load_intents(path: Path) -> AgentIntentBatchSpec:
    return AgentIntentBatchSpec.model_validate(load_jsonc_path(path))


def _agent_map(state: AgentStateBundleSpec) -> Dict[str, AgentRuntimeProfileSpec]:
    return {agent.agent_id: agent for agent in state.agents}


def _decay_status_effects(
    state: AgentStateBundleSpec,
    mutations: dict[str, Any],
) -> None:
    for agent in state.agents:
        kept: list[StatusEffectSpec] = []
        expired: list[dict[str, Any]] = []
        decayed: list[dict[str, Any]] = []
        for effect in agent.status_effects:
            before = effect.model_dump()
            next_duration = int(effect.duration_steps) - 1
            if next_duration <= 0:
                expired.append(before)
                continue
            updated = effect.model_copy(update={"duration_steps": next_duration})
            kept.append(updated)
            if next_duration != effect.duration_steps:
                decayed.append({"before": before, "after": updated.model_dump()})
        if expired or decayed:
            agent.status_effects = kept
            mutations["profile_updates"].append(
                {
                    "agent_id": agent.agent_id,
                    "status_effects_decayed": decayed,
                    "status_effects_expired": expired,
                }
            )


def _build_agent_prompt_injections(state: AgentStateBundleSpec) -> list[dict[str, Any]]:
    injections: list[dict[str, Any]] = []
    agents = _agent_map(state)
    for source_id, agent in agents.items():
        relationships = state.relationship_tensor.get(source_id, {})
        peers: list[dict[str, Any]] = []
        for target_id, vector in relationships.items():
            if target_id not in agents:
                continue
            posture = "guarded"
            if vector.trust >= 70:
                posture = "open"
            elif vector.trust <= 35:
                posture = "deceptive_or_protective"
            peers.append(
                {
                    "target_agent_id": target_id,
                    "target_display_name": agents[target_id].display_name or target_id,
                    "relationship_tensor": vector.model_dump(),
                    "recommended_persona_posture": posture,
                }
            )
        injections.append(
            {
                "agent_id": source_id,
                "display_name": agent.display_name or source_id,
                "gender_presentation": agent.gender_presentation,
                "appearance_prompt": agent.appearance_prompt,
                "current_coordinate": agent.coordinates.model_dump(),
                "room_id": agent.room_id,
                "relationship_context": peers,
            }
        )
    return injections


def _local_adjudicate(
    *,
    control: AdjudicatorControlSpec,
    world_rules: WorldRulesSpec,
    agent_state: AgentStateBundleSpec,
    intent_batch: AgentIntentBatchSpec,
) -> Tuple[dict[str, Any], AgentStateBundleSpec, WorldRulesSpec]:
    state = agent_state.model_copy(deep=True)
    rules = world_rules.model_copy(deep=True)
    agents = _agent_map(state)
    for agent in agents.values():
        agent.room_id = _room_for_position(agent.coordinates, rules.topology.rooms)

    start_positions = {
        agent_id: agent.coordinates.model_copy(deep=True)
        for agent_id, agent in agents.items()
    }
    priority = {call: index for index, call in enumerate(control.priority_order)}
    ordered_intents = sorted(
        intent_batch.intents,
        key=lambda item: (priority.get(item.call, 999), item.intent_id),
    )
    moved_agent_ids: set[str] = set()
    broadcasts: list[dict[str, Any]] = []
    rule_appendices: list[dict[str, Any]] = []
    mutations: dict[str, Any] = {
        "coordinate_updates": [],
        "inventory_updates": [],
        "relationship_tensor_updates": [],
        "profile_updates": [],
        "visual_state_updates": [],
        "action_results": [],
        "agent_prompt_injections": [],
    }
    _decay_status_effects(state, mutations)

    for intent in ordered_intents:
        before_positions = {
            agent_id: _coord_key(agent.coordinates)
            for agent_id, agent in agents.items()
        }
        if intent.call == "Move":
            _handle_move(
                control=control,
                world_rules=rules,
                state=state,
                agents=agents,
                intent=intent,
                broadcasts=broadcasts,
                mutations=mutations,
            )
            actor = agents.get(intent.agent_id)
            if actor is not None and before_positions.get(intent.agent_id) != _coord_key(actor.coordinates):
                moved_agent_ids.add(intent.agent_id)
            continue
        if intent.call == "Custom":
            _handle_custom(
                control=control,
                world_rules=rules,
                state=state,
                agents=agents,
                start_positions=start_positions,
                moved_agent_ids=moved_agent_ids,
                intent=intent,
                broadcasts=broadcasts,
                mutations=mutations,
                rule_appendices=rule_appendices,
            )
            continue
        if intent.call == "Item":
            _handle_item(
                control=control,
                world_rules=rules,
                state=state,
                agents=agents,
                intent=intent,
                broadcasts=broadcasts,
                mutations=mutations,
                rule_appendices=rule_appendices,
            )
            continue
        if intent.call == "Image":
            _handle_image(
                control=control,
                world_rules=rules,
                state=state,
                agents=agents,
                intent=intent,
                broadcasts=broadcasts,
                mutations=mutations,
                rule_appendices=rule_appendices,
            )

    mutations["agent_prompt_injections"] = _build_agent_prompt_injections(state)
    return (
        {
            "Global_Event_Broadcast": broadcasts,
            "State_Mutations": mutations,
            "Rule_Appendices": rule_appendices if rules.world_mode == "LLM_Wrap" else [],
        },
        state,
        rules,
    )


def _build_flex_payload(
    *,
    control: AdjudicatorControlSpec,
    world_rules: WorldRulesSpec,
    agent_state: AgentStateBundleSpec,
    intent_batch: AgentIntentBatchSpec,
) -> dict[str, Any]:
    return {
        "timestep_index": intent_batch.timestep_index,
        "world_mode": world_rules.world_mode,
        "priority_order": control.priority_order,
        "World_Rules": world_rules.model_dump(),
        "Agent_Profiles": agent_state.model_dump(),
        "Intent_Batch": intent_batch.model_dump(),
        "required_output_keys": [
            "Global_Event_Broadcast",
            "State_Mutations",
            "Rule_Appendices",
        ],
    }


def _flex_adjudicate(
    *,
    control: AdjudicatorControlSpec,
    rendered_prompt: str,
    world_rules: WorldRulesSpec,
    agent_state: AgentStateBundleSpec,
    intent_batch: AgentIntentBatchSpec,
) -> dict[str, Any]:
    client = FlexClient(api_url=control.flex.flex_api_url)
    response_schema = {
        "Global_Event_Broadcast": [],
        "State_Mutations": {},
        "Rule_Appendices": [],
    }
    return client.generate_json(
        prompt=json.dumps(
            _build_flex_payload(
                control=control,
                world_rules=world_rules,
                agent_state=agent_state,
                intent_batch=intent_batch,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        system_instruction=rendered_prompt,
        model=control.flex.model or None,
        temperature=control.flex.temperature,
        max_output_tokens=control.flex.max_output_tokens,
        thinking_level=control.flex.thinking_level,
        response_schema=response_schema,
        timeout_seconds=control.flex.timeout_seconds,
    )


def _append_visual_state(
    state: AgentStateBundleSpec,
    key: str,
    value: Any,
) -> int:
    events = state.localized_visual_state.setdefault(str(key), [])
    before_count = len(events)
    if isinstance(value, list):
        for item in value:
            events.append(item if isinstance(item, dict) else {"value": item})
    elif isinstance(value, dict):
        events.append(value)
    else:
        events.append({"value": value})
    return len(events) - before_count


def _apply_flex_output_to_state(
    *,
    adjudicator_output: dict[str, Any],
    agent_state: AgentStateBundleSpec,
    world_rules: WorldRulesSpec,
) -> Tuple[AgentStateBundleSpec, WorldRulesSpec, dict[str, Any]]:
    state = agent_state.model_copy(deep=True)
    rules = world_rules.model_copy(deep=True)
    diagnostics = {
        "agent_updates_applied": 0,
        "relationship_updates_applied": 0,
        "visual_updates_applied": 0,
        "rule_appendices_applied": 0,
        "ignored_mutation_keys": [],
        "apply_errors": [],
    }
    agents = _agent_map(state)

    if rules.world_mode == "LLM_Wrap":
        for appendix in adjudicator_output.get("Rule_Appendices", []) or []:
            if isinstance(appendix, dict):
                rules.discovered_rules.append(appendix)
                diagnostics["rule_appendices_applied"] += 1

    mutations = adjudicator_output.get("State_Mutations", {})
    if not isinstance(mutations, dict):
        diagnostics["apply_errors"].append("State_Mutations is not a JSON object")
        return state, rules, diagnostics

    def apply_agent_payload(agent_id: str, payload: Any) -> None:
        agent = agents.get(agent_id)
        if agent is None or not isinstance(payload, dict):
            return
        changed = False
        if "coordinates" in payload:
            try:
                agent.coordinates = GridPosition.model_validate(payload["coordinates"])
                changed = True
            except Exception as exc:
                diagnostics["apply_errors"].append(f"{agent_id}.coordinates: {exc}")
        if "room_id" in payload:
            agent.room_id = str(payload["room_id"])
            changed = True
        elif "coordinates" in payload:
            agent.room_id = _room_for_position(agent.coordinates, rules.topology.rooms)
            changed = True
        if "inventory" in payload and isinstance(payload["inventory"], list):
            try:
                parsed_inventory = [
                    InventoryItemSpec.model_validate(item)
                    for item in payload["inventory"]
                    if isinstance(item, dict)
                ]
                agent.inventory = [item for item in parsed_inventory if item.quantity > 0]
                changed = True
            except Exception as exc:
                diagnostics["apply_errors"].append(f"{agent_id}.inventory: {exc}")
        if "status_effects" in payload and isinstance(payload["status_effects"], list):
            try:
                agent.status_effects = [
                    StatusEffectSpec.model_validate(item)
                    for item in payload["status_effects"]
                    if isinstance(item, dict)
                ]
                changed = True
            except Exception as exc:
                diagnostics["apply_errors"].append(f"{agent_id}.status_effects: {exc}")
        if "public_state" in payload and isinstance(payload["public_state"], dict):
            agent.public_state.update(payload["public_state"])
            changed = True
        if "relationship_tensor" in payload and isinstance(payload["relationship_tensor"], dict):
            state.relationship_tensor.setdefault(agent_id, {})
            for target_agent_id, vector_payload in payload["relationship_tensor"].items():
                if not isinstance(vector_payload, dict):
                    continue
                try:
                    state.relationship_tensor[agent_id][str(target_agent_id)] = (
                        RelationshipVectorSpec.model_validate(vector_payload)
                    )
                    diagnostics["relationship_updates_applied"] += 1
                except Exception as exc:
                    diagnostics["apply_errors"].append(
                        f"{agent_id}.relationship_tensor.{target_agent_id}: {exc}"
                    )
        if changed:
            diagnostics["agent_updates_applied"] += 1

    for key, value in mutations.items():
        if key in agents:
            apply_agent_payload(str(key), value)
            continue
        if key == "relationship_tensor" and isinstance(value, dict):
            for source_agent_id, targets in value.items():
                if not isinstance(targets, dict):
                    continue
                state.relationship_tensor.setdefault(str(source_agent_id), {})
                for target_agent_id, vector_payload in targets.items():
                    if not isinstance(vector_payload, dict):
                        continue
                    try:
                        state.relationship_tensor[str(source_agent_id)][str(target_agent_id)] = (
                            RelationshipVectorSpec.model_validate(vector_payload)
                        )
                        diagnostics["relationship_updates_applied"] += 1
                    except Exception as exc:
                        diagnostics["apply_errors"].append(
                            f"relationship_tensor.{source_agent_id}.{target_agent_id}: {exc}"
                        )
            continue
        if key == "agents" and isinstance(value, dict):
            for agent_id, payload in value.items():
                apply_agent_payload(str(agent_id), payload)
            continue
        if key == "localized_visual_state" and isinstance(value, dict):
            for visual_key, visual_value in value.items():
                diagnostics["visual_updates_applied"] += _append_visual_state(
                    state,
                    str(visual_key),
                    visual_value,
                )
            continue
        if key == "coordinate_updates" and isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                agent_id = str(item.get("agent_id", ""))
                payload = {"coordinates": item.get("to")}
                if item.get("to_room_id"):
                    payload["room_id"] = item.get("to_room_id")
                apply_agent_payload(agent_id, payload)
            continue
        if key == "profile_updates" and isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                agent = agents.get(str(item.get("agent_id", "")))
                effect_payload = item.get("status_effect_added")
                if agent is None or not isinstance(effect_payload, dict):
                    continue
                try:
                    agent.status_effects.append(StatusEffectSpec.model_validate(effect_payload))
                    diagnostics["agent_updates_applied"] += 1
                except Exception as exc:
                    diagnostics["apply_errors"].append(f"profile_updates.status_effect_added: {exc}")
            continue
        if key == "relationship_tensor_updates" and isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                source_id = str(item.get("source_agent_id", ""))
                target_id = str(item.get("target_agent_id", ""))
                after = item.get("after")
                if not source_id or not target_id or not isinstance(after, dict):
                    continue
                try:
                    state.relationship_tensor.setdefault(source_id, {})[target_id] = (
                        RelationshipVectorSpec.model_validate(after)
                    )
                    diagnostics["relationship_updates_applied"] += 1
                except Exception as exc:
                    diagnostics["apply_errors"].append(f"relationship_tensor_updates: {exc}")
            continue
        if key == "visual_state_updates" and isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                visual_key = str(item.get("room_id") or item.get("coordinate") or "global")
                diagnostics["visual_updates_applied"] += _append_visual_state(state, visual_key, item)
            continue
        if key not in {"action_results", "agent_prompt_injections", "inventory_updates"}:
            diagnostics["ignored_mutation_keys"].append(str(key))

    return state, rules, diagnostics


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Universal Core Adjudicator from JSONC-controlled inputs."
    )
    parser.add_argument("--control-file", type=Path, default=DEFAULT_CONTROL_FILE)
    parser.add_argument("--world-rules-file", type=Path, default=DEFAULT_WORLD_RULES_FILE)
    parser.add_argument("--agent-state-file", type=Path, default=DEFAULT_AGENT_STATE_FILE)
    parser.add_argument("--intents-file", type=Path, default=DEFAULT_INTENTS_FILE)
    parser.add_argument("--prompt-file", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--validate-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--adjudication-backend-override",
        choices=["local", "flex"],
        default="",
        help="Override control.adjudication_backend without editing the JSONC control file.",
    )
    parser.add_argument(
        "--flex-api-url-override",
        type=str,
        default="",
        help="Override control.flex.flex_api_url without editing the JSONC control file.",
    )
    parser.add_argument(
        "--model-override",
        type=str,
        default="",
        help="Override control.flex.model without editing the JSONC control file.",
    )
    parser.add_argument(
        "--flex-timeout-override",
        type=float,
        default=0.0,
        help="Override control.flex.timeout_seconds when greater than zero.",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    control_path = _resolve_path(args.control_file)
    control = _load_control(control_path)
    if args.adjudication_backend_override:
        control.adjudication_backend = args.adjudication_backend_override
    if args.flex_api_url_override:
        control.flex.flex_api_url = args.flex_api_url_override
    if args.model_override:
        control.flex.model = args.model_override
    if args.flex_timeout_override > 0:
        control.flex.timeout_seconds = args.flex_timeout_override
    prompt_path = _resolve_path(args.prompt_file or control.prompt_file)
    world_rules_path = _resolve_path(args.world_rules_file)
    agent_state_path = _resolve_path(args.agent_state_file)
    intents_path = _resolve_path(args.intents_file)

    prompt = _load_prompt(prompt_path)
    world_rules = _load_world_rules(world_rules_path)
    agent_state = _load_agent_state(agent_state_path)
    intent_batch = _load_intents(intents_path)
    rendered_prompt = _render_prompt(prompt, control)

    run_id = _now_run_id()
    output_root_input = (
        Path(control.output_subdir)
        if Path(args.output_dir) == DEFAULT_OUTPUT_ROOT
        else Path(args.output_dir)
    )
    run_dir = _resolve_path(output_root_input) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    config_path = run_dir / "config.json"
    rendered_prompt_path = run_dir / "rendered_system_prompt.txt"
    rendered_prompt_path.write_text(rendered_prompt + "\n", encoding="utf-8")
    dump_json(
        config_path,
        {
            "run_id": run_id,
            "created_at": _now_iso(),
            "paths": {
                "control_file": str(control_path),
                "prompt_file": str(prompt_path),
                "world_rules_file": str(world_rules_path),
                "agent_state_file": str(agent_state_path),
                "intents_file": str(intents_path),
            },
            "validate_only": bool(args.validate_only),
            "backend": control.adjudication_backend,
            "flex": control.flex.model_dump(),
            "world_mode": world_rules.world_mode,
            "timestep_index": intent_batch.timestep_index,
        },
    )

    if args.validate_only:
        dump_json(
            run_dir / "validation.json",
            {
                "status": "ok",
                "message": "Universal Adjudicator JSONC inputs validated and prompt rendered",
                "rendered_prompt_file": str(rendered_prompt_path),
            },
        )
        print(f"[VALIDATE-ONLY] ok run_dir={run_dir}")
        return

    backend = control.adjudication_backend
    adjudicator_output: dict[str, Any]
    updated_state = agent_state
    updated_rules = world_rules
    diagnostics: dict[str, Any] = {}

    try:
        if control.adjudication_backend == "flex":
            adjudicator_output = _flex_adjudicate(
                control=control,
                rendered_prompt=rendered_prompt,
                world_rules=world_rules,
                agent_state=agent_state,
                intent_batch=intent_batch,
            )
            updated_state, updated_rules, apply_diagnostics = _apply_flex_output_to_state(
                adjudicator_output=adjudicator_output,
                agent_state=agent_state,
                world_rules=world_rules,
            )
            diagnostics["flex_status"] = "ok"
            diagnostics["flex_apply"] = apply_diagnostics
            if apply_diagnostics.get("apply_errors"):
                raise RuntimeError(
                    "failed to apply Flex output: "
                    + "; ".join(str(item) for item in apply_diagnostics["apply_errors"])
                )
        else:
            adjudicator_output, updated_state, updated_rules = _local_adjudicate(
                control=control,
                world_rules=world_rules,
                agent_state=agent_state,
                intent_batch=intent_batch,
            )
    except Exception as exc:
        diagnostics["status"] = "failed"
        if control.adjudication_backend == "flex":
            diagnostics["flex_status"] = "failed"
            diagnostics["flex_error"] = str(exc)
        else:
            diagnostics["local_error"] = str(exc)
        failure_payload = {
            "status": "failed",
            "stage": "adjudication",
            "backend": backend,
            "error": str(exc),
            "diagnostics": diagnostics,
        }
        dump_json(run_dir / "failure.json", failure_payload)
        failure_manifest = AdjudicatorManifestSpec(
            run_id=run_id,
            timestep_index=intent_batch.timestep_index,
            backend=backend,
            world_mode=world_rules.world_mode,
            files={
                "config": str(config_path),
                "rendered_system_prompt": str(rendered_prompt_path),
                "failure": str(run_dir / "failure.json"),
            },
            diagnostics={
                **diagnostics,
                "action_count": len(intent_batch.intents),
                "rule_appendix_count": 0,
            },
        )
        dump_json(run_dir / "final_manifest.json", failure_manifest.model_dump())
        raise

    output_path = run_dir / "adjudicator_output.json"
    updated_agent_state_path = run_dir / "updated_agent_profiles.json"
    updated_world_rules_path = run_dir / "updated_world_rules.json"
    dump_json(output_path, adjudicator_output)
    dump_json(updated_agent_state_path, updated_state.model_dump())
    dump_json(updated_world_rules_path, updated_rules.model_dump())

    manifest = AdjudicatorManifestSpec(
        run_id=run_id,
        timestep_index=intent_batch.timestep_index,
        backend=backend,
        world_mode=updated_rules.world_mode,
        files={
            "config": str(config_path),
            "rendered_system_prompt": str(rendered_prompt_path),
            "adjudicator_output": str(output_path),
            "updated_agent_profiles": str(updated_agent_state_path),
            "updated_world_rules": str(updated_world_rules_path),
        },
        diagnostics={
            **diagnostics,
            "action_count": len(intent_batch.intents),
            "rule_appendix_count": len(adjudicator_output.get("Rule_Appendices", [])),
        },
    )
    dump_json(run_dir / "final_manifest.json", manifest.model_dump())
    print(f"[DONE] run_dir={run_dir}")
