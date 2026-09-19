#!/usr/bin/env python3
"""Evaluate one-sentence Agora artifacts for LivingWorldBench."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agora_social_dynamics_analysis import analyze as analyze_story


BENCHMARK_VERSION = "livingworldbench.artifact.v0.2"
PERCEPTUAL_DIMENSIONS = (
    "premise_specificity",
    "composition",
    "readability",
    "cross_modal_coherence",
    "character_appeal",
)
PLAYABLE_PROBE_IDS = (
    "human_entry",
    "connected_space_movement",
    "world_pressure_message",
    "world_specific_inspection",
    "owned_item_persistent_use",
    "asymmetric_trade",
    "absent_catalog_request",
    "revision_after_rejection",
    "bounded_object_creation",
    "persistent_reentry",
)
BUILD_AXIS_WEIGHTS = {
    "sentence_realization": 0.15,
    "spatial_and_material_coherence": 0.12,
    "visual_world_quality": 0.18,
    "agent_society_design": 0.15,
    "interaction_and_open_agency": 0.22,
    "executable_human_playability": 0.18,
}
PROHIBITED_ITEM_IDS = {"task_ledger", "meeting_notice", "tea_coupon"}
STOPWORDS = {
    "about", "after", "and", "are", "become", "build", "controlled", "each",
    "every", "from", "have", "inside", "into", "must", "one", "that", "their",
    "through", "while", "with", "world", "sentence", "players", "player",
}
GENERIC_ACTIONS = {
    "chat", "inspect", "coordinate", "trade", "move", "interact", "document",
    "act together", "cinematicinteraction",
}
RELATION_MARKERS = {
    "alliance", "blackmail", "contract", "depend", "dispute", "favor", "mentor",
    "negotiate", "owe", "protect", "rival", "smuggle", "supplier", "trust",
}
CREATION_MARKERS = {
    "assemble", "build", "compose", "craft", "create", "fabricate", "forge",
    "grow", "mint", "record", "repair", "weave", "write",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _mean(values: Iterable[float], default: float = 0.0) -> float:
    rows = list(values)
    return statistics.fmean(rows) if rows else default


def _ratio(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return _text(value)


def _words(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9'-]{2,}", _text(value).lower())
        if token not in STOPWORDS
    }


def _first_sentence(text: str) -> str:
    cleaned = " ".join(str(text).split())
    match = re.match(r"^(.+?[.!?])(?:\s|$)", cleaned)
    return match.group(1).strip() if match else cleaned


def _largest_component(room_ids: set[str], edges: set[tuple[str, str]]) -> int:
    graph: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        graph[source].add(target)
        graph[target].add(source)
    remaining = set(room_ids)
    largest = 0
    while remaining:
        stack = [remaining.pop()]
        size = 0
        while stack:
            node = stack.pop()
            size += 1
            unseen = graph[node] & remaining
            remaining.difference_update(unseen)
            stack.extend(unseen)
        largest = max(largest, size)
    return largest


def _normalized_entropy(values: list[str]) -> float:
    counts = Counter(value for value in values if value)
    total = sum(counts.values())
    if total <= 1 or len(counts) <= 1:
        return 0.0
    entropy = -sum((count / total) * math.log(count / total) for count in counts.values())
    return _clip(entropy / math.log(len(counts)))


def _geometric_score(axes: dict[str, float], weights: dict[str, float]) -> float:
    return 100.0 * math.exp(
        sum(
            weight * math.log(max(0.01, float(axes.get(axis, 0.0)) / 100.0))
            for axis, weight in weights.items()
        )
    )


def _resolve_evidence_path(root: Path, value: Any) -> Path | None:
    path_value = _text(value)
    if not path_value:
        return None
    path = Path(path_value)
    return path if path.is_absolute() else root / path


def _perceptual_visual_evidence(root: Path, entry: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    path = _resolve_evidence_path(root, entry.get("perceptual_visual_path"))
    payload = _read_json(path) if path and path.is_file() else {}
    ratings = [item for item in _safe_list(payload.get("ratings")) if isinstance(item, dict)]
    valid_rows = []
    for rating in ratings:
        scores = _safe_dict(rating.get("scores")) or rating
        values = []
        for dimension in PERCEPTUAL_DIMENSIONS:
            value = scores.get(dimension)
            if not isinstance(value, (int, float)) or not 1 <= float(value) <= 5:
                values = []
                break
            values.append(float(value))
        if values:
            valid_rows.append(values)
    dimension_means = {
        dimension: round(_mean(row[index] for row in valid_rows), 3)
        for index, dimension in enumerate(PERCEPTUAL_DIMENSIONS)
    } if valid_rows else {}
    score = 25.0 * (_mean(dimension_means.values()) - 1.0) if dimension_means else None
    qualified = len(valid_rows) >= 3 and bool(payload.get("blinded"))
    return (score if qualified else None), {
        "path": str(path) if path else "",
        "blinded": bool(payload.get("blinded")),
        "valid_rater_count": len(valid_rows),
        "minimum_rater_count": 3,
        "dimension_means_1_to_5": dimension_means,
        "qualified": qualified,
        "score": round(score, 2) if score is not None else None,
    }


def _playable_probe_evidence(root: Path, entry: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    path = _resolve_evidence_path(root, entry.get("playable_probe_path"))
    payload = _read_json(path) if path and path.is_file() else {}
    rows = [item for item in _safe_list(payload.get("probes")) if isinstance(item, dict)]
    statuses = {
        _text(item.get("probe_id")): _text(item.get("status")).lower()
        for item in rows
        if _text(item.get("probe_id")) in PLAYABLE_PROBE_IDS
    }
    passed = {probe_id for probe_id, status in statuses.items() if status == "pass"}
    complete = set(PLAYABLE_PROBE_IDS).issubset(statuses)
    score = 100.0 * _ratio(len(passed), len(PLAYABLE_PROBE_IDS)) if complete else None
    qualified = complete and len(passed) == len(PLAYABLE_PROBE_IDS)
    return score, {
        "path": str(path) if path else "",
        "required_probe_ids": list(PLAYABLE_PROBE_IDS),
        "reported_probe_ids": sorted(statuses),
        "passed_probe_ids": sorted(passed),
        "complete": complete,
        "qualified": qualified,
        "score": round(score, 2) if score is not None else None,
    }


def _asset_evidence(root: Path, draft_id: str, revision_id: str, config: dict[str, Any]) -> dict[str, Any]:
    asset_root = root / "frontend" / "assets" / "generated" / "world_asset_sets" / f"{draft_id}_{revision_id}"
    component_manifest = _read_json(asset_root / "component_generation" / "component_generation_manifest.json")
    sidecar = _read_json(asset_root / "world_map_source.components.json")
    sprite_qa = _read_json(asset_root / "sprite_batch_vision_qa.json")
    expected_ids = {
        _text(component.get("component_id"))
        for room in _safe_list(_safe_dict(config.get("space")).get("rooms"))
        if isinstance(room, dict)
        for component in _safe_list(_safe_dict(room.get("visual")).get("scene_components"))
        if isinstance(component, dict) and _text(component.get("component_id"))
    }
    generated_ids = {
        _text(job.get("component_id"))
        for job in _safe_list(component_manifest.get("jobs"))
        if isinstance(job, dict)
        and job.get("semantic_generated") is True
        and job.get("status") == "ok"
        and _text(job.get("component_id"))
    }
    placements = [item for item in _safe_list(sidecar.get("placements")) if isinstance(item, dict)]
    placed_ids = {
        _text(item.get("component_id"))
        for item in placements
        if item.get("semantic_generated") is True and _text(item.get("component_id"))
    }
    readable_ids = {
        _text(item.get("component_id"))
        for item in placements
        if item.get("semantic_generated") is True
        and item.get("readability_pass") is True
        and _text(item.get("component_id"))
    }
    sprite_rows = [item for item in _safe_list(sprite_qa.get("agents")) if isinstance(item, dict)]
    return {
        "asset_root": str(asset_root),
        "expected_component_count": len(expected_ids),
        "generated_component_rate": _ratio(len(expected_ids & generated_ids), len(expected_ids)),
        "placement_sidecar_present": bool(sidecar),
        "placed_component_rate": _ratio(len(expected_ids & placed_ids), len(expected_ids)),
        "readable_component_rate": _ratio(len(expected_ids & readable_ids), len(expected_ids)),
        "sprite_qa_rate": _ratio(sum(item.get("pass_qa") is True for item in sprite_rows), len(config.get("main_characters", []))),
        "sprite_qa_overall": bool(sprite_qa.get("status") == "ok" and sprite_qa.get("overall_pass") is True),
    }


def _sentence_axis(premise: str, config: dict[str, Any], builder: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    premise_terms = _words(premise)
    actions = _safe_dict(config.get("actions"))
    branches = {
        "space": _flatten(_safe_dict(config.get("space")).get("rooms")),
        "agents": _flatten(config.get("main_characters")),
        "materials": _flatten([config.get("economy"), builder.get("item_catalog")]),
        "interactions": _flatten([actions, config.get("world_rules"), builder.get("gameplay_loops")]),
        "visuals": _flatten([config.get("pixel_asset_pipeline"), builder.get("visual_canon"), builder.get("agent_visual_policy")]),
    }
    recalls = {
        name: _ratio(len(_words(text) & premise_terms), len(premise_terms))
        for name, text in branches.items()
    }
    normalized_recall = _mean(min(value / 0.30, 1.0) for value in recalls.values())
    rooms = _safe_list(_safe_dict(config.get("space")).get("rooms"))
    agents = _safe_list(config.get("main_characters"))
    custom = _safe_list(actions.get("allowed_custom_actions"))
    loops = _safe_list(builder.get("gameplay_loops"))
    expansion = _mean([
        _clip(len(rooms) / 6),
        _clip(len(agents) / 12),
        _clip(len(custom) / 8),
        _clip(len(loops) / 2),
    ])
    score = 100.0 * (0.72 * normalized_recall + 0.28 * expansion)
    return score, {"premise_terms": sorted(premise_terms), "branch_recall": recalls, "expansion": expansion}


def _spatial_axis(config: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    rooms = [item for item in _safe_list(_safe_dict(config.get("space")).get("rooms")) if isinstance(item, dict)]
    room_ids = {_text(room.get("room_id")) for room in rooms if _text(room.get("room_id"))}
    edges = {
        tuple(sorted((_text(room.get("room_id")), _text(door.get("connects_to_room_id")))))
        for room in rooms
        for door in _safe_list(room.get("doorways"))
        if isinstance(door, dict)
        and _text(room.get("room_id")) in room_ids
        and _text(door.get("connects_to_room_id")) in room_ids
    }
    agents = [item for item in _safe_list(config.get("main_characters")) if isinstance(item, dict)]
    homes = [_text(agent.get("home_room_id")) for agent in agents]
    component_rooms = sum(bool(_safe_list(_safe_dict(room.get("visual")).get("scene_components"))) for room in rooms)
    observations = {
        "room_count": len(rooms),
        "connected_room_fraction": _ratio(_largest_component(room_ids, edges), len(room_ids)),
        "home_room_valid_rate": _ratio(sum(home in room_ids for home in homes), len(homes)),
        "occupied_room_fraction": _ratio(len(set(homes) & room_ids), len(room_ids)),
        "room_assignment_entropy": _normalized_entropy([home for home in homes if home in room_ids]),
        "semantic_component_room_fraction": _ratio(component_rooms, len(rooms)),
    }
    score = 100.0 * _mean([
        _clip(len(rooms) / 6),
        observations["connected_room_fraction"],
        observations["home_room_valid_rate"],
        observations["occupied_room_fraction"],
        observations["room_assignment_entropy"],
        observations["semantic_component_room_fraction"],
    ])
    return score, observations


def _society_axis(config: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    agents = [item for item in _safe_list(config.get("main_characters")) if isinstance(item, dict)]
    roles = [_text(agent.get("role_id") or agent.get("role_name")) for agent in agents]
    inventory = [item for agent in agents for item in _safe_list(agent.get("inventory")) if isinstance(item, dict)]
    inventory_names = [_text(item.get("item_id") or item.get("name")).lower() for item in inventory]
    relation_hits = sum(bool(_words(_flatten(agent)) & RELATION_MARKERS) for agent in agents)
    observations = {
        "agent_count": len(agents),
        "unique_role_rate": _ratio(len(set(roles)), len(roles)),
        "private_state_rate": _ratio(sum(bool(_text(agent.get("private_notes"))) for agent in agents), len(agents)),
        "knowledge_asset_rate": _ratio(sum(bool(_safe_list(agent.get("knowledge_assets"))) for agent in agents), len(agents)),
        "material_inventory_rate": _ratio(sum(len(_safe_list(agent.get("inventory"))) >= 5 for agent in agents), len(agents)),
        "relational_agent_rate": _ratio(relation_hits, len(agents)),
        "inventory_unique_rate": _ratio(len(set(inventory_names)), len(inventory_names)),
        "prohibited_inventory_count": sum(name in PROHIBITED_ITEM_IDS for name in inventory_names),
    }
    score = 100.0 * _mean([
        _clip(len(agents) / 12),
        observations["unique_role_rate"],
        observations["private_state_rate"],
        observations["knowledge_asset_rate"],
        observations["material_inventory_rate"],
        observations["relational_agent_rate"],
        observations["inventory_unique_rate"],
        float(observations["prohibited_inventory_count"] == 0),
    ])
    return score, observations


def _interaction_axis(config: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    actions = _safe_dict(config.get("actions"))
    custom = _safe_list(actions.get("allowed_custom_actions"))
    ordinary = [item for item in _safe_list(actions.get("ordinary_routes")) if isinstance(item, dict)]
    cinematic = [item for item in _safe_list(actions.get("cinematic_routes")) if isinstance(item, dict)]
    catalog = [item for item in _safe_list(actions.get("interaction_affordance_catalog")) if isinstance(item, dict)]
    route_rows = ordinary + cinematic
    families = {
        _text(item.get("interaction_family") or item.get("kind"))
        for item in (catalog or route_rows)
        if _text(item.get("interaction_family") or item.get("kind"))
    }
    labels = [
        _text(item.get("label") or item.get("action") or item.get("route_id")).lower()
        for item in catalog
    ] or [_text(item).lower() if not isinstance(item, dict) else _text(item.get("action") or item.get("route_id")).lower() for item in custom]
    world_specific = sum(label and label not in GENERIC_ACTIONS for label in labels)
    persistent_rate = _ratio(
        sum(bool(item.get("persistent_effects") or item.get("status_effect") or item.get("kind") == "item_trade") for item in (catalog or route_rows)),
        len(catalog or route_rows),
    )
    freeform = any(item.get("freeform_required") is True or item.get("model_selected_action") is True for item in cinematic)
    custom_rules = _safe_dict(_safe_dict(config.get("world_rules")).get("custom_action_rules"))
    routing_policy = _safe_dict(actions.get("routing_policy"))
    open_proposals = bool(custom_rules.get("open_proposals_enabled")) or "__propose__" in _flatten(routing_policy)
    creation = bool(_words(" ".join(labels)) & CREATION_MARKERS)
    human_enabled = bool(_safe_dict(config.get("human_interaction")).get("enabled"))
    shared_contract_rate = _ratio(
        sum({"human", "ai"}.issubset(set(_safe_list(item.get("actor_modes")))) for item in catalog),
        len(catalog),
    ) if catalog else 0.0
    trade_present = any(item.get("kind") == "item_trade" or "trade" in _text(item.get("route_id")).lower() for item in route_rows)
    observations = {
        "custom_action_count": len(custom),
        "route_count": len(route_rows),
        "interaction_family_count": len(families),
        "world_specific_action_count": world_specific,
        "persistent_effect_rate": persistent_rate,
        "trade_present": trade_present,
        "creation_action_present": creation,
        "freeform_intent_present": freeform,
        "coordinator_open_proposals": open_proposals,
        "human_interaction_enabled": human_enabled,
        "shared_human_ai_contract_rate": shared_contract_rate,
    }
    score = 100.0 * (
        0.10 * _clip(len(custom) / 8)
        + 0.08 * _clip(len(route_rows) / 8)
        + 0.08 * _clip(len(families) / 4)
        + 0.08 * _clip(world_specific / 6)
        + 0.10 * persistent_rate
        + 0.07 * float(trade_present)
        + 0.09 * float(creation)
        + 0.10 * float(freeform)
        + 0.15 * float(open_proposals)
        + 0.10 * float(human_enabled)
        + 0.05 * shared_contract_rate
    )
    return score, observations


def _visual_axis(
    config: dict[str, Any],
    art: dict[str, Any],
    assets: dict[str, Any],
    fallback_count: int,
    perceptual_score: float | None = None,
) -> tuple[float, dict[str, Any]]:
    map_qa = _safe_dict(art.get("map_vision_qa"))
    observations = {
        "visual_canon_present": bool(_safe_dict(_safe_dict(config.get("pixel_asset_pipeline")).get("visual_canon"))),
        "semantic_component_generation_rate": assets["generated_component_rate"],
        "semantic_component_readability_rate": (
            assets["readable_component_rate"]
            if assets["placement_sidecar_present"]
            else 0.5 * assets["generated_component_rate"]
        ),
        "sprite_qa_rate": assets["sprite_qa_rate"],
        "sprite_qa_overall": assets["sprite_qa_overall"],
        "map_qa_pass": bool(map_qa.get("is_pixel_map") == "Y" and map_qa.get("has_visual_errors") == "N"),
        "zero_prohibited_inventory": fallback_count == 0,
    }
    technical_score = 100.0 * _mean([
        float(observations["visual_canon_present"]),
        observations["semantic_component_generation_rate"],
        observations["semantic_component_readability_rate"],
        observations["sprite_qa_rate"],
        float(observations["sprite_qa_overall"]),
        float(observations["map_qa_pass"]),
        float(observations["zero_prohibited_inventory"]),
    ])
    score = (
        0.40 * technical_score + 0.60 * perceptual_score
        if perceptual_score is not None
        else technical_score
    )
    observations.update({
        "technical_score": round(technical_score, 2),
        "perceptual_score": round(perceptual_score, 2) if perceptual_score is not None else None,
        "score_mode": "technical_plus_blind_perceptual" if perceptual_score is not None else "technical_calibration_only",
    })
    return score, observations


def _playability_axis(
    revision_dir: Path,
    config: dict[str, Any],
    compiler: dict[str, Any],
    art: dict[str, Any],
    probe_score: float | None = None,
) -> tuple[float, dict[str, Any]]:
    pixel = _safe_dict(art.get("pixel_launch_validation"))
    observations = {
        "compiler_pass": compiler.get("status") == "ok",
        "package_db_present": (revision_dir / "world_package.db").is_file(),
        "pixel_read_pass": _safe_dict(art.get("qa_summary")).get("pixel_read") is True,
        "backend_startup_pass": _safe_dict(art.get("backend_startup_validation")).get("startup_ok") is True,
        "headless_pixel_launch_pass": pixel.get("startup_ok") is True,
        "publish_gate_pass": _text(art.get("status")) == "publish_ready",
        "movement_contract_present": bool(_safe_dict(_safe_dict(config.get("space")).get("movement"))),
        "human_entry_present": bool(_safe_list(_safe_dict(config.get("scenario_meta")).get("player_entry_points"))),
    }
    technical_score = 100.0 * _mean(float(value) for value in observations.values())
    score = 0.40 * technical_score + 0.60 * probe_score if probe_score is not None else technical_score
    observations.update({
        "technical_score": round(technical_score, 2),
        "probe_score": round(probe_score, 2) if probe_score is not None else None,
        "score_mode": "technical_plus_black_box_probes" if probe_score is not None else "technical_calibration_only",
    })
    return score, observations


def _runtime_axis(story_path: Path, agent_count: int) -> tuple[float, dict[str, Any]]:
    metrics = analyze_story(story_path)
    rounds = max(1, int(metrics.get("rounds", 0)))
    observed = max(1, int(metrics.get("observed_agents", 0)))
    components = [
        _clip(int(metrics.get("observed_agents", 0)) / max(1, agent_count)),
        _clip(int(metrics.get("unique_dyads", 0)) / max(1, agent_count * 0.6)),
        _clip(float(metrics.get("repeated_dyad_event_fraction", 0.0)) / 0.20),
        _clip(int(metrics.get("largest_component", 0)) / observed),
        _clip(float(metrics.get("route_entropy_bits", 0.0)) / 2.0),
        _clip(int(metrics.get("open_proposal_events", 0)) / rounds),
        _clip(int(metrics.get("human_interaction_events", 0)) / max(1, rounds // 2)),
        float(metrics.get("action_success_rate", 0.0)),
        float(bool(_safe_dict(metrics.get("identity_audit")).get("passed"))),
    ]
    return 100.0 * _mean(components), metrics


def evaluate_case(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    draft_id = _text(entry.get("draft_id"))
    revision_id = _text(entry.get("revision_id")) or "r001"
    revision_dir = root / "output" / "world_creator_drafts" / draft_id / "revisions" / revision_id
    config = _read_json(revision_dir / "world_config.json")
    builder = _read_json(revision_dir / "builder_spec.json")
    compiler = _read_json(revision_dir / "compiler_report.json")
    art = _read_json(revision_dir / "art_status.json")
    brief_path = revision_dir / "input_brief.txt"
    brief = brief_path.read_text(encoding="utf-8") if brief_path.is_file() else _text(builder.get("premise"))
    premise = _first_sentence(brief)
    assets = _asset_evidence(root, draft_id, revision_id, config)

    sentence_score, sentence_obs = _sentence_axis(premise, config, builder)
    spatial_score, spatial_obs = _spatial_axis(config)
    society_score, society_obs = _society_axis(config)
    interaction_score, interaction_obs = _interaction_axis(config)
    perceptual_score, perceptual_obs = _perceptual_visual_evidence(root, entry)
    probe_score, probe_obs = _playable_probe_evidence(root, entry)
    visual_score, visual_obs = _visual_axis(
        config, art, assets, society_obs["prohibited_inventory_count"], perceptual_score
    )
    play_score, play_obs = _playability_axis(revision_dir, config, compiler, art, probe_score)
    axes = {
        "sentence_realization": round(sentence_score, 2),
        "spatial_and_material_coherence": round(spatial_score, 2),
        "visual_world_quality": round(visual_score, 2),
        "agent_society_design": round(society_score, 2),
        "interaction_and_open_agency": round(interaction_score, 2),
        "executable_human_playability": round(play_score, 2),
    }
    uncapped = _geometric_score(axes, BUILD_AXIS_WEIGHTS)
    cap = 100.0
    cap_reasons = []
    if not play_obs["compiler_pass"]:
        cap, cap_reasons = min(cap, 39.0), cap_reasons + ["compiler did not pass"]
    if not play_obs["package_db_present"] or not play_obs["headless_pixel_launch_pass"]:
        cap, cap_reasons = min(cap, 49.0), cap_reasons + ["world did not reach a real playable package and browser launch"]
    if not visual_obs["sprite_qa_overall"] or not visual_obs["map_qa_pass"]:
        cap, cap_reasons = min(cap, 59.0), cap_reasons + ["strict map or sprite visual gate did not pass"]
    if not interaction_obs["human_interaction_enabled"] or not (
        interaction_obs["coordinator_open_proposals"] or interaction_obs["freeform_intent_present"]
    ):
        cap, cap_reasons = min(cap, 59.0), cap_reasons + ["human entry or open intention surface is absent"]
    if society_obs["prohibited_inventory_count"]:
        cap, cap_reasons = min(cap, 49.0), cap_reasons + ["prohibited generic inventory is present"]
    build_score = min(uncapped, cap)

    level_a = bool(play_obs["compiler_pass"] and config)
    level_b = bool(
        level_a
        and build_score >= 60.0
        and play_obs["headless_pixel_launch_pass"]
        and interaction_obs["human_interaction_enabled"]
        and interaction_obs["coordinator_open_proposals"]
        and probe_obs["qualified"]
        and perceptual_obs["qualified"]
        and perceptual_score is not None
        and perceptual_score >= 50.0
    )

    runtime_score = None
    runtime_metrics = None
    story_path_value = _text(entry.get("story_path"))
    if story_path_value:
        story_path = Path(story_path_value)
        if not story_path.is_absolute():
            story_path = root / story_path
        if story_path.is_file():
            runtime_score, runtime_metrics = _runtime_axis(story_path, int(society_obs["agent_count"]))
    runtime_qualified = bool(
        runtime_metrics
        and int(runtime_metrics.get("rounds", 0)) >= 24
        and int(runtime_metrics.get("open_proposal_events", 0)) >= 1
        and int(runtime_metrics.get("human_interaction_events", 0)) >= 1
        and bool(_safe_dict(runtime_metrics.get("identity_audit")).get("passed"))
    )
    level_c = bool(level_b and runtime_score is not None and runtime_qualified)
    living_score = (
        100.0 * ((max(build_score, 0.01) / 100.0) ** 0.70) * ((max(runtime_score, 0.01) / 100.0) ** 0.30)
        if level_c
        else None
    )
    return {
        "case_id": _text(entry.get("case_id")) or draft_id,
        "draft_id": draft_id,
        "revision_id": revision_id,
        "world_name": _text(_safe_dict(config.get("scenario_meta")).get("world_name")),
        "input_sentence": premise,
        "generated_world_score": round(build_score, 2),
        "uncapped_generated_world_score": round(uncapped, 2),
        "score_cap": cap,
        "cap_reasons": cap_reasons,
        "runtime_society_score": round(runtime_score, 2) if runtime_score is not None else None,
        "living_world_score": round(living_score, 2) if living_score is not None else None,
        "qualification": {
            "level_a_generated_world": level_a,
            "level_b_playable_world": level_b,
            "level_c_living_world": level_c,
            "runtime_trajectory_qualified": runtime_qualified,
        },
        "axes": axes,
        "evidence": {
            "sentence": sentence_obs,
            "space": spatial_obs,
            "visual": visual_obs,
            "society": society_obs,
            "interaction": interaction_obs,
            "playability": play_obs,
            "runtime": runtime_metrics,
            "assets": assets,
            "perceptual_visual": perceptual_obs,
            "playable_probes": probe_obs,
        },
        "paths": {"revision_dir": str(revision_dir), "story": story_path_value},
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# LivingWorldBench Artifact Evaluation",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "| World | Generated | Sentence | Space | Visual | Society | Interaction | Artifact exec. | Living |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in payload["cases"]:
        living = "n/a" if case["living_world_score"] is None else f"{case['living_world_score']:.2f}"
        axes = case["axes"]
        lines.append(
            f"| {case['world_name']} | **{case['generated_world_score']:.2f}** | "
            f"{axes['sentence_realization']:.2f} | {axes['spatial_and_material_coherence']:.2f} | "
            f"{axes['visual_world_quality']:.2f} | {axes['agent_society_design']:.2f} | "
            f"{axes['interaction_and_open_agency']:.2f} | {axes['executable_human_playability']:.2f} | {living} |"
        )
    summary = payload["summary"]
    lines.extend([
        "",
        "## Summary",
        "",
        f"- Worlds: {summary['world_count']}",
        f"- Mean Generated World Score: {summary['generated_world_score_mean']:.2f}",
        f"- Browser-playable artifacts: {summary['browser_playable_count']}/{summary['world_count']}",
        f"- Level B qualified playable worlds: {summary['level_b_count']}/{summary['world_count']}",
        f"- Coordinator-level open proposals: {summary['open_proposal_world_count']}/{summary['world_count']}",
        f"- Runtime-qualified Living World Scores: {summary['living_world_score_count']}/{summary['world_count']}",
        "",
        "A missing Living score means no benchmark story trajectory was attached. It is not scored as zero.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    manifest = _read_json(args.manifest.resolve())
    cases = [evaluate_case(root, entry) for entry in _safe_list(manifest.get("cases")) if isinstance(entry, dict)]
    living_scores = [case["living_world_score"] for case in cases if case["living_world_score"] is not None]
    payload = {
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(args.manifest.resolve()),
        "manifest_note": manifest.get("note", ""),
        "protocol": {
            "input": "one generator-visible sentence",
            "primary_grader": "deterministic artifact/runtime evidence plus blinded player-view visual ratings",
            "generated_world_score": "weighted geometric mean of six generation/playability axes with hard gates",
            "living_world_score": "GeneratedWorld^0.70 * RuntimeSociety^0.30",
            "efficiency": "reported separately from world quality",
        },
        "summary": {
            "world_count": len(cases),
            "generated_world_score_mean": round(_mean(case["generated_world_score"] for case in cases), 2),
            "browser_playable_count": sum(case["evidence"]["playability"]["headless_pixel_launch_pass"] for case in cases),
            "level_b_count": sum(case["qualification"]["level_b_playable_world"] for case in cases),
            "open_proposal_world_count": sum(case["evidence"]["interaction"]["coordinator_open_proposals"] for case in cases),
            "living_world_score_count": len(living_scores),
            "living_world_score_mean": round(_mean(living_scores), 2) if living_scores else None,
        },
        "cases": cases,
    }
    output_json = args.output_json if args.output_json.is_absolute() else root / args.output_json
    output_md = args.output_md if args.output_md.is_absolute() else root / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
