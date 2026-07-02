from typing import Any
from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.world_builder.generation import _execute_json_prompt

def _hooks_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["social_rules", "custom_actions", "player_entry_points", "conflict_hooks", "gameplay_loops"],
        "properties": {
            "social_rules": {"type": "array", "items": {"type": "string"}},
            "custom_actions": {"type": "array", "items": {"type": "string"}},
            "player_entry_points": {"type": "array", "items": {"type": "string"}},
            "conflict_hooks": {"type": "array", "items": {"type": "string"}},
            "gameplay_loops": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["label", "summary"],
                    "properties": {
                        "label": {"type": "string"},
                        "summary": {"type": "string"},
                        "roles": {"type": "array", "items": {"type": "string"}},
                        "rooms": {"type": "array", "items": {"type": "string"}},
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
    repair_note: str = "",
) -> dict[str, Any]:
    role_names = [r["role_name"] for r in roles]
    
    prompt = f"""
    You are the narrative designer for the world: {planner_spec.get('world_name')}
    Conflict Tone: {planner_spec.get('conflict_tone')}
    Available Roles: {', '.join(role_names)}
    
    Generate the social rules, custom actions, entry points, conflict hooks, and gameplay loops.
    CRITICAL CONSTRAINT: You MUST provide at least 2 conflict hooks, 3 custom actions, and 2 gameplay loops.
    """
    
    if repair_note:
        prompt += f"\n\nRepair Note:\n{repair_note}"
        
    spec = _execute_json_prompt(
        provider=provider,
        system_instruction="You are the narrative designer for Agora. Generate conflict hooks and gameplay loops.",
        prompt=prompt,
        response_schema=_hooks_schema(),
        temperature=0.4,
        max_output_tokens=4096,
        thinking_level="high",
    )
    
    # Validation
    if len(spec.get("conflict_hooks", [])) < 2:
        raise ValueError("Hooks node failed: generated less than 2 conflict hooks.")
    if len(spec.get("custom_actions", [])) < 3:
        raise ValueError("Hooks node failed: generated less than 3 custom actions.")
    if len(spec.get("gameplay_loops", [])) < 2:
        raise ValueError("Hooks node failed: generated less than 2 gameplay loops.")
        
    return spec
