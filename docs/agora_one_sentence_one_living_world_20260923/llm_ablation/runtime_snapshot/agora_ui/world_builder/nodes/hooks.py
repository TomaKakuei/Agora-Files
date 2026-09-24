from __future__ import annotations

import json
from typing import Any

from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.world_builder.generation import _execute_json_prompt


def _reference_schema(values: list[str]) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string"}
    if values:
        schema["enum"] = values
    return schema


def _hooks_schema(
    room_names: list[str] | None = None,
    role_names: list[str] | None = None,
) -> dict[str, Any]:
    room_names = list(dict.fromkeys(room_names or []))
    role_names = list(dict.fromkeys(role_names or []))
    return {
        "type": "object",
        "required": ["social_rules", "custom_actions", "open_action_examples", "player_entry_points", "conflict_hooks", "gameplay_loops"],
        "properties": {
            "social_rules": {"type": "array", "items": {"type": "string"}},
            "custom_actions": {"type": "array", "items": {"type": "string"}},
            "open_action_examples": {
                "type": "array",
                "minItems": 4,
                "items": {
                    "type": "object",
                    "required": ["action_name", "initiating_role", "target_role", "situation", "proposed_effects", "coordinator_checks"],
                    "properties": {
                        "action_name": {"type": "string"},
                        "initiating_role": _reference_schema(role_names),
                        "target_role": _reference_schema(role_names),
                        "situation": {"type": "string"},
                        "proposed_effects": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "enum": ["speech", "transfer", "create_item", "status"]},
                        },
                        "coordinator_checks": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                    },
                },
            },
            "player_entry_points": {"type": "array", "items": {"type": "string"}},
            "conflict_hooks": {"type": "array", "items": {"type": "string"}},
            "gameplay_loops": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["label", "summary", "roles", "rooms", "pressure"],
                    "properties": {
                        "label": {"type": "string"},
                        "summary": {"type": "string"},
                        "roles": {
                            "type": "array",
                            "minItems": 1,
                            "items": _reference_schema(role_names),
                        },
                        "rooms": {
                            "type": "array",
                            "minItems": 1,
                            "items": _reference_schema(room_names),
                        },
                        "pressure": {"type": "string"},
                    },
                },
            },
        },
    }

def generate_hooks_spec(
    provider: VertexJsonClient,
    planner_spec: dict[str, Any],
    roles: list[dict[str, Any]],
    rooms: list[dict[str, Any]] | None = None,
    main_characters: list[dict[str, Any]] | None = None,
    repair_note: str = "",
) -> dict[str, Any]:
    room_names = [
        str(room.get("name", "")).strip()
        for room in (rooms or [])
        if str(room.get("name", "")).strip()
    ]
    role_names = [
        str(role.get("role_name", "")).strip()
        for role in [*(roles or []), *(main_characters or [])]
        if str(role.get("role_name", "")).strip()
    ]
    dynamics_json = json.dumps(planner_spec.get("world_dynamics", {}), ensure_ascii=False)

    prompt = f"""
    You are the narrative designer for the world: {planner_spec.get('world_name')}
    Conflict Tone: {planner_spec.get('conflict_tone')}
    Exact Room Names: {', '.join(room_names)}
    Exact Role Names: {', '.join(role_names)}
    World Dynamics JSON: {dynamics_json}
    
    Generate the social rules, custom actions, entry points, conflict hooks, and gameplay loops.
    CRITICAL CONSTRAINT: You MUST provide at least 2 conflict hooks, 6 custom actions, 4 open-action examples, and 3 gameplay loops.
    Every gameplay loop MUST name at least one room and one role from the exact lists above.
    Copy those names exactly. Do not invent a location, occupation, faction, or placeholder here.
    Each loop must change a named state variable or activate a causal link from World Dynamics.
    Custom actions must be world-specific verbs, not generic Chat, Inspect, Trade, Move, or Coordinate labels.
    Open-action examples demonstrate actions that were not pre-authored: unequal exchanges, targeted speech,
    bounded object creation, or a new social status. Give the World Coordinator concrete legality,
    ownership, proximity, consent, and bounded-creation checks; do not pre-approve the action.
    """
    
    if repair_note:
        prompt += f"\n\nRepair Note:\n{repair_note}"
        
    spec = _execute_json_prompt(
        provider=provider,
        system_instruction="You are the narrative designer for Agora. Generate conflict hooks and gameplay loops.",
        prompt=prompt,
        response_schema=_hooks_schema(room_names, role_names),
        temperature=0.4,
        max_output_tokens=4096,
        thinking_level="low",
    )
    
    # Validation
    if len(spec.get("conflict_hooks", [])) < 2:
        raise ValueError("Hooks node failed: generated less than 2 conflict hooks.")
    if len(spec.get("custom_actions", [])) < 6:
        raise ValueError("Hooks node failed: generated less than 6 custom actions.")
    if len(spec.get("open_action_examples", [])) < 4:
        raise ValueError("Hooks node failed: generated less than 4 open-action examples.")
    if len(spec.get("gameplay_loops", [])) < 3:
        raise ValueError("Hooks node failed: generated less than 3 gameplay loops.")
    if len([item for item in spec.get("social_rules", []) if str(item).strip()]) < 1:
        raise ValueError("Hooks node failed: generated no social rules.")
    if len([item for item in spec.get("player_entry_points", []) if str(item).strip()]) < 1:
        raise ValueError("Hooks node failed: generated no player entry points.")

    room_name_set = set(room_names)
    role_name_set = set(role_names)
    for index, loop in enumerate(spec.get("gameplay_loops", []), start=1):
        loop_rooms = [str(value).strip() for value in loop.get("rooms", []) if str(value).strip()]
        loop_roles = [str(value).strip() for value in loop.get("roles", []) if str(value).strip()]
        invalid_rooms = sorted(set(loop_rooms) - room_name_set)
        invalid_roles = sorted(set(loop_roles) - role_name_set)
        if not loop_rooms or invalid_rooms:
            raise ValueError(
                f"Hooks node loop {index} has unresolved room references: "
                f"{invalid_rooms or ['<missing>']}"
            )
        if not loop_roles or invalid_roles:
            raise ValueError(
                f"Hooks node loop {index} has unresolved role references: "
                f"{invalid_roles or ['<missing>']}"
            )
    for index, example in enumerate(spec.get("open_action_examples", []), start=1):
        invalid_roles = {
            str(example.get(field, "")).strip()
            for field in ("initiating_role", "target_role")
        } - role_name_set
        if invalid_roles:
            raise ValueError(
                f"Hooks node open-action example {index} has unresolved roles: {sorted(invalid_roles)}"
            )
        
    return spec
