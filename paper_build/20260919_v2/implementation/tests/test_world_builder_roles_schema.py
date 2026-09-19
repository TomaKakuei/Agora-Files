from copy import deepcopy

import pytest

from agora_ui.world_builder.nodes import roles


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _characters(count: int) -> list[dict]:
    names = [f"Character {index}" for index in range(count)]
    return [
        {
            "display_name": name,
            "role_name": f"Role {index}",
            "activity": "Maintains the shared kiln state.",
            "home_base": "Kiln Hall",
            "arc_goal": "Change the firing queue through the council.",
            "inventory": [
                {"name": f"item_{index}_{item}", "description": "Specific tool.", "quantity": 1}
                for item in range(8)
            ],
            "property_templates": [
                {"asset_name": f"property_{n}", "asset_type": "tool", "description": "Specific asset.", "story_use": "Repair work."}
                for n in range(2)
            ],
            "knowledge_templates": [
                {"knowledge_id": f"knowledge_{n}", "topic": "kiln", "summary": "Specific fact.", "confidence": 80}
                for n in range(2)
            ],
            "relationships": [
                {"target_name": names[(index + 1) % count], "relationship_type": "supplier", "description": "Provides clay."},
                {"target_name": names[(index + 2) % count], "relationship_type": "rival", "description": "Contests queue priority."},
            ],
        }
        for index, name in enumerate(names)
    ]


def test_wire_schema_avoids_combinatorial_serving_constraints() -> None:
    schema = roles._main_character_batch_schema(4)
    forbidden = {"minItems", "maxItems", "enum", "minimum", "maximum"}
    assert not any(forbidden & set(node) for node in _walk(schema))


def test_relationship_enum_remains_a_local_hard_constraint(monkeypatch) -> None:
    payload = {"characters": _characters(4)}
    payload["characters"][0]["relationships"][0]["relationship_type"] = "roommate"
    monkeypatch.setattr(roles, "_execute_json_prompt", lambda **_kwargs: deepcopy(payload))

    with pytest.raises(ValueError, match="invalid relationship types"):
        roles.generate_roles_spec(
            provider=object(),
            planner_spec={"world_name": "Kiln", "world_dynamics": {}},
            rooms=[{"name": "Kiln Hall"}],
            items=[{"item_id": "clay"}],
            agent_count_target=8,
            min_merchant_items=8,
        )
