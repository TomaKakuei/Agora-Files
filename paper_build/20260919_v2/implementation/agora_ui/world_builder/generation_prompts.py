from __future__ import annotations
import json
import time
import traceback
from typing import Any
from agora_ui.vertex_json_client import VertexJsonClient
from .generation_schemas import *

def _render_builder_prompt(request: dict[str, Any], *, prior_context: dict[str, Any] | None = None, feedback: str = "", repair_note: str = "") -> str:
    try:
        agent_count_target = int(request.get("agent_count_target") or 40)
    except Exception:
        agent_count_target = 40
    agent_count_target = max(8, min(120, agent_count_target))

    min_rooms = max(6, agent_count_target // 3)
    if "panjiayuan" in request.get("world_name", "").lower():
        min_rooms = 7
    min_items_catalog = max(15, agent_count_target // 2)

    lines = [
        "Create a high-level builder_spec for an Agora persistent multi-agent world.",
        "Stay concrete and implementation-friendly.",
        f"Requested world name: {request.get('world_name', '')}",
        f"Theme/genre: {request.get('genre', '')}",
        f"Expected human players: {request.get('player_count_target', '')}",
        f"Expected agent count: {agent_count_target}",
        f"Primary focus: {request.get('focus', '')}",
        f"Seed hint: {request.get('seed', '')}",
        f"DYNAMIC SCALING ADVISOR RULES FOR THIS SCALE ({agent_count_target} agents):",
        f"- You MUST generate at least {min_rooms} distinct and uniquely themed rooms to prevent overcrowding.",
        f"- The `item_catalog` MUST contain at least {min_items_catalog} rich, setting-appropriate items.",
        "- Keep personal starting items compact. Merchant stock belongs in the item catalog and property assets, not in role-name-triggered personal inventory.",
        "Natural language brief:",
        str(request.get("brief", "")).strip(),
    ]
    if prior_context:
        lines.extend(
            [
                "",
                "Previous draft context:",
                json.dumps(prior_context, ensure_ascii=False, indent=2),
            ]
        )
    if feedback.strip():
        lines.extend(["", "User revision request:", feedback.strip()])
    if repair_note.strip():
        lines.extend(["", "Repair note from previous invalid draft:", repair_note.strip()])
    lines.extend(
        [
            "",
            "Return only JSON for builder_spec.",
            "Prefer 6-12 room concepts, 3-5 role groups, and 2-3 main characters.",
            "Keep counts realistic for the requested agent scale.",
            "Author an open semantic world_seed with seed_version world_seed_v3_open, locale, tone, visual direction, and a world-specific currency.",
            "Do not select a preset, profile, kit, registry, or implementation template; the compiler chooses compatibility adapters later.",
            "Author world_dynamics with at least 3 institutions, 4 mutable state variables, 4 exact-ID causal links, and 3 stakeholder groups.",
            "Every institution must expose a decision rule and visible output. Every causal link must create a player-visible downstream consequence.",
            "Also include gameplay_loops, player_entry_points, conflict_hooks, and custom_actions when they help the world feel playable.",
            "Role groups should ideally hint at a home base and actionable starting items.",
            "CRITICAL: You MUST invent and author a rich, culturally specific list of items in `item_catalog` matching the world's locale and tone (e.g. if the world is a Chinese antique market, populate it with 15 to 30 authentic items like jades, bronze ware, historical appraisals, calligraphy, ancient coins, appraisers' tools, rather than standard Western fantasy items). Each item must have: a unique string `item_id`, a friendly `name`, base `price` (integer minor unit base value, e.g. CNY cents, silver coins, gold points), `mass` (float in kg), `description`, an `image_prompt` (a descriptive visual prompt for generating a beautiful high-quality pixel-art RPG item icon on a simple black/dark background, no text), and an optional `category` (e.g. general, antique, gear, document, coin).",
            "For every room, you MUST explicitly define a semantic 'archetype' chosen exactly from: 'market_exchange', 'checkpoint', 'logistics_yard', 'lookout', 'workshop', 'archive_ritual', 'rest_social', 'training', 'council', 'commons'. This ensures Phaser knows how to render the walls and floors. Choose the archetype that fits the room's purpose best. Also choose an 'ambient_palette' chosen exactly from: 'warm_lantern', 'soft_mint', 'focused_blue', 'clear_day', 'dusty_brown', 'ember_orange', 'low_lantern' to set the atmosphere.",
            "CRITICAL MAP AESTHETICS: You MUST explicitly assign `floor_tile` and `wall_tile` for every room, and match the aesthetic to the world's locale and tone. Do NOT default to generic RPG stones if it doesn't fit the setting. Choose the specific tiles that match the world's exact era and atmosphere (e.g., use `clean_tile` and `glass_case_wall` for a modern commercial center, use `bamboo_planks` and `red_pillar_wall` for a traditional antique market, use `forge_slate` for a workshop).",
            "CRITICAL MAP AGENT INSTRUCTION: You must assign `width_tiles` and `height_tiles` to every room. Size each room from its purpose and expected occupancy: shared public hubs in 50+ agent worlds may need 30-60 tile dimensions, while focused shops or offices usually need 8-15 tiles. Do not force one world's spatial pattern onto another.",
            "For every role group and every main character, you MUST explicitly populate 'starting_item_ids' as an array of strings. Each string in 'starting_item_ids' MUST be an 'item_id' that you defined in your custom 'item_catalog', ensuring characters start with the specific items you invented instead of placeholders. To achieve high inventory density and freedom, civilians and main characters MUST have 8 to 15 relevant starting item IDs, and merchants/traders MUST have 20 to 40 relevant starting item IDs.",
            "For every role group and every main character, you MUST explicitly populate both 'property_templates' and 'knowledge_templates' with culturally authentic, world-specific details. Do not use generic placeholders. Each property template must be an object with: 'asset_name', 'asset_type', 'description', and 'story_use'. Each knowledge template must be an object with: 'knowledge_id', 'topic', 'summary', and 'confidence'.",
        ]
    )
    return "\n".join(lines).strip()


def _world_config_critique_prompt(request: dict[str, Any], builder_spec: dict[str, Any], config: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Critique this compiled Agora world_config as a world compiler reviewer.",
            "Focus on whether the world feels playable and persistent rather than merely valid.",
            "Only suggest compact repairs that can be applied deterministically to builder_spec or the compiled config.",
            "Prefer fixes for missing gameplay loops, weak player entry, vague conflict pressure, role-room mismatch, and thin action coverage.",
            "",
            "Original request:",
            json.dumps(request, ensure_ascii=False, indent=2),
            "",
            "Builder spec:",
            json.dumps(builder_spec, ensure_ascii=False, indent=2),
            "",
            "Compiled config snapshot:",
            json.dumps(_config_snapshot_for_critique(config), ensure_ascii=False, indent=2),
        ]
    ).strip()


def _world_summary_prompt(builder_spec: dict[str, Any], config: dict[str, Any]) -> str:
    from .builder import _structured_summary
    return "\n".join(
        [
            f"Write a world-setting summary in about 1000 words for {builder_spec.get('world_name', 'this world')}.",
            "Explain the world premise, space, main characters, social loops, economy, exploration hooks, and the kinds of multiplayer interactions this world supports.",
            "Be concrete and readable for a creator reviewing a draft package.",
            "Mention what players and agents are expected to do in this world.",
            "",
            "Builder spec:",
            json.dumps(builder_spec, ensure_ascii=False, indent=2),
            "",
            "Structured config summary:",
            json.dumps(_structured_summary(config), ensure_ascii=False, indent=2),
        ]
    ).strip()
