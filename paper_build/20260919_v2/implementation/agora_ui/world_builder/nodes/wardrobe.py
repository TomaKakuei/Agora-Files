from __future__ import annotations

from typing import Any

from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.world_builder.generation import _execute_json_prompt


def _wardrobe_policy_schema() -> dict[str, Any]:
    rule_schema = {
        "type": "object",
        "required": ["rule_id", "role_keywords", "attire", "props", "palette_notes", "silhouette_notes"],
        "properties": {
            "rule_id": {"type": "string"},
            "role_keywords": {"type": "array", "items": {"type": "string"}},
            "attire": {"type": "array", "items": {"type": "string"}},
            "props": {"type": "array", "items": {"type": "string"}},
            "palette_notes": {"type": "string"},
            "silhouette_notes": {"type": "string"},
            "avoid": {"type": "array", "items": {"type": "string"}},
        },
    }
    return {
        "type": "object",
        "required": [
            "policy_id",
            "world_wardrobe_brief",
            "forbidden_aesthetics",
            "palette_families",
            "role_style_rules",
            "default_rule",
            "visual_consistency_rules",
        ],
        "properties": {
            "policy_id": {"type": "string"},
            "world_wardrobe_brief": {"type": "string"},
            "forbidden_aesthetics": {"type": "array", "items": {"type": "string"}},
            "palette_families": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "dominant", "accent", "trim", "material"],
                    "properties": {
                        "name": {"type": "string"},
                        "dominant": {"type": "string"},
                        "accent": {"type": "string"},
                        "trim": {"type": "string"},
                        "material": {"type": "string"},
                    },
                },
            },
            "role_style_rules": {"type": "array", "items": rule_schema},
            "default_rule": rule_schema,
            "visual_consistency_rules": {"type": "array", "items": {"type": "string"}},
        },
    }


def _compact_rooms(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for room in rooms[:24]:
        if not isinstance(room, dict):
            continue
        compact.append(
            {
                "name": str(room.get("name", "")),
                "biome": str(room.get("biome", "")),
                "purpose": str(room.get("purpose", "")),
                "decor_tags": [str(item) for item in room.get("decor_tags", []) if str(item).strip()][:8],
                "activity_tags": [str(item) for item in room.get("activity_tags", []) if str(item).strip()][:8],
            }
        )
    return compact


def _compact_roles(role_groups: list[dict[str, Any]], main_characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for role in role_groups[:20]:
        if not isinstance(role, dict):
            continue
        compact.append(
            {
                "role_name": str(role.get("role_name", "")),
                "activity": str(role.get("activity", "")),
                "core_values": [str(item) for item in role.get("core_values", []) if str(item).strip()][:6],
            }
        )
    for character in main_characters[:40]:
        if not isinstance(character, dict):
            continue
        compact.append(
            {
                "display_name": str(character.get("display_name", "")),
                "role_name": str(character.get("role_name", "")),
                "activity": str(character.get("activity", "")),
                "home_base": str(character.get("home_base", "")),
            }
        )
    return compact


def _normalize_text_list(values: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _normalize_rule(rule: dict[str, Any], *, fallback_id: str) -> dict[str, Any]:
    normalized = {
        "rule_id": str(rule.get("rule_id", fallback_id) or fallback_id).strip() or fallback_id,
        "role_keywords": _normalize_text_list(rule.get("role_keywords", []), limit=16),
        "attire": _normalize_text_list(rule.get("attire", []), limit=8),
        "props": _normalize_text_list(rule.get("props", []), limit=8),
        "palette_notes": str(rule.get("palette_notes", "")).strip(),
        "silhouette_notes": str(rule.get("silhouette_notes", "")).strip(),
        "avoid": _normalize_text_list(rule.get("avoid", []), limit=10),
    }
    if not normalized["attire"]:
        raise ValueError(f"Wardrobe policy rule {fallback_id} did not provide attire.")
    if not normalized["props"]:
        raise ValueError(f"Wardrobe policy rule {fallback_id} did not provide props.")
    if not normalized["silhouette_notes"]:
        normalized["silhouette_notes"] = "readable full-body silhouette at 64x64 gameplay scale"
    return normalized


def _normalize_policy(policy: dict[str, Any], planner_spec: dict[str, Any]) -> dict[str, Any]:
    palette_families: list[dict[str, str]] = []
    for index, raw_palette in enumerate(policy.get("palette_families", [])):
        if not isinstance(raw_palette, dict):
            continue
        palette = {
            "name": str(raw_palette.get("name", f"palette_{index + 1}") or f"palette_{index + 1}").strip(),
            "dominant": str(raw_palette.get("dominant", "")).strip(),
            "accent": str(raw_palette.get("accent", "")).strip(),
            "trim": str(raw_palette.get("trim", "")).strip(),
            "material": str(raw_palette.get("material", "")).strip(),
        }
        if all(palette[key] for key in ("dominant", "accent", "trim")):
            palette_families.append(palette)
    if len(palette_families) < 3:
        raise ValueError("Wardrobe policy node failed: fewer than 3 palette families.")

    role_rules: list[dict[str, Any]] = []
    for index, raw_rule in enumerate(policy.get("role_style_rules", [])):
        if isinstance(raw_rule, dict):
            role_rules.append(_normalize_rule(raw_rule, fallback_id=f"role_rule_{index + 1}"))
    if len(role_rules) < 3:
        raise ValueError("Wardrobe policy node failed: fewer than 3 role style rules.")

    default_rule_raw = policy.get("default_rule", {})
    if not isinstance(default_rule_raw, dict):
        default_rule_raw = {}
    default_rule = _normalize_rule(default_rule_raw, fallback_id="default_world_attire")

    return {
        "policy_version": "agent_visual_policy_v1",
        "generated_by": "world_builder.nodes.wardrobe",
        "model_stage": "agent_wardrobe_policy_generation",
        "policy_id": str(policy.get("policy_id", "") or f"{planner_spec.get('world_id', 'world')}_wardrobe_policy").strip(),
        "world_wardrobe_brief": str(policy.get("world_wardrobe_brief", "")).strip(),
        "forbidden_aesthetics": _normalize_text_list(policy.get("forbidden_aesthetics", []), limit=16),
        "palette_families": palette_families[:10],
        "role_style_rules": role_rules[:20],
        "default_rule": default_rule,
        "visual_consistency_rules": _normalize_text_list(policy.get("visual_consistency_rules", []), limit=12),
    }


def generate_wardrobe_policy(
    provider: VertexJsonClient,
    planner_spec: dict[str, Any],
    rooms: list[dict[str, Any]],
    role_groups: list[dict[str, Any]],
    main_characters: list[dict[str, Any]],
    items: list[dict[str, Any]],
    repair_note: str = "",
) -> dict[str, Any]:
    world_context = {
        "world_name": planner_spec.get("world_name", ""),
        "world_id": planner_spec.get("world_id", ""),
        "genre": planner_spec.get("genre", ""),
        "premise": planner_spec.get("premise", ""),
        "economy_focus": planner_spec.get("economy_focus", ""),
        "exploration_focus": planner_spec.get("exploration_focus", ""),
        "visual_style": planner_spec.get("visual_style", ""),
        "visual_canon": planner_spec.get("visual_canon", {}),
        "conflict_tone": planner_spec.get("conflict_tone", ""),
        "rooms": _compact_rooms(rooms),
        "roles_and_characters": _compact_roles(role_groups, main_characters),
        "representative_items": [
            {
                "item_id": str(item.get("item_id", "")),
                "name": str(item.get("name", "")),
                "description": str(item.get("description", "")),
            }
            for item in items[:24]
            if isinstance(item, dict)
        ],
    }

    prompt = f"""
You are the Agent Wardrobe Policy node for Agora world generation.

Your job is to produce a compact visual policy that later sprite-generation prompts will consume.
Do not create individual images. Do not describe map art. Create wardrobe rules only.

The policy must be specific to THIS world, not a generic default. It must prevent unrelated aesthetics from leaking in.
If this is a space station, use pressure suits, utility jumpsuits, station badges, salvage rigs, medical/lab gear, and other fitting attire.
If this is an antique market, use antique-market attire. If it is not an antique market, forbid antique-market clothing.

Return:
- a world_wardrobe_brief
- forbidden_aesthetics that should never appear unless explicitly requested by this world
- 3 to 10 palette_families
- 3 to 20 role_style_rules keyed by role_keywords
- a default_rule for roles that do not match a specific rule
- concise visual_consistency_rules for 64x64 sprite readability

World context JSON:
{world_context}
"""
    if repair_note:
        prompt += f"\nRepair note:\n{repair_note}\n"

    policy = _execute_json_prompt(
        provider=provider,
        system_instruction=(
            "You are a world-specific wardrobe policy agent. "
            "Output only JSON matching the schema. The output is a contract for later art generation."
        ),
        prompt=prompt,
        response_schema=_wardrobe_policy_schema(),
        temperature=0.35,
        max_output_tokens=4096,
        thinking_level="low",
        thinking_budget=128,
        stage="agent_wardrobe_policy_generation",
    )
    normalized = _normalize_policy(policy, planner_spec)
    if not normalized["world_wardrobe_brief"]:
        raise ValueError("Wardrobe policy node failed: empty world_wardrobe_brief.")
    return normalized
