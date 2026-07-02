from __future__ import annotations
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
                    "preset_id",
                    "profile_id",
                    "locale",
                    "tone",
                    "visual_direction",
                    "currency_code",
                    "currency_symbol",
                    "currency_minor_unit",
                    "domain_label",
                    "kit_refs",
                ],
                "properties": {
                    "seed_version": {"type": "string", "enum": ["world_seed_v2"]},
                    "preset_id": {"type": "string", "enum": ["grounded_antique_market", "coastal_trade_city", "civic_social_world", "fantasy_guild_world"]},
                    "profile_id": {"type": "string", "enum": ["grounded_antique_market", "coastal_trade_city", "civic_social_world", "fantasy_guild_world"]},
                    "locale": {"type": "string"},
                    "tone": {"type": "string"},
                    "visual_direction": {"type": "string"},
                    "currency_code": {"type": "string"},
                    "currency_symbol": {"type": "string"},
                    "currency_minor_unit": {"type": "string"},
                    "currency_name": {"type": "string"},
                    "domain_label": {"type": "string"},
                    "kit_refs": {
                        "type": "object",
                        "required": ["pixel_component_kit_id", "frontend_affordance_id", "asset_prompt_kit_id"],
                        "properties": {
                            "pixel_component_kit_id": {"type": "string"},
                            "frontend_affordance_id": {"type": "string"},
                            "asset_prompt_kit_id": {"type": "string"},
                        },
                    },
                    "policy_refs": {
                        "type": "object",
                        "required": ["economy_policy_id", "item_collection_id", "inventory_layer_policy_id", "role_item_policy_id", "property_policy_id", "knowledge_policy_id"],
                        "properties": {
                            "economy_policy_id": {"type": "string"},
                            "item_collection_id": {"type": "string"},
                            "inventory_layer_policy_id": {"type": "string"},
                            "role_item_policy_id": {"type": "string"},
                            "property_policy_id": {"type": "string"},
                            "knowledge_policy_id": {"type": "string"},
                            "inventory_layers": {"type": "array", "items": {"type": "string"}},
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
    prompt = f"""
    You are the master world planner.
    Define the core overarching theme, economy, and style based on the user request.
    
    User Request Details:
    - World Name: {request.get('world_name', '')}
    - Genre / Theme: {request.get('genre', '')}
    - Gameplay Focus: {request.get('focus', '')}
    - Natural Language Brief: {request.get('brief', request.get('prompt', ''))}
    
    IMPORTANT: You MUST select the most appropriate preset_id and profile_id from the following options based on the world's setting:
    - grounded_antique_market (for antique markets, modern black markets, item appraisal)
    - coastal_trade_city (for harbor logistics, coastal villages, seafood markets, docks)
    - civic_social_world (for office spaces, bureaucratic organizations, sci-fi administration)
    - fantasy_guild_world (for medieval fantasy, adventurers guild, magic)
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
        max_output_tokens=2048,
        thinking_level="high",
    )
    
    if not spec:
        raise ValueError("Planner node returned empty spec.")
    return spec
