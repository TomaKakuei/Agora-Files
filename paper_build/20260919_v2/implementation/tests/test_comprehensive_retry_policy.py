from __future__ import annotations

import pytest

from scripts.agora_comprehensive_hidden_benchmark import (
    _active_floor_qa_paths,
    _visual_layer,
    _semantic_retry_adjusted_score,
)


@pytest.mark.parametrize(
    ("retry_count", "expected"),
    [(0, 100.0), (1, 98.0), (2, 96.04), (3, 94.1192)],
)
def test_semantic_retry_penalty_is_uniform_and_small(
    retry_count: int,
    expected: float,
) -> None:
    assert _semantic_retry_adjusted_score(100.0, retry_count) == pytest.approx(
        expected
    )


def test_semantic_retry_penalty_never_rewards_invalid_counts() -> None:
    assert _semantic_retry_adjusted_score(80.0, -2) == 80.0


def test_floor_score_uses_current_artifact_not_rejected_history(tmp_path) -> None:
    floors = tmp_path / "floors"
    floors.mkdir()
    current = floors / "floor_room_01.qa.json"
    rejected = floors / "floor_room_01.rejected_123.qa.json"
    current.write_text("{}", encoding="utf-8")
    rejected.write_text("{}", encoding="utf-8")

    assert _active_floor_qa_paths(tmp_path) == [current]


def test_missing_visual_manifest_receives_no_technical_credit(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "scripts.agora_comprehensive_hidden_benchmark.WORLD_ASSET_ROOT",
        tmp_path,
    )

    result = _visual_layer("gpt-5.6-luna", 0.0, {})

    assert result["technical_score"] == 0.0
    assert result["score"] == 0.0
    assert result["hard_gate_pass"] is False
