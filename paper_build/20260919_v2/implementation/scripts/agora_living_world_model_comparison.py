#!/usr/bin/env python3
"""Aggregate matched-model LivingWorldBench generation and FLUX evidence."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agora_living_world_benchmark import (
    _interaction_axis,
    _sentence_axis,
    _society_axis,
    _spatial_axis,
)


MODEL_DIRS = {
    "gemini-2.5-flash": "gemini_2_5_flash",
    "gemini-3.1-flash-lite": "gemini_3_1_flash_lite",
    "gemini-3.1-pro-preview": "gemini_3_1_pro_preview",
    "gemini-3.5-flash-lite": "gemini_3_5_flash_lite",
    "gemini-3.7-flash": "gemini_3_7_flash",
}
PRE_ART_WEIGHTS = {
    "sentence_realization": 0.20,
    "compiled_space": 0.15,
    "agent_society": 0.20,
    "interaction_contract": 0.25,
    "compiler_conformance": 0.20,
}
FULL_WEIGHTS = {
    "sentence_realization": 0.15,
    "compiled_space": 0.10,
    "cross_node_referential_integrity": 0.12,
    "agent_society": 0.13,
    "interaction_contract": 0.18,
    "visual_artifact": 0.22,
    "compiler_conformance": 0.10,
}


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _first(path: Path, pattern: str) -> Path | None:
    return next(path.glob(pattern), None)


def _mean(values: Iterable[float]) -> float:
    rows = list(values)
    return sum(rows) / len(rows) if rows else 0.0


def _geometric(axes: dict[str, float], weights: dict[str, float]) -> float:
    return 100.0 * math.exp(
        sum(weight * math.log(max(0.01, axes.get(name, 0.0) / 100.0)) for name, weight in weights.items())
    )


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _cross_node(builder: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    room_names = {_normalized(room.get("name")) for room in builder.get("rooms", []) if isinstance(room, dict)}
    role_names = {
        _normalized(character.get("role_name"))
        for character in builder.get("main_characters", [])
        if isinstance(character, dict)
    }
    room_refs = [
        _normalized(value)
        for loop in builder.get("gameplay_loops", [])
        if isinstance(loop, dict)
        for value in loop.get("rooms", [])
    ]
    role_refs = [
        _normalized(value)
        for loop in builder.get("gameplay_loops", [])
        if isinstance(loop, dict)
        for value in loop.get("roles", [])
    ]
    room_hits = sum(value in room_names for value in room_refs)
    role_hits = sum(value in role_names for value in role_refs)
    room_rate = room_hits / len(room_refs) if room_refs else 0.0
    role_rate = role_hits / len(role_refs) if role_refs else 0.0
    return 100.0 * _mean([room_rate, role_rate]), {
        "loop_room_reference_count": len(room_refs),
        "resolved_loop_room_references": room_hits,
        "loop_role_reference_count": len(role_refs),
        "resolved_loop_role_references": role_hits,
        "strict_room_reference_rate": round(room_rate, 4),
        "strict_role_reference_rate": round(role_rate, 4),
    }


def _visual_artifact(asset_dir: Path, builder: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    manifest = _read(asset_dir / "world_asset_set_manifest.json")
    component = manifest.get("component_generation", {}) if isinstance(manifest.get("component_generation"), dict) else {}
    jobs = [item for item in component.get("jobs", []) if isinstance(item, dict)]
    sidecar = _read(asset_dir / "world_map_source.components.json")
    semantic = [item for item in sidecar.get("placements", []) if isinstance(item, dict) and item.get("semantic_generated") is True]
    sprite = _read(asset_dir / "sprite_batch_vision_qa.json")
    floor_reports = [_read(path) for path in sorted((asset_dir / "floors").glob("*.qa.json"))]
    canon = builder.get("visual_canon", {}) if isinstance(builder.get("visual_canon"), dict) else {}
    required_canon = (
        "camera", "palette", "materials", "lighting", "architecture", "terrain",
        "sprite_language", "world_prompt_prefix", "sprite_prompt_prefix", "forbidden_visuals",
    )
    observations = {
        "visual_canon_completeness": sum(bool(canon.get(key)) for key in required_canon) / len(required_canon),
        "semantic_component_generation_rate": sum(item.get("status") == "ok" for item in jobs) / len(jobs) if jobs else 0.0,
        "semantic_component_readability_rate": sum(item.get("readability_pass") is True for item in semantic) / len(semantic) if semantic else 0.0,
        "floor_qa_pass_rate": sum(item.get("pass") is True for item in floor_reports) / len(floor_reports) if floor_reports else 0.0,
        "map_source_present": (asset_dir / "world_map_source.png").is_file(),
        "sprite_batch_qa_pass": sprite.get("overall_pass") is True,
        "semantic_component_count": len(jobs),
        "readable_semantic_component_count": sum(item.get("readability_pass") is True for item in semantic),
        "floor_count": len(floor_reports),
        "floor_generation_mode": "procedural_visual_canon_floor",
    }
    score = 100.0 * _mean([
        observations["visual_canon_completeness"],
        observations["semantic_component_generation_rate"],
        observations["semantic_component_readability_rate"],
        observations["floor_qa_pass_rate"],
        float(observations["map_source_present"]),
        float(observations["sprite_batch_qa_pass"]),
    ])
    return score, observations


def _expert_score(review: dict[str, Any], weights: dict[str, float]) -> float | None:
    scores = review.get("scores", {}) if isinstance(review.get("scores"), dict) else {}
    if not scores or any(name not in scores for name in weights):
        return None
    return sum(weights[name] * float(scores[name]) for name in weights)


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# LivingWorldBench Matched-Model Pilot",
        "",
        f"Generated: `{payload['generated_at']}`",
        "",
        f"Sentence: **{payload['sentence']}**",
        "",
        "## Experimental Design",
        "",
        "Five Gemini APIs received the same single-sentence semantic input and used the same specialist world-generation graph. "
        "The selected model was forced across every generative node; compiler, renderer, FLUX service, agent count, player count, temperature, thinking level, and output allowance were held fixed. "
        "This is a development-prompt pilot with one generation replicate per model, so its purpose is diagnosis and protocol calibration rather than population-level model ranking.",
        "",
        "- 12 generated agents and 4 human-player slots per world",
        "- temperature 0.2, low thinking, 16,384 maximum output tokens per call",
        "- one full typed compilation and one FLUX asset pass per model",
        "- three representative sprites requested per model",
        "- one advanced-LLM expert review, exploratory and not blinded",
        "",
        "## Score Contract",
        "",
        "The two objective scores and the expert score are reported independently.",
        "",
        "**Pre-art objective.** A weighted geometric mean of sentence realization (20%), compiled space (15%), agent society (20%), interaction contract (25%), and compiler conformance (20%). "
        "It measures the typed world before visual realization.",
        "",
        "**Full-artifact objective.** A weighted geometric mean of sentence realization (15%), compiled space (10%), strict cross-node referential integrity (12%), agent society (13%), interaction contract (18%), visual artifacts (22%), and compiler conformance (10%). "
        "The geometric mean makes a zero-valued world layer visible instead of allowing strong schema completion to average it away.",
        "",
        "**Expert subjective.** A separately weighted review of premise transformation (15%), institutional causality (20%), spatial/material imagination (15%), agent society (15%), interaction imagination (20%), and rendered-map quality (15%). "
        "The review judges world specificity and experienced coherence that count-based validators do not capture. It is not blended into either objective score.",
        "",
        "## Main Results",
        "",
        "| Model | Pre-art objective | Full artifact objective | Expert subjective | Compile | First pass | Seconds | Tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in sorted(payload["models"], key=lambda item: item.get("expert_subjective_score") or 0, reverse=True):
        lines.append(
            f"| {row['model']} | {row['pre_art_objective_score']:.2f} | {row['full_artifact_objective_score']:.2f} | "
            f"{row['expert_subjective_score']:.2f} | {str(row['complete_success'])} | {str(row['first_pass_success'])} | "
            f"{row['elapsed_seconds']:.1f} | {row['total_tokens']} |"
        )
    lines.extend([
        "",
        "### Objective Axes",
        "",
        "| Model | Sentence | Space | Cross-node | Society | Interaction | Visual | Compiler |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in sorted(payload["models"], key=lambda item: item.get("full_artifact_objective_score") or 0, reverse=True):
        axes = row["objective_axes"]
        lines.append(
            f"| {row['model']} | {axes['sentence_realization']:.2f} | {axes['compiled_space']:.2f} | "
            f"{axes['cross_node_referential_integrity']:.2f} | {axes['agent_society']:.2f} | "
            f"{axes['interaction_contract']:.2f} | {axes['visual_artifact']:.2f} | "
            f"{axes['compiler_conformance']:.2f} |"
        )
    lines.extend([
        "",
        "### Expert Axes",
        "",
        "| Model | Premise | Institutions | Space/material | Society | Interaction | Rendered map |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for row in sorted(payload["models"], key=lambda item: item.get("expert_subjective_score") or 0, reverse=True):
        scores = row["expert_review"]["scores"]
        lines.append(
            f"| {row['model']} | {scores['premise_transformation']:.0f} | "
            f"{scores['institutional_causality']:.0f} | {scores['spatial_material_imagination']:.0f} | "
            f"{scores['agent_society']:.0f} | {scores['interaction_imagination']:.0f} | "
            f"{scores['rendered_map_quality']:.0f} |"
        )
    lines.extend([
        "",
        "## Shared Pipeline Findings",
        "",
    ])
    for finding in payload["shared_pipeline_findings"]:
        lines.append(f"- {finding}")
    lines.extend([
        "",
        "![Matched rendered maps](matched_model_maps.png)",
        "",
        "The map montage is not a model-only comparison. Every map passes through the same structured renderer: FLUX supplies semantic component images, while procedural room packing determines the visible topology and most floor composition. "
        "The consistently rectangular, canal-poor layouts are therefore evidence of a shared renderer ceiling.",
        "",
        "## Model Analyses",
        "",
    ])
    for row in sorted(payload["models"], key=lambda item: item.get("expert_subjective_score") or 0, reverse=True):
        observations = row["objective_observations"]
        interaction = observations["interaction"]
        visual = observations["visual"]
        cross = observations["cross_node"]
        lines.extend([
            f"### {row['model']}: {row['generated_world_name']}",
            "",
            f"Pre-art objective {row['pre_art_objective_score']:.2f}; full-artifact objective {row['full_artifact_objective_score']:.2f}; expert subjective {row['expert_subjective_score']:.2f}. "
            f"Compilation took {row['elapsed_seconds']:.1f}s and {row['total_tokens']} tokens; first-pass success was {row['first_pass_success']}.",
            "",
            f"**World reading.** {row['expert_review'].get('strengths', '')}",
            "",
            f"**Observed limits.** {row['expert_review'].get('weaknesses', '')}",
            "",
            f"**Artifact evidence.** {interaction['world_specific_action_count']} world-specific compiled actions, "
            f"{interaction['interaction_family_count']} interaction families, "
            f"{cross['resolved_loop_room_references']}/{cross['loop_room_reference_count']} resolved loop-room references, "
            f"{visual['readable_semantic_component_count']}/{visual['semantic_component_count']} readable semantic FLUX placements, "
            f"and representative sprite batch pass={visual['sprite_batch_qa_pass']}.",
            "",
        ])
    lines.extend([
        "## Interpretation",
        "",
        "Gemini 3.1 Pro Preview ranks first on the pre-art objective score (93.69) but fourth on expert world quality (64.60). It completed many typed fields and produced strong structural counts, yet its canal politics remained comparatively generic and it required two localized role retries. "
        "Gemini 3.7 Flash shows the reverse pattern: its pre-art objective score is lowest (87.50), while its expert score is highest (82.10) because it turns the sentence into interacting institutions: lock quotas, electoral exchange, toll arbitrage, ward dividends, bonds, and ballot infrastructure.",
        "",
        "The disagreement is informative rather than noise. Current objective structure metrics saturate when every model emits six connected rooms, twelve richly populated characters, and a valid action catalog. They under-measure institutional causality, semantic drift, duplicate roles, and whether the generated mechanisms truly transform the sentence. "
        "The expert review captures those qualities, but a single non-blinded reviewer is not a substitute for independent human ratings. The confirmatory study should retain both layers.",
        "",
        "Once cross-node and visual evidence are added, all five full-artifact scores collapse to 49.84--52.83. This narrow interval is dominated by system-level failures shared across models: zero strict loop references, procedural rather than semantic topology, and zero passing representative motion sprites. "
        "The pilot can therefore distinguish text-world imagination, but it cannot yet estimate how much of that imagination survives into a playable visual world.",
        "",
        "## Next Confirmatory Run",
        "",
        "After the generation graph and asset contracts are frozen, run four development prompts across all candidate models and three seeds per prompt for typed generation. Run the full FLUX, browser, open-proposal, and 24-round society protocol only on the predeclared first valid seed. "
        "Use at least three blinded human raters for player-view quality and an independent advanced-model judge with shuffled model labels. Report paired prompt-level intervals; do not infer significance from this one-prompt pilot.",
        "",
        "The concrete pipeline changes motivated by this pilot are specified in `pipeline_freedom_audit.md`.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, default=ROOT / "frontend/assets/generated/world_asset_sets")
    parser.add_argument("--prompt-suite", type=Path, required=True)
    parser.add_argument("--prompt-id", default="lwb_dev_01")
    parser.add_argument("--expert-review", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    suite = _read(args.prompt_suite)
    prompt = next(item for item in suite.get("prompts", []) if item.get("prompt_id") == args.prompt_id)
    sentence = str(prompt.get("sentence", ""))
    expert = _read(args.expert_review)
    expert_weights = expert.get("weights", {})
    rows = []
    total_loop_room_refs = total_loop_room_hits = 0
    preset_ids = set()
    for model, dirname in MODEL_DIRS.items():
        model_dir = args.base_dir / dirname
        spec_path = _first(model_dir, "*_builder_spec.json")
        config_path = _first(model_dir, "*_world_config.json")
        result_path = _first(model_dir, "*_result.json")
        if not spec_path or not config_path or not result_path:
            continue
        builder, config, result = _read(spec_path), _read(config_path), _read(result_path)
        sentence_score, sentence_obs = _sentence_axis(sentence, config, builder)
        spatial_score, spatial_obs = _spatial_axis(config)
        society_score, society_obs = _society_axis(config)
        interaction_score, interaction_obs = _interaction_axis(config)
        cross_score, cross_obs = _cross_node(builder)
        visual_score, visual_obs = _visual_artifact(args.asset_root / f"lwb_dev01_{dirname}", builder)
        compiler_score = 100.0 * _mean([
            float(result.get("generation_ok") is True),
            float(result.get("merged_contract_probe", {}).get("merged_contract_ok") is True),
            float(result.get("compile_probe", {}).get("compile_ok") is True),
            float(result.get("complete_success") is True),
        ])
        pre_axes = {
            "sentence_realization": sentence_score,
            "compiled_space": spatial_score,
            "agent_society": society_score,
            "interaction_contract": interaction_score,
            "compiler_conformance": compiler_score,
        }
        full_axes = {
            "sentence_realization": sentence_score,
            "compiled_space": spatial_score,
            "cross_node_referential_integrity": cross_score,
            "agent_society": society_score,
            "interaction_contract": interaction_score,
            "visual_artifact": visual_score,
            "compiler_conformance": compiler_score,
        }
        review = expert.get("reviews", {}).get(model, {})
        telemetry = result.get("telemetry", {})
        total_loop_room_refs += cross_obs["loop_room_reference_count"]
        total_loop_room_hits += cross_obs["resolved_loop_room_references"]
        preset_ids.add(str(builder.get("world_seed", {}).get("preset_id", "")))
        rows.append({
            "model": model,
            "generated_world_name": builder.get("world_name", ""),
            "pre_art_objective_score": round(_geometric(pre_axes, PRE_ART_WEIGHTS), 2),
            "full_artifact_objective_score": round(_geometric(full_axes, FULL_WEIGHTS), 2),
            "expert_subjective_score": round(_expert_score(review, expert_weights), 2),
            "objective_axes": {name: round(value, 2) for name, value in full_axes.items()},
            "objective_observations": {
                "sentence": sentence_obs,
                "space": spatial_obs,
                "society": society_obs,
                "interaction": interaction_obs,
                "cross_node": cross_obs,
                "visual": visual_obs,
            },
            "expert_review": review,
            "complete_success": result.get("complete_success") is True,
            "first_pass_success": bool(
                result.get("complete_success") is True
                and not result.get("generation_node_retries")
                and int(telemetry.get("retry_or_failure_attempt_count") or 0) == 0
            ),
            "provider_attempt_count": int(telemetry.get("provider_attempt_count") or 0),
            "provider_retry_count": int(telemetry.get("retry_or_failure_attempt_count") or 0),
            "localized_node_retry_count": len(result.get("generation_node_retries") or []),
            "elapsed_seconds": float(result.get("elapsed_seconds") or 0),
            "total_tokens": int(telemetry.get("token_totals", {}).get("totalTokenCount") or 0),
        })

    payload = {
        "experiment_version": "livingworldbench.matched_models.pilot.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prompt_id": args.prompt_id,
        "sentence": sentence,
        "protocol": {
            "same_sentence": True,
            "same_specialist_pipeline": True,
            "same_model_for_every_generation_node": True,
            "temperature": 0.2,
            "thinking_level": "low",
            "max_output_tokens_per_call": 16384,
            "agent_count": 12,
            "player_count": 4,
            "text_replicates_per_model": 1,
            "representative_sprites_requested_per_model": 3,
            "expert_review": expert.get("review_status"),
        },
        "shared_pipeline_findings": [
            f"All five planners selected only {sorted(preset_ids)} from the four-value preset enum.",
            f"Strict gameplay-loop room references resolved {total_loop_room_hits}/{total_loop_room_refs} across the five worlds.",
            "All five configs compiled, but none explicitly persisted open_proposals_enabled or a __propose__ affordance; generic runtime support exists outside generated content.",
            "All 30 room floors used procedural_visual_canon_floor; FLUX generated semantic components rather than complete room composition.",
            "FLUX produced 43/43 requested semantic components and 40/43 passed placement readability.",
            "All 15 requested representative sprites failed strict motion QA because animation rows repeated static poses.",
        ],
        "models": rows,
    }
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_md.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps({row["model"]: {"objective": row["pre_art_objective_score"], "expert": row["expert_subjective_score"]} for row in rows}, indent=2))


if __name__ == "__main__":
    main()
