from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from scripts.agora_living_world_benchmark import (
    BUILD_AXIS_WEIGHTS,
    PERCEPTUAL_DIMENSIONS,
    PLAYABLE_PROBE_IDS,
    _first_sentence,
    _interaction_axis,
    _perceptual_visual_evidence,
    _playable_probe_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "docs" / "living_world_benchmark_20260824" / "prompt_suite_v1.json"


def test_prompt_suite_is_frozen_one_sentence_contract() -> None:
    suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    prompts = suite["prompts"]
    assert len(prompts) == 12
    assert sum(item["split"] == "development" for item in prompts) == 8
    assert sum(item["split"] == "held_out" for item in prompts) == 4
    assert len({item["prompt_id"] for item in prompts}) == len(prompts)
    assert all(_first_sentence(item["sentence"]) == item["sentence"] for item in prompts)
    assert sum(BUILD_AXIS_WEIGHTS.values()) == 1.0


def test_open_world_contract_raises_interaction_score() -> None:
    closed = {
        "human_interaction": {"enabled": True},
        "actions": {
            "allowed_custom_actions": ["inspect", "trade", "message"],
            "ordinary_routes": [
                {"route_id": "trade", "kind": "item_trade"},
                {"route_id": "inspect", "kind": "inspect"},
            ],
            "cinematic_routes": [{"route_id": "freeform", "freeform_required": True}],
        },
    }
    opened = deepcopy(closed)
    opened["world_rules"] = {"custom_action_rules": {"open_proposals_enabled": True}}
    opened["actions"]["routing_policy"] = {"catalog_role": "__propose__"}
    opened["actions"]["interaction_affordance_catalog"] = [
        {
            "label": label,
            "interaction_family": family,
            "actor_modes": ["human", "ai"],
            "persistent_effects": ["world_state"],
        }
        for label, family in (
            ("forge floodgate compact", "governance"),
            ("trade stored rain", "exchange"),
            ("create shared gate token", "creation"),
            ("repair sluice", "maintenance"),
            ("contest water claim", "dispute"),
            ("record downstream debt", "memory"),
        )
    ]
    closed_score, closed_observations = _interaction_axis(closed)
    open_score, open_observations = _interaction_axis(opened)
    assert closed_observations["coordinator_open_proposals"] is False
    assert open_observations["coordinator_open_proposals"] is True
    assert open_observations["creation_action_present"] is True
    assert open_observations["shared_human_ai_contract_rate"] == 1.0
    assert open_score >= closed_score + 20


def test_blind_perceptual_score_requires_three_valid_raters(tmp_path: Path) -> None:
    ratings = {
        "blinded": True,
        "ratings": [
            {"scores": {dimension: value for dimension in PERCEPTUAL_DIMENSIONS}}
            for value in (3, 4, 5)
        ],
    }
    evidence_path = tmp_path / "visual_ratings.json"
    evidence_path.write_text(json.dumps(ratings), encoding="utf-8")
    score, evidence = _perceptual_visual_evidence(
        tmp_path, {"perceptual_visual_path": evidence_path.name}
    )
    assert score == 75.0
    assert evidence["qualified"] is True
    ratings["ratings"].pop()
    evidence_path.write_text(json.dumps(ratings), encoding="utf-8")
    score, evidence = _perceptual_visual_evidence(
        tmp_path, {"perceptual_visual_path": evidence_path.name}
    )
    assert score is None
    assert evidence["qualified"] is False


def test_level_b_probe_contract_requires_all_ten_probes(tmp_path: Path) -> None:
    payload = {
        "probes": [
            {"probe_id": probe_id, "status": "pass", "evidence": f"trace:{probe_id}"}
            for probe_id in PLAYABLE_PROBE_IDS
        ]
    }
    evidence_path = tmp_path / "playable_probes.json"
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    score, evidence = _playable_probe_evidence(
        tmp_path, {"playable_probe_path": evidence_path.name}
    )
    assert score == 100.0
    assert evidence["qualified"] is True
    payload["probes"][-1]["status"] = "fail"
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    score, evidence = _playable_probe_evidence(
        tmp_path, {"playable_probe_path": evidence_path.name}
    )
    assert score == 90.0
    assert evidence["qualified"] is False
