from typing import Any
from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.world_builder.generation import _execute_json_prompt

def _items_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["item_catalog"],
        "properties": {
            "item_catalog": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["item_id", "name", "price", "mass", "description", "image_prompt"],
                    "properties": {
                        "item_id": {"type": "string"},
                        "name": {"type": "string"},
                        "price": {"type": "integer"},
                        "mass": {"type": "number"},
                        "description": {"type": "string"},
                        "image_prompt": {"type": "string"},
                        "category": {"type": "string"},
                    },
                },
            },
        },
    }

def generate_items_spec(
    provider: VertexJsonClient,
    planner_spec: dict[str, Any],
    min_items_catalog: int,
    repair_note: str = "",
) -> list[dict[str, Any]]:
    prompt = f"""
    You are the item smith for the world: {planner_spec.get('world_name')}
    Theme: {planner_spec.get('genre')}
    Economy Focus: {planner_spec.get('economy_focus')}
    Visual Style: {planner_spec.get('visual_style')}
    Item Themes: {', '.join(planner_spec.get('item_themes', []))}
    
    CRITICAL CONSTRAINT: You MUST generate AT LEAST {min_items_catalog} unique items in the `item_catalog`.
    Populate it with culturally authentic, world-specific items matching the locale and tone.
    Each item MUST have a unique `item_id`, a friendly `name`, base `price` (integer), `mass` (float), `description`, an `image_prompt`, and an optional `category`.
    """
    
    if repair_note:
        prompt += f"\n\nRepair Note:\n{repair_note}"
        
    spec = _execute_json_prompt(
        provider=provider,
        system_instruction="You are the item smith for Agora. Create a rich, culturally specific item catalog.",
        prompt=prompt,
        response_schema=_items_schema(),
        temperature=0.4,
        max_output_tokens=8192,
        thinking_level="high",
    )
    
    items = spec.get("item_catalog", [])
    if not items or len(items) < min_items_catalog:
        raise ValueError(f"Items node failed constraint: generated {len(items)} items, needed at least {min_items_catalog}.")
    return items
