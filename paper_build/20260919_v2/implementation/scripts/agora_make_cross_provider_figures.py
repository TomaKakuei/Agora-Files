#!/usr/bin/env python3
"""Render paper figures for the cross-provider benchmark."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = ROOT / "docs" / "living_world_benchmark_20260825_hidden"
FIGURE_ROOT = BENCHMARK_ROOT / "figures"


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(
        f"/usr/share/fonts/truetype/dejavu/{name}",
        size,
    )


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _ranking_figure() -> None:
    payload = _read(BENCHMARK_ROOT / "cross_provider_comprehensive_results.json")
    rows = payload["ranking"]
    width, height = 2100, 1120
    image = Image.new("RGB", (width, height), "#fbfbf8")
    draw = ImageDraw.Draw(image)
    draw.text((80, 54), "Cross-provider world-generation benchmark", font=_font(50, bold=True), fill="#17202a")
    draw.text(
        (80, 118),
        "Five-layer composite; GPT expert review is post-hoc and model-visible",
        font=_font(26),
        fill="#58636f",
    )
    layer_names = ["World", "Comm.", "Visual", "Runtime", "Expert"]
    layer_keys = [
        "generated_world",
        "community_policy",
        "visual_realization",
        "generated_world_runtime",
        "expert_world_quality",
    ]
    matrix_x = 1450
    for index, label in enumerate(layer_names):
        draw.text((matrix_x + index * 116, 184), label, font=_font(18, bold=True), fill="#3e4954")
    draw.text((1195, 184), "Composite", font=_font(20, bold=True), fill="#3e4954")
    palette = {
        "gemini": "#247a66",
        "gpt": "#b6533c",
    }
    bar_x, bar_width = 600, 520
    for index, row in enumerate(rows):
        y = 238 + index * 101
        model = row["model"]
        family = "gpt" if model.startswith("gpt") else "gemini"
        color = palette[family]
        draw.text((82, y + 13), f"{row['rank']}", font=_font(26, bold=True), fill="#6b737b")
        draw.text((135, y + 11), model, font=_font(28, bold=True), fill="#17202a")
        draw.rounded_rectangle((bar_x, y + 8, bar_x + bar_width, y + 46), radius=5, fill="#e5e7e5")
        filled = int(bar_width * float(row["headline_score"]) / 100.0)
        draw.rounded_rectangle((bar_x, y + 8, bar_x + filled, y + 46), radius=5, fill=color)
        draw.text((1195, y + 8), f"{row['headline_score']:.2f}", font=_font(28, bold=True), fill=color)
        scores = row["layer_scores"]
        for layer_index, key in enumerate(layer_keys):
            score = float(scores[key])
            cx = matrix_x + layer_index * 116 + 35
            shade = "#d7ece5" if score >= 80 else "#f2dfbd" if score >= 50 else "#edd0cc"
            draw.rounded_rectangle((cx - 27, y + 4, cx + 50, y + 52), radius=5, fill=shade)
            draw.text((cx - 17, y + 15), f"{score:.0f}", font=_font(20, bold=True), fill="#26323c")
        if row["score_cap_reasons"]:
            reasons = "; ".join(
                reason.replace("_", " ") for reason in row["score_cap_reasons"]
            )
            draw.text((bar_x, y + 57), reasons, font=_font(17), fill="#8a4c3a")
    draw.text(
        (80, height - 58),
        "Weights: generated world 35%, community 20%, visual 15%, runtime 15%, expert 15%.",
        font=_font(22),
        fill="#58636f",
    )
    FIGURE_ROOT.mkdir(parents=True, exist_ok=True)
    image.save(FIGURE_ROOT / "cross_provider_comprehensive.png")


def _fit(path: Path, size: tuple[int, int], *, background: str = "white") -> Image.Image:
    with Image.open(path) as source:
        image = source.convert("RGB")
    return ImageOps.pad(image, size, method=Image.Resampling.LANCZOS, color=background)


def _visual_cases_figure() -> None:
    width, height = 2100, 1360
    image = Image.new("RGB", (width, height), "#f8f8f5")
    draw = ImageDraw.Draw(image)
    draw.text((72, 44), "Actual FLUX2 realizations of generated worlds", font=_font(48, bold=True), fill="#17202a")
    draw.text(
        (72, 106),
        "Maps use every referenced semantic component; character sheets are shown before atlas slicing",
        font=_font(25),
        fill="#59636d",
    )
    cases = [
        {
            "label": "GPT-5.6 Sol: The Weight of Words",
            "note": "20/20 components; 3/3 representative sprites pass",
            "map": ROOT / "frontend/assets/generated/world_asset_sets/lwbv2_gpt_5_6_sol/world_map_source.png",
            "sprites": [
                ROOT / f"frontend/assets/generated/weight_of_words_main_0{i}/lwbv2_gpt_5_6_sol/raw_character_128.png"
                for i in range(1, 4)
            ],
        },
        {
            "label": "GPT-5.6 Terra: Vowfall",
            "note": "14/14 components; 2/3 representative sprites pass",
            "map": ROOT / "frontend/assets/generated/world_asset_sets/lwbv2_gpt_5_6_terra/world_map_source.png",
            "sprites": [
                ROOT / "frontend/assets/generated/vowfall_cliff_city_main_01/lwbv2_gpt_5_6_terra_generation_repair_01/raw_character_128.png",
                ROOT / "frontend/assets/generated/vowfall_cliff_city_main_02/lwbv2_gpt_5_6_terra/raw_character_128.png",
                None,
            ],
        },
    ]
    for row_index, case in enumerate(cases):
        top = 170 + row_index * 580
        draw.text((72, top), case["label"], font=_font(31, bold=True), fill="#1d2a34")
        draw.text((72, top + 42), case["note"], font=_font(22), fill="#59636d")
        map_image = _fit(case["map"], (790, 480), background="#30363b")
        image.paste(map_image, (72, top + 84))
        draw.rectangle((72, top + 84, 862, top + 564), outline="#9aa2a8", width=2)
        for sprite_index, sprite_path in enumerate(case["sprites"]):
            left = 930 + sprite_index * 365
            if sprite_path is None:
                draw.rounded_rectangle((left, top + 126, left + 320, top + 446), radius=6, fill="#f0d9d5", outline="#b65a49", width=2)
                draw.text((left + 50, top + 238), "QA rejected", font=_font(29, bold=True), fill="#8c392e")
                draw.text((left + 39, top + 280), "3 attempts exhausted", font=_font(20), fill="#8c392e")
            else:
                sprite = _fit(sprite_path, (320, 320), background="white")
                image.paste(sprite, (left, top + 126))
                draw.rectangle((left, top + 126, left + 320, top + 446), outline="#9aa2a8", width=2)
    image.save(FIGURE_ROOT / "gpt_actual_visual_cases.png")


def _sprite_evidence(path: Path) -> tuple[Image.Image, Image.Image, Image.Image]:
    with Image.open(path) as source:
        sheet = source.convert("RGBA")
    cell_width = sheet.width // 4
    cell_height = sheet.height // 4
    front = sheet.crop((0, 0, cell_width, cell_height)).convert("RGB")
    side = sheet.crop((0, cell_height * 2, cell_width, cell_height * 3)).convert("RGB")
    return front, side, sheet.convert("RGB")


def _character_scale_figure() -> None:
    width, height = 2100, 1180
    image = Image.new("RGB", (width, height), "#f8f8f5")
    draw = ImageDraw.Draw(image)
    draw.text((72, 42), "Runtime-scale character identity", font=_font(48, bold=True), fill="#17202a")
    draw.text(
        (72, 104),
        "Accepted FLUX2 sheets shown as enlarged native frames plus the complete directional atlas",
        font=_font(25),
        fill="#59636d",
    )
    cases = [
        {
            "label": "GPT-5.6 Sol: The Weight of Words",
            "note": "compact 4-5 head silhouettes; 3/3 representative characters accepted",
            "sprites": [
                ROOT / "frontend/assets/generated/weight_of_words_main_01/lwbv2_gpt_5_6_sol/raw_character_128.png",
                ROOT / "frontend/assets/generated/weight_of_words_main_02/lwbv2_gpt_5_6_sol/raw_character_128.png",
            ],
        },
        {
            "label": "GPT-5.6 Terra: Vowfall",
            "note": "two accepted identities shown; the third representative character remains rejected",
            "sprites": [
                ROOT / "frontend/assets/generated/vowfall_cliff_city_main_01/lwbv2_gpt_5_6_terra_generation_repair_01/raw_character_128.png",
                ROOT / "frontend/assets/generated/vowfall_cliff_city_main_02/lwbv2_gpt_5_6_terra/raw_character_128.png",
            ],
        },
    ]
    for row_index, case in enumerate(cases):
        top = 170 + row_index * 500
        draw.text((72, top), case["label"], font=_font(31, bold=True), fill="#1d2a34")
        draw.text((72, top + 42), case["note"], font=_font(21), fill="#59636d")
        for agent_index, sprite_path in enumerate(case["sprites"]):
            left = 375 + agent_index * 850
            draw.text((left, top + 82), f"Representative {agent_index + 1}", font=_font(21, bold=True), fill="#34414c")
            front, side, sheet = _sprite_evidence(sprite_path)
            front = front.resize((250, 250), Image.Resampling.NEAREST)
            side = side.resize((250, 250), Image.Resampling.NEAREST)
            sheet = sheet.resize((300, 300), Image.Resampling.NEAREST)
            image.paste(front, (left, top + 120))
            image.paste(side, (left + 270, top + 120))
            image.paste(sheet, (left + 540, top + 95))
            draw.rectangle((left, top + 120, left + 250, top + 370), outline="#8e989f", width=2)
            draw.rectangle((left + 270, top + 120, left + 520, top + 370), outline="#8e989f", width=2)
            draw.rectangle((left + 540, top + 95, left + 840, top + 395), outline="#8e989f", width=2)
            draw.text((left + 88, top + 379), "front", font=_font(18), fill="#59636d")
            draw.text((left + 357, top + 379), "side", font=_font(18), fill="#59636d")
            draw.text((left + 637, top + 404), "4 x 4 atlas", font=_font(18), fill="#59636d")
    image.save(FIGURE_ROOT / "gpt_character_scale_cases.png")


def main() -> None:
    _ranking_figure()
    _visual_cases_figure()
    _character_scale_figure()
    print(FIGURE_ROOT / "cross_provider_comprehensive.png")
    print(FIGURE_ROOT / "gpt_actual_visual_cases.png")
    print(FIGURE_ROOT / "gpt_character_scale_cases.png")


if __name__ == "__main__":
    main()
