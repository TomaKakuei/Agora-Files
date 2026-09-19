from __future__ import annotations

from agora_ui.world_builder import generation_schemas
from agora_ui.world_builder.generation import (
    DecoupledGenerationExhausted,
    _generation_cache_keys_to_invalidate,
)
from agora_ui.world_builder.nodes.hooks import _hooks_schema
from agora_ui.world_builder.nodes.planner import _planner_schema
from agora_ui.world_pipeline import (
    ASSET_PROMPT_KIT_REGISTRY,
    COMPONENT_KIT_REGISTRY,
    ECONOMY_POLICY_REGISTRY,
    FRONTEND_AFFORDANCE_REGISTRY,
    INVENTORY_LAYER_POLICY_REGISTRY,
    ITEM_COLLECTION_REGISTRY,
    KNOWLEDGE_POLICY_REGISTRY,
    PROPERTY_POLICY_REGISTRY,
    ROLE_ITEM_POLICY_REGISTRY,
    WORLD_PROFILE_LIBRARY,
    resolve_world_seed,
)


def _schema() -> dict:
    for name, value in {
        "ASSET_PROMPT_KIT_REGISTRY": ASSET_PROMPT_KIT_REGISTRY,
        "COMPONENT_KIT_REGISTRY": COMPONENT_KIT_REGISTRY,
        "ECONOMY_POLICY_REGISTRY": ECONOMY_POLICY_REGISTRY,
        "FRONTEND_AFFORDANCE_REGISTRY": FRONTEND_AFFORDANCE_REGISTRY,
        "INVENTORY_LAYER_POLICY_REGISTRY": INVENTORY_LAYER_POLICY_REGISTRY,
        "ITEM_COLLECTION_REGISTRY": ITEM_COLLECTION_REGISTRY,
        "KNOWLEDGE_POLICY_REGISTRY": KNOWLEDGE_POLICY_REGISTRY,
        "PROPERTY_POLICY_REGISTRY": PROPERTY_POLICY_REGISTRY,
        "ROLE_ITEM_POLICY_REGISTRY": ROLE_ITEM_POLICY_REGISTRY,
        "WORLD_PROFILE_LIBRARY": WORLD_PROFILE_LIBRARY,
    }.items():
        setattr(generation_schemas, name, value)
    return generation_schemas._builder_spec_schema()


def test_main_character_schema_exposes_strict_compiler_contract() -> None:
    character = _schema()["properties"]["main_characters"]["items"]

    assert {
        "inventory",
        "property_templates",
        "knowledge_templates",
        "relationships",
    }.issubset(character["required"])
    assert character["properties"]["inventory"]["minItems"] == 8
    assert character["properties"]["property_templates"]["minItems"] == 2
    assert character["properties"]["knowledge_templates"]["minItems"] == 2
    assert character["properties"]["relationships"]["minItems"] == 2


def test_planner_contract_is_open_semantic_world_not_preset_selection() -> None:
    planner = _planner_schema()
    seed = planner["properties"]["world_seed"]

    assert seed["properties"]["seed_version"]["enum"] == ["world_seed_v3_open"]
    assert "preset_id" not in seed["properties"]
    assert "profile_id" not in seed["properties"]
    assert "kit_refs" not in seed["properties"]
    assert planner["properties"]["world_dynamics"]["properties"]["causal_links"]["minItems"] == 4


def test_open_world_seed_gets_compiler_adapter_without_semantic_preset() -> None:
    seed = resolve_world_seed(
        {
            "world_name": "Mycelial Editions",
            "genre": "living fungal library",
            "premise": "Authors negotiate with books that grow as fungi.",
            "world_seed": {
                "seed_version": "world_seed_v3_open",
                "locale": "en",
                "tone": "scholarly and uncanny",
                "visual_direction": "luminous paper mycelium",
                "currency_code": "SPORE",
                "currency_symbol": "sp",
                "currency_minor_unit": "thread",
                "currency_name": "spore mark",
                "domain_label": "authorship, fungal growth, and living editions",
            },
            "world_dynamics": {"institutions": [], "state_variables": [], "causal_links": [], "stakeholder_groups": []},
        }
    )

    assert seed["semantic_origin"] == "open_world_plan"
    assert seed["implementation_adapter_id"] == "civic_social_world"
    assert seed["currency_code"] == "SPORE"
    assert "preset_id" not in seed
    assert "profile_id" not in seed


def test_roles_failure_invalidates_only_roles_and_dependents() -> None:
    invalidated = _generation_cache_keys_to_invalidate(
        "roles",
        ValueError("merchant generated 8 inventory items, required 15"),
    )

    assert invalidated == {"roles", "wardrobe", "hooks"}
    assert {
        "planner",
        "visual_canon",
        "rooms",
        "materials",
        "items",
    }.isdisjoint(invalidated)


def test_rooms_failure_also_invalidates_grounded_hooks() -> None:
    invalidated = _generation_cache_keys_to_invalidate(
        "rooms",
        ValueError("rooms node changed the traversable locations"),
    )

    assert invalidated == {"rooms", "materials", "roles", "wardrobe", "hooks"}


def test_hooks_schema_restricts_loops_to_generated_rooms_and_roles() -> None:
    schema = _hooks_schema(
        ["Lower Lock Tollhouse", "Ward Electoral Exchange"],
        ["Lock Warden", "Ward Delegate"],
    )
    loop = schema["properties"]["gameplay_loops"]["items"]

    assert set(loop["required"]) == {"label", "summary", "roles", "rooms", "pressure"}
    assert loop["properties"]["rooms"]["items"]["enum"] == [
        "Lower Lock Tollhouse",
        "Ward Electoral Exchange",
    ]
    assert loop["properties"]["roles"]["items"]["enum"] == [
        "Lock Warden",
        "Ward Delegate",
    ]
    examples = schema["properties"]["open_action_examples"]
    assert examples["minItems"] == 4
    assert examples["items"]["properties"]["initiating_role"]["enum"] == [
        "Lock Warden",
        "Ward Delegate",
    ]


def test_contract_failure_is_attributed_from_error_message() -> None:
    invalidated = _generation_cache_keys_to_invalidate(
        "contract",
        ValueError("character 3 has fewer than 8 valid inventory items"),
    )

    assert invalidated == {"roles", "wardrobe", "hooks"}


def test_unknown_contract_failure_invalidates_full_dependency_graph() -> None:
    invalidated = _generation_cache_keys_to_invalidate(
        "contract",
        ValueError("unknown merged contract failure"),
    )

    assert invalidated == {
        "planner",
        "visual_canon",
        "rooms",
        "materials",
        "items",
        "roles",
        "wardrobe",
        "hooks",
    }


def test_exhausted_generation_preserves_semantic_retry_audit() -> None:
    events = [{"failed_node": "roles", "failed_node_attempt": 3}]

    error = DecoupledGenerationExhausted("failed", retry_events=events)
    events[0]["failed_node"] = "mutated"

    assert error.generation_node_retries == [
        {"failed_node": "roles", "failed_node_attempt": 3}
    ]
