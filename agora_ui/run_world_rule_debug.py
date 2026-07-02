from __future__ import annotations
import argparse
import asyncio
import json
import random
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .flex_client import AsyncFlexClient
from .foundation_schemas import (
    CompiledRoomSpec,
    CompiledWorldAgent,
    CompiledWorldSpec,
    GridPosition,
    GridShape,
    MovementPolicy,
    RoomSpec,
    WorldAgentSpec,
    WorldAgentsSpec,
    WorldControlSpec,
    WorldRuleDebugManifest,
    WorldRuleTraceRecord,
    WorldSpec,
)
from .jsonc_utils import dump_json, load_jsonc_path

from .world_rule_debug.core import (
    _resolve_path,
    _now_run_id,
    _now_iso,
    DEFAULT_WORLD_TEMPLATE,
    DEFAULT_WORLD_AGENTS,
    DEFAULT_WORLD_CONTROL,
    DEFAULT_OUTPUT_ROOT
)
from .world_rule_debug.compiler import (
    _compile_world,
    _load_world,
    _load_world_agents,
    _load_world_control
)
from .world_rule_debug.simulation import _simulate_world


"""Compile and simulate the unified world-rule debug workflow.

The workflow has three phases:

1. Load JSONC world, agent, and control templates.
2. Compile them into concrete rooms and initial agent positions.
3. Simulate movement rounds with either deterministic heuristic decisions or
   Flex-backed movement planning.
"""

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the unified world-rule debug workflow from JSONC templates."
    )
    parser.add_argument("--world-template-file", type=Path, default=DEFAULT_WORLD_TEMPLATE)
    parser.add_argument("--world-agents-file", type=Path, default=DEFAULT_WORLD_AGENTS)
    parser.add_argument("--world-control-file", type=Path, default=DEFAULT_WORLD_CONTROL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--validate-only",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Compile and validate only, without simulating rounds.",
    )
    parser.add_argument(
        "--decision-backend-override",
        choices=["heuristic", "flex"],
        default="",
        help="Override control.decision.backend without editing the JSONC control file.",
    )
    parser.add_argument(
        "--flex-api-url-override",
        type=str,
        default="",
        help="Override control.decision.flex_api_url without editing the JSONC control file.",
    )
    parser.add_argument(
        "--model-override",
        type=str,
        default="",
        help="Override control.decision.model without editing the JSONC control file.",
    )
    parser.add_argument(
        "--rounds-override",
        type=int,
        default=-1,
        help="Override control.rounds when non-negative.",
    )
    parser.add_argument(
        "--concurrency-limit-override",
        type=int,
        default=-1,
        help="Override control.decision.concurrency_limit when non-negative.",
    )
    parser.add_argument(
        "--request-timeout-override",
        type=float,
        default=0.0,
        help="Override control.decision.request_timeout_seconds when greater than zero.",
    )
    return parser

async def _main_async() -> None:
    args = _build_arg_parser().parse_args()

    world_template_path = _resolve_path(args.world_template_file)
    world_agents_path = _resolve_path(args.world_agents_file)
    world_control_path = _resolve_path(args.world_control_file)

    world = _load_world(world_template_path)
    world_agents = _load_world_agents(world_agents_path)
    control = _load_world_control(world_control_path)
    if args.decision_backend_override:
        control.decision.backend = args.decision_backend_override
    if args.flex_api_url_override:
        control.decision.flex_api_url = args.flex_api_url_override
    if args.model_override:
        control.decision.model = args.model_override
    if args.rounds_override >= 0:
        control.rounds = args.rounds_override
    if args.concurrency_limit_override >= 0:
        control.decision.concurrency_limit = args.concurrency_limit_override
    if args.request_timeout_override > 0:
        control.decision.request_timeout_seconds = args.request_timeout_override

    run_id = _now_run_id()
    output_root_input = (
        Path(control.output_subdir)
        if Path(args.output_dir) == DEFAULT_OUTPUT_ROOT
        else Path(args.output_dir)
    )
    run_dir = _resolve_path(output_root_input) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    config_payload = {
        "run_id": run_id,
        "created_at": _now_iso(),
        "paths": {
            "world_template_file": str(world_template_path),
            "world_agents_file": str(world_agents_path),
            "world_control_file": str(world_control_path),
        },
        "validate_only": bool(args.validate_only),
        "movement_mode": world.movement_mode,
        "decision_backend": control.decision.backend,
        "decision": control.decision.model_dump(),
        "clock": control.clock.model_dump(),
    }
    dump_json(run_dir / "config.json", config_payload)

    compiled, diagnostics = _compile_world(world, world_agents, control)
    dump_json(run_dir / "compiled_world.json", compiled.model_dump())

    if args.validate_only or control.validate_only:
        dump_json(
            run_dir / "validation.json",
            {
                "status": "ok",
                "message": "world-rule workflow inputs validated and compiled",
                "diagnostics": diagnostics,
            },
        )
        print(f"[VALIDATE-ONLY] ok run_dir={run_dir}")
        return

    try:
        traces, snapshots, round_summaries, final_clock_time = await _simulate_world(compiled)
    except Exception as exc:
        failure_payload = {
            "status": "failed",
            "stage": "world_simulation",
            "error": str(exc),
            "diagnostics": diagnostics,
        }
        failure_path = run_dir / "failure.json"
        dump_json(failure_path, failure_payload)
        failure_manifest = WorldRuleDebugManifest(
            run_id=run_id,
            world_id=compiled.world.world_id,
            rounds=compiled.control.rounds,
            movement_mode=compiled.world.movement_mode,
            final_clock_time=compiled.control.clock.initial_time,
            room_count=len(compiled.rooms),
            agent_count=len(compiled.agents),
            active_agent_count=sum(1 for item in compiled.agents if item.active),
            files={
                "config": str(run_dir / "config.json"),
                "compiled_world": str(run_dir / "compiled_world.json"),
                "failure": str(failure_path),
            },
            diagnostics={**diagnostics, "status": "failed", "error": str(exc)},
        )
        dump_json(run_dir / "final_manifest.json", failure_manifest.model_dump())
        raise
    trace_path = run_dir / "round_trace.jsonl"
    with trace_path.open("w", encoding="utf-8") as handle:
        for item in traces:
            handle.write(item.model_dump_json() + "\n")
    snapshots_path = run_dir / "position_snapshots.json"
    round_summaries_path = run_dir / "round_summaries.json"
    dump_json(snapshots_path, {"snapshots": snapshots})
    dump_json(round_summaries_path, {"round_summaries": round_summaries})

    manifest = WorldRuleDebugManifest(
        run_id=run_id,
        world_id=compiled.world.world_id,
        rounds=compiled.control.rounds,
        movement_mode=compiled.world.movement_mode,
        final_clock_time=final_clock_time,
        room_count=len(compiled.rooms),
        agent_count=len(compiled.agents),
        active_agent_count=sum(1 for item in compiled.agents if item.active),
        files={
            "config": str(run_dir / "config.json"),
            "compiled_world": str(run_dir / "compiled_world.json"),
            "round_trace": str(trace_path),
            "position_snapshots": str(snapshots_path),
            "round_summaries": str(round_summaries_path),
        },
        diagnostics=diagnostics,
    )
    dump_json(run_dir / "final_manifest.json", manifest.model_dump())
    print(f"[DONE] run_dir={run_dir}")

def main() -> None:
    asyncio.run(_main_async())

if __name__ == "__main__":
    main()
