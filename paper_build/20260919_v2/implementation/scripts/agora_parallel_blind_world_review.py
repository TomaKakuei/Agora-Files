#!/usr/bin/env python3
"""Run an experimental blind-comparison pilot; never update headline results."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora_ui.vertex_json_client import VertexJsonClient


EVIDENCE_ROOT = ROOT / "docs" / "living_world_benchmark_20260825_hidden"
DEFAULT_EVIDENCE = EVIDENCE_ROOT / "strict_generation_evidence_v1.json"
DEFAULT_COMPREHENSIVE = EVIDENCE_ROOT / "cross_provider_comprehensive_results.json"
DEFAULT_OUTPUT = EVIDENCE_ROOT / "parallel_blind_review_v2"
PROTOCOL_VERSION = "parallel-blind-world-review-v2"

# These preserve the old generation-review ratios after removing its 7% visual
# axis. Visual comparison is intentionally a separate matched panel.
CATEGORIES: dict[str, dict[str, Any]] = {
    "premise_causality": {
        "label": "Premise transformation and causal institutions",
        "weight": 0.24 / 0.93,
        "question": (
            "How fully does the one-sentence premise become a specific, coherent "
            "causal system with institutions, state variables, feedback, and stakes?"
        ),
    },
    "society_personhood": {
        "label": "Society, interdependence, and personhood",
        "weight": 0.22 / 0.93,
        "question": (
            "Do groups and named people have differentiated goals, leverage, dependencies, "
            "material lives, relationships, and credible tensions?"
        ),
    },
    "space_materiality": {
        "label": "Spatial and material imagination",
        "weight": 0.10 / 0.93,
        "question": (
            "Are places and objects world-specific, materially legible, and necessary to "
            "the premise rather than interchangeable labels?"
        ),
    },
    "interaction_open_endedness": {
        "label": "Interaction possibility and open-endedness",
        "weight": 0.30 / 0.93,
        "question": (
            "Can a human or agent pursue meaningfully different strategies, including "
            "coordinator-checkable actions outside the fixed catalog, with real consequences?"
        ),
    },
    "holistic_coherence": {
        "label": "Holistic lived-world coherence",
        "weight": 0.07 / 0.93,
        "question": (
            "Taken as a whole, does this feel like a distinctive world worth exploring, "
            "rather than a complete but schematic specification?"
        ),
    },
}

TIER_ORDER = {
    "failed": 0,
    "weak": 1,
    "partial": 2,
    "competent": 3,
    "strong": 4,
    "exceptional": 5,
    "reference": 6,
}
TIER_SCORES = {
    "failed": 0.0,
    "weak": 30.0,
    "partial": 45.0,
    "competent": 60.0,
    "strong": 75.0,
    "exceptional": 85.0,
    "reference": 92.0,
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def clip(value: Any, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def take(rows: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [row for row in rows[:limit] if isinstance(row, dict)]


def project(rows: Any, fields: Iterable[str], *, limit: int, text_limit: int = 260) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in take(rows, limit):
        projected = {
            field: clip(row.get(field), text_limit)
            for field in fields
            if row.get(field) not in (None, "", [], {})
        }
        if projected:
            output.append(projected)
    return output


def compact_relationships(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, str]] = []
    for row in value[:2]:
        if isinstance(row, dict):
            output.append(
                {
                    key: clip(row.get(key), 120)
                    for key in ("target", "target_name", "type", "relationship", "description")
                    if row.get(key) not in (None, "", [], {})
                }
            )
    return [row for row in output if row]


def character_cards(spec: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for row in take(spec.get("main_characters"), 4):
        inventory = [
            clip(item.get("name"), 80)
            for item in take(row.get("inventory"), 2)
            if item.get("name")
        ]
        card = {
            "name": clip(row.get("display_name") or row.get("name"), 90),
            "role": clip(row.get("role_name") or row.get("role"), 120),
            "activity": clip(row.get("activity"), 150),
            "goal": clip(row.get("arc_goal") or row.get("goal"), 150),
            "home": clip(row.get("home_base") or row.get("home_room"), 100),
            "inventory_sample": inventory,
            "relationships": compact_relationships(row.get("relationships")),
        }
        cards.append({key: value for key, value in card.items() if value not in ("", [], {})})
    return cards


def dynamics(spec: dict[str, Any]) -> dict[str, Any]:
    value = spec.get("world_dynamics")
    return value if isinstance(value, dict) else {}


def card_for_category(spec: dict[str, Any], category: str) -> dict[str, Any]:
    dyn = dynamics(spec)
    base = {
        "world_name": clip(spec.get("world_name"), 100),
        "authored_premise": clip(spec.get("premise"), 420),
    }
    if category == "premise_causality":
        base.update(
            {
                "simulation_objective": clip(spec.get("simulation_objective"), 360),
                "institutions": project(
                    dyn.get("institutions"),
                    ("name", "mandate", "decision_rule", "enforced_by", "visible_output"),
                    limit=3,
                    text_limit=170,
                ),
                "state_variables": project(
                    dyn.get("state_variables"),
                    ("label", "initial_tension", "changed_by", "affects"),
                    limit=4,
                    text_limit=150,
                ),
                "causal_links": project(
                    dyn.get("causal_links"),
                    ("source_state", "trigger", "target_state", "effect", "delay"),
                    limit=4,
                    text_limit=160,
                ),
            }
        )
    elif category == "society_personhood":
        base.update(
            {
                "stakeholder_groups": project(
                    dyn.get("stakeholder_groups"),
                    ("name", "goal", "leverage", "dependency"),
                    limit=3,
                    text_limit=170,
                ),
                "social_rules": [clip(item, 170) for item in (spec.get("social_rules") or [])[:3]],
                "conflict_hooks": project(
                    spec.get("conflict_hooks"),
                    ("title", "summary", "roles", "stakes", "trigger"),
                    limit=3,
                    text_limit=160,
                ),
                "people": character_cards(spec),
            }
        )
    elif category == "space_materiality":
        rooms = project(
            spec.get("rooms"),
            ("name", "purpose", "biome", "visual_prompt", "scene_prompt"),
            limit=5,
            text_limit=170,
        )
        item_sample = project(
            spec.get("item_catalog"),
            ("name", "description", "category"),
            limit=8,
            text_limit=120,
        )
        base.update(
            {
                "economy_focus": clip(spec.get("economy_focus"), 240),
                "exploration_focus": clip(spec.get("exploration_focus"), 240),
                "visual_style": clip(spec.get("visual_style"), 240),
                "rooms": rooms,
                "material_item_sample": item_sample,
            }
        )
    elif category == "interaction_open_endedness":
        base.update(
            {
                "gameplay_loops": project(
                    spec.get("gameplay_loops"),
                    ("label", "summary", "roles", "rooms", "pressure"),
                    limit=3,
                    text_limit=170,
                ),
                "custom_actions": [clip(item, 100) for item in (spec.get("custom_actions") or [])[:8]],
                "open_action_examples": project(
                    spec.get("open_action_examples"),
                    (
                        "action_name",
                        "initiating_role",
                        "target_role",
                        "situation",
                        "proposed_effects",
                        "coordinator_checks",
                    ),
                    limit=3,
                    text_limit=170,
                ),
                "player_entry_points": [
                    clip(item, 170) for item in (spec.get("player_entry_points") or [])[:3]
                ],
            }
        )
    elif category == "holistic_coherence":
        base.update(
            {
                "simulation_objective": clip(spec.get("simulation_objective"), 280),
                "institutions": [
                    clip(row.get("name"), 100) for row in take(dyn.get("institutions"), 3)
                ],
                "state_variables": [
                    clip(row.get("label"), 100) for row in take(dyn.get("state_variables"), 4)
                ],
                "stakeholders": project(
                    dyn.get("stakeholder_groups"), ("name", "goal"), limit=3, text_limit=140
                ),
                "places": project(spec.get("rooms"), ("name", "purpose"), limit=5, text_limit=130),
                "people": [
                    {
                        "name": clip(row.get("display_name") or row.get("name"), 80),
                        "role": clip(row.get("role_name") or row.get("role"), 100),
                        "goal": clip(row.get("arc_goal") or row.get("goal"), 150),
                    }
                    for row in take(spec.get("main_characters"), 4)
                ],
                "loop_labels": [
                    clip(row.get("label"), 120) for row in take(spec.get("gameplay_loops"), 3)
                ],
                "custom_actions": [clip(item, 100) for item in (spec.get("custom_actions") or [])[:8]],
                "open_actions": [
                    clip(row.get("action_name"), 120)
                    for row in take(spec.get("open_action_examples"), 3)
                ],
            }
        )
    else:
        raise KeyError(category)
    return {key: value for key, value in base.items() if value not in ("", [], {})}


def prompt_sentences(comprehensive: dict[str, Any]) -> dict[str, str]:
    for row in comprehensive.get("ranking") or []:
        cases = ((row.get("generated_world") or {}).get("cases") or [])
        if cases:
            return {str(case["prompt_id"]): str(case["sentence"]) for case in cases}
    raise RuntimeError("No prompt sentences found")


def evidence_index(evidence: dict[str, Any]) -> tuple[list[str], list[str], dict[tuple[str, str], dict[str, Any]]]:
    models = [str(row["model"]) for row in evidence.get("ranking") or []]
    prompts: list[str] = []
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for model_row in evidence.get("ranking") or []:
        model = str(model_row["model"])
        for case in model_row.get("cases") or []:
            prompt_id = str(case["prompt_id"])
            if prompt_id not in prompts:
                prompts.append(prompt_id)
            rows[(model, prompt_id)] = case
    return models, prompts, rows


def build_cards(
    evidence: dict[str, Any], category: str
) -> tuple[list[str], list[str], dict[tuple[str, str], dict[str, Any]]]:
    models, prompts, rows = evidence_index(evidence)
    cards: dict[tuple[str, str], dict[str, Any]] = {}
    for model in models:
        for prompt_id in prompts:
            case = rows.get((model, prompt_id)) or {}
            relative_path = str(case.get("builder_spec_path") or "")
            if case.get("status") != "compiled" or not relative_path:
                cards[(model, prompt_id)] = {
                    "status": "failed_no_compiled_world",
                    "evidence": "No compiled artifact was produced under the common attempt budget.",
                }
                continue
            spec = load_json(ROOT / relative_path)
            cards[(model, prompt_id)] = {
                "status": "compiled",
                "evidence": card_for_category(spec, category),
            }
    return models, prompts, cards


def make_packet(
    *,
    evidence: dict[str, Any],
    category: str,
    pass_index: int,
    seed: int,
    sentences: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    models, prompts, cards = build_cards(evidence, category)
    packet_prompts: list[dict[str, Any]] = []
    mapping_prompts: dict[str, Any] = {}
    for prompt_offset, prompt_id in enumerate(prompts):
        rng = random.Random(seed + pass_index * 1009 + prompt_offset * 101 + sum(map(ord, category)))
        labels = [f"C{number:02d}" for number in range(1, len(models) + 1)]
        rng.shuffle(labels)
        label_by_model = dict(zip(models, labels))
        presentation = list(models)
        rng.shuffle(presentation)
        candidates = [
            {
                "candidate_id": label_by_model[model],
                **cards[(model, prompt_id)],
            }
            for model in presentation
        ]
        packet_prompts.append(
            {
                "prompt_id": prompt_id,
                "source_sentence": sentences[prompt_id],
                "candidates": candidates,
            }
        )
        mapping_prompts[prompt_id] = {
            "candidate_to_model": {label_by_model[model]: model for model in models},
            "presentation_order": [label_by_model[model] for model in presentation],
        }
    packet = {
        "protocol": PROTOCOL_VERSION,
        "category": category,
        "category_label": CATEGORIES[category]["label"],
        "category_question": CATEGORIES[category]["question"],
        "pass": pass_index,
        "prompt_blocks": packet_prompts,
    }
    mapping = {
        "category": category,
        "pass": pass_index,
        "prompts": mapping_prompts,
    }
    return packet, mapping


def response_schema() -> dict[str, Any]:
    candidate = {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string"},
            "tier": {"type": "string"},
            "rank": {"type": "integer"},
            "score": {"type": "integer"},
            "strongest_evidence": {"type": "string"},
            "main_limitation": {"type": "string"},
        },
        "required": [
            "candidate_id",
            "tier",
            "rank",
            "score",
            "strongest_evidence",
            "main_limitation",
        ],
    }
    prompt_review = {
        "type": "object",
        "properties": {
            "prompt_id": {"type": "string"},
            "candidates": {"type": "array", "items": candidate},
            "comparison_summary": {"type": "string"},
        },
        "required": ["prompt_id", "candidates", "comparison_summary"],
    }
    return {
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "prompt_reviews": {"type": "array", "items": prompt_review},
            "calibration_note": {"type": "string"},
        },
        "required": ["category", "prompt_reviews", "calibration_note"],
    }


SYSTEM_INSTRUCTION = """You are a comparative evaluator of executable social worlds.
The candidate identities and source models are hidden. Evaluate only the requested category.
For each source sentence, compare every candidate side by side before assigning any score.
Do not reward length, field count, polished prose, safety language, or schema compliance by itself.
Reward concrete causal or social consequences evidenced in the supplied card.
Use these fixed anchors: 0=failed/no artifact, 25=weak formal mimicry, 45=partial and shallow,
60=competent complete work, 75=strong and clearly differentiated, 85=exceptional sustained
quality, 92=rare reference quality. Do not force a winner or force a score spread.
Candidates within two points should normally share a rank. Scores for usable candidates in one
prompt should normally span no more than 25 points unless there is an obvious qualitative gulf.
Use tiers only from: failed, weak, partial, competent, strong, exceptional, reference.
Failed candidates must receive score 0 and the lowest rank. A lower rank number is better.
Tier and comparative rank are the primary decisions. The numeric score is a diagnostic expression
of the chosen tier and is not used directly in aggregation; keep it compatible with the anchors.
Judge all three prompt blocks with the same severity before returning the result."""


def client_config(model: str, api_key_env: str, thinking_level: str) -> dict[str, Any]:
    return {
        "vertex_api": {
            "backend": "ai_studio",
            "api_key_env": api_key_env,
            "endpoint_base": "https://generativelanguage.googleapis.com/v1beta",
            "method": "generateContent",
            "model": model,
            "temperature": 0.2,
            "max_output_tokens": 8192,
            "thinking_level": thinking_level,
            "thinking_budget": 1024,
            "timeout_seconds": 300,
            "retry": {
                "max_attempts": 3,
                "initial_sleep_seconds": 3.0,
                "max_sleep_seconds": 15.0,
                "backoff_multiplier": 2.0,
                "status_codes": [408, 429, 500, 502, 503, 504],
            },
            "stages": {
                "parallel_blind_review": {
                    "model": model,
                    "temperature": 0.2,
                    "max_output_tokens": 8192,
                    "thinking_level": thinking_level,
                }
            },
        }
    }


def load_env_key(path: Path, key: str) -> None:
    if os.environ.get(key):
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            os.environ[key] = value.strip().strip("'\"")
            return


def validate_review(review: dict[str, Any], packet: dict[str, Any]) -> None:
    if str(review.get("category")) != str(packet["category"]):
        raise ValueError("Reviewer returned the wrong category")
    expected_blocks = {row["prompt_id"]: row for row in packet["prompt_blocks"]}
    returned_blocks = {str(row.get("prompt_id")): row for row in review.get("prompt_reviews") or []}
    if set(returned_blocks) != set(expected_blocks):
        raise ValueError("Reviewer returned the wrong prompt set")
    for prompt_id, packet_block in expected_blocks.items():
        expected_ids = {row["candidate_id"] for row in packet_block["candidates"]}
        candidates = returned_blocks[prompt_id].get("candidates") or []
        returned_ids = [str(row.get("candidate_id")) for row in candidates]
        if len(returned_ids) != len(set(returned_ids)) or set(returned_ids) != expected_ids:
            raise ValueError(f"Candidate mismatch for {prompt_id}")
        for row in candidates:
            score = int(row.get("score", -1))
            rank = int(row.get("rank", 0))
            tier = str(row.get("tier", "")).lower()
            if not 0 <= score <= 100 or rank < 1 or tier not in TIER_ORDER:
                raise ValueError(f"Invalid score, rank, or tier for {prompt_id}")


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = statistics.mean(left)
    right_mean = statistics.mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_ss = sum((a - left_mean) ** 2 for a in left)
    right_ss = sum((b - right_mean) ** 2 for b in right)
    if left_ss <= 0 or right_ss <= 0:
        return None
    return numerator / math.sqrt(left_ss * right_ss)


def aggregate(
    *,
    evidence: dict[str, Any],
    output: Path,
    passes: int,
    judge_model: str,
) -> dict[str, Any]:
    models, prompts, evidence_rows = evidence_index(evidence)
    observations: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    card_chars: dict[tuple[str, str, str], int] = {}
    position_x: list[float] = []
    position_y: list[float] = []
    response_maps: dict[tuple[str, str, int], dict[str, dict[str, Any]]] = {}
    for pass_index in range(1, passes + 1):
        for category in CATEGORIES:
            mapping = load_json(output / "label_maps" / f"pass_{pass_index:02d}_{category}.json")
            review = load_json(output / "raw_reviews" / f"pass_{pass_index:02d}_{category}.json")
            packet = load_json(output / "packets" / f"pass_{pass_index:02d}_{category}.json")
            packet_by_prompt = {
                str(row["prompt_id"]): row for row in packet["prompt_blocks"]
            }
            review_by_prompt = {
                str(row["prompt_id"]): row for row in review["prompt_reviews"]
            }
            for prompt_id in prompts:
                prompt_map = mapping["prompts"][prompt_id]
                candidate_to_model = prompt_map["candidate_to_model"]
                positions = {
                    candidate_id: index
                    for index, candidate_id in enumerate(prompt_map["presentation_order"], start=1)
                }
                if pass_index == 1:
                    for candidate in packet_by_prompt[prompt_id]["candidates"]:
                        candidate_id = str(candidate["candidate_id"])
                        model = candidate_to_model[candidate_id]
                        card_chars[(model, category, prompt_id)] = len(
                            json.dumps(candidate.get("evidence"), ensure_ascii=False)
                        )
                returned: dict[str, dict[str, Any]] = {}
                for row in review_by_prompt[prompt_id]["candidates"]:
                    candidate_id = str(row["candidate_id"])
                    model = candidate_to_model[candidate_id]
                    failed = (evidence_rows.get((model, prompt_id)) or {}).get("status") != "compiled"
                    normalized = {
                        **row,
                        "score": 0 if failed else int(row["score"]),
                        "rank": int(row["rank"]),
                        "presentation_position": positions[candidate_id],
                        "failed": failed,
                    }
                    returned[model] = normalized
                compiled_models = [model for model, row in returned.items() if not row["failed"]]
                for model, normalized in returned.items():
                    if normalized["failed"]:
                        normalized["tier_anchor_score"] = 0.0
                        normalized["comparative_rank_score"] = 0.0
                        normalized["panel_score"] = 0.0
                    else:
                        other_models = [item for item in compiled_models if item != model]
                        wins = 0.0
                        for other_model in other_models:
                            if normalized["rank"] < returned[other_model]["rank"]:
                                wins += 1.0
                            elif normalized["rank"] == returned[other_model]["rank"]:
                                wins += 0.5
                        win_rate = wins / len(other_models) if other_models else 0.5
                        tier_anchor = TIER_SCORES[str(normalized["tier"]).lower()]
                        rank_score = 55.0 + 30.0 * win_rate
                        normalized["tier_anchor_score"] = round(tier_anchor, 2)
                        normalized["comparative_rank_score"] = round(rank_score, 2)
                        normalized["panel_score"] = round(
                            0.70 * tier_anchor + 0.30 * rank_score,
                            2,
                        )
                        position_x.append(float(normalized["presentation_position"]))
                        position_y.append(float(normalized["score"]))
                    observations.setdefault((model, category, prompt_id), []).append(normalized)
                response_maps[(category, prompt_id, pass_index)] = returned

    category_prompt: dict[str, dict[str, dict[str, Any]]] = {model: {} for model in models}
    for model in models:
        for category in CATEGORIES:
            category_prompt[model][category] = {}
            for prompt_id in prompts:
                rows = observations[(model, category, prompt_id)]
                scores = [float(row["panel_score"]) for row in rows]
                judge_scores = [float(row["score"]) for row in rows]
                ranks = [float(row["rank"]) for row in rows]
                category_prompt[model][category][prompt_id] = {
                    "score_median": round(statistics.median(scores), 2),
                    "score_mean": round(statistics.mean(scores), 2),
                    "score_stddev": round(statistics.pstdev(scores), 2),
                    "judge_score_median": round(statistics.median(judge_scores), 2),
                    "rank_median": round(statistics.median(ranks), 2),
                    "passes": rows,
                }

    stability: dict[str, dict[str, float | None]] = {}
    correlations: list[float] = []
    for category in CATEGORIES:
        stability[category] = {}
        for prompt_id in prompts:
            pair_correlations: list[float] = []
            for left_pass in range(1, passes + 1):
                for right_pass in range(left_pass + 1, passes + 1):
                    left = [
                        float(response_maps[(category, prompt_id, left_pass)][model]["rank"])
                        for model in models
                    ]
                    right = [
                        float(response_maps[(category, prompt_id, right_pass)][model]["rank"])
                        for model in models
                    ]
                    value = pearson(left, right)
                    if value is not None:
                        pair_correlations.append(value)
                        correlations.append(value)
            stability[category][prompt_id] = (
                round(statistics.mean(pair_correlations), 3) if pair_correlations else None
            )

    length_correlations: dict[str, float | None] = {}
    all_centered_lengths: list[float] = []
    all_centered_scores: list[float] = []
    for category in CATEGORIES:
        centered_lengths: list[float] = []
        centered_scores: list[float] = []
        for prompt_id in prompts:
            compiled_models = [
                model
                for model in models
                if (evidence_rows.get((model, prompt_id)) or {}).get("status") == "compiled"
            ]
            lengths = [float(card_chars[(model, category, prompt_id)]) for model in compiled_models]
            scores = [
                float(category_prompt[model][category][prompt_id]["score_median"])
                for model in compiled_models
            ]
            length_mean = statistics.mean(lengths)
            score_mean = statistics.mean(scores)
            centered_lengths.extend(value - length_mean for value in lengths)
            centered_scores.extend(value - score_mean for value in scores)
        value = pearson(centered_lengths, centered_scores)
        length_correlations[category] = round(value, 3) if value is not None else None
        all_centered_lengths.extend(centered_lengths)
        all_centered_scores.extend(centered_scores)
    overall_length_correlation = pearson(all_centered_lengths, all_centered_scores)

    model_rows: list[dict[str, Any]] = []
    for model in models:
        category_scores = {
            category: round(
                statistics.mean(
                    category_prompt[model][category][prompt_id]["score_median"]
                    for prompt_id in prompts
                ),
                2,
            )
            for category in CATEGORIES
        }
        category_card_chars = {
            category: round(
                statistics.mean(card_chars[(model, category, prompt_id)] for prompt_id in prompts),
                1,
            )
            for category in CATEGORIES
        }
        overall = sum(
            category_scores[category] * float(config["weight"])
            for category, config in CATEGORIES.items()
        )
        pass_scores: list[float] = []
        for pass_index in range(1, passes + 1):
            pass_category_scores = {
                category: statistics.mean(
                    observations[(model, category, prompt_id)][pass_index - 1]["panel_score"]
                    for prompt_id in prompts
                )
                for category in CATEGORIES
            }
            pass_scores.append(
                sum(
                    pass_category_scores[category] * float(CATEGORIES[category]["weight"])
                    for category in CATEGORIES
                )
            )
        model_rows.append(
            {
                "model": model,
                "parallel_blind_text_score": round(overall, 2),
                "pass_scores": [round(value, 2) for value in pass_scores],
                "pass_stddev": round(statistics.pstdev(pass_scores), 2),
                "compiled_worlds": sum(
                    1
                    for prompt_id in prompts
                    if (evidence_rows.get((model, prompt_id)) or {}).get("status") == "compiled"
                ),
                "category_scores": category_scores,
                "mean_card_characters": category_card_chars,
                "prompt_details": category_prompt[model],
            }
        )
    model_rows.sort(key=lambda row: row["parallel_blind_text_score"], reverse=True)
    position_bias = pearson(position_x, position_y)
    return {
        "benchmark": "Agora Parallel Blind World Review",
        "version": PROTOCOL_VERSION,
        "experimental_only": True,
        "eligible_for_headline": False,
        "judge_model": judge_model,
        "judge_identity_blind": True,
        "passes": passes,
        "prompt_count": len(prompts),
        "category_weights": {
            category: round(float(config["weight"]), 8)
            for category, config in CATEGORIES.items()
        },
        "aggregation": (
            "Per pass, 70% fixed tier anchor plus 30% within-prompt pairwise rank-win score; "
            "median across randomized passes within prompt/category; arithmetic mean across "
            "the three matched prompts; fixed weighted arithmetic mean across categories."
        ),
        "ranking": model_rows,
        "diagnostics": {
            "mean_pairwise_rank_correlation": (
                round(statistics.mean(correlations), 3) if correlations else None
            ),
            "rank_correlation_by_category_prompt": stability,
            "presentation_position_score_correlation": (
                round(position_bias, 3) if position_bias is not None else None
            ),
            "prompt_centered_card_length_score_correlation": {
                "overall": (
                    round(overall_length_correlation, 3)
                    if overall_length_correlation is not None
                    else None
                ),
                "by_category": length_correlations,
            },
        },
        "scope": (
            "Textual generated-world quality only. Visual comparison and runtime behavior "
            "must be judged in separate matched panels."
        ),
    }


def make_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Agora Parallel Blind World Review v2",
        "",
        "> EXPERIMENTAL METHOD PILOT ONLY. This output is not eligible for the main benchmark or paper headline.",
        "",
        f"Judge: `{payload['judge_model']}`  ",
        f"Repeated randomized passes: `{payload['passes']}`  ",
        f"Prompt-matched blocks: `{payload['prompt_count']}`",
        "",
        "## Method",
        "",
        "Each call evaluates one category only. All anonymous worlds for all three source sentences are visible in parallel. Candidate labels and presentation order change on every pass. Each candidate receives a quality tier and a rank with ties. The panel score is 70% fixed tier anchor and 30% within-prompt pairwise rank-win score; free-form 0--100 numbers are diagnostic only. The final score uses the median across passes inside each prompt/category, then averages the three matched prompts. Failed worlds remain zero.",
        "",
        "The review is text-only. It does not reuse objective detector scores, provider names, latency, token use, compilation retries, or the prior expert review.",
        "",
        "## Ranking",
        "",
        "| Rank | Model | Blind text | Pass SD | Compiled | Premise/causal | Society/personhood | Space/material | Interaction/open | Holistic |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index, row in enumerate(payload["ranking"], start=1):
        scores = row["category_scores"]
        lines.append(
            f"| {index} | {row['model']} | **{row['parallel_blind_text_score']:.2f}** | "
            f"{row['pass_stddev']:.2f} | {row['compiled_worlds']}/3 | "
            f"{scores['premise_causality']:.2f} | {scores['society_personhood']:.2f} | "
            f"{scores['space_materiality']:.2f} | {scores['interaction_open_endedness']:.2f} | "
            f"{scores['holistic_coherence']:.2f} |"
        )
    diagnostics = payload["diagnostics"]
    lines.extend(
        [
            "",
            "## Reliability diagnostics",
            "",
            f"- Mean pairwise rank correlation across randomized passes: `{diagnostics['mean_pairwise_rank_correlation']}`",
            f"- Presentation-position/score correlation: `{diagnostics['presentation_position_score_correlation']}`",
            "",
            "Near-zero presentation correlation is desirable. Low or negative repeated-pass rank correlation means the category is not reliable enough for a headline and should be merged, clarified, or sent to humans.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--comprehensive", type=Path, default=DEFAULT_COMPREHENSIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--judge-model", default="gemini-3.1-pro-preview")
    parser.add_argument("--api-key-env", default="AGORA_AISTUDIO_API_KEY")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--thinking-level", default="low")
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260826)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()

    if args.passes < 2:
        raise ValueError("At least two randomized passes are required")
    evidence = load_json(args.evidence)
    sentences = prompt_sentences(load_json(args.comprehensive))
    args.output.mkdir(parents=True, exist_ok=True)
    protocol = {
        "version": PROTOCOL_VERSION,
        "experimental_only": True,
        "eligible_for_headline": False,
        "categories": CATEGORIES,
        "passes": args.passes,
        "seed": args.seed,
        "judge_model": args.judge_model,
        "card_profile": "balanced fixed-slot evidence cards",
        "aggregation": {
            "tier_anchor_weight": 0.70,
            "within_prompt_pairwise_rank_weight": 0.30,
            "free_form_numeric_score_weight": 0.0,
        },
        "score_anchors": {
            "0": "failed or no artifact",
            "25": "weak formal mimicry",
            "45": "partial and shallow",
            "60": "competent complete work",
            "75": "strong and clearly differentiated",
            "85": "exceptional sustained quality",
            "92": "rare reference quality",
        },
    }
    write_json(args.output / "protocol.json", protocol)

    packets: list[tuple[int, str, dict[str, Any]]] = []
    for pass_index in range(1, args.passes + 1):
        for category in CATEGORIES:
            packet, mapping = make_packet(
                evidence=evidence,
                category=category,
                pass_index=pass_index,
                seed=args.seed,
                sentences=sentences,
            )
            packet_path = args.output / "packets" / f"pass_{pass_index:02d}_{category}.json"
            mapping_path = args.output / "label_maps" / f"pass_{pass_index:02d}_{category}.json"
            write_json(packet_path, packet)
            write_json(mapping_path, mapping)
            packets.append((pass_index, category, packet))

    if args.prepare_only:
        print(json.dumps({"output": str(args.output), "packets": len(packets)}, indent=2))
        return

    if args.aggregate_only:
        result = aggregate(
            evidence=evidence,
            output=args.output,
            passes=args.passes,
            judge_model=args.judge_model,
        )
        write_json(args.output / "aggregate.json", result)
        (args.output / "report.md").write_text(make_report(result), encoding="utf-8")
        print(json.dumps({"output": str(args.output), "ranking": result["ranking"]}, indent=2))
        return

    if args.env_file:
        load_env_key(args.env_file, args.api_key_env)
    if not os.environ.get(args.api_key_env):
        raise RuntimeError(f"{args.api_key_env} is not set")
    client = VertexJsonClient(
        client_config(args.judge_model, args.api_key_env, args.thinking_level)
    )
    for pass_index, category, packet in packets:
        review_path = args.output / "raw_reviews" / f"pass_{pass_index:02d}_{category}.json"
        if review_path.exists():
            validate_review(load_json(review_path), packet)
            print(f"[BLIND_REVIEW_SKIP] pass={pass_index} category={category}", flush=True)
            continue
        for semantic_attempt in range(1, 3):
            print(
                f"[BLIND_REVIEW] pass={pass_index} category={category} "
                f"semantic_attempt={semantic_attempt}",
                flush=True,
            )
            review = client.generate_json(
                system_instruction=SYSTEM_INSTRUCTION,
                prompt=json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                schema=response_schema(),
                stage="parallel_blind_review",
            )
            try:
                validate_review(review, packet)
            except ValueError:
                invalid_path = (
                    args.output
                    / "invalid_reviews"
                    / f"pass_{pass_index:02d}_{category}_attempt_{semantic_attempt}.json"
                )
                write_json(invalid_path, review)
                if semantic_attempt >= 2:
                    raise
                continue
            write_json(review_path, review)
            break

    result = aggregate(
        evidence=evidence,
        output=args.output,
        passes=args.passes,
        judge_model=args.judge_model,
    )
    write_json(args.output / "aggregate.json", result)
    (args.output / "report.md").write_text(make_report(result), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "ranking": result["ranking"]}, indent=2))


if __name__ == "__main__":
    main()
