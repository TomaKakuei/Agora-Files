from __future__ import annotations
import os
from typing import Any
from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.world_builder.generation import _execute_json_prompt

def _planner_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "world_name",
            "world_id",
            "world_seed",
            "world_dynamics",
            "genre",
            "premise",
            "simulation_objective",
            "player_count_target",
            "economy_focus",
            "exploration_focus",
            "conflict_tone",
            "visual_style",
            "item_themes",
        ],
        "properties": {
            "world_name": {"type": "string"},
            "world_id": {"type": "string"},
            "world_seed": {
                "type": "object",
                "required": [
                    "seed_version",
                    "locale",
                    "tone",
                    "visual_direction",
                    "currency_code",
                    "currency_symbol",
                    "currency_minor_unit",
                    "domain_label",
                ],
                "properties": {
                    "seed_version": {"type": "string", "enum": ["world_seed_v3_open"]},
                    "locale": {"type": "string"},
                    "tone": {"type": "string"},
                    "visual_direction": {"type": "string"},
                    "currency_code": {"type": "string"},
                    "currency_symbol": {"type": "string"},
                    "currency_minor_unit": {"type": "string"},
                    "currency_name": {"type": "string"},
                    "domain_label": {"type": "string"},
                },
            },
            "world_dynamics": {
                "type": "object",
                "required": ["institutions", "state_variables", "causal_links", "stakeholder_groups"],
                "properties": {
                    "institutions": {
                        "type": "array",
                        "minItems": 3,
                        "items": {
                            "type": "object",
                            "required": ["institution_id", "name", "mandate", "decision_rule", "enforced_by", "visible_output"],
                            "properties": {
                                "institution_id": {"type": "string"},
                                "name": {"type": "string"},
                                "mandate": {"type": "string"},
                                "decision_rule": {"type": "string"},
                                "enforced_by": {"type": "string"},
                                "visible_output": {"type": "string"},
                            },
                        },
                    },
                    "state_variables": {
                        "type": "array",
                        "minItems": 4,
                        "items": {
                            "type": "object",
                            "required": ["state_id", "label", "initial_tension", "changed_by", "affects"],
                            "properties": {
                                "state_id": {"type": "string"},
                                "label": {"type": "string"},
                                "initial_tension": {"type": "string"},
                                "changed_by": {"type": "array", "items": {"type": "string"}},
                                "affects": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                    "causal_links": {
                        "type": "array",
                        "minItems": 4,
                        "items": {
                            "type": "object",
                            "required": ["source_state", "trigger", "target_state", "effect", "delay"],
                            "properties": {
                                "source_state": {"type": "string"},
                                "trigger": {"type": "string"},
                                "target_state": {"type": "string"},
                                "effect": {"type": "string"},
                                "delay": {"type": "string"},
                            },
                        },
                    },
                    "stakeholder_groups": {
                        "type": "array",
                        "minItems": 3,
                        "items": {
                            "type": "object",
                            "required": ["group_id", "name", "goal", "leverage", "dependency"],
                            "properties": {
                                "group_id": {"type": "string"},
                                "name": {"type": "string"},
                                "goal": {"type": "string"},
                                "leverage": {"type": "string"},
                                "dependency": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "genre": {"type": "string"},
            "premise": {"type": "string"},
            "simulation_objective": {"type": "string"},
            "player_count_target": {"type": "integer"},
            "economy_focus": {"type": "string"},
            "exploration_focus": {"type": "string"},
            "conflict_tone": {"type": "string"},
            "visual_style": {"type": "string"},
            "item_themes": {"type": "array", "items": {"type": "string"}},
        },
    }

def generate_planner_spec(
    provider: VertexJsonClient,
    request: dict[str, Any],
    prior_context: dict[str, Any] | None = None,
    feedback: str = "",
    repair_note: str = "",
) -> dict[str, Any]:
    try:
        planner_max_output_tokens = max(32768, int(os.environ.get("AGORA_PLANNER_MAX_OUTPUT_TOKENS", "32768")))
    except Exception:
        planner_max_output_tokens = 32768
    prompt = f"""
    You are the master world planner.
    Define the core overarching theme, economy, and style based on the user request.

    User Request Details:
    - World Name: {request.get('world_name', '')}
    - Genre / Theme: {request.get('genre', '')}
    - Gameplay Focus: {request.get('focus', '')}
    - Natural Language Brief: {request.get('brief', request.get('prompt', ''))}

    Do not choose a preset, profile, kit, policy registry, or implementation template.
    Author an open semantic world_seed using seed_version world_seed_v3_open.

    Build a world_dynamics causal graph, not a setting synopsis:
    - At least three institutions with different mandates, decision rules, enforcement, and visible outputs.
    - At least four state variables that can visibly change through play.
    - At least four causal links whose source_state and target_state exactly reference those state IDs.
    - At least three stakeholder groups with incompatible goals, distinct leverage, and concrete dependencies.
    - Every mechanism must be specific to this sentence. A human or AI agent must be able to intervene in it.
    - Include delayed or second-order consequences so one action can alter what becomes possible elsewhere.

    REFERENCE-INTEGRITY PROCEDURE:
    1. Author world_dynamics.state_variables first and freeze its exact state_id strings.
    2. For every causal link, copy source_state and target_state verbatim from that frozen state_id list.
    3. Never put an institution_id, stakeholder group_id, institution name, group name, or newly invented outcome in source_state or target_state. Put those concepts in trigger or effect instead.
    4. Before returning JSON, form the set S of state_variables[].state_id and verify for every link that source_state is in S and target_state is in S. Repair every link that fails this check.
    """

    if prior_context:
        prompt += f"\n\nPrior Context:\n{prior_context}"
    if feedback:
        prompt += f"\n\nFeedback:\n{feedback}"
    if repair_note:
        prompt += f"\n\nRepair Note:\n{repair_note}"

    spec = _execute_json_prompt(
        provider=provider,
        system_instruction="You are the world planner for Agora. Convert user intent into a clean base spec for a persistent multi-agent world.",
        prompt=prompt,
        response_schema=_planner_schema(),
        temperature=0.2,
        max_output_tokens=planner_max_output_tokens,
        thinking_level="medium",
    )

    if not spec:
        raise ValueError("Planner node returned empty spec.")
    dynamics = spec.get("world_dynamics", {})
    state_ids = {
        str(item.get("state_id", "")).strip()
        for item in dynamics.get("state_variables", [])
        if isinstance(item, dict) and str(item.get("state_id", "")).strip()
    }
    if len(state_ids) < 4:
        raise ValueError("Planner node returned fewer than four unique state variables.")
    for index, link in enumerate(dynamics.get("causal_links", []), start=1):
        if not isinstance(link, dict):
            raise ValueError(f"Planner causal link {index} is not an object.")
        unresolved = {
            str(link.get(field, "")).strip()
            for field in ("source_state", "target_state")
        } - state_ids
        if unresolved:
            raise ValueError(
                f"Planner causal link {index} references unknown state IDs: {sorted(unresolved)}"
            )
    return spec
