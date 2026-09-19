from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from scripts.agora_community_performance_benchmark import _plan_schema, aggregate_model, score_plan


ROOT = Path(__file__).resolve().parents[1]
SUITE = json.loads(
    (ROOT / "docs" / "community_performance_benchmark_20260824" / "micro_scenarios.json").read_text(
        encoding="utf-8"
    )
)
TIDAL = SUITE["scenarios"][0]


def test_api_plan_schema_is_native_json_schema() -> None:
    schema = _plan_schema()
    actions = schema["properties"]["actions"]
    item = actions["items"]
    assert schema["type"] == "object"
    assert actions["type"] == "array"
    assert item["type"] == "object"
    assert item["properties"]["action_type"]["enum"] == ["catalog", "propose"]
    assert set(item["required"]) == set(item["properties"])


def _action(
    actor: str,
    target: str,
    catalog: str,
    thread: str,
    task: str,
    contribution: str,
    fact: str,
    *,
    object_id: str = "",
    detail: str,
    human: bool = False,
) -> dict:
    return {
        "actor_id": actor,
        "target_id": target,
        "action_type": "catalog",
        "catalog_action_id": catalog,
        "proposal": {"verb": "", "scope": "target", "bounded_effect": True, "requires_consent": False},
        "thread_id": thread,
        "task_id": task,
        "contribution_ids": [contribution],
        "fact_ids": [fact],
        "input_object_ids": [object_id] if object_id else [],
        "output_object_ids": [],
        "world_detail_ids": [detail],
        "intended_role_ids": [],
        "addresses_human_intent": human,
        "consent_basis": "",
        "expected_effect": f"Advance {contribution} without applying unapproved world state.",
    }


def strong_tidal_plan() -> dict:
    actions = [
        _action(
            "vaela", "rook", "coordinate_rescue", "thread_lower_archive_rescue", "task_rescue_treaty",
            "contrib_secure_document", "fact_tide_deadline", object_id="treaty_case", detail="lower_archive",
        ),
        _action(
            "oren", "rook", "coordinate_rescue", "thread_lower_archive_rescue", "task_rescue_treaty",
            "contrib_slow_water", "fact_filter_bypass", object_id="sluice_key", detail="phonetic_sluice",
        ),
        _action(
            "rook", "vaela", "move_between_rooms", "thread_lower_archive_rescue", "task_rescue_treaty",
            "contrib_move_document", "fact_dry_route", object_id="archive_sling", detail="lower_archive",
        ),
        _action(
            "mirel", "human_player", "message", "thread_translation_rights", "task_preserve_rights",
            "contrib_negotiate_clause", "fact_delegate_condition", detail="communal_translation_rights", human=True,
        ),
        _action(
            "senn", "mirel", "inspect_custody_record", "thread_translation_rights", "task_preserve_rights",
            "contrib_witness_custody", "fact_custody_clause", object_id="custody_seal", detail="treaty_gallery",
        ),
        {
            "actor_id": "lyra",
            "target_id": "mirel",
            "action_type": "propose",
            "catalog_action_id": "",
            "proposal": {
                "verb": "wax and attest a communal-rights custody token",
                "scope": "target",
                "bounded_effect": True,
                "requires_consent": True,
            },
            "thread_id": "thread_translation_rights",
            "task_id": "task_preserve_rights",
            "contribution_ids": ["contrib_state_language_rights"],
            "fact_ids": ["fact_delegate_condition"],
            "input_object_ids": ["vowel_wax"],
            "output_object_ids": ["witnessed_custody_token"],
            "world_detail_ids": ["communal_translation_rights"],
            "intended_role_ids": ["diplomat"],
            "addresses_human_intent": False,
            "consent_basis": "Mirel must accept the wording before the coordinator creates the token.",
            "expected_effect": "Submit one witnessed token proposal while leaving treaty custody unchanged until approval.",
        },
    ]
    return {"actions": actions}


def test_strong_plan_scores_across_all_axes() -> None:
    result = score_plan(TIDAL, strong_tidal_plan())
    assert result["score"] >= 80
    assert result["observations"]["actor_coverage"] == 1.0
    assert result["observations"]["human_intent_answered"] is True
    assert result["observations"]["valid_contribution_coverage"] == 1.0
    assert result["axes"]["institutional_integrity"] == 100.0
    assert result["violations"] == {}


def test_private_fact_leak_is_audited() -> None:
    plan = strong_tidal_plan()
    plan["actions"][1]["fact_ids"] = ["fact_delegate_condition"]
    result = score_plan(TIDAL, plan)
    assert result["violations"]["fact_access"] == 1
    assert result["axes"]["institutional_integrity"] < 100


def test_low_participation_caps_composite() -> None:
    plan = {"actions": strong_tidal_plan()["actions"][:2]}
    result = score_plan(TIDAL, plan)
    assert result["observations"]["actor_coverage"] < 0.5
    assert result["score"] <= 49
    assert "fewer than half of eligible agents acted" in result["cap_reasons"]


def test_majority_illegal_actions_cap_composite() -> None:
    plan = strong_tidal_plan()
    for action in plan["actions"][:4]:
        action["fact_ids"] = ["fact_old_repair"]
    result = score_plan(TIDAL, plan)
    assert result["observations"]["actor_coverage"] == 1.0
    assert result["axes"]["institutional_integrity"] < 50
    assert result["score"] <= 49
    assert "fewer than half of proposed actions are fully legal" in result["cap_reasons"]


def test_model_aggregate_penalizes_api_unavailability() -> None:
    score = score_plan(TIDAL, strong_tidal_plan())
    completed = {"status": "ok", "score": score, "latency_seconds": 2.0, "telemetry": []}
    failed = {"status": "error", "latency_seconds": 1.0, "telemetry": []}
    summary = aggregate_model("model-x", [deepcopy(completed), failed])
    assert summary["completion_rate"] == 0.5
    assert summary["community_score"] == round(summary["mean_completed_scenario_score"] * 0.5, 2)
