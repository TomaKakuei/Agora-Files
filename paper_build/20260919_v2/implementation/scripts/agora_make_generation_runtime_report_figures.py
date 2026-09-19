#!/usr/bin/env python3
"""Render the standalone generation/runtime scorecard figures."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = ROOT / "docs" / "living_world_benchmark_20260825_hidden"
OUTPUT_ROOT = ROOT / "docs" / "generation_runtime_scoring_report_20260825"


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)


def _rows() -> list[dict]:
    payload = json.loads(
        (BENCHMARK_ROOT / "cross_provider_comprehensive_results.json").read_text(
            encoding="utf-8"
        )
    )
    return list(payload["ranking"])


def _model_label(model: str) -> str:
    labels = {
        "gemini-3.1-pro-preview": "Gemini 3.1 Pro",
        "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
        "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
        "gemini-3.7-flash": "Gemini 3.7 Flash",
        "gemini-2.5-flash": "Gemini 2.5 Flash",
        "gpt-5.6-sol": "GPT-5.6 Sol",
        "gpt-5.6-terra": "GPT-5.6 Terra",
        "gpt-5.6-luna": "GPT-5.6 Luna",
    }
    return labels.get(model, model)


def _family_color(model: str) -> str:
    return "#b6533c" if model.startswith("gpt") else "#247a66"


def _scoreboards() -> None:
    rows = _rows()
    generation = sorted(rows, key=lambda row: row["generated_world"]["score"], reverse=True)
    runtime = sorted(
        (row for row in rows if row["generated_world_runtime"].get("score")),
        key=lambda row: row["generated_world_runtime"]["score"]["score"],
        reverse=True,
    )
    width, height = 2100, 1220
    image = Image.new("RGB", (width, height), "#fbfbf8")
    draw = ImageDraw.Draw(image)
    draw.text((72, 44), "Two independent world scorecards", font=_font(49, bold=True), fill="#17202a")
    draw.text(
        (72, 108),
        "Generation measures the compiled artifact; runtime measures 3 x 24 rounds inside an eligible generated world",
        font=_font(25),
        fill="#59636d",
    )
    panels = [
        (72, "G  World generation", generation, "generation"),
        (1090, "R  Generated-world runtime", runtime, "runtime"),
    ]
    for panel_x, title, panel_rows, kind in panels:
        draw.text((panel_x, 176), title, font=_font(31, bold=True), fill="#1d2a34")
        subtitle = "three unseen sentences; failed worlds are zero" if kind == "generation" else "mean and population SD over three trajectories"
        draw.text((panel_x, 220), subtitle, font=_font(20), fill="#59636d")
        for index, row in enumerate(panel_rows):
            y = 282 + index * 108
            model = row["model"]
            color = _family_color(model)
            if kind == "generation":
                score = float(row["generated_world"]["score"])
                suffix = f"{row['generated_world']['completed_cases']}/3 worlds"
                score_label = f"{score:.2f}"
            else:
                runtime_score = row["generated_world_runtime"]["score"]
                score = float(runtime_score["score"])
                suffix = "eligible prompt-01 world"
                score_label = f"{score:.2f} +/- {float(runtime_score['score_stddev']):.2f}"
            draw.text((panel_x, y), f"{index + 1}", font=_font(22, bold=True), fill="#727a82")
            draw.text((panel_x + 44, y), _model_label(model), font=_font(23, bold=True), fill="#1d2a34")
            draw.rounded_rectangle((panel_x + 380, y + 3, panel_x + 780, y + 38), radius=5, fill="#e4e7e5")
            draw.rounded_rectangle(
                (panel_x + 380, y + 3, panel_x + 380 + int(400 * score / 100.0), y + 38),
                radius=5,
                fill=color,
            )
            draw.text((panel_x + 800, y - 1), score_label, font=_font(22, bold=True), fill=color)
            draw.text((panel_x + 380, y + 48), suffix, font=_font(18), fill="#626c75")
    draw.text(
        (1090, 1063),
        "GPT-5.6 Luna: not eligible (no compiled prompt-01 world)",
        font=_font(20),
        fill="#8a4c3a",
    )
    draw.text(
        (72, 1148),
        "Scores are intentionally not averaged: a high runtime score cannot erase failed world construction.",
        font=_font(24, bold=True),
        fill="#34414c",
    )
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT_ROOT / "generation_runtime_scoreboards.png")


def _profile() -> None:
    rows = [
        row for row in _rows()
        if row["generated_world_runtime"].get("score")
    ]
    width, height = 1500, 1120
    image = Image.new("RGB", (width, height), "#fbfbf8")
    draw = ImageDraw.Draw(image)
    draw.text((68, 42), "Generation-runtime capability profile", font=_font(43, bold=True), fill="#17202a")
    draw.text((68, 98), "Each point retains both scores; labels show compiled worlds out of three", font=_font(23), fill="#59636d")
    left, top, right, bottom = 170, 190, 1400, 970
    draw.rectangle((left, top, right, bottom), outline="#9ca4aa", width=2)
    for tick in range(0, 101, 20):
        x = left + int((right - left) * tick / 100)
        y = bottom - int((bottom - top) * tick / 100)
        draw.line((x, top, x, bottom), fill="#e0e3e2", width=2)
        draw.line((left, y, right, y), fill="#e0e3e2", width=2)
        draw.text((x - 15, bottom + 14), str(tick), font=_font(18), fill="#606a73")
        draw.text((left - 48, y - 10), str(tick), font=_font(18), fill="#606a73")
    offsets = {
        "gemini-3.7-flash": (-235, -58),
        "gpt-5.6-sol": (-255, -82),
        "gemini-3.1-pro-preview": (-315, 68),
        "gemini-2.5-flash": (-300, -4),
        "gemini-3.1-flash-lite": (-350, 30),
        "gpt-5.6-terra": (22, -25),
        "gemini-3.5-flash-lite": (22, 12),
    }
    for row in rows:
        generation = float(row["generated_world"]["score"])
        runtime = float(row["generated_world_runtime"]["score"]["score"])
        x = left + int((right - left) * generation / 100.0)
        y = bottom - int((bottom - top) * runtime / 100.0)
        color = _family_color(row["model"])
        draw.ellipse((x - 12, y - 12, x + 12, y + 12), fill=color, outline="white", width=3)
        dx, dy = offsets.get(row["model"], (16, -20))
        label = f"{_model_label(row['model'])} ({row['generated_world']['completed_cases']}/3)"
        draw.text((x + dx, y + dy), label, font=_font(18, bold=True), fill="#26323c")
    draw.text((570, 1032), "G: world generation score", font=_font(23, bold=True), fill="#34414c")
    draw.text((26, 520), "R", font=_font(26, bold=True), fill="#34414c")
    draw.text((18, 555), "runtime", font=_font(18), fill="#34414c")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT_ROOT / "generation_runtime_profile.png")


def main() -> None:
    _scoreboards()
    _profile()
    print(OUTPUT_ROOT / "generation_runtime_scoreboards.png")
    print(OUTPUT_ROOT / "generation_runtime_profile.png")


if __name__ == "__main__":
    main()
