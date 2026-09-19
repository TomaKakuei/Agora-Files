#!/usr/bin/env python3
"""Collect quality proxies and stage-local ablation evidence for the 10-world benchmark."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FALLBACK_ITEM_IDS = {
    "task_ledger",
    "meeting_notice",
    "tea_coupon",
}
FALLBACK_ITEM_NAMES = {
    "task ledger",
    "meeting notice",
    "tea coupon",
}
STRICT_INVENTORY_SUBSET_DRAFT_IDS = {
    "creator_20260706_053251_1ad0b086",  # Clockwork Rain Conservatory
    "creator_20260724_203817_f86ae13e",  # Aurora Court of Migrating Cities
    "creator_20260724_211037_1c17ca96",  # Mycelium Patent Bazaar
    "creator_20260724_215709_f5f54ceb",  # Tidal Embassy of Lost Languages
    "creator_20260724_224121_43ca9360",  # Sunken Satellite Monastery
}
FALLBACK_ALLOWED_BASELINE_DRAFT_IDS = {
    "creator_20260704_074735_a680c064",  # Orbital Trade Station 42670
    "creator_20260705_042509_f26a61c1",  # Clockwork Renaissance
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


def _text(value: Any) -> str:
    return str(value or "").strip()


def _score_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _iter_agent_files(revision_dir: Path) -> list[Path]:
    return sorted((revision_dir / "scenario" / "Agents").glob("*.json"))


def _non_currency_inventory(agent: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _safe_array(agent.get("inventory")):
        if not isinstance(item, dict):
            continue
        metadata = _safe_object(item.get("metadata"))
        if metadata.get("currency") is True:
            continue
        if _text(item.get("item_id")) == "civic_credit":
            continue
        rows.append(item)
    return rows


def _fallback_inventory_count(items: list[dict[str, Any]]) -> int:
    total = 0
    for item in items:
        item_id = _text(item.get("item_id")).lower()
        name = _text(item.get("name") or _safe_object(item.get("metadata")).get("name")).lower()
        if item_id in FALLBACK_ITEM_IDS or name in FALLBACK_ITEM_NAMES:
            total += 1
    return total


def _generated_inventory_count(items: list[dict[str, Any]]) -> int:
    total = 0
    for item in items:
        metadata = _safe_object(item.get("metadata"))
        if metadata.get("main_character_generated_inventory") is True:
            total += 1
    return total


def _count_floor_qa_rejections(revision_dir: Path, art_status: dict[str, Any]) -> int:
    text_blocks: list[str] = []
    log_path = revision_dir / "art_runtime" / "art_pipeline.log"
    if log_path.is_file():
        try:
            text_blocks.append(log_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    for entry in _safe_array(art_status.get("logs")):
        if isinstance(entry, dict):
            text_blocks.append(_text(entry.get("stdout")))
            text_blocks.append(_text(entry.get("stderr")))
    return sum(block.count("[FLOOR_QA] Rejecting") for block in text_blocks)


def _collect_one(row: dict[str, Any]) -> dict[str, Any]:
    revision_dir = Path(_text(row.get("revision_dir")))
    builder_spec = _read_json(revision_dir / "builder_spec.json")
    status = _read_json(revision_dir / "status.json")
    art_status = _read_json(revision_dir / "art_status.json")
    wardrobe = _read_json(revision_dir / "wardrobe_policy.json")
    compiler_report = _read_json(revision_dir / "compiler_report.json")
    compiler_critique = _read_json(revision_dir / "compiler_critique.json")

    agent_files = _iter_agent_files(revision_dir)
    agents = [_read_json(path) for path in agent_files]
    inventory_counts = [_non_currency_inventory(agent) for agent in agents]
    non_currency_total = sum(len(items) for items in inventory_counts)
    generated_inventory_total = sum(_generated_inventory_count(items) for items in inventory_counts)
    fallback_inventory_total = sum(_fallback_inventory_count(items) for items in inventory_counts)
    agents_with_generated_inventory = sum(1 for items in inventory_counts if _generated_inventory_count(items) > 0)
    agents_with_fallback_inventory = sum(1 for items in inventory_counts if _fallback_inventory_count(items) > 0)
    property_library_count = sum(len(_safe_array(agent.get("property_library"))) for agent in agents)
    knowledge_asset_count = sum(len(_safe_array(agent.get("knowledge_assets"))) for agent in agents)

    role_rules = _safe_array(wardrobe.get("role_style_rules"))
    palette_families = _safe_array(wardrobe.get("palette_families"))
    visual_rules = _safe_array(wardrobe.get("visual_consistency_rules"))
    forbidden_aesthetics = _safe_array(wardrobe.get("forbidden_aesthetics"))
    has_default_rule = bool(_safe_object(wardrobe.get("default_rule")))
    wardrobe_rule_count = len(role_rules) + (1 if has_default_rule else 0)

    art_logs = _safe_array(art_status.get("logs"))
    art_duration_seconds = round(
        sum(float(_safe_object(log).get("duration_seconds") or 0.0) for log in art_logs if isinstance(log, dict)),
        3,
    )
    floor_qa_rejections = _count_floor_qa_rejections(revision_dir, art_status)
    qa_summary = _safe_object(art_status.get("qa_summary"))
    backend_startup = _safe_object(art_status.get("backend_startup_validation"))
    pixel_launch = _safe_object(art_status.get("pixel_launch_validation"))
    pipeline_report = _safe_object(status.get("package_validation")).get("pipeline_compiler_report")
    if not isinstance(pipeline_report, dict):
        pipeline_report = compiler_report

    rooms = _safe_array(builder_spec.get("rooms"))
    main_characters = _safe_array(builder_spec.get("main_characters"))
    gameplay_loops = _safe_array(builder_spec.get("gameplay_loops"))
    player_entry_points = _safe_array(builder_spec.get("player_entry_points"))
    conflict_hooks = _safe_array(builder_spec.get("conflict_hooks"))

    automatic_quality = {
        "world_coherence_proxy": round(
            min(
                1.0,
                0.20 * bool(rooms)
                + 0.20 * bool(main_characters)
                + 0.20 * bool(gameplay_loops)
                + 0.20 * bool(player_entry_points)
                + 0.20 * bool(conflict_hooks),
            ),
            4,
        ),
        "agent_specificity_proxy": _score_ratio(
            agents_with_generated_inventory + sum(1 for agent in agents if _safe_array(agent.get("knowledge_assets"))),
            max(1, len(agents) * 2),
        ),
        "inventory_usefulness_proxy": _score_ratio(generated_inventory_total - fallback_inventory_total, max(1, non_currency_total)),
        "visual_policy_proxy": _score_ratio(
            len(palette_families) + len(role_rules) + len(visual_rules) + len(forbidden_aesthetics) + int(has_default_rule),
            16,
        ),
        "playability_gate_proxy": round(
            min(
                1.0,
                0.25 * bool(row.get("export_pixel_read") is True or qa_summary.get("pixel_read") is True)
                + 0.25 * bool(row.get("export_startup_ok") is True or backend_startup.get("startup_ok") is True)
                + 0.25 * bool(pixel_launch.get("startup_ok") is True)
                + 0.25 * bool(row.get("publish_status") == "published"),
            ),
            4,
        ),
    }

    return {
        "world_name": _text(row.get("world_name")),
        "draft_id": _text(row.get("draft_id")),
        "revision_id": _text(row.get("revision_id")),
        "access_code": _text(row.get("published_access_code") or row.get("export_access_code")),
        "revision_dir": str(revision_dir),
        "counts": {
            "rooms": len(rooms),
            "agents": len(agents),
            "main_characters": len(main_characters),
            "gameplay_loops": len(gameplay_loops),
            "player_entry_points": len(player_entry_points),
            "conflict_hooks": len(conflict_hooks),
            "non_currency_inventory_items": non_currency_total,
            "generated_inventory_items": generated_inventory_total,
            "fallback_inventory_items": fallback_inventory_total,
            "agents_with_generated_inventory": agents_with_generated_inventory,
            "agents_with_fallback_inventory": agents_with_fallback_inventory,
            "property_templates": property_library_count,
            "knowledge_assets": knowledge_asset_count,
            "wardrobe_role_rules": len(role_rules),
            "wardrobe_palette_families": len(palette_families),
            "wardrobe_visual_rules": len(visual_rules),
            "floor_qa_rejections": floor_qa_rejections,
        },
        "stage_results": {
            "published": row.get("publish_status") == "published",
            "pixel_read": bool(row.get("export_pixel_read") is True or qa_summary.get("pixel_read") is True),
            "startup_ok": bool(row.get("export_startup_ok") is True or backend_startup.get("startup_ok") is True),
            "pixel_launch_ok": bool(pixel_launch.get("startup_ok") is True),
            "compiler_ok": _text(pipeline_report.get("status")) == "ok" or _text(compiler_report.get("status")) == "ok",
            "compiler_critique_applied": bool(_safe_object(status.get("package_validation")).get("compiler_critique_applied")),
            "compiler_critique_should_repair": bool(compiler_critique.get("should_repair")),
            "art_duration_seconds": art_duration_seconds,
        },
        "quality_proxies": automatic_quality,
        "ablation_evidence": {
            "no_wardrobe_policy": {
                "stage": "visual_prompt_policy",
                "full_pipeline_coverage_units": wardrobe_rule_count + len(palette_families) + len(visual_rules),
                "ablated_coverage_units": 0,
                "expected_effect": "removes world-specific attire, forbidden-aesthetic, palette, and sprite-readability constraints before FLUX character prompting",
            },
            "fallback_allowed_inventory": {
                "stage": "agent_inventory",
                "full_pipeline_fallback_items": fallback_inventory_total,
                "full_pipeline_agents_with_generated_inventory": agents_with_generated_inventory,
                "ablated_risk": "would allow generic Task Ledger / Meeting Notice / Tea Coupon style inventories instead of hardfailing malformed JSON or missing generated items",
            },
            "no_compiler_critique": {
                "stage": "compiler_repair",
                "critique_should_repair": bool(compiler_critique.get("should_repair")),
                "critique_applied": bool(_safe_object(status.get("package_validation")).get("compiler_critique_applied")),
                "observed_effect": "equivalent on this world" if not compiler_critique.get("should_repair") else "would skip a requested repair before packaging",
            },
            "no_floor_visual_qa": {
                "stage": "map_art",
                "rejected_candidate_floors": floor_qa_rejections,
                "ablated_risk": "would admit blank-margin, poster-card, or wrong-crop floor candidates into the final map render",
            },
        },
    }


def _mean(rows: list[float]) -> float:
    if not rows:
        return 0.0
    return round(sum(rows) / len(rows), 4)


def _summarize_worlds(worlds: list[dict[str, Any]]) -> dict[str, Any]:
    total_agents = sum(int(world["counts"]["agents"]) for world in worlds)
    total_inventory = sum(int(world["counts"]["non_currency_inventory_items"]) for world in worlds)
    total_generated_inventory = sum(int(world["counts"]["generated_inventory_items"]) for world in worlds)
    total_fallback_inventory = sum(int(world["counts"]["fallback_inventory_items"]) for world in worlds)
    return {
        "world_count": len(worlds),
        "agent_count": total_agents,
        "published_worlds": sum(1 for world in worlds if world["stage_results"]["published"]),
        "pixel_read_worlds": sum(1 for world in worlds if world["stage_results"]["pixel_read"]),
        "pixel_launch_worlds": sum(1 for world in worlds if world["stage_results"]["pixel_launch_ok"]),
        "total_inventory_items": total_inventory,
        "total_generated_inventory_items": total_generated_inventory,
        "total_fallback_inventory_items": total_fallback_inventory,
        "generated_inventory_item_rate": _score_ratio(total_generated_inventory, max(1, total_inventory)),
        "fallback_inventory_item_rate": _score_ratio(total_fallback_inventory, max(1, total_inventory)),
        "agents_with_generated_inventory": sum(int(world["counts"]["agents_with_generated_inventory"]) for world in worlds),
        "agents_with_fallback_inventory": sum(int(world["counts"]["agents_with_fallback_inventory"]) for world in worlds),
        "total_wardrobe_policy_units": sum(
            int(world["counts"]["wardrobe_role_rules"])
            + int(world["counts"]["wardrobe_palette_families"])
            + int(world["counts"]["wardrobe_visual_rules"])
            for world in worlds
        ),
        "floor_qa_rejections": sum(int(world["counts"]["floor_qa_rejections"]) for world in worlds),
        "compiler_repairs_requested": sum(1 for world in worlds if world["stage_results"]["compiler_critique_should_repair"]),
        "compiler_repairs_applied": sum(1 for world in worlds if world["stage_results"]["compiler_critique_applied"]),
        "mean_quality_proxy": _mean(
            [
                _mean([float(value) for value in world["quality_proxies"].values()])
                for world in worlds
            ]
        ),
        "world_coherence_proxy_mean": _mean([float(world["quality_proxies"]["world_coherence_proxy"]) for world in worlds]),
        "agent_specificity_proxy_mean": _mean([float(world["quality_proxies"]["agent_specificity_proxy"]) for world in worlds]),
        "inventory_usefulness_proxy_mean": _mean([float(world["quality_proxies"]["inventory_usefulness_proxy"]) for world in worlds]),
        "visual_policy_proxy_mean": _mean([float(world["quality_proxies"]["visual_policy_proxy"]) for world in worlds]),
        "playability_gate_proxy_mean": _mean([float(world["quality_proxies"]["playability_gate_proxy"]) for world in worlds]),
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = []
    summary = payload["summary"]
    strict_subset = payload.get("strict_inventory_subset", {})
    strict_summary = _safe_object(strict_subset.get("summary"))
    baseline = payload.get("fallback_allowed_baseline", {})
    baseline_summary = _safe_object(baseline.get("summary"))
    lines.append("# Agora 10-World Quality and Ablation Evidence")
    lines.append("")
    lines.append(f"Generated: `{payload['generated_at']}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for key, value in summary.items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## Current Strict Inventory Subset")
    lines.append("")
    lines.append(
        "Fallback inventory is reported separately for the current strict subset so legacy artifacts do not dilute "
        "the claim about the latest inventory hardfail pipeline."
    )
    lines.append("")
    for key, value in strict_summary.items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("| Strict-Subset World | Access | Agents | Inv. Items | Generated | Fallback | Agents with Fallback |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for row in _safe_array(strict_subset.get("worlds")):
        counts = row["counts"]
        lines.append(
            f"| {row['world_name']} | `{row['access_code']}` | {counts['agents']} | "
            f"{counts['non_currency_inventory_items']} | {counts['generated_inventory_items']} | "
            f"{counts['fallback_inventory_items']} | {counts['agents_with_fallback_inventory']} |"
        )
    lines.append("")
    lines.append("## Fallback-Allowed Historical Baseline")
    lines.append("")
    lines.append(
        "This baseline uses completed legacy worlds that published while generic fallback inventory was still accepted. "
        "It is a historical counterfactual rather than a freshly generated monolithic baseline."
    )
    lines.append("")
    for key, value in baseline_summary.items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("| Baseline World | Access | Agents | Inv. Items | Generated | Fallback | Agents with Fallback | Quality Mean |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in _safe_array(baseline.get("worlds")):
        counts = row["counts"]
        q_mean = _mean([float(value) for value in row["quality_proxies"].values()])
        lines.append(
            f"| {row['world_name']} | `{row['access_code']}` | {counts['agents']} | "
            f"{counts['non_currency_inventory_items']} | {counts['generated_inventory_items']} | "
            f"{counts['fallback_inventory_items']} | {counts['agents_with_fallback_inventory']} | {q_mean} |"
        )
    lines.append("")
    lines.append("## Strict vs Fallback Baseline")
    lines.append("")
    lines.append("| Condition | Worlds | Agents | Inv. Items | Generated Rate | Fallback Rate | Agents with Fallback | Mean Quality Proxy |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    lines.append(
        f"| Current strict pipeline | {strict_summary.get('world_count', 0)} | {strict_summary.get('agent_count', 0)} | "
        f"{strict_summary.get('total_inventory_items', 0)} | {strict_summary.get('generated_inventory_item_rate', 0)} | "
        f"{strict_summary.get('fallback_inventory_item_rate', 0)} | {strict_summary.get('agents_with_fallback_inventory', 0)} | "
        f"{strict_summary.get('mean_quality_proxy', 0)} |"
    )
    lines.append(
        f"| Fallback-allowed historical baseline | {baseline_summary.get('world_count', 0)} | {baseline_summary.get('agent_count', 0)} | "
        f"{baseline_summary.get('total_inventory_items', 0)} | {baseline_summary.get('generated_inventory_item_rate', 0)} | "
        f"{baseline_summary.get('fallback_inventory_item_rate', 0)} | {baseline_summary.get('agents_with_fallback_inventory', 0)} | "
        f"{baseline_summary.get('mean_quality_proxy', 0)} |"
    )
    lines.append("")
    lines.append("## Per-World Quality Proxies")
    lines.append("")
    lines.append("| World | Access | Agents | Inv. Items | Fallback | Wardrobe Rules | Floor QA Rejects | Pixel | Launch | Quality Mean |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in payload["worlds"]:
        q = row["quality_proxies"]
        q_mean = _mean([float(value) for value in q.values()])
        counts = row["counts"]
        stage = row["stage_results"]
        lines.append(
            f"| {row['world_name']} | `{row['access_code']}` | {counts['agents']} | "
            f"{counts['non_currency_inventory_items']} | {counts['fallback_inventory_items']} | "
            f"{counts['wardrobe_role_rules']} | {counts['floor_qa_rejections']} | "
            f"{stage['pixel_read']} | {stage['pixel_launch_ok']} | {q_mean} |"
        )
    lines.append("")
    lines.append("## Ablation Evidence")
    lines.append("")
    lines.append("| Ablation | Observed Full-Pipeline Signal | Stage-Local Counterfactual |")
    lines.append("| --- | --- | --- |")
    lines.append(
        f"| No wardrobe policy | {summary['total_wardrobe_policy_units']} policy units across 10 worlds | "
        "0 policy units; sprite prompts lose world-specific attire/palette constraints |"
    )
    lines.append(
        f"| Fallback-allowed inventory | strict subset: {strict_summary.get('total_fallback_inventory_items', 0)} fallback items, "
        f"{strict_summary.get('agents_with_fallback_inventory', 0)}/{strict_summary.get('agent_count', 0)} agents with fallback inventory; "
        f"baseline: {baseline_summary.get('total_fallback_inventory_items', 0)} fallback items, "
        f"{baseline_summary.get('agents_with_fallback_inventory', 0)}/{baseline_summary.get('agent_count', 0)} agents with fallback inventory | "
        "generic inventory was accepted instead of hardfailed |"
    )
    lines.append(
        f"| No compiler critique | {summary['compiler_repairs_requested']} worlds requested repair; "
        f"{summary['compiler_repairs_applied']} repairs applied | "
        "equivalent for worlds where critique did not request repair; unsafe when repair is requested |"
    )
    lines.append(
        f"| No floor visual QA | {summary['floor_qa_rejections']} rejected floor candidates | "
        "those candidates would become possible published map artifacts |"
    )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="docs/benchmark_20260724/benchmark_manifest.json")
    parser.add_argument("--out-dir", default="docs/benchmark_20260724")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    out_dir = Path(args.out_dir).resolve()
    manifest = _read_json(manifest_path)
    rows = [
        row
        for row in _safe_array(manifest.get("drafts"))
        if isinstance(row, dict) and row.get("complete_for_benchmark") is True
    ]
    rows.sort(key=lambda row: (_text(row.get("world_name")), _text(row.get("draft_id"))))
    worlds = [_collect_one(row) for row in rows]
    summary = _summarize_worlds(worlds)
    strict_worlds = [world for world in worlds if world["draft_id"] in STRICT_INVENTORY_SUBSET_DRAFT_IDS]
    fallback_baseline_worlds = [world for world in worlds if world["draft_id"] in FALLBACK_ALLOWED_BASELINE_DRAFT_IDS]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": str(manifest_path),
        "summary": summary,
        "strict_inventory_subset": {
            "selection_rule": "latest five completed worlds used for strict inventory reporting; legacy fallback-allowed artifacts remain in the 10-world completion/runtime benchmark",
            "draft_ids": sorted(STRICT_INVENTORY_SUBSET_DRAFT_IDS),
            "summary": _summarize_worlds(strict_worlds),
            "worlds": strict_worlds,
        },
        "fallback_allowed_baseline": {
            "selection_rule": "completed legacy worlds where generic fallback inventory was accepted before the strict hardfail policy",
            "draft_ids": sorted(FALLBACK_ALLOWED_BASELINE_DRAFT_IDS),
            "summary": _summarize_worlds(fallback_baseline_worlds),
            "worlds": fallback_baseline_worlds,
        },
        "worlds": worlds,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "quality_ablation_summary.json"
    md_path = out_dir / "quality_ablation_summary.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(md_path, payload)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
