from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "living_world_benchmark_20260824" / "model_comparison_20260824"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_matched_model_pilot_keeps_objective_and_expert_scores_separate() -> None:
    results = _read(EVIDENCE / "comparison_results.json")
    rows = results["models"]

    assert len(rows) == 5
    assert all(row["complete_success"] for row in rows)
    assert all("pre_art_objective_score" in row for row in rows)
    assert all("full_artifact_objective_score" in row for row in rows)
    assert all("expert_subjective_score" in row for row in rows)
    assert "combined_score" not in results
    assert all("combined_score" not in row for row in rows)


def test_expert_review_rubric_is_complete_and_normalized() -> None:
    review = _read(EVIDENCE / "expert_review_v1.json")

    assert review["review_status"] == "exploratory_single_reviewer_not_blinded"
    assert abs(sum(review["weights"].values()) - 1.0) < 1e-9
    assert len(review["reviews"]) == 5
    assert all(
        set(entry["scores"]) == set(review["weights"])
        for entry in review["reviews"].values()
    )


def test_every_ranked_model_retains_raw_generation_evidence() -> None:
    results = _read(EVIDENCE / "comparison_results.json")

    for row in results["models"]:
        dirname = row["model"].replace("-", "_").replace(".", "_")
        model_dir = EVIDENCE / dirname
        assert next(model_dir.glob("*_builder_spec.json"), None) is not None
        assert next(model_dir.glob("*_world_config.json"), None) is not None
        assert next(model_dir.glob("*_result.json"), None) is not None
        assert next(model_dir.glob("*_vertex_calls.jsonl"), None) is not None


def test_invalid_harness_launch_is_preserved_but_not_ranked() -> None:
    invalid = EVIDENCE / "invalid_harness_string_seed_gemini_3_7_flash"
    results = _read(EVIDENCE / "comparison_results.json")

    assert invalid.is_dir()
    assert len(results["models"]) == 5
    assert all("invalid_harness" not in row["model"] for row in results["models"])
