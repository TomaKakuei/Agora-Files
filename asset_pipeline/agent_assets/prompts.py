from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from asset_pipeline.process_sprite import DEFAULT_ANIMATION_STATES


SPRITE_PROMPT_ANTI_CROP_GUARDRAILS = (
    "Classic JRPG field-sprite proportions with a normal full-body human silhouette, readable torso, and readable leg length. "
    "Do not use super-deformed chibi sticker proportions, do not widen the body to fill a square, and do not crop the figure to fit the box. "
    "Transparent padding inside each cell is allowed and preferred when it preserves full-body proportions. "
    "Keep strong empty transparent spacing between rows and columns, with strictly isolated characters centered in invisible grid cells. "
    "Each character must remain fully contained inside its own cell with generous transparent margins on all sides. "
    "Never let the head, hands, weapon, feet, hair, or clothing cross a cell boundary. "
    "No overlap between neighboring cells, no cropping, no partial body, no split body parts. "
    "PURE WHITE BACKGROUND ONLY. ABSOLUTELY NO SCENERY, NO ENVIRONMENT, NO PROPS BEHIND THE CHARACTER. "
    "No floor shadow, no reflection, no caption, no title, no labels, no letters, no typography. "
    "This is a strict production sprite sheet, not a poster, not a concept board, not a character lineup, and not a reference sheet."
)


def _locate_package_root(config_path: Path) -> Path:
    current = config_path.resolve()
    for candidate in [current.parent, *current.parents]:
        if (candidate / "agora_ui").is_dir() and (candidate / "asset_pipeline").is_dir():
            return candidate
    raise RuntimeError(f"Could not locate Agora_UI package root from config path: {config_path}")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


_VISUAL_KITS = None

def _load_visual_kits(package_root: Path) -> dict[str, Any]:
    global _VISUAL_KITS
    if _VISUAL_KITS is None:
        kits_path = package_root / "agora_ui" / "data" / "registries" / "agent_visual_kits.json"
        _VISUAL_KITS = _read_json(kits_path) if kits_path.is_file() else {}
    return _VISUAL_KITS


def _agent_visual_seed(agent_profile: dict[str, Any]) -> int:
    agent_id = str(agent_profile.get("agent_id", "")).strip()
    suffix = agent_id.rsplit("_", 1)[-1]
    if suffix.isdigit():
        return max(0, int(suffix) - 1)
    digest = hashlib.sha256(agent_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _role_style_key(role_name: str) -> str:
    normalized = str(role_name or "").strip().lower()
    if "frontline" in normalized or "adventurer" in normalized:
        return "frontline_adventurer"
    if "ranger" in normalized:
        return "ranger"
    if "healer" in normalized:
        return "healer"
    return "default"


def _build_visual_identity(agent_profile: dict[str, Any], public_state: dict[str, Any], package_root: Path, world_config: dict[str, Any] | None = None) -> dict[str, Any]:
    kits = _load_visual_kits(package_root)
    
    world_name = ""
    world_locale = "zh_CN"
    if world_config:
        scenario_meta = world_config.get("scenario_meta", {})
        world_name = str(scenario_meta.get("world_name", "")).lower()
        seed_data = world_config.get("world_definition", {}).get("world_definition_seed", {})
        world_locale = str(seed_data.get("locale", "zh_CN") or "zh_CN").strip()
    
    is_panjiayuan = "panjiayuan" in world_name or "北京" in world_name or "北京潘家园" in world_name or "古玩" in world_name or world_locale == "zh_CN"

    if is_panjiayuan:
        # Traditional or vintage Chinese aesthetics for Panjiayuan Antique Market
        themes = [
            {"theme_name": "tang_dynasty_classic", "dominant": "cinnabar red", "accent": "warm ivory", "trim": "soft black", "leather": "dark walnut"},
            {"theme_name": "vintage_scholar", "dominant": "ink black", "accent": "bamboo green", "trim": "pure ivory", "leather": "cedar brown"},
            {"theme_name": "imperial_jade", "dominant": "jade green", "accent": "warm brass gold", "trim": "cream", "leather": "dark brown"},
            {"theme_name": "beijing_vendor", "dominant": "indigo blue", "accent": "dull gray", "trim": "pure white", "leather": "tan"},
            {"theme_name": "chestnut_collector", "dominant": "chestnut brown", "accent": "saffron amber", "trim": "off-white", "leather": "dark walnut"},
            {"theme_name": "bamboo_mist", "dominant": "sage green", "accent": "mist white", "trim": "bronze", "leather": "wood brown"}
        ]
        styles = {
            "frontline_adventurer": [
                "a traditional Chinese vendor's Tangzhuang vest with classic loop button knots",
                "a Beijing-style merchant short coat with a rolled fabric waistband",
                "an ornate satin Tang suit jacket with traditional round-collar patterns",
                "a rugged vendor's canvas work apron with large brass pocket buckles"
            ],
            "ranger": [
                "a traditional linen travel robe with symmetrical side-fasteners",
                "a scholar's lightweight linen overcoat layered with a folding fan pocket",
                "a modern casual Tang suit jacket with simple aesthetic frog closures",
                "a classic Beijing style vendor vest over a white cotton undershirt"
            ],
            "healer": [
                "a long vintage scholar's gown or changshan with wide flowing sleeves",
                "a premium silk scholar's robe with elegant jade-beaded sashes",
                "a traditional Chinese tea master's linen tunic with elegant sleeve cuffs",
                "a classic vintage direct-fastened long gown with an ink-wash pattern"
            ],
            "default": [
                "a classic Beijing merchant vest and long tunic combination",
                "a traditional Chinese cotton-padded vest with hand-woven button closures",
                "a simple vintage Chinese tunic suit or Zhongshan suit",
                "a casual modern Chinese tea-style top"
            ]
        }
        props = {
            "frontline_adventurer": ["a copper coin purse", "a merchant brass seal", "腰挂算盘", "a vintage receipt ledger"],
            "ranger": ["a vintage antique magnifying glass", "a folding paper fan", "a vintage pocket watch", "a leather coin bag"],
            "healer": ["a bead bracelet or string of prayer beads", "a jade pendant", "a small purple clay teapot", "a tea cup holder"],
            "default": ["a traditional Chinese red knot", "a small brass key", "a silk coin pouch", "a waist bamboo token"]
        }
        patterns = [
            "a gold-embroidered dragon/phoenix hem pattern",
            "a bold red Chinese sash accent",
            "a two-tone traditional cloud-pattern hem border",
            "a single circular jade medallion patch",
            "a contrasting white roll-up sleeve cuff",
            "a classic black frog button closure repeat",
            "a split-color traditional silk lining",
            "a strong woven waist cord accent"
        ]
    else:
        # Fallback to standard fantasy kits
        themes = kits.get("VISUAL_THEME_PRESETS", [{"theme_name": "default", "dominant": "gray", "accent": "white", "trim": "black", "leather": "brown"}])
        styles = kits.get("ROLE_STYLE_VARIANTS", {"default": ["a bold outerwear layer"]})
        props = kits.get("ROLE_SIGNATURE_PROPS", {"default": ["a shoulder clasp"]})
        patterns = kits.get("VISUAL_PATTERN_VARIANTS", ["a two-tone hem border"])

    seed = _agent_visual_seed(agent_profile)
    role_key = _role_style_key(public_state.get("role_name", ""))
    theme = themes[seed % len(themes)]
    silhouette_options = styles.get(role_key, styles["default"])
    prop_options = props.get(role_key, props["default"])
    pattern = patterns[(seed * 7 + 3) % len(patterns)]
    silhouette = silhouette_options[(seed * 3 + 1) % len(silhouette_options)]
    prop = prop_options[(seed * 5 + 2) % len(prop_options)]
    
    if is_panjiayuan:
        identity_brief = (
            f"Chinese Style Theme {theme['theme_name']}: dominant {theme['dominant']} attire, "
            f"{theme['accent']} secondary cloth, {theme['trim']} trim details, and {theme['leather']} accents. "
            f"Character wears {silhouette}, carries {prop}, with {pattern}. "
            "This cultural look must read immediately at 32x32 pixel gameplay size."
        )
        sprite_constraints = (
            f"Chinese merchant/citizen identity: make {theme['dominant']} the dominant clothing color block, "
            f"use {theme['accent']} for secondary cloth blocks, and reserve {theme['trim']} for frog buttons, trim, and highlights. "
            f"Display {silhouette} as the main clothing silhouette and make {prop} visible on the sprite. "
            "Override fantasy options with this vintage Beijing Chinese character outfit. At gameplay scale, the agent must be distinguishable."
        )
    else:
        identity_brief = (
            f"Locked theme {theme['theme_name']}: dominant {theme['dominant']} outerwear, "
            f"{theme['accent']} accent cloth, {theme['trim']} trim, and {theme['leather']} leather details. "
            f"Use {silhouette}, plus {prop}, with {pattern}. "
            "This theme must read immediately at 32x32 and must not look like a palette-swap of neighboring agents."
        )
        sprite_constraints = (
            f"Unique visual identity lock: make {theme['dominant']} the dominant clothing color block, "
            f"use {theme['accent']} only as a secondary accent, and reserve {theme['trim']} for trim/highlights. "
            f"Show {silhouette} as a large readable silhouette cue and keep {prop} visible in the sprite. "
            "Override stock colors from the base appearance prompt if needed; do not fall back to generic green ranger capes, "
            "generic mint healer robes, or generic blue mage robes unless they match this locked theme. "
            "At gameplay scale, this agent must remain distinguishable from other nearby characters by both palette and clothing silhouette."
        )
        
    return {
        "seed": seed,
        "role_style_key": role_key,
        "theme_name": theme["theme_name"],
        "dominant_color": theme["dominant"],
        "accent_color": theme["accent"],
        "trim_color": theme["trim"],
        "leather_color": theme["leather"],
        "silhouette": silhouette,
        "signature_prop": prop,
        "pattern": pattern,
        "identity_brief": identity_brief,
        "sprite_constraints": sprite_constraints,
    }


def _build_prompt_bundle(
    *,
    world_config: dict[str, Any],
    agent_profile: dict[str, Any],
    room: dict[str, Any] | None,
    pipeline_config: dict[str, Any],
    package_root: Path | None = None,
) -> dict[str, Any]:
    # Test suite compatibility backup
    if package_root is None:
        package_root = _locate_package_root(Path(__file__).resolve())

    scenario_meta = world_config.get("scenario_meta", {})
    runner = world_config.get("runner", {})
    public_state = agent_profile.get("public_state", {})
    room_visual = (room or {}).get("visual", {})
    sheet_layout = pipeline_config.get("sheet_layout", {})
    processing = pipeline_config.get("processing", {})
    agent_name = agent_profile.get("display_name", agent_profile["agent_id"])
    room_name = (room or {}).get("name", room_visual.get("biome", "unknown_room"))
    palette = room_visual.get("ambient_palette", "balanced_fantasy")
    core_values = ", ".join(agent_profile.get("core_values", []))
    personality_tags = ", ".join(public_state.get("personality_tags", []))
    role_name = public_state.get("role_name", "Agent")
    appearance_prompt = agent_profile.get("appearance_prompt", "")
    activity_directive = public_state.get("activity_directive", "")
    domain_label = runner.get("domain_label", "fictional world")
    world_name = scenario_meta.get("world_name", "Agora world")
    visual_identity = _build_visual_identity(agent_profile, public_state, package_root, world_config=world_config)

    concept_prompt = (
        f"Design a game-ready character concept for {agent_name}, a {role_name} in {world_name}. "
        f"Theme: {domain_label}. Room context: {room_name} with biome {room_visual.get('biome', 'neutral')} "
        f"and decor {', '.join(room_visual.get('decor_tags', [])) or 'minimal decor'}. "
        f"Appearance: {appearance_prompt}. Core values: {core_values or 'steady presence'}. "
        f"Personality tags: {personality_tags or 'grounded'}. "
        f"Activity directive: {activity_directive or 'support the world state'}. "
        f"{visual_identity['identity_brief']} "
        "Keep the silhouette readable, expressive, and suitable for later pixel-art reduction."
    )
    # Derive a clean gender representation to avoid confusing the generator
    gender_presentation = "male"
    app_lower = appearance_prompt.lower()
    name_lower = agent_name.lower()
    if any(x in app_lower or x in name_lower for x in ("female", "woman", "girl", "lady")):
        gender_presentation = "female"
    elif any(x in app_lower or x in name_lower for x in ("male", "man", "boy", "gentleman")):
        gender_presentation = "male"

    # Strict full-body identity to prevent FLUX from drawing close-ups/portraits
    sprite_identity = (
        f"Role identity: {role_name}. Appearance: {appearance_prompt}. "
        f"Core values: {core_values or 'steady presence'}. Personality tags: {personality_tags or 'grounded'}. "
        f"Activity directive: {activity_directive or 'support the world state'}. "
        f"{visual_identity['identity_brief']}"
    )
    sprite_prompt = (
        f"Create a strict pixel-art sprite sheet for one world character matching this identity. {sprite_identity} "
        f"Use a {sheet_layout.get('columns', 4)}x"
        f"{sheet_layout.get('rows', 4)} grid with frames sized "
        f"{sheet_layout.get('raw_frame_width', 128)}x{sheet_layout.get('raw_frame_height', 128)}. "
        f"Each row represents one motion state in this order: "
        f"{', '.join(state['name'] for state in sheet_layout.get('animation_states', DEFAULT_ANIMATION_STATES))}. "
        f"{SPRITE_PROMPT_ANTI_CROP_GUARDRAILS} "
        "This must be a complete production sheet, not a concept image: every cell must be populated and no cells may be blank. "
        f"Preserve a strong outline, consistent facing, readable hands, readable boots, readable gear, and a {palette} palette mood. "
        "The character must be full-body in every cell with visible head, torso, hips, two arms, two legs, and both feet. "
        "Every cell must contain exactly one complete character as a single connected silhouette; do not split upper body "
        "and lower body into disconnected islands, do not show only a bust, and do not cut the character into halves. "
        f"{visual_identity['sprite_constraints']} "
        "Keep the character fully inside each cell, centered, with feet anchored to a consistent baseline across frames. "
        "If preserving natural proportions requires extra transparent space on the left or right edges of a cell, keep that transparent padding instead of stretching the body wider. "
        "Lock the body scale, pelvis height, torso width, and shoulder line across the whole sheet; animate by moving limbs, "
        "not by resizing or sliding the torso around. "
        "The idle row must depict the same standing pose with minimal motion variation; walking rows may move limbs but "
        "must keep the torso stable, hips stable, and directionally readable. Avoid cropped limbs, amputated silhouettes, floating torsos, "
        "separated legs or torsos, oversized weapons that hide the body. "
        "Background must be PURE WHITE. Avoid text, UI framing, weapons leaving the frame, and painterly blur. "
        f"Target outcome after reduction: {processing.get('target_frame_width', 32)}x"
        f"{processing.get('target_frame_height', 32)} gameplay sprite frames."
    )
    return {
        "agent_id": agent_profile["agent_id"],
        "display_name": agent_name,
        "world_id": scenario_meta.get("world_id", ""),
        "world_name": world_name,
        "room_id": agent_profile.get("room_id", ""),
        "room_name": room_name,
        "room_visual": room_visual,
        "core_values": agent_profile.get("core_values", []),
        "personality_tags": public_state.get("personality_tags", []),
        "framework_version": pipeline_config.get("framework_version", "pixel_sprite_framework_v2"),
        "sheet_layout": sheet_layout,
        "processing": processing,
        "alignment_policy": processing.get("alignment_policy", {}),
        "concept_prompt": concept_prompt,
        "sprite_prompt": sprite_prompt,
        "negative_prompt": pipeline_config.get("sprite_generation", {}).get(
            "negative_prompt",
            "blurry, anti-aliased, smooth gradients, realistic lighting, text, watermark, captions, title text, logo, character name, studio backdrop, floor shadow, floor reflection, cropped limbs, missing arms, missing legs, amputated body, floating torso, bust portrait, upper body only, separated body parts, split torso and legs, character cut in half, giant weapon covering body, cropped head, cropped feet, boundary crossing, frame overlap, split body, detached legs, detached head",
        ),
    }
