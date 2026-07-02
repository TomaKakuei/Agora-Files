from typing import Any
from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.world_builder.generation import _execute_json_prompt

def _materials_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["room_materials"],
        "properties": {
            "room_materials": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "room_name",
                        "floor_tile",
                        "wall_tile",
                        "ambient_palette",
                        "showcase_shelf",
                        "showcase_item_colors",
                        "reflection_glares"
                    ],
                    "properties": {
                        "room_name": {"type": "string"},
                        "floor_tile": {
                            "type": "string",
                            "enum": ["bamboo_planks", "red_brick", "jade_tile", "stone_checker", "yard_pavers", "library_planks", "wood_planks", "stone_slabs", "forge_slate", "clean_tile", "dorm_planks", "war_room_inlay"]
                        },
                        "wall_tile": {
                            "type": "string",
                            "enum": ["red_pillar_wall", "bamboo_wall", "courtyard_brick_wall", "quiet_lane_wall", "stall_canvas_wall", "wood_beam_wall", "storage_wall", "forge_wall", "healer_wall", "dorm_wall", "war_room_wall", "library_shelf_wall", "glass_case_wall", "tavern_wall", "yard_fence"]
                        },
                        "ambient_palette": {
                            "type": "string",
                            "enum": ["warm_lantern", "soft_mint", "focused_blue", "clear_day", "dusty_brown", "ember_orange", "low_lantern"]
                        },
                        "showcase_shelf": {
                            "type": "boolean",
                            "description": "Whether to draw a showcase shelf inside glass case walls. Enable for optical retail or showcase areas."
                        },
                        "showcase_item_colors": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Hex colors of tiny display items (e.g. spectacles/lenses) on the shelf."
                        },
                        "reflection_glares": {
                            "type": "boolean",
                            "description": "Whether to render glossy specular reflections on the floor tiles. Enable for clean, high-end, polished surfaces."
                        }
                    }
                }
            }
        }
    }

def generate_materials_spec(
    provider: VertexJsonClient,
    planner_spec: dict[str, Any],
    rooms: list[dict[str, Any]],
    repair_note: str = "",
) -> list[dict[str, Any]]:
    room_summaries = []
    for r in rooms:
        name = r.get("name", "Unknown Room")
        purpose = r.get("purpose", "")
        archetype = r.get("archetype", "")
        biome = r.get("biome", "")
        room_summaries.append(f"- '{name}' (Archetype: {archetype}, Biome: {biome}): {purpose}")

    room_list_str = "\n".join(room_summaries)

    world_desc = " ".join([
        str(planner_spec.get('world_name', '')),
        str(planner_spec.get('premise', '')),
        str(planner_spec.get('economy_focus', '')),
        str(planner_spec.get('genre', ''))
    ]).lower()
    
    is_modern = any(k in world_desc for k in ["glass", "optical", "modern", "wholesale", "retail", "glasses", "mall"])

    style_guidance = ""
    if is_modern:
        style_guidance = """
        This is a MODERN commercial wholesale optical market / glasses mall (Danyang Glasses City).
        - Floor Tiles: Prefer `clean_tile` or `stone_checker`. Enable `reflection_glares` (true) for high-end glossy showrooms.
        - Wall Tiles: Prefer `glass_case_wall` for showrooms/stalls. Enable `showcase_shelf` (true) and specify display colors like `["#ca6c3a", "#7fb8a3"]` (representing colored spectacles/lenses) for retail spots.
        - Ambient Palettes: Use `focused_blue` or `clear_day` for clean lab/retail lighting, and `warm_lantern` or `low_lantern` for cozy lounge/cafe areas.
        - DO NOT use traditional/historical options like `bamboo_planks`, `jade_tile`, `bamboo_wall`, or `red_pillar_wall` here.
        """
    else:
        style_guidance = """
        Select appropriate traditional materials:
        - For a traditional Chinese antique market (Panjiayuan style): Prefer `bamboo_planks` or `red_brick` for floors, and `bamboo_wall` or `red_pillar_wall` for walls.
        """

    prompt = f"""
    You are the Material Generator Agent for the world: {planner_spec.get('world_name')}
    Premise: {planner_spec.get('premise')}
    
    Your task is to design detailed visual materials, tile palettes, and showcase decorations for each room.
    Below are the rooms generated by the Map Agent:
    {room_list_str}
    
    STYLE GUIDELINES:
    {style_guidance}
    
    For every room in the list, generate a matching room_materials entry by room_name. Ensure that all generated properties fit the specific setting.
    """

    if repair_note:
        prompt += f"\n\nRepair Note:\n{repair_note}"

    spec = _execute_json_prompt(
        provider=provider,
        system_instruction="You are the Material Generator Agent for Agora. Design detailed textures, show cases, and polished material characteristics for rooms.",
        prompt=prompt,
        response_schema=_materials_schema(),
        temperature=0.3,
        max_output_tokens=8192,
        thinking_level="high",
    )

    return spec.get("room_materials", [])
