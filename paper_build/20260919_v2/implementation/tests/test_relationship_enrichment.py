from __future__ import annotations

import pytest

from scripts.agora_relationship_enrichment import _validate


def _edge(target: str, relationship_type: str = "trust") -> dict[str, str]:
    return {
        "target_name": target,
        "relationship_type": relationship_type,
        "description": f"A concrete obligation involving {target} and a world resource.",
    }


def test_relationship_validator_accepts_connected_distinct_graph() -> None:
    names = ["A", "B", "C", "D"]
    payload = {
        "characters": [
            {"source_name": "A", "relationships": [_edge("B"), _edge("C", "rival")]},
            {"source_name": "B", "relationships": [_edge("A"), _edge("D", "supplier")]},
            {"source_name": "C", "relationships": [_edge("A"), _edge("D", "contract")]},
            {"source_name": "D", "relationships": [_edge("B"), _edge("C", "depend")]},
        ]
    }

    graph, diagnostics = _validate(payload, names)

    assert set(graph) == set(names)
    assert diagnostics["connected"] is True
    assert diagnostics["edge_count"] == 8
    assert diagnostics["duplicate_target_sources"] == []


def test_relationship_validator_rejects_duplicate_targets() -> None:
    names = ["A", "B", "C"]
    payload = {
        "characters": [
            {"source_name": "A", "relationships": [_edge("B"), _edge("B", "rival")]},
            {"source_name": "B", "relationships": [_edge("A"), _edge("C")]},
            {"source_name": "C", "relationships": [_edge("A"), _edge("B")]},
        ]
    }

    with pytest.raises(ValueError, match="duplicate_target_sources"):
        _validate(payload, names)


def test_relationship_validator_rejects_disconnected_communities() -> None:
    names = ["A", "B", "C", "D", "E", "F"]
    payload = {
        "characters": [
            {"source_name": "A", "relationships": [_edge("B"), _edge("C")]},
            {"source_name": "B", "relationships": [_edge("A"), _edge("C")]},
            {"source_name": "C", "relationships": [_edge("A"), _edge("B")]},
            {"source_name": "D", "relationships": [_edge("E"), _edge("F")]},
            {"source_name": "E", "relationships": [_edge("D"), _edge("F")]},
            {"source_name": "F", "relationships": [_edge("D"), _edge("E")]},
        ]
    }

    with pytest.raises(ValueError, match="disconnected_sources"):
        _validate(payload, names)
