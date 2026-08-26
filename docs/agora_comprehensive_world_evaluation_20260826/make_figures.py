#!/usr/bin/env python3
"""Generate publication-ready vector figures for the Agora evaluation report."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch


ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / "data" / "comprehensive_aggregate.json").read_text())
DUAL = json.loads((ROOT / "data" / "dual_judge_aggregate.json").read_text())
FIG = ROOT / "figures"
FIG.mkdir(parents=True, exist_ok=True)

INK = "#172333"
MUTED = "#5D6978"
GRID = "#DCE3E8"
TEAL = "#168A8A"
CORAL = "#E76F51"
GOLD = "#D99A2B"
BLUE = "#427AA1"
PALE_TEAL = "#DCEEEE"
PALE_CORAL = "#F8E5DF"
PALE_GOLD = "#F7EDDA"
BG = "#F7F9FA"

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.labelcolor": INK,
        "axes.edgecolor": GRID,
        "axes.titlecolor": INK,
        "xtick.color": MUTED,
        "ytick.color": INK,
        "text.color": INK,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    }
)

SHORT = {
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "gemini-3.7-flash": "Gemini 3.7 Flash",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
    "gpt-5.6-terra": "GPT-5.6 Terra",
    "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
    "gpt-5.6-luna": "GPT-5.6 Luna",
}


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(FIG / f"{name}.pdf", bbox_inches="tight", pad_inches=0.08)
    fig.savefig(FIG / f"{name}.png", dpi=220, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def clean_axis(ax: plt.Axes, *, xgrid: bool = True) -> None:
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="y", length=0)
    if xgrid:
        ax.grid(axis="x", color=GRID, lw=0.7, alpha=0.8)
        ax.set_axisbelow(True)


def framework() -> None:
    fig, ax = plt.subplots(figsize=(11.2, 3.1))
    ax.set_xlim(0, 11.2)
    ax.set_ylim(0, 3.1)
    ax.axis("off")
    cards = [
        (0.15, TEAL, PALE_TEAL, "40%", "Blind World Quality", "Ideas, society, space,\nand open interaction"),
        (3.95, CORAL, PALE_CORAL, "35%", "Objective Generation", "Typed completeness, causal\nstructure, and affordance"),
        (7.75, GOLD, PALE_GOLD, "25%", "Objective Runtime", "Execution, community traces,\nand human impact"),
    ]
    for index, (x, color, pale, weight, title, detail) in enumerate(cards):
        patch = FancyBboxPatch(
            (x, 0.35),
            3.25,
            2.35,
            boxstyle="round,pad=0.02,rounding_size=0.12",
            linewidth=1.2,
            edgecolor=color,
            facecolor=pale,
        )
        ax.add_patch(patch)
        ax.text(x + 0.28, 2.28, weight, fontsize=20, weight="bold", color=color, va="center")
        ax.text(x + 0.28, 1.65, title, fontsize=12.2, weight="bold", color=INK, va="center")
        ax.text(x + 0.28, 0.92, detail, fontsize=9.4, color=MUTED, va="center", linespacing=1.4)
        if index < 2:
            ax.add_patch(
                FancyArrowPatch(
                    (x + 3.34, 1.52),
                    (x + 3.72, 1.52),
                    arrowstyle="-|>",
                    mutation_scale=15,
                    lw=1.5,
                    color=INK,
                )
            )
    ax.text(
        5.6,
        2.98,
        "One sentence  →  executable world  →  lived social process",
        ha="center",
        va="top",
        fontsize=13.2,
        weight="bold",
        color=INK,
    )
    save(fig, "evaluation_framework")


def comprehensive_scores() -> None:
    rows = sorted(DATA["models"], key=lambda row: row["comprehensive_score"])
    names = [SHORT[row["model"]] for row in rows]
    scores = [row["comprehensive_score"] for row in rows]
    colors = [
        TEAL if score >= 85 else BLUE if score >= 80 else CORAL if score >= 70 else GOLD if score >= 60 else MUTED
        for score in scores
    ]
    fig, ax = plt.subplots(figsize=(8.5, 4.7))
    y = np.arange(len(rows))
    bars = ax.barh(y, scores, height=0.58, color=colors, zorder=3)
    ax.set_yticks(y, names)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Comprehensive score")
    ax.set_title("End-to-end world quality and performance", loc="left", pad=12)
    clean_axis(ax)
    for bar, score, row in zip(bars, scores, rows):
        ax.text(
            max(2, score - 1.6),
            bar.get_y() + bar.get_height() / 2,
            f"{score:.2f}  {row['band']}",
            ha="right" if score >= 13 else "left",
            va="center",
            color="white" if score >= 13 else INK,
            fontsize=8.5,
            weight="bold",
        )
    save(fig, "comprehensive_scores")


def partition_profile() -> None:
    rows = sorted(DATA["models"], key=lambda row: row["comprehensive_score"], reverse=True)
    names = [SHORT[row["model"]] for row in rows]
    quality = [row["blind_world_quality"] for row in rows]
    generation = [row["objective_generation"] for row in rows]
    runtime = [row["objective_runtime"] for row in rows]
    x = np.arange(len(rows))
    width = 0.24
    fig, ax = plt.subplots(figsize=(10.8, 4.6))
    ax.bar(x - width, quality, width, label="Blind quality", color=TEAL)
    ax.bar(x, generation, width, label="Objective generation", color=CORAL)
    ax.bar(x + width, runtime, width, label="Objective runtime", color=GOLD)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Score")
    ax.set_xticks(x, names, rotation=24, ha="right")
    ax.set_title("Complementary capability profiles", loc="left", pad=12)
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(frameon=False, ncol=3, loc="upper right")
    save(fig, "partition_profile")


def quality_heatmap() -> None:
    rows = sorted(DATA["models"], key=lambda row: row["comprehensive_score"], reverse=True)
    axes = [
        "premise_causality",
        "society_personhood",
        "space_materiality",
        "interaction_open_endedness",
        "holistic_coherence",
    ]
    labels = ["Premise &\ncausality", "Society &\npersonhood", "Space &\nmateriality", "Open\ninteraction", "Holistic\ncoherence"]
    matrix = np.array([[row["blind_quality_axes"][axis] for axis in axes] for row in rows])
    fig, ax = plt.subplots(figsize=(8.6, 5.0))
    image = ax.imshow(matrix, cmap="YlGnBu", vmin=0, vmax=100, aspect="auto")
    ax.set_yticks(np.arange(len(rows)), [SHORT[row["model"]] for row in rows])
    ax.set_xticks(np.arange(len(labels)), labels)
    ax.tick_params(length=0)
    ax.set_title("Blind dual-judge world quality", loc="left", pad=12)
    for row_index in range(matrix.shape[0]):
        for column_index in range(matrix.shape[1]):
            value = matrix[row_index, column_index]
            ax.text(
                column_index,
                row_index,
                f"{value:.0f}",
                ha="center",
                va="center",
                fontsize=8.3,
                weight="bold",
                color="white" if value >= 66 else INK,
            )
    for spine in ax.spines.values():
        spine.set_visible(False)
    cbar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.025)
    cbar.outline.set_visible(False)
    cbar.ax.tick_params(labelsize=8, colors=MUTED, length=0)
    save(fig, "quality_heatmap")


def agreement() -> None:
    rows = DUAL["diagnostics"]["inter_rater_agreement_by_category"]
    order = [
        "premise_causality",
        "society_personhood",
        "space_materiality",
        "interaction_open_endedness",
        "holistic_coherence",
    ]
    labels = ["Premise & causality", "Society & personhood", "Space & materiality", "Open interaction", "Holistic coherence"]
    alpha = [rows[key]["ordinal_krippendorff_alpha"] for key in order]
    kappa = [rows[key]["quadratic_weighted_kappa"] for key in order]
    y = np.arange(len(order))
    fig, ax = plt.subplots(figsize=(8.7, 3.8))
    height = 0.31
    ax.barh(y + height / 2, alpha, height, color=TEAL, label="Ordinal alpha")
    ax.barh(y - height / 2, kappa, height, color=BLUE, label="Weighted kappa")
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xlabel("Agreement")
    ax.set_title("Inter-judge consistency by dimension", loc="left", pad=12)
    clean_axis(ax)
    ax.legend(frameon=False, ncol=2, loc="lower right")
    for row_index, (left, right) in enumerate(zip(alpha, kappa)):
        ax.text(left + 0.012, row_index + height / 2, f"{left:.3f}", va="center", fontsize=8, color=TEAL)
        ax.text(right + 0.012, row_index - height / 2, f"{right:.3f}", va="center", fontsize=8, color=BLUE)
    save(fig, "judge_agreement")


def generation_components() -> None:
    rows = sorted(DATA["models"], key=lambda row: row["objective_generation"], reverse=True)
    names = [SHORT[row["model"]] for row in rows]
    contract = [row["generation_components"].get("contract_compliance", 0) for row in rows]
    structure = [row["generation_components"].get("strict_objective_quality", 0) for row in rows]
    first_pass = [100 * row["first_pass_worlds"] / 3 for row in rows]
    x = np.arange(len(rows))
    width = 0.24
    fig, ax = plt.subplots(figsize=(10.8, 4.5))
    ax.bar(x - width, contract, width, color=CORAL, label="Contract compliance")
    ax.bar(x, structure, width, color=TEAL, label="Objective world structure")
    ax.bar(x + width, first_pass, width, color=BLUE, label="First-pass completion")
    ax.set_ylim(0, 105)
    ax.set_ylabel("Score / completion rate")
    ax.set_xticks(x, names, rotation=24, ha="right")
    ax.set_title("Objective generation realization", loc="left", pad=12)
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(frameon=False, ncol=3, loc="upper right")
    save(fig, "generation_components")


def runtime_components() -> None:
    rows = sorted(DATA["models"], key=lambda row: row["objective_runtime"], reverse=True)
    names = [SHORT[row["model"]] for row in rows]
    execution = [row["runtime_components"].get("execution_compliance", 0) for row in rows]
    trace = [row["runtime_components"].get("strict_trace_quality", 0) for row in rows]
    stress = [row["runtime_components"].get("cross_world_stress", 0) for row in rows]
    x = np.arange(len(rows))
    width = 0.24
    fig, ax = plt.subplots(figsize=(10.8, 4.5))
    ax.bar(x - width, execution, width, color=GOLD, label="Execution compliance")
    ax.bar(x, trace, width, color=TEAL, label="Trace quality")
    ax.bar(x + width, stress, width, color=BLUE, label="Cross-world stress")
    ax.set_ylim(0, 105)
    ax.set_ylabel("Score")
    ax.set_xticks(x, names, rotation=24, ha="right")
    ax.set_title("Objective runtime performance", loc="left", pad=12)
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(frameon=False, ncol=3, loc="upper right")
    save(fig, "runtime_components")


def main() -> None:
    framework()
    comprehensive_scores()
    partition_profile()
    quality_heatmap()
    agreement()
    generation_components()
    runtime_components()
    print(f"Generated 7 vector figures in {FIG}")


if __name__ == "__main__":
    main()
