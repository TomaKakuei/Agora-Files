#!/usr/bin/env python3
"""Extract qualitative case-study evidence from completed Agora worlds."""

from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs" / "benchmark_20260724" / "benchmark_manifest.json"
OUT_DIR = ROOT / "docs" / "benchmark_20260724"
FIG_DIR = ROOT / "docs" / "figures_20260725"

CASE_DRAFT_IDS = [
    "creator_20260724_203817_f86ae13e",  # Aurora Court of Migrating Cities
    "creator_20260724_211037_1c17ca96",  # Mycelium Patent Bazaar
    "creator_20260724_215709_f5f54ceb",  # Tidal Embassy of Lost Languages
    "creator_20260724_224121_43ca9360",  # Sunken Satellite Monastery
]

COLORS = {
    "ink": "#1d2433",
    "muted": "#617086",
    "surface": "#f7f9fc",
    "teal": "#146c72",
    "blue": "#314f9f",
    "green": "#24744f",
    "rust": "#9b4f1c",
    "gold": "#c49a2c",
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


def _truncate(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _rows_by_draft() -> dict[str, dict[str, Any]]:
    manifest = _read_json(MANIFEST_PATH)
    return {
        _text(row.get("draft_id")): dict(row)
        for row in _safe_array(manifest.get("drafts"))
        if isinstance(row, dict) and _text(row.get("draft_id"))
    }


def _first_agent(revision_dir: Path) -> dict[str, Any]:
    for path in sorted((revision_dir / "scenario" / "Agents").glob("*.json")):
        payload = _read_json(path)
        if payload:
            payload["_path"] = str(path)
            return payload
    return {}


def _inventory_examples(agent: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for item in _safe_array(agent.get("inventory")):
        if not isinstance(item, dict):
            continue
        metadata = _safe_object(item.get("metadata"))
        if metadata.get("currency") is True:
            continue
        examples.append(
            {
                "name": _text(item.get("name") or metadata.get("name") or item.get("item_id")),
                "description": _truncate(_text(item.get("description") or metadata.get("description")), 140),
                "generated": bool(metadata.get("main_character_generated_inventory") is True),
            }
        )
        if len(examples) >= limit:
            break
    return examples


def _asset_evidence(row: dict[str, Any]) -> dict[str, str]:
    access = _text(row.get("export_access_code") or row.get("published_access_code"))
    draft_id = _text(row.get("draft_id"))
    revision_id = _text(row.get("revision_id") or "r001")
    package_root = ROOT / "output" / "package_exports" / access / "materialized" / "assets" / "generated"
    world_asset_dir = package_root / "world_asset_sets" / f"{draft_id}_{revision_id}"
    evidence = {
        "world_map_source": str(world_asset_dir / "world_map_source.png") if (world_asset_dir / "world_map_source.png").is_file() else "",
        "world_asset_manifest": str(world_asset_dir / "world_asset_set_manifest.json") if (world_asset_dir / "world_asset_set_manifest.json").is_file() else "",
    }
    for atlas in sorted(package_root.glob(f"*/{draft_id}_{revision_id}/character_atlas.png")):
        evidence["sample_character_atlas"] = str(atlas)
        break
    return evidence


def _extract_case(row: dict[str, Any]) -> dict[str, Any]:
    revision_dir = Path(_text(row.get("revision_dir")))
    request = _safe_object(_read_json(revision_dir / "generation_request.json").get("request"))
    builder = _read_json(revision_dir / "builder_spec.json")
    agent = _first_agent(revision_dir)
    builder_character = _safe_object(_safe_array(builder.get("main_characters"))[0]) if _safe_array(builder.get("main_characters")) else {}
    rooms = _safe_array(builder.get("rooms"))
    loops = _safe_array(builder.get("gameplay_loops"))
    return {
        "world_name": _text(row.get("world_name")),
        "access_code": _text(row.get("export_access_code") or row.get("published_access_code")),
        "draft_id": _text(row.get("draft_id")),
        "brief": _text(request.get("brief")),
        "premise": _text(builder.get("premise")),
        "visual_style": _text(builder.get("visual_style")),
        "sample_rooms": [
            {
                "name": _text(room.get("name")),
                "purpose": _truncate(_text(room.get("purpose")), 130),
                "archetype": _text(room.get("archetype")),
            }
            for room in rooms[:3]
            if isinstance(room, dict)
        ],
        "gameplay_loop": {
            "label": _text(_safe_object(loops[0]).get("label")) if loops else "",
            "summary": _truncate(_text(_safe_object(loops[0]).get("summary")), 180) if loops else "",
            "pressure": _truncate(_text(_safe_object(loops[0]).get("pressure")), 120) if loops else "",
        },
        "conflict_hooks": [_truncate(_text(item), 140) for item in _safe_array(builder.get("conflict_hooks"))[:3]],
        "sample_agent": {
            "display_name": _text(agent.get("display_name") or builder_character.get("display_name")),
            "role_name": _text(agent.get("role_name") or builder_character.get("role_name")),
            "activity": _truncate(_text(agent.get("activity") or builder_character.get("activity")), 160),
            "home_base": _text(agent.get("home_base") or builder_character.get("home_base")),
            "inventory_examples": _inventory_examples(agent),
            "property_example": _safe_object(_safe_array(agent.get("property_library"))[0]) if _safe_array(agent.get("property_library")) else {},
            "knowledge_example": _safe_object(_safe_array(agent.get("knowledge_assets"))[0]) if _safe_array(agent.get("knowledge_assets")) else {},
            "source_path": _text(agent.get("_path")),
        },
        "asset_evidence": _asset_evidence(row),
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Agora Qualitative Case Studies",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        "These cases are extracted from real strict-pipeline published worlds. They provide qualitative evidence for world-specific rooms, agents, inventory, conflict pressure, and generated art assets.",
        "",
    ]
    for case in payload["cases"]:
        agent = case["sample_agent"]
        lines.extend(
            [
                f"## {case['world_name']}",
                "",
                f"- Access code: `{case['access_code']}`",
                f"- Draft: `{case['draft_id']}`",
                f"- Premise: {case['premise']}",
                f"- Visual style: {case['visual_style']}",
                f"- Sample agent: {agent['display_name']} / {agent['role_name']} at {agent['home_base']}",
                f"- Agent activity: {agent['activity']}",
                "- Inventory examples: "
                + "; ".join(f"{item['name']} ({item['description']})" for item in agent["inventory_examples"]),
                "- Rooms: "
                + "; ".join(f"{room['name']} [{room['archetype']}] - {room['purpose']}" for room in case["sample_rooms"]),
                "- Conflict hooks: " + "; ".join(case["conflict_hooks"]),
                f"- World map asset: `{case['asset_evidence'].get('world_map_source', '')}`",
                f"- Character atlas asset: `{case['asset_evidence'].get('sample_character_atlas', '')}`",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _draw_case_cards(cases: list[dict[str, Any]], path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 8.8))
    axes = axes.flatten()
    border_colors = [COLORS["teal"], COLORS["green"], COLORS["blue"], COLORS["rust"]]
    for ax, case, color in zip(axes, cases, border_colors):
        ax.set_axis_off()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        card = FancyBboxPatch(
            (0.02, 0.03),
            0.96,
            0.94,
            boxstyle="round,pad=0.018,rounding_size=0.025",
            facecolor=COLORS["surface"],
            edgecolor=color,
            linewidth=2.0,
        )
        ax.add_patch(card)
        agent = case["sample_agent"]
        inv = ", ".join(item["name"] for item in agent["inventory_examples"][:3])
        room = case["sample_rooms"][0] if case["sample_rooms"] else {}
        hook = case["conflict_hooks"][0] if case["conflict_hooks"] else ""
        lines = [
            case["world_name"],
            f"Agent: {agent['role_name']}",
            f"Room: {room.get('name', '')}",
            f"Inventory: {inv}",
            f"Pressure: {_truncate(hook, 115)}",
        ]
        ax.text(0.07, 0.88, lines[0], fontsize=15, weight="bold", color=COLORS["ink"], va="top")
        y = 0.72
        for line in lines[1:]:
            wrapped = textwrap.fill(line, width=52)
            ax.text(0.07, y, wrapped, fontsize=10.8, color=COLORS["ink"], va="top")
            y -= 0.14 + 0.035 * wrapped.count("\n")
    fig.suptitle("Qualitative examples from strict-pipeline published worlds", fontsize=18, weight="bold", color=COLORS["ink"], y=0.99)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    rows = _rows_by_draft()
    cases = [_extract_case(rows[draft_id]) for draft_id in CASE_DRAFT_IDS if draft_id in rows]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_draft_ids": CASE_DRAFT_IDS,
        "cases": cases,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "qualitative_case_studies_20260726.json"
    md_path = OUT_DIR / "qualitative_case_studies_20260726.md"
    fig_path = FIG_DIR / "qualitative_case_examples.png"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_markdown(md_path, payload)
    _draw_case_cards(cases, fig_path)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "figure": str(fig_path), "case_count": len(cases)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
