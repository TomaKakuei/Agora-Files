from __future__ import annotations

import pytest

from scripts.agora_cross_provider_objective_benchmark import _objective_score


def test_objective_score_preserves_equal_layer_score() -> None:
    assert _objective_score(
        {
            "generated_world": 80.0,
            "community_policy": 80.0,
            "generated_world_runtime": 80.0,
        }
    ) == pytest.approx(80.0)


def test_objective_score_requires_all_objective_layers() -> None:
    assert _objective_score(
        {
            "generated_world": 90.0,
            "community_policy": 90.0,
            "generated_world_runtime": 0.0,
        }
    ) == 0.0
