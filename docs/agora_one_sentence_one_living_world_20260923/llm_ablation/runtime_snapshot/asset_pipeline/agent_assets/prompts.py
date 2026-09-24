from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from asset_pipeline.process_sprite import DEFAULT_ANIMATION_STATES


SPRITE_PROMPT_ANTI_CROP_GUARDRAILS = (
    "Readable JRPG field-sprite proportions with a normal full-body human silhouette, a clearly visible head-and-shoulder shape, a broad readable torso, and distinct legs. "
    "The silhouette must remain recognizable at 64x64 gameplay size: the body should occupy at least 30 percent of the frame width in front-facing views, with bold clothing color blocks and a strong outline after reduction. "
    "Do not use super-deformed chibi sticker proportions. Use mildly stylized game proportions rather than a thin realistic fashion silhouette or an extreme chibi body. Do not crop the figure to fit the box. "
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
    if any(token in normalized for token in (
        "frontline",
        "adventurer",
        "security",
        "guard",
        "marshal",
        "soldier",
        "mercenary",
        "enforcer",
        "arms",
        "bouncer",
    )):
        return "frontline_adventurer"
    if any(token in normalized for token in (
        "ranger",
        "pilot",
        "captain",
        "courier",
        "salvage",
        "salvager",
        "wrecker",
        "dock",
        "hauler",
        "scout",
    )):
        return "ranger"
    if any(token in normalized for token in (
        "healer",
        "doctor",
        "medic",
        "surgeon",
        "pharmacist",
        "药师",
        "botanist",
        "xeno",
        "lab",
    )):
        return "healer"
    return "default"


def _world_style_text(world_config: dict[str, Any] | None) -> str:
    if not world_config:
        return ""
    scenario_meta = world_config.get("scenario_meta", {})
    runner = world_config.get("runner", {})
    longlive = world_config.get("longlive", {})
    seed_data = world_config.get("world_definition", {}).get("world_definition_seed", {})
    parts = [
        scenario_meta.get("world_name", ""),
        scenario_meta.get("description", ""),
        scenario_meta.get("simulation_objective", ""),
        runner.get("domain_label", ""),
        longlive.get("visual_style", ""),
        seed_data.get("genre", ""),
        seed_data.get("locale", ""),
        seed_data.get("focus", ""),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _is_panjiayuan_world(style_text: str) -> bool:
    explicit_markers = (
        "panjiayuan",
        "潘家园",
        "北京潘家园",
        "古玩",
        "antique market",
        "antiques market",
        "beijing antique",
        "liulichang",
        "琉璃厂",
    )
    return any(marker in style_text for marker in explicit_markers)


def _world_style_family(style_text: str) -> str:
    if any(token in style_text for token in (
        "space",
        "orbital",
        "lagrange",
        "starship",
        "spaceship",
        "sci-fi",
        "science fiction",
        "cyber",
        "alien",
        "future",
        "futuristic",
    )):
        return "hard_sci_fi"
    if any(token in style_text for token in (
        "modern",
        "corporate",
        "city",
        "urban",
        "bureaucracy",
        "civic",
        "contemporary",
    )):
        return "modern_civic"
    if any(token in style_text for token in (
        "port",
        "harbor",
        "seafood",
        "cold-chain",
        "cold chain",
        "maritime",
        "dock",
        "warehouse",
        "industrial",
        "logistics",
    )):
        return "maritime_industrial"
    return "registry_default"


def _world_aware_visual_kit(style_family: str) -> dict[str, Any]:
    if style_family == "hard_sci_fi":
        return {
            "themes": [
                {"theme_name": "orbital_hazard", "dominant": "graphite gray", "accent": "hazard orange", "trim": "cold white", "leather": "rubber black"},
                {"theme_name": "station_authority", "dominant": "navy pressure-cloth", "accent": "signal blue", "trim": "brushed silver", "leather": "charcoal"},
                {"theme_name": "salvage_yard", "dominant": "dusty olive", "accent": "rust red", "trim": "dull brass", "leather": "oil-dark brown"},
                {"theme_name": "hydroponic_tech", "dominant": "clean mint", "accent": "bio-lume green", "trim": "white polymer", "leather": "graphite"},
                {"theme_name": "black_market_neon", "dominant": "matte black", "accent": "magenta neon", "trim": "cyan light", "leather": "dark vinyl"},
                {"theme_name": "cargo_union", "dominant": "workwear tan", "accent": "industrial yellow", "trim": "steel gray", "leather": "dark canvas"},
            ],
            "styles": {
                "frontline_adventurer": [
                    "a station-security armored jacket over a compact pressure suit",
                    "a reinforced EVA duty harness with plated shoulders",
                    "a customs enforcement coat with scanner pouches and hard knee pads",
                    "a black-market body-armor vest over a utility jumpsuit",
                ],
                "ranger": [
                    "a worn flight jacket over a vacuum-rated utility suit",
                    "a salvage rig with cargo straps, magnetic boot cuffs, and tool loops",
                    "a freighter captain coat with a compact comms harness",
                    "a dock-worker pressure jumpsuit with bright modular cargo tabs",
                ],
                "healer": [
                    "a sterile lab coat over a sealed pressure undersuit",
                    "a xenobiology field smock with sealed gloves and sample pockets",
                    "a cybernetics clinic apron over a high-collar medical jumpsuit",
                    "a biohazard technician jacket with glowing diagnostic bands",
                ],
                "default": [
                    "a modular space-station utility jacket with visible ID patch",
                    "a practical cargo jumpsuit with magnetic boot cuffs",
                    "a corporate spacer coat with a slim datapad holster",
                    "a layered habitat-worker vest over a pressure-cloth undersuit",
                ],
            },
            "props": {
                "frontline_adventurer": ["a wrist scanner", "a security badge light", "a compact baton holster", "a shoulder-mounted comms tab"],
                "ranger": ["a salvage claim tag", "a tether hook", "a compact tool pouch", "a freighter transponder badge"],
                "healer": ["a sample vial rack", "a medical scanner", "a sealed specimen pouch", "a glowing diagnostic wrist cuff"],
                "default": ["a datapad", "a cargo seal tag", "a station ID badge", "a small oxygen tether clip"],
            },
            "patterns": [
                "a high-visibility sleeve stripe",
                "a glowing chest status strip",
                "a single station-emblem shoulder patch",
                "a diagonal cargo harness color break",
                "a reflective boot-and-cuff repeat",
                "a compact utility-belt color accent",
            ],
            "label": "hard sci-fi station wardrobe",
        }
    if style_family == "modern_civic":
        return {
            "themes": [
                {"theme_name": "civic_slate", "dominant": "slate gray", "accent": "public-service blue", "trim": "white", "leather": "black"},
                {"theme_name": "corporate_teal", "dominant": "deep teal", "accent": "warm gray", "trim": "silver", "leather": "charcoal"},
                {"theme_name": "street_maroon", "dominant": "maroon", "accent": "cream", "trim": "black", "leather": "dark brown"},
            ],
            "styles": {
                "frontline_adventurer": ["a fitted security jacket with radio loops", "a municipal field coat with reinforced elbows"],
                "ranger": ["a courier jacket with cross-body utility strap", "a practical outdoor shell with cargo pockets"],
                "healer": ["a modern clinical coat over practical streetwear", "a medical responder vest with clear utility pockets"],
                "default": ["a tailored work jacket with visible role badge", "a layered urban vest over a clean shirt"],
            },
            "props": {
                "frontline_adventurer": ["a radio mic", "a laminated access badge"],
                "ranger": ["a messenger satchel", "a route tablet"],
                "healer": ["a compact med kit", "a diagnostic tablet"],
                "default": ["a phone-sized tablet", "a badge clip"],
            },
            "patterns": ["a crisp sleeve stripe", "a small chest logo patch", "a contrasting zipper line", "a color-blocked shoulder panel"],
            "label": "modern civic wardrobe",
        }
    if style_family == "maritime_industrial":
        return {
            "themes": [
                {"theme_name": "cold_chain_blue", "dominant": "cold blue", "accent": "safety orange", "trim": "white", "leather": "rubber black"},
                {"theme_name": "dockworker_olive", "dominant": "olive workwear", "accent": "rust red", "trim": "steel gray", "leather": "dark canvas"},
                {"theme_name": "harbor_yellow", "dominant": "raincoat yellow", "accent": "navy", "trim": "reflective white", "leather": "black rubber"},
            ],
            "styles": {
                "frontline_adventurer": ["a waterproof security slicker with reflective bands", "a reinforced dock safety vest over workwear"],
                "ranger": ["a harbor runner jacket with cargo straps", "a cold-chain loader suit with insulated cuffs"],
                "healer": ["a clean inspection coat over waterproof boots", "a food-safety lab smock with sealed cuffs"],
                "default": ["a practical dock jacket with apron-like utility panel", "an insulated logistics vest over rolled work sleeves"],
            },
            "props": {
                "frontline_adventurer": ["a handheld inspection light", "a dock radio"],
                "ranger": ["a cargo hook tag", "a manifest satchel"],
                "healer": ["a sample case", "a temperature probe"],
                "default": ["a cargo manifest tag", "a small tool pouch"],
            },
            "patterns": ["a reflective hem band", "a safety stripe on one sleeve", "a bold utility-belt accent", "a cold-storage badge patch"],
            "label": "maritime industrial wardrobe",
        }
    return {}


def _agent_visual_policy(world_config: dict[str, Any] | None) -> dict[str, Any]:
    if not world_config:
        return {}
    pipeline = world_config.get("pixel_asset_pipeline", {})
    if not isinstance(pipeline, dict):
        return {}
    policy = pipeline.get("agent_visual_policy", {})
    return dict(policy) if isinstance(policy, dict) else {}


def _world_visual_canon(world_config: dict[str, Any] | None) -> dict[str, Any]:
    if not world_config:
        return {}
    pipeline = world_config.get("pixel_asset_pipeline", {})
    if not isinstance(pipeline, dict):
        return {}
    canon = pipeline.get("visual_canon", {})
    return dict(canon) if isinstance(canon, dict) else {}


def _policy_palette(policy: dict[str, Any], seed: int) -> dict[str, str]:
    palettes = [dict(entry) for entry in policy.get("palette_families", []) if isinstance(entry, dict)]
    if not palettes:
        raise ValueError("agent_visual_policy is present but palette_families is empty.")
    palette = palettes[seed % len(palettes)]
    return {
        "name": str(palette.get("name", "world_palette")).strip() or "world_palette",
        "dominant": str(palette.get("dominant", "world-colored")).strip() or "world-colored",
        "accent": str(palette.get("accent", "secondary")).strip() or "secondary",
        "trim": str(palette.get("trim", "trim")).strip() or "trim",
        "material": str(palette.get("material", "practical material")).strip() or "practical material",
    }


def _policy_text_list(value: Any, *, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        key = text.lower()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _select_policy_rule(policy: dict[str, Any], agent_profile: dict[str, Any], public_state: dict[str, Any]) -> dict[str, Any]:
    role_text = " ".join(
        [
            str(public_state.get("role_name", "")),
            str(public_state.get("activity_directive", "")),
            str(agent_profile.get("appearance_prompt", "")),
            str(agent_profile.get("display_name", "")),
        ]
    ).lower()
    best_rule: dict[str, Any] | None = None
    best_score = 0
    for raw_rule in policy.get("role_style_rules", []):
        if not isinstance(raw_rule, dict):
            continue
        keywords = _policy_text_list(raw_rule.get("role_keywords", []), limit=20)
        score = sum(1 for keyword in keywords if keyword.lower() and keyword.lower() in role_text)
        if score > best_score:
            best_rule = dict(raw_rule)
            best_score = score
    if best_rule is None:
        default_rule = policy.get("default_rule", {})
        if not isinstance(default_rule, dict):
            raise ValueError("agent_visual_policy is present but default_rule is missing.")
        best_rule = dict(default_rule)
    if not _policy_text_list(best_rule.get("attire", [])):
        raise ValueError("agent_visual_policy selected rule has no attire.")
    if not _policy_text_list(best_rule.get("props", [])):
        raise ValueError("agent_visual_policy selected rule has no props.")
    return best_rule


def _build_visual_identity_from_policy(
    *,
    policy: dict[str, Any],
    agent_profile: dict[str, Any],
    public_state: dict[str, Any],
) -> dict[str, Any]:
    seed = _agent_visual_seed(agent_profile)
    role_key = _role_style_key(public_state.get("role_name", ""))
    palette = _policy_palette(policy, seed)
    rule = _select_policy_rule(policy, agent_profile, public_state)
    attire_options = _policy_text_list(rule.get("attire", []), limit=8)
    prop_options = _policy_text_list(rule.get("props", []), limit=8)
    forbidden = _policy_text_list(policy.get("forbidden_aesthetics", []), limit=12)
    avoid = _policy_text_list(rule.get("avoid", []), limit=8)
    consistency = _policy_text_list(policy.get("visual_consistency_rules", []), limit=6)
    attire = attire_options[(seed * 3 + 1) % len(attire_options)]
    prop = prop_options[(seed * 5 + 2) % len(prop_options)]
    silhouette_notes = str(rule.get("silhouette_notes", "")).strip() or "readable full-body silhouette at 64x64 gameplay size"
    palette_notes = str(rule.get("palette_notes", "")).strip()
    world_brief = str(policy.get("world_wardrobe_brief", "")).strip()
    forbidden_sentence = ""
    if forbidden or avoid:
        forbidden_sentence = " Avoid unrelated aesthetics: " + ", ".join((forbidden + avoid)[:14]) + "."
    consistency_sentence = ""
    if consistency:
        consistency_sentence = " Consistency rules: " + "; ".join(consistency[:4]) + "."

    identity_brief = (
        f"World-authored wardrobe policy {policy.get('policy_id', 'agent_visual_policy')}: {world_brief} "
        f"Palette family {palette['name']}: dominant {palette['dominant']}, accent {palette['accent']}, "
        f"trim {palette['trim']}, material cue {palette['material']}. "
        f"Character wears {attire}, carries {prop}, and follows silhouette rule: {silhouette_notes}. "
        f"{palette_notes} This policy must read immediately at 64x64 gameplay size."
        f"{forbidden_sentence}{consistency_sentence}"
    )
    sprite_constraints = (
        f"Use the world-authored wardrobe policy, not a hardcoded regional template. "
        f"Make {palette['dominant']} the main clothing color block, use {palette['accent']} as secondary accents, "
        f"and reserve {palette['trim']} for trim/highlights. "
        f"Display {attire} as the main silhouette cue and keep {prop} visible if it can fit without hiding the body. "
        f"Preserve {silhouette_notes}. {palette_notes} "
        f"{forbidden_sentence}{consistency_sentence} "
        "At gameplay scale, this agent must remain distinguishable from other nearby characters by palette, silhouette, and role-specific gear."
    )
    return {
        "seed": seed,
        "role_style_key": role_key,
        "style_family": "world_authored_policy",
        "theme_name": palette["name"],
        "dominant_color": palette["dominant"],
        "accent_color": palette["accent"],
        "trim_color": palette["trim"],
        "leather_color": palette["material"],
        "silhouette": attire,
        "signature_prop": prop,
        "pattern": silhouette_notes,
        "identity_brief": identity_brief,
        "sprite_constraints": sprite_constraints,
    }


def _build_visual_identity(agent_profile: dict[str, Any], public_state: dict[str, Any], package_root: Path, world_config: dict[str, Any] | None = None) -> dict[str, Any]:
    kits = _load_visual_kits(package_root)

    policy = _agent_visual_policy(world_config)
    if policy:
        return _build_visual_identity_from_policy(
            policy=policy,
            agent_profile=agent_profile,
            public_state=public_state,
        )
    
    world_style_text = _world_style_text(world_config)
    is_panjiayuan = _is_panjiayuan_world(world_style_text)
    style_family = _world_style_family(world_style_text)

    if is_panjiayuan:
        # Traditional or vintage Chinese aesthetics only for explicit Panjiayuan/antique-market worlds.
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
        world_kit = _world_aware_visual_kit(style_family)
        if world_kit:
            themes = world_kit["themes"]
            styles = world_kit["styles"]
            props = world_kit["props"]
            patterns = world_kit["patterns"]
        else:
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
            "This cultural look must read immediately at 64x64 pixel gameplay size."
        )
        sprite_constraints = (
            f"Chinese merchant/citizen identity: make {theme['dominant']} the dominant clothing color block, "
            f"use {theme['accent']} for secondary cloth blocks, and reserve {theme['trim']} for frog buttons, trim, and highlights. "
            f"Display {silhouette} as the main clothing silhouette and make {prop} visible on the sprite. "
            "Override fantasy options with this vintage Beijing Chinese character outfit. At gameplay scale, the agent must be distinguishable."
        )
    else:
        world_kit_label = "registry visual kit"
        world_kit = _world_aware_visual_kit(style_family)
        if world_kit:
            world_kit_label = str(world_kit.get("label", world_kit_label))
        else:
            world_kit = {}
        identity_brief = (
            f"Locked theme {theme['theme_name']}: dominant {theme['dominant']} outerwear, "
            f"{theme['accent']} accent cloth, {theme['trim']} trim, and {theme['leather']} leather details. "
            f"Use {silhouette}, plus {prop}, with {pattern}. "
            f"World wardrobe family: {world_kit_label}. "
            "This theme must read immediately at 64x64 and must not look like a palette-swap of neighboring agents. "
            "Do not inject unrelated regional, historical-market, tea-house, or antique-vendor clothing unless the world or appearance explicitly asks for it."
        )
        sprite_constraints = (
            f"Unique visual identity lock: make {theme['dominant']} the dominant clothing color block, "
            f"use {theme['accent']} only as a secondary accent, and reserve {theme['trim']} for trim/highlights. "
            f"Show {silhouette} as a large readable silhouette cue and keep {prop} visible in the sprite. "
            "Override stock colors from the base appearance prompt only when needed to preserve this world's wardrobe family; "
            "do not fall back to generic fantasy robes, regional vendor coats, tea-service tops, or antique-market clothing unless they match this world. "
            "At gameplay scale, this agent must remain distinguishable from other nearby characters by both palette and clothing silhouette."
        )
        
    return {
        "seed": seed,
        "role_style_key": role_key,
        "style_family": "panjiayuan_antique_market" if is_panjiayuan else style_family,
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
    visual_canon = _world_visual_canon(world_config)
    canon_sprite_prefix = str(visual_canon.get("sprite_prompt_prefix", "")).strip()
    canon_hash = str(visual_canon.get("canon_hash", "")).strip()
    canon_forbidden = _policy_text_list(visual_canon.get("forbidden_visuals", []), limit=12)
    canon_clause = (
        f"Shared visual canon {canon_hash}: {canon_sprite_prefix}. "
        f"Never include {', '.join(canon_forbidden)}. "
        if visual_canon
        else ""
    )

    authored_presentation = str(agent_profile.get("gender_presentation", "")).strip().lower()
    if authored_presentation in {"female", "feminine", "woman"}:
        gender_presentation = "feminine"
    elif authored_presentation in {"male", "masculine", "man"}:
        gender_presentation = "masculine"
    elif authored_presentation in {"androgynous", "nonbinary", "non-binary", "neutral"}:
        gender_presentation = "androgynous"
    else:
        gender_presentation = ""

    # Fall back to textual inference only when the profile has no authored cue.
    if not gender_presentation:
        app_lower = appearance_prompt.lower()
        name_lower = agent_name.lower()
        if any(x in app_lower or x in name_lower for x in ("female", "woman", "girl", "lady")):
            gender_presentation = "feminine"
        elif any(x in app_lower or x in name_lower for x in ("male", "man", "boy", "gentleman")):
            gender_presentation = "masculine"
        else:
            gender_presentation = "androgynous"

    concept_prompt = (
        f"Design a game-ready character concept for {agent_name}, a {role_name} in {world_name}. "
        f"Gender presentation: {gender_presentation}. "
        f"Theme: {domain_label}. Room context: {room_name} with biome {room_visual.get('biome', 'neutral')} "
        f"and decor {', '.join(room_visual.get('decor_tags', [])) or 'minimal decor'}. "
        f"Appearance: {appearance_prompt}. Core values: {core_values or 'steady presence'}. "
        f"Personality tags: {personality_tags or 'grounded'}. "
        f"Activity directive: {activity_directive or 'support the world state'}. "
        f"{canon_clause}{visual_identity['identity_brief']} "
        "Keep the silhouette readable, expressive, and suitable for later pixel-art reduction."
    )
    # Strict full-body identity to prevent FLUX from drawing close-ups/portraits
    sprite_identity = (
        f"Role identity: {role_name}. Gender presentation: {gender_presentation}. Appearance: {appearance_prompt}. "
        f"Core values: {core_values or 'steady presence'}. Personality tags: {personality_tags or 'grounded'}. "
        f"Activity directive: {activity_directive or 'support the world state'}. "
        f"{visual_identity['identity_brief']}"
    )
    sprite_prompt = (
        f"Create a strict pixel-art sprite sheet for one world character matching this identity. {canon_clause}{sprite_identity} "
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
        "Keep modest transparent separation between cells, but do not shrink the person into a narrow strip; head, shoulders, torso, and role-defining clothing must remain readable after reduction. "
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
        "gender_presentation": gender_presentation,
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
