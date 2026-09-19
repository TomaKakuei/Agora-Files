from agora_ui.world_builder.builder import _interaction_affordance_catalog
from scripts.agora_interaction_quality_audit import audit


def test_affordance_catalog_exposes_shared_typed_effects() -> None:
    catalog = _interaction_affordance_catalog(
        [
            {"route_id": "decode_treaty", "kind": "custom", "action": "Decode Treaty", "status_effect": "decoded"},
            {"route_id": "trade_supplies", "kind": "item_trade"},
            {"route_id": "move_archive", "kind": "move"},
        ]
    )
    assert catalog[0]["actor_modes"] == ["human", "ai"]
    assert catalog[0]["target_types"] == ["agent", "human_player"]
    assert catalog[0]["persistent_effects"] == ["relationship", "status"]
    assert catalog[1]["persistent_effects"] == ["relationship", "inventory"]
    assert catalog[2]["persistent_effects"] == ["location"]


def test_quality_audit_requires_breadth_and_world_specificity() -> None:
    routes = [
        {"route_id": "decode", "kind": "custom", "action": "Decode Treaty", "status_effect": "decoded"},
        {"route_id": "seal", "kind": "custom", "action": "Forge Seal", "status_effect": "sealed"},
        {"route_id": "rescue", "kind": "custom", "action": "Rescue Archive", "status_effect": "rescued"},
        {"route_id": "trade", "kind": "item_trade"},
        {"route_id": "move", "kind": "move"},
        {"route_id": "image", "kind": "image"},
        {"route_id": "cinematic", "kind": "cinematic"},
        {"route_id": "mediate", "kind": "custom", "action": "Mediate", "status_effect": "calm"},
    ]
    config = {"scenario_meta": {"world_id": "tidal"}, "actions": {"interaction_affordance_catalog": _interaction_affordance_catalog(routes)}}
    result = audit(config)
    assert result["passed"] is True
