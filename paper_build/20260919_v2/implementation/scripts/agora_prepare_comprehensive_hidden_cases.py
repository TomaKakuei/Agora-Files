#!/usr/bin/env python3
"""Materialize representative hidden worlds and probe open-action execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora_ui.adjudicator_schemas import (  # noqa: E402
    ActionIntentSpec,
    AdjudicatorControlSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    WorldRulesSpec,
)
from agora_ui.run_interaction_simulation.core import materialize_scenario  # noqa: E402
from agora_ui.universal_adjudicator.handlers_custom import _handle_custom  # noqa: E402
from agora_ui.world_coordinator import evaluate_open_action  # noqa: E402


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


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _agent(agent_id: str, items: list[tuple[str, int]]) -> AgentRuntimeProfileSpec:
    return AgentRuntimeProfileSpec.model_validate(
        {
            "agent_id": agent_id,
            "display_name": agent_id,
            "coordinates": {"x": 1, "y": 1, "z": 0},
            "room_id": "probe_room",
            "inventory": [{"item_id": item_id, "quantity": quantity} for item_id, quantity in items],
        }
    )


def _interaction_probes(config: dict[str, Any], scenario_dir: Path) -> dict[str, Any]:
    actor = _agent("probe_actor", [("gold", 10), ("paper", 1)])
    target = _agent("probe_target", [("relic", 1)])
    state = AgentStateBundleSpec(agents=[actor, target])
    transfer = {
        "action_name": "Deliberately Unequal Relic Deal",
        "action_text": "Offer ten gold for one chipped relic.",
        "target_agent_id": "probe_target",
        "target_response": "accept",
        "effects": [
            {"kind": "transfer", "source_agent_id": "probe_actor", "target_agent_id": "probe_target", "item_id": "gold", "quantity": 10},
            {"kind": "transfer", "source_agent_id": "probe_target", "target_agent_id": "probe_actor", "item_id": "relic", "quantity": 1},
        ],
    }
    creation = {
        "action_name": "Fold Promise Token",
        "action_text": "Fold owned paper into one bounded promise token.",
        "target_agent_id": "probe_target",
        "target_response": "not_required",
        "effects": [
            {
                "kind": "create_item",
                "item_id": "promise_token",
                "item_name": "Promise Token",
                "item_description": "A paper token carrying one household promise.",
                "input_item_ids": ["paper"],
            }
        ],
    }
    approved_trade = evaluate_open_action(transfer, actor=actor, target=target, state=state, config=config)
    approved_creation = evaluate_open_action(creation, actor=actor, target=target, state=state, config=config)
    without_consent = evaluate_open_action(
        {**transfer, "target_response": "unknown"}, actor=actor, target=target, state=state, config=config
    )
    speech_only_config = json.loads(json.dumps(config))
    speech_only_config.setdefault("world_rules", {}).setdefault("custom_action_rules", {})[
        "open_proposal_effects"
    ] = ["speech"]
    disabled_creation = evaluate_open_action(
        creation, actor=actor, target=target, state=state, config=speech_only_config
    )

    intent = ActionIntentSpec(
        intent_id="probe_transfer",
        agent_id="probe_actor",
        target_agent_id="probe_target",
        call="Custom",
        action=transfer["action_name"],
        metadata={
            "open_action_proposal": transfer,
            "coordinator_decision": approved_trade.model_dump(),
        },
    )
    mutations = {
        "action_results": [],
        "profile_updates": [],
        "relationship_updates": [],
        "relationship_tensor_updates": [],
        "inventory_updates": [],
    }
    _handle_custom(
        control=AdjudicatorControlSpec(world_description="hidden probe", simulation_objective="probe"),
        world_rules=WorldRulesSpec(world_mode="Fixed"),
        state=state,
        agents={"probe_actor": actor, "probe_target": target},
        start_positions={
            "probe_actor": actor.coordinates.model_copy(),
            "probe_target": target.coordinates.model_copy(),
        },
        moved_agent_ids=set(),
        intent=intent,
        broadcasts=[],
        mutations=mutations,
        rule_appendices=[],
    )
    custom_rules = config.get("world_rules", {}).get("custom_action_rules", {})
    routing = config.get("actions", {}).get("routing_policy", {})
    materialized_rules = _read(scenario_dir / "world_rules.json").get("custom_action_rules", {})
    agent_files = list((scenario_dir / "Agents").glob("*.json"))
    checks = {
        "generated_contract_exposes_route": bool(
            custom_rules.get("open_proposals_enabled")
            and routing.get("open_proposal_route_id") == "__propose__"
        ),
        "materialized_contract_preserves_route": bool(
            materialized_rules.get("open_proposals_enabled")
            and set(materialized_rules.get("open_proposal_effects", []))
            >= {"speech", "transfer", "create_item", "status"}
            and len(agent_files) == 12
        ),
        "unequal_consensual_trade_approved": approved_trade.status == "approved",
        "bounded_creation_approved": approved_creation.status == "approved",
        "missing_consent_rejected": without_consent.status == "rejected",
        "disabled_effect_rejected": disabled_creation.status == "rejected",
        "approved_trade_commits_atomically": bool(
            mutations["action_results"]
            and mutations["action_results"][0].get("status") == "success"
            and any(item.item_id == "relic" for item in actor.inventory)
            and any(item.item_id == "gold" and item.quantity == 10 for item in target.inventory)
        ),
    }
    return {
        "score": round(100.0 * sum(checks.values()) / len(checks), 2),
        "checks": checks,
        "decisions": {
            "unequal_trade": approved_trade.model_dump(),
            "bounded_creation": approved_creation.model_dump(),
            "without_consent": without_consent.model_dump(),
            "disabled_creation": disabled_creation.model_dump(),
        },
        "materialized_agent_count": len(agent_files),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--prompt-id", default="lwb_hidden_v2_01")
    args = parser.parse_args()

    rows = []
    for model, slug in MODELS.items():
        run_dir = args.run_root / slug / args.prompt_id
        result_path = next(run_dir.glob("*_decomposed_result.json"), None)
        if result_path is None:
            rows.append(
                {
                    "model": model,
                    "status": "generation_result_missing",
                }
            )
            continue
        result = _read(result_path)
        if result.get("complete_success") is not True:
            rows.append(
                {
                    "model": model,
                    "status": "generation_failed",
                    "generation_result_path": str(result_path.resolve()),
                    "generation_error": str(result.get("error", "")),
                }
            )
            continue
        config_path = next(run_dir.glob("*_decomposed_world_config.json"), None)
        spec_path = next(run_dir.glob("*_decomposed_builder_spec.json"), None)
        if config_path is None or spec_path is None:
            rows.append(
                {
                    "model": model,
                    "status": "compiled_artifact_missing",
                    "generation_result_path": str(result_path.resolve()),
                }
            )
            continue
        config = _read(config_path)
        case_root = args.output_root / slug
        scenario_dir = case_root / "scenario"
        materialize_scenario(config, scenario_dir)
        interaction = _interaction_probes(config, scenario_dir)
        interaction_path = case_root / "interaction_probes.json"
        _write(interaction_path, interaction)
        rows.append(
            {
                "model": model,
                "status": "ready",
                "config_path": str(config_path.resolve()),
                "builder_spec_path": str(spec_path.resolve()),
                "scenario_dir": str(scenario_dir.resolve()),
                "interaction_probe_path": str(interaction_path.resolve()),
                "interaction_score": interaction["score"],
                "asset_revision": f"lwbv2_{slug}",
            }
        )
    payload = {"prompt_id": args.prompt_id, "models": rows}
    _write(args.output_root / "case_manifest.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
