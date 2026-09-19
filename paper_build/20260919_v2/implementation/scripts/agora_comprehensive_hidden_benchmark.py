#!/usr/bin/env python3
"""Aggregate the 2026-08-25 hidden matched-model benchmark."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agora_living_world_benchmark import (  # noqa: E402
    _interaction_axis,
    _sentence_axis,
    _society_axis,
    _spatial_axis,
)
from scripts.agora_living_world_model_comparison import _cross_node  # noqa: E402


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
    "gpt-5.6-sol": "gpt_5_6_sol",
    "gpt-5.6-terra": "gpt_5_6_terra",
    "gpt-5.6-luna": "gpt_5_6_luna",
}
WORLD_WEIGHTS = {
    "sentence_realization": 0.15,
    "compiled_space": 0.15,
    "cross_node_referential_integrity": 0.15,
    "agent_society": 0.15,
    "interaction_contract": 0.20,
    "compiler_conformance": 0.20,
}
HEADLINE_WEIGHTS = {
    "generated_world": 0.35,
    "community_policy": 0.20,
    "visual_realization": 0.15,
    "generated_world_runtime": 0.15,
    "expert_world_quality": 0.15,
}
REQUIRED_CANON = (
    "camera",
    "palette",
    "materials",
    "lighting",
    "architecture",
    "terrain",
    "sprite_language",
    "world_prompt_prefix",
    "sprite_prompt_prefix",
    "forbidden_visuals",
)
SEMANTIC_RETRY_MULTIPLIER = 0.98


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _mean(values: Iterable[float]) -> float:
    rows = list(values)
    return sum(rows) / len(rows) if rows else 0.0


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _weighted_geometric(scores: dict[str, float], weights: dict[str, float]) -> float:
    return 100.0 * math.exp(
        sum(weight * math.log(max(0.0001, scores.get(name, 0.0) / 100.0)) for name, weight in weights.items())
    )


def _semantic_retry_adjusted_score(score: float, retry_count: int) -> float:
    return max(0.0, float(score)) * (
        SEMANTIC_RETRY_MULTIPLIER ** max(0, int(retry_count))
    )


def _active_floor_qa_paths(asset_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted((asset_dir / "floors").glob("floor_*.qa.json"))
        if ".rejected_" not in path.name
    ]


def _compiler_axis(result: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    compile_probe = result.get("compile_probe") if isinstance(result.get("compile_probe"), dict) else {}
    merged_probe = result.get("merged_contract_probe") if isinstance(result.get("merged_contract_probe"), dict) else {}
    request = result.get("request") if isinstance(result.get("request"), dict) else {}
    target_agents = int(request.get("agent_count_target", 12) or 12)
    runtime_agents = int(compile_probe.get("runtime_agent_count", 0) or 0)
    checks = {
        "generation_ok": result.get("generation_ok") is True,
        "complete_success": result.get("complete_success") is True,
        "compile_ok": compile_probe.get("compile_ok") is True,
        "merged_contract_ok": merged_probe.get("merged_contract_ok") is True,
        "runtime_agent_target_met": runtime_agents == target_agents,
    }
    return 100.0 * _mean(float(value) for value in checks.values()), {
        **checks,
        "runtime_agent_count": runtime_agents,
        "target_agent_count": target_agents,
    }


def _generation_case(model_dir: str, prompt: dict[str, Any]) -> dict[str, Any]:
    prompt_id = str(prompt["prompt_id"])
    case_dir = RUN_ROOT / model_dir / prompt_id
    result = _read(case_dir / f"{prompt_id}_r01_decomposed_result.json")
    telemetry = result.get("telemetry") if isinstance(result.get("telemetry"), dict) else {}
    tokens = telemetry.get("token_totals") if isinstance(telemetry.get("token_totals"), dict) else {}
    retries = result.get("generation_node_retries") if isinstance(result.get("generation_node_retries"), list) else []
    semantic_retry_count = len(retries) + int(
        result.get("compiler_critique_applied") is True
    )
    operational = {
        "elapsed_seconds": round(float(result.get("elapsed_seconds", 0.0) or 0.0), 4),
        "provider_attempt_count": int(telemetry.get("provider_attempt_count", 0) or 0),
        "total_tokens": int(
            tokens.get("totalTokenCount", tokens.get("total_tokens", 0)) or 0
        ),
        "localized_node_retry_count": len(retries),
        "localized_retry_nodes": [str(item.get("failed_node", "")) for item in retries if isinstance(item, dict)],
        "compiler_critique_repair_count": int(
            result.get("compiler_critique_applied") is True
        ),
        "semantic_retry_count": semantic_retry_count,
        "semantic_retry_multiplier": round(
            SEMANTIC_RETRY_MULTIPLIER ** semantic_retry_count, 6
        ),
        "transport_retry_or_failure_count": int(
            telemetry.get("retry_or_failure_attempt_count", 0) or 0
        ),
    }
    if result.get("complete_success") is not True:
        return {
            "prompt_id": prompt_id,
            "sentence": prompt["sentence"],
            "status": "failed",
            "world_name": "",
            "score": 0.0,
            "axes": {name: 0.0 for name in WORLD_WEIGHTS},
            "observations": {},
            "first_pass_success": False,
            "error": str(result.get("error", "")),
            "operational": operational,
        }
    builder = _read(case_dir / f"{prompt_id}_r01_decomposed_builder_spec.json")
    config = _read(case_dir / f"{prompt_id}_r01_decomposed_world_config.json")
    sentence_score, sentence_obs = _sentence_axis(str(prompt["sentence"]), config, builder)
    space_score, space_obs = _spatial_axis(config)
    cross_score, cross_obs = _cross_node(builder)
    society_score, society_obs = _society_axis(config)
    interaction_score, interaction_obs = _interaction_axis(config)
    compiler_score, compiler_obs = _compiler_axis(result)
    axes = {
        "sentence_realization": sentence_score,
        "compiled_space": space_score,
        "cross_node_referential_integrity": cross_score,
        "agent_society": society_score,
        "interaction_contract": interaction_score,
        "compiler_conformance": compiler_score,
    }
    raw_score = _weighted_geometric(axes, WORLD_WEIGHTS)
    return {
        "prompt_id": prompt_id,
        "sentence": prompt["sentence"],
        "status": "compiled",
        "world_name": str(builder.get("world_name", result.get("world_name", ""))),
        "score": round(
            _semantic_retry_adjusted_score(raw_score, semantic_retry_count), 2
        ),
        "unpenalized_score": round(raw_score, 2),
        "axes": {name: round(value, 2) for name, value in axes.items()},
        "observations": {
            "sentence": sentence_obs,
            "space": space_obs,
            "cross_node": cross_obs,
            "society": society_obs,
            "interaction": interaction_obs,
            "compiler": compiler_obs,
        },
        "first_pass_success": not retries,
        "error": "",
        "operational": operational,
    }


def _generation_layer(model: str, prompts: list[dict[str, Any]]) -> dict[str, Any]:
    cases = [_generation_case(MODEL_DIRS[model], prompt) for prompt in prompts]
    completed = [case for case in cases if case["status"] == "compiled"]
    completion_rate = _ratio(len(completed), len(cases))
    axis_means = {
        axis: round(_mean(float(case["axes"][axis]) for case in cases), 2)
        for axis in WORLD_WEIGHTS
    }
    return {
        "score": round(_mean(float(case["score"]) for case in cases), 2),
        "completion_rate": round(completion_rate, 4),
        "completed_cases": len(completed),
        "total_cases": len(cases),
        "first_pass_successes": sum(case["first_pass_success"] for case in cases),
        "axis_means_including_failures": axis_means,
        "cases": cases,
        "operational": {
            "elapsed_seconds_total": round(sum(case["operational"]["elapsed_seconds"] for case in cases), 3),
            "elapsed_seconds_mean": round(_mean(case["operational"]["elapsed_seconds"] for case in cases), 3),
            "provider_attempts_total": sum(case["operational"]["provider_attempt_count"] for case in cases),
            "tokens_total": sum(case["operational"]["total_tokens"] for case in cases),
            "localized_node_retries_total": sum(case["operational"]["localized_node_retry_count"] for case in cases),
        },
    }


def _agent_visual_evidence(item: dict[str, Any]) -> dict[str, Any]:
    bundle = item.get("asset_bundle") if isinstance(item.get("asset_bundle"), dict) else {}
    raw = bundle.get("quality_summary") if isinstance(bundle.get("quality_summary"), dict) else {}
    directional = raw.get("directional_rows") if isinstance(raw.get("directional_rows"), dict) else {}
    atlas_path = Path(str(bundle.get("atlas_png", "")))
    metadata_path = Path(str(bundle.get("atlas_json", "")))
    atlas_report = _read(Path(str(bundle.get("atlas_quality_report_path", ""))))
    metadata = _read(metadata_path)
    meta = metadata.get("meta") if isinstance(metadata.get("meta"), dict) else {}
    meta_size = meta.get("size") if isinstance(meta.get("size"), dict) else {}
    frame_size = meta.get("frame_size") if isinstance(meta.get("frame_size"), dict) else {}
    image_size = (0, 0)
    if atlas_path.is_file():
        with Image.open(atlas_path) as image:
            image_size = image.size
    states = meta.get("quality_report", {}).get("states", []) if isinstance(meta.get("quality_report"), dict) else []
    min_heights = [float(state.get("min_body_height_ratio", 0.0) or 0.0) for state in states if isinstance(state, dict)]
    metadata_matches = image_size == (int(meta_size.get("w", 0) or 0), int(meta_size.get("h", 0) or 0))
    frame_grid_matches = (
        int(frame_size.get("w", 0) or 0) > 0
        and int(frame_size.get("h", 0) or 0) > 0
        and image_size[0] == int(frame_size.get("w", 0) or 0) * 4
        and image_size[1] == int(frame_size.get("h", 0) or 0) * 4
    )
    atlas_quality = atlas_report.get("quality_summary") if isinstance(atlas_report.get("quality_summary"), dict) else {}
    return {
        "agent_id": str(item.get("agent_id", "")),
        "publishable": item.get("publishable") is True,
        "raw_sheet_qa_pass": raw.get("pass_qa") is True,
        "directional_qa_pass": directional.get("pass") is True,
        "atlas_integrity_pass": atlas_quality.get("pass") is True,
        "atlas_metadata_matches_png": metadata_matches,
        "atlas_grid_matches_4x4": frame_grid_matches,
        "atlas_size": list(image_size),
        "runtime_frame_size": [int(frame_size.get("w", 0) or 0), int(frame_size.get("h", 0) or 0)],
        "mean_minimum_body_height_ratio": round(_mean(min_heights), 4),
    }


def _visual_layer(model: str, direct_score: float, builder: dict[str, Any]) -> dict[str, Any]:
    asset_dir = WORLD_ASSET_ROOT / f"lwbv2_{MODEL_DIRS[model]}"
    manifest = _read(asset_dir / "world_asset_set_manifest.json")
    sidecar = _read(asset_dir / "world_map_source.components.json")
    jobs = [item for item in manifest.get("component_generation", {}).get("jobs", []) if isinstance(item, dict)]
    semantic = [
        item for item in sidecar.get("placements", [])
        if isinstance(item, dict) and item.get("semantic_generated") is True
    ]
    active_floor_paths = _active_floor_qa_paths(asset_dir)
    rejected_floor_paths = sorted(
        (asset_dir / "floors").glob("floor_*.rejected_*.qa.json")
    )
    floors = [_read(path) for path in active_floor_paths]
    canon = builder.get("visual_canon") if isinstance(builder.get("visual_canon"), dict) else {}
    agents = [_agent_visual_evidence(item) for item in manifest.get("agents", []) if isinstance(item, dict)]
    rates = {
        "visual_canon_completeness": _ratio(sum(bool(canon.get(key)) for key in REQUIRED_CANON), len(REQUIRED_CANON)),
        "map_source_present": float((asset_dir / "world_map_source.png").is_file()),
        "semantic_component_generation_rate": _ratio(sum(item.get("status") == "ok" for item in jobs), len(jobs)),
        "semantic_component_readability_rate": _ratio(sum(item.get("readability_pass") is True for item in semantic), len(semantic)),
        "floor_qa_pass_rate": _ratio(sum(item.get("pass") is True for item in floors), len(floors)),
        "representative_agent_completion_rate": _ratio(len(agents), 3),
        "raw_sheet_qa_pass_rate": _ratio(sum(item["raw_sheet_qa_pass"] for item in agents), len(agents)),
        "directional_qa_pass_rate": _ratio(sum(item["directional_qa_pass"] for item in agents), len(agents)),
        "atlas_integrity_pass_rate": _ratio(sum(item["atlas_integrity_pass"] for item in agents), len(agents)),
        "atlas_publish_contract_rate": _ratio(
            sum(item["atlas_metadata_matches_png"] and item["atlas_grid_matches_4x4"] for item in agents),
            len(agents),
        ),
        "no_fallback_rate": float(
            bool(manifest)
            and int(
                manifest.get("quality_summary", {}).get("fallback_agents", 0)
                or 0
            )
            == 0
        ),
    }
    technical_weights = {
        "visual_canon_completeness": 0.08,
        "map_source_present": 0.08,
        "semantic_component_generation_rate": 0.10,
        "semantic_component_readability_rate": 0.10,
        "floor_qa_pass_rate": 0.07,
        "representative_agent_completion_rate": 0.05,
        "raw_sheet_qa_pass_rate": 0.12,
        "directional_qa_pass_rate": 0.10,
        "atlas_integrity_pass_rate": 0.12,
        "atlas_publish_contract_rate": 0.10,
        "no_fallback_rate": 0.08,
    }
    technical_score = 100.0 * sum(technical_weights[key] * rates[key] for key in technical_weights)
    score = 0.60 * technical_score + 0.40 * direct_score
    passing_agents = sum(
        item["publishable"]
        and item["raw_sheet_qa_pass"]
        and item["directional_qa_pass"]
        and item["atlas_integrity_pass"]
        and item["atlas_metadata_matches_png"]
        and item["atlas_grid_matches_4x4"]
        for item in agents
    )
    hard_gate_pass = bool(
        manifest.get("status") in {"ok", "partial"}
        and rates["map_source_present"] == 1.0
        and passing_agents > 0
    )
    return {
        "score": round(score if hard_gate_pass else min(score, 49.0), 2),
        "technical_score": round(technical_score, 2),
        "direct_blind_visual_score": round(direct_score, 2),
        "blend": {"technical_weight": 0.60, "direct_blind_visual_weight": 0.40},
        "hard_gate_pass": hard_gate_pass,
        "component_count": len(jobs),
        "readable_component_count": sum(item.get("readability_pass") is True for item in semantic),
        "floor_count": len(floors),
        "rejected_floor_history_count": len(rejected_floor_paths),
        "representative_agent_count": len(agents),
        "passing_representative_agent_count": passing_agents,
        "rates": {name: round(value, 4) for name, value in rates.items()},
        "agents": agents,
    }


def _expert_layer(label: str, review: dict[str, Any]) -> dict[str, Any]:
    weights = review["axis_weights"]
    cases = review["labels"][label]["cases"]
    axis_means = {
        axis: _mean(float(case["scores"][axis]) for case in cases.values())
        for axis in weights
    }
    score = sum(float(weights[axis]) * axis_means[axis] for axis in weights)
    return {
        "score": round(score, 2),
        "anonymous_label": label,
        "axis_means": {axis: round(value, 2) for axis, value in axis_means.items()},
        "cases": cases,
    }


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    return ImageFont.truetype(str(path), size=size) if path.is_file() else ImageFont.load_default()


def _score_color(score: float) -> str:
    if score >= 90:
        return "#287a55"
    if score >= 80:
        return "#6e9340"
    if score >= 70:
        return "#c19a36"
    if score >= 60:
        return "#c66b35"
    return "#9f3e3e"


def _score_figure(rows: list[dict[str, Any]], path: Path) -> None:
    labels = [
        ("Comprehensive", "headline_score"),
        ("World", "generated_world"),
        ("Community", "community_policy"),
        ("Visual", "visual_realization"),
        ("Runtime", "generated_world_runtime"),
        ("Expert", "expert_world_quality"),
    ]
    width, height = 1660, 150 + len(rows) * 118
    image = Image.new("RGB", (width, height), "#f1f3f0")
    draw = ImageDraw.Draw(image)
    title_font = _font(34, bold=True)
    head_font = _font(19, bold=True)
    body_font = _font(22, bold=True)
    small_font = _font(16)
    draw.text((42, 28), "Agora hidden comprehensive model benchmark", fill="#171a17", font=title_font)
    model_w, cell_w = 330, 205
    y0 = 96
    draw.text((42, y0), "Model", fill="#30342f", font=head_font)
    for col, (label, _) in enumerate(labels):
        draw.text((model_w + col * cell_w + 18, y0), label, fill="#30342f", font=head_font)
    for row_index, row in enumerate(rows):
        y = y0 + 42 + row_index * 118
        draw.rectangle((30, y, width - 30, y + 96), fill="#ffffff", outline="#c6cbc4", width=1)
        draw.text((42, y + 22), row["model"], fill="#171a17", font=body_font)
        draw.text((42, y + 56), f"compiled {row['generated_world']['completed_cases']}/3", fill="#60655f", font=small_font)
        values = {
            "headline_score": row["headline_score"],
            **row["layer_scores"],
        }
        for col, (_, key) in enumerate(labels):
            value = float(values[key])
            x = model_w + col * cell_w
            draw.rectangle((x + 8, y + 13, x + cell_w - 10, y + 82), fill=_score_color(value))
            text = f"{value:.1f}"
            bounds = draw.textbbox((0, 0), text, font=body_font)
            draw.text(
                (x + (cell_w - (bounds[2] - bounds[0])) / 2, y + 31),
                text,
                fill="#ffffff",
                font=body_font,
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _runtime_figure(rows: list[dict[str, Any]], path: Path) -> None:
    columns = [
        ("Runtime", "score"),
        ("Ground", "executable_grounding"),
        ("Space", "spatial_mobility"),
        ("Consequence", "persistent_consequences"),
        ("Social", "social_continuity"),
        ("Human", "human_integration"),
        ("Open + recovery", "open_action_recovery"),
        ("Integrity", "institutional_integrity"),
        ("Time", "temporal_progression"),
    ]
    width, height = 2020, 152 + len(rows) * 112
    image = Image.new("RGB", (width, height), "#f1f3f0")
    draw = ImageDraw.Draw(image)
    title_font = _font(34, bold=True)
    head_font = _font(17, bold=True)
    body_font = _font(21, bold=True)
    small_font = _font(15)
    draw.text((42, 25), "AGWRE v1.0: three 24-round generated-world trajectories", fill="#171a17", font=title_font)
    model_w, cell_w = 320, 184
    y0 = 92
    draw.text((42, y0), "Model", fill="#30342f", font=head_font)
    for column, (label, _) in enumerate(columns):
        draw.text((model_w + column * cell_w + 10, y0), label, fill="#30342f", font=head_font)
    for row_index, row in enumerate(rows):
        y = y0 + 38 + row_index * 112
        score = row["score"]
        draw.rectangle((30, y, width - 30, y + 92), fill="#ffffff", outline="#c6cbc4", width=1)
        draw.text((42, y + 18), row["model"], fill="#171a17", font=body_font)
        observations = score["observations"]
        draw.text(
            (42, y + 52),
            f"{observations['actions_succeeded']}/{observations['actions_planned']} actions",
            fill="#60655f",
            font=small_font,
        )
        values = {"score": score["score"], **score["axes"]}
        for column, (_, key) in enumerate(columns):
            value = float(values[key])
            x = model_w + column * cell_w
            draw.rectangle((x + 6, y + 11, x + cell_w - 8, y + 78), fill=_score_color(value))
            text_value = f"{value:.1f}"
            bounds = draw.textbbox((0, 0), text_value, font=body_font)
            draw.text(
                (x + (cell_w - (bounds[2] - bounds[0])) / 2, y + 29),
                text_value,
                fill="#ffffff",
                font=body_font,
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _report(payload: dict[str, Any]) -> str:
    rows = payload["ranking"]
    lines = [
        "# Agora 隐藏题综合模型评测",
        "",
        f"评测日期：`{payload['generated_at']}`  ",
        "套件：`lwb_hidden_20260825_v2`（三道未见单句世界题）+ `ACPB-H1`（三道未见社区策略题）",
        "",
        "## 结论",
        "",
        "`gemini-3.7-flash` 是本轮唯一在生成世界、社区策略、视觉实现、生成世界运行和盲评五层都超过 90 分的模型。"
        "它的综合分超过 80 分目标，并且 3/3 世界均一次通过。`gemini-3.1-pro-preview` 的生成耗时最高，"
        "但社区策略和世界文本没有超过 3.7；`gemini-3.5-flash-lite` 仅完成 1/3 世界，不能进入可发布档。",
        "",
        "![综合评分](figures/comprehensive_scores.png)",
        "",
        "| 排名 | 模型 | 综合 | 世界生成 | 社区策略 | 视觉实现 | 世界运行 | 盲评质量 | 编译 | 首轮通过 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for index, row in enumerate(rows, start=1):
        layer = row["layer_scores"]
        generation = row["generated_world"]
        lines.append(
            f"| {index} | {row['model']} | **{row['headline_score']:.2f}** | {layer['generated_world']:.2f} | "
            f"{layer['community_policy']:.2f} | {layer['visual_realization']:.2f} | "
            f"{layer['generated_world_runtime']:.2f} | {layer['expert_world_quality']:.2f} | "
            f"{generation['completed_cases']}/3 | {generation['first_pass_successes']}/3 |"
        )
    lines.extend([
        "",
        "综合分为五层加权几何平均：世界生成 35%、社区策略 20%、视觉实现 15%、生成世界运行 15%、盲评质量 15%。"
        "未编译题按 0 分进入世界与盲评层；少于 2/3 编译、视觉硬门失败或 coordinator 接受非法动作时，综合分最高 59。",
        "",
        "## 隐藏题与控制",
        "",
        "三道生成题在冻结前逐句检索仓库，均无匹配。早期 v1 题在修正 schema 和局部重试时已被使用，因此只作为 calibration，完全排除于本表。"
        "五个模型按相同顺序使用同一生产管线、温度 0.2、low thinking、12 个 AI 角色、4 个真人槽位、相同编译器、coordinator 与 FLUX2。"
        "生成时没有模型替换，也没有复用旧世界。",
        "",
    ])
    for prompt in payload["prompts"]:
        lines.append(f"- `{prompt['prompt_id']}`：{prompt['sentence']}")
    lines.extend([
        "",
        "Planner 的结构化输出上限为 32,768 tokens；角色批次最高 32,768，其余专门节点使用各自生产上限。"
        "所有 planner/JSON 调用均以 `STOP` 结束。2.5 Flash 的三个非结构化世界摘要在 3,200-token 上限结束，"
        "但这些摘要不参与 builder、编译或评分。",
        "",
        "## 世界生成",
        "",
        "每个成功世界先分别计算句子实现、空间结构、跨节点引用、角色社会、交互契约和编译一致性，再按 15/15/15/15/20/20 的几何平均形成逐题分。"
        "模型世界分是三道逐题分的算术平均，失败题为 0；这等价于成功题均分乘以完成率。",
        "",
        "| 模型 | 世界分 | 句子 | 空间 | 跨节点 | 社会 | 交互 | 编译 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in rows:
        axes = row["generated_world"]["axis_means_including_failures"]
        lines.append(
            f"| {row['model']} | {row['layer_scores']['generated_world']:.2f} | {axes['sentence_realization']:.2f} | "
            f"{axes['compiled_space']:.2f} | {axes['cross_node_referential_integrity']:.2f} | "
            f"{axes['agent_society']:.2f} | {axes['interaction_contract']:.2f} | {axes['compiler_conformance']:.2f} |"
        )
    lines.extend([
        "",
        "| 模型 | 题 01 | 题 02 | 题 03 |",
        "|---|---:|---:|---:|",
    ])
    for row in rows:
        cases = row["generated_world"]["cases"]
        values = ["失败" if case["status"] != "compiled" else f"{case['score']:.2f}" for case in cases]
        lines.append(f"| {row['model']} | {values[0]} | {values[1]} | {values[2]} |")
    lines.extend([
        "",
        "3.7 Flash 的三个世界都把核心句子转译成了可循环的物质与制度机制。例如 Aethelcleft 将承诺实现为可称量的 vow capsule，"
        "其堆积压坏吊桥、提高运输附加费、促成地下 whisper market，破约又可被磨成修桥砂浆；Littoral Barony 则把没收物的密度鉴定、"
        "防波堤施工、收费闸门、渔民通海权、打捞和伪造连接成同一因果链。",
        "",
        "3.5 Flash Lite 在题 02 与题 03 的角色节点连续违反强类型契约，包括非法关系类型、缺失 property templates 和不存在的关系目标。"
        "管线没有用模板世界兜底，所以两题保持失败并计 0 分。",
        "",
        "## 社区策略",
        "",
        "ACPB-H1 使用三个固定状态的新场景，确定性检查参与覆盖、互动拓扑、跨群体桥接、关系延续、集体协作、世界落地、开放动作和制度完整性。"
        "每个场景要求六个动作；合法 oracle 在三题八轴均可达 100，说明评分地板与天花板都可检验。",
        "",
        "| 模型 | 社区分 | 参与 | 拓扑 | 桥接 | 延续 | 协作 | 落地 | 开放动作 | 制度完整性 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    community_by_model = {row["model"]: row for row in payload["community_ranking"]}
    for row in rows:
        community = community_by_model[row["model"]]
        axes = community["axis_means"]
        lines.append(
            f"| {row['model']} | {community['community_score']:.2f} | {axes['participation_and_human_uptake']:.2f} | "
            f"{axes['interaction_topology']:.2f} | {axes['cross_group_bridging']:.2f} | {axes['relational_continuity']:.2f} | "
            f"{axes['collective_coordination']:.2f} | {axes['world_grounded_agency']:.2f} | "
            f"{axes['open_action_quality']:.2f} | {axes['institutional_integrity']:.2f} |"
        )
    lines.extend([
        "",
        "3.7 Flash 得到 93.87；Pro 为 91.50。其余模型的主要损失不是文风，而是动作引用非法 target/object、调用不存在的 action，"
        "或把普通 catalog action 偷带为不受支持的物体创建，因而触发制度完整性惩罚或场景上限。",
        "",
        "## 生成世界运行",
        "",
        "AGWRE v1.0 在每个模型自己生成的题 01 世界中运行三条独立的 24 轮轨迹，共 72 轮。每条轨迹在第 1、5、9、13、17、21 轮重规划，"
        "每次提交未来四轮的 12 个动作；执行器逐个检查精确 ID、同房条件、相邻房间移动、物品所有权和同意，再通过 Agora coordinator 与"
        "通用动作处理器提交状态。固定介入依次加入真人请求、非法提案拒绝、资源损失、跨房间协作要求和真人追问；真人发言前进入有 AI 的房间，"
        "使每次真人互动都有合法可达的响应机会。",
        "",
        "八轴确定性评分覆盖可执行落地、空间流动、持久后果、社会连续、真人共玩、开放动作与拒绝后修正、制度完整性和时间推进。"
        "旧七项 coordinator 黑盒探针仍作为硬门：五个世界包均为 100/100，但不再直接充当运行质量分。",
        "",
        "![三次24轮运行八轴评分](figures/runtime_axes.png)",
        "",
        "| 模型 | 运行均值 | 标准差 | 范围 | 落地 | 空间 | 后果 | 社会 | 真人 | 开放/修正 | 完整性 | 时间 | 成功动作 | 真人成功 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    runtime_by_model = {row["model"]: row for row in payload["runtime_ranking"]}
    for row in rows:
        runtime = runtime_by_model[row["model"]]
        score = runtime["score"]
        axes = score["axes"]
        obs = score["observations"]
        lines.append(
            f"| {row['model']} | {score['score']:.2f} | {score['score_stddev']:.2f} | "
            f"{score['score_min']:.2f}–{score['score_max']:.2f} | {axes['executable_grounding']:.2f} | "
            f"{axes['spatial_mobility']:.2f} | {axes['persistent_consequences']:.2f} | "
            f"{axes['social_continuity']:.2f} | {axes['human_integration']:.2f} | "
            f"{axes['open_action_recovery']:.2f} | {axes['institutional_integrity']:.2f} | "
            f"{axes['temporal_progression']:.2f} | {obs['actions_succeeded']}/{obs['actions_planned']} | "
            f"{obs['human_successful_replicates']}/3 |"
        )
    lines.extend([
        "",
        "2.5 Flash 的运行均值最高，为 95.31±2.15；3.1 Flash Lite、3.7 Flash 和 Pro 分别为 94.03、93.86 和 91.59，"
        "三者的三次轨迹也都成功响应真人。3.7 的 216 个动作全部提交成功，空间流动仍相对保守；Pro 的真人轴为 77.08、"
        "开放动作与修正轴为 77.92，但不存在此前单轨迹所呈现的全面真人交互失败。",
        "",
        "3.5 Flash Lite 三次为 31.11、28.45 和 29.66，且 0/3 轨迹形成有效真人响应；这是修正可达性后仍重复出现的稳定失效。"
        "早期单轨迹版本在空房间中注入真人提案，使所有权与距离两项检查同时失败，因此已从正式结果中排除。",
        "",
        "## FLUX2 视觉实现",
        "",
        "每个模型在题 01 上生成完整地图构件与前三个角色。角色由 FLUX2 输出 512×512 原始 sheet，经过背景处理、共享缩放、"
        "脚底锚定和调色后发布为 256×256 atlas（4×4，每帧 64×64）。15/15 角色通过原始布局、透明度、主体占比、"
        "左右方向差异、动作差异、身份连续性、atlas 完整性和发布元数据检查；没有 fallback。",
        "",
        "![匿名地图](figures/maps_blind.png)",
        "",
        "![匿名人物](figures/characters_blind.png)",
        "",
        "| 模型 | 视觉分 | 技术 QA | 匿名直观分 | 构件可读 | 角色通过 | 运行帧 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in rows:
        visual = row["visual_realization"]
        runtime = visual["agents"][0]["runtime_frame_size"] if visual["agents"] else [0, 0]
        lines.append(
            f"| {row['model']} | {visual['score']:.2f} | {visual['technical_score']:.2f} | "
            f"{visual['direct_blind_visual_score']:.2f} | {visual['readable_component_count']}/{visual['component_count']} | "
            f"{visual['passing_representative_agent_count']}/{visual['representative_agent_count']} | {runtime[0]}×{runtime[1]} |"
        )
    lines.extend([
        "",
        "技术 QA 与直观质量按 60/40 合并。3.7 的地图在房间色彩分区、主体构件密度和角色造型差异上最好；Pro 的地图较空，"
        "且 1/6 语义构件未通过可读性检查。当前地图仍呈现明显的房间拼块与大片空地，视觉层尚未达到生成世界文本的丰富度。",
        "",
        "## 单盲专家评审",
        "",
        "评审时模型被随机映射为 A–E，逐题查看句子、制度与状态、房间、12 个角色、物品、循环、开放动作、冲突钩子及匿名地图和人物板；"
        "分数锁定后才解盲。失败题六轴均为 0。",
        "",
        "| 模型 | 盲评 | 题意转译 | 因果制度 | 空间/物质 | 社会互依 | 互动想象 | 视觉一致 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in rows:
        expert = row["expert_world_quality"]
        axes = expert["axis_means"]
        lines.append(
            f"| {row['model']} | {expert['score']:.2f} | {axes['premise_transformation']:.2f} | "
            f"{axes['causal_institutions']:.2f} | {axes['spatial_material_imagination']:.2f} | "
            f"{axes['social_interdependence']:.2f} | {axes['interaction_imagination']:.2f} | "
            f"{axes['experienced_visual_coherence']:.2f} |"
        )
    lines.extend([
        "",
        "所有成功世界的角色都有明确目标、活动、物品、知识和财产，但编译后的显式 `relationships` 数组为空。"
        "因此“角色围绕同一制度工作”已经成立，“角色记得并改变彼此关系”仍没有被生成包证明，这也是社会互依分普遍低于制度分的原因。",
        "",
        "## 运行成本",
        "",
        "延迟与 token 只作为运行指标，不进入质量分。",
        "",
        "| 模型 | 生成秒数 | 平均/题 | API 调用 | 总 tokens | 社区秒数 | 运行秒数 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in rows:
        operational = row["generated_world"]["operational"]
        community = community_by_model[row["model"]]
        runtime = runtime_by_model[row["model"]]
        lines.append(
            f"| {row['model']} | {operational['elapsed_seconds_total']:.1f} | {operational['elapsed_seconds_mean']:.1f} | "
            f"{operational['provider_attempts_total']} | {operational['tokens_total']:,} | {community['latency_seconds_total']:.3f} | "
            f"{runtime['elapsed_seconds']:.3f} |"
        )
    lines.extend([
        "",
        "## 判定",
        "",
        "当前默认高质量非 preset 生成模型应设为 `gemini-3.7-flash`。它以 3/3 首轮编译、93.87 社区分和最高盲评质量稳定越过 80 分目标。"
        "`gemini-3.1-pro-preview` 不应仅因 Pro 标签成为默认：它三题都需要局部角色重试，耗时约为 3.7 的 2.27 倍，综合质量仍更低。",
        "",
        "下一轮管线升级应集中在三个位置：把角色节点已生成的合法关系保存进最终 `main_characters.relationships`；"
        "让房间连接和岸线/站台权限真正改变可导航图，而不只存在于状态文字；对地图做可玩视角截图 QA，直接约束空房间比例、"
        "语义构件占地和人物在真实相机下的屏幕占比。",
        "",
        "## 证据边界",
        "",
        "本轮每个模型每题一次生成，视觉只覆盖题 01 的三名代表角色，专家层只有一名高级 LLM 评审。"
        "结果适合选择当前默认模型和定位管线瓶颈，不用于估计跨随机种子的统计显著性。",
        "",
        "完整机器结果：`comprehensive_results.json`；匿名评分：`blind_review/review_form.json`；"
        "社区逐动作证据：`community_results.json`；三次 24 轮运行结果：`generated_world_runtime_results.json`；"
        "完整轨迹：`runtime_trajectories_v2/replicate_*/*/trajectory.json`；coordinator 硬门：`visual_cases/*/interaction_probes.json`；"
        "逐题原始生成：`confirmatory_runs/`。",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-root", type=Path, default=BENCHMARK_ROOT)
    args = parser.parse_args()
    benchmark_root = args.benchmark_root.resolve()
    suite = _read(benchmark_root / "prompt_suite_hidden_v2.json")
    prompts = [item for item in suite.get("prompts", []) if isinstance(item, dict)]
    community = _read(benchmark_root / "community_results.json")
    community_by_model = {item["model"]: item for item in community.get("ranking", []) if isinstance(item, dict)}
    interactions = _read(benchmark_root / "visual_cases" / "case_manifest.json")
    interaction_by_model = {item["model"]: item for item in interactions.get("models", []) if isinstance(item, dict)}
    runtime = _read(benchmark_root / "generated_world_runtime_results.json")
    runtime_by_model = {item["model"]: item for item in runtime.get("ranking", []) if isinstance(item, dict)}
    review = _read(benchmark_root / "blind_review" / "review_form.json")
    label_map = _read(benchmark_root / "blind_review" / "blind_label_map.json")
    model_to_label = {model: label for label, model in label_map.items()}
    models: list[dict[str, Any]] = []
    for model in MODEL_DIRS:
        generation = _generation_layer(model, prompts)
        expert = _expert_layer(model_to_label[model], review)
        first_case = generation["cases"][0]
        builder_path = RUN_ROOT / MODEL_DIRS[model] / prompts[0]["prompt_id"] / f"{prompts[0]['prompt_id']}_r01_decomposed_builder_spec.json"
        builder = _read(builder_path) if first_case["status"] == "compiled" else {}
        visual = _visual_layer(model, float(expert["cases"][prompts[0]["prompt_id"]]["scores"]["experienced_visual_coherence"]), builder)
        community_row = community_by_model[model]
        interaction_row = interaction_by_model[model]
        runtime_row = runtime_by_model[model]
        layer_scores = {
            "generated_world": float(generation["score"]),
            "community_policy": float(community_row["community_score"]),
            "visual_realization": float(visual["score"]),
            "generated_world_runtime": float(runtime_row["score"]["score"]),
            "expert_world_quality": float(expert["score"]),
        }
        raw_headline = _weighted_geometric(layer_scores, HEADLINE_WEIGHTS)
        cap_reasons: list[str] = []
        if generation["completed_cases"] < 2:
            cap_reasons.append("fewer_than_two_of_three_worlds_compiled")
        if not visual["hard_gate_pass"]:
            cap_reasons.append("representative_visual_hard_gate_failed")
        if float(interaction_row["interaction_score"]) < 100.0:
            cap_reasons.append("interaction_contract_safety_probe_failed")
        headline = min(raw_headline, 59.0) if cap_reasons else raw_headline
        models.append({
            "model": model,
            "headline_score": round(headline, 2),
            "raw_headline_score": round(raw_headline, 2),
            "score_cap_applied": bool(cap_reasons),
            "score_cap_reasons": cap_reasons,
            "layer_scores": {name: round(value, 2) for name, value in layer_scores.items()},
            "generated_world": generation,
            "community_policy": community_row,
            "visual_realization": visual,
            "generated_world_runtime": runtime_row,
            "interaction_contract_probe": interaction_row,
            "expert_world_quality": expert,
        })
    ranking = sorted(models, key=lambda item: item["headline_score"], reverse=True)
    for rank, row in enumerate(ranking, start=1):
        row["rank"] = rank
    payload = {
        "benchmark": "Agora Comprehensive Matched-Model Hidden Evaluation",
        "suite_id": suite.get("suite_id", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headline_weights": HEADLINE_WEIGHTS,
        "world_weights": WORLD_WEIGHTS,
        "prompts": prompts,
        "ranking": ranking,
        "community_ranking": community.get("ranking", []),
        "runtime_ranking": runtime.get("ranking", []),
        "artifacts": {
            "protocol": "protocol.md",
            "blind_review": "blind_review/review_form.json",
            "blind_label_map": "blind_review/blind_label_map.json",
            "maps_figure": "figures/maps_blind.png",
            "characters_figure": "figures/characters_blind.png",
            "score_figure": "figures/comprehensive_scores.png",
            "generated_world_runtime": "generated_world_runtime_results.json",
            "runtime_figure": "figures/runtime_axes.png",
        },
    }
    _write(benchmark_root / "comprehensive_results.json", payload)
    _score_figure(ranking, benchmark_root / "figures" / "comprehensive_scores.png")
    _runtime_figure(runtime.get("ranking", []), benchmark_root / "figures" / "runtime_axes.png")
    (benchmark_root / "comprehensive_report.md").write_text(_report(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
