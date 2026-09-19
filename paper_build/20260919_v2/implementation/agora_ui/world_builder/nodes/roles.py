from typing import Any
import json
import os
from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.world_builder.generation import _execute_json_prompt

RELATIONSHIP_TYPES = {
    "alliance",
    "blackmail",
    "contract",
    "depend",
    "dispute",
    "favor",
    "mentor",
    "negotiate",
    "owe",
    "protect",
    "rival",
    "smuggle",
    "supplier",
    "trust",
}


def _main_character_batch_schema(expected_count: int) -> dict[str, Any]:
    # Gemini 2.5 rejects the Cartesian state space created by nested exact
    # array lengths, enums, and numeric ranges. Keep the wire schema typed and
    # enforce the same semantic constraints locally after generation.
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
                        "knowledge_templates",
                        "relationships",
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
                        },
                        "relationships": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["target_name", "relationship_type", "description"],
                                "properties": {
                                    "target_name": {"type": "string"},
                                    "relationship_type": {"type": "string"},
                                    "description": {"type": "string"}
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
    try:
        main_character_max_output_tokens = max(4096, int(os.environ.get("AGORA_MAIN_CHARACTER_MAX_OUTPUT_TOKENS", "8192")))
    except Exception:
        main_character_max_output_tokens = 8192
    try:
        main_character_thinking_budget = max(2046, int(os.environ.get("AGORA_MAIN_CHARACTER_THINKING_BUDGET", "2046")))
    except Exception:
        main_character_thinking_budget = 2046
    item_ids = [item["item_id"] for item in items]
    room_names = [room["name"] for room in rooms]

    target_count = max(8, min(40, int(agent_count_target or 12)))
    try:
        configured_batch_size = int(os.environ.get("AGORA_MAIN_CHARACTER_BATCH_SIZE", "4"))
    except Exception:
        configured_batch_size = 4
    batch_size = max(1, min(6, configured_batch_size))
    batch_sizes: list[int] = []
    remaining = target_count
    while remaining > 0:
        current = min(batch_size, remaining)
        batch_sizes.append(current)
        remaining -= current

    all_main_chars = []

    for i, current_batch_size in enumerate(batch_sizes):
        print(f"      -> Generating characters batch {i+1}/{len(batch_sizes)} ({current_batch_size} characters)...")

        context_str = ""
        if all_main_chars:
            summaries = [f"- {c['display_name']} ({c['role_name']}): {c['activity']}" for c in all_main_chars]
            context_str = "PREVIOUSLY GENERATED CHARACTERS IN THIS WORLD:\n" + "\n".join(summaries) + "\n\nCRITICAL: Ensure new characters interlock with existing ones (rivalries, suppliers, friends) and don't duplicate niches!"

        prompt = f"""
        You are the casting director for the world: {planner_spec.get('world_name')}
        Available Rooms: {', '.join(room_names)}
        Available Item IDs: {', '.join(item_ids[:50])} ... (and more)
        World Dynamics JSON: {json.dumps(planner_spec.get('world_dynamics', {}), ensure_ascii=False)}

        {context_str}

        CRITICAL CONSTRAINT:
        - We are using BOUTIQUE SIMULATION LOGIC. Do not output generic role groups.
        - Generate exactly {current_batch_size} highly detailed "Main Characters".
        - Each character MUST INDEPENDENTLY GENERATE their own unique `inventory` items. Invent culturally authentic, world-specific items (provide name, description, and quantity).
        - Every character MUST have AT LEAST 8 valid, world-specific inventory objects. Generic civic items are forbidden.
        - A merchant's sellable stock belongs in the shared item catalog and property templates, not in personal inventory. Do not inflate inventory based on words in role_name.
        - Each character MUST explicitly populate both 'property_templates' and 'knowledge_templates' with culturally authentic, world-specific details. (CRITICAL: Limit to exactly 2 templates each to prevent output truncation!)
        - Every home_base MUST exactly copy one Available Room name.
        - Every activity and arc_goal must say which institution, stakeholder dependency, or state variable the character can change.
        - Every character MUST have 2-4 relationships. target_name MUST exactly copy another character display_name from this batch or PREVIOUSLY GENERATED CHARACTERS; never target the character itself.
        - relationship_type MUST be exactly one of: {', '.join(sorted(RELATIONSHIP_TYPES))}.
        - Across the cast, create suppliers, rivals, debtors, allies, favors, and information dependencies using those controlled values. Do not duplicate social niches.
        - After the first batch, every new batch must include relationships to PREVIOUSLY GENERATED CHARACTERS so the community is one network rather than isolated batch clusters.
        """

        if repair_note and i == 0:
            prompt += f"\n\nRepair Note:\n{repair_note}"

        spec = _execute_json_prompt(
            provider=provider,
            system_instruction="You are the casting director for Agora. Output unique Boutique Main Characters. Every character is playable.",
            prompt=prompt,
            response_schema=_main_character_batch_schema(current_batch_size),
            temperature=0.4,
            max_output_tokens=main_character_max_output_tokens,
            thinking_level="low",
            thinking_budget=main_character_thinking_budget,
            stage="main_character_generation",
        )

        batch = spec.get("characters", [])
        if len(batch) != current_batch_size:
            raise ValueError(
                f"Roles node failed at batch {i+1}: generated {len(batch)} characters, "
                f"required exactly {current_batch_size}."
            )

        # Validation must fail hard. Do not silently patch missing inventory with generic items.
        available_character_names = {
            str(character.get("display_name", "")).strip()
            for character in [*all_main_chars, *batch]
            if str(character.get("display_name", "")).strip()
        }
        for char in batch:
            inventory = [
                item for item in char.get("inventory", [])
                if isinstance(item, dict)
                and str(item.get("name") or item.get("item_id") or "").strip()
                and str(item.get("description", "")).strip()
            ]
            required_items = 8
            if len(inventory) < required_items:
                raise ValueError(
                    f"Roles node failed at batch {i+1}: {char.get('display_name', 'character')} "
                    f"generated {len(inventory)} valid inventory items, required {required_items}."
                )
            if len([item for item in char.get("property_templates", []) if isinstance(item, dict)]) < 2:
                raise ValueError(f"Roles node failed at batch {i+1}: {char.get('display_name', 'character')} missing property_templates.")
            if len([item for item in char.get("knowledge_templates", []) if isinstance(item, dict)]) < 2:
                raise ValueError(f"Roles node failed at batch {i+1}: {char.get('display_name', 'character')} missing knowledge_templates.")
            relationships = [item for item in char.get("relationships", []) if isinstance(item, dict)]
            if not 2 <= len(relationships) <= 4:
                raise ValueError(
                    f"Roles node failed at batch {i+1}: {char.get('display_name', 'character')} "
                    f"generated {len(relationships)} relationships, required 2-4."
                )
            invalid_relationship_types = sorted({
                str(item.get("relationship_type", "")).strip()
                for item in relationships
                if str(item.get("relationship_type", "")).strip() not in RELATIONSHIP_TYPES
            })
            if invalid_relationship_types:
                raise ValueError(
                    f"Roles node failed at batch {i+1}: {char.get('display_name', 'character')} "
                    f"used invalid relationship types {invalid_relationship_types}."
                )
            invalid_confidences = [
                item.get("confidence")
                for item in char.get("knowledge_templates", [])
                if isinstance(item, dict)
                and (
                    isinstance(item.get("confidence"), bool)
                    or not isinstance(item.get("confidence"), int)
                    or not 0 <= item.get("confidence") <= 100
                )
            ]
            if invalid_confidences:
                raise ValueError(
                    f"Roles node failed at batch {i+1}: {char.get('display_name', 'character')} "
                    f"used confidence values outside 0-100: {invalid_confidences}."
                )
            own_name = str(char.get("display_name", "")).strip()
            invalid_targets = [
                str(item.get("target_name", "")).strip()
                for item in relationships
                if str(item.get("target_name", "")).strip() not in available_character_names
                or str(item.get("target_name", "")).strip() == own_name
            ]
            if invalid_targets:
                raise ValueError(
                    f"Roles node failed at batch {i+1}: {own_name or 'character'} has invalid relationship targets {invalid_targets}."
                )

        all_main_chars.extend(batch)

    if len(all_main_chars) != target_count:
        raise ValueError(f"Roles node generated {len(all_main_chars)} characters, expected {target_count}.")

    # Boutique mode keeps every generated character directly playable.
    return [], all_main_chars
