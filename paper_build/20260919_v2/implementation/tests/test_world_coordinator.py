from agora_ui.adjudicator_schemas import (
    ActionIntentSpec,
    AdjudicatorControlSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    WorldRulesSpec,
)
from agora_ui.universal_adjudicator.handlers_custom import _handle_custom
from agora_ui.world_coordinator import evaluate_open_action, proposal_route


def _agent(agent_id: str, *, item_id: str = "", quantity: int = 0) -> AgentRuntimeProfileSpec:
    inventory = [{"item_id": item_id, "quantity": quantity}] if item_id else []
    return AgentRuntimeProfileSpec.model_validate(
        {
            "agent_id": agent_id,
            "display_name": agent_id,
            "coordinates": {"x": 0, "y": 0, "z": 0},
            "room_id": "room",
            "inventory": inventory,
        }
    )


def test_coordinator_allows_unfair_but_accepted_trade() -> None:
    actor = _agent("actor", item_id="gold", quantity=10)
    target = _agent("target", item_id="relic", quantity=1)
    state = AgentStateBundleSpec(agents=[actor, target])
    decision = evaluate_open_action(
        {
            "action_name": "Absurd Relic Deal",
            "action_text": "Offer ten gold for one chipped relic.",
            "target_agent_id": "target",
            "target_response": "accept",
            "effects": [
                {"kind": "transfer", "source_agent_id": "actor", "target_agent_id": "target", "item_id": "gold", "quantity": 10},
                {"kind": "transfer", "source_agent_id": "target", "target_agent_id": "actor", "item_id": "relic", "quantity": 1},
            ],
        },
        actor=actor,
        target=target,
        state=state,
        config={},
    )
    assert decision.status == "approved"
    assert proposal_route(decision)["route_id"] == "proposed_absurd_relic_deal"


def test_coordinator_rejects_trade_without_consent() -> None:
    actor = _agent("actor")
    target = _agent("target", item_id="relic", quantity=1)
    state = AgentStateBundleSpec(agents=[actor, target])
    decision = evaluate_open_action(
        {
            "action_name": "Take Relic",
            "action_text": "Take the relic without agreement.",
            "target_agent_id": "target",
            "target_response": "unknown",
            "effects": [{"kind": "transfer", "source_agent_id": "target", "target_agent_id": "actor", "item_id": "relic"}],
        },
        actor=actor,
        target=target,
        state=state,
        config={},
    )
    assert decision.status == "rejected"
    assert decision.checks["consent_for_exchange"] is False


def test_coordinator_allows_bounded_object_creation() -> None:
    actor = _agent("actor", item_id="paper", quantity=1)
    target = _agent("target")
    state = AgentStateBundleSpec(agents=[actor, target])
    decision = evaluate_open_action(
        {
            "action_name": "Fold Treaty Bird",
            "action_text": "Fold the paper into a treaty-carrying bird.",
            "target_agent_id": "target",
            "target_response": "not_required",
            "effects": [
                {
                    "kind": "create_item",
                    "item_id": "treaty_bird",
                    "item_name": "Treaty Bird",
                    "item_description": "A paper bird made to carry one diplomatic note.",
                    "input_item_ids": ["paper"],
                }
            ],
        },
        actor=actor,
        target=target,
        state=state,
        config={},
    )
    assert decision.status == "approved"


def test_coordinator_rejects_effect_kind_disabled_by_world() -> None:
    actor = _agent("actor", item_id="paper", quantity=1)
    target = _agent("target")
    state = AgentStateBundleSpec(agents=[actor, target])
    decision = evaluate_open_action(
        {
            "action_name": "Fold Treaty Bird",
            "action_text": "Fold the paper into a treaty-carrying bird.",
            "target_agent_id": "target",
            "target_response": "not_required",
            "effects": [
                {
                    "kind": "create_item",
                    "item_id": "treaty_bird",
                    "item_name": "Treaty Bird",
                    "item_description": "A paper bird made to carry one diplomatic note.",
                    "input_item_ids": ["paper"],
                }
            ],
        },
        actor=actor,
        target=target,
        state=state,
        config={
            "world_rules": {
                "custom_action_rules": {
                    "open_proposals_enabled": True,
                    "open_proposal_effects": ["speech"],
                }
            }
        },
    )

    assert decision.status == "rejected"
    assert decision.checks["effect_kinds_allowed"] is False


def test_approved_unfair_trade_commits_atomically_in_fixed_world() -> None:
    actor = _agent("actor", item_id="gold", quantity=10)
    target = _agent("target", item_id="relic", quantity=1)
    state = AgentStateBundleSpec(agents=[actor, target])
    proposal = {
        "action_name": "Absurd Relic Deal",
        "action_text": "Trade ten gold for one chipped relic.",
        "target_agent_id": "target",
        "target_response": "accept",
        "effects": [
            {"kind": "transfer", "source_agent_id": "actor", "target_agent_id": "target", "item_id": "gold", "quantity": 10},
            {"kind": "transfer", "source_agent_id": "target", "target_agent_id": "actor", "item_id": "relic", "quantity": 1},
        ],
    }
    decision = evaluate_open_action(proposal, actor=actor, target=target, state=state, config={})
    intent = ActionIntentSpec(
        intent_id="proposal_1",
        agent_id="actor",
        target_agent_id="target",
        call="Custom",
        action="Absurd Relic Deal",
        metadata={"open_action_proposal": proposal, "coordinator_decision": decision.model_dump()},
    )
    mutations = {
        "action_results": [],
        "profile_updates": [],
        "relationship_updates": [],
        "relationship_tensor_updates": [],
        "inventory_updates": [],
    }
    _handle_custom(
        control=AdjudicatorControlSpec(world_description="world", simulation_objective="test"),
        world_rules=WorldRulesSpec(world_mode="Fixed"),
        state=state,
        agents={"actor": actor, "target": target},
        start_positions={"actor": actor.coordinates.model_copy(), "target": target.coordinates.model_copy()},
        moved_agent_ids=set(),
        intent=intent,
        broadcasts=[],
        mutations=mutations,
        rule_appendices=[],
    )
    assert not actor.inventory or all(item.item_id != "gold" for item in actor.inventory)
    assert any(item.item_id == "relic" for item in actor.inventory)
    assert any(item.item_id == "gold" and item.quantity == 10 for item in target.inventory)
    assert mutations["action_results"][0]["status"] == "success"
