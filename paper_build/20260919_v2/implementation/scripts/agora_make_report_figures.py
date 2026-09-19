#!/usr/bin/env python3
"""Generate figures for the Agora 2.0 benchmark report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "figures_20260725"
QUALITY_PATH = ROOT / "docs" / "benchmark_20260724" / "quality_ablation_summary.json"
RUNTIME_PATH = ROOT / "docs" / "benchmark_20260724" / "runtime_evaluation_summary.json"
MESSAGE_PATH = ROOT / "docs" / "benchmark_20260724" / "headless_message_latency_summary.json"
MONOLITHIC_PATH = ROOT / "docs" / "benchmark_20260724" / "monolithic_baseline" / "monolithic_baseline_summary.json"

COLORS = {
    "ink": "#1d2433",
    "muted": "#617086",
    "grid": "#d6dee8",
    "surface": "#f7f9fc",
    "teal": "#146c72",
    "rust": "#9b4f1c",
    "blue": "#314f9f",
    "green": "#24744f",
    "red": "#a33a3a",
    "gold": "#c49a2c",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(fig: plt.Figure, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_DIR / name, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _style_axes(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(COLORS["grid"])
    ax.spines["bottom"].set_color(COLORS["grid"])
    ax.tick_params(colors=COLORS["muted"])
    ax.yaxis.label.set_color(COLORS["muted"])
    ax.xaxis.label.set_color(COLORS["muted"])
    ax.title.set_color(COLORS["ink"])


def make_pipeline_figure() -> None:
    fig, ax = plt.subplots(figsize=(14.4, 5.2))
    ax.set_axis_off()
    ax.set_xlim(0, 14.4)
    ax.set_ylim(0, 5.0)

    nodes = [
        ("Theme\nPrompt", 0.35, 3.05, 1.2, 0.82, COLORS["gold"]),
        ("Decomposed\nLLM Nodes", 1.95, 3.05, 1.7, 0.82, COLORS["teal"]),
        ("Typed\nBuilder\nSpec", 4.05, 3.05, 1.45, 0.82, COLORS["blue"]),
        ("Strict Gates\ninventory / compiler", 5.9, 3.05, 1.9, 0.82, COLORS["red"]),
        ("FLUX Art\nmap + sprites", 8.2, 3.05, 1.55, 0.82, COLORS["rust"]),
        ("SQLite\nPackage", 10.15, 3.05, 1.45, 0.82, COLORS["green"]),
        ("Pixel Launch\nValidation", 12.0, 3.05, 1.65, 0.82, COLORS["teal"]),
    ]
    for label, x, y, w, h, color in nodes:
        box = FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.04,rounding_size=0.08",
            linewidth=1.4,
            edgecolor=color,
            facecolor="#ffffff",
        )
        ax.add_patch(box)
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", color=COLORS["ink"], fontsize=9.8, weight="bold")
    for index in range(len(nodes) - 1):
        _, x, y, w, h, _ = nodes[index]
        _, nx, ny, _nw, _nh, _ = nodes[index + 1]
        arrow = FancyArrowPatch(
            (x + w + 0.08, y + h / 2),
            (nx - 0.08, ny + h / 2),
            arrowstyle="-|>",
            mutation_scale=12,
            linewidth=1.3,
            color=COLORS["muted"],
        )
        ax.add_patch(arrow)

    lower_nodes = [
        ("Wardrobe Policy\n96 units", 2.2, 1.25, 1.6, 0.72, COLORS["teal"]),
        ("Floor QA\n16 rejects", 4.25, 1.25, 1.45, 0.72, COLORS["rust"]),
        ("Publish Gates\nPixel Read + startup", 6.05, 1.25, 1.9, 0.72, COLORS["green"]),
        ("Live Runtime\nDB authority", 8.35, 1.25, 1.6, 0.72, COLORS["blue"]),
        ("User Study\nsurvey + logs", 10.35, 1.25, 1.45, 0.72, COLORS["gold"]),
    ]
    for label, x, y, w, h, color in lower_nodes:
        box = FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.035,rounding_size=0.08",
            linewidth=1.1,
            edgecolor=color,
            facecolor="#f9fbfd",
        )
        ax.add_patch(box)
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", color=COLORS["ink"], fontsize=9.5)

    ax.text(0.35, 4.45, "Agora 2.0 generative world compiler", fontsize=18, weight="bold", color=COLORS["ink"])
    ax.text(
        0.35,
        4.13,
        "LLM authoring is split into typed nodes; deterministic gates turn generated content into executable multiplayer packages.",
        fontsize=10.5,
        color=COLORS["muted"],
    )
    _save(fig, "agora_pipeline_architecture.png")


def make_strict_baseline_figure(quality: dict[str, Any]) -> None:
    strict = quality["strict_inventory_subset"]["summary"]
    baseline = quality["fallback_allowed_baseline"]["summary"]
    labels = ["Generated\nitem rate", "Fallback\nitem rate", "Quality\nproxy"]
    strict_values = [
        strict["generated_inventory_item_rate"],
        strict["fallback_inventory_item_rate"],
        strict["mean_quality_proxy"],
    ]
    baseline_values = [
        baseline["generated_inventory_item_rate"],
        baseline["fallback_inventory_item_rate"],
        baseline["mean_quality_proxy"],
    ]
    x = np.arange(len(labels))
    width = 0.34
    fig, ax = plt.subplots(figsize=(7.8, 4.5))
    ax.bar(x - width / 2, strict_values, width, label="Current strict pipeline", color=COLORS["teal"])
    ax.bar(x + width / 2, baseline_values, width, label="Fallback-allowed baseline", color=COLORS["rust"])
    ax.set_ylim(-0.05, 1.05)
    ax.set_ylabel("Rate / proxy score")
    ax.set_title("Strict inventory hardfail removes fallback artifacts")
    ax.set_xticks(x, labels)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=2)
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.7, alpha=0.7)
    _style_axes(ax)
    for bars in ax.containers:
        ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=9, color=COLORS["ink"])
    _save(fig, "strict_vs_fallback_baseline.png")


def make_monolithic_baseline_figure(quality: dict[str, Any], monolithic: dict[str, Any]) -> None:
    strict = quality["strict_inventory_subset"]["summary"]
    mono = monolithic["summary"]
    world_count = max(1, int(mono.get("world_count", 0) or 0))
    labels = ["JSON\ngenerated", "Compiler\nvalid", "Inventory\nuseful", "Quality\nproxy"]
    strict_values = [
        1.0,
        1.0,
        strict["inventory_usefulness_proxy_mean"],
        strict["mean_quality_proxy"],
    ]
    mono_values = [
        float(mono.get("generation_ok", 0)) / world_count,
        float(mono.get("compile_ok", 0)) / world_count,
        float(mono.get("mean_inventory_usefulness_proxy", 0.0)),
        float(mono.get("mean_quality_proxy", 0.0)),
    ]
    x = np.arange(len(labels))
    width = 0.34
    fig, ax = plt.subplots(figsize=(7.8, 4.5))
    ax.bar(x - width / 2, strict_values, width, label="Decomposed strict pipeline", color=COLORS["teal"])
    ax.bar(x + width / 2, mono_values, width, label="Fresh monolithic one-shot", color=COLORS["red"])
    ax.set_ylim(-0.05, 1.05)
    ax.set_ylabel("Rate / proxy score")
    ax.set_title("One-shot monolithic generation fails strict executable contracts")
    ax.set_xticks(x, labels)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=2)
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.7, alpha=0.7)
    _style_axes(ax)
    for bars in ax.containers:
        ax.bar_label(bars, fmt="%.2f", padding=3, fontsize=9, color=COLORS["ink"])
    _save(fig, "monolithic_baseline_validity.png")


def make_runtime_figure(runtime: dict[str, Any], message: dict[str, Any]) -> None:
    summary = runtime["summary"]
    msg = message["summary"]
    labels = [
        "REST live-state p95",
        "WS movement p95",
        "Message persist p95",
        "Provider latency p95",
        "Visible reply p95",
    ]
    values = [
        summary["rest_live_state_p95_mean_ms"],
        summary["ws_move_delta_p95_mean_ms"],
        msg["message_persist_ms"]["p95"],
        msg["provider_latency_ms"]["p95"],
        msg["agent_reply_ms"]["p95"],
    ]
    colors = [COLORS["green"], COLORS["green"], COLORS["gold"], COLORS["blue"], COLORS["rust"]]
    fig, ax = plt.subplots(figsize=(8.4, 4.7))
    bars = ax.barh(labels, values, color=colors)
    ax.set_xscale("log")
    ax.set_xlabel("Latency in ms, log scale")
    ax.set_title("Hot-path runtime and real AI reply latency live on different scales")
    ax.grid(axis="x", color=COLORS["grid"], linewidth=0.7, alpha=0.7)
    _style_axes(ax)
    ax.invert_yaxis()
    for bar, value in zip(bars, values):
        ax.text(value * 1.08, bar.get_y() + bar.get_height() / 2, f"{value:.0f} ms", va="center", fontsize=9.5, color=COLORS["ink"])
    _save(fig, "runtime_latency_overview.png")


def make_message_latency_figure(message: dict[str, Any]) -> None:
    runs = message["runs"]
    labels = [row["world_name"].replace(" of ", "\nof ").replace(" ", "\n", 1) for row in runs]
    reply = [row["agent_reply_ms"] for row in runs]
    provider = [row["provider_latency_ms"] for row in runs]
    persist = [row["message_persist_ms"] for row in runs]
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(9.8, 4.8))
    ax.bar(x, reply, color=COLORS["teal"], label="Visible agent reply")
    ax.plot(x, provider, color=COLORS["rust"], marker="o", linewidth=2.4, label="AI Studio provider latency")
    ax.plot(x, persist, color=COLORS["gold"], marker="s", linewidth=2.0, label="Message persisted")
    ax.set_ylabel("Milliseconds")
    ax.set_title("Message-only headless browser latency across strict worlds")
    ax.set_xticks(x, labels, fontsize=8.5)
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.7, alpha=0.7)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3)
    _style_axes(ax)
    for index, value in enumerate(reply):
        ax.text(index, value + 70, f"{value}", ha="center", fontsize=9, color=COLORS["ink"])
    _save(fig, "message_latency_per_world.png")


def main() -> int:
    quality = _read_json(QUALITY_PATH)
    runtime = _read_json(RUNTIME_PATH)
    message = _read_json(MESSAGE_PATH)
    monolithic = _read_json(MONOLITHIC_PATH) if MONOLITHIC_PATH.is_file() else {"summary": {}}
    make_pipeline_figure()
    make_strict_baseline_figure(quality)
    make_monolithic_baseline_figure(quality, monolithic)
    make_runtime_figure(runtime, message)
    make_message_latency_figure(message)
    print(json.dumps({"out_dir": str(OUT_DIR), "figures": sorted(path.name for path in OUT_DIR.glob("*.png"))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
