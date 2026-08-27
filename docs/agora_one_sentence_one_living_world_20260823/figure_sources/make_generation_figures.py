#!/usr/bin/env python3
"""Reproduce the architecture, world-gallery, and generation-result figures.

All inputs are frozen under ``input_snapshot`` so this script does not depend on
an Agora checkout or generated runtime state outside the paper package.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


INK = "#17202A"
MUTED = "#5D6D7E"
PAPER = "#FBFCFC"
TEAL = "#168A8A"
GOLD = "#D4A72C"
RED = "#C44E52"
BLUE = "#3D6FB4"
GREEN = "#3C8D5A"
SOURCE_DIR = Path(__file__).resolve().parent
INPUT_ROOT = SOURCE_DIR / "input_snapshot"
DEFAULT_OUTPUT = SOURCE_DIR.parent / "reproduced_figures"
WORLD_CASES = (
    ("A", "Clockwork Rain\nConservatory", "creator_20260706_053251_1ad0b086_r001"),
    ("B", "Aurora Court of\nMigrating Cities", "creator_20260724_203817_f86ae13e_r001"),
    ("C", "Mycelium\nPatent Bazaar", "creator_20260724_211037_1c17ca96_r001"),
    ("D", "Sunken Satellite\nMonastery", "creator_20260724_224121_43ca9360_r001"),
    ("E", "Tidal Embassy of\nLost Languages", "creator_20260724_215709_f5f54ceb_r001"),
)
WORLD_FIGURE_AGENTS = {
    "creator_20260706_053251_1ad0b086_r001": (
        "clockwork_rain_conservatory_main_01",
        "Wa Sanniang",
    ),
    "creator_20260724_203817_f86ae13e_r001": (
        "aurora_court_of_migrating_cities_main_01",
        "Shen Tieyan",
    ),
    "creator_20260724_211037_1c17ca96_r001": (
        "mycelium_patent_bazaar_main_01",
        "Shen Tiebi",
    ),
    "creator_20260724_224121_43ca9360_r001": (
        "sunken_satellite_monastery_main_01",
        "Lu Ji",
    ),
    "creator_20260724_215709_f5f54ceb_r001": (
        "tidal_embassy_of_lost_languages_main_01",
        "Shen Mo",
    ),
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _wilson(successes: int, trials: int) -> tuple[float, float]:
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
    return max(0.0, center - margin), min(1.0, center + margin)


def _box(
    ax: plt.Axes,
    xy: tuple[float, float],
    width: float,
    height: float,
    title: str,
    detail: str,
    *,
    color: str,
    title_fontsize: float = 7.4,
    detail_fontsize: float = 6.2,
) -> None:
    x, y = xy
    ax.add_patch(
        Rectangle(
            (x, y),
            width,
            height,
            facecolor=PAPER,
            edgecolor=color,
            linewidth=1.8,
        )
    )
    ax.add_patch(Rectangle((x, y), 0.07, height, facecolor=color, edgecolor="none"))
    ax.text(
        x + 0.16,
        y + height - 0.18,
        title,
        ha="left",
        va="top",
        color=INK,
        fontsize=title_fontsize,
        fontweight="bold",
        linespacing=1.05,
    )
    ax.text(
        x + 0.16,
        y + 0.16,
        detail,
        ha="left",
        va="bottom",
        color=MUTED,
        fontsize=detail_fontsize,
        linespacing=1.25,
    )


def _arrow(
    ax: plt.Axes,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: str = MUTED,
    dashed: bool = False,
    connectionstyle: str = "arc3",
) -> None:
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=10,
            linewidth=1.2,
            color=color,
            linestyle="--" if dashed else "-",
            connectionstyle=connectionstyle,
        )
    )


def architecture_figure(output_root: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.15, 3.65), dpi=220)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6.2)
    ax.axis("off")
    ax.text(
        0.15,
        5.88,
        "AGORA",
        fontsize=16,
        fontweight="bold",
        color=INK,
        va="top",
    )
    ax.text(
        0.15,
        5.48,
        "One Sentence, One Living World",
        fontsize=10,
        fontweight="bold",
        color=MUTED,
        va="top",
    )

    _box(
        ax,
        (0.15, 2.55),
        1.55,
        1.55,
        "Premise",
        "Archive licenses\ngravity\nas property.",
        color=GOLD,
        detail_fontsize=5.8,
    )
    _box(
        ax,
        (2.05, 3.65),
        2.25,
        1.05,
        "Semantic structure",
        "rooms | roles | items\nrelations | hooks",
        color=BLUE,
    )
    _box(
        ax,
        (2.05, 2.25),
        2.25,
        1.05,
        "Visual direction",
        "canon | wardrobe\ncomponents | anchors",
        color=RED,
    )
    _box(
        ax,
        (2.05, 0.85),
        2.25,
        1.05,
        "Evolving world",
        "inventory | property\nknowledge | actions",
        color=GREEN,
    )
    _box(
        ax,
        (4.75, 2.25),
        1.95,
        1.7,
        "World representation",
        "entities + relations\nspace + social state\nvisual identity",
        color=TEAL,
        detail_fontsize=5.8,
    )
    _box(
        ax,
        (7.15, 3.62),
        2.1,
        1.08,
        "FLUX media",
        "sprites + props\nprocedural floors",
        color=RED,
        detail_fontsize=5.9,
    )
    _box(
        ax,
        (7.15, 2.18),
        2.1,
        1.08,
        "World assembly",
        "cross-domain consistency\ncoverage | persistence",
        color=BLUE,
        detail_fontsize=5.8,
    )
    _box(
        ax,
        (7.15, 0.74),
        2.1,
        1.08,
        "Visual evaluation",
        "character consistency\nmap readability | playability",
        color=GOLD,
    )
    _box(
        ax,
        (9.55, 2.25),
        2.3,
        1.7,
        "Living world",
        "movement | dialogue\ntrade | creation\nmemory | relationships",
        color=GREEN,
        title_fontsize=6.6,
        detail_fontsize=5.9,
    )

    _arrow(ax, (1.70, 3.32), (2.02, 4.17))
    _arrow(ax, (1.70, 3.32), (2.02, 2.77))
    _arrow(ax, (1.70, 3.32), (2.02, 1.37))
    _arrow(ax, (4.30, 4.17), (4.72, 3.50))
    _arrow(ax, (4.30, 2.77), (4.72, 3.10))
    _arrow(ax, (4.30, 1.37), (4.72, 2.65))
    _arrow(ax, (6.70, 3.38), (7.12, 4.17))
    _arrow(ax, (6.70, 3.10), (7.12, 2.72))
    _arrow(ax, (8.20, 3.62), (8.20, 3.28))
    _arrow(ax, (8.20, 2.18), (8.20, 1.84))
    _arrow(ax, (9.25, 1.28), (10.05, 2.22))
    _arrow(ax, (9.25, 2.72), (9.52, 3.05))
    _arrow(
        ax,
        (7.12, 1.05),
        (4.30, 1.05),
        color=RED,
        dashed=True,
        connectionstyle="arc3,rad=-0.18",
    )
    ax.text(
        5.35,
        0.28,
        "local refinement updates one room, object, or character while preserving the world",
        fontsize=7.2,
        color=RED,
        ha="center",
    )
    output_root.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_root / "generation_overview.pdf", bbox_inches="tight")
    fig.savefig(output_root / "generation_overview.png", bbox_inches="tight")
    plt.close(fig)


def results_figure(root: Path, output_root: Path) -> None:
    evidence = _read_json(
        root
        / "docs/benchmark_20260724/paper_evidence_summary_20260729.json"
    )

    fig, axes = plt.subplots(2, 2, figsize=(7.15, 5.15), dpi=220)
    fig.patch.set_facecolor("white")
    fig.subplots_adjust(wspace=0.46, hspace=0.46)
    axes = axes.ravel()

    ax = axes[0]
    world_rows = evidence["paired_worlds"]
    outcome_columns = [
        ("specialist_first_pass_success", "Comp.\nfirst", TEAL),
        ("monolithic_first_pass_success", "1-pass\nfirst", GOLD),
        ("specialist_eventual_success", "Comp.\nfinal", TEAL),
        ("monolithic_eventual_success", "1-pass\nfinal", GOLD),
    ]
    short_names = {
        "Archive of Borrowed Gravity": "Archive Gravity",
        "Cartographer Lung Exchange": "Cartographer Lung",
        "Intertidal Embassy for Extinct Rivers": "Intertidal Embassy",
        "Museum of Future Debts": "Future Debts",
        "Night Market of Unfinished Weather": "Night Market",
        "Aurora Court of Migrating Cities": "Aurora Court",
        "Clockwork Rain Conservatory": "Clockwork Rain",
        "Mycelium Patent Bazaar": "Mycelium Bazaar",
        "Sunken Satellite Monastery": "Sunken Satellite",
        "Tidal Embassy of Lost Languages": "Tidal Embassy",
    }
    for row_index, row in enumerate(world_rows):
        for column_index, (key, _, color) in enumerate(outcome_columns):
            passed = bool(row[key])
            ax.add_patch(
                Rectangle(
                    (column_index - 0.39, row_index - 0.37),
                    0.78,
                    0.74,
                    facecolor=color if passed else "#F4F5F6",
                    edgecolor=color if passed else RED,
                    linewidth=1.0,
                )
            )
            ax.text(
                column_index,
                row_index,
                "OK" if passed else "X",
                ha="center",
                va="center",
                fontsize=5.8,
                fontweight="bold",
                color="white" if passed else RED,
            )
    ax.axhline(4.5, color="#AAB2B8", linewidth=0.8)
    ax.text(3.55, 2.0, "primary", rotation=90, fontsize=5.8, color=MUTED, va="center")
    ax.text(3.55, 7.0, "held-out", rotation=90, fontsize=5.8, color=MUTED, va="center")
    ax.set_xlim(-0.48, 3.78)
    ax.set_ylim(len(world_rows) - 0.45, -0.55)
    ax.set_xticks(
        range(len(outcome_columns)),
        [label for _, label, _ in outcome_columns],
        fontsize=6.2,
    )
    ax.xaxis.tick_top()
    ax.set_yticks(
        range(len(world_rows)),
        [short_names.get(row["world_name"], row["world_name"]) for row in world_rows],
        fontsize=5.5,
    )
    ax.set_title("A. Paired world outcomes", loc="left", fontsize=8.4, fontweight="bold")
    ax.text(
        0.5,
        -0.12,
        "Primary worlds use the majority outcome across three matched repetitions",
        transform=ax.transAxes,
        ha="center",
        fontsize=5.8,
        color=MUTED,
    )

    ax = axes[1]
    split_markers = {"primary": "o", "heldout": "s"}
    method_colors = {"specialist": TEAL, "monolithic": GOLD}
    split_labels = {"primary": "Primary", "heldout": "Held-out"}
    short_method_labels = {"specialist": "comp.", "monolithic": "1-pass"}
    for split, rows in evidence["cost_by_split"].items():
        points: list[tuple[float, float]] = []
        for row in rows:
            treatment = row["treatment"]
            tokens = float(row["mean_total_tokens_per_trial"]) / 1000.0
            rate = 100.0 * float(row["eventual_successes"]) / float(row["trials"])
            median_seconds = float(row["median_elapsed_seconds"])
            points.append((tokens, rate))
            ax.scatter(
                tokens,
                rate,
                s=35.0 + median_seconds * 0.55,
                marker=split_markers[split],
                color=method_colors[treatment],
                edgecolor="white",
                linewidth=0.8,
                zorder=3,
            )
            offset = (2.0, 2.2) if treatment == "specialist" else (2.0, -6.5)
            ax.annotate(
                f"{split_labels[split]} {short_method_labels[treatment]}  {median_seconds:.0f}s",
                (tokens, rate),
                xytext=offset,
                textcoords="offset points",
                fontsize=5.9,
                color=INK,
            )
        ax.plot(
            [point[0] for point in points],
            [point[1] for point in points],
            color="#B8C0C5",
            linewidth=1.0,
            zorder=1,
        )
    ax.set_xlim(15, 86)
    ax.set_ylim(50, 106)
    ax.set_xticks([20, 40, 60, 80])
    ax.set_yticks([60, 80, 100], ["60", "80", "100%"])
    ax.set_xlabel("mean tokens per trial (thousands)", fontsize=6.4)
    ax.set_ylabel("complete worlds", fontsize=6.4)
    ax.set_title("B. Reliability vs. cost frontier", loc="left", fontsize=8.4, fontweight="bold")
    ax.grid(alpha=0.18)

    ax = axes[2]
    quality = evidence["quality_combined_10_worlds"]
    quality_worlds = evidence["quality_worlds"]
    metric_rows = [
        ("wardrobe_canon_term_coverage", "Wardrobe canon"),
        ("merchant_inventory_pass_rate", "Merchant inventory"),
        ("premise_items_recall", "Premise items"),
        ("room_visual_canon_adherence", "Room visual canon"),
        ("role_unique_rate", "Role uniqueness"),
        ("premise_agents_recall", "Premise agents"),
    ]
    jitter = [-0.18, -0.14, -0.10, -0.06, -0.02, 0.02, 0.06, 0.10, 0.14, 0.18]
    for row_index, (metric, _) in enumerate(metric_rows):
        deltas = [
            100.0
            * (
                float(row["specialist"].get(metric) or 0.0)
                - float(row["monolithic"].get(metric) or 0.0)
            )
            for row in quality_worlds
        ]
        ax.scatter(
            deltas,
            [row_index + value for value in jitter[: len(deltas)]],
            s=10,
            color="#AAB2B8",
            alpha=0.72,
            linewidth=0,
            zorder=2,
        )
        mean_delta = 100.0 * (
            float(quality[metric]["decomposed_mean"])
            - float(quality[metric]["monolithic_mean"])
        )
        ax.scatter(
            mean_delta,
            row_index,
            s=35,
            marker="D",
            color=TEAL if mean_delta >= 0 else GOLD,
            edgecolor="white",
            linewidth=0.6,
            zorder=3,
        )
    ax.axvline(0, color=INK, linewidth=0.8)
    ax.set_xlim(-82, 60)
    ax.set_ylim(len(metric_rows) - 0.5, -0.5)
    ax.set_yticks(
        range(len(metric_rows)),
        [label for _, label in metric_rows],
        fontsize=5.8,
    )
    ax.set_xticks([-75, -50, -25, 0, 25, 50])
    ax.set_xlabel("compositional minus single-pass (percentage points)", fontsize=5.9)
    ax.set_title("C. Per-world quality deltas", loc="left", fontsize=8.4, fontweight="bold")
    ax.grid(axis="x", alpha=0.18)

    ax = axes[3]
    repair_worlds = evidence["localized_repair_worlds"]
    ratio_keys = ["call_ratio", "token_ratio", "provider_time_ratio"]
    ratio_labels = ["Model\ncalls", "Tokens", "Model\ntime"]
    positions = list(range(3))
    for row in repair_worlds:
        values = [100.0 * float(row[key]) for key in ratio_keys]
        ax.plot(
            positions,
            values,
            color="#B8C0C5",
            linewidth=0.8,
            alpha=0.7,
            zorder=1,
        )
        ax.scatter(
            positions,
            values,
            s=14,
            color=BLUE,
            alpha=0.78,
            edgecolor="white",
            linewidth=0.4,
            zorder=2,
        )
    means = [
        100.0
        * sum(float(row[key]) for row in repair_worlds)
        / len(repair_worlds)
        for key in ratio_keys
    ]
    ax.scatter(
        positions,
        means,
        s=52,
        marker="D",
        color=RED,
        edgecolor="white",
        linewidth=0.7,
        zorder=3,
        label="Mean",
    )
    for position, value in zip(positions, means):
        ax.text(position + 0.08, value - 4.0, f"{value:.0f}%", fontsize=5.8, color=RED)
    ax.axhline(100, color=INK, linewidth=0.8, linestyle="--")
    ax.set_xlim(-0.35, 2.35)
    ax.set_ylim(35, 133)
    ax.set_xticks(positions, ratio_labels, fontsize=6.2)
    ax.set_yticks([50, 75, 100, 125], ["50", "75", "100", "125%"])
    ax.set_ylabel("localized refinement (% of reference)", fontsize=6.2)
    ax.set_title("D. Five localized refinement traces", loc="left", fontsize=8.4, fontweight="bold")
    ax.grid(axis="y", alpha=0.18)
    ax.legend(frameon=False, fontsize=5.8, loc="upper left")

    for ax in axes:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#B8C0C5")
        ax.spines["bottom"].set_color("#B8C0C5")
        ax.tick_params(length=2, color="#8D979D")

    output_root.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_root / "world_quality_results.pdf", bbox_inches="tight")
    fig.savefig(output_root / "world_quality_results.png", bbox_inches="tight")
    plt.close(fig)


def world_strip_figure(root: Path, output_root: Path) -> None:
    fig = plt.figure(figsize=(7.15, 3.02), dpi=220)
    fig.patch.set_facecolor("white")
    grid = fig.add_gridspec(
        2,
        5,
        left=0.01,
        right=0.99,
        top=0.94,
        bottom=0.035,
        height_ratios=(1.55, 0.88),
        hspace=0.20,
        wspace=0.10,
    )
    for column, (letter, name, revision) in enumerate(WORLD_CASES):
        accent = TEAL if letter in {"A", "C", "D"} else RED
        ax = fig.add_subplot(grid[0, column])
        map_path = (
            root
            / "frontend"
            / "assets"
            / "generated"
            / "world_asset_sets"
            / revision
            / "world_map_source.png"
        )
        ax.imshow(plt.imread(map_path))
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_linewidth(1.2)
            spine.set_color(accent)
        ax.set_title(
            f"{letter}. {name}",
            loc="left",
            fontsize=6.4,
            fontweight="bold",
            color=INK,
            pad=4,
            linespacing=1.05,
        )
        agent_id, display_name = WORLD_FIGURE_AGENTS[revision]
        agent_root = (
            root
            / "frontend"
            / "assets"
            / "generated"
            / agent_id
            / revision
        )
        character_sheet = plt.imread(agent_root / "raw_character_128.png")
        frame_height, frame_width = (
            character_sheet.shape[0] // 4,
            character_sheet.shape[1] // 4,
        )
        character_frame = character_sheet[:frame_height, :frame_width]

        agent_grid = grid[1, column].subgridspec(
            1,
            2,
            width_ratios=(2.15, 1.0),
            wspace=0.03,
        )
        character_ax = fig.add_subplot(agent_grid[0, 0])
        character_ax.imshow(character_frame, interpolation="nearest")
        character_ax.set_facecolor("#F3F5F6")
        character_ax.set_xticks([])
        character_ax.set_yticks([])
        for spine in character_ax.spines.values():
            spine.set_linewidth(0.8)
            spine.set_color("#CDD3D7")
        character_ax.set_title(
            display_name,
            loc="left",
            fontsize=6.0,
            fontweight="bold",
            color=INK,
            pad=2,
        )

        atlas_ax = fig.add_subplot(agent_grid[0, 1])
        atlas_ax.imshow(
            plt.imread(agent_root / "character_atlas.png"),
            interpolation="nearest",
        )
        atlas_ax.set_facecolor(INK)
        atlas_ax.set_xticks([])
        atlas_ax.set_yticks([])
        for spine in atlas_ax.spines.values():
            spine.set_linewidth(0.8)
            spine.set_color(accent)
        atlas_ax.set_title(
            "atlas",
            fontsize=5.6,
            color=MUTED,
            pad=2,
        )
    output_root.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_root / "generated_worlds.pdf", bbox_inches="tight")
    fig.savefig(output_root / "generated_worlds.png", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=INPUT_ROOT,
        help="Frozen partial Agora tree containing the figure inputs.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory for regenerated PDF and PNG figures.",
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output_root = args.output_root if args.output_root.is_absolute() else root / args.output_root
    architecture_figure(output_root)
    world_strip_figure(root, output_root)
    results_figure(root, output_root)
    print(output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
