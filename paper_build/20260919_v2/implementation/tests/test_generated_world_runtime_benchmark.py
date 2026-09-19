from __future__ import annotations

from agora_ui.adjudicator_schemas import AgentRuntimeProfileSpec, AgentStateBundleSpec
from scripts.agora_generated_world_runtime_benchmark import (
    _intervention,
    aggregate_replicate_scores,
    score_trajectory,
)


def _oracle_trajectory() -> dict:
    agents = [f"agent_{index:02d}" for index in range(12)]
    events = [
        {
            "event_id": "human_request_r05",
            "round_index": 5,
            "event_type": "human_request",
            "status": "active",
        },
        {
            "event_id": "coordinator_rejection_r09",
            "round_index": 9,
            "event_type": "coordinator_rejection",
            "status": "rejected",
            "state_changed": False,
        },
        {
            "event_id": "human_followup_r21",
            "round_index": 21,
            "event_type": "human_followup",
            "status": "active",
        },
    ]
    proposal_index = 0
    for round_index in range(1, 25):
        for slot in range(3):
            actor_index = (round_index * 3 + slot) % len(agents)
            actor = agents[actor_index]
            target = agents[(actor_index + 1 + slot) % len(agents)]
            action_type = "catalog"
            route_id = "world_action_specific_route"
            mutation_kinds = ["status", "relationship"]
            extra = {}
            if slot == 0 and round_index % 4 == 1:
                action_type = "move"
                route_id = "move_to_next_thread"
                mutation_kinds = ["location"]
                extra["destination_room_id"] = f"room_{1 + proposal_index % 4}"
            elif slot == 1 and round_index in {2, 6, 10, 14, 18, 22}:
                action_type = "propose"
                route_id = ""
                kinds = ["speech", "status", "create_item"][proposal_index % 3]
                mutation_kinds = ["status", "relationship"] + (["inventory"] if kinds == "create_item" else [])
                extra.update({
                    "proposal_name": f"World Specific Proposal {proposal_index}",
                    "proposal_effect_kinds": [kinds],
                    "coordinator_decision": {"status": "approved", "checks": {"ownership": True}},
                })
                proposal_index += 1
            references = []
            if round_index == 5 and slot == 2:
                target = "human_interactor"
                references = ["human_request_r05"]
            elif round_index == 10 and slot == 1:
                references = ["coordinator_rejection_r09"]
            elif round_index in {21, 22, 23} and slot == 2:
                target = "human_interactor"
                references = ["human_followup_r21"]
            events.append({
                "event_id": f"event_{round_index}_{slot}",
                "round_index": round_index,
                "event_type": "model_action",
                "status": "success",
                "action_type": action_type,
                "actor_id": actor,
                "target_id": target,
                "route_id": route_id,
                "thread_id": f"thread_{slot}",
                "responds_to_event_ids": references,
                "violations": [],
                "state_changed": True,
                "mutation_kinds": mutation_kinds,
                **extra,
            })
    return {
        "completed_checkpoints": 6,
        "room_count": 6,
        "ai_agent_ids": agents,
        "human_agent_id": "human_interactor",
        "events": events,
        "persistence_check": {"roundtrip_equal": True},
        "final_observations": {"relationship_edge_count": 24},
    }


def test_oracle_trajectory_can_exceed_ninety() -> None:
    score = score_trajectory(_oracle_trajectory())

    assert score["score"] >= 90
    assert score["score_cap"] == 100
    assert score["observations"]["active_round_count"] == 24
    assert score["observations"]["recovery_actions"] == 1


def test_incomplete_noninteractive_trajectory_is_capped() -> None:
    trajectory = _oracle_trajectory()
    trajectory["completed_checkpoints"] = 2
    trajectory["events"] = [
        event
        for event in trajectory["events"]
        if event.get("event_type") != "model_action" or event.get("round_index", 0) <= 8
    ]
    for event in trajectory["events"]:
        if event.get("event_type") == "model_action":
            event["target_id"] = "agent_00"
            event["responds_to_event_ids"] = []

    score = score_trajectory(trajectory)

    assert score["score"] <= 49
    assert "incomplete_24_round_policy" in score["cap_reasons"]
    assert "no_substantive_human_uptake" in score["cap_reasons"]


def test_rejection_intervention_handles_human_alone_in_room() -> None:
    state = AgentStateBundleSpec(agents=[
        AgentRuntimeProfileSpec(
            agent_id="human_interactor",
            room_id="human_room",
            coordinates={"x": 0, "y": 0, "z": 0},
        ),
        AgentRuntimeProfileSpec(
            agent_id="agent_01",
            room_id="remote_room",
            coordinates={"x": 10, "y": 10, "z": 0},
        ),
    ])
    config = {
        "human_interaction": {"runtime_human_agent_id": "human_interactor"},
        "world_rules": {"custom_action_rules": {"open_proposals_enabled": True}},
    }
    events = []

    event = _intervention(9, state=state, config=config, events=events)

    assert event is not None
    assert event["status"] == "rejected"
    assert event["state_changed"] is False
    assert events[0]["event_type"] == "human_movement"
    assert state.agents[0].room_id == "remote_room"
    assert event["decision"]["checks"]["same_room_for_physical_effects"] is True


def test_missing_recovery_reduces_axis_without_hard_cap() -> None:
    trajectory = _oracle_trajectory()
    for event in trajectory["events"]:
        if event.get("event_type") == "model_action":
            event["responds_to_event_ids"] = [
                event_id for event_id in event.get("responds_to_event_ids", [])
                if event_id != "coordinator_rejection_r09"
            ]

    score = score_trajectory(trajectory)

    assert score["score_cap"] == 100
    assert score["observations"]["recovery_actions"] == 0
    assert score["axes"]["open_action_recovery"] < 100


def test_replicate_aggregate_reports_variation_and_total_evidence() -> None:
    first = score_trajectory(_oracle_trajectory())
    second_trajectory = _oracle_trajectory()
    second_trajectory["events"] = [
        event for event in second_trajectory["events"]
        if event.get("event_type") != "model_action" or event.get("round_index", 0) <= 20
    ]
    second_trajectory["completed_checkpoints"] = 5
    second = score_trajectory(second_trajectory)
    second["observations"]["human_event_responses"] = 0

    aggregate = aggregate_replicate_scores([first, second])

    assert aggregate["replicate_count"] == 2
    assert aggregate["score_stddev"] > 0
    assert aggregate["observations"]["actions_planned"] == 132
    assert aggregate["observations"]["human_successful_replicates"] == 1
