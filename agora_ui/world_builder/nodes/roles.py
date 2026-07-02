from typing import Any
import json
from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.world_builder.generation import _execute_json_prompt

def _main_character_batch_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["characters"],
        "properties": {
            "characters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "display_name", 
                        "role_name", 
                        "activity", 
                        "arc_goal",
                        "inventory",
                        "property_templates",
                        "knowledge_templates"
                    ],
                    "properties": {
                        "display_name": {"type": "string"},
                        "role_name": {"type": "string"},
                        "activity": {"type": "string"},
                        "home_base": {"type": "string"},
                        "arc_goal": {"type": "string"},
                        "inventory": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["name", "description", "quantity"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "quantity": {"type": "integer"}
                                }
                            }
                        },
                        "property_templates": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["asset_name", "asset_type", "description", "story_use"],
                                "properties": {
                                    "asset_name": {"type": "string"},
                                    "asset_type": {"type": "string"},
                                    "description": {"type": "string"},
                                    "story_use": {"type": "string"}
                                }
                            }
                        },
                        "knowledge_templates": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["knowledge_id", "topic", "summary", "confidence"],
                                "properties": {
                                    "knowledge_id": {"type": "string"},
                                    "topic": {"type": "string"},
                                    "summary": {"type": "string"},
                                    "confidence": {"type": "integer"}
                                }
                            }
                        }
                    },
                },
            },
        },
    }

def generate_roles_spec(
    provider: VertexJsonClient,
    planner_spec: dict[str, Any],
    rooms: list[dict[str, Any]],
    items: list[dict[str, Any]],
    agent_count_target: int,
    min_merchant_items: int,
    repair_note: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    item_ids = [item["item_id"] for item in items]
    room_names = [room["name"] for room in rooms]
    
    # Force the total agents to be 25 as per boutique logic constraints
    target_count = 25
    batch_size = 1
    iterations = target_count // batch_size
    
    all_main_chars = []
    
    for i in range(iterations):
        print(f"      -> Generating characters batch {i+1}/{iterations}...")
        
        context_str = ""
        if all_main_chars:
            summaries = [f"- {c['display_name']} ({c['role_name']}): {c['activity']}" for c in all_main_chars]
            context_str = "PREVIOUSLY GENERATED CHARACTERS IN THIS WORLD:\n" + "\n".join(summaries) + "\n\nCRITICAL: Ensure new characters interlock with existing ones (rivalries, suppliers, friends) and don't duplicate niches!"
            
        prompt = f"""
        You are the casting director for the world: {planner_spec.get('world_name')}
        Available Rooms: {', '.join(room_names)}
        Available Item IDs: {', '.join(item_ids[:50])} ... (and more)
        
        {context_str}
        
        CRITICAL CONSTRAINT: 
        - We are using BOUTIQUE SIMULATION LOGIC. Do not output generic role groups. 
        - Generate exactly {batch_size} highly detailed "Main Characters". 
        - Each character MUST INDEPENDENTLY GENERATE their own unique `inventory` items. Invent culturally authentic, world-specific items (provide name, description, and quantity). 
        - Any character representing merchants/traders MUST have AT LEAST {min_merchant_items} valid items in `inventory`.
        - Each character MUST explicitly populate both 'property_templates' and 'knowledge_templates' with culturally authentic, world-specific details. (CRITICAL: Limit to exactly 2 templates each to prevent output truncation!)
        """
        
        if repair_note and i == 0:
            prompt += f"\n\nRepair Note:\n{repair_note}"
            
        spec = _execute_json_prompt(
            provider=provider,
            system_instruction="You are the casting director for Agora. Output unique Boutique Main Characters. Every character is playable.",
            prompt=prompt,
            response_schema=_main_character_batch_schema(),
            temperature=0.4,
            max_output_tokens=8192,
            thinking_level="high",
            stage="main_character_generation",
        )
        
        batch = spec.get("characters", [])
        if not batch:
            raise ValueError(f"Roles node failed at batch {i+1}: generated 0 characters.")
            
        # Validation: Merchant items
        for char in batch:
            role_name = char.get("role_name", "").lower()
            if "merchant" in role_name or "stall" in role_name or "shop" in role_name or "vendor" in role_name:
                if len(char.get("inventory", [])) < min_merchant_items:
                    for fallback_id in item_ids[:min_merchant_items]:
                        char.setdefault("inventory", []).append({
                            "name": fallback_id,
                            "description": f"A {fallback_id} inside the world.",
                            "quantity": 1
                        })
        
        all_main_chars.extend(batch)
    
    # We return 0 role_groups and 25 main_characters
    return [], all_main_chars
