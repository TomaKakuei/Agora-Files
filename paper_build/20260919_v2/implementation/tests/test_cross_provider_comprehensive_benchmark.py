from __future__ import annotations

from scripts.agora_cross_provider_comprehensive_benchmark import (
    _direct_expert_layer,
)


def test_direct_expert_layer_uses_shared_axis_weights() -> None:
    review = {
        "status": "model_identity_visible",
        "axis_weights": {"a": 0.25, "b": 0.75},
        "models": {
            "model": {
                "cases": {
                    "one": {"scores": {"a": 100, "b": 80}},
                    "two": {"scores": {"a": 80, "b": 60}},
                }
            }
        },
    }

    result = _direct_expert_layer("model", review)

    assert result["axis_means"] == {"a": 90.0, "b": 70.0}
    assert result["score"] == 75.0
