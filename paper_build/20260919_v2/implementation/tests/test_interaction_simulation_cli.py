import json

import pytest

from agora_ui.run_interaction_simulation import core
from agora_ui.run_interaction_simulation.intent_schemas import _extra_world_functions_config
from agora_ui.run_interaction_simulation.memory import _initialize_runtime_memory
from agora_ui.adjudicator_schemas import AgentRuntimeProfileSpec
from agora_ui.runtime.operations import _validate_materialized_agent_ids


def test_core_loads_private_helpers_from_split_modules() -> None:
    assert core._resolve is not None
    assert core._resolved_grid_shape is not None
    assert core._build_agent_payloads is not None
    assert core._append_jsonl is not None


def test_split_intent_schema_world_helpers_are_bound() -> None:
    assert _extra_world_functions_config({"extra_world_functions": {"enabled": True}})["enabled"] is True


def test_split_memory_module_resolves_legacy_private_helpers() -> None:
    agent = AgentRuntimeProfileSpec.model_validate(
        {
            "agent_id": "a1",
            "display_name": "A",
            "coordinates": {"x": 0, "y": 0, "z": 0},
            "room_id": "r1",
        }
    )
    assert _initialize_runtime_memory(agent, {})["recent_rounds"] == []


def test_materialized_agent_identity_gate_rejects_cross_world_files(tmp_path) -> None:
    agents_dir = tmp_path / "Agents"
    agents_dir.mkdir()
    (agents_dir / "world_a_01.json").write_text(json.dumps({"agent_id": "world_a_01"}))
    (agents_dir / "world_b_01.json").write_text(json.dumps({"agent_id": "world_b_01"}))

    with pytest.raises(ValueError, match="agent identity mismatch"):
        _validate_materialized_agent_ids(tmp_path, [{"agent_id": "world_a_01"}])


def test_materialized_agent_identity_gate_accepts_exact_set(tmp_path) -> None:
    agents_dir = tmp_path / "Agents"
    agents_dir.mkdir()
    (agents_dir / "world_a_01.json").write_text(json.dumps({"agent_id": "world_a_01"}))

    _validate_materialized_agent_ids(tmp_path, [{"agent_id": "world_a_01"}])


def test_materialization_allows_every_custom_catalog_label(tmp_path) -> None:
    config = {
        "runtime": {"world_mode": "Fixed"},
        "space": {
            "rooms": [{"room_id": "r1", "name": "Room", "x": 0, "y": 0, "width_tiles": 2, "height_tiles": 2}],
            "grid_shape": {"width": 2, "height": 2, "levels": 1},
        },
        "actions": {
            "allowed_custom_actions": ["Chat"],
            "interaction_affordance_catalog": [
                {"route_id": "mediate_pressure", "kind": "custom", "label": "Mediate"},
                {"route_id": "cinematic", "kind": "cinematic", "label": "Act Together"},
                {"route_id": "move", "kind": "move", "label": "Move"},
            ],
        },
    }
    agent_payloads = [{
        "agent_id": "a1",
        "display_name": "A",
        "coordinates": {"x": 0, "y": 0, "z": 0},
        "room_id": "r1",
    }]

    paths = core.materialize_scenario(config, tmp_path / "scenario", agent_payloads=agent_payloads)
    rules = json.loads(paths["world_rules"].read_text())

    assert rules["custom_action_rules"]["allowed_actions"] == ["Chat", "Mediate", "Act Together"]
