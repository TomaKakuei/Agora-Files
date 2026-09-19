#!/usr/bin/env python3
"""Extract quality-sensitive evidence from hidden world-generation artifacts."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "docs" / "living_world_benchmark_20260825_hidden"
DEFAULT_RESULTS = EVIDENCE_ROOT / "cross_provider_comprehensive_results.json"
DEFAULT_RUNS = EVIDENCE_ROOT / "confirmatory_runs"
DEFAULT_OUTPUT = EVIDENCE_ROOT / "strict_generation_evidence_v1.json"

TOKEN_RE = re.compile(r"[a-z][a-z0-9_-]{2,}")
STOPWORDS = {
    "about", "after", "again", "against", "along", "also", "among", "and",
    "around", "before", "between", "because", "being", "from", "have", "into",
    "more", "over", "that", "their", "then", "there", "these", "they", "this",
    "through", "under", "with", "within", "world", "agent", "main", "using",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def tokens(value: Any) -> set[str]:
    return {
        token
        for token in TOKEN_RE.findall(str(value).lower())
        if token not in STOPWORDS
    }


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def target(value: float, full_at: float) -> float:
    return clamp01(value / full_at) if full_at > 0 else 0.0


def completeness(rows: list[Any], fields: Iterable[str]) -> float:
    fields = list(fields)
    if not rows or not fields:
        return 0.0
    good = 0
    total = len(rows) * len(fields)
    for row in rows:
        if not isinstance(row, dict):
            continue
        good += sum(bool(row.get(field)) for field in fields)
    return good / total


def pairwise_distinctiveness(values: Iterable[Any]) -> float:
    documents = [tokens(value) for value in values if str(value).strip()]
    if len(documents) <= 1:
        return 0.0
    similarities: list[float] = []
    for index, left in enumerate(documents):
        for right in documents[index + 1 :]:
            similarities.append(len(left & right) / max(1, len(left | right)))
    return clamp01(1.0 - mean(similarities)) if similarities else 0.0


def uniqueness(values: Iterable[Any]) -> float:
    normalized = [str(value).strip().casefold() for value in values if str(value).strip()]
    return len(set(normalized)) / max(1, len(normalized))


def cycle_fraction(state_ids: list[str], causal_links: list[dict[str, Any]]) -> float:
    graph: dict[str, set[str]] = {state_id: set() for state_id in state_ids}
    for link in causal_links:
        source = str(link.get("source_state", ""))
        target_state = str(link.get("target_state", ""))
        if source in graph and target_state in graph:
            graph[source].add(target_state)

    def reaches(start: str, goal: str) -> bool:
        stack = list(graph.get(start, ()))
        seen: set[str] = set()
        while stack:
            node = stack.pop()
            if node == goal:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(graph.get(node, ()))
        return False

    cyclic = sum(reaches(state_id, state_id) for state_id in state_ids)
    return cyclic / max(1, len(state_ids))


def find_builder_spec(runs_root: Path, model: str, prompt_id: str) -> Path | None:
    model_slug = re.sub(r"[^a-z0-9]+", "_", model.casefold()).strip("_")
    directory = runs_root / model_slug / prompt_id
    candidates = sorted(directory.glob("*_builder_spec.json"))
    return candidates[0] if candidates else None


def extract_compiled_case(
    spec: dict[str, Any], case: dict[str, Any], visual: dict[str, Any]
) -> tuple[dict[str, float], dict[str, Any]]:
    dynamics = spec.get("world_dynamics") or {}
    institutions = [row for row in (dynamics.get("institutions") or []) if isinstance(row, dict)]
    states = [row for row in (dynamics.get("state_variables") or []) if isinstance(row, dict)]
    links = [row for row in (dynamics.get("causal_links") or []) if isinstance(row, dict)]
    groups = [row for row in (dynamics.get("stakeholder_groups") or []) if isinstance(row, dict)]
    rooms = [row for row in (spec.get("rooms") or []) if isinstance(row, dict)]
    agents = [row for row in (spec.get("main_characters") or []) if isinstance(row, dict)]
    loops = [row for row in (spec.get("gameplay_loops") or []) if isinstance(row, dict)]
    conflict_hooks = list(spec.get("conflict_hooks") or [])
    custom_actions = list(spec.get("custom_actions") or [])
    open_examples = [row for row in (spec.get("open_action_examples") or []) if isinstance(row, dict)]
    item_catalog = [row for row in (spec.get("item_catalog") or []) if isinstance(row, dict)]
    entry_points = list(spec.get("player_entry_points") or [])
    observations = case.get("observations") or {}
    society_obs = observations.get("society") or {}
    interaction_obs = observations.get("interaction") or {}

    state_ids = [str(row.get("state_id", "")) for row in states if row.get("state_id")]
    state_tokens = set().union(*(tokens(state_id) for state_id in state_ids)) if state_ids else set()
    institution_tokens = set().union(
        *(tokens(row.get("name", "")) | tokens(row.get("institution_id", "")) for row in institutions)
    ) if institutions else set()
    mechanic_tokens = state_tokens | institution_tokens

    room_purposes = [row.get("purpose", "") for row in rooms]
    purpose_binding_rate = mean(
        bool(tokens(purpose) & mechanic_tokens) for purpose in room_purposes
    ) if room_purposes and mechanic_tokens else 0.0
    referenced_loop_rooms = {
        str(room_name).casefold()
        for loop in loops
        for room_name in (loop.get("rooms") or [])
    }
    room_names = {str(room.get("name", "")).casefold() for room in rooms}
    loop_room_coverage = len(room_names & referenced_loop_rooms) / max(1, len(room_names))
    scene_components = [
        component for room in rooms for component in (room.get("scene_components") or [])
    ]

    names = [agent.get("display_name", "") for agent in agents]
    roles = [agent.get("role_name", "") for agent in agents]
    goals = [agent.get("arc_goal", "") for agent in agents]
    inventories = [list(agent.get("inventory") or []) for agent in agents]
    inventory_names = [
        item.get("name", "")
        for inventory in inventories
        for item in inventory
        if isinstance(item, dict)
    ]
    inventory_descriptions = [
        item.get("description", "")
        for inventory in inventories
        for item in inventory
        if isinstance(item, dict)
    ]
    inventory_sets = [
        {str(item.get("name", "")).casefold() for item in inventory if isinstance(item, dict)}
        for inventory in inventories
    ]
    inventory_pair_distinctiveness: list[float] = []
    for index, left in enumerate(inventory_sets):
        for right in inventory_sets[index + 1 :]:
            inventory_pair_distinctiveness.append(1 - len(left & right) / max(1, len(left | right)))
    inventory_distinctiveness = (
        mean(inventory_pair_distinctiveness) if inventory_pair_distinctiveness else 0.0
    )
    role_inventory_binding: list[float] = []
    for agent, inventory in zip(agents, inventories):
        role_words = tokens(
            " ".join(
                str(agent.get(field, ""))
                for field in ("role_name", "activity", "arc_goal")
            )
        )
        inventory_words = set().union(
            *(
                tokens(item.get("name", "")) | tokens(item.get("description", ""))
                for item in inventory
                if isinstance(item, dict)
            )
        ) if inventory else set()
        role_inventory_binding.append(
            len(role_words & inventory_words) / max(1, len(role_words))
        )

    group_completeness = completeness(groups, ("goal", "leverage", "dependency"))
    loop_roles = {
        str(role).casefold()
        for loop in loops
        for role in (loop.get("roles") or [])
    }
    role_names = {str(role).casefold() for role in roles if role}
    loop_role_coverage = len(loop_roles & role_names) / max(1, len(role_names))
    relational_rate = float(society_obs.get("relational_agent_rate") or 0.0)

    effect_kinds = {
        str(kind).casefold()
        for example in open_examples
        for kind in (example.get("proposed_effects") or [])
    }
    loop_state_binding = mean(
        bool(tokens(" ".join(str(loop.get(field, "")) for field in ("summary", "pressure"))) & state_tokens)
        for loop in loops
    ) if loops and state_tokens else 0.0

    floor_prompt_rate = mean(bool(room.get("flux_floor_prompt")) for room in rooms) if rooms else 0.0
    scene_prompt_rate = mean(bool(room.get("room_scene_prompt")) for room in rooms) if rooms else 0.0
    prompt_distinctiveness = pairwise_distinctiveness(
        room.get("room_scene_prompt", "") for room in rooms
    )
    component_uniqueness = uniqueness(
        component.get("component_id", "") if isinstance(component, dict) else component
        for component in scene_components
    )
    visual_canon = spec.get("visual_canon") or {}
    visual_canon_richness = target(len([value for value in visual_canon.values() if value]), 10)

    vocabulary_fields = room_purposes + goals + [str(value) for value in custom_actions]
    vocabulary = [token for value in vocabulary_fields for token in tokens(value)]
    vocabulary_richness = len(set(vocabulary)) / max(1, len(vocabulary))

    raw = {
        "institution_count": len(institutions),
        "state_variable_count": len(states),
        "causal_link_count": len(links),
        "cyclic_state_fraction": cycle_fraction(state_ids, links),
        "room_count": len(rooms),
        "unique_biome_rate": uniqueness(room.get("biome", "") for room in rooms),
        "room_purpose_distinctiveness": pairwise_distinctiveness(room_purposes),
        "room_mechanic_binding_rate": purpose_binding_rate,
        "loop_room_coverage": loop_room_coverage,
        "scene_components_per_room": len(scene_components) / max(1, len(rooms)),
        "agent_count": len(agents),
        "unique_name_rate": uniqueness(names),
        "unique_role_rate": uniqueness(roles),
        "goal_distinctiveness": pairwise_distinctiveness(goals),
        "inventory_unique_rate": uniqueness(inventory_names),
        "inventory_distinctiveness": inventory_distinctiveness,
        "mean_inventory_count": mean(map(len, inventories)) if inventories else 0.0,
        "role_inventory_binding": mean(role_inventory_binding) if role_inventory_binding else 0.0,
        "relational_agent_rate": relational_rate,
        "stakeholder_group_count": len(groups),
        "stakeholder_completeness": group_completeness,
        "stakeholder_distinctiveness": pairwise_distinctiveness(
            " ".join(str(row.get(field, "")) for field in ("goal", "leverage", "dependency"))
            for row in groups
        ),
        "conflict_hook_count": len(conflict_hooks),
        "loop_role_coverage": loop_role_coverage,
        "item_catalog_count": len(item_catalog),
        "inventory_description_rate": mean(bool(value) for value in inventory_descriptions)
        if inventory_descriptions else 0.0,
        "gameplay_loop_count": len(loops),
        "custom_action_count": len(custom_actions),
        "open_action_example_count": len(open_examples),
        "open_effect_kind_count": len(effect_kinds),
        "mean_coordinator_check_count": mean(
            len(example.get("coordinator_checks") or []) for example in open_examples
        ) if open_examples else 0.0,
        "loop_state_binding_rate": loop_state_binding,
        "player_entry_count": len(entry_points),
        "player_entry_distinctiveness": pairwise_distinctiveness(entry_points),
        "world_specific_action_rate": float(interaction_obs.get("world_specific_action_count") or 0)
        / max(1, float(interaction_obs.get("custom_action_count") or 0)),
        "shared_human_ai_contract_rate": float(
            interaction_obs.get("shared_human_ai_contract_rate") or 0.0
        ),
        "human_interaction_enabled": bool(interaction_obs.get("human_interaction_enabled")),
        "coordinator_open_proposals": bool(interaction_obs.get("coordinator_open_proposals")),
        "vocabulary_richness": vocabulary_richness,
        "floor_prompt_rate": floor_prompt_rate,
        "scene_prompt_rate": scene_prompt_rate,
        "visual_prompt_distinctiveness": prompt_distinctiveness,
        "component_uniqueness": component_uniqueness,
        "visual_canon_richness": visual_canon_richness,
        "agent_visual_policy_present": bool(spec.get("agent_visual_policy")),
        "visual_technical_score": float(visual.get("technical_score") or 0.0),
    }

    axes = {
        "causal_system": 100 * (
            0.16 * target(raw["institution_count"], 5)
            + 0.16 * target(raw["state_variable_count"], 6)
            + 0.24 * target(raw["causal_link_count"], 10)
            + 0.20 * raw["cyclic_state_fraction"]
            + 0.24 * completeness(links, ("trigger", "effect", "delay"))
        ),
        "spatial_semantic_necessity": 100 * (
            0.12 * target(raw["room_count"], 10)
            + 0.12 * raw["unique_biome_rate"]
            + 0.14 * raw["room_purpose_distinctiveness"]
            + 0.24 * target(raw["room_mechanic_binding_rate"], 0.75)
            + 0.18 * target(raw["loop_room_coverage"], 0.80)
            + 0.20 * target(raw["scene_components_per_room"], 2.0)
        ),
        "agent_individuation": 100 * (
            0.08 * target(raw["agent_count"], 12)
            + 0.10 * raw["unique_name_rate"]
            + 0.12 * raw["unique_role_rate"]
            + 0.18 * raw["goal_distinctiveness"]
            + 0.12 * raw["inventory_unique_rate"]
            + 0.12 * raw["inventory_distinctiveness"]
            + 0.10 * target(raw["role_inventory_binding"], 0.18)
            + 0.18 * raw["relational_agent_rate"]
        ),
        "social_interdependence": 100 * (
            0.18 * target(raw["stakeholder_group_count"], 5)
            + 0.15 * raw["stakeholder_completeness"]
            + 0.15 * raw["stakeholder_distinctiveness"]
            + 0.16 * target(raw["conflict_hook_count"], 6)
            + 0.16 * target(raw["loop_role_coverage"], 0.75)
            + 0.20 * raw["relational_agent_rate"]
        ),
        "material_economy": 100 * (
            0.16 * target(raw["item_catalog_count"], 20)
            + 0.14 * target(raw["mean_inventory_count"], 8)
            + 0.14 * raw["inventory_unique_rate"]
            + 0.16 * raw["inventory_distinctiveness"]
            + 0.18 * target(raw["role_inventory_binding"], 0.18)
            + 0.10 * raw["inventory_description_rate"]
            + 0.12 * target(len(tokens(spec.get("economy_focus", ""))), 10)
        ),
        "interaction_depth": 100 * (
            0.14 * target(raw["gameplay_loop_count"], 6)
            + 0.14 * target(raw["loop_room_coverage"], 0.80)
            + 0.12 * target(raw["loop_role_coverage"], 0.75)
            + 0.14 * target(raw["custom_action_count"], 12)
            + 0.12 * target(raw["open_action_example_count"], 4)
            + 0.12 * target(raw["open_effect_kind_count"], 5)
            + 0.10 * target(raw["mean_coordinator_check_count"], 6)
            + 0.12 * target(raw["loop_state_binding_rate"], 0.75)
        ),
        "human_affordance": 100 * (
            0.20 * target(raw["player_entry_count"], 4)
            + 0.15 * raw["player_entry_distinctiveness"]
            + 0.20 * raw["shared_human_ai_contract_rate"]
            + 0.15 * float(raw["human_interaction_enabled"])
            + 0.15 * float(raw["coordinator_open_proposals"])
            + 0.15 * target(raw["open_action_example_count"], 4)
        ),
        "template_escape": 100 * (
            0.16 * raw["room_purpose_distinctiveness"]
            + 0.16 * raw["goal_distinctiveness"]
            + 0.14 * raw["unique_role_rate"]
            + 0.14 * raw["inventory_distinctiveness"]
            + 0.12 * target(raw["vocabulary_richness"], 0.72)
            + 0.18 * target(raw["world_specific_action_rate"], 0.85)
            + 0.10 * raw["stakeholder_distinctiveness"]
        ),
        "visual_authorship": 100 * (
            0.12 * raw["floor_prompt_rate"]
            + 0.12 * raw["scene_prompt_rate"]
            + 0.16 * raw["visual_prompt_distinctiveness"]
            + 0.18 * target(raw["scene_components_per_room"], 2.0)
            + 0.12 * raw["component_uniqueness"]
            + 0.14 * raw["visual_canon_richness"]
            + 0.08 * float(raw["agent_visual_policy_present"])
            + 0.08 * target(raw["visual_technical_score"], 100)
        ),
        "first_pass_robustness": max(
            0.0,
            100.0
            - 20.0 * float((case.get("operational") or {}).get("semantic_retry_count") or 0)
            - (0.0 if case.get("first_pass_success") else 20.0),
        ),
    }
    axes = {name: round(clamp01(value / 100.0) * 100.0, 2) for name, value in axes.items()}
    raw = {
        name: round(value, 4) if isinstance(value, float) else value for name, value in raw.items()
    }
    return axes, raw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    comprehensive = load_json(args.results)
    axis_weights = {
        "causal_system": 0.13,
        "spatial_semantic_necessity": 0.10,
        "agent_individuation": 0.12,
        "social_interdependence": 0.12,
        "material_economy": 0.09,
        "interaction_depth": 0.13,
        "human_affordance": 0.09,
        "template_escape": 0.08,
        "visual_authorship": 0.08,
        "first_pass_robustness": 0.06,
    }
    ranking: list[dict[str, Any]] = []
    for row in comprehensive.get("ranking") or []:
        model = str(row.get("model", ""))
        visual = row.get("visual_realization") or {}
        case_records: list[dict[str, Any]] = []
        for case in (row.get("generated_world") or {}).get("cases") or []:
            prompt_id = str(case.get("prompt_id", ""))
            path = find_builder_spec(args.runs_root, model, prompt_id)
            if case.get("status") != "compiled" or path is None:
                axes = {name: 0.0 for name in axis_weights}
                raw: dict[str, Any] = {}
            else:
                axes, raw = extract_compiled_case(load_json(path), case, visual)
            score = sum(axes[name] * weight for name, weight in axis_weights.items())
            case_records.append(
                {
                    "prompt_id": prompt_id,
                    "status": case.get("status"),
                    "builder_spec_path": str(path.relative_to(ROOT)) if path else "",
                    "score": round(score, 2),
                    "axes": axes,
                    "raw": raw,
                }
            )
        axis_means = {
            name: round(mean(case["axes"][name] for case in case_records), 2)
            for name in axis_weights
        }
        strict_score = round(mean(case["score"] for case in case_records), 2)
        ranking.append(
            {
                "model": model,
                "strict_generation_objective": strict_score,
                "contract_score_v1": (row.get("generated_world") or {}).get("score", 0.0),
                "visual_realization_v1": visual.get("score", 0.0),
                "compiled_worlds": (row.get("generated_world") or {}).get("completed_cases", 0),
                "first_pass_worlds": (row.get("generated_world") or {}).get("first_pass_successes", 0),
                "axes": axis_means,
                "cases": case_records,
            }
        )
    ranking.sort(key=lambda item: item["strict_generation_objective"], reverse=True)
    payload = {
        "benchmark": "Agora strict generation evidence",
        "version": "strict-generation-evidence-v1",
        "construct": (
            "Causal, social, spatial, material, interactive, human-facing, and visual "
            "authorship quality; failures remain zero"
        ),
        "axis_weights": axis_weights,
        "ranking": ranking,
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "models": len(ranking)}, indent=2))


if __name__ == "__main__":
    main()
