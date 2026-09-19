#!/usr/bin/env python3
"""Score one non-preset LivingWorldBench full-artifact development attempt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agora_living_world_benchmark import (  # noqa: E402
    _interaction_axis,
    _sentence_axis,
    _society_axis,
    _spatial_axis,
)
from scripts.agora_living_world_model_comparison import (  # noqa: E402
    FULL_WEIGHTS,
    _cross_node,
    _expert_score,
    _geometric,
    _visual_artifact,
)


EXPERT_WEIGHTS = {
    "premise_transformation": 0.15,
    "institutional_causality": 0.20,
    "spatial_material_imagination": 0.15,
    "agent_society": 0.15,
    "interaction_imagination": 0.20,
    "rendered_map_quality": 0.15,
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _dynamics_gate(builder: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    dynamics = builder.get("world_dynamics", {}) if isinstance(builder.get("world_dynamics"), dict) else {}
    institutions = [item for item in dynamics.get("institutions", []) if isinstance(item, dict)]
    states = [item for item in dynamics.get("state_variables", []) if isinstance(item, dict)]
    links = [item for item in dynamics.get("causal_links", []) if isinstance(item, dict)]
    groups = [item for item in dynamics.get("stakeholder_groups", []) if isinstance(item, dict)]
    state_ids = {str(item.get("state_id", "")).strip() for item in states if str(item.get("state_id", "")).strip()}
    exact_links = sum(
        str(link.get("source_state", "")).strip() in state_ids
        and str(link.get("target_state", "")).strip() in state_ids
        for link in links
    )
    observations = {
        "institution_count": len(institutions),
        "state_variable_count": len(state_ids),
        "causal_link_count": len(links),
        "exact_causal_link_count": exact_links,
        "stakeholder_group_count": len(groups),
    }
    return bool(
        len(institutions) >= 3
        and len(state_ids) >= 4
        and len(links) >= 4
        and exact_links == len(links)
        and len(groups) >= 3
    ), observations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--builder", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--expert-review", type=Path, required=True)
    parser.add_argument("--sentence", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    builder = _read(args.builder)
    config = _read(args.config)
    result = _read(args.result)
    review = _read(args.expert_review)
    sentence_score, sentence_obs = _sentence_axis(args.sentence, config, builder)
    spatial_score, spatial_obs = _spatial_axis(config)
    cross_score, cross_obs = _cross_node(builder)
    society_score, society_obs = _society_axis(config)
    interaction_score, interaction_obs = _interaction_axis(config)
    visual_score, visual_obs = _visual_artifact(args.asset_dir, builder)
    compiler_score = 25.0 * sum(
        [
            result.get("generation_ok") is True,
            result.get("merged_contract_probe", {}).get("merged_contract_ok") is True,
            result.get("compile_probe", {}).get("compile_ok") is True,
            result.get("complete_success") is True,
        ]
    )
    axes = {
        "sentence_realization": sentence_score,
        "compiled_space": spatial_score,
        "cross_node_referential_integrity": cross_score,
        "agent_society": society_score,
        "interaction_contract": interaction_score,
        "visual_artifact": visual_score,
        "compiler_conformance": compiler_score,
    }
    objective = _geometric(axes, FULL_WEIGHTS)
    dynamics_ok, dynamics_obs = _dynamics_gate(builder)
    seed = builder.get("world_seed", {}) if isinstance(builder.get("world_seed"), dict) else {}
    forbidden_seed_keys = sorted({"preset_id", "profile_id", "kit_refs", "policy_refs"} & set(seed))
    custom_rules = config.get("world_rules", {}).get("custom_action_rules", {})
    routing = config.get("actions", {}).get("routing_policy", {})
    examples = config.get("actions", {}).get("open_action_examples", [])
    effects = set(custom_rules.get("open_proposal_effects", []))
    gates = {
        "nonpreset_semantic_seed": seed.get("seed_version") == "world_seed_v3_open" and not forbidden_seed_keys,
        "world_dynamics": dynamics_ok,
        "compiler_and_package": compiler_score == 100.0,
        "exact_cross_node_references": cross_score == 100.0,
        "open_world_actions": bool(
            custom_rules.get("open_proposals_enabled")
            and routing.get("open_proposal_route_id") == "__propose__"
            and len(examples) >= 4
            and {"speech", "transfer", "create_item", "status"}.issubset(effects)
        ),
        "visual_floor": bool(
            visual_obs["map_source_present"]
            and visual_obs["semantic_component_count"] > 0
            and visual_obs["semantic_component_generation_rate"] >= 0.80
            and visual_obs["semantic_component_readability_rate"] >= 0.75
            and visual_obs["floor_count"] > 0
            and visual_obs["floor_qa_pass_rate"] == 1.0
            and (args.asset_dir / "sprite_batch_vision_qa.json").is_file()
        ),
    }
    expert = _expert_score({"scores": review.get("scores", {})}, EXPERT_WEIGHTS)
    payload = {
        "protocol": "nonpreset_80plus_20260824",
        "objective_threshold": 80.0,
        "expert_threshold": 80.0,
        "full_artifact_objective_score": round(objective, 2),
        "expert_subjective_score": round(float(expert or 0.0), 2),
        "accepted": bool(objective >= 80.0 and (expert or 0.0) >= 80.0 and all(gates.values())),
        "axes": {name: round(value, 2) for name, value in axes.items()},
        "gates": gates,
        "observations": {
            "forbidden_seed_keys": forbidden_seed_keys,
            "world_dynamics": dynamics_obs,
            "sentence": sentence_obs,
            "space": spatial_obs,
            "cross_node": cross_obs,
            "society": society_obs,
            "interaction": interaction_obs,
            "visual": visual_obs,
        },
        "expert_review": review,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"objective": payload["full_artifact_objective_score"], "expert": payload["expert_subjective_score"], "accepted": payload["accepted"], "gates": gates}, indent=2))


if __name__ == "__main__":
    main()
