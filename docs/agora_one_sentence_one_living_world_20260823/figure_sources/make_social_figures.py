#!/usr/bin/env python3
"""Reproduce social-process diagrams and evidence figures for the paper.

All metrics and raster inputs are frozen under ``input_snapshot``.  The output
names match the filenames referenced by the bundled LaTeX source.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


SOURCE_DIR = Path(__file__).resolve().parent
ROOT = SOURCE_DIR / "input_snapshot"
DATA = ROOT / "docs" / "world_interaction_experiment_20260803"
OUT = SOURCE_DIR.parent / "reproduced_figures"
OUT.mkdir(parents=True, exist_ok=True)

OUTPUT_NAMES = {
    "multiworld_interaction_dashboard": "multiworld_interactions",
    "agent_coordinator_state_loop": "situated_action_cycle",
    "clockwork_developing_episode": "clockwork_social_episode",
    "tidal_embassy_experiment_design": "memory_intervention_design",
    "tidal_real_artifact_gallery": "tidal_embassy_visual_elements",
    "tidal_real_visual_repair": "localized_visual_refinement",
    "tidal_real_firefox_runtime": "embodied_character_interaction",
}

COLORS = {
    "teal": "#167D8D",
    "gold": "#D89B22",
    "coral": "#C9574D",
    "green": "#3D8B5B",
    "ink": "#26323D",
    "gray": "#81909A",
    "pale": "#E9EEF0",
}


def load(name: str):
    with (DATA / name).open() as handle:
        return json.load(handle)


def finish(fig, name: str):
    publication_name = OUTPUT_NAMES.get(name, name)
    fig.savefig(OUT / f"{publication_name}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{publication_name}.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def multiworld_dashboard():
    runs = load("multiworld_metrics.json")["runs"]
    labels = ["Aurora", "Clockwork", "Mycelium", "Sunken", "Tidal"]
    x = np.arange(len(runs))
    fig, axes = plt.subplots(1, 3, figsize=(12.2, 3.25))

    compiled = np.array([r["world_action_events"] for r in runs])
    proposed = np.array([r["open_proposal_events"] for r in runs])
    other = np.array([r["events"] for r in runs]) - compiled - proposed
    axes[0].bar(x, other, color=COLORS["gray"], label="general action")
    axes[0].bar(x, compiled, bottom=other, color=COLORS["teal"], label="world-specific")
    axes[0].bar(x, proposed, bottom=other + compiled, color=COLORS["coral"], label="open proposal")
    axes[0].set_ylabel("observed events")
    axes[0].legend(frameon=False, fontsize=7, ncol=1)

    width = 0.34
    axes[1].bar(x - width / 2, [r["unique_dyads"] for r in runs], width,
                color=COLORS["teal"], label="unique dyads")
    axes[1].bar(x + width / 2, [r["human_interaction_events"] for r in runs], width,
                color=COLORS["gold"], label="AI-to-human")
    axes[1].set_ylabel("interaction count")
    axes[1].legend(frameon=False, fontsize=7)

    dims = ["trust", "affection", "influence_fear"]
    bottoms = np.zeros(len(runs))
    for dim, color, label in zip(dims, [COLORS["green"], COLORS["gold"], COLORS["coral"]],
                                 ["trust", "affection", "influence/fear"]):
        vals = np.array([r["relationship_delta_totals"][dim] for r in runs])
        axes[2].bar(x, vals, bottom=bottoms, color=color, label=label)
        bottoms += vals
    axes[2].set_ylabel("sum of directed deltas")
    axes[2].legend(frameon=False, fontsize=7)

    for ax, title in zip(axes, ["A. Action pathways", "B. Social reach", "C. State consequences"]):
        ax.set_title(title, loc="left", fontweight="bold", fontsize=10)
        ax.set_xticks(x, labels, rotation=28, ha="right")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color="#DDE3E6", linewidth=0.6)
        ax.set_axisbelow(True)
    fig.tight_layout(w_pad=2.2)
    finish(fig, "multiworld_interaction_dashboard")


def pilot_dynamics():
    runs = load("pilot_metrics.json")["runs"]
    names = ["Guild", "Black market", "Storm cruise"]
    colors = [COLORS["teal"], COLORS["coral"], COLORS["gold"]]
    fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.25))
    for run, name, color in zip(runs, names, colors):
        dynamics = run["round_dynamics"]
        rounds = [d["round"] for d in dynamics]
        axes[0].plot(rounds, [d["cumulative_unique_dyads"] for d in dynamics],
                     color=color, linewidth=2.2, label=name)
        axes[1].plot(rounds, [d["largest_component"] for d in dynamics],
                     color=color, linewidth=2.2, label=name)
    axes[0].set_title("A. New social ties accumulate", loc="left", fontweight="bold")
    axes[0].set_ylabel("cumulative unique dyads")
    axes[1].set_title("B. Local clusters stabilize early", loc="left", fontweight="bold")
    axes[1].set_ylabel("agents in largest component")
    for ax in axes:
        ax.set_xlabel("round")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(color="#DDE3E6", linewidth=0.6)
        ax.legend(frameon=False, fontsize=8)
    fig.tight_layout(w_pad=2.6)
    finish(fig, "pilot_social_dynamics")


def box(ax, x, y, w, h, title, body, color):
    patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012,rounding_size=0.015",
                           facecolor="white", edgecolor=color, linewidth=1.8)
    ax.add_patch(patch)
    ax.text(x + 0.018, y + h - 0.035, title, fontsize=9.3, fontweight="bold", va="top")
    ax.text(x + 0.018, y + h - 0.105, body, fontsize=7.5, va="top", color=COLORS["ink"], linespacing=1.25)
    return patch


def coordinator_loop():
    fig, ax = plt.subplots(figsize=(11.5, 3.2))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    nodes = [
        (0.02, "1. Observe", "room + nearby actors\ninventory + memories\nrules + live events", COLORS["teal"]),
        (0.22, "2. Form intention", "select an established action\nor propose a new\ntarget-specific action", COLORS["gold"]),
        (0.42, "3. Coordinate", "consider locality, ownership,\nconsent, consequences,\nand world rules", COLORS["coral"]),
        (0.62, "4. Change world", "inventory, object,\nrelationship, location,\nor status consequence", COLORS["green"]),
        (0.82, "5. Remember", "record result and failure;\nupdate episodic memory\nand next-round context", COLORS["teal"]),
    ]
    for x, title, body, color in nodes:
        box(ax, x, 0.34, 0.16, 0.45, title, body, color)
    for x in [0.18, 0.38, 0.58, 0.78]:
        ax.add_patch(FancyArrowPatch((x, 0.565), (x + 0.035, 0.565), arrowstyle="-|>",
                                     mutation_scale=12, color=COLORS["ink"], linewidth=1.3))
    ax.add_patch(FancyArrowPatch((0.90, 0.31), (0.10, 0.31), connectionstyle="arc3,rad=-0.19",
                                 arrowstyle="-|>", mutation_scale=12, color=COLORS["gray"], linewidth=1.3))
    ax.text(0.50, 0.06, "the next decision observes the consequences of the previous action",
            ha="center", fontsize=8.5, color=COLORS["ink"])
    finish(fig, "agent_coordinator_state_loop")


def clockwork_episode():
    fig, ax = plt.subplots(figsize=(11.4, 3.45))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    stages = [
        (0.02, "World event", "Weather-sheet press jams;\nproduction halts.", COLORS["gray"]),
        (0.21, "Round 1", "Marius confronts Valerius\nabout the press jam.", COLORS["coral"]),
        (0.40, "Parallel inquiry", "Seraphina questions the\nfolio's authenticity.", COLORS["gold"]),
        (0.59, "Round 2", "Sabotage is suspected;\nValerius probes Seraphina.", COLORS["coral"]),
        (0.78, "Persistent result", "Trust: -21 total\nInfluence/fear: +21\n7 novel proposals", COLORS["teal"]),
    ]
    for x, title, body, color in stages:
        box(ax, x, 0.38, 0.17, 0.40, title, body, color)
    for x in [0.19, 0.38, 0.57, 0.76]:
        ax.add_patch(FancyArrowPatch((x, 0.58), (x + 0.016, 0.58), arrowstyle="-|>",
                                     mutation_scale=11, color=COLORS["ink"], linewidth=1.4))
    ax.text(0.5, 0.18, "The agents introduce new utterances and social consequences while the press event remains shared.",
            ha="center", fontsize=8.3, color=COLORS["ink"])
    finish(fig, "clockwork_developing_episode")


def experiment_design():
    fig, ax = plt.subplots(figsize=(11.3, 3.35))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    box(ax, 0.02, 0.35, 0.17, 0.42, "Seeded fact", "At round 0, three lower-\narchive agents privately learn\nthat a flood threatens the treaty.", COLORS["gold"])
    box(ax, 0.27, 0.58, 0.22, 0.30, "Full memory", "episodic memory + task threads\n+ relationships + world state", COLORS["teal"])
    box(ax, 0.27, 0.16, 0.22, 0.30, "Memory ablation", "same profiles, model, seed, and\nworld; remove prior social episodes", COLORS["coral"])
    box(ax, 0.58, 0.35, 0.17, 0.42, "32 rounds", "agents must transmit the fact,\ncross rooms, recruit roles, find\nobjects, and move the treaty.", COLORS["green"])
    box(ax, 0.82, 0.35, 0.16, 0.42, "Measured outcomes", "diffusion reach; time to first\ncross-room transfer; rescue success;\nnetwork and norm violations", COLORS["teal"])
    for start, end in [((0.19, .56), (.27, .73)), ((.19, .56), (.27, .31)), ((.49, .73), (.58, .56)), ((.49, .31), (.58, .56)), ((.75, .56), (.82, .56))]:
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=11,
                                     color=COLORS["ink"], linewidth=1.3))
    finish(fig, "tidal_embassy_experiment_design")


def tidal_artifact_gallery():
    asset_root = ROOT / "frontend/assets/generated/world_asset_sets/creator_20260724_215709_f5f54ceb_r001"
    char_root = ROOT / "frontend/assets/generated"
    panels = [
        (asset_root / "world_map_source.png", "A. Composed world map"),
        (asset_root / "floors/floor_room_01_the_phoneme_exchange.png", "B. Phoneme Exchange"),
        (asset_root / "floors/floor_room_06_the_mnemonic_garden.png", "C. Mnemonic Garden"),
        (asset_root / "floors/floor_room_08_the_ballast_hold.png", "D. Ballast Hold"),
        (char_root / "tidal_embassy_of_lost_languages_main_01/creator_20260805_character_v8_final/character_atlas.png", "E. Shen Mo"),
        (char_root / "tidal_embassy_of_lost_languages_main_02/creator_20260805_character_v8_final/character_atlas.png", "F. Inspector Shen Jian"),
        (char_root / "tidal_embassy_of_lost_languages_main_03/creator_20260805_character_v8_final/character_atlas.png", "G. Shen Wusheng"),
        (asset_root / "component_generation/local_icons/prop_parchment_scrolls.png", "H. Linguistic scrolls"),
    ]
    fig = plt.figure(figsize=(12, 5.4))
    grid = fig.add_gridspec(2, 6, height_ratios=[1.7, 1], wspace=0.18, hspace=0.28)
    slots = [grid[0, 0:3], grid[0, 3], grid[0, 4], grid[0, 5],
             grid[1, 0:2], grid[1, 2:4], grid[1, 4], grid[1, 5]]
    for (path, title), slot in zip(panels, slots):
        ax = fig.add_subplot(slot)
        ax.imshow(plt.imread(path))
        ax.set_title(title, loc="left", fontsize=7.5, fontweight="bold")
        ax.axis("off")
    finish(fig, "tidal_real_artifact_gallery")


def tidal_repair_trace():
    root = ROOT / "frontend/assets/generated/world_asset_sets/creator_20260724_215709_f5f54ceb_r001/floors"
    panels = [
        (root / "floor_room_05_the_diplomat_s_lounge.rejected_attempt_1.png",
         "Attempt 1: rejected", "poster-card background\nblank margin ratio: 0.56"),
        (root / "floor_room_05_the_diplomat_s_lounge.rejected_attempt_2.png",
         "Attempt 2: rejected", "blank margin remains\nmax blank row: 0.73"),
        (root / "floor_room_05_the_diplomat_s_lounge.png",
         "Attempt 3: accepted", "edge-to-edge playable floor\nvisual identity preserved"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(11.2, 3.7))
    for ax, (path, title, note) in zip(axes, panels):
        ax.imshow(plt.imread(path))
        ax.set_title(title, loc="left", fontsize=10, fontweight="bold")
        ax.text(0.02, -0.06, note, transform=ax.transAxes, va="top", fontsize=8,
                color=COLORS["ink"])
        ax.axis("off")
    fig.tight_layout(w_pad=1.5)
    finish(fig, "tidal_real_visual_repair")


def tidal_runtime_capture():
    screenshot = ROOT / "runtime_captures" / "interaction.png"
    context_screenshot = ROOT / "runtime_captures" / "world_context.png"
    atlas = ROOT / "frontend/assets/generated/tidal_embassy_of_lost_languages_main_01/creator_20260805_character_v8_final/character_atlas.png"
    if not screenshot.exists() or not context_screenshot.exists() or not atlas.exists():
        return
    image_data = plt.imread(screenshot)
    context_data = plt.imread(context_screenshot)
    atlas_data = plt.imread(atlas)
    fig = plt.figure(figsize=(12.0, 5.8))
    grid = fig.add_gridspec(2, 7, width_ratios=[1, 1, 1, 1, 1, 0.9, 0.9],
                            height_ratios=[1.18, 1], wspace=0.16, hspace=0.28)

    interaction = fig.add_subplot(grid[:, :5])
    interaction.imshow(image_data[155:620, 450:680], interpolation="nearest")
    interaction.set_title("A. Latest character at player interaction scale", loc="left",
                          fontsize=10, fontweight="bold")
    interaction.axis("off")

    overview = fig.add_subplot(grid[0, 5:])
    overview.imshow(context_data)
    overview.set_title("B. World and neighboring agents", loc="left", fontsize=9, fontweight="bold")
    overview.axis("off")

    detail = fig.add_subplot(grid[1, 5:])
    detail.imshow(atlas_data, interpolation="nearest")
    detail.set_title("C. Directional identity", loc="left", fontsize=9, fontweight="bold")
    detail.axis("off")

    fig.suptitle("Character identity from visual generation to embodied interaction",
                 x=0.06, ha="left", fontsize=11, fontweight="bold")
    fig.subplots_adjust(top=0.88)
    finish(fig, "tidal_real_firefox_runtime")


def main() -> int:
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUT,
        help="Directory for regenerated PDF and PNG figures.",
    )
    args = parser.parse_args()
    OUT = args.output_root.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5, "axes.titleweight": "bold"})
    multiworld_dashboard()
    pilot_dynamics()
    coordinator_loop()
    clockwork_episode()
    experiment_design()
    tidal_artifact_gallery()
    tidal_repair_trace()
    tidal_runtime_capture()
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
