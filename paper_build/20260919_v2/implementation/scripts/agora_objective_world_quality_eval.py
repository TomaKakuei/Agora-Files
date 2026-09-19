#!/usr/bin/env python3
"""Compare generated world specifications with deterministic quality measures."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.agora_monolithic_baseline import (
    _generation_request_for,
    _load_rows,
    _load_paper_rows,
    _read_json,
    _safe_array,
    _safe_object,
    _slug,
    _text,
)


STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "also",
    "among",
    "and",
    "are",
    "around",
    "before",
    "build",
    "character",
    "characters",
    "each",
    "explicit",
    "for",
    "from",
    "have",
    "into",
    "keep",
    "more",
    "must",
    "named",
    "needs",
    "one",
    "only",
    "player",
    "players",
    "room",
    "rooms",
    "same",
    "sentence",
    "specific",
    "that",
    "the",
    "their",
    "them",
    "this",
    "through",
    "top",
    "under",
    "view",
    "visible",
    "with",
    "world",
}
MERCHANT_MARKERS = {
    "broker",
    "dealer",
    "market",
    "merchant",
    "proprietor",
    "seller",
    "shop",
    "stall",
    "trader",
    "vendor",
}
RELATION_MARKERS = {
    "alliance",
    "blackmail",
    "broker",
    "buy",
    "contract",
    "depend",
    "dispute",
    "faction",
    "favor",
    "leverage",
    "negotiate",
    "owe",
    "protect",
    "rival",
    "sell",
    "smuggle",
    "supplier",
    "trade",
}
FALLBACK_NAMES = {
    "meeting notice",
    "task ledger",
    "tea coupon",
}


def _words(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9'-]{2,}", _text(value).lower())
        if token not in STOPWORDS
    }


def _flatten_text(
    value: Any,
    *,
    excluded_keys: set[str] | None = None,
) -> str:
    excluded = excluded_keys or set()
    if isinstance(value, dict):
        return " ".join(
            _flatten_text(item, excluded_keys=excluded)
            for key, item in value.items()
            if str(key) not in excluded
        )
    if isinstance(value, list):
        return " ".join(
            _flatten_text(item, excluded_keys=excluded) for item in value
        )
    return _text(value)


def _premise_terms(request: dict[str, Any]) -> set[str]:
    brief = _text(request.get("brief"))
    creative_sentence = brief.split(".", 1)[0]
    return _words(
        " ".join(
            (
                _text(request.get("world_name")),
                _text(request.get("genre")),
                creative_sentence,
            )
        )
    )


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _normalized_entropy(values: list[str]) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    if len(counts) <= 1:
        return 0.0
    total = len(values)
    entropy = -sum(
        (count / total) * math.log(count / total) for count in counts.values()
    )
    return round(entropy / math.log(len(counts)), 4)


def _branch_text(spec: dict[str, Any], branch: str) -> str:
    if branch == "rooms":
        return _flatten_text(spec.get("rooms", []))
    if branch == "agents":
        return _flatten_text(spec.get("main_characters", []))
    if branch == "items":
        return _flatten_text(spec.get("item_catalog", []))
    if branch == "visual":
        return " ".join(
            (
                _flatten_text(
                    spec.get("visual_canon", {}),
                    excluded_keys={"forbidden_visuals", "canon_hash"},
                ),
                _flatten_text(
                    spec.get("agent_visual_policy", {}),
                    excluded_keys={"forbidden_aesthetics"},
                ),
            )
        )
    raise ValueError(f"unknown branch: {branch}")


def _quality_metrics(
    spec: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    rooms = [
        dict(room) for room in _safe_array(spec.get("rooms")) if isinstance(room, dict)
    ]
    characters = [
        dict(character)
        for character in _safe_array(spec.get("main_characters"))
        if isinstance(character, dict)
    ]
    room_names = {_text(room.get("name")).lower() for room in rooms}
    roles = [_text(character.get("role_name")).lower() for character in characters]
    home_bases = [_text(character.get("home_base")).lower() for character in characters]

    merchant_characters = [
        character
        for character in characters
        if _words(character.get("role_name")) & MERCHANT_MARKERS
    ]
    merchant_inventory_passes = sum(
        len(_safe_array(character.get("inventory"))) >= 15
        for character in merchant_characters
    )
    all_inventory = [
        item
        for character in characters
        for item in _safe_array(character.get("inventory"))
        if isinstance(item, dict)
    ]
    inventory_names = [
        _text(item.get("name") or item.get("item_id")).lower()
        for item in all_inventory
        if _text(item.get("name") or item.get("item_id"))
    ]
    component_ids = [
        _text(component.get("component_id")).lower()
        for room in rooms
        for component in _safe_array(room.get("scene_components"))
        if isinstance(component, dict) and _text(component.get("component_id"))
    ]

    relation_hits = 0
    for character in characters:
        relation_text = " ".join(
            (
                _text(character.get("activity")),
                _text(character.get("arc_goal")),
                _flatten_text(character.get("knowledge_templates", [])),
                _flatten_text(character.get("property_templates", [])),
            )
        )
        relation_hits += bool(_words(relation_text) & RELATION_MARKERS)

    premise_terms = _premise_terms(request)
    branch_recall: dict[str, float] = {}
    for branch in ("rooms", "agents", "items", "visual"):
        branch_recall[branch] = _ratio(
            len(_words(_branch_text(spec, branch)) & premise_terms),
            len(premise_terms),
        )

    canon = _safe_object(spec.get("visual_canon"))
    canon_terms = _words(
        " ".join(
            (
                _flatten_text(canon.get("palette", {})),
                _flatten_text(canon.get("materials", [])),
                _flatten_text(canon.get("architecture", [])),
                _flatten_text(canon.get("terrain", {})),
            )
        )
    )
    room_canon_hits = 0
    for room in rooms:
        room_visual_terms = _words(
            " ".join(
                (
                    _text(room.get("room_scene_prompt")),
                    _text(room.get("flux_floor_prompt")),
                    _flatten_text(room.get("scene_components", [])),
                )
            )
        )
        room_canon_hits += len(room_visual_terms & canon_terms) >= 2
    wardrobe_terms = _words(
        _flatten_text(
            spec.get("agent_visual_policy", {}),
            excluded_keys={"forbidden_aesthetics"},
        )
    )

    role_counts = Counter(role for role in roles if role)
    occupied_valid_rooms = {
        home_base for home_base in home_bases if home_base in room_names
    }
    return {
        "room_count": len(rooms),
        "agent_count": len(characters),
        "home_base_valid_rate": _ratio(
            sum(home_base in room_names for home_base in home_bases),
            len(characters),
        ),
        "room_occupancy_coverage": _ratio(len(occupied_valid_rooms), len(rooms)),
        "room_assignment_entropy": _normalized_entropy(
            [home_base for home_base in home_bases if home_base in room_names]
        ),
        "component_room_coverage_rate": _ratio(
            sum(bool(_safe_array(room.get("scene_components"))) for room in rooms),
            len(rooms),
        ),
        "component_id_unique_rate": _ratio(
            len(set(component_ids)),
            len(component_ids),
        ),
        "role_unique_rate": _ratio(len(role_counts), len(characters)),
        "max_role_repetition_share": _ratio(
            max(role_counts.values(), default=0),
            len(characters),
        ),
        "relational_agent_rate": _ratio(relation_hits, len(characters)),
        "merchant_count": len(merchant_characters),
        "merchant_inventory_pass_rate": (
            _ratio(merchant_inventory_passes, len(merchant_characters))
            if merchant_characters
            else 1.0
        ),
        "inventory_name_unique_rate": _ratio(
            len(set(inventory_names)),
            len(inventory_names),
        ),
        "fallback_inventory_count": sum(
            name in FALLBACK_NAMES for name in inventory_names
        ),
        "premise_rooms_recall": branch_recall["rooms"],
        "premise_agents_recall": branch_recall["agents"],
        "premise_items_recall": branch_recall["items"],
        "premise_visual_recall": branch_recall["visual"],
        "premise_branch_macro_recall": _mean(list(branch_recall.values())),
        "room_visual_canon_adherence": _ratio(room_canon_hits, len(rooms)),
        "wardrobe_canon_term_coverage": _ratio(
            len(wardrobe_terms & canon_terms),
            len(canon_terms),
        ),
    }


def _sign_test(values: list[tuple[float, float]], *, higher_better: bool) -> dict[str, Any]:
    decomposed_wins = 0
    monolithic_wins = 0
    ties = 0
    for decomposed, monolithic in values:
        if abs(decomposed - monolithic) < 1e-12:
            ties += 1
            continue
        decomposed_is_better = (
            decomposed > monolithic if higher_better else decomposed < monolithic
        )
        decomposed_wins += decomposed_is_better
        monolithic_wins += not decomposed_is_better
    discordant = decomposed_wins + monolithic_wins
    p_value = (
        sum(
            math.comb(discordant, value)
            for value in range(decomposed_wins, discordant + 1)
        )
        / (2**discordant)
        if discordant
        else 1.0
    )
    return {
        "decomposed_wins": decomposed_wins,
        "monolithic_wins": monolithic_wins,
        "ties": ties,
        "one_sided_sign_test_p": round(min(1.0, p_value), 6),
    }


def _find_spec(directory: Path, world_name: str, treatment: str) -> Path:
    slug = _slug(world_name)
    patterns = (
        [f"{slug}_r01_decomposed_builder_spec.json"]
        if treatment == "decomposed"
        else [f"{slug}_rep01_monolithic_builder_spec.json"]
    )
    for pattern in patterns:
        path = directory / pattern
        if path.is_file():
            return path
    return directory / patterns[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decomposed-dir", required=True)
    parser.add_argument("--monolithic-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--manifest",
        default="docs/benchmark_20260724/benchmark_manifest.json",
    )
    parser.add_argument(
        "--legacy-cases",
        action="store_true",
        help="Evaluate the five frozen complete legacy worlds.",
    )
    parser.add_argument(
        "--append-report",
        action="append",
        default=[],
        help="Append world-level rows from an existing objective quality JSON report.",
    )
    args = parser.parse_args()

    decomposed_dir = Path(args.decomposed_dir).resolve()
    monolithic_dir = Path(args.monolithic_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    source_rows = (
        _load_rows(Path(args.manifest).resolve(), None)
        if args.legacy_cases
        else _load_paper_rows(REPO_ROOT, None)
    )
    rows: list[dict[str, Any]] = []
    for source_row in source_rows:
        world_name = _text(source_row.get("world_name"))
        request = _generation_request_for(source_row)
        decomposed_path = _find_spec(decomposed_dir, world_name, "decomposed")
        monolithic_path = _find_spec(monolithic_dir, world_name, "monolithic")
        decomposed_spec = _read_json(decomposed_path)
        monolithic_spec = _read_json(monolithic_path)
        rows.append(
            {
                "world_name": world_name,
                "decomposed_spec_path": str(decomposed_path),
                "monolithic_spec_path": str(monolithic_path),
                "decomposed": _quality_metrics(decomposed_spec, request),
                "monolithic": _quality_metrics(monolithic_spec, request),
            }
        )
    appended_reports: list[str] = []
    existing_worlds = {_text(row.get("world_name")) for row in rows}
    for raw_path in args.append_report:
        report_path = Path(raw_path).resolve()
        report = _read_json(report_path)
        for row in _safe_array(report.get("worlds")):
            if not isinstance(row, dict):
                continue
            world_name = _text(row.get("world_name"))
            if not world_name or world_name in existing_worlds:
                continue
            rows.append(dict(row))
            existing_worlds.add(world_name)
        appended_reports.append(str(report_path))

    metric_names = sorted(
        {
            key
            for row in rows
            for key, value in _safe_object(row.get("decomposed")).items()
            if isinstance(value, (int, float))
            and key not in {"agent_count", "merchant_count", "room_count"}
        }
    )
    lower_is_better = {
        "fallback_inventory_count",
        "max_role_repetition_share",
    }
    aggregate: dict[str, Any] = {}
    for metric in metric_names:
        paired_values = [
            (
                float(_safe_object(row.get("decomposed")).get(metric) or 0.0),
                float(_safe_object(row.get("monolithic")).get(metric) or 0.0),
            )
            for row in rows
        ]
        aggregate[metric] = {
            "decomposed_mean": round(
                statistics.mean(value[0] for value in paired_values), 4
            ),
            "monolithic_mean": round(
                statistics.mean(value[1] for value in paired_values), 4
            ),
            **_sign_test(
                paired_values,
                higher_better=metric not in lower_is_better,
            ),
        }

    payload = {
        "decomposed_dir": str(decomposed_dir),
        "monolithic_dir": str(monolithic_dir),
        "case_set": (
            "combined"
            if appended_reports
            else ("legacy_heldout" if args.legacy_cases else "paper_primary")
        ),
        "appended_reports": appended_reports,
        "world_count": len(rows),
        "protocol": {
            "deterministic_only": True,
            "no_llm_judge": True,
            "same_frozen_metrics_for_all_treatments": True,
            "analysis_unit": "world",
            "exploratory_unadjusted_sign_tests": True,
        },
        "aggregate": aggregate,
        "worlds": rows,
    }
    json_path = out_dir / "objective_world_quality.json"
    md_path = out_dir / "objective_world_quality.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Deterministic World Quality Audit",
        "",
        f"- Decomposed: `{decomposed_dir}`",
        f"- Monolithic: `{monolithic_dir}`",
        "- Metrics are deterministic and frozen in the evaluator source.",
        "- Sign tests are exploratory and unadjusted across metrics.",
        "",
        "| Metric | Decomposed | Monolithic | D wins | M wins | Ties | p |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for metric, summary in aggregate.items():
        lines.append(
            f"| {metric} | {summary['decomposed_mean']} | "
            f"{summary['monolithic_mean']} | {summary['decomposed_wins']} | "
            f"{summary['monolithic_wins']} | {summary['ties']} | "
            f"{summary['one_sided_sign_test_p']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
