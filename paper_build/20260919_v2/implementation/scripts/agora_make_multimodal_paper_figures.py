#!/usr/bin/env python3
"""Create paper figures for the Agora multimodal world compiler draft."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "docs" / "benchmark_20260724" / "multimodal_audit_20260727.json"
OUT_DIR = ROOT / "docs" / "figures_20260727"

COLORS = {
    "ink": "#172033",
    "muted": "#5b667a",
    "line": "#cbd3df",
    "surface": "#f5f7fb",
    "blue": "#2f5ca8",
    "teal": "#13736d",
    "green": "#2f7d4f",
    "amber": "#b36b16",
    "red": "#a33f45",
    "purple": "#6750a4",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(fig: plt.Figure, filename: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / filename, dpi=240, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _box(
    ax: plt.Axes,
    xy: tuple[float, float],
    size: tuple[float, float],
    label: str,
    *,
    edge: str,
    face: str = "white",
    fontsize: float = 9.2,
    dashed: bool = False,
) -> None:
    x, y = xy
    width, height = size
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.025,rounding_size=0.06",
        linewidth=1.4,
        linestyle="--" if dashed else "-",
        edgecolor=edge,
        facecolor=face,
    )
    ax.add_patch(patch)
    ax.text(
        x + width / 2,
        y + height / 2,
        label,
        ha="center",
        va="center",
        color=COLORS["ink"],
        fontsize=fontsize,
        weight="semibold",
    )


def _arrow(
    ax: plt.Axes,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: str = COLORS["muted"],
    dashed: bool = False,
) -> None:
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=12,
            linewidth=1.2,
            linestyle="--" if dashed else "-",
            color=color,
        )
    )


def make_compiler_architecture() -> None:
    fig, ax = plt.subplots(figsize=(14.5, 7.0))
    ax.set_axis_off()
    ax.set_xlim(0, 14.5)
    ax.set_ylim(0, 7.0)

    ax.text(0.3, 6.55, "Cross-modal world compilation", fontsize=19, weight="bold", color=COLORS["ink"])
    ax.text(
        0.3,
        6.22,
        "One typed world IR binds semantic entities to generated media, package provenance, and live state.",
        fontsize=10.5,
        color=COLORS["muted"],
    )

    _box(ax, (0.35, 3.0), (1.35, 0.78), "One-sentence\nworld brief", edge=COLORS["blue"], face="#eef4ff")
    _box(
        ax,
        (2.05, 2.55),
        (2.15, 1.68),
        "Typed World IR\n\nrooms + topology\nagents + roles\nitems + knowledge\nvisual policies",
        edge=COLORS["purple"],
        face="#f4f0ff",
        fontsize=9.5,
    )
    _arrow(ax, (1.72, 3.39), (2.02, 3.39))

    semantic_y = 4.82
    visual_y = 3.05
    runtime_y = 1.20
    ax.text(4.6, 5.75, "SEMANTIC", fontsize=9, weight="bold", color=COLORS["blue"])
    ax.text(4.6, 3.98, "VISUAL", fontsize=9, weight="bold", color=COLORS["teal"])
    ax.text(4.6, 1.98, "EXECUTION", fontsize=9, weight="bold", color=COLORS["green"])

    _box(ax, (4.6, semantic_y), (1.65, 0.72), "Planner +\nspecialist nodes", edge=COLORS["blue"])
    _box(ax, (6.65, semantic_y), (1.55, 0.72), "Schema +\ncompiler checks", edge=COLORS["blue"])
    _box(ax, (8.6, semantic_y), (1.65, 0.72), "Scenario graph +\nagent state", edge=COLORS["blue"])
    _arrow(ax, (6.27, semantic_y + 0.36), (6.62, semantic_y + 0.36))
    _arrow(ax, (8.22, semantic_y + 0.36), (8.57, semantic_y + 0.36))

    _box(ax, (4.6, visual_y), (1.65, 0.72), "Room scene\nconditions", edge=COLORS["teal"])
    _box(ax, (4.6, visual_y - 0.93), (1.65, 0.72), "Wardrobe +\nidentity policy", edge=COLORS["teal"])
    _box(ax, (6.65, visual_y), (1.55, 0.72), "FLUX room\nplates", edge=COLORS["teal"])
    _box(ax, (6.65, visual_y - 0.93), (1.55, 0.72), "FLUX character\nsheets", edge=COLORS["teal"])
    _box(ax, (8.6, visual_y - 0.46), (1.65, 0.9), "Spatial compositor\n+ Phaser atlases", edge=COLORS["teal"], face="#effaf8")
    _arrow(ax, (6.27, visual_y + 0.36), (6.62, visual_y + 0.36))
    _arrow(ax, (6.27, visual_y - 0.57), (6.62, visual_y - 0.57))
    _arrow(ax, (8.22, visual_y + 0.36), (8.57, visual_y + 0.12))
    _arrow(ax, (8.22, visual_y - 0.57), (8.57, visual_y - 0.12))

    _box(ax, (4.6, runtime_y), (1.65, 0.72), "SQLite world\npackage", edge=COLORS["green"])
    _box(ax, (6.65, runtime_y), (1.55, 0.72), "Package-backed\nPixel launch", edge=COLORS["green"])
    _box(ax, (8.6, runtime_y), (1.65, 0.72), "Persistent multi-user\nruntime", edge=COLORS["green"])
    _arrow(ax, (6.27, runtime_y + 0.36), (6.62, runtime_y + 0.36))
    _arrow(ax, (8.22, runtime_y + 0.36), (8.57, runtime_y + 0.36))

    _arrow(ax, (4.22, 3.55), (4.57, semantic_y + 0.35), color=COLORS["purple"])
    _arrow(ax, (4.22, 3.35), (4.57, visual_y - 0.05), color=COLORS["purple"])
    _arrow(ax, (4.22, 3.05), (4.57, runtime_y + 0.35), color=COLORS["purple"])

    _box(
        ax,
        (10.75, 2.85),
        (1.55, 1.05),
        "Render-and-\nverify gate\n\nasset + screenshot",
        edge=COLORS["amber"],
        face="#fff8ec",
    )
    _arrow(ax, (10.27, 3.05), (10.72, 3.25), color=COLORS["amber"])
    _arrow(ax, (10.27, 1.56), (10.72, 3.05), color=COLORS["amber"])
    _box(
        ax,
        (12.65, 2.85),
        (1.45, 1.05),
        "Accept,\nregenerate,\nor reject",
        edge=COLORS["red"],
        face="#fff1f2",
    )
    _arrow(ax, (12.32, 3.37), (12.62, 3.37), color=COLORS["red"])
    _arrow(ax, (13.4, 2.82), (13.4, 1.97), color=COLORS["red"], dashed=True)
    ax.text(
        11.1,
        0.55,
        "Current gap: visual feedback is a publication gate,\nnot yet a localized repair controller.",
        ha="left",
        va="center",
        fontsize=9,
        color=COLORS["red"],
    )
    _save(fig, "multimodal_compiler_architecture.png")


def make_world_gallery(audit: dict[str, Any]) -> None:
    worlds = audit["worlds"][1:5]
    fig, axes = plt.subplots(1, 4, figsize=(14.5, 4.25))
    styles = {
        "Aurora Court of Migrating Cities": "Biomechanical arctic court",
        "Mycelium Patent Bazaar": "Biopunk patent market",
        "Tidal Embassy of Lost Languages": "Sino-futurist floating embassy",
        "Sunken Satellite Monastery": "Deep-sea gothic signal order",
    }
    for ax, world in zip(axes.flat, worlds):
        image = Image.open(world["map_path"]).convert("RGB")
        ax.imshow(image)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_edgecolor(COLORS["line"])
            spine.set_linewidth(1.1)
        display_name = {
            "Aurora Court of Migrating Cities": "Aurora Court",
            "Mycelium Patent Bazaar": "Mycelium Bazaar",
            "Tidal Embassy of Lost Languages": "Tidal Embassy",
            "Sunken Satellite Monastery": "Sunken Monastery",
        }.get(world["world_name"], world["world_name"])
        ax.set_title(display_name, loc="left", fontsize=11.2, weight="bold", color=COLORS["ink"], pad=8)
        ax.text(
            0.0,
            -0.055,
            styles.get(world["world_name"], ""),
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=9.2,
            color=COLORS["muted"],
        )
    fig.suptitle(
        "Room-conditioned maps produced from four distinct world premises",
        x=0.07,
        y=0.985,
        ha="left",
        fontsize=15,
        weight="bold",
        color=COLORS["ink"],
    )
    fig.text(
        0.07,
        0.905,
        "Each map stitches eight independently generated FLUX room plates into the authored tile grid.",
        ha="left",
        fontsize=10,
        color=COLORS["muted"],
    )
    fig.subplots_adjust(top=0.76, bottom=0.10, wspace=0.08)
    _save(fig, "multimodal_world_gallery.png")


def _crop(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    return image.crop(box)


def make_visual_audit(audit: dict[str, Any]) -> None:
    world_by_name = {world["world_name"]: world for world in audit["worlds"]}
    sunken = world_by_name["Sunken Satellite Monastery"]
    tidal = world_by_name["Tidal Embassy of Lost Languages"]
    sunken_map = Image.open(sunken["map_path"]).convert("RGB")
    tidal_map = Image.open(tidal["map_path"]).convert("RGB")
    screenshot = Image.open(sunken["screenshot_path"]).convert("RGB")
    raw_sheet = Image.open(
        ROOT
        / "frontend"
        / "assets"
        / "generated"
        / "sunken_satellite_monastery_main_01"
        / "creator_20260724_224121_43ca9360_r001"
        / "raw_character_128.png"
    ).convert("RGB")

    fig, axes = plt.subplots(2, 2, figsize=(12.0, 8.5))
    panels = [
        (
            axes[0, 0],
            _crop(sunken_map, (0, 0, min(430, sunken_map.width), min(380, sunken_map.height))),
            "A. Prompt violation survives QA",
            "Visible room-title text and a clipped plate\nappear in a published map.",
        ),
        (
            axes[0, 1],
            _crop(tidal_map, (0, 0, tidal_map.width, min(760, tidal_map.height))),
            "B. Local quality, global style drift",
            "Individually rich rooms disagree in perspective,\npalette, and architectural language.",
        ),
        (
            axes[1, 0],
            raw_sheet,
            "C. Declared animation collapses",
            "Every four-frame animated row contains one repeated image;\ndirection rows are also mislabelled.",
        ),
        (
            axes[1, 1],
            _crop(screenshot, (130, 150, min(1200, screenshot.width), min(1050, screenshot.height))),
            "D. Render contract and overlay debt",
            "Configured margin, dense grid lines, labels,\nand tiny agents weaken the live scene.",
        ),
    ]
    for ax, image, title, note in panels:
        ax.imshow(image)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_edgecolor(COLORS["line"])
            spine.set_linewidth(1.1)
        ax.set_title(title, loc="left", fontsize=11.2, weight="bold", color=COLORS["ink"], pad=8)
        ax.text(
            0,
            -0.065,
            note,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=8.5,
            color=COLORS["muted"],
            wrap=True,
        )
    fig.suptitle(
        "The multimodal audit distinguishes artifact existence from visual readiness",
        x=0.06,
        y=0.997,
        ha="left",
        fontsize=16,
        weight="bold",
        color=COLORS["ink"],
    )
    fig.subplots_adjust(top=0.925, bottom=0.085, hspace=0.31, wspace=0.09)
    _save(fig, "multimodal_visual_failure_audit.png")


def main() -> int:
    audit = _read_json(AUDIT_PATH)
    make_compiler_architecture()
    make_world_gallery(audit)
    make_visual_audit(audit)
    print(
        json.dumps(
            {
                "out_dir": str(OUT_DIR),
                "figures": sorted(path.name for path in OUT_DIR.glob("*.png")),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
