from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_ORCHESTRATION = {
    "version": "agora_c_1",
    "mode": "json_declared_runtime",
    "components": [
        {"component_id": "phase_trace", "kind": "phase_trace"},
    ],
    "policies": {
        "activation_policy": {"policy_id": "human_visible_decay_activation"},
        "target_selection_policy": {"policy_id": "human_priority_target_selection"},
        "route_request_policy": {"policy_id": "vertex_json_route_request"},
        "route_quota_policy": {"policy_id": "quota_fallback"},
        "intent_builder_policy": {"policy_id": "legacy_intent_builder"},
        "adjudication_policy": {"policy_id": "local_universal_adjudicator"},
        "finalization_policy": {"policy_id": "legacy_manifest_writer"},
    },
    "phases": [
        {
            "phase_id": "bootstrap",
            "steps": [
                {"operation": "initialize_runtime"},
                {"operation": "materialize_or_resume_state"},
                {"operation": "initialize_round_accumulators"},
                {"operation": "write_compiled_runtime_plan"},
            ],
        },
        {
            "phase_id": "round_loop",
            "for_each": "round_indices",
            "item_as": "round_index",
            "steps": [
                {"operation": "prepare_round"},
                {"operation": "sync_human_interactor"},
                {"operation": "run_extra_world_functions"},
                {"operation": "activate_agents"},
                {
                    "phase_id": "actor_loop",
                    "for_each": "activated_agents",
                    "item_as": "actor",
                    "steps": [
                        {"operation": "select_target"},
                        {"operation": "prepare_actor_request"},
                        {"operation": "request_route", "when": {"store_key": "current_actor_skipped", "equals": False}},
                        {"operation": "apply_route_fallbacks", "when": {"store_key": "current_actor_skipped", "equals": False}},
                        {"operation": "build_actor_outputs", "when": {"store_key": "current_actor_skipped", "equals": False}},
                        {"operation": "record_actor_outputs", "when": {"store_key": "current_actor_skipped", "equals": False}},
                    ],
                },
                {"operation": "adjudicate_round"},
                {"operation": "record_round_outputs"},
            ],
        },
        {
            "phase_id": "finalize",
            "steps": [
                {"operation": "write_final_outputs"},
                {"operation": "build_optional_report"},
                {"operation": "write_runtime_snapshot"},
            ],
        },
    ],
}


def compile_orchestration_config(config: dict[str, Any]) -> dict[str, Any]:
    explicit = config.get("orchestration")
    if isinstance(explicit, dict):
        compiled = deepcopy(DEFAULT_ORCHESTRATION)
        compiled.update({key: deepcopy(value) for key, value in explicit.items() if key not in {"components", "policies", "phases"}})
        if isinstance(explicit.get("components"), list):
            compiled["components"] = deepcopy(explicit["components"])
        if isinstance(explicit.get("policies"), dict):
            compiled["policies"] = deepcopy(explicit["policies"])
        if isinstance(explicit.get("phases"), list):
            compiled["phases"] = deepcopy(explicit["phases"])
        return compiled
    return deepcopy(DEFAULT_ORCHESTRATION)
