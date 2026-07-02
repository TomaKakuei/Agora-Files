from typing import Any
from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.world_builder.generation import _execute_json_prompt

def _rooms_schema(min_rooms: int, is_panjiayuan: bool) -> dict[str, Any]:
    schema = {
        "type": "object",
        "required": ["wall_color_theme", "outdoor_terrain", "rooms"],
        "properties": {
            "wall_color_theme": {
                "type": "string",
                "description": "The global color/material theme for the thin connective walls between rooms (e.g., 'white_plaster', 'glass', 'dark_brick')."
            },
            "outdoor_terrain": {
                "type": "string",
                "enum": ["dirt", "concrete"],
                "description": "The global outdoor terrain style outside of rooms."
            },
            "rooms": {
                "type": "array",
                "minItems": min_rooms if is_panjiayuan else None,
                "maxItems": min_rooms if is_panjiayuan else None,
                "items": {
                    "type": "object",
                    "required": ["name", "biome", "purpose", "decor_tags", "archetype", "ambient_palette", "width_tiles", "height_tiles", "flux_floor_prompt", "room_scene_prompt"],
                    "properties": {
                        "name": {"type": "string"},
                        "biome": {"type": "string"},
                        "purpose": {"type": "string"},
                        "decor_tags": {"type": "array", "items": {"type": "string"}},
                        "activity_tags": {"type": "array", "items": {"type": "string"}},
                        "flux_floor_prompt": {
                            "type": "string",
                            "description": "A precise description for FLUX2 to generate a pixel-art floor texture for this specific room. E.g., 'crunchy 16-bit pixel art of cracked concrete flooring with subtle moss' or 'seamless modern shiny glass mall floor pixel art'."
                        },
                        "room_scene_prompt": {
                            "type": "string",
                            "description": "A room-scale FLUX prompt for a full top-down/isometric room plate. It should mention the room name, function, interior materials, and a clean pixel-art overview suitable for compressing back onto the room footprint as a 32x32-per-tile map texture."
                        },
                        "ambient_palette": {
                            "type": "string",
                            "enum": ["warm_lantern", "soft_mint", "focused_blue", "clear_day", "dusty_brown", "ember_orange", "low_lantern"]
                        },
                        "archetype": {
                            "type": "string",
                            "enum": ["market_exchange", "checkpoint", "logistics_yard", "lookout", "workshop", "archive_ritual", "rest_social", "training", "council", "commons"]
                        },
                        "width_tiles": {"type": "integer", "minimum": 3},
                        "height_tiles": {"type": "integer", "minimum": 3},
                    },
                },
            }
        },
    }
    return schema

def generate_rooms_spec(
    provider: VertexJsonClient,
    planner_spec: dict[str, Any],
    min_rooms: int,
    repair_note: str = "",
) -> dict[str, Any]:
    # Dynamic constraint based on modern vs traditional theme
    world_desc = " ".join([
        str(planner_spec.get('world_name', '')),
        str(planner_spec.get('premise', '')),
        str(planner_spec.get('economy_focus', '')),
        str(planner_spec.get('genre', ''))
    ]).lower()
    
    is_panjiayuan = "panjiayuan" in world_desc or "潘家园" in world_desc
    is_modern = any(k in world_desc for k in ["glass", "optical", "modern", "wholesale", "retail", "glasses", "mall"])
    
    style_instruction = ""
    if is_panjiayuan:
        style_instruction = """
    CRITICAL THEME CONSTRAINT:
    - This is Panjiayuan (潘家园旧货市场), the famous Beijing antique market.
    - IMPORTANT: FLUX does NOT automatically know what Panjiayuan is! Your `flux_floor_prompt`s and `room_scene_prompt`s MUST explicitly describe the physical textures and room identity to FLUX.
    - Examples for `flux_floor_prompt`: "16-bit pixel art, cracked old gray concrete pavement, dusty, scattered leaves, antique market outdoor ground", or "16-bit pixel art floor, worn red carpet texture over stone, indoor antique stall", or "crunchy pixel art, dirty cobblestone street with small debris".
    - Example for `room_scene_prompt`: "Top-down pixel art room plate for Panjiayuan jade stall, worn red carpet over stone, glass display cases, packed antique tables, warm lantern highlights, no text, readable room overview."
    - `wall_color_theme` should be weathered and traditional (e.g., 'dusty_brick', 'weathered_stone', 'red_wood').
    """
    elif is_modern:
        style_instruction = """
    CRITICAL THEME CONSTRAINT:
    - This is a MODERN commercial wholesale optical market / glasses mall (Danyang Glasses City).
    - Ensure your `wall_color_theme`, `flux_floor_prompt`s, and `room_scene_prompt`s reflect a modern, clean, glassy, or commercial aesthetic.
    """
    else:
        style_instruction = """
    CRITICAL THEME CONSTRAINT:
    - Ensure your `wall_color_theme`, `flux_floor_prompt`s, and `room_scene_prompt`s reflect the specific setting (e.g. traditional, antique).
    """

    prompt = f"""
    You are the Map Agent and Room Architect for the world: {planner_spec.get('world_name')}
    Premise: {planner_spec.get('premise')}
    Economy Focus: {planner_spec.get('economy_focus')}
    
    YOUR MAIN RESPONSIBILITIES:
    1. Spatial Zoning: Divide the world logically into distinct functional rooms.
    2. Room Dimensions: Carefully assign room dimensions:
       - width_tiles and height_tiles represent the interior floor space of the room.
       - A standard stall might be 4x4, but a large hall could be 20x15 or larger.
    3. Floor Generation Prompts: Write a detailed `flux_floor_prompt` for each room. This prompt will be sent to FLUX2 to generate the floor texture. Keep it focused on crunchy 2D pixel art textures (from a top-down/isometric perspective).
    4. Room Scene Prompts: Write a `room_scene_prompt` for each room. This is the main FLUX prompt for a full-room top-down/isometric plate that captures the room's name, function, props, atmosphere, and materials, while remaining readable after being compressed back to the room footprint on a 32x32 tile grid.
    5. Wall Theme: Choose a single `wall_color_theme` for the thin walls that connect all these rooms.
    6. Outdoor Terrain: Choose an `outdoor_terrain` ("dirt" or "concrete") for the areas outside of the rooms.
    
    CRITICAL CONSTRAINT: You MUST generate {"EXACTLY" if is_panjiayuan else "AT LEAST"} {min_rooms} distinct rooms. {"Do NOT generate any more or any less than this exact number." if is_panjiayuan else ""}
    Do NOT group rooms together into broad zones. Each vendor stall, each specific office, and each distinct area MUST be its own room.
    
    {style_instruction}
    """
    
    if repair_note:
        prompt += f"\n\nRepair Note:\n{repair_note}"
        
    spec = _execute_json_prompt(
        provider=provider,
        system_instruction="You are the room architect for Agora. Generate distinct, specific locations.",
        prompt=prompt,
        response_schema=_rooms_schema(min_rooms, is_panjiayuan),
        temperature=0.3,
        max_output_tokens=8192,
        thinking_level="high",
    )
    
    rooms = spec.get("rooms", [])
    if not rooms or (is_panjiayuan and len(rooms) != min_rooms) or (not is_panjiayuan and len(rooms) < min_rooms):
        raise ValueError(f"Rooms node failed constraint: generated {len(rooms)} rooms, needed {'exactly' if is_panjiayuan else 'at least'} {min_rooms}.")
    
    # Post-process to rigorously clamp dimensions
    for r in rooms:
        r["width_tiles"] = min(60, max(3, int(r.get("width_tiles", 5))))
        r["height_tiles"] = min(50, max(3, int(r.get("height_tiles", 5))))
        
    return spec
