#!/usr/bin/env python3
"""Run and score Agora's evidence-grounded community micro-benchmark."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora_ui.vertex_json_client import VertexJsonClient
from agora_ui.openai_responses_client import OpenAIResponsesJsonClient


DEFAULT_SUITE = ROOT / "docs" / "community_performance_benchmark_20260824" / "micro_scenarios.json"
DEFAULT_MODELS = (
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.7-flash",
    "gemini-3.1-pro-preview",
)
SCORING_VERSION = "acpb.scorer.v1.1"

AXIS_WEIGHTS = {
    "participation_and_human_uptake": 0.13,
    "interaction_topology": 0.11,
    "cross_group_bridging": 0.11,
    "relational_continuity": 0.12,
    "collective_coordination": 0.17,
    "world_grounded_agency": 0.15,
    "open_action_quality": 0.11,
    "institutional_integrity": 0.10,
}

def _plan_schema() -> dict[str, Any]:
    string_array = {"type": "array", "items": {"type": "string"}}
    action_fields = [
        "actor_id",
        "target_id",
        "action_type",
        "catalog_action_id",
        "proposal",
        "thread_id",
        "task_id",
        "contribution_ids",
        "fact_ids",
        "input_object_ids",
        "output_object_ids",
        "world_detail_ids",
        "intended_role_ids",
        "addresses_human_intent",
        "consent_basis",
        "expected_effect",
    ]
    return {
        "type": "object",
        "required": ["actions"],
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": action_fields,
                    "properties": {
                        "actor_id": {"type": "string"},
                        "target_id": {"type": "string"},
                        "action_type": {"type": "string", "enum": ["catalog", "propose"]},
                        "catalog_action_id": {"type": "string"},
                        "proposal": {
                            "type": "object",
                            "required": ["verb", "scope", "bounded_effect", "requires_consent"],
                            "properties": {
                                "verb": {"type": "string"},
                                "scope": {"type": "string", "enum": ["target", "room", "local"]},
                                "bounded_effect": {"type": "boolean"},
                                "requires_consent": {"type": "boolean"},
                            },
                        },
                        "thread_id": {"type": "string"},
                        "task_id": {"type": "string"},
                        "contribution_ids": string_array,
                        "fact_ids": string_array,
                        "input_object_ids": string_array,
                        "output_object_ids": string_array,
                        "world_detail_ids": string_array,
                        "intended_role_ids": string_array,
                        "addresses_human_intent": {"type": "boolean"},
                        "consent_basis": {"type": "string"},
                        "expected_effect": {"type": "string"},
                    },
                },
            }
        },
    }


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _mean(values: Iterable[float], default: float = 0.0) -> float:
    items = list(values)
    return statistics.fmean(items) if items else default


def _normalized_entropy(values: Iterable[str], support_size: int) -> float:
    counts = Counter(value for value in values if value)
    total = sum(counts.values())
    if total <= 1 or support_size <= 1:
        return 0.0
    raw = -sum((count / total) * math.log(count / total) for count in counts.values())
    return _clip(raw / math.log(min(support_size, total)))


def _id_set(items: Any, key: str = "id") -> set[str]:
    if not isinstance(items, list):
        return set()
    return {
        str(item.get(key, "")).strip()
        for item in items
        if isinstance(item, dict) and str(item.get(key, "")).strip()
    }


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _geometric_profile(axis_scores: dict[str, float]) -> float:
    log_score = 0.0
    for axis, weight in AXIS_WEIGHTS.items():
        normalized = max(0.01, float(axis_scores.get(axis, 0.0)) / 100.0)
        log_score += weight * math.log(normalized)
    return 100.0 * math.exp(log_score)


def _bridge_score(rate: float) -> float:
    """Reward cross-group contact monotonically, saturating at half of social actions."""
    return _clip(rate / 0.5)


def score_plan(scenario: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Score one structured community plan without an LLM judge."""
    raw_actions = plan.get("actions", []) if isinstance(plan, dict) else []
    actions = [item for item in raw_actions if isinstance(item, dict)] if isinstance(raw_actions, list) else []

    agents = [item for item in scenario.get("agents", []) if isinstance(item, dict)]
    agent_by_id = {str(item.get("id", "")): item for item in agents if str(item.get("id", ""))}
    expected_actors = set(agent_by_id)
    human = scenario.get("human_player", {}) if isinstance(scenario.get("human_player"), dict) else {}
    human_id = str(human.get("id", "human_player")).strip() or "human_player"
    all_participants = expected_actors | {human_id}
    role_by_agent = {agent_id: str(agent.get("role_id", "")) for agent_id, agent in agent_by_id.items()}
    group_by_agent = {agent_id: str(agent.get("group_id", "")) for agent_id, agent in agent_by_id.items()}

    facts = {
        str(item.get("id", "")): item
        for item in scenario.get("facts", [])
        if isinstance(item, dict) and str(item.get("id", ""))
    }
    objects = {
        str(item.get("id", "")): item
        for item in scenario.get("objects", [])
        if isinstance(item, dict) and str(item.get("id", ""))
    }
    catalog_actions = {
        str(item.get("id", "")): item
        for item in scenario.get("catalog_actions", [])
        if isinstance(item, dict) and str(item.get("id", ""))
    }
    affordance_ids = set(catalog_actions)
    world_detail_ids = _id_set(scenario.get("world_details", []))
    creatable_ids = set(_str_list(scenario.get("creatable_object_ids", [])))
    threads = {
        str(item.get("id", "")): item
        for item in scenario.get("threads", [])
        if isinstance(item, dict) and str(item.get("id", ""))
    }
    tasks = {
        str(item.get("id", "")): item
        for item in scenario.get("tasks", [])
        if isinstance(item, dict) and str(item.get("id", ""))
    }
    contributions: dict[str, dict[str, Any]] = {}
    contribution_task: dict[str, str] = {}
    for task_id, task in tasks.items():
        for item in task.get("contributions", []):
            if isinstance(item, dict) and str(item.get("id", "")):
                contribution_id = str(item["id"])
                contributions[contribution_id] = item
                contribution_task[contribution_id] = task_id

    actor_counts = Counter(str(action.get("actor_id", "")).strip() for action in actions)
    valid_actor_actions = [
        action for action in actions
        if str(action.get("actor_id", "")).strip() in expected_actors
    ]
    represented_actors = set(actor_counts) & expected_actors
    actor_coverage = len(represented_actors) / len(expected_actors) if expected_actors else 0.0
    exactly_once = _mean(actor_counts.get(actor_id, 0) == 1 for actor_id in expected_actors)
    human_uptake = any(
        str(action.get("target_id", "")).strip() == human_id
        and bool(action.get("addresses_human_intent"))
        for action in valid_actor_actions
    )
    participation = 0.60 * actor_coverage + 0.20 * exactly_once + 0.20 * float(human_uptake)

    valid_social_actions = [
        action for action in valid_actor_actions
        if str(action.get("target_id", "")).strip() in all_participants
        and str(action.get("target_id", "")).strip() != str(action.get("actor_id", "")).strip()
    ]
    targets = [str(action.get("target_id", "")).strip() for action in valid_social_actions]
    target_entropy = _normalized_entropy(targets, len(all_participants) - 1)
    target_breadth = len(set(targets)) / min(max(1, len(valid_social_actions)), max(1, len(all_participants) - 1))
    topology = 0.60 * target_entropy + 0.40 * target_breadth

    group_edges: list[tuple[str, str]] = []
    for action in valid_social_actions:
        actor_id = str(action.get("actor_id", "")).strip()
        target_id = str(action.get("target_id", "")).strip()
        if target_id not in expected_actors:
            continue
        actor_group = group_by_agent.get(actor_id, "")
        target_group = group_by_agent.get(target_id, "")
        if actor_group and target_group:
            group_edges.append(tuple(sorted((actor_group, target_group))))
    bridge_count = sum(source != target for source, target in group_edges)
    bridge_rate = bridge_count / len(group_edges) if group_edges else 0.0
    distinct_bridge_pairs = {edge for edge in group_edges if edge[0] != edge[1]}
    bridge_pair_target = max(1, int(scenario.get("bridge_pair_target", 2)))
    bridging = 0.70 * _bridge_score(bridge_rate) + 0.30 * _clip(
        len(distinct_bridge_pairs) / bridge_pair_target
    )

    thread_eligible = {
        agent_id
        for agent_id in expected_actors
        if any(agent_id in _str_list(thread.get("participants", [])) for thread in threads.values())
    }
    thread_followthrough: list[float] = []
    for actor_id in thread_eligible:
        actor_actions = [action for action in valid_actor_actions if str(action.get("actor_id", "")).strip() == actor_id]
        valid_thread = any(
            str(action.get("thread_id", "")).strip() in threads
            and actor_id in _str_list(threads[str(action.get("thread_id", "")).strip()].get("participants", []))
            for action in actor_actions
            if str(action.get("thread_id", "")).strip()
        )
        thread_followthrough.append(float(valid_thread))
    prior_dyads = {
        tuple(sorted((str(pair[0]), str(pair[1]))))
        for pair in scenario.get("prior_dyads", [])
        if isinstance(pair, list) and len(pair) == 2
    }
    observed_dyads = {
        tuple(sorted((str(action.get("actor_id", "")).strip(), str(action.get("target_id", "")).strip())))
        for action in valid_social_actions
    }
    repeat_target = max(1, int(scenario.get("repeat_dyad_target", 1)))
    repeat_score = _clip(len(prior_dyads & observed_dyads) / repeat_target)
    continuity = 0.80 * _mean(thread_followthrough) + 0.20 * repeat_score

    valid_contributions: set[str] = set()
    task_actor_sets: dict[str, set[str]] = {task_id: set() for task_id in tasks}
    task_role_sets: dict[str, set[str]] = {task_id: set() for task_id in tasks}
    for action in valid_actor_actions:
        actor_id = str(action.get("actor_id", "")).strip()
        task_id = str(action.get("task_id", "")).strip()
        if task_id not in tasks:
            continue
        actor_role = role_by_agent.get(actor_id, "")
        for contribution_id in _str_list(action.get("contribution_ids", [])):
            definition = contributions.get(contribution_id)
            allowed_roles = set(_str_list(definition.get("allowed_role_ids", []))) if definition else set()
            if contribution_task.get(contribution_id) == task_id and (not allowed_roles or actor_role in allowed_roles):
                valid_contributions.add(contribution_id)
                task_actor_sets[task_id].add(actor_id)
                if actor_role:
                    task_role_sets[task_id].add(actor_role)
    contribution_coverage = len(valid_contributions) / len(contributions) if contributions else 0.0
    coalition_scores = []
    for task_id, task in tasks.items():
        required_roles = set(_str_list(task.get("required_role_ids", [])))
        role_coverage = len(required_roles & task_role_sets[task_id]) / len(required_roles) if required_roles else 1.0
        min_actors = max(1, int(task.get("min_distinct_actors", 2)))
        actor_score = _clip(len(task_actor_sets[task_id]) / min_actors)
        coalition_scores.append(0.65 * role_coverage + 0.35 * actor_score)
    coordination = 0.65 * contribution_coverage + 0.35 * _mean(coalition_scores)

    grounding_checks: list[float] = []
    action_families: list[str] = []
    for action in valid_actor_actions:
        action_type = str(action.get("action_type", "")).strip()
        catalog_id = str(action.get("catalog_action_id", "")).strip()
        proposal = action.get("proposal", {}) if isinstance(action.get("proposal"), dict) else {}
        family = catalog_id if action_type == "catalog" else f"propose:{str(proposal.get('verb', '')).strip()}"
        if family:
            action_families.append(family)
        refs = (
            _str_list(action.get("fact_ids", []))
            + _str_list(action.get("input_object_ids", []))
            + _str_list(action.get("output_object_ids", []))
            + _str_list(action.get("world_detail_ids", []))
            + _str_list(action.get("contribution_ids", []))
        )
        valid_catalog = action_type == "catalog" and catalog_id in affordance_ids
        valid_proposal = action_type == "propose" and bool(str(proposal.get("verb", "")).strip())
        grounding_checks.append(float(bool(refs) and bool(str(action.get("expected_effect", "")).strip()) and (valid_catalog or valid_proposal)))
    family_entropy = _normalized_entropy(action_families, len(valid_actor_actions))
    grounded_agency = 0.65 * _mean(grounding_checks) + 0.35 * family_entropy

    proposal_actions = [action for action in valid_actor_actions if str(action.get("action_type", "")).strip() == "propose"]
    proposal_target = max(1, int(scenario.get("open_proposal_target", 1)))
    proposal_presence = _clip(len(proposal_actions) / proposal_target)
    proposal_quality_checks = []
    for action in proposal_actions:
        proposal = action.get("proposal", {}) if isinstance(action.get("proposal"), dict) else {}
        requires_consent = bool(proposal.get("requires_consent"))
        actor_id = str(action.get("actor_id", "")).strip()
        proposal_inputs = _str_list(action.get("input_object_ids", []))
        proposal_outputs = _str_list(action.get("output_object_ids", []))
        resource_access = all(
            object_id in objects
            and (bool(objects[object_id].get("shared")) or str(objects[object_id].get("owner_id", "")) == actor_id)
            for object_id in proposal_inputs
        )
        proposal_quality_checks.append(_mean([
            bool(str(proposal.get("verb", "")).strip()),
            str(proposal.get("scope", "")).strip() in {"target", "room", "local"},
            bool(proposal.get("bounded_effect")),
            not str(action.get("catalog_action_id", "")).strip(),
            bool(str(action.get("expected_effect", "")).strip()),
            (not requires_consent) or bool(str(action.get("consent_basis", "")).strip()),
            resource_access,
            all(object_id in creatable_ids for object_id in proposal_outputs),
            bool(_str_list(action.get("world_detail_ids", []))),
        ]))
    open_action_quality = 0.40 * proposal_presence + 0.60 * _mean(proposal_quality_checks)

    integrity_checks: list[float] = []
    integrity_action_scores: list[float] = []
    violation_counts = Counter()
    action_audits = []
    for action in actions:
        actor_id = str(action.get("actor_id", "")).strip()
        target_id = str(action.get("target_id", "")).strip()
        action_type = str(action.get("action_type", "")).strip()
        catalog_id = str(action.get("catalog_action_id", "")).strip()
        proposal = action.get("proposal", {}) if isinstance(action.get("proposal"), dict) else {}
        fact_ids = _str_list(action.get("fact_ids", []))
        input_ids = _str_list(action.get("input_object_ids", []))
        output_ids = _str_list(action.get("output_object_ids", []))
        detail_ids = _str_list(action.get("world_detail_ids", []))
        contribution_ids = _str_list(action.get("contribution_ids", []))
        task_id = str(action.get("task_id", "")).strip()
        thread_id = str(action.get("thread_id", "")).strip()

        checks = {
            "known_actor": actor_id in expected_actors,
            "legal_target": target_id in all_participants and target_id != actor_id,
            "known_action": (action_type == "catalog" and catalog_id in affordance_ids)
            or (action_type == "propose" and not catalog_id and bool(str(proposal.get("verb", "")).strip())),
            "fact_access": all(
                fact_id in facts
                and (bool(facts[fact_id].get("public")) or actor_id in _str_list(facts[fact_id].get("known_by", [])))
                for fact_id in fact_ids
            ),
            "object_access": all(
                object_id in objects
                and (bool(objects[object_id].get("shared")) or str(objects[object_id].get("owner_id", "")) == actor_id)
                for object_id in input_ids
            ),
            "legal_outputs": all(object_id in creatable_ids for object_id in output_ids)
            and (
                not output_ids
                or action_type == "propose"
                or set(output_ids).issubset(set(_str_list(catalog_actions.get(catalog_id, {}).get("allowed_output_ids", []))))
            ),
            "known_world_details": all(detail_id in world_detail_ids for detail_id in detail_ids),
            "known_task": (not task_id) or task_id in tasks,
            "known_thread": (not thread_id) or thread_id in threads,
            "known_contributions": all(
                contribution_id in contributions and contribution_task.get(contribution_id) == task_id
                for contribution_id in contribution_ids
            ),
            "consent_recorded": (
                not (
                    "trade" in catalog_id
                    or "exchange" in catalog_id
                    or bool(proposal.get("requires_consent"))
                )
                or bool(str(action.get("consent_basis", "")).strip())
            ),
        }
        for check, passed in checks.items():
            integrity_checks.append(float(passed))
            if not passed:
                violation_counts[check] += 1
        integrity_action_scores.append(float(all(checks.values())))
        action_audits.append({"actor_id": actor_id, "checks": checks})
    integrity = _mean(integrity_action_scores)
    integrity_check_rate = _mean(integrity_checks)

    axes = {
        "participation_and_human_uptake": round(100.0 * participation, 2),
        "interaction_topology": round(100.0 * topology, 2),
        "cross_group_bridging": round(100.0 * bridging, 2),
        "relational_continuity": round(100.0 * continuity, 2),
        "collective_coordination": round(100.0 * coordination, 2),
        "world_grounded_agency": round(100.0 * grounded_agency, 2),
        "open_action_quality": round(100.0 * open_action_quality, 2),
        "institutional_integrity": round(100.0 * integrity, 2),
    }
    uncapped_score = _geometric_profile(axes)
    score_cap = 100.0
    cap_reasons = []
    if actor_coverage < 0.5:
        score_cap = min(score_cap, 49.0)
        cap_reasons.append("fewer than half of eligible agents acted")
    if integrity < 0.5:
        score_cap = min(score_cap, 49.0)
        cap_reasons.append("fewer than half of proposed actions are fully legal")
    if not valid_actor_actions:
        score_cap = 0.0
        cap_reasons.append("no valid actor actions")
    final_score = min(uncapped_score, score_cap)

    return {
        "scenario_id": str(scenario.get("scenario_id", "")),
        "score": round(final_score, 2),
        "uncapped_score": round(uncapped_score, 2),
        "score_cap": score_cap,
        "cap_reasons": cap_reasons,
        "axes": axes,
        "observations": {
            "actions_returned": len(actions),
            "eligible_agents": len(expected_actors),
            "actor_coverage": round(actor_coverage, 4),
            "human_intent_answered": human_uptake,
            "target_entropy": round(target_entropy, 4),
            "cross_group_action_rate": round(bridge_rate, 4),
            "distinct_cross_group_pairs": len(distinct_bridge_pairs),
            "valid_contribution_coverage": round(contribution_coverage, 4),
            "open_proposals": len(proposal_actions),
            "fully_legal_action_rate": round(integrity, 4),
            "integrity_check_rate": round(integrity_check_rate, 4),
        },
        "violations": dict(sorted(violation_counts.items())),
        "action_audits": action_audits,
    }


def aggregate_model(model: str, scenario_results: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [item for item in scenario_results if item.get("status") == "ok"]
    axis_means = {
        axis: round(_mean(item["score"]["axes"][axis] for item in completed), 2)
        for axis in AXIS_WEIGHTS
    }
    score_mean = _mean(item["score"]["score"] for item in completed)
    completion_rate = len(completed) / len(scenario_results) if scenario_results else 0.0
    # Availability is part of API performance, while invalid social actions are already in the rubric.
    availability_adjusted = score_mean * completion_rate
    calls = [call for item in scenario_results for call in item.get("telemetry", [])]
    usage_totals = Counter()
    for call in calls:
        for key, value in call.get("usage_metadata", {}).items():
            try:
                usage_totals[str(key)] += int(value)
            except (TypeError, ValueError):
                continue
    return {
        "model": model,
        "community_score": round(availability_adjusted, 2),
        "mean_completed_scenario_score": round(score_mean, 2),
        "completion_rate": round(completion_rate, 4),
        "completed_scenarios": len(completed),
        "total_scenarios": len(scenario_results),
        "axis_means": axis_means,
        "latency_seconds_total": round(sum(float(item.get("latency_seconds", 0.0)) for item in scenario_results), 3),
        "latency_seconds_mean": round(_mean(float(item.get("latency_seconds", 0.0)) for item in completed), 3),
        "usage_metadata_totals": dict(usage_totals),
        "api_attempts": len(calls),
    }


def _client_config(model: str, api_key_env: str, thinking_level: str) -> dict[str, Any]:
    return {
        "vertex_api": {
            "backend": "ai_studio",
            "api_key_env": api_key_env,
            "endpoint_base": "https://generativelanguage.googleapis.com/v1beta",
            "method": "generateContent",
            "model": model,
            "temperature": 1.0,
            "max_output_tokens": 8192,
            "thinking_level": thinking_level,
            "thinking_budget": 512,
            "timeout_seconds": 180,
            "retry": {
                "max_attempts": 2,
                "initial_sleep_seconds": 2.0,
                "max_sleep_seconds": 8.0,
                "backoff_multiplier": 2.0,
                "status_codes": [408, 429, 500, 502, 503, 504],
            },
            "stages": {
                "community_benchmark": {
                    "model": model,
                    "max_output_tokens": 8192,
                    "temperature": 1.0,
                    "thinking_level": thinking_level,
                    "thinking_budget": 512,
                }
            },
        }
    }


def _openai_client_config(model: str, api_key_env: str, thinking_level: str) -> dict[str, Any]:
    return {
        "openai_api": {
            "api_key_env": api_key_env,
            "endpoint_base": os.environ.get("AGORA_GPT_BASE_URL", "https://api.openai.com/v1"),
            "model": model,
            "temperature": 1.0,
            "max_output_tokens": 8192,
            "thinking_level": thinking_level,
            "timeout_seconds": 240,
            "retry": {
                "max_attempts": 2,
                "initial_sleep_seconds": 2.0,
                "max_sleep_seconds": 8.0,
                "backoff_multiplier": 2.0,
                "status_codes": [408, 409, 429, 500, 502, 503, 504],
            },
            "stages": {
                "community_benchmark": {
                    "model": model,
                    "max_output_tokens": 8192,
                    "thinking_level": thinking_level,
                }
            },
        }
    }


def _scenario_prompt(scenario: dict[str, Any]) -> str:
    return (
        "Produce exactly one action for every AI agent in the scenario. Treat each action as an independent "
        "decision: an actor may cite only facts whose known_by list contains that actor or facts marked public. "
        "Use identifiers exactly as declared. Balance continuing existing relationships with new cross-group bridges. "
        "Make joint tasks cover their declared role contributions. At least one AI must directly and substantively "
        "answer the human player's stated intent. Use catalog actions when they fit, and use action_type=propose for "
        "one or more specific actions outside the catalog. Proposals must be local, bounded, resource-grounded, and "
        "record consent when required. Do not narrate outcomes the coordinator has not approved.\n\n"
        "SCENARIO:\n" + json.dumps(scenario, ensure_ascii=False, separators=(",", ":"))
    )


def run_suite(
    suite: dict[str, Any],
    *,
    models: list[str],
    api_key_env: str,
    thinking_level: str,
    provider: str = "gemini",
    suite_path: Path = DEFAULT_SUITE,
) -> dict[str, Any]:
    if not os.environ.get(api_key_env):
        raise RuntimeError(f"{api_key_env} is not set")
    scenarios = [item for item in suite.get("scenarios", []) if isinstance(item, dict)]
    model_runs = []
    for model in models:
        client = (
            OpenAIResponsesJsonClient(_openai_client_config(model, api_key_env, thinking_level))
            if provider == "openai"
            else VertexJsonClient(_client_config(model, api_key_env, thinking_level))
        )
        results = []
        for scenario in scenarios:
            before_calls = len(client.call_history)
            started = time.perf_counter()
            try:
                plan = client.generate_json(
                    system_instruction=(
                        "You are the action policy inside a typed multi-agent world. Select intentions; the world "
                        "coordinator alone decides legality and applies effects. Optimize community participation, "
                        "social diversity, durable coordination, world specificity, and human co-play."
                    ),
                    prompt=_scenario_prompt(scenario),
                    schema=_plan_schema(),
                    stage="community_benchmark",
                )
                result = {
                    "scenario_id": scenario.get("scenario_id", ""),
                    "status": "ok",
                    "latency_seconds": round(time.perf_counter() - started, 3),
                    "plan": plan,
                    "score": score_plan(scenario, plan),
                    "telemetry": client.call_history[before_calls:],
                }
            except Exception as exc:
                result = {
                    "scenario_id": scenario.get("scenario_id", ""),
                    "status": "error",
                    "latency_seconds": round(time.perf_counter() - started, 3),
                    "error": str(exc)[:2000],
                    "telemetry": client.call_history[before_calls:],
                }
            results.append(result)
        model_runs.append({"model": model, "summary": aggregate_model(model, results), "scenarios": results})
    ranking = sorted((item["summary"] for item in model_runs), key=lambda item: item["community_score"], reverse=True)
    return {
        "benchmark": suite.get("benchmark", {}),
        "run_protocol": {
            "suite_path": str(suite_path.resolve().relative_to(ROOT)),
            "models": models,
            "thinking_level": thinking_level,
            "temperature": 1.0,
            "api_backend": "OpenAI Responses API" if provider == "openai" else "Gemini Developer API generateContent",
            "scoring": "deterministic event-contract rubric; no LLM judge",
            "scoring_version": SCORING_VERSION,
            "scope": "preliminary fixed-snapshot micro-benchmark, not a longitudinal emergence claim",
        },
        "ranking": ranking,
        "model_runs": model_runs,
    }


def rescore_results(suite: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    """Recompute deterministic scores from saved model plans without API calls."""
    scenarios = {
        str(item.get("scenario_id", "")): item
        for item in suite.get("scenarios", [])
        if isinstance(item, dict) and str(item.get("scenario_id", ""))
    }
    model_runs = prior.get("model_runs", []) if isinstance(prior.get("model_runs"), list) else []
    for model_run in model_runs:
        if not isinstance(model_run, dict):
            continue
        results = [item for item in model_run.get("scenarios", []) if isinstance(item, dict)]
        for item in results:
            scenario = scenarios.get(str(item.get("scenario_id", "")))
            if item.get("status") == "ok" and isinstance(scenario, dict) and isinstance(item.get("plan"), dict):
                item["score"] = score_plan(scenario, item["plan"])
        model_run["summary"] = aggregate_model(str(model_run.get("model", "")), results)
    prior["ranking"] = sorted(
        (item["summary"] for item in model_runs if isinstance(item, dict) and isinstance(item.get("summary"), dict)),
        key=lambda item: item["community_score"],
        reverse=True,
    )
    prior.setdefault("run_protocol", {})["scoring_version"] = SCORING_VERSION
    return prior


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    score_parser = subparsers.add_parser("score", help="Score a saved plan for one scenario")
    score_parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    score_parser.add_argument("--scenario", required=True)
    score_parser.add_argument("--plan", type=Path, required=True)
    score_parser.add_argument("--output", type=Path)

    run_parser = subparsers.add_parser("run", help="Run the micro-suite through configured API models")
    run_parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    run_parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    run_parser.add_argument("--api-key-env", default="AGORA_AISTUDIO_API_KEY")
    run_parser.add_argument("--provider", choices=("gemini", "openai"), default="gemini")
    run_parser.add_argument("--thinking-level", choices=("minimal", "low", "medium", "high"), default="low")
    run_parser.add_argument("--output", type=Path, required=True)

    rescore_parser = subparsers.add_parser("rescore", help="Rescore saved model plans without API calls")
    rescore_parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    rescore_parser.add_argument("--input", type=Path, required=True)
    rescore_parser.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    suite = _load(args.suite.resolve())
    if args.command == "score":
        scenario = next(
            (item for item in suite.get("scenarios", []) if item.get("scenario_id") == args.scenario),
            None,
        )
        if not isinstance(scenario, dict):
            raise ValueError(f"unknown scenario: {args.scenario}")
        result = score_plan(scenario, _load(args.plan.resolve()))
    elif args.command == "run":
        result = run_suite(
            suite,
            models=list(args.models),
            api_key_env=args.api_key_env,
            thinking_level=args.thinking_level,
            provider=args.provider,
            suite_path=args.suite,
        )
    else:
        result = rescore_results(suite, _load(args.input.resolve()))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    output = getattr(args, "output", None)
    if output:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
