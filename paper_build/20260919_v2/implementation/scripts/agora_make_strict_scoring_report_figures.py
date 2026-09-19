#!/usr/bin/env python3
"""Render figures for the strict generation/runtime scoring report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "living_world_benchmark_20260825_hidden"
RESULTS = EVIDENCE / "strict_generation_runtime_results_v1_1.json"
OUTPUT = ROOT / "docs" / "generation_runtime_scoring_strict_v1_1_20260826"


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)


def load() -> dict[str, Any]:
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def label(model: str) -> str:
    return {
        "gpt-5.6-sol": "GPT-5.6 Sol",
        "gpt-5.6-terra": "GPT-5.6 Terra",
        "gpt-5.6-luna": "GPT-5.6 Luna",
        "gemini-2.5-flash": "Gemini 2.5 Flash",
        "gemini-3.1-pro-preview": "Gemini 3.1 Pro",
        "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
        "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
        "gemini-3.7-flash": "Gemini 3.7 Flash",
    }.get(model, model)


def family_color(model: str) -> str:
    return "#b6533c" if model.startswith("gpt") else "#247a66"


def interpolate(left: tuple[int, int, int], right: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    ratio = max(0.0, min(1.0, ratio))
    return tuple(round(a + (b - a) * ratio) for a, b in zip(left, right))


def cell_color(value: float) -> tuple[int, int, int]:
    anchors = [
        (0.0, (151, 62, 47)),
        (40.0, (202, 116, 63)),
        (60.0, (219, 181, 91)),
        (75.0, (87, 148, 126)),
        (100.0, (30, 104, 88)),
    ]
    for (x0, color0), (x1, color1) in zip(anchors, anchors[1:]):
        if value <= x1:
            return interpolate(color0, color1, (value - x0) / (x1 - x0))
    return anchors[-1][1]


def comparison() -> None:
    payload = load()
    width, height = 2200, 1300
    image = Image.new("RGB", (width, height), "#fbfbf8")
    draw = ImageDraw.Draw(image)
    draw.text((70, 42), "Compliance is not world quality", font=font(48, bold=True), fill="#17202a")
    draw.text(
        (70, 106),
        "Old contract scores are retained; strict v1.1 adds causal, social, human, open-action, and anchored expert evidence",
        font=font(24),
        fill="#59636d",
    )
    panels = [
        (70, "World generation", payload["generation"], "contract_compliance", "strict_generation_score"),
        (1130, "Generated-world runtime", [row for row in payload["runtime"] if row["strict_runtime_score"] is not None], "execution_compliance", "strict_runtime_score"),
    ]
    for left, title, rows, old_key, new_key in panels:
        draw.text((left, 180), title, font=font(32, bold=True), fill="#1d2a34")
        axis_left, axis_right = left + 330, left + 920
        for tick in range(0, 101, 20):
            x = axis_left + round((axis_right - axis_left) * tick / 100)
            draw.line((x, 250, x, 1120), fill="#e2e4e2", width=2)
            draw.text((x - 13, 1132), str(tick), font=font(17), fill="#68727b")
        for index, row in enumerate(rows):
            y = 294 + index * 105
            model = row["model"]
            old = float(row["components"][old_key])
            new = float(row[new_key])
            old_x = axis_left + round((axis_right - axis_left) * old / 100)
            new_x = axis_left + round((axis_right - axis_left) * new / 100)
            draw.text((left, y - 16), label(model), font=font(20, bold=True), fill="#26323c")
            draw.line((new_x, y + 32, old_x, y + 32), fill="#aeb5b7", width=5)
            draw.ellipse((old_x - 10, y + 22, old_x + 10, y + 42), fill="#727b82")
            color = family_color(model)
            draw.ellipse((new_x - 13, y + 19, new_x + 13, y + 45), fill=color, outline="white", width=3)
            draw.text((old_x - 24, y + 50), f"{old:.1f}", font=font(16), fill="#657078")
            draw.text((new_x - 25, y - 10), f"{new:.1f}", font=font(17, bold=True), fill=color)
    draw.text((70, 1220), "gray = contract compliance", font=font(22), fill="#68727b")
    draw.text((410, 1220), "color = strict quality score", font=font(22, bold=True), fill="#2b6057")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT / "old_vs_strict_scores.png")


def heatmap(
    filename: str,
    title: str,
    subtitle: str,
    rows: list[dict[str, Any]],
    panels: list[tuple[str, str, list[tuple[str, str]]]],
) -> None:
    width = 2300
    panel_height = 650
    height = 180 + panel_height * len(panels)
    image = Image.new("RGB", (width, height), "#fbfbf8")
    draw = ImageDraw.Draw(image)
    draw.text((65, 38), title, font=font(45, bold=True), fill="#17202a")
    draw.text((65, 98), subtitle, font=font(23), fill="#59636d")
    label_width = 315
    cell_width = 185
    cell_height = 55
    for panel_index, (panel_title, data_key, axes) in enumerate(panels):
        top = 165 + panel_index * panel_height
        draw.text((65, top), panel_title, font=font(28, bold=True), fill="#1d2a34")
        grid_top = top + 100
        for column, (_, axis_label) in enumerate(axes):
            x = label_width + column * cell_width
            words = axis_label.split(" ")
            if len(words) > 1:
                first = " ".join(words[: (len(words) + 1) // 2])
                second = " ".join(words[(len(words) + 1) // 2 :])
                draw.text((x + 5, top + 45), first, font=font(16, bold=True), fill="#3a4650")
                draw.text((x + 5, top + 66), second, font=font(16, bold=True), fill="#3a4650")
            else:
                draw.text((x + 5, top + 56), axis_label, font=font(16, bold=True), fill="#3a4650")
        for row_index, row in enumerate(rows):
            y = grid_top + row_index * cell_height
            draw.text((65, y + 15), label(row["model"]), font=font(18, bold=True), fill="#26323c")
            values = row[data_key]
            for column, (axis_key, _) in enumerate(axes):
                value = float(values[axis_key])
                x = label_width + column * cell_width
                fill = cell_color(value)
                draw.rectangle((x, y, x + cell_width - 5, y + cell_height - 5), fill=fill)
                text_fill = "#ffffff" if value < 45 or value > 82 else "#17202a"
                rendered = f"{value:.0f}"
                bbox = draw.textbbox((0, 0), rendered, font=font(18, bold=True))
                draw.text(
                    (x + (cell_width - 5 - (bbox[2] - bbox[0])) / 2, y + 13),
                    rendered,
                    font=font(18, bold=True),
                    fill=text_fill,
                )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT / filename)


def generation_heatmap() -> None:
    rows = load()["generation"]
    heatmap(
        "strict_generation_lines.png",
        "Generation quality: twenty separate lines",
        "Failures remain zero; objective artifact evidence and anchored expert judgment are shown separately",
        rows,
        [
            (
                "Objective artifact evidence",
                "objective_axes",
                [
                    ("causal_system", "Causal system"),
                    ("spatial_semantic_necessity", "Spatial necessity"),
                    ("agent_individuation", "Agent individuation"),
                    ("social_interdependence", "Social interdependence"),
                    ("material_economy", "Material economy"),
                    ("interaction_depth", "Interaction depth"),
                    ("human_affordance", "Human affordance"),
                    ("template_escape", "Template escape"),
                    ("visual_authorship", "Visual authorship"),
                    ("first_pass_robustness", "First pass"),
                ],
            ),
            (
                "Anchored advanced-LLM review",
                "expert_axes",
                [
                    ("premise_transformation", "Premise transformed"),
                    ("causal_institutional_depth", "Causal depth"),
                    ("spatial_material_imagination", "Spatial imagination"),
                    ("agent_personhood", "Agent personhood"),
                    ("social_tension_interdependence", "Social tension"),
                    ("interaction_possibility", "Play possibilities"),
                    ("open_endedness", "Open endedness"),
                    ("human_legibility", "Human legibility"),
                    ("experienced_visual_coherence", "Visual coherence"),
                    ("holistic_world_desire", "Want to explore"),
                ],
            ),
        ],
    )


def runtime_heatmap() -> None:
    rows = [row for row in load()["runtime"] if row["strict_runtime_score"] is not None]
    heatmap(
        "strict_runtime_lines.png",
        "Runtime quality: twenty separate lines",
        "Contract success is excluded here; these lines ask whether the executed community was actually alive and consequential",
        rows,
        [
            (
                "Objective long-trajectory evidence",
                "trace_axes",
                [
                    ("intervention_sensitivity", "Intervention sensitivity"),
                    ("causal_threading", "Causal threading"),
                    ("role_conditioning", "Role conditioned"),
                    ("open_action_substance", "Open substance"),
                    ("state_evolution", "State evolution"),
                    ("social_differentiation", "Social differentiation"),
                    ("human_impact", "Human impact"),
                    ("conflict_and_recovery", "Conflict recovery"),
                    ("behavioral_specificity", "Specific behavior"),
                    ("spatial_causality", "Spatial causality"),
                ],
            ),
            (
                "Anchored advanced-LLM review",
                "expert_axes",
                [
                    ("intervention_comprehension", "Intervention understood"),
                    ("causal_continuity", "Causal continuity"),
                    ("role_identity_fidelity", "Identity fidelity"),
                    ("social_differentiation_conflict", "Social conflict"),
                    ("human_agency_influence", "Human agency"),
                    ("open_action_imagination", "Open imagination"),
                    ("world_state_consequence_depth", "Consequence depth"),
                    ("spatial_material_grounding", "Spatial grounding"),
                    ("long_horizon_adaptation", "Long adaptation"),
                    ("lived_world_coherence", "Lived coherence"),
                ],
            ),
        ],
    )


def strict_profile() -> None:
    payload = load()
    generation = {row["model"]: row for row in payload["generation"]}
    runtime = {
        row["model"]: row for row in payload["runtime"] if row["strict_runtime_score"] is not None
    }
    width, height = 1550, 1100
    image = Image.new("RGB", (width, height), "#fbfbf8")
    draw = ImageDraw.Draw(image)
    draw.text((70, 38), "Strict generation-runtime profile", font=font(45, bold=True), fill="#17202a")
    draw.text((70, 98), "High compliance alone no longer places a model in the upper-right corner", font=font(23), fill="#59636d")
    left, top, right, bottom = 170, 190, 1430, 960
    draw.rectangle((left, top, right, bottom), outline="#9ca4aa", width=2)
    for tick in range(0, 101, 20):
        x = left + round((right - left) * tick / 100)
        y = bottom - round((bottom - top) * tick / 100)
        draw.line((x, top, x, bottom), fill="#e0e3e2", width=2)
        draw.line((left, y, right, y), fill="#e0e3e2", width=2)
        draw.text((x - 14, bottom + 14), str(tick), font=font(18), fill="#606a73")
        draw.text((left - 48, y - 10), str(tick), font=font(18), fill="#606a73")
    offsets = {
        "gpt-5.6-sol": (-190, -65),
        "gpt-5.6-terra": (18, 40),
        "gemini-2.5-flash": (-390, -35),
        "gemini-3.7-flash": (-140, 15),
        "gemini-3.1-pro-preview": (-470, 80),
        "gemini-3.1-flash-lite": (-440, 70),
        "gemini-3.5-flash-lite": (18, -20),
    }
    for model, runtime_row in runtime.items():
        x_value = float(generation[model]["strict_generation_score"])
        y_value = float(runtime_row["strict_runtime_score"])
        x = left + round((right - left) * x_value / 100)
        y = bottom - round((bottom - top) * y_value / 100)
        color = family_color(model)
        draw.ellipse((x - 12, y - 12, x + 12, y + 12), fill=color, outline="white", width=3)
        dx, dy = offsets.get(model, (16, -20))
        draw.text((x + dx, y + dy), f"{label(model)}  {x_value:.1f}, {y_value:.1f}", font=font(18, bold=True), fill="#26323c")
    draw.text((580, 1020), "Strict generation score", font=font(23, bold=True), fill="#34414c")
    draw.text((22, 510), "Strict", font=font(19, bold=True), fill="#34414c")
    draw.text((18, 537), "runtime", font=font(19, bold=True), fill="#34414c")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT / "strict_generation_runtime_profile.png")


def main() -> None:
    comparison()
    generation_heatmap()
    runtime_heatmap()
    strict_profile()
    for path in sorted(OUTPUT.glob("*.png")):
        print(path)


if __name__ == "__main__":
    main()
