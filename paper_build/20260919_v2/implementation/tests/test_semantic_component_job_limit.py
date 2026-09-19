from __future__ import annotations

import pytest

from asset_pipeline.generate_world_asset_set_full import (
    _semantic_component_job_limit,
)


def test_default_limit_expands_to_every_referenced_semantic_component() -> None:
    assert _semantic_component_job_limit({}, 12) == 12
    assert _semantic_component_job_limit({}, 20) == 20


def test_strict_mode_expands_legacy_compiler_budget_to_all_jobs() -> None:
    assert _semantic_component_job_limit(
        {"max_jobs": 12, "strict_semantic_components": True},
        20,
    ) == 20


def test_non_strict_explicit_limit_remains_a_budget_control() -> None:
    assert _semantic_component_job_limit(
        {"max_jobs": 12, "strict_semantic_components": False},
        20,
    ) == 12


def test_hard_limit_rejects_unbounded_strict_world() -> None:
    with pytest.raises(ValueError, match="required=65, hard_limit=64"):
        _semantic_component_job_limit({}, 65)
