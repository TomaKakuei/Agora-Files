#!/usr/bin/env python3
"""Run a model-controlled decomposed Agora generation experiment.

The treatment uses the production specialist pipeline through package validation,
but omits FLUX art, browser launch, and publication. Each trial is evaluated with
the same merged builder contract and deterministic compiler used by the
monolithic baseline. Results and provider usage metadata are written per trial
so an interrupted experiment can resume without repeating completed calls.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agora_ui.world_builder.generation import (
    DecoupledGenerationExhausted,
    _build_revision_payload,
)
from scripts.agora_monolithic_baseline import (
    _compile_probe,
    _coverage_metrics,
    _generation_request_for,
    _load_rows,
    _load_paper_rows,
    _mean,
    _merged_contract_probe,
    _read_json,
    _safe_array,
    _safe_object,
    _slug,
    _text,
    _wilson,
)


DEFAULT_MONOLITHIC_SUMMARY = (
    "docs/benchmark_20260724/monolithic_baseline_fair_20260729/"
    "monolithic_baseline_summary.json"
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _token_totals(call_rows: list[dict[str, Any]]) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for row in call_rows:
        usage = _safe_object(row.get("usage_metadata"))
        for key, value in usage.items():
            try:
                totals[str(key)] += int(value)
            except (TypeError, ValueError):
                continue
    return dict(sorted(totals.items()))


def _total_token_count(token_totals: dict[str, int]) -> int:
    return int(token_totals.get("totalTokenCount", token_totals.get("total_tokens", 0)) or 0)


def _telemetry_summary(path: Path) -> dict[str, Any]:
    rows = _read_jsonl(path)
    statuses = Counter(_text(row.get("status")) for row in rows)
    stages = Counter(_text(row.get("stage")) for row in rows)
    models = Counter(_text(row.get("model")) for row in rows)
    usage_rows = sum(bool(_safe_object(row.get("usage_metadata"))) for row in rows)
    elapsed = [float(row.get("elapsed_seconds") or 0.0) for row in rows]
    return {
        "path": str(path),
        "provider_attempt_count": len(rows),
        "successful_attempt_count": int(statuses.get("ok", 0)),
        "retry_or_failure_attempt_count": len(rows) - int(statuses.get("ok", 0)),
        "usage_metadata_attempt_count": usage_rows,
        "usage_metadata_coverage": (
            round(usage_rows / len(rows), 4) if rows else 0.0
        ),
        "status_counts": dict(sorted(statuses.items())),
        "stage_attempt_counts": dict(sorted(stages.items())),
        "model_attempt_counts": dict(sorted(models.items())),
        "provider_elapsed_seconds_sum": round(sum(elapsed), 4),
        "token_totals": _token_totals(rows),
    }


def _configure_controlled_environment(
    *,
    provider: str,
    model: str,
    temperature: float,
    thinking_level: str,
    thinking_budget: int,
    max_output_tokens: int,
) -> None:
    values = {
        "AGORA_LLM_PROVIDER": provider,
        "AGORA_VERTEX_BACKEND": "openai_responses" if provider == "openai" else "ai_studio",
        "AGORA_WORLD_CREATOR_MODEL": model,
        "AGORA_WORLD_CREATOR_LITE_MODEL": model,
        "AGORA_WARDROBE_POLICY_MODEL": model,
        "AGORA_VISUAL_CANON_MODEL": model,
        "AGORA_MAIN_CHARACTER_MODEL": model,
        "AGORA_MAIN_CHARACTER_PROFILE_MODEL": model,
        "AGORA_AGENT_PROFILE_MODEL": model,
        "AGORA_INITIAL_INVENTORY_MODEL": model,
        "AGORA_WORLD_CREATOR_MAX_OUTPUT_TOKENS": str(max_output_tokens),
        "AGORA_PLANNER_MAX_OUTPUT_TOKENS": str(max_output_tokens),
        "AGORA_MAIN_CHARACTER_MAX_OUTPUT_TOKENS": str(max_output_tokens),
        "AGORA_EXPERIMENT_FORCE_TEMPERATURE": str(temperature),
        "AGORA_EXPERIMENT_FORCE_THINKING_LEVEL": thinking_level,
        "AGORA_WORLD_CREATOR_THINKING_LEVEL": thinking_level,
        "AGORA_WORLD_CREATOR_THINKING_BUDGET": str(thinking_budget),
        "AGORA_MAIN_CHARACTER_THINKING_BUDGET": str(thinking_budget),
    }
    os.environ.update(values)
    if model.strip().lower().startswith("gemini-3"):
        os.environ.pop("AGORA_EXPERIMENT_FORCE_THINKING_BUDGET", None)
    else:
        os.environ["AGORA_EXPERIMENT_FORCE_THINKING_BUDGET"] = str(thinking_budget)


def _run_one(
    *,
    package_root: Path,
    out_dir: Path,
    row: dict[str, Any],
    replicate: int,
    resume: bool,
    treatment: str = "decomposed",
) -> dict[str, Any]:
    world_name = _text(row.get("world_name"))
    world_slug = _slug(world_name)
    trial_id = f"{world_slug}_r{replicate:02d}"
    result_path = out_dir / f"{trial_id}_decomposed_result.json"
    spec_path = out_dir / f"{trial_id}_decomposed_builder_spec.json"
    config_path = out_dir / f"{trial_id}_decomposed_world_config.json"
    provider = str(os.environ.get("AGORA_LLM_PROVIDER", "gemini")).strip().lower()
    telemetry_path = out_dir / f"{trial_id}_{provider}_calls.jsonl"
    if resume and result_path.is_file():
        cached = _read_json(result_path)
        if cached:
            print(
                f"[DECOMPOSED_RESUME] world={world_name} replicate={replicate}",
                flush=True,
            )
            return cached

    telemetry_path.unlink(missing_ok=True)
    request = _safe_object(row.get("request")) or _generation_request_for(row)
    os.environ["AGORA_VERTEX_TELEMETRY_PATH"] = str(telemetry_path)
    os.environ["AGORA_VERTEX_TELEMETRY_RUN_ID"] = trial_id
    os.environ["AGORA_VERTEX_TELEMETRY_TREATMENT"] = treatment
    os.environ["AGORA_LLM_TELEMETRY_PATH"] = str(telemetry_path)
    os.environ["AGORA_LLM_TELEMETRY_RUN_ID"] = trial_id
    os.environ["AGORA_LLM_TELEMETRY_TREATMENT"] = treatment

    started = time.perf_counter()
    builder_spec: dict[str, Any] = {}
    config: dict[str, Any] = {}
    package_validation: dict[str, Any] = {}
    compiler_critique: dict[str, Any] = {}
    failed_generation_node_retries: list[dict[str, Any]] = []
    error = ""
    temp_package_db: Path | None = None
    try:
        (
            builder_spec,
            config,
            _world_summary,
            temp_package_db,
            package_validation,
            compiler_critique,
            _pipeline_artifacts,
            _agent_payloads,
        ) = _build_revision_payload(
            package_root=package_root,
            request=request,
            prior_context=None,
            feedback="",
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:1500]}"
        if isinstance(exc, DecoupledGenerationExhausted):
            failed_generation_node_retries = _safe_array(
                exc.generation_node_retries
            )
    finally:
        if temp_package_db is not None:
            temp_package_db.unlink(missing_ok=True)

    elapsed_seconds = round(time.perf_counter() - started, 4)
    if builder_spec:
        _write_json(spec_path, builder_spec)
    if config:
        _write_json(config_path, config)

    merged_contract_probe = (
        _merged_contract_probe(builder_spec, request)
        if builder_spec
        else {"merged_contract_ok": False, "error": "no builder_spec"}
    )
    compile_probe = (
        _compile_probe(package_root, builder_spec, request)
        if builder_spec
        else {"compile_ok": False, "error": "no builder_spec"}
    )
    metrics = (
        _coverage_metrics(builder_spec, builder_spec, request)
        if builder_spec
        else {}
    )
    telemetry = _telemetry_summary(telemetry_path)
    complete_success = bool(
        builder_spec
        and merged_contract_probe.get("merged_contract_ok") is True
        and compile_probe.get("compile_ok") is True
        and not error
    )
    result = {
        "trial_id": trial_id,
        "world_name": world_name,
        "draft_id": _text(row.get("draft_id")),
        "source_revision_dir": _text(row.get("revision_dir")),
        "replicate": replicate,
        "request": request,
        "elapsed_seconds": elapsed_seconds,
        "generation_ok": bool(builder_spec) and not error,
        "complete_success": complete_success,
        "error": error,
        "builder_spec_path": str(spec_path) if builder_spec else "",
        "world_config_path": str(config_path) if config else "",
        "merged_contract_probe": merged_contract_probe,
        "compile_probe": compile_probe,
        "metrics": metrics,
        "package_validation_status": _text(package_validation.get("status")),
        "compiler_critique_applied": bool(
            package_validation.get("compiler_critique_applied")
        ),
        "compiler_critique_should_repair": bool(
            compiler_critique.get("should_repair")
        ),
        "generation_node_retries": (
            _safe_array(package_validation.get("generation_node_retries"))
            or failed_generation_node_retries
        ),
        "telemetry": telemetry,
    }
    _write_json(result_path, result)
    print(
        "[DECOMPOSED_DONE] "
        f"world={world_name} replicate={replicate} "
        f"success={complete_success} calls={telemetry['provider_attempt_count']} "
        f"tokens={_total_token_count(telemetry['token_totals'])} "
        f"elapsed_seconds={elapsed_seconds}",
        flush=True,
    )
    return result


def _binomial_upper_tail(successes: int, trials: int) -> float:
    if trials <= 0:
        return 1.0
    return min(
        1.0,
        sum(math.comb(trials, value) for value in range(successes, trials + 1))
        / (2**trials),
    )


def _paired_summary(
    decomposed_rows: list[dict[str, Any]],
    monolithic_payload: dict[str, Any],
) -> dict[str, Any]:
    monolithic_rows = {
        (_text(row.get("world_name")), int(row.get("replicate") or 0)): row
        for row in _safe_array(monolithic_payload.get("worlds"))
        if isinstance(row, dict)
    }
    pairs: list[dict[str, Any]] = []
    for row in decomposed_rows:
        key = (_text(row.get("world_name")), int(row.get("replicate") or 0))
        baseline = monolithic_rows.get(key)
        if baseline is None:
            continue
        baseline_success = bool(
            _safe_object(baseline.get("merged_contract_probe")).get(
                "merged_contract_ok"
            )
            is True
            and _safe_object(baseline.get("compile_probe")).get("compile_ok")
            is True
        )
        decomposed_first_pass = bool(
            row.get("complete_success")
            and int(
                _safe_object(row.get("telemetry")).get(
                    "retry_or_failure_attempt_count"
                )
                or 0
            )
            == 0
            and not _safe_array(row.get("generation_node_retries"))
        )
        monolithic_first_pass = bool(
            baseline_success
            and int(
                _safe_object(baseline.get("telemetry")).get(
                    "retry_or_failure_attempt_count"
                )
                or 0
            )
            == 0
        )
        pairs.append(
            {
                "world_name": key[0],
                "replicate": key[1],
                "decomposed_success": bool(row.get("complete_success")),
                "monolithic_success": baseline_success,
                "decomposed_first_pass_success": decomposed_first_pass,
                "monolithic_first_pass_success": monolithic_first_pass,
            }
        )
    decomposed_only = sum(
        pair["decomposed_success"] and not pair["monolithic_success"]
        for pair in pairs
    )
    monolithic_only = sum(
        pair["monolithic_success"] and not pair["decomposed_success"]
        for pair in pairs
    )
    discordant = decomposed_only + monolithic_only
    first_pass_decomposed_only = sum(
        pair["decomposed_first_pass_success"]
        and not pair["monolithic_first_pass_success"]
        for pair in pairs
    )
    first_pass_monolithic_only = sum(
        pair["monolithic_first_pass_success"]
        and not pair["decomposed_first_pass_success"]
        for pair in pairs
    )
    first_pass_discordant = (
        first_pass_decomposed_only + first_pass_monolithic_only
    )
    world_names = sorted({pair["world_name"] for pair in pairs})
    decomposed_majority_only = 0
    monolithic_majority_only = 0
    for world_name in world_names:
        world_pairs = [
            pair for pair in pairs if pair["world_name"] == world_name
        ]
        decomposed_majority = (
            sum(pair["decomposed_first_pass_success"] for pair in world_pairs)
            > len(world_pairs) / 2.0
        )
        monolithic_majority = (
            sum(pair["monolithic_first_pass_success"] for pair in world_pairs)
            > len(world_pairs) / 2.0
        )
        decomposed_majority_only += decomposed_majority and not monolithic_majority
        monolithic_majority_only += monolithic_majority and not decomposed_majority
    world_discordant = decomposed_majority_only + monolithic_majority_only
    return {
        "paired_trial_count": len(pairs),
        "decomposed_only_successes": decomposed_only,
        "monolithic_only_successes": monolithic_only,
        "discordant_trial_count": discordant,
        "trial_level_one_sided_exact_p": round(
            _binomial_upper_tail(decomposed_only, discordant), 6
        ),
        "first_pass_decomposed_only_successes": first_pass_decomposed_only,
        "first_pass_monolithic_only_successes": first_pass_monolithic_only,
        "first_pass_discordant_trial_count": first_pass_discordant,
        "first_pass_trial_level_one_sided_exact_p": round(
            _binomial_upper_tail(
                first_pass_decomposed_only,
                first_pass_discordant,
            ),
            6,
        ),
        "first_pass_world_majority_decomposed_only": decomposed_majority_only,
        "first_pass_world_majority_monolithic_only": monolithic_majority_only,
        "first_pass_world_discordant_count": world_discordant,
        "first_pass_world_level_one_sided_sign_test_p": round(
            _binomial_upper_tail(decomposed_majority_only, world_discordant),
            6,
        ),
        "warning": (
            "Repeated trials within a world are not independent premise clusters; "
            "the world-majority analysis remains primary."
        ),
        "pairs": pairs,
    }


def _summarize(
    rows: list[dict[str, Any]],
    monolithic_payload: dict[str, Any],
) -> dict[str, Any]:
    successes = [row for row in rows if row.get("complete_success") is True]
    world_names = sorted({_text(row.get("world_name")) for row in rows})
    per_world: list[dict[str, Any]] = []
    majority_successes = 0
    first_pass_majority_successes = 0
    for world_name in world_names:
        world_rows = [
            row for row in rows if _text(row.get("world_name")) == world_name
        ]
        count = sum(row.get("complete_success") is True for row in world_rows)
        first_pass_count = sum(
            row.get("complete_success") is True
            and int(
                _safe_object(row.get("telemetry")).get(
                    "retry_or_failure_attempt_count"
                )
                or 0
            )
            == 0
            and not _safe_array(row.get("generation_node_retries"))
            for row in world_rows
        )
        majority_successes += count > len(world_rows) / 2.0
        first_pass_majority_successes += first_pass_count > (
            len(world_rows) / 2.0
        )
        per_world.append(
            {
                "world_name": world_name,
                "successes": count,
                "first_pass_successes": first_pass_count,
                "trials": len(world_rows),
                "success_rate": round(count / len(world_rows), 4),
                "first_pass_success_rate": round(
                    first_pass_count / len(world_rows), 4
                ),
                "wilson_95": _wilson(count, len(world_rows)),
            }
        )

    token_totals: Counter[str] = Counter()
    total_attempts = 0
    retry_attempts = 0
    usage_attempts = 0
    localized_retry_events: list[dict[str, Any]] = []
    for row in rows:
        telemetry = _safe_object(row.get("telemetry"))
        total_attempts += int(telemetry.get("provider_attempt_count") or 0)
        retry_attempts += int(
            telemetry.get("retry_or_failure_attempt_count") or 0
        )
        usage_attempts += int(
            telemetry.get("usage_metadata_attempt_count") or 0
        )
        for key, value in _safe_object(telemetry.get("token_totals")).items():
            token_totals[str(key)] += int(value)
        localized_retry_events.extend(
            event
            for event in _safe_array(row.get("generation_node_retries"))
            if isinstance(event, dict)
        )

    elapsed = [float(row.get("elapsed_seconds") or 0.0) for row in rows]
    success_count = len(successes)
    first_pass_success_count = sum(
        row.get("complete_success") is True
        and int(
            _safe_object(row.get("telemetry")).get(
                "retry_or_failure_attempt_count"
            )
            or 0
        )
        == 0
        and not _safe_array(row.get("generation_node_retries"))
        for row in rows
    )
    failed_nodes = Counter(
        _text(event.get("failed_node")) for event in localized_retry_events
    )
    preserved_cache_key_count = sum(
        len(_safe_array(event.get("preserved_cache_keys")))
        for event in localized_retry_events
    )
    return {
        "world_count": len(world_names),
        "trial_count": len(rows),
        "complete_successes": success_count,
        "complete_success_rate": (
            round(success_count / len(rows), 4) if rows else 0.0
        ),
        "complete_success_wilson_95": _wilson(success_count, len(rows)),
        "worlds_with_majority_success": majority_successes,
        "first_pass_complete_successes": first_pass_success_count,
        "first_pass_complete_success_rate": (
            round(first_pass_success_count / len(rows), 4) if rows else 0.0
        ),
        "worlds_with_majority_first_pass_success": first_pass_majority_successes,
        "per_world": per_world,
        "mean_elapsed_seconds": _mean(elapsed),
        "median_elapsed_seconds": (
            round(statistics.median(elapsed), 4) if elapsed else 0.0
        ),
        "provider_attempt_count": total_attempts,
        "retry_or_failure_attempt_count": retry_attempts,
        "usage_metadata_attempt_count": usage_attempts,
        "usage_metadata_coverage": (
            round(usage_attempts / total_attempts, 4)
            if total_attempts
            else 0.0
        ),
        "localized_node_retry_event_count": len(localized_retry_events),
        "localized_node_retry_failed_node_counts": dict(sorted(failed_nodes.items())),
        "localized_node_retry_preserved_cache_key_count": preserved_cache_key_count,
        "token_totals": dict(sorted(token_totals.items())),
        "mean_total_tokens_per_trial": (
            round(_total_token_count(token_totals) / len(rows), 2)
            if rows
            else 0.0
        ),
        "paired_monolithic": _paired_summary(rows, monolithic_payload),
    }


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    summary = _safe_object(payload.get("summary"))
    lines = [
        "# Model-Controlled Decomposed Baseline",
        "",
        f"Generated: `{payload.get('generated_at')}`",
        "",
        "Production specialist generation and package validation are run without "
        "FLUX art, browser launch, or publication. Pro and lite node groups are "
        "forced to the same model and generation settings for this experiment.",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        if key not in {"per_world", "paired_monolithic"}:
            lines.append(f"- `{key}`: {value}")
    paired = _safe_object(summary.get("paired_monolithic"))
    lines.extend(["", "## Paired Monolithic Comparison", ""])
    for key, value in paired.items():
        if key != "pairs":
            lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Per World",
            "",
            "| World | Success | Trials | Rate |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in _safe_array(summary.get("per_world")):
        lines.append(
            f"| {row.get('world_name')} | {row.get('successes')} | "
            f"{row.get('trials')} | {row.get('success_rate')} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default="docs/benchmark_20260724/benchmark_manifest.json",
    )
    parser.add_argument(
        "--legacy-cases",
        action="store_true",
        help="Use the five frozen complete legacy worlds instead of the paper cases.",
    )
    parser.add_argument(
        "--out-dir",
        default="docs/benchmark_20260724/decomposed_controlled_20260729",
    )
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "AGORA_DECOMPOSED_EXPERIMENT_MODEL", "gemini-3-flash-preview"
        ),
    )
    parser.add_argument(
        "--provider",
        choices=("auto", "gemini", "openai"),
        default="auto",
        help="JSON generation provider. Auto selects OpenAI for gpt-* models.",
    )
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--thinking-level", default="low")
    parser.add_argument(
        "--thinking-budget",
        type=int,
        default=1024,
        help="Legacy numeric budget for pre-Gemini-3 models; Gemini 3 uses thinking-level.",
    )
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument(
        "--prompt-suite",
        default="",
        help="Optional LivingWorldBench prompt-suite JSON; exposes only its sentence as semantic input.",
    )
    parser.add_argument(
        "--prompt-id",
        default="",
        help="Prompt ID to select when --prompt-suite is supplied.",
    )
    parser.add_argument("--agent-count", type=int, default=12)
    parser.add_argument("--player-count", type=int, default=4)
    parser.add_argument(
        "--monolithic-summary",
        default=DEFAULT_MONOLITHIC_SUMMARY,
    )
    args = parser.parse_args()

    package_root = Path.cwd().resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    provider = str(args.provider)
    if provider == "auto":
        provider = "openai" if str(args.model).strip().lower().startswith(("gpt-", "o1", "o3", "o4")) else "gemini"
    _configure_controlled_environment(
        provider=provider,
        model=str(args.model),
        temperature=float(args.temperature),
        thinking_level=str(args.thinking_level).strip().lower(),
        thinking_budget=max(0, int(args.thinking_budget)),
        max_output_tokens=max(1024, int(args.max_output_tokens)),
    )

    if args.prompt_suite:
        suite = _read_json(Path(args.prompt_suite).resolve())
        prompt = next(
            (
                item
                for item in _safe_array(suite.get("prompts"))
                if isinstance(item, dict)
                and _text(item.get("prompt_id")) == _text(args.prompt_id)
            ),
            None,
        )
        if prompt is None:
            raise ValueError(f"Prompt ID not found in suite: {args.prompt_id}")
        sentence = _text(prompt.get("sentence"))
        rows = [
            {
                "world_name": _text(prompt.get("prompt_id")),
                "request": {
                    "world_name": "",
                    "genre": "",
                    "player_count_target": max(1, int(args.player_count)),
                    "agent_count_target": max(8, int(args.agent_count)),
                    "focus": "",
                    "seed": 26082401,
                    "brief": sentence,
                },
            }
        ]
    else:
        rows = (
            _load_rows(Path(args.manifest).resolve(), args.limit)
            if args.legacy_cases
            else _load_paper_rows(package_root, args.limit)
        )
    results: list[dict[str, Any]] = []
    for replicate in range(1, max(1, int(args.replicates)) + 1):
        for row in rows:
            print(
                f"[DECOMPOSED_START] world={row.get('world_name')} "
                f"replicate={replicate}",
                flush=True,
            )
            results.append(
                _run_one(
                    package_root=package_root,
                    out_dir=out_dir,
                    row=row,
                    replicate=replicate,
                    resume=bool(args.resume),
                )
            )

    monolithic_path = Path(args.monolithic_summary).resolve()
    monolithic_payload = _read_json(monolithic_path)
    monolithic_model = _text(monolithic_payload.get("model"))
    monolithic_temperature = monolithic_payload.get("temperature")
    monolithic_thinking_level = _text(
        monolithic_payload.get("thinking_level")
    ).lower()
    monolithic_output_cap = int(
        monolithic_payload.get("max_output_tokens") or 0
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "treatment": "production_specialist_decomposition_without_art",
        "model": str(args.model),
        "temperature": float(args.temperature),
        "thinking_level": str(args.thinking_level).strip().lower(),
        "thinking_budget": max(0, int(args.thinking_budget)),
        "max_output_tokens": max(1024, int(args.max_output_tokens)),
        "replicates": max(1, int(args.replicates)),
        "case_set": (
            f"livingworldbench:{args.prompt_id}"
            if args.prompt_suite
            else ("legacy_heldout" if args.legacy_cases else "paper_primary")
        ),
        "manifest_path": (
            str(Path(args.manifest).resolve()) if args.legacy_cases else ""
        ),
        "monolithic_summary_path": str(monolithic_path),
        "protocol": {
            "same_original_briefs": True,
            "generator_semantic_input": (
                "sentence_only" if args.prompt_suite else "original_request"
            ),
            "input_case_count": len(rows),
            "same_model_across_all_specialist_nodes": True,
            "same_model_as_monolithic": (
                not monolithic_model or monolithic_model == str(args.model)
            ),
            "same_temperature_as_monolithic": (
                monolithic_temperature is None
                or float(monolithic_temperature) == float(args.temperature)
            ),
            "same_thinking_level_as_monolithic": (
                not monolithic_thinking_level
                or monolithic_thinking_level
                == str(args.thinking_level).strip().lower()
            ),
            "same_per_call_output_cap_as_monolithic": (
                not monolithic_output_cap
                or monolithic_output_cap == max(1024, int(args.max_output_tokens))
            ),
            "monolithic_output_cap": monolithic_output_cap,
            "same_merged_contract_evaluator": True,
            "same_deterministic_compiler": True,
            "strict_no_content_fallback": True,
            "art_browser_publish_excluded": True,
            "provider_usage_metadata_recorded": True,
            "provider": provider,
            "thinking_control": (
                "reasoning_effort"
                if provider == "openai"
                else (
                    "thinking_level"
                    if str(args.model).strip().lower().startswith("gemini-3")
                    else "thinking_budget"
                )
            ),
        },
        "summary": _summarize(results, monolithic_payload),
        "worlds": results,
    }
    json_path = out_dir / "decomposed_controlled_summary.json"
    md_path = out_dir / "decomposed_controlled_summary.md"
    _write_json(json_path, payload)
    _write_markdown(md_path, payload)
    print(
        json.dumps(
            {
                "json": str(json_path),
                "markdown": str(md_path),
                "summary": payload["summary"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
