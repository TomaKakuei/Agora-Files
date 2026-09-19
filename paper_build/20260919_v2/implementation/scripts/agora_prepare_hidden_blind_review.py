#!/usr/bin/env python3
"""Prepare anonymized evidence and image boards for the hidden model review."""

from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = ROOT / "docs" / "living_world_benchmark_20260825_hidden"
RUN_ROOT = BENCHMARK_ROOT / "confirmatory_runs"
ASSET_ROOT = ROOT / "frontend" / "assets" / "generated"
WORLD_ASSET_ROOT = ASSET_ROOT / "world_asset_sets"
MODEL_DIRS = {
    "gemini-2.5-flash": "gemini_2_5_flash",
    "gemini-3.1-flash-lite": "gemini_3_1_flash_lite",
    "gemini-3.5-flash-lite": "gemini_3_5_flash_lite",
    "gemini-3.7-flash": "gemini_3_7_flash",
    "gemini-3.1-pro-preview": "gemini_3_1_pro_preview",
}
PROMPT_IDS = ["lwb_hidden_v2_01", "lwb_hidden_v2_02", "lwb_hidden_v2_03"]


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for path in (Path("/usr/share/fonts/truetype/dejavu") / filename, Path("/usr/share/fonts") / filename):
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _fit(image: Image.Image, width: int, height: int, *, background: str = "#f4f5f3") -> Image.Image:
    source = image.convert("RGBA")
    scale = min(width / source.width, height / source.height)
    resized = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (width, height), background)
    canvas.alpha_composite(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
    return canvas.convert("RGB")


def _label_mapping(path: Path) -> dict[str, str]:
    if path.is_file():
        mapping = _read(path)
        if set(mapping) == {"A", "B", "C", "D", "E"} and set(mapping.values()) == set(MODEL_DIRS):
            return {str(key): str(value) for key, value in mapping.items()}
    models = list(MODEL_DIRS)
    secrets.SystemRandom().shuffle(models)
    mapping = dict(zip("ABCDE", models))
    _write(path, mapping)
    return mapping


def _pick(mapping: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: mapping.get(key) for key in keys if mapping.get(key) not in (None, "", [], {})}


def _room_summary(room: dict[str, Any]) -> dict[str, Any]:
    visual = room.get("visual") if isinstance(room.get("visual"), dict) else {}
    components = room.get("scene_components") if isinstance(room.get("scene_components"), list) else []
    if not components:
        components = visual.get("scene_components") if isinstance(visual.get("scene_components"), list) else []
    return {
        **_pick(
            room,
            "room_id",
            "name",
            "purpose",
            "description",
            "gameplay_function",
            "atmosphere",
            "distinctive_features",
            "biome",
            "decor_tags",
            "activity_tags",
        ),
        "scene_components": [
            _pick(item, "component_id", "name", "description", "function")
            for item in components
            if isinstance(item, dict)
        ],
    }


def _agent_summary(agent: dict[str, Any]) -> dict[str, Any]:
    relationships = agent.get("relationships") if isinstance(agent.get("relationships"), list) else []
    return {
        **_pick(
            agent,
            "display_name",
            "name",
            "role_name",
            "home_room_id",
            "home_base",
            "personality",
            "daily_activity",
            "activity",
            "activity_directive",
            "goal",
            "arc_goal",
            "archetype",
            "private_notes",
        ),
        "relationships": [
            _pick(item, "target_character_name", "target_name", "relationship_type", "description")
            for item in relationships
            if isinstance(item, dict)
        ],
        "inventory": [
            _pick(item, "name", "description", "quantity")
            for item in agent.get("inventory", [])
            if isinstance(item, dict)
        ],
        "properties": [
            _pick(item, "asset_name", "asset_type", "story_use")
            for item in agent.get("property_library", agent.get("property_templates", []))
            if isinstance(item, dict)
        ],
        "knowledge": [
            _pick(item, "topic", "summary", "confidence")
            for item in agent.get("knowledge_assets", agent.get("knowledge_templates", []))
            if isinstance(item, dict)
        ],
    }


def _case_evidence(model_dir: str, prompt_id: str, sentence: str) -> dict[str, Any]:
    case_dir = RUN_ROOT / model_dir / prompt_id
    result_path = case_dir / f"{prompt_id}_r01_decomposed_result.json"
    result = _read(result_path)
    if result.get("complete_success") is not True:
        return {
            "prompt_id": prompt_id,
            "sentence": sentence,
            "status": "failed",
            "failure_stage": "typed world generation or compilation",
        }
    builder = _read(case_dir / f"{prompt_id}_r01_decomposed_builder_spec.json")
    config = _read(case_dir / f"{prompt_id}_r01_decomposed_world_config.json")
    return {
        "prompt_id": prompt_id,
        "sentence": sentence,
        "status": "compiled",
        "world": _pick(
            builder,
            "world_name",
            "premise",
            "world_dynamics",
            "simulation_objective",
            "economy_focus",
            "exploration_focus",
            "social_rules",
            "conflict_tone",
            "visual_style",
        ),
        "rooms": [_room_summary(item) for item in builder.get("rooms", []) if isinstance(item, dict)],
        "agents": [_agent_summary(item) for item in config.get("main_characters", []) if isinstance(item, dict)],
        "gameplay_loops": builder.get("gameplay_loops", []),
        "custom_actions": builder.get("custom_actions", []),
        "open_action_examples": builder.get("open_action_examples", []),
        "conflict_hooks": builder.get("conflict_hooks", []),
    }


def _map_board(mapping: dict[str, str], output: Path) -> None:
    tile_w, tile_h = 760, 570
    margin, header = 28, 58
    board = Image.new("RGB", (margin * 3 + tile_w * 2, margin * 4 + (tile_h + header) * 3), "#eceeea")
    draw = ImageDraw.Draw(board)
    label_font = _font(30, bold=True)
    for index, label in enumerate("ABCDE"):
        row, col = divmod(index, 2)
        x = margin + col * (tile_w + margin)
        y = margin + row * (tile_h + header + margin)
        draw.rectangle((x, y, x + tile_w, y + tile_h + header), fill="#ffffff", outline="#30342f", width=2)
        draw.text((x + 18, y + 12), f"World {label}", fill="#171a17", font=label_font)
        model_dir = MODEL_DIRS[mapping[label]]
        image_path = WORLD_ASSET_ROOT / f"lwbv2_{model_dir}" / "world_map_source.png"
        board.paste(_fit(Image.open(image_path), tile_w - 4, tile_h - 4), (x + 2, y + header + 2))
    board.save(output)


def _agent_atlases(model: str) -> list[tuple[Path, int, int]]:
    manifest = _read(WORLD_ASSET_ROOT / f"lwbv2_{MODEL_DIRS[model]}" / "world_asset_set_manifest.json")
    paths: list[tuple[Path, int, int]] = []
    for item in manifest.get("agents", []):
        if not isinstance(item, dict):
            continue
        bundle = item.get("asset_bundle") if isinstance(item.get("asset_bundle"), dict) else {}
        atlas = Path(str(bundle.get("atlas_png", "")))
        metadata_path = Path(str(bundle.get("atlas_json", "")))
        if atlas.is_file() and metadata_path.is_file():
            metadata = _read(metadata_path)
            frame_size = metadata.get("meta", {}).get("frame_size", {})
            frame_width = int(frame_size.get("w", 0))
            frame_height = int(frame_size.get("h", 0))
            if frame_width > 0 and frame_height > 0:
                paths.append((atlas, frame_width, frame_height))
    return paths[:3]


def _character_board(mapping: dict[str, str], output: Path) -> None:
    shown = 172
    label_w, gap, outer = 120, 12, 24
    columns = 9
    row_h = shown + 52
    width = outer * 2 + label_w + columns * shown + (columns - 1) * gap
    height = outer * 2 + 5 * row_h
    board = Image.new("RGBA", (width, height), "#eceeea")
    draw = ImageDraw.Draw(board)
    label_font = _font(28, bold=True)
    small_font = _font(15)
    directions = ((0, "front"), (2, "left"), (3, "right"))
    for row, label in enumerate("ABCDE"):
        y = outer + row * row_h
        draw.text((outer, y + 55), label, fill="#171a17", font=label_font)
        atlases = _agent_atlases(mapping[label])
        for agent_index, (atlas_path, frame_width, frame_height) in enumerate(atlases):
            atlas = Image.open(atlas_path).convert("RGBA")
            for direction_index, (atlas_row, direction) in enumerate(directions):
                column = agent_index * 3 + direction_index
                x = outer + label_w + column * (shown + gap)
                frame = atlas.crop((0, atlas_row * frame_height, frame_width, (atlas_row + 1) * frame_height))
                frame = frame.resize((shown, shown), Image.Resampling.NEAREST)
                cell = Image.new("RGBA", (shown, shown), "#ffffff")
                cell.alpha_composite(frame)
                board.alpha_composite(cell, (x, y + 26))
                draw.rectangle((x, y + 26, x + shown - 1, y + 26 + shown - 1), outline="#666b65", width=1)
                draw.text((x + 4, y + 4), f"{agent_index + 1}:{direction}", fill="#30342f", font=small_font)
        draw.line((outer, y + row_h - 4, width - outer, y + row_h - 4), fill="#c3c7c1", width=1)
    board.convert("RGB").save(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-root", type=Path, default=BENCHMARK_ROOT)
    args = parser.parse_args()
    root = args.benchmark_root.resolve()
    figures = root / "figures"
    blind_root = root / "blind_review"
    figures.mkdir(parents=True, exist_ok=True)
    blind_root.mkdir(parents=True, exist_ok=True)
    mapping = _label_mapping(blind_root / "blind_label_map.json")
    suite = _read(root / "prompt_suite_hidden_v2.json")
    prompts = {
        str(item.get("prompt_id") or item.get("id")): str(item.get("sentence") or item.get("prompt"))
        for item in suite.get("prompts", suite.get("items", []))
        if isinstance(item, dict)
    }
    for label in "ABCDE":
        model_dir = MODEL_DIRS[mapping[label]]
        evidence = {
            "anonymous_label": label,
            "instructions": "Score only the supplied evidence. A failed case receives zero on all expert axes.",
            "cases": [_case_evidence(model_dir, prompt_id, prompts[prompt_id]) for prompt_id in PROMPT_IDS],
            "representative_visual": f"World {label} in figures/maps_blind.png and row {label} in figures/characters_blind.png",
        }
        _write(blind_root / f"world_{label}.json", evidence)
    _map_board(mapping, figures / "maps_blind.png")
    _character_board(mapping, figures / "characters_blind.png")
    _write(
        blind_root / "review_form.json",
        {
            "reviewer": "advanced_llm_single_blind",
            "status": "unscored",
            "axis_weights": {
                "premise_transformation": 0.15,
                "causal_institutions": 0.20,
                "spatial_material_imagination": 0.15,
                "social_interdependence": 0.15,
                "interaction_imagination": 0.20,
                "experienced_visual_coherence": 0.15,
            },
            "labels": {label: {"cases": {prompt_id: {} for prompt_id in PROMPT_IDS}} for label in "ABCDE"},
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
