#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CASES = (
    "creator_20260727_233333_efa8235f",
    "creator_20260728_002605_dd9ffc0c",
    "creator_20260728_020032_6f7b670a",
    "creator_20260728_220950_e2278e2f",
    "creator_20260728_223205_1924f12f",
)
PROHIBITED_FALLBACK_ITEM_IDS = {
    "task_ledger",
    "meeting_notice",
    "tea_coupon",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _world_record(root: Path, draft_id: str) -> dict[str, Any]:
    revision_id = "r001"
    revision_dir = root / "output" / "world_creator_drafts" / draft_id / "revisions" / revision_id
    draft = _read_json(revision_dir.parents[1] / "draft_manifest.json")
    config = _read_json(revision_dir / "world_config.json")
    compiler = _read_json(revision_dir / "compiler_report.json")
    art = _read_json(revision_dir / "art_status.json")
    brief_path = revision_dir / "input_brief.txt"
    brief = (
        " ".join(brief_path.read_text(encoding="utf-8").split())
        if brief_path.is_file()
        else ""
    )
    premise_match = re.match(r"^(.+?[.!?])(?:\s|$)", brief)
    premise_condition = premise_match.group(1).strip() if premise_match else brief
    asset_revision = f"{draft_id}_{revision_id}"
    asset_root = (
        root
        / "frontend"
        / "assets"
        / "generated"
        / "world_asset_sets"
        / asset_revision
    )
    component_manifest = _read_json(
        asset_root / "component_generation" / "component_generation_manifest.json"
    )
    component_sidecar = _read_json(asset_root / "world_map_source.components.json")
    sprite_qa = _read_json(asset_root / "sprite_batch_vision_qa.json")

    characters = [
        entry for entry in config.get("main_characters", []) if isinstance(entry, dict)
    ]
    inventories = [
        item
        for character in characters
        for item in character.get("inventory", [])
        if isinstance(item, dict)
    ]
    fallback_items = [
        item
        for item in inventories
        if str(item.get("item_id", "")).strip() in PROHIBITED_FALLBACK_ITEM_IDS
    ]
    expected_component_ids = {
        str(component.get("component_id", "")).strip()
        for room in config.get("space", {}).get("rooms", [])
        if isinstance(room, dict)
        for component in (
            room.get("visual", {}).get("scene_components", [])
            if isinstance(room.get("visual", {}), dict)
            else []
        )
        if isinstance(component, dict)
        and str(component.get("component_id", "")).strip()
    }
    generated_component_ids = {
        str(job.get("component_id", "")).strip()
        for job in component_manifest.get("jobs", [])
        if isinstance(job, dict)
        and job.get("semantic_generated") is True
        and job.get("status") == "ok"
        and str(job.get("component_id", "")).strip()
    }
    semantic_placements = [
        placement
        for placement in component_sidecar.get("placements", [])
        if isinstance(placement, dict)
        and placement.get("semantic_generated") is True
        and placement.get("pasted") is True
    ]
    placed_component_ids = {
        str(placement.get("component_id", "")).strip()
        for placement in semantic_placements
        if str(placement.get("component_id", "")).strip()
    }
    sidecar_schema = str(component_sidecar.get("schema_version", "")).strip()
    readable_component_ids = {
        str(placement.get("component_id", "")).strip()
        for placement in semantic_placements
        if (
            sidecar_schema != "agora.map_component_placements.v2"
            or placement.get("readability_pass") is True
        )
        and str(placement.get("component_id", "")).strip()
    }
    sprite_agents = [
        entry for entry in sprite_qa.get("agents", []) if isinstance(entry, dict)
    ]
    map_qa = art.get("map_vision_qa", {}) if isinstance(art.get("map_vision_qa"), dict) else {}
    pixel_qa = (
        art.get("pixel_launch_validation", {})
        if isinstance(art.get("pixel_launch_validation"), dict)
        else {}
    )
    return {
        "premise_condition": premise_condition,
        "premise_condition_sentence_count": len(
            re.findall(r"[.!?](?=\s|$)", premise_condition)
        ),
        "world_name": str(config.get("scenario_meta", {}).get("world_name", "")).strip(),
        "draft_id": draft_id,
        "revision_id": revision_id,
        "draft_status": str(draft.get("status", "")).strip(),
        "compiler_ok": compiler.get("status") == "ok",
        "room_count": len(config.get("space", {}).get("rooms", [])),
        "agent_count": len(characters),
        "inventory_entry_count": len(inventories),
        "prohibited_fallback_inventory_count": len(fallback_items),
        "visual_canon_present": bool(
            config.get("pixel_asset_pipeline", {}).get("visual_canon", {})
        ),
        "expected_semantic_component_count": len(expected_component_ids),
        "generated_semantic_component_count": len(
            expected_component_ids & generated_component_ids
        ),
        "component_sidecar_schema": sidecar_schema,
        "placed_semantic_component_count": len(
            expected_component_ids & placed_component_ids
        ),
        "readable_semantic_component_count": len(
            expected_component_ids & readable_component_ids
        ),
        "sprite_qa_pass_count": sum(
            entry.get("pass_qa") is True for entry in sprite_agents
        ),
        "sprite_qa_expected_count": len(characters),
        "sprite_qa_overall_pass": bool(
            sprite_qa.get("status") == "ok"
            and sprite_qa.get("overall_pass") is True
            and len(sprite_agents) == len(characters)
        ),
        "map_qa_pass": bool(
            map_qa.get("is_pixel_map") == "Y"
            and map_qa.get("has_visual_errors") == "N"
        ),
        "backend_startup_pass": bool(
            art.get("backend_startup_validation", {}).get("startup_ok")
        ),
        "pixel_launch_pass": bool(pixel_qa.get("startup_ok")),
        "pixel_validation_profile": str(
            pixel_qa.get("validation_profile", "legacy_full_publish")
        ).strip(),
        "publish_gate_pass": str(art.get("status", "")).strip() == "publish_ready",
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Strict Multimodal World Audit",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "| World | Rooms | Agents | Inventory | Fallback | Semantic generated | Sidecar placed | Sprite QA | Pixel | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for world in payload["worlds"]:
        sidecar_value = (
            f"{world['placed_semantic_component_count']}/"
            f"{world['expected_semantic_component_count']}"
            if world["component_sidecar_schema"]
            else "legacy n/a"
        )
        lines.append(
            "| {world_name} | {room_count} | {agent_count} | "
            "{inventory_entry_count} | {prohibited_fallback_inventory_count} | "
            "{generated_semantic_component_count}/{expected_semantic_component_count} | "
            "{sidecar} | {sprite_qa_pass_count}/{sprite_qa_expected_count} | "
            "{pixel_launch_pass} | {publish_gate_pass} |".format(
                **world,
                sidecar=sidecar_value,
            )
        )
    summary = payload["summary"]
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Strict worlds: {summary['world_count']}",
            f"- Compiler-valid: {summary['compiler_pass_count']}/{summary['world_count']}",
            f"- Publish gate passed: {summary['publish_gate_pass_count']}/{summary['world_count']}",
            f"- Rooms / agents: {summary['room_count']} / {summary['agent_count']}",
            f"- Protagonist inventory entries: {summary['inventory_entry_count']}",
            f"- Prohibited fallback entries: {summary['prohibited_fallback_inventory_count']}",
            f"- Generated semantic components: {summary['generated_semantic_component_count']}/{summary['expected_semantic_component_count']}",
            f"- Sidecar-certified placements (four post-sidecar worlds): {summary['sidecar_placed_count']}/{summary['sidecar_expected_count']}",
            f"- Sprite batch QA: {summary['sprite_qa_pass_count']}/{summary['sprite_qa_expected_count']}",
            f"- Backend / Pixel / map-QA pass: {summary['backend_pass_count']}/{summary['world_count']}, "
            f"{summary['pixel_pass_count']}/{summary['world_count']}, "
            f"{summary['map_qa_pass_count']}/{summary['world_count']}",
            "",
            "Archive of Borrowed Gravity predates the placement sidecar; its 10/10 generated "
            "component artifacts are counted, but not promoted to sidecar-certified placement evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("docs/benchmark_20260724/strict_multimodal_audit_20260729.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/benchmark_20260724/strict_multimodal_audit_20260729.md"),
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    worlds = [_world_record(root, draft_id) for draft_id in CASES]
    sidecar_worlds = [world for world in worlds if world["component_sidecar_schema"]]
    summary = {
        "world_count": len(worlds),
        "one_sentence_premise_count": sum(
            world["premise_condition_sentence_count"] == 1 for world in worlds
        ),
        "compiler_pass_count": sum(world["compiler_ok"] for world in worlds),
        "publish_gate_pass_count": sum(world["publish_gate_pass"] for world in worlds),
        "room_count": sum(world["room_count"] for world in worlds),
        "agent_count": sum(world["agent_count"] for world in worlds),
        "inventory_entry_count": sum(world["inventory_entry_count"] for world in worlds),
        "prohibited_fallback_inventory_count": sum(
            world["prohibited_fallback_inventory_count"] for world in worlds
        ),
        "expected_semantic_component_count": sum(
            world["expected_semantic_component_count"] for world in worlds
        ),
        "generated_semantic_component_count": sum(
            world["generated_semantic_component_count"] for world in worlds
        ),
        "sidecar_expected_count": sum(
            world["expected_semantic_component_count"] for world in sidecar_worlds
        ),
        "sidecar_placed_count": sum(
            world["placed_semantic_component_count"] for world in sidecar_worlds
        ),
        "sprite_qa_expected_count": sum(
            world["sprite_qa_expected_count"] for world in worlds
        ),
        "sprite_qa_pass_count": sum(
            world["sprite_qa_pass_count"] for world in worlds
        ),
        "backend_pass_count": sum(world["backend_startup_pass"] for world in worlds),
        "pixel_pass_count": sum(world["pixel_launch_pass"] for world in worlds),
        "map_qa_pass_count": sum(world["map_qa_pass"] for world in worlds),
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "case_ids": list(CASES),
            "input_protocol": (
                "The variable semantic condition is the first premise sentence. "
                "Remaining evaluator-owned instructions define scale, semantic-prop, "
                "camera, and rendering constraints."
            ),
            "prohibited_fallback_item_ids": sorted(PROHIBITED_FALLBACK_ITEM_IDS),
            "strict_rule": (
                "A world passes only when compiler, zero prohibited fallback, sprite QA, "
                "backend startup, Pixel launch, map QA, and publish gate all pass."
            ),
        },
        "summary": summary,
        "worlds": worlds,
    }
    output_json = args.output_json if args.output_json.is_absolute() else root / args.output_json
    output_md = args.output_md if args.output_md.is_absolute() else root / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    output_md.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
