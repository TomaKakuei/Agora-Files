#!/usr/bin/env python3
"""Run a fresh one-shot monolithic builder-spec baseline.

This baseline intentionally does not use the decomposed Agora world-builder nodes
and does not run FLUX art generation or publication. For each selected benchmark
world, it asks a single LLM call to produce a complete builder_spec from the
original brief, then evaluates schema/coverage signals and deterministic compiler
compatibility.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agora_ui.world_builder.builder import _build_world_config_from_spec
from agora_ui.world_builder.generation import (
    _execute_json_prompt,
    _normalize_builder_spec,
    _world_creator_provider,
)
from agora_ui.world_builder.nodes.rooms import _rooms_schema
from agora_ui.world_builder.nodes.visual_canon import _visual_canon_schema
from agora_ui.world_builder.nodes.wardrobe import _wardrobe_policy_schema
from agora_ui.world_builder import generation_schemas as generation_schema_module
from agora_ui.world_builder.generation_schemas import _builder_spec_schema
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
    build_world_pipeline,
)

for _name, _value in {
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
    setattr(generation_schema_module, _name, _value)


STRICT_INVENTORY_SUBSET_DRAFT_IDS = {
    "creator_20260706_053251_1ad0b086",  # Clockwork Rain Conservatory
    "creator_20260724_203817_f86ae13e",  # Aurora Court of Migrating Cities
    "creator_20260724_211037_1c17ca96",  # Mycelium Patent Bazaar
    "creator_20260724_215709_f5f54ceb",  # Tidal Embassy of Lost Languages
    "creator_20260724_224121_43ca9360",  # Sunken Satellite Monastery
}

PAPER_CASE_DRAFT_IDS = (
    "creator_20260727_233333_efa8235f",
    "creator_20260728_002605_dd9ffc0c",
    "creator_20260728_020032_6f7b670a",
    "creator_20260728_220950_e2278e2f",
    "creator_20260728_223205_1924f12f",
)

FALLBACK_ITEM_NAMES = {
    "task ledger",
    "meeting notice",
    "tea coupon",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_array(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _telemetry_summary(path: Path) -> dict[str, Any]:
    rows = _read_jsonl(path)
    statuses = Counter(_text(row.get("status")) for row in rows)
    token_totals: Counter[str] = Counter()
    elapsed_seconds = 0.0
    usage_rows = 0
    for row in rows:
        elapsed_seconds += float(row.get("elapsed_seconds") or 0.0)
        usage = _safe_object(row.get("usage_metadata"))
        usage_rows += bool(usage)
        for key, value in usage.items():
            try:
                token_totals[str(key)] += int(value)
            except (TypeError, ValueError):
                continue
    return {
        "path": str(path),
        "provider_attempt_count": len(rows),
        "successful_attempt_count": int(statuses.get("ok", 0)),
        "retry_or_failure_attempt_count": len(rows) - int(statuses.get("ok", 0)),
        "usage_metadata_attempt_count": usage_rows,
        "usage_metadata_coverage": (
            round(usage_rows / len(rows), 4) if rows else 0.0
        ),
        "status_counts": dict(sorted(statuses.items())),
        "provider_elapsed_seconds_sum": round(elapsed_seconds, 4),
        "token_totals": dict(sorted(token_totals.items())),
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "world"


def _score_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _wilson(successes: int, trials: int) -> list[float]:
    if trials <= 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    center = (proportion + z * z / (2.0 * trials)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / trials
            + z * z / (4.0 * trials * trials)
        )
        / denominator
    )
    return [
        round(max(0.0, center - margin), 4),
        round(min(1.0, center + margin), 4),
    ]


def _load_rows(manifest_path: Path, limit: int | None) -> list[dict[str, Any]]:
    manifest = _read_json(manifest_path)
    rows = [
        dict(row)
        for row in _safe_array(manifest.get("drafts"))
        if isinstance(row, dict)
        and row.get("complete_for_benchmark") is True
        and _text(row.get("draft_id")) in STRICT_INVENTORY_SUBSET_DRAFT_IDS
    ]
    rows.sort(key=lambda row: _text(row.get("world_name")))
    if limit is not None:
        rows = rows[: max(0, int(limit))]
    return rows


def _load_paper_rows(package_root: Path, limit: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for draft_id in PAPER_CASE_DRAFT_IDS:
        revision_dir = (
            package_root
            / "output"
            / "world_creator_drafts"
            / draft_id
            / "revisions"
            / "r001"
        )
        request_payload = _read_json(revision_dir / "generation_request.json")
        request = _safe_object(request_payload.get("request"))
        rows.append(
            {
                "world_name": _text(request.get("world_name")) or draft_id,
                "draft_id": draft_id,
                "revision_dir": str(revision_dir),
                "complete_for_benchmark": True,
            }
        )
    if limit is not None:
        rows = rows[: max(0, int(limit))]
    return rows


def _generation_request_for(row: dict[str, Any]) -> dict[str, Any]:
    revision_dir = Path(_text(row.get("revision_dir")))
    payload = _read_json(revision_dir / "generation_request.json")
    request = _safe_object(payload.get("request"))
    if request:
        return request
    return {
        "world_name": _text(row.get("world_name")),
        "genre": "",
        "player_count_target": 4,
        "agent_count_target": 25,
        "focus": "economy and trade-heavy world",
        "seed": "",
        "brief": "",
    }


def _monolithic_prompt(request: dict[str, Any]) -> str:
    agent_count_target = max(8, min(40, int(request.get("agent_count_target") or 25)))
    min_rooms = max(6, agent_count_target // 3)
    min_items = max(15, agent_count_target // 2)
    return "\n".join(
        [
            "You are the MONOLITHIC baseline for an Agora world compiler paper.",
            "Do not decompose the work into specialist nodes. Produce one complete builder_spec JSON object in one call.",
            "The result will be normalized and compiled by the same deterministic Agora compiler used by the strict pipeline.",
            "",
            "Original request:",
            json.dumps(request, ensure_ascii=False, indent=2),
            "",
            "Required content:",
            f"- Exactly {agent_count_target} main_characters.",
            "- Give every main character a distinct social or economic niche; do not repeat role templates under new names.",
            "- Connect each character to at least one other named character through a concrete dependency, rivalry, debt, contract, supply relation, or alliance.",
            f"- At least {min_rooms} rooms.",
            f"- At least {min_items} world-specific item_catalog entries.",
            "- Each main_character must contain at least 8 concrete inventory objects with name, description, and quantity.",
            "- Merchant stock belongs in item_catalog and property templates; do not inflate personal inventory from role-name keywords.",
            "- Each main_character must contain at least 2 property_templates and at least 2 knowledge_templates.",
            "- Do not use generic placeholder inventory such as Task Ledger, Meeting Notice, Tea Coupon, Generic Key, Basic Rations, or Blank Map.",
            "- Rooms must include archetype, ambient_palette, width_tiles, height_tiles, floor_tile, wall_tile, and a room_scene_prompt.",
            "- Every room must include 1 or 2 world-specific scene_components with component_id, label, description, anchor, width_tiles, and height_tiles.",
            "- Include gameplay_loops, player_entry_points, conflict_hooks, social_rules, item_themes, and visual_style.",
            "- Include a complete strict-top-down visual_canon and a world-specific agent_visual_policy with at least 3 palette families and 3 role style rules.",
            "- Include world_seed with registry-compatible kit_refs and policy_refs.",
            "",
            "Registry choices:",
            "- grounded_antique_market -> grounded_antique_market_v1 kits, cny_market_v1, antique_market_items_v1, CNY, cny_cash, fen",
            "- coastal_trade_city -> coastal_trade_city_v1 kits, harbor_chit_v1, harbor_trade_items_v1, HBR, harbor_chit, mark",
            "- civic_social_world -> civic_social_world_v1 kits, civic_credit_v1, civic_social_items_v1, CRD, civic_credit, point",
            "- fantasy_guild_world -> fantasy_guild_world_v1 kits, guild_gold_v1, fantasy_guild_items_v1, GLD, gold, coin",
            "",
            "Return only JSON. Do not include Markdown.",
        ]
    ).strip()


def _monolithic_schema(request: dict[str, Any]) -> dict[str, Any]:
    schema = copy.deepcopy(_builder_spec_schema())
    required = schema["required"]
    for field in (
        "gameplay_loops",
        "player_entry_points",
        "conflict_hooks",
        "custom_actions",
        "visual_canon",
        "agent_visual_policy",
    ):
        if field not in required:
            required.append(field)
    schema["properties"]["visual_canon"] = _visual_canon_schema()
    schema["properties"]["agent_visual_policy"] = _wardrobe_policy_schema()

    agent_target = max(8, min(40, int(request.get("agent_count_target") or 25)))
    characters = schema["properties"]["main_characters"]
    characters["minItems"] = agent_target
    characters["maxItems"] = agent_target

    min_rooms = max(6, agent_target // 3)
    rooms = schema["properties"]["rooms"]
    rooms["minItems"] = min_rooms
    room_item = rooms["items"]
    room_required = room_item["required"]
    for field in (
        "floor_tile",
        "wall_tile",
        "flux_floor_prompt",
        "room_scene_prompt",
        "scene_components",
    ):
        if field not in room_required:
            room_required.append(field)
    room_item["properties"]["scene_components"] = copy.deepcopy(
        _rooms_schema(min_rooms, False)["properties"]["rooms"]["items"]["properties"][
            "scene_components"
        ]
    )

    min_items = max(15, agent_target // 2)
    schema["properties"]["item_catalog"]["minItems"] = min_items
    schema["properties"]["gameplay_loops"]["minItems"] = 2
    schema["properties"]["player_entry_points"]["minItems"] = 1
    schema["properties"]["conflict_hooks"]["minItems"] = 2
    schema["properties"]["custom_actions"]["minItems"] = 3
    schema["properties"]["social_rules"]["minItems"] = 1
    return schema


def _inventory_rows(builder_spec: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for character in _safe_array(builder_spec.get("main_characters")):
        if not isinstance(character, dict):
            continue
        for item in _safe_array(character.get("inventory")):
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _count_fallback_inventory(items: list[dict[str, Any]]) -> int:
    total = 0
    for item in items:
        name = _text(item.get("name") or item.get("item_id")).lower()
        if name in FALLBACK_ITEM_NAMES:
            total += 1
    return total


def _coverage_metrics(raw_spec: dict[str, Any], normalized_spec: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    rooms = _safe_array(raw_spec.get("rooms"))
    catalog = _safe_array(raw_spec.get("item_catalog"))
    main_characters = _safe_array(raw_spec.get("main_characters"))
    gameplay_loops = _safe_array(raw_spec.get("gameplay_loops"))
    entry_points = _safe_array(raw_spec.get("player_entry_points"))
    conflict_hooks = _safe_array(raw_spec.get("conflict_hooks"))
    inventory_items = _inventory_rows(raw_spec)
    fallback_items = _count_fallback_inventory(inventory_items)
    agents_with_inventory = sum(
        1
        for character in main_characters
        if isinstance(character, dict) and len(_safe_array(character.get("inventory"))) > 0
    )
    agents_with_properties = sum(
        1
        for character in main_characters
        if isinstance(character, dict) and len(_safe_array(character.get("property_templates"))) > 0
    )
    agents_with_knowledge = sum(
        1
        for character in main_characters
        if isinstance(character, dict) and len(_safe_array(character.get("knowledge_templates"))) > 0
    )
    target_agents = max(1, int(request.get("agent_count_target") or normalized_spec.get("agent_count_target") or 25))
    world_coherence = round(
        min(
            1.0,
            0.2 * bool(rooms)
            + 0.2 * bool(catalog)
            + 0.2 * bool(gameplay_loops)
            + 0.2 * bool(entry_points)
            + 0.2 * bool(conflict_hooks),
        ),
        4,
    )
    agent_specificity = _score_ratio(agents_with_inventory + agents_with_properties + agents_with_knowledge, target_agents * 3)
    inventory_usefulness = _score_ratio(len(inventory_items) - fallback_items, max(1, len(inventory_items)))
    scale_coverage = _score_ratio(len(main_characters), target_agents)
    catalog_coverage = _score_ratio(len(catalog), max(16, target_agents // 2))
    quality_proxy = _mean([world_coherence, agent_specificity, inventory_usefulness, scale_coverage, min(1.0, catalog_coverage)])
    return {
        "rooms": len(rooms),
        "item_catalog_items": len(catalog),
        "main_characters": len(main_characters),
        "gameplay_loops": len(gameplay_loops),
        "player_entry_points": len(entry_points),
        "conflict_hooks": len(conflict_hooks),
        "inventory_items": len(inventory_items),
        "fallback_inventory_items": fallback_items,
        "agents_with_inventory": agents_with_inventory,
        "agents_with_properties": agents_with_properties,
        "agents_with_knowledge": agents_with_knowledge,
        "world_coherence_proxy": world_coherence,
        "agent_specificity_proxy": agent_specificity,
        "inventory_usefulness_proxy": inventory_usefulness,
        "scale_coverage_proxy": min(1.0, scale_coverage),
        "catalog_coverage_proxy": min(1.0, catalog_coverage),
        "quality_proxy": quality_proxy,
    }


def _compile_probe(package_root: Path, builder_spec: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    try:
        pipeline_artifacts = build_world_pipeline(builder_spec, request)
        config = _build_world_config_from_spec(package_root, builder_spec, request, pipeline_artifacts=pipeline_artifacts)
        compiler_report = _safe_object(pipeline_artifacts.get("compiler_report"))
        return {
            "compile_ok": True,
            "compiler_status": _text(compiler_report.get("status")) or "unknown",
            "runtime_agent_count": _safe_object(config.get("runtime")).get("agent_count"),
            "compiled_room_count": len(_safe_array(_safe_object(config.get("space")).get("rooms"))),
            "world_id": _text(_safe_object(config.get("scenario_meta")).get("world_id")),
        }
    except Exception as exc:
        return {
            "compile_ok": False,
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }


def _merged_contract_probe(
    builder_spec: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    agent_target = max(8, min(40, int(request.get("agent_count_target") or 25)))
    failures: list[str] = []
    rooms = _safe_array(builder_spec.get("rooms"))
    if len(rooms) < max(6, agent_target // 3):
        failures.append("insufficient_rooms")
    if any(
        not _safe_array(_safe_object(room).get("scene_components"))
        for room in rooms
    ):
        failures.append("room_semantic_components_missing")
    if not _safe_object(builder_spec.get("visual_canon")):
        failures.append("visual_canon_missing")
    if not _safe_object(builder_spec.get("agent_visual_policy")):
        failures.append("agent_visual_policy_missing")
    characters = _safe_array(builder_spec.get("main_characters"))
    if len(characters) != agent_target:
        failures.append("agent_count_mismatch")
    for character in characters:
        character_obj = _safe_object(character)
        inventory_count = len(_safe_array(character_obj.get("inventory")))
        if inventory_count < 8:
            failures.append("agent_inventory_incomplete")
            break
        if len(_safe_array(character_obj.get("property_templates"))) < 2:
            failures.append("agent_property_templates_incomplete")
            break
        if len(_safe_array(character_obj.get("knowledge_templates"))) < 2:
            failures.append("agent_knowledge_templates_incomplete")
            break
    if len(_safe_array(builder_spec.get("item_catalog"))) < max(
        15, agent_target // 2
    ):
        failures.append("item_catalog_incomplete")
    for field, minimum in (
        ("gameplay_loops", 2),
        ("player_entry_points", 1),
        ("conflict_hooks", 2),
        ("custom_actions", 3),
        ("social_rules", 1),
    ):
        if len(_safe_array(builder_spec.get(field))) < minimum:
            failures.append(f"{field}_incomplete")
    if failures:
        return {
            "merged_contract_ok": False,
            "error_codes": sorted(set(failures)),
            "error": "; ".join(sorted(set(failures))),
        }
    return {
        "merged_contract_ok": True,
        "error_codes": [],
        "error": "",
    }


def _run_one(
    package_root: Path,
    out_dir: Path,
    row: dict[str, Any],
    *,
    dry_run: bool,
    replicate: int,
    temperature: float,
    resume: bool,
) -> dict[str, Any]:
    request = _generation_request_for(row)
    world_slug = _slug(_text(row.get("world_name")) or _text(request.get("world_name")))
    suffix = f"rep{replicate:02d}"
    raw_path = out_dir / f"{world_slug}_{suffix}_monolithic_builder_spec.json"
    prompt_path = out_dir / f"{world_slug}_{suffix}_monolithic_prompt.txt"
    result_path = out_dir / f"{world_slug}_{suffix}_result.json"
    telemetry_path = out_dir / f"{world_slug}_{suffix}_vertex_calls.jsonl"
    if resume and result_path.is_file():
        cached = _read_json(result_path)
        if cached:
            print(
                f"[BASELINE_RESUME] world={row.get('world_name')} replicate={replicate}",
                flush=True,
            )
            return cached
    raw_path.unlink(missing_ok=True)
    telemetry_path.unlink(missing_ok=True)
    prompt = _monolithic_prompt(request)
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    os.environ["AGORA_VERTEX_TELEMETRY_PATH"] = str(telemetry_path)
    os.environ["AGORA_VERTEX_TELEMETRY_RUN_ID"] = f"{world_slug}_{suffix}"
    os.environ["AGORA_VERTEX_TELEMETRY_TREATMENT"] = "monolithic"

    started = time.perf_counter()
    raw_spec: dict[str, Any] = {}
    error = ""
    if dry_run:
        source_spec = _read_json(Path(_text(row.get("revision_dir"))) / "builder_spec.json")
        raw_spec = {
            key: value
            for key, value in source_spec.items()
            if key
            in {
                "world_name",
                "world_id",
                "world_seed",
                "genre",
                "premise",
                "simulation_objective",
                "agent_count_target",
                "player_count_target",
                "economy_focus",
                "exploration_focus",
                "conflict_tone",
                "visual_style",
                "visual_canon",
                "agent_visual_policy",
                "rooms",
                "item_catalog",
                "main_characters",
                "social_rules",
                "gameplay_loops",
                "player_entry_points",
                "conflict_hooks",
                "custom_actions",
                "item_themes",
            }
        }
    else:
        previous_model = os.environ.get("AGORA_WORLD_CREATOR_MODEL")
        previous_tokens = os.environ.get("AGORA_WORLD_CREATOR_MAX_OUTPUT_TOKENS")
        previous_thinking = os.environ.get("AGORA_WORLD_CREATOR_THINKING_LEVEL")
        previous_budget = os.environ.get("AGORA_WORLD_CREATOR_THINKING_BUDGET")
        os.environ["AGORA_WORLD_CREATOR_MODEL"] = os.environ.get(
            "AGORA_MONOLITHIC_BASELINE_MODEL", "gemini-3-flash-preview"
        )
        os.environ["AGORA_WORLD_CREATOR_MAX_OUTPUT_TOKENS"] = os.environ.get("AGORA_MONOLITHIC_BASELINE_MAX_OUTPUT_TOKENS", "8192")
        os.environ["AGORA_WORLD_CREATOR_THINKING_LEVEL"] = os.environ.get("AGORA_MONOLITHIC_BASELINE_THINKING_LEVEL", "low")
        os.environ["AGORA_WORLD_CREATOR_THINKING_BUDGET"] = os.environ.get("AGORA_MONOLITHIC_BASELINE_THINKING_BUDGET", "1024")
        try:
            provider = _world_creator_provider("pro")
            raw_spec = _execute_json_prompt(
                provider=provider,
                system_instruction="You generate one-shot JSON builder specifications for an ablation baseline.",
                prompt=prompt,
                response_schema=_monolithic_schema(request),
                temperature=temperature,
                max_output_tokens=int(os.environ["AGORA_WORLD_CREATOR_MAX_OUTPUT_TOKENS"]),
                thinking_level=os.environ["AGORA_WORLD_CREATOR_THINKING_LEVEL"],
                thinking_budget=int(os.environ["AGORA_WORLD_CREATOR_THINKING_BUDGET"]),
                stage="world_creator_generation",
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:1000]}"
        finally:
            if previous_model is None:
                os.environ.pop("AGORA_WORLD_CREATOR_MODEL", None)
            else:
                os.environ["AGORA_WORLD_CREATOR_MODEL"] = previous_model
            if previous_tokens is None:
                os.environ.pop("AGORA_WORLD_CREATOR_MAX_OUTPUT_TOKENS", None)
            else:
                os.environ["AGORA_WORLD_CREATOR_MAX_OUTPUT_TOKENS"] = previous_tokens
            if previous_thinking is None:
                os.environ.pop("AGORA_WORLD_CREATOR_THINKING_LEVEL", None)
            else:
                os.environ["AGORA_WORLD_CREATOR_THINKING_LEVEL"] = previous_thinking
            if previous_budget is None:
                os.environ.pop("AGORA_WORLD_CREATOR_THINKING_BUDGET", None)
            else:
                os.environ["AGORA_WORLD_CREATOR_THINKING_BUDGET"] = previous_budget

    elapsed = round(time.perf_counter() - started, 3)
    if raw_spec:
        raw_path.write_text(json.dumps(raw_spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    normalized: dict[str, Any] = {}
    normalize_error = ""
    compile_probe: dict[str, Any] = {"compile_ok": False, "error": "no raw_spec"}
    merged_contract_probe: dict[str, Any] = {
        "merged_contract_ok": False,
        "error": "no raw_spec",
    }
    if raw_spec:
        try:
            normalized = _normalize_builder_spec(raw_spec, request)
            merged_contract_probe = _merged_contract_probe(normalized, request)
            compile_probe = _compile_probe(package_root, normalized, request)
        except Exception as exc:
            normalize_error = f"{type(exc).__name__}: {str(exc)[:500]}"
            compile_probe = {"compile_ok": False, "error": normalize_error}
            merged_contract_probe = {
                "merged_contract_ok": False,
                "error": normalize_error,
            }
    metrics = _coverage_metrics(raw_spec, normalized, request) if raw_spec else {}
    result = {
        "world_name": _text(row.get("world_name")) or _text(request.get("world_name")),
        "draft_id": _text(row.get("draft_id")),
        "source_revision_dir": _text(row.get("revision_dir")),
        "replicate": replicate,
        "prompt_path": str(prompt_path),
        "raw_builder_spec_path": str(raw_path) if raw_spec else "",
        "elapsed_seconds": elapsed,
        "dry_run": dry_run,
        "generation_ok": bool(raw_spec) and not error,
        "generation_error": error,
        "normalize_error": normalize_error,
        "compile_probe": compile_probe,
        "merged_contract_probe": merged_contract_probe,
        "metrics": metrics,
        "telemetry": _telemetry_summary(telemetry_path),
    }
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "[BASELINE_DONE] "
        f"world={result['world_name']} replicate={replicate} "
        f"generation_ok={result['generation_ok']} "
        f"merged_contract_ok={result['merged_contract_probe'].get('merged_contract_ok')} "
        f"compile_ok={result['compile_probe'].get('compile_ok')} "
        f"elapsed_seconds={elapsed}",
        flush=True,
    )
    if (
        not dry_run
        and any(
            marker in result["generation_error"]
            for marker in ("HTTP 400", "HTTP 401", "HTTP 403", "HTTP 404", "HTTP 405", "HTTP 422")
        )
    ):
        raise RuntimeError(
            "Baseline stopped on a non-retryable provider/configuration error: "
            + result["generation_error"][:500]
        )
    return result


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [_safe_object(row.get("metrics")) for row in rows]
    successful_rows = [
        row
        for row in rows
        if _safe_object(row.get("merged_contract_probe")).get(
            "merged_contract_ok"
        )
        is True
        and _safe_object(row.get("compile_probe")).get("compile_ok") is True
    ]
    successful_metrics = [
        _safe_object(row.get("metrics")) for row in successful_rows
    ]
    world_names = sorted({_text(row.get("world_name")) for row in rows})
    majority_compile_worlds = 0
    first_pass_majority_worlds = 0
    any_compile_worlds = 0
    per_world: list[dict[str, Any]] = []
    for world_name in world_names:
        world_rows = [row for row in rows if _text(row.get("world_name")) == world_name]
        successes = sum(
            _safe_object(row.get("merged_contract_probe")).get(
                "merged_contract_ok"
            )
            is True
            and _safe_object(row.get("compile_probe")).get("compile_ok") is True
            for row in world_rows
        )
        any_compile_worlds += successes > 0
        majority_compile_worlds += successes > (len(world_rows) / 2.0)
        first_pass_successes = sum(
            _safe_object(row.get("merged_contract_probe")).get(
                "merged_contract_ok"
            )
            is True
            and _safe_object(row.get("compile_probe")).get("compile_ok") is True
            and int(
                _safe_object(row.get("telemetry")).get(
                    "retry_or_failure_attempt_count"
                )
                or 0
            )
            == 0
            for row in world_rows
        )
        first_pass_majority_worlds += first_pass_successes > (
            len(world_rows) / 2.0
        )
        per_world.append(
            {
                "world_name": world_name,
                "successes": successes,
                "first_pass_successes": first_pass_successes,
                "trials": len(world_rows),
                "success_rate": round(successes / len(world_rows), 4),
                "first_pass_success_rate": round(
                    first_pass_successes / len(world_rows), 4
                ),
                "wilson_95": _wilson(successes, len(world_rows)),
            }
        )
    discordant_worlds = len(world_names) - majority_compile_worlds
    paired_one_sided_sign_test_p = (
        round(0.5**discordant_worlds, 6) if discordant_worlds else 1.0
    )
    completed = len(successful_rows)
    latencies = [float(row.get("elapsed_seconds") or 0.0) for row in rows]
    success_latencies = [
        float(row.get("elapsed_seconds") or 0.0) for row in successful_rows
    ]
    failure_latencies = [
        float(row.get("elapsed_seconds") or 0.0)
        for row in rows
        if row not in successful_rows
    ]
    truncation_failures = sum(
        "did not return a JSON object" in _text(row.get("generation_error"))
        for row in rows
    )
    token_totals: Counter[str] = Counter()
    provider_attempt_count = 0
    usage_metadata_attempt_count = 0
    retry_or_failure_attempt_count = 0
    invalid_json_attempt_count = 0
    for row in rows:
        telemetry = _safe_object(row.get("telemetry"))
        provider_attempt_count += int(telemetry.get("provider_attempt_count") or 0)
        usage_metadata_attempt_count += int(
            telemetry.get("usage_metadata_attempt_count") or 0
        )
        retry_or_failure_attempt_count += int(
            telemetry.get("retry_or_failure_attempt_count") or 0
        )
        invalid_json_attempt_count += int(
            _safe_object(telemetry.get("status_counts")).get("invalid_json") or 0
        )
        for key, value in _safe_object(telemetry.get("token_totals")).items():
            token_totals[str(key)] += int(value)
    return {
        "world_count": len(world_names),
        "trial_count": len(rows),
        "generation_ok": sum(1 for row in rows if row.get("generation_ok") is True),
        "merged_contract_ok": sum(
            1
            for row in rows
            if _safe_object(row.get("merged_contract_probe")).get(
                "merged_contract_ok"
            )
            is True
        ),
        "compile_ok": sum(1 for row in rows if _safe_object(row.get("compile_probe")).get("compile_ok") is True),
        "worlds_with_any_compile_success": any_compile_worlds,
        "worlds_with_majority_compile_success": majority_compile_worlds,
        "worlds_with_majority_first_pass_success": first_pass_majority_worlds,
        "strict_source_compile_worlds": len(world_names),
        "paired_one_sided_sign_test_p": paired_one_sided_sign_test_p,
        "complete_trial_successes": completed,
        "complete_trial_success_rate": round(completed / len(rows), 4),
        "complete_trial_wilson_95": _wilson(completed, len(rows)),
        "truncation_failure_count": truncation_failures,
        "first_pass_complete_successes": sum(
            row in successful_rows
            and int(
                _safe_object(row.get("telemetry")).get(
                    "retry_or_failure_attempt_count"
                )
                or 0
            )
            == 0
            for row in rows
        ),
        "recovered_complete_successes": sum(
            row in successful_rows
            and int(
                _safe_object(row.get("telemetry")).get(
                    "retry_or_failure_attempt_count"
                )
                or 0
            )
            > 0
            for row in rows
        ),
        "provider_attempt_count": provider_attempt_count,
        "retry_or_failure_attempt_count": retry_or_failure_attempt_count,
        "invalid_json_attempt_count": invalid_json_attempt_count,
        "mean_provider_attempts_per_trial": (
            round(provider_attempt_count / len(rows), 4) if rows else 0.0
        ),
        "usage_metadata_attempt_count": usage_metadata_attempt_count,
        "usage_metadata_coverage": (
            round(usage_metadata_attempt_count / provider_attempt_count, 4)
            if provider_attempt_count
            else 0.0
        ),
        "token_totals": dict(sorted(token_totals.items())),
        "mean_total_tokens_per_trial": (
            round(token_totals.get("totalTokenCount", 0) / len(rows), 2)
            if rows
            else 0.0
        ),
        "per_world": per_world,
        "mean_elapsed_seconds": _mean([float(row.get("elapsed_seconds") or 0.0) for row in rows]),
        "median_elapsed_seconds": round(statistics.median(latencies), 4),
        "mean_success_elapsed_seconds": _mean(success_latencies),
        "mean_failure_elapsed_seconds": _mean(failure_latencies),
        "mean_rooms": _mean([float(metric.get("rooms") or 0) for metric in metrics]),
        "mean_item_catalog_items": _mean([float(metric.get("item_catalog_items") or 0) for metric in metrics]),
        "mean_main_characters": _mean([float(metric.get("main_characters") or 0) for metric in metrics]),
        "mean_inventory_items": _mean([float(metric.get("inventory_items") or 0) for metric in metrics]),
        "total_fallback_inventory_items": sum(int(metric.get("fallback_inventory_items") or 0) for metric in metrics),
        "mean_quality_proxy": _mean([float(metric.get("quality_proxy") or 0.0) for metric in metrics]),
        "mean_agent_specificity_proxy": _mean([float(metric.get("agent_specificity_proxy") or 0.0) for metric in metrics]),
        "mean_inventory_usefulness_proxy": _mean([float(metric.get("inventory_usefulness_proxy") or 0.0) for metric in metrics]),
        "successful_mean_rooms": _mean(
            [float(metric.get("rooms") or 0) for metric in successful_metrics]
        ),
        "successful_mean_item_catalog_items": _mean(
            [
                float(metric.get("item_catalog_items") or 0)
                for metric in successful_metrics
            ]
        ),
        "successful_mean_main_characters": _mean(
            [
                float(metric.get("main_characters") or 0)
                for metric in successful_metrics
            ]
        ),
        "successful_mean_inventory_items": _mean(
            [
                float(metric.get("inventory_items") or 0)
                for metric in successful_metrics
            ]
        ),
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = _safe_object(payload.get("summary"))
    lines = [
        "# Fresh Monolithic LLM Baseline",
        "",
        f"Generated: `{payload.get('generated_at')}`",
        "",
        "This baseline uses one LLM call per world to generate a complete `builder_spec` from the same original briefs used by the strict subset. It does not run decomposed planner/rooms/items/roles/wardrobe nodes, FLUX art, Pixel launch, or publish.",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Per World",
            "",
            "| World | Generation | Compile | Main Chars | Items | Inventory | Fallback | Quality | Error |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in _safe_array(payload.get("worlds")):
        metric = _safe_object(row.get("metrics"))
        compile_probe = _safe_object(row.get("compile_probe"))
        error = _text(row.get("generation_error") or row.get("normalize_error") or compile_probe.get("error"))
        lines.append(
            f"| {row.get('world_name')} | {row.get('generation_ok')} | {compile_probe.get('compile_ok')} | "
            f"{metric.get('main_characters', 0)} | {metric.get('item_catalog_items', 0)} | "
            f"{metric.get('inventory_items', 0)} | {metric.get('fallback_inventory_items', 0)} | "
            f"{metric.get('quality_proxy', 0)} | {error[:120]} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="docs/benchmark_20260724/benchmark_manifest.json")
    parser.add_argument("--out-dir", default="docs/benchmark_20260724/monolithic_baseline")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--paper-cases",
        action="store_true",
        help="Use the five one-sentence paper worlds instead of the legacy manifest subset.",
    )
    parser.add_argument("--replicates", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Use stripped strict specs to test evaluator without provider calls.")
    args = parser.parse_args()

    package_root = Path.cwd().resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = (
        _load_paper_rows(package_root, args.limit)
        if args.paper_cases
        else _load_rows(Path(args.manifest).resolve(), args.limit)
    )
    worlds: list[dict[str, Any]] = []
    for replicate in range(1, max(1, int(args.replicates)) + 1):
        for row in rows:
            print(
                f"[BASELINE_START] world={row.get('world_name')} replicate={replicate}",
                flush=True,
            )
            worlds.append(
                _run_one(
                    package_root,
                    out_dir,
                    row,
                    dry_run=args.dry_run,
                    replicate=replicate,
                    temperature=float(args.temperature),
                    resume=bool(args.resume),
                )
            )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": (
            "" if args.paper_cases else str(Path(args.manifest).resolve())
        ),
        "paper_cases": bool(args.paper_cases),
        "model": os.environ.get(
            "AGORA_MONOLITHIC_BASELINE_MODEL", "gemini-3-flash-preview"
        ),
        "max_output_tokens": int(os.environ.get("AGORA_MONOLITHIC_BASELINE_MAX_OUTPUT_TOKENS", "8192")),
        "thinking_level": os.environ.get("AGORA_MONOLITHIC_BASELINE_THINKING_LEVEL", "low"),
        "thinking_budget": int(os.environ.get("AGORA_MONOLITHIC_BASELINE_THINKING_BUDGET", "1024")),
        "temperature": float(args.temperature),
        "replicates": max(1, int(args.replicates)),
        "protocol": {
            "same_input_brief": True,
            "same_model_as_specialist": True,
            "same_temperature_as_specialist": True,
            "same_output_cap_across_monolithic_trials": True,
            "output_cap_matches_specialist_per_call": False,
            "same_json_schema": True,
            "schema_contract": "complete_merged_multimodal_builder_spec",
            "same_deterministic_compiler": True,
            "same_total_call_count": False,
            "provider_usage_metadata_recorded": True,
            "thinking_control": "thinking_level",
            "treatment": "one_monolithic_call_vs_specialist_decomposition",
            "analysis_unit": "world",
            "primary_test": "paired_one_sided_sign_test_on_majority_compile_success",
        },
        "dry_run": bool(args.dry_run),
        "summary": _summarize(worlds),
        "worlds": worlds,
    }
    json_path = out_dir / "monolithic_baseline_summary.json"
    md_path = out_dir / "monolithic_baseline_summary.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(md_path, payload)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "summary": payload["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
