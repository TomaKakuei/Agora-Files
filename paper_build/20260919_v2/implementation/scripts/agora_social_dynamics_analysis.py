#!/usr/bin/env python3
"""Compute deterministic social-dynamics measures from Agora story logs."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_story(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("stories"), list):
        raise ValueError(f"not an Agora story bundle: {path}")
    return payload


def entropy(counts: Counter[str]) -> float:
    total = sum(counts.values())
    return -sum((n / total) * math.log2(n / total) for n in counts.values()) if total else 0.0


def largest_component(edges: set[tuple[str, str]], nodes: set[str]) -> int:
    graph: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        graph[source].add(target)
        graph[target].add(source)
    remaining = set(nodes)
    largest = 0
    while remaining:
        stack = [remaining.pop()]
        size = 0
        while stack:
            node = stack.pop()
            size += 1
            unseen = graph[node] & remaining
            remaining.difference_update(unseen)
            stack.extend(unseen)
        largest = max(largest, size)
    return largest


def analyze(path: Path) -> dict[str, Any]:
    payload = load_story(path)
    stories = [event for event in payload["stories"] if isinstance(event, dict)]
    nodes: set[str] = set()
    edges: set[tuple[str, str]] = set()
    dyad_counts: Counter[tuple[str, str]] = Counter()
    routes: Counter[str] = Counter()
    rooms: Counter[str] = Counter()
    relation_totals = Counter()
    rounds: dict[int, list[dict[str, Any]]] = defaultdict(list)
    world_id = str(payload.get("scenario_meta", {}).get("world_id", "")).strip()
    identity_violations: set[str] = set()

    for event in stories:
        actor = str(event.get("actor_id", ""))
        target = str(event.get("target_id", ""))
        if actor:
            nodes.add(actor)
        if target:
            nodes.add(target)
        for agent_id in (actor, target):
            if agent_id and agent_id != "human_interactor" and world_id and not agent_id.startswith(f"{world_id}_"):
                identity_violations.add(agent_id)
        if actor and target and actor != target:
            dyad = tuple(sorted((actor, target)))
            edges.add(dyad)
            dyad_counts[dyad] += 1
        routes[str(event.get("route_id", event.get("kind", "unknown")))] += 1
        rooms[str(event.get("actor_room_id", "unknown"))] += 1
        rounds[int(event.get("round_index", 0) or 0)].append(event)
        for delta in event.get("relationship_adjustments", []):
            if isinstance(delta, dict):
                relation_totals["trust"] += int(delta.get("trust_delta", 0) or 0)
                relation_totals["affection"] += int(delta.get("affection_delta", 0) or 0)
                relation_totals["influence_fear"] += int(delta.get("influence_fear_delta", 0) or 0)

    cumulative_edges: set[tuple[str, str]] = set()
    cumulative_nodes: set[str] = set()
    round_dynamics = []
    for round_index in sorted(rounds):
        round_routes: Counter[str] = Counter()
        for event in rounds[round_index]:
            actor, target = str(event.get("actor_id", "")), str(event.get("target_id", ""))
            cumulative_nodes.update(x for x in (actor, target) if x)
            if actor and target and actor != target:
                cumulative_edges.add(tuple(sorted((actor, target))))
            round_routes[str(event.get("route_id", event.get("kind", "unknown")))] += 1
        round_dynamics.append({
            "round": round_index,
            "events": len(rounds[round_index]),
            "cumulative_unique_dyads": len(cumulative_edges),
            "largest_component": largest_component(cumulative_edges, cumulative_nodes),
            "route_entropy_bits": round(entropy(round_routes), 3),
        })

    repeated_events = sum(count - 1 for count in dyad_counts.values() if count > 1)
    proposal_events = sum(count for route, count in routes.items() if route.startswith("proposed_"))
    world_action_events = sum(count for route, count in routes.items() if route.startswith("world_action_"))
    human_events = sum(
        1 for event in stories
        if "human_interactor" in {str(event.get("actor_id", "")), str(event.get("target_id", ""))}
    )
    result_counts = Counter()
    for summary in payload.get("round_summaries", []):
        if isinstance(summary, dict):
            result_counts["success"] += int(summary.get("action_success_count", 0) or 0)
            result_counts["total"] += int(summary.get("action_result_count", 0) or 0)
    return {
        "source": str(path),
        "run_id": payload.get("run_id", ""),
        "world_name": payload.get("scenario_meta", {}).get("world_name", ""),
        "rounds": len(rounds),
        "events": len(stories),
        "observed_agents": len(nodes),
        "unique_dyads": len(edges),
        "repeated_dyad_event_fraction": round(repeated_events / len(stories), 4) if stories else 0.0,
        "largest_component": largest_component(edges, nodes),
        "route_entropy_bits": round(entropy(routes), 3),
        "open_proposal_events": proposal_events,
        "world_action_events": world_action_events,
        "human_interaction_events": human_events,
        "action_success_rate": round(result_counts["success"] / result_counts["total"], 4) if result_counts["total"] else 0.0,
        "identity_audit": {"passed": not identity_violations, "unexpected_agent_ids": sorted(identity_violations)},
        "route_counts": dict(routes.most_common()),
        "room_event_counts": dict(rooms.most_common()),
        "relationship_delta_totals": dict(relation_totals),
        "round_dynamics": round_dynamics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stories", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runs = [analyze(path.resolve()) for path in args.stories]
    totals = Counter()
    for run in runs:
        for key in ("events", "unique_dyads", "open_proposal_events", "world_action_events", "human_interaction_events"):
            totals[key] += int(run[key])
    total_results = sum(
        sum(int(summary.get("action_result_count", 0) or 0) for summary in load_story(path.resolve()).get("round_summaries", []) if isinstance(summary, dict))
        for path in args.stories
    )
    total_successes = sum(
        sum(int(summary.get("action_success_count", 0) or 0) for summary in load_story(path.resolve()).get("round_summaries", []) if isinstance(summary, dict))
        for path in args.stories
    )
    result = {
        "runs": runs,
        "aggregate": {
            "worlds": len(runs),
            **dict(totals),
            "action_success_rate": round(total_successes / total_results, 4) if total_results else 0.0,
            "identity_audit_passed": all(run["identity_audit"]["passed"] for run in runs),
        },
    }
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
