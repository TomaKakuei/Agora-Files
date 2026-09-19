#!/usr/bin/env python3
"""Extract stricter behavioral evidence from AGWRE trajectories.

The original AGWRE score is an execution-contract score.  This extractor keeps
that evidence intact and adds measures that distinguish successful state calls
from sustained, role-conditioned, intervention-sensitive world behavior.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRAJECTORY_ROOT = (
    ROOT
    / "docs"
    / "living_world_benchmark_20260825_hidden"
    / "runtime_trajectories_v2"
)
DEFAULT_OUTPUT = (
    ROOT
    / "docs"
    / "living_world_benchmark_20260825_hidden"
    / "strict_runtime_evidence_v1.json"
)

TOKEN_RE = re.compile(r"[a-z][a-z0-9_-]{2,}")
STOPWORDS = {
    "about", "after", "again", "against", "along", "also", "among", "and",
    "around", "before", "between", "because", "been", "being", "carry", "from",
    "have", "into", "make", "more", "over", "that", "their", "then", "there",
    "these", "they", "this", "through", "under", "with", "within", "world",
    "action", "agent", "main", "keep", "using", "used", "visible", "complete",
}
SUBSTANTIVE_EFFECT_KINDS = {
    "transfer", "create", "create_item", "inventory", "move", "location",
    "relationship", "status", "world_state", "property", "knowledge",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def tokens(value: Any) -> set[str]:
    found = TOKEN_RE.findall(str(value).lower())
    return {token for token in found if token not in STOPWORDS}


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def target(value: float, full_at: float) -> float:
    if full_at <= 0:
        return 0.0
    return clamp01(value / full_at)


def normalized_entropy(counts: Iterable[int]) -> float:
    values = [value for value in counts if value > 0]
    total = sum(values)
    if total <= 0 or len(values) <= 1:
        return 0.0
    entropy = -sum((value / total) * math.log(value / total) for value in values)
    return entropy / math.log(len(values))


def geometric_score(axes: dict[str, float], weights: dict[str, float]) -> float:
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    log_sum = 0.0
    for name, weight in weights.items():
        fraction = max(1e-4, axes[name] / 100.0)
        log_sum += (weight / total) * math.log(fraction)
    return round(100.0 * math.exp(log_sum), 2)


def arithmetic_score(axes: dict[str, float], weights: dict[str, float]) -> float:
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    return round(sum(axes[name] * weight for name, weight in weights.items()) / total, 2)


def role_documents(trajectory_path: Path) -> dict[str, set[str]]:
    documents: dict[str, set[str]] = {}
    for path in sorted((trajectory_path.parent / "scenario" / "Agents").glob("*.json")):
        agent = load_json(path)
        agent_id = str(agent.get("agent_id", ""))
        public = agent.get("public_state") or {}
        parts: list[Any] = [
            public.get("role_name", ""),
            public.get("main_character_archetype", ""),
            public.get("activity_directive", ""),
            agent.get("private_notes", ""),
        ]
        for asset in agent.get("knowledge_assets") or []:
            parts.extend([asset.get("topic", ""), asset.get("summary", "")])
        for asset in agent.get("property_library") or []:
            parts.extend([asset.get("asset_name", ""), asset.get("story_use", "")])
        documents[agent_id] = tokens(" ".join(str(part) for part in parts))
    return documents


def extract_one(path: Path) -> dict[str, Any]:
    trajectory = load_json(path)
    model = str(trajectory.get("model", "unknown"))
    events = trajectory.get("events") or []
    actions = [event for event in events if event.get("event_type") == "model_action"]
    interventions = [event for event in events if event.get("event_type") != "model_action"]
    intervention_ids = {str(event.get("event_id")) for event in interventions}
    intervention_by_type = {
        str(event.get("event_type")): str(event.get("event_id")) for event in interventions
    }

    successful = [event for event in actions if event.get("status") == "success"]
    explicit_refs = [
        str(ref)
        for event in actions
        for ref in (event.get("responds_to_event_ids") or [])
        if str(ref)
    ]
    referenced_interventions = intervention_ids.intersection(explicit_refs)

    approved_proposals = [
        event
        for event in actions
        if (event.get("coordinator_decision") or {}).get("status") == "approved"
    ]
    proposal_effect_sets: list[set[str]] = []
    for event in approved_proposals:
        proposal = (event.get("coordinator_decision") or {}).get("proposal") or {}
        effect_kinds = {
            str(effect.get("kind", "")).lower()
            for effect in (proposal.get("effects") or [])
            if effect.get("kind")
        }
        proposal_effect_sets.append(effect_kinds)
    all_effect_kinds = set().union(*proposal_effect_sets) if proposal_effect_sets else set()
    non_speech_proposals = [kinds for kinds in proposal_effect_sets if kinds - {"speech"}]
    substantive_proposals = [
        kinds for kinds in proposal_effect_sets if kinds.intersection(SUBSTANTIVE_EFFECT_KINDS)
    ]

    thread_buckets: dict[str, set[int]] = defaultdict(set)
    thread_counts: Counter[str] = Counter()
    for event in actions:
        thread_id = str(event.get("thread_id", ""))
        if not thread_id:
            continue
        round_index = int(event.get("round_index") or 0)
        thread_buckets[thread_id].add(max(0, (round_index - 1) // 4))
        thread_counts[thread_id] += 1
    spanning_three = sum(len(buckets) >= 3 for buckets in thread_buckets.values())
    spanning_five = sum(len(buckets) >= 5 for buckets in thread_buckets.values())

    actor_counts = Counter(str(event.get("actor_id", "")) for event in actions)
    target_counts = Counter(
        str(event.get("target_id", "")) for event in actions if event.get("target_id")
    )
    route_ids = {
        str(event.get("route_id", "")) for event in actions if event.get("route_id")
    }
    intent_token_sets = [tokens(event.get("intent_text", "")) for event in actions]
    unique_intents = {
        " ".join(sorted(token_set)) for token_set in intent_token_sets if token_set
    }

    documents = role_documents(path)
    actions_by_actor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in actions:
        actions_by_actor[str(event.get("actor_id", ""))].append(event)
    role_coverages: list[float] = []
    top_role_matches: list[float] = []
    for actor_id, actor_actions in actions_by_actor.items():
        role_tokens = documents.get(actor_id, set())
        action_tokens = set().union(
            *(tokens(event.get("intent_text", "")) for event in actor_actions)
        )
        if role_tokens:
            role_coverages.append(len(role_tokens.intersection(action_tokens)) / len(role_tokens))
        for event in actor_actions:
            event_tokens = tokens(event.get("intent_text", ""))
            if not event_tokens or not documents:
                continue
            overlaps = {
                candidate: len(event_tokens.intersection(candidate_tokens))
                / max(1, len(event_tokens.union(candidate_tokens)))
                for candidate, candidate_tokens in documents.items()
            }
            best = max(overlaps.values(), default=0.0)
            own = overlaps.get(actor_id, 0.0)
            top_role_matches.append(1.0 if best > 0 and own >= best else 0.0)

    mutation_counts: Counter[str] = Counter()
    distinct_status_effects: set[str] = set()
    relationship_deltas: Counter[tuple[int, int, int]] = Counter()
    negative_relationship_updates = 0
    external_state_actions = 0
    for event in successful:
        kinds = {str(kind) for kind in (event.get("mutation_kinds") or [])}
        mutation_counts.update(kinds)
        if kinds.intersection({"inventory", "location"}):
            external_state_actions += 1
        mutations = event.get("mutations") or {}
        for update in mutations.get("profile_updates") or []:
            status = update.get("status_effect_added") or {}
            if status.get("effect"):
                distinct_status_effects.add(str(status["effect"]))
        for update in mutations.get("relationship_tensor_updates") or []:
            before = update.get("before") or {}
            after = update.get("after") or {}
            delta = (
                int(after.get("trust", 0)) - int(before.get("trust", 0)),
                int(after.get("affection", 0)) - int(before.get("affection", 0)),
                int(after.get("influence_fear", 0)) - int(before.get("influence_fear", 0)),
            )
            relationship_deltas[delta] += 1
            if any(value < 0 for value in delta):
                negative_relationship_updates += 1

    human_actions = [
        event
        for event in actions
        if event.get("target_id") == trajectory.get("human_agent_id")
    ]
    human_responders = {str(event.get("actor_id")) for event in human_actions}
    human_event_ids = {
        intervention_by_type.get("human_request", ""),
        intervention_by_type.get("human_followup", ""),
    } - {""}
    human_explicit_refs = human_event_ids.intersection(explicit_refs)

    rejected_model_actions = [event for event in actions if event.get("status") != "success"]
    model_declines = [
        event
        for event in actions
        if ((event.get("coordinator_decision") or {}).get("proposal") or {}).get(
            "target_response"
        )
        in {"reject", "decline"}
    ]
    failed_action_ids = {str(event.get("event_id")) for event in rejected_model_actions}
    recovered_failures = failed_action_ids.intersection(explicit_refs)

    move_events = [event for event in successful if event.get("action_type") == "move"]
    moved_actors_with_later_action = 0
    for move in move_events:
        actor_id = move.get("actor_id")
        round_index = int(move.get("round_index") or 0)
        if any(
            later.get("actor_id") == actor_id
            and int(later.get("round_index") or 0) > round_index
            and later.get("action_type") != "move"
            for later in actions
        ):
            moved_actors_with_later_action += 1

    raw = {
        "actions": len(actions),
        "success_rate": len(successful) / max(1, len(actions)),
        "intervention_count": len(interventions),
        "intervention_reference_coverage": len(referenced_interventions)
        / max(1, len(intervention_ids)),
        "explicit_intervention_reference_count": sum(
            ref in intervention_ids for ref in explicit_refs
        ),
        "human_event_reference_coverage": len(human_explicit_refs)
        / max(1, len(human_event_ids)),
        "approved_proposal_count": len(approved_proposals),
        "non_speech_proposal_rate": len(non_speech_proposals)
        / max(1, len(approved_proposals)),
        "substantive_proposal_count": len(substantive_proposals),
        "proposal_effect_kind_count": len(all_effect_kinds),
        "spanning_three_checkpoint_threads": spanning_three,
        "spanning_five_checkpoint_threads": spanning_five,
        "thread_count": len(thread_buckets),
        "actor_participation_entropy": normalized_entropy(actor_counts.values()),
        "target_entropy": normalized_entropy(target_counts.values()),
        "unique_route_count": len(route_ids),
        "unique_intent_rate": len(unique_intents) / max(1, len(actions)),
        "mean_role_vocabulary_coverage": mean(role_coverages) if role_coverages else 0.0,
        "role_top_match_rate": mean(top_role_matches) if top_role_matches else 0.0,
        "external_state_action_rate": external_state_actions / max(1, len(successful)),
        "mutation_kind_count": len(mutation_counts),
        "distinct_status_effect_count": len(distinct_status_effects),
        "relationship_delta_pattern_count": len(relationship_deltas),
        "negative_relationship_update_count": negative_relationship_updates,
        "human_target_action_count": len(human_actions),
        "human_responder_count": len(human_responders),
        "failed_model_action_count": len(rejected_model_actions),
        "model_decline_count": len(model_declines),
        "recovered_failed_action_count": len(recovered_failures),
        "successful_move_count": len(move_events),
        "moved_actor_later_action_rate": moved_actors_with_later_action
        / max(1, len(move_events)),
    }

    axes = {
        "intervention_sensitivity": 100
        * (
            0.55 * raw["intervention_reference_coverage"]
            + 0.25 * target(raw["explicit_intervention_reference_count"], 10)
            + 0.20 * raw["human_event_reference_coverage"]
        ),
        "causal_threading": 100
        * (
            0.45 * target(raw["spanning_three_checkpoint_threads"], 4)
            + 0.30 * target(raw["spanning_five_checkpoint_threads"], 2)
            + 0.25 * target(raw["explicit_intervention_reference_count"], 12)
        ),
        "role_conditioning": 100
        * (
            0.55 * target(raw["mean_role_vocabulary_coverage"], 0.30)
            + 0.45 * target(raw["role_top_match_rate"], 0.55)
        ),
        "open_action_substance": 100
        * (
            0.45 * target(raw["non_speech_proposal_rate"], 0.65)
            + 0.30 * target(raw["proposal_effect_kind_count"], 4)
            + 0.25 * target(raw["substantive_proposal_count"], 8)
        ),
        "state_evolution": 100
        * (
            0.40 * target(raw["external_state_action_rate"], 0.25)
            + 0.20 * target(raw["mutation_kind_count"], 4)
            + 0.20 * target(raw["relationship_delta_pattern_count"], 4)
            + 0.20 * target(raw["negative_relationship_update_count"], 4)
        ),
        "social_differentiation": 100
        * (
            0.35 * raw["actor_participation_entropy"]
            + 0.25 * raw["target_entropy"]
            + 0.20 * target(raw["relationship_delta_pattern_count"], 4)
            + 0.20 * target(raw["model_decline_count"], 3)
        ),
        "human_impact": 100
        * (
            0.40 * raw["human_event_reference_coverage"]
            + 0.30 * target(raw["human_target_action_count"], 8)
            + 0.30 * target(raw["human_responder_count"], 4)
        ),
        "conflict_and_recovery": 100
        * (
            0.35 * target(raw["model_decline_count"], 3)
            + 0.30 * target(raw["recovered_failed_action_count"], 3)
            + 0.35 * target(raw["negative_relationship_update_count"], 4)
        ),
        "behavioral_specificity": 100
        * (
            0.35 * target(raw["unique_route_count"], 28)
            + 0.35 * raw["unique_intent_rate"]
            + 0.30 * target(raw["distinct_status_effect_count"], 24)
        ),
        "spatial_causality": 100
        * (
            0.45 * target(raw["successful_move_count"], 8)
            + 0.55 * raw["moved_actor_later_action_rate"]
        ),
    }
    axes = {name: round(clamp01(value / 100.0) * 100.0, 2) for name, value in axes.items()}
    axis_weights = {
        "intervention_sensitivity": 0.14,
        "causal_threading": 0.12,
        "role_conditioning": 0.10,
        "open_action_substance": 0.14,
        "state_evolution": 0.12,
        "social_differentiation": 0.10,
        "human_impact": 0.12,
        "conflict_and_recovery": 0.08,
        "behavioral_specificity": 0.04,
        "spatial_causality": 0.04,
    }
    arithmetic = arithmetic_score(axes, axis_weights)
    cap = 100.0
    cap_reasons: list[str] = []
    if not human_actions:
        cap = min(cap, 49.0)
        cap_reasons.append("no successful or attempted human-target action")
    if approved_proposals and not non_speech_proposals:
        cap = min(cap, 64.0)
        cap_reasons.append("all approved open proposals are speech-only")
    if raw["external_state_action_rate"] < 0.10:
        cap = min(cap, 74.0)
        cap_reasons.append("fewer than 10% of successful actions alter inventory or location")

    return {
        "model": model,
        "replicate": path.parts[-3],
        "trajectory_path": str(path.relative_to(ROOT)),
        "raw": {name: round(value, 4) if isinstance(value, float) else value for name, value in raw.items()},
        "axes": axes,
        "strict_trace_objective": round(min(arithmetic, cap), 2),
        "uncapped_arithmetic_score": arithmetic,
        "geometric_diagnostic": geometric_score(axes, axis_weights),
        "score_cap": cap,
        "cap_reasons": cap_reasons,
        "examples": {
            "intervention_responses": [
                {
                    "round": event.get("round_index"),
                    "actor": event.get("actor_id"),
                    "references": [
                        ref
                        for ref in (event.get("responds_to_event_ids") or [])
                        if ref in intervention_ids
                    ],
                    "intent": event.get("intent_text", ""),
                    "expected_consequence": event.get("expected_world_consequence", ""),
                    "status": event.get("status"),
                }
                for event in actions
                if intervention_ids.intersection(event.get("responds_to_event_ids") or [])
            ][:12],
            "approved_proposals": [
                {
                    "round": event.get("round_index"),
                    "actor": event.get("actor_id"),
                    "thread": event.get("thread_id"),
                    "name": ((event.get("coordinator_decision") or {}).get("proposal") or {}).get(
                        "action_name", ""
                    ),
                    "rationale": ((event.get("coordinator_decision") or {}).get("proposal") or {}).get(
                        "rationale", ""
                    ),
                    "effect_kinds": sorted(
                        {
                            effect.get("kind", "")
                            for effect in (
                                ((event.get("coordinator_decision") or {}).get("proposal") or {}).get(
                                    "effects"
                                )
                                or []
                            )
                        }
                    ),
                }
                for event in approved_proposals
            ][:12],
            "failed_actions": [
                {
                    "round": event.get("round_index"),
                    "actor": event.get("actor_id"),
                    "action_type": event.get("action_type"),
                    "intent": event.get("intent_text", ""),
                    "reason": event.get("reason", ""),
                    "violations": event.get("violations") or [],
                }
                for event in rejected_model_actions
            ][:8],
            "deep_threads": [
                {
                    "thread": thread_id,
                    "checkpoint_count": len(thread_buckets[thread_id]),
                    "action_count": thread_counts[thread_id],
                    "intents": [
                        event.get("intent_text", "")
                        for event in actions
                        if event.get("thread_id") == thread_id
                    ][:8],
                }
                for thread_id in sorted(
                    thread_buckets,
                    key=lambda item: (len(thread_buckets[item]), thread_counts[item]),
                    reverse=True,
                )
            ][:4],
        },
    }


def aggregate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["model"]].append(record)
    ranking: list[dict[str, Any]] = []
    for model, model_records in grouped.items():
        axis_names = model_records[0]["axes"].keys()
        raw_names = model_records[0]["raw"].keys()
        scores = [record["strict_trace_objective"] for record in model_records]
        ranking.append(
            {
                "model": model,
                "strict_trace_objective": round(mean(scores), 2),
                "score_stddev": round(pstdev(scores), 2),
                "replicate_scores": scores,
                "mean_uncapped_arithmetic_score": round(
                    mean(record["uncapped_arithmetic_score"] for record in model_records), 2
                ),
                "mean_geometric_diagnostic": round(
                    mean(record["geometric_diagnostic"] for record in model_records), 2
                ),
                "cap_reasons_by_replicate": [
                    record["cap_reasons"] for record in model_records
                ],
                "axes": {
                    name: round(mean(record["axes"][name] for record in model_records), 2)
                    for name in axis_names
                },
                "raw_means": {
                    name: round(mean(record["raw"][name] for record in model_records), 4)
                    for name in raw_names
                },
                "replicates": model_records,
            }
        )
    return sorted(ranking, key=lambda row: row["strict_trace_objective"], reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trajectory-root", type=Path, default=DEFAULT_TRAJECTORY_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    paths = sorted(args.trajectory_root.glob("replicate_*/*/trajectory.json"))
    records = [extract_one(path) for path in paths]
    payload = {
        "benchmark": "Agora strict runtime evidence",
        "version": "strict-runtime-evidence-v1",
        "construct": (
            "Long-horizon causal, social, human-responsive, and open-action quality; "
            "supplementary to AGWRE execution compliance"
        ),
        "trajectory_count": len(records),
        "ranking": aggregate(records),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "trajectory_count": len(records)}, indent=2))


if __name__ == "__main__":
    main()
