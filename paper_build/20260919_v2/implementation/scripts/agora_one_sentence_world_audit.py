#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FALLBACK_ITEM_IDS = {"task_ledger", "meeting_notice", "tea_coupon"}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _sentence_count(text: str) -> int:
    return len(re.findall(r"[.!?](?=\s|$)", text.strip()))


def _revision_id(manifest: dict[str, Any]) -> str:
    return str(manifest.get("current_revision", "")).strip() or "r001"


def _world_record(draft_dir: Path) -> dict[str, Any] | None:
    manifest = _read_json(draft_dir / "draft_manifest.json")
    if str(manifest.get("status", "")).strip() != "published":
        return None
    revision_id = _revision_id(manifest)
    revision_dir = draft_dir / "revisions" / revision_id
    brief_path = revision_dir / "input_brief.txt"
    if not brief_path.is_file():
        return None
    brief = " ".join(brief_path.read_text(encoding="utf-8").split())
    if _sentence_count(brief) != 1:
        return None

    world_config = _read_json(revision_dir / "world_config.json")
    compiler_report = _read_json(revision_dir / "compiler_report.json")
    main_characters = [
        value
        for value in world_config.get("main_characters", [])
        if isinstance(value, dict)
    ]
    inventory_entries = [
        item
        for character in main_characters
        for item in character.get("inventory", [])
        if isinstance(item, dict)
    ]
    fallback_entries = [
        item
        for item in inventory_entries
        if str(item.get("item_id", "")).strip() in FALLBACK_ITEM_IDS
    ]
    art = manifest.get("art", {}) if isinstance(manifest.get("art", {}), dict) else {}
    publish = (
        manifest.get("publish", {})
        if isinstance(manifest.get("publish", {}), dict)
        else {}
    )
    access_code = str(manifest.get("published_access_code", "")).strip()
    package_path = revision_dir / "world_package.db"
    asset_revision = f"{draft_dir.name}_{revision_id}"
    map_path = (
        draft_dir.parents[2]
        / "frontend"
        / "assets"
        / "generated"
        / "world_asset_sets"
        / asset_revision
        / "world_map_source.png"
    )
    return {
        "world_name": str(manifest.get("world_name", "")).strip(),
        "draft_id": draft_dir.name,
        "revision_id": revision_id,
        "input_brief": brief,
        "input_sentence_count": 1,
        "input_word_count": len(brief.split()),
        "room_count": len(world_config.get("space", {}).get("rooms", [])),
        "agent_count": len(main_characters),
        "inventory_entry_count": len(inventory_entries),
        "fallback_inventory_entry_count": len(fallback_entries),
        "compiler_ok": str(compiler_report.get("status", "")).strip() == "ok",
        "package_exists": package_path.is_file(),
        "map_exists": map_path.is_file(),
        "pixel_read": bool(
            publish.get("pixel_read")
            or art.get("qa_summary", {}).get("pixel_read")
        ),
        "startup_ok": bool(
            publish.get("startup_ok")
            or art.get("pixel_launch_validation", {}).get("startup_ok")
            or art.get("startup_validation", {}).get("startup_ok")
        ),
        "published": True,
        "access_code_present": bool(access_code),
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# One Sentence, One Executable World Audit",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "| World | Words | Rooms | Agents | Compiler | Package | Map | Pixel/startup |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for world in payload["worlds"]:
        lines.append(
            "| {world_name} | {input_word_count} | {room_count} | {agent_count} | "
            "{compiler_ok} | {package_exists} | {map_exists} | {runtime_ok} |".format(
                **world,
                runtime_ok=bool(world["pixel_read"] and world["startup_ok"]),
            )
        )
    summary = payload["summary"]
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Exact one-sentence published worlds: {summary['world_count']}",
            f"- Compiler-valid: {summary['compiler_ok_count']}/{summary['world_count']}",
            f"- Package + map present: {summary['artifact_complete_count']}/{summary['world_count']}",
            f"- Pixel/startup verified: {summary['runtime_verified_count']}/{summary['world_count']}",
            f"- Total agents: {summary['agent_count']}",
            f"- Protagonist fallback entries: {summary['fallback_inventory_entry_count']}",
            "",
            "This audit proves the one-sentence interface on existing artifacts. It does not "
            "treat the subset as a perceptual-quality benchmark.",
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
        default=Path(
            "docs/benchmark_20260724/one_sentence_world_audit_20260729.json"
        ),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path(
            "docs/benchmark_20260724/one_sentence_world_audit_20260729.md"
        ),
    )
    args = parser.parse_args()

    root = args.repo_root.resolve()
    draft_root = root / "output" / "world_creator_drafts"
    worlds = [
        record
        for draft_dir in sorted(draft_root.iterdir())
        if draft_dir.is_dir()
        if (record := _world_record(draft_dir)) is not None
    ]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "input_contract": (
                "Published drafts whose preserved input_brief.txt contains exactly "
                "one English sentence terminator."
            ),
            "fallback_item_ids": sorted(FALLBACK_ITEM_IDS),
        },
        "summary": {
            "world_count": len(worlds),
            "compiler_ok_count": sum(bool(world["compiler_ok"]) for world in worlds),
            "artifact_complete_count": sum(
                bool(world["package_exists"] and world["map_exists"])
                for world in worlds
            ),
            "runtime_verified_count": sum(
                bool(world["pixel_read"] and world["startup_ok"])
                for world in worlds
            ),
            "room_count": sum(int(world["room_count"]) for world in worlds),
            "agent_count": sum(int(world["agent_count"]) for world in worlds),
            "inventory_entry_count": sum(
                int(world["inventory_entry_count"]) for world in worlds
            ),
            "fallback_inventory_entry_count": sum(
                int(world["fallback_inventory_entry_count"]) for world in worlds
            ),
        },
        "worlds": worlds,
    }
    output_json = args.output_json if args.output_json.is_absolute() else root / args.output_json
    output_md = args.output_md if args.output_md.is_absolute() else root / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    output_md.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
