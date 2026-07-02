from __future__ import annotations
import json
import time
import traceback
from typing import Any
from agora_ui.vertex_json_client import VertexJsonClient
from .generation_schemas import _world_config_critique_schema
from .generation_prompts import _world_config_critique_prompt
from .io_utils import _dedupe_texts, _first_non_empty, _clone_json

def _focus_profile(request: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(
        [
            str(request.get("focus", "")),
            str(request.get("genre", "")),
            str(request.get("brief", "")),
            str(spec.get("premise", "")),
            str(spec.get("economy_focus", "")),
            str(spec.get("exploration_focus", "")),
            str(spec.get("conflict_tone", "")),
        ]
    ).lower()
    keyword_map = {
        "economy": ["economy", "trade", "market", "supply", "merchant", "contract", "logistics", "resource", "commerce", "broker"],
        "exploration": ["explore", "exploration", "scout", "ruin", "mystery", "map", "route", "discover", "investigate", "frontier"],
        "story": ["story", "narrative", "drama", "character", "politic", "faction", "quest", "arc", "plot", "intrigue"],
        "conflict": ["conflict", "danger", "war", "rival", "tension", "suspicion", "smuggle", "threat", "crisis", "hazard"],
        "craft": ["craft", "repair", "forge", "build", "maker", "workshop", "engineer", "artifact"],
    }
    scores = {label: sum(1 for keyword in keywords if keyword in text) for label, keywords in keyword_map.items()}
    primary_focus = max(scores, key=lambda label: (scores[label], label))
    return {
        "scores": scores,
        "primary_focus": primary_focus,
        "economy": scores["economy"] > 0 or primary_focus == "economy",
        "exploration": scores["exploration"] > 0 or primary_focus == "exploration",
        "story": scores["story"] > 0 or primary_focus == "story",
        "conflict": scores["conflict"] > 0,
        "craft": scores["craft"] > 0,
    }


def _synthesized_gameplay_loops(
    *,
    request: dict[str, Any],
    rooms: list[dict[str, Any]],
    role_groups: list[dict[str, Any]],
    item_themes: list[str],
    focus_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    room_names = [str(entry.get("name", "")).strip() for entry in rooms if str(entry.get("name", "")).strip()]
    role_names = [str(entry.get("role_name", "")).strip() for entry in role_groups if str(entry.get("role_name", "")).strip()]
    loops: list[dict[str, Any]] = []
    if focus_profile.get("economy"):
        loops.append(
            {
                "label": "Exchange Loop",
                "summary": (
                    f"Agents circulate {', '.join(item_themes[:2]) or 'resources'} through bargains, assignments, and price pressure "
                    "so every agreement creates a follow-up obligation."
                ),
                "roles": role_names[:3],
                "rooms": room_names[:2],
                "pressure": "supply bottlenecks and shifting leverage",
            }
        )
    if focus_profile.get("exploration"):
        loops.append(
            {
                "label": "Discovery Loop",
                "summary": (
                    "Agents bring back route knowledge, rumors, and partial findings, then trade that information "
                    "for access, safety, or support."
                ),
                "roles": role_names[1:4] or role_names[:2],
                "rooms": room_names[1:4] or room_names[:2],
                "pressure": "uncertain information and contested interpretation",
            }
        )
    loops.append(
        {
            "label": "Coordination Loop",
            "summary": (
                "Visible coordination turns scattered opportunities into concrete next steps, pairing the right people, rooms, and items."
            ),
            "roles": role_names[: max(2, min(4, len(role_names)))],
            "rooms": room_names[: max(2, min(3, len(room_names)))],
            "pressure": "social friction and unfinished commitments",
        }
    )
    if focus_profile.get("conflict") or focus_profile.get("story"):
        loops.append(
            {
                "label": "Tension Loop",
                "summary": (
                    "Rival priorities create suspicion, negotiation, and reversals, but the pressure should always return as a playable choice."
                ),
                "roles": role_names[-3:] or role_names[:2],
                "rooms": room_names[-2:] or room_names[:2],
                "pressure": "faction distrust and contested decisions",
            }
        )
    return loops[:4]




def _fallback_conflict_hooks(builder_spec: dict[str, Any], focus_profile: dict[str, Any]) -> list[str]:
    base_hooks = [
        "Two groups want the same scarce opportunity but for incompatible reasons.",
        "Information is valuable enough that agents may delay, distort, or barter it.",
    ]
    if focus_profile.get("conflict"):
        base_hooks.append("A recent disruption has made routine coordination feel politically charged.")
    if focus_profile.get("exploration"):
        base_hooks.append("New territory or new evidence keeps reopening old assumptions.")
    return base_hooks[:4]


def _fallback_custom_actions(focus_profile: dict[str, Any]) -> list[str]:
    actions = ["Chat", "Inspect", "Coordinate", "Trade", "Move", "CinematicInteraction"]
    if focus_profile.get("economy"):
        actions.extend(["Negotiate", "Broker"])
    if focus_profile.get("exploration"):
        actions.extend(["ScoutReport", "Research"])
    if focus_profile.get("conflict") or focus_profile.get("story"):
        actions.extend(["Mediate", "Debate", "Warn"])
    if focus_profile.get("craft"):
        actions.extend(["Repair", "Build"])
    return _dedupe_texts(actions, limit=12)


def _config_snapshot_for_critique(config: dict[str, Any]) -> dict[str, Any]:
    from .builder import _structured_summary
    rooms = [dict(entry) for entry in config.get("space", {}).get("rooms", []) if isinstance(entry, dict)]
    role_groups = [dict(entry) for entry in config.get("agent_generation", {}).get("role_groups", []) if isinstance(entry, dict)]
    main_characters = [dict(entry) for entry in config.get("main_characters", []) if isinstance(entry, dict)]
    ordinary_routes = [dict(entry) for entry in config.get("actions", {}).get("ordinary_routes", []) if isinstance(entry, dict)]
    cinematic_routes = [dict(entry) for entry in config.get("actions", {}).get("cinematic_routes", []) if isinstance(entry, dict)]
    return {
        "scenario_meta": dict(config.get("scenario_meta", {})),
        "runner": dict(config.get("runner", {})),
        "runtime": dict(config.get("runtime", {})),
        "structured_summary": _structured_summary(config),
        "rooms": [
            {
                "room_id": str(entry.get("room_id", "")),
                "name": str(entry.get("name", "")),
                "purpose": str(dict(entry.get("metadata", {})).get("purpose", "")) if isinstance(entry.get("metadata", {}), dict) else "",
                "activity_tags": list(dict(entry.get("metadata", {})).get("activity_tags", []))[:20] if isinstance(entry.get("metadata", {}), dict) else [],
            }
            for entry in rooms[:60]
        ],
        "role_groups": [
            {
                "role_id": str(entry.get("role_id", "")),
                "role_name": str(entry.get("role_name", "")),
                "home_room_id": str(entry.get("home_room_id", "")),
                "activity_directive": str(entry.get("activity_directive", "")),
            }
            for entry in role_groups[:60]
        ],
        "main_characters": [
            {
                "agent_id": str(entry.get("agent_id", "")),
                "display_name": str(entry.get("display_name", "")),
                "home_room_id": str(entry.get("home_room_id", "")),
                "activity_directive": str(entry.get("activity_directive", "")),
            }
            for entry in main_characters[:80]
        ],
        "actions": {
            "allowed_custom_actions": [str(item) for item in config.get("actions", {}).get("allowed_custom_actions", [])[:40]],
            "ordinary_routes": [
                {
                    "route_id": str(entry.get("route_id", "")),
                    "kind": str(entry.get("kind", "")),
                    "action": str(entry.get("action", "")),
                    "actor_role_ids": [str(item) for item in entry.get("actor_role_ids", [])[:10]],
                }
                for entry in ordinary_routes[:50]
            ],
            "cinematic_route_count": len(cinematic_routes),
        },
        "extra_world_functions": dict(config.get("extra_world_functions", {})),
        "world_progress": dict(config.get("world_progress", {})),
    }


def _normalized_critique_dict(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw = payload if isinstance(payload, dict) else {}
    critique = {
        "should_repair": bool(raw.get("should_repair", False)),
        "diagnosis": _dedupe_texts(raw.get("diagnosis", []), limit=8),
        "custom_actions": _dedupe_texts(raw.get("custom_actions", []), limit=12),
        "player_entry_points": _dedupe_texts(raw.get("player_entry_points", []), limit=4),
        "conflict_hooks": _dedupe_texts(raw.get("conflict_hooks", []), limit=4),
        "social_rules": _dedupe_texts(raw.get("social_rules", []), limit=6),
        "loop_reinforcements": [],
        "room_adjustments": [],
        "role_adjustments": [],
        "main_character_adjustments": [],
    }
    for loop in raw.get("loop_reinforcements", []) or []:
        if not isinstance(loop, dict):
            continue
        label = _first_non_empty(loop.get("label"))
        summary = _first_non_empty(loop.get("summary"))
        if not label or not summary:
            continue
        critique["loop_reinforcements"].append(
            {
                "label": label,
                "summary": summary,
                "roles": _dedupe_texts(loop.get("roles", []), limit=4),
                "rooms": _dedupe_texts(loop.get("rooms", []), limit=4),
                "pressure": _first_non_empty(loop.get("pressure")),
            }
        )
    for room in raw.get("room_adjustments", []) or []:
        if not isinstance(room, dict):
            continue
        room_name = _first_non_empty(room.get("room_name"))
        if not room_name:
            continue
        critique["room_adjustments"].append(
            {
                "room_name": room_name,
                "purpose_hint": _first_non_empty(room.get("purpose_hint")),
                "activity_tags": _dedupe_texts(room.get("activity_tags", []), limit=5),
            }
        )
    for role in raw.get("role_adjustments", []) or []:
        if not isinstance(role, dict):
            continue
        role_name = _first_non_empty(role.get("role_name"))
        if not role_name:
            continue
        critique["role_adjustments"].append(
            {
                "role_name": role_name,
                "home_base": _first_non_empty(role.get("home_base")),
                "activity_hint": _first_non_empty(role.get("activity_hint")),
                "starting_items": _dedupe_texts(role.get("starting_items", []), limit=3),
            }
        )
    for character in raw.get("main_character_adjustments", []) or []:
        if not isinstance(character, dict):
            continue
        display_name = _first_non_empty(character.get("display_name"))
        if not display_name:
            continue
        critique["main_character_adjustments"].append(
            {
                "display_name": display_name,
                "home_base": _first_non_empty(character.get("home_base")),
                "activity_hint": _first_non_empty(character.get("activity_hint")),
                "arc_goal": _first_non_empty(character.get("arc_goal")),
            }
        )
    critique["should_repair"] = bool(
        critique["should_repair"]
        or critique["custom_actions"]
        or critique["player_entry_points"]
        or critique["conflict_hooks"]
        or critique["social_rules"]
        or critique["loop_reinforcements"]
        or critique["room_adjustments"]
        or critique["role_adjustments"]
        or critique["main_character_adjustments"]
    )
    return critique


def _critique_compiled_world_config(
    *,
    provider: VertexJsonClient,
    request: dict[str, Any],
    builder_spec: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    try:
        raw = _execute_json_prompt(
            provider=provider,
            system_instruction=(
                "You review compiled Agora worlds for playability and persistence. "
                "Return only strict JSON critique with deterministic repair suggestions."
            ),
            prompt=_world_config_critique_prompt(request, builder_spec, config),
            response_schema=_world_config_critique_schema(),
            temperature=0.1,
            max_output_tokens=3072,
            thinking_level="high",
        )
    except Exception:
        raw = {}
    return _normalized_critique_dict(raw)


def _merge_gameplay_loops(existing: list[dict[str, Any]], additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for addition in additions:
        label = str(addition.get("label", "")).strip()
        if not label or label.lower() in seen_labels:
            continue
        seen_labels.add(label.lower())
        merged.append(
            {
                "label": label,
                "summary": _first_non_empty(addition.get("summary"), default="A reinforced world loop."),
                "roles": _dedupe_texts(addition.get("roles", []), limit=4),
                "rooms": _dedupe_texts(addition.get("rooms", []), limit=4),
                "pressure": _first_non_empty(addition.get("pressure"), default="unfinished obligations"),
            }
        )
    for entry in existing:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "")).strip()
        if not label or label.lower() in seen_labels:
            continue
        seen_labels.add(label.lower())
        merged.append(dict(entry))
    return merged[:4]


def _apply_compiler_critique_to_builder_spec(
    builder_spec: dict[str, Any],
    critique: dict[str, Any],
) -> dict[str, Any]:
    if not critique.get("should_repair", False):
        return dict(builder_spec)
    updated = _clone_json(builder_spec)
    updated["custom_actions"] = _dedupe_texts(
        list(updated.get("custom_actions", [])) + list(critique.get("custom_actions", [])),
        limit=14,
    )
    updated["player_entry_points"] = _dedupe_texts(
        list(updated.get("player_entry_points", [])) + list(critique.get("player_entry_points", [])),
        limit=5,
    )
    updated["conflict_hooks"] = _dedupe_texts(
        list(updated.get("conflict_hooks", [])) + list(critique.get("conflict_hooks", [])),
        limit=5,
    )
    updated["social_rules"] = _dedupe_texts(
        list(updated.get("social_rules", [])) + list(critique.get("social_rules", [])),
        limit=10,
    )
    updated["gameplay_loops"] = _merge_gameplay_loops(
        [dict(entry) for entry in updated.get("gameplay_loops", []) if isinstance(entry, dict)],
        [dict(entry) for entry in critique.get("loop_reinforcements", []) if isinstance(entry, dict)],
    )

    rooms = [dict(entry) for entry in updated.get("rooms", []) if isinstance(entry, dict)]
    room_lookup = {str(entry.get("name", "")).strip().lower(): entry for entry in rooms if str(entry.get("name", "")).strip()}
    for adjustment in critique.get("room_adjustments", []):
        room = room_lookup.get(str(adjustment.get("room_name", "")).strip().lower())
        if room is None:
            continue
        room["activity_tags"] = _dedupe_texts(
            list(room.get("activity_tags", [])) + list(adjustment.get("activity_tags", [])),
            limit=6,
        )
        if not str(room.get("purpose", "")).strip() and str(adjustment.get("purpose_hint", "")).strip():
            room["purpose"] = str(adjustment.get("purpose_hint", "")).strip()
    updated["rooms"] = rooms

    roles = [dict(entry) for entry in updated.get("role_groups", []) if isinstance(entry, dict)]
    role_lookup = {str(entry.get("role_name", "")).strip().lower(): entry for entry in roles if str(entry.get("role_name", "")).strip()}
    for adjustment in critique.get("role_adjustments", []):
        role = role_lookup.get(str(adjustment.get("role_name", "")).strip().lower())
        if role is None:
            continue
        if not str(role.get("home_base", "")).strip() and str(adjustment.get("home_base", "")).strip():
            role["home_base"] = str(adjustment.get("home_base", "")).strip()
        if str(adjustment.get("activity_hint", "")).strip():
            base_activity = str(role.get("activity", "")).strip()
            hint = str(adjustment.get("activity_hint", "")).strip()
            if hint.lower() not in base_activity.lower():
                role["activity"] = f"{base_activity}; {hint}".strip("; ")
        role["starting_items"] = _dedupe_texts(
            list(role.get("starting_items", [])) + list(adjustment.get("starting_items", [])),
            limit=4,
        )
    updated["role_groups"] = roles

    characters = [dict(entry) for entry in updated.get("main_characters", []) if isinstance(entry, dict)]
    character_lookup = {str(entry.get("display_name", "")).strip().lower(): entry for entry in characters if str(entry.get("display_name", "")).strip()}
    for adjustment in critique.get("main_character_adjustments", []):
        character = character_lookup.get(str(adjustment.get("display_name", "")).strip().lower())
        if character is None:
            continue
        if not str(character.get("home_base", "")).strip() and str(adjustment.get("home_base", "")).strip():
            character["home_base"] = str(adjustment.get("home_base", "")).strip()
        if str(adjustment.get("activity_hint", "")).strip():
            base_activity = str(character.get("activity", "")).strip()
            hint = str(adjustment.get("activity_hint", "")).strip()
            if hint.lower() not in base_activity.lower():
                character["activity"] = f"{base_activity}; {hint}".strip("; ")
        if not str(character.get("arc_goal", "")).strip() and str(adjustment.get("arc_goal", "")).strip():
            character["arc_goal"] = str(adjustment.get("arc_goal", "")).strip()
    updated["main_characters"] = characters
    return updated

