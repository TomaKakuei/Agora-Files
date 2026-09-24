#!/usr/bin/env python3
"""Agora-mini Scenario Manifest launcher."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .adjudicator_schemas import (
    AdjudicatorControlSpec,
    AdjudicatorFlexSpec,
    AgentIntentBatchSpec,
    AgentRuntimeProfileSpec,
    AgentStateBundleSpec,
    RelationshipVectorSpec,
)
from .jsonc_utils import dump_json, load_jsonc_path
from . import run_universal_adjudicator as adjudicator
from .scenario_schemas import (
    RelationshipTensorBundleSpec,
    ScenarioManifestSpec,
    ScenarioMapGridSpec,
)


SCRIPT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SCENARIOS_DIR = SCRIPT_DIR / "sample_json"
DEFAULT_OUTPUT_ROOT = SCRIPT_DIR / "output" / "scenario_launcher"

PROVIDER_SERVER_SCRIPTS = {
    "Gemini_Studio": "gemini_flex_server.py",
    "Vertex_AI": "vertex_flex_server.py",
    "GPT": "gpt_flex_server.py",
    "Generic": "generic_flex_server.py",
}


class ScenarioTimestepError(RuntimeError):
    def __init__(self, message: str, diagnostics: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


def _now_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _resolve_path(path_like: Path | str) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path.resolve()
    local = (SCRIPT_DIR / path).resolve()
    if local.exists():
        return local
    return (Path.cwd() / path).resolve()


def _resolve_scenario_path(scenario_dir: Path, path_like: str) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (scenario_dir / path).resolve()


def _load_manifest(path: Path) -> ScenarioManifestSpec:
    return ScenarioManifestSpec.model_validate(load_jsonc_path(path))


def _scan_manifests(scenarios_dir: Path) -> list[Path]:
    if not scenarios_dir.exists():
        return []
    results: list[Path] = []
    for name in ("manifest.json", "manifest.jsonc"):
        results.extend(scenarios_dir.glob(f"*/{name}"))
    return sorted(path.resolve() for path in results)


def _scenario_label(path: Path, manifest: ScenarioManifestSpec) -> str:
    return f"{path.parent.name}: {manifest.scenario_meta.world_name} ({manifest.scenario_meta.world_id})"


def _select_manifest(
    *,
    scenarios_dir: Path,
    manifest_path: Optional[Path],
    scenario_selector: str,
) -> Path:
    if manifest_path is not None:
        return _resolve_path(manifest_path)

    manifests = _scan_manifests(scenarios_dir)
    if not manifests:
        raise FileNotFoundError(f"no scenario manifests found under {scenarios_dir}")

    if scenario_selector:
        normalized = scenario_selector.strip().lower()
        for candidate in manifests:
            manifest = _load_manifest(candidate)
            names = {
                candidate.parent.name.lower(),
                manifest.scenario_meta.world_id.lower(),
                manifest.scenario_meta.world_name.lower(),
            }
            if normalized in names:
                return candidate
        raise ValueError(f"scenario not found: {scenario_selector}")

    if len(manifests) == 1 or not sys.stdin.isatty():
        return manifests[0]

    print("[System] Found Worlds:")
    for index, candidate in enumerate(manifests, start=1):
        print(f"  {index}: {_scenario_label(candidate, _load_manifest(candidate))}")
    raw = input("Select World to initialize by number, or type path to custom manifest: ").strip()
    if raw.isdigit():
        index = int(raw) - 1
        if not 0 <= index < len(manifests):
            raise ValueError(f"scenario index out of range: {raw}")
        return manifests[index]
    return _resolve_path(raw)


def _load_map_grid(path: Path) -> ScenarioMapGridSpec:
    return ScenarioMapGridSpec.model_validate(load_jsonc_path(path))


def _load_agent(path: Path) -> AgentRuntimeProfileSpec:
    return AgentRuntimeProfileSpec.model_validate(load_jsonc_path(path))


def _load_relationship_tensor(path: Path) -> dict[str, dict[str, RelationshipVectorSpec]]:
    payload = load_jsonc_path(path)
    if isinstance(payload, dict) and "relationship_tensor" in payload:
        return RelationshipTensorBundleSpec.model_validate(payload).relationship_tensor
    return RelationshipTensorBundleSpec.model_validate({"relationship_tensor": payload}).relationship_tensor


def _default_relationship_tensor(agent_ids: list[str]) -> dict[str, dict[str, RelationshipVectorSpec]]:
    tensor: dict[str, dict[str, RelationshipVectorSpec]] = {}
    for source_id in agent_ids:
        tensor[source_id] = {}
        for target_id in agent_ids:
            if source_id == target_id:
                continue
            tensor[source_id][target_id] = RelationshipVectorSpec()
    return tensor


def _build_agent_state(
    *,
    scenario_dir: Path,
    manifest: ScenarioManifestSpec,
    map_grid: ScenarioMapGridSpec,
) -> tuple[AgentStateBundleSpec, dict[str, str]]:
    agent_paths: dict[str, str] = {}
    agents: list[AgentRuntimeProfileSpec] = []
    for relative in manifest.asset_bindings.active_agents:
        path = _resolve_scenario_path(scenario_dir, relative)
        agent = _load_agent(path)
        if agent.agent_id in map_grid.initial_positions:
            agent.coordinates = map_grid.initial_positions[agent.agent_id].model_copy(deep=True)
        if agent.agent_id in map_grid.initial_room_ids:
            agent.room_id = map_grid.initial_room_ids[agent.agent_id]
        else:
            agent.room_id = adjudicator._room_for_position(agent.coordinates, map_grid.rooms)
        agent_paths[agent.agent_id] = str(path)
        agents.append(agent)

    if manifest.asset_bindings.relationship_tensor_path:
        relationship_path = _resolve_scenario_path(
            scenario_dir,
            manifest.asset_bindings.relationship_tensor_path,
        )
        relationship_tensor = _load_relationship_tensor(relationship_path)
    else:
        relationship_tensor = _default_relationship_tensor([agent.agent_id for agent in agents])

    if manifest.asset_bindings.localized_visual_state_path:
        visual_state_path = _resolve_scenario_path(
            scenario_dir,
            manifest.asset_bindings.localized_visual_state_path,
        )
        localized_visual_state = load_jsonc_path(visual_state_path)
        if not isinstance(localized_visual_state, dict):
            raise ValueError("localized_visual_state_path must point to a JSON object")
    else:
        localized_visual_state = {}

    return (
        AgentStateBundleSpec(
            agents=agents,
            relationship_tensor=relationship_tensor,
            localized_visual_state=localized_visual_state,
        ),
        agent_paths,
    )


def _load_intent_batches(
    *,
    scenario_dir: Path,
    manifest: ScenarioManifestSpec,
) -> tuple[list[AgentIntentBatchSpec], list[str]]:
    paths: list[Path] = []
    if manifest.asset_bindings.intent_batches_path:
        batches_dir = _resolve_scenario_path(scenario_dir, manifest.asset_bindings.intent_batches_path)
        if not batches_dir.is_dir():
            raise ValueError(f"intent_batches_path must be a directory: {batches_dir}")
        for pattern in ("*.json", "*.jsonc"):
            paths.extend(batches_dir.glob(pattern))
        paths = sorted(set(path.resolve() for path in paths))
    else:
        paths = [_resolve_scenario_path(scenario_dir, manifest.asset_bindings.intents_path)]

    max_timesteps = manifest.engine_config.simulation_params.max_timesteps
    selected_paths = paths[:max_timesteps]
    batches = [
        AgentIntentBatchSpec.model_validate(load_jsonc_path(path))
        for path in selected_paths
    ]
    return batches, [str(path) for path in selected_paths]


def _provider_backend(provider: str) -> str:
    return "local" if provider == "Local" else "flex"


def _build_control(
    *,
    manifest: ScenarioManifestSpec,
    prompt_path: Path,
    timestep_index: int,
) -> AdjudicatorControlSpec:
    api = manifest.engine_config.adjudicator_api
    return AdjudicatorControlSpec(
        run_name=f"scenario_launcher_{manifest.scenario_meta.world_id}",
        adjudication_backend=_provider_backend(api.provider),
        world_description=manifest.scenario_meta.description,
        simulation_objective=(
            manifest.scenario_meta.simulation_objective
            or f"Run scenario {manifest.scenario_meta.world_name}."
        ),
        social_norms=[],
        timestep_index=timestep_index,
        prompt_file=str(prompt_path),
        output_subdir="output/scenario_launcher",
        flex=AdjudicatorFlexSpec(
            flex_api_url=api.flex_api_url,
            model=api.model,
            temperature=api.temperature,
            thinking_level="medium",
            max_output_tokens=2048,
            timeout_seconds=60.0,
        ),
    )


def _build_runtime_from_manifest(
    manifest_path: Path,
    *,
    adjudicator_provider_override: str = "",
    flex_api_url_override: str = "",
    model_override: str = "",
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    if adjudicator_provider_override:
        manifest.engine_config.adjudicator_api.provider = adjudicator_provider_override
    if flex_api_url_override:
        manifest.engine_config.adjudicator_api.flex_api_url = flex_api_url_override
    if model_override:
        manifest.engine_config.adjudicator_api.model = model_override

    scenario_dir = manifest_path.parent
    world_rules_path = _resolve_scenario_path(scenario_dir, manifest.asset_bindings.world_rules_path)
    map_grid_path = _resolve_scenario_path(scenario_dir, manifest.asset_bindings.map_grid_path)
    prompt_path = (
        _resolve_scenario_path(scenario_dir, manifest.asset_bindings.prompt_path)
        if manifest.asset_bindings.prompt_path
        else (SCRIPT_DIR / "data" / "templates" / "foundation" / "universal_adjudicator_prompt.jsonc").resolve()
    )
    world_rules = adjudicator._load_world_rules(world_rules_path)
    map_grid = _load_map_grid(map_grid_path)
    world_rules.world_mode = manifest.engine_config.world_mode
    world_rules.topology.grid_shape = map_grid.grid_shape.model_copy(deep=True)
    world_rules.topology.rooms = [room.model_copy(deep=True) for room in map_grid.rooms]
    control = _build_control(
        manifest=manifest,
        prompt_path=prompt_path,
        timestep_index=1,
    )
    control.social_norms = list(world_rules.social_rules)
    prompt = adjudicator._load_prompt(prompt_path)
    agent_state, agent_paths = _build_agent_state(
        scenario_dir=scenario_dir,
        manifest=manifest,
        map_grid=map_grid,
    )
    intent_batches, intent_paths = _load_intent_batches(
        scenario_dir=scenario_dir,
        manifest=manifest,
    )
    if intent_batches:
        control.timestep_index = intent_batches[0].timestep_index
    rendered_prompt = adjudicator._render_prompt(prompt, control)
    provider = manifest.engine_config.adjudicator_api.provider
    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "scenario_dir": scenario_dir,
        "world_rules": world_rules,
        "world_rules_path": world_rules_path,
        "map_grid": map_grid,
        "map_grid_path": map_grid_path,
        "control": control,
        "prompt": prompt,
        "prompt_path": prompt_path,
        "rendered_prompt": rendered_prompt,
        "agent_state": agent_state,
        "agent_paths": agent_paths,
        "intent_batches": intent_batches,
        "intent_paths": intent_paths,
        "provider_route": {
            "provider": provider,
            "backend": control.adjudication_backend,
            "server_script": (
                manifest.engine_config.adjudicator_api.server_script
                or PROVIDER_SERVER_SCRIPTS.get(provider, "")
            ),
            "flex_api_url": manifest.engine_config.adjudicator_api.flex_api_url,
            "model": manifest.engine_config.adjudicator_api.model,
            "temperature": manifest.engine_config.adjudicator_api.temperature,
            "agent_default_provider": manifest.engine_config.agent_default_api.provider,
            "agent_default_model": manifest.engine_config.agent_default_api.model,
            "parallel_execution": manifest.engine_config.simulation_params.parallel_execution,
            "concurrency_limit": manifest.engine_config.simulation_params.concurrency_limit,
        },
    }


def _run_adjudicator_timestep(
    *,
    control: AdjudicatorControlSpec,
    rendered_prompt: str,
    world_rules: Any,
    agent_state: AgentStateBundleSpec,
    intent_batch: AgentIntentBatchSpec,
) -> tuple[dict[str, Any], AgentStateBundleSpec, Any, dict[str, Any], str]:
    step_control = control.model_copy(update={"timestep_index": intent_batch.timestep_index})
    backend = step_control.adjudication_backend
    diagnostics: dict[str, Any] = {}
    try:
        if step_control.adjudication_backend == "flex":
            output = adjudicator._flex_adjudicate(
                control=step_control,
                rendered_prompt=rendered_prompt,
                world_rules=world_rules,
                agent_state=agent_state,
                intent_batch=intent_batch,
            )
            updated_state, updated_rules, apply_diagnostics = adjudicator._apply_flex_output_to_state(
                adjudicator_output=output,
                agent_state=agent_state,
                world_rules=world_rules,
            )
            diagnostics["flex_status"] = "ok"
            diagnostics["flex_apply"] = apply_diagnostics
            if apply_diagnostics.get("apply_errors"):
                raise RuntimeError(
                    "failed to apply Flex output: "
                    + "; ".join(str(item) for item in apply_diagnostics["apply_errors"])
                )
            return output, updated_state, updated_rules, diagnostics, backend

        output, updated_state, updated_rules = adjudicator._local_adjudicate(
            control=step_control,
            world_rules=world_rules,
            agent_state=agent_state,
            intent_batch=intent_batch,
        )
        return output, updated_state, updated_rules, diagnostics, backend
    except Exception as exc:
        diagnostics["status"] = "failed"
        if step_control.adjudication_backend == "flex":
            diagnostics["flex_status"] = "failed"
            diagnostics["flex_error"] = str(exc)
        else:
            diagnostics["local_error"] = str(exc)
        raise ScenarioTimestepError(str(exc), diagnostics) from exc


def _write_runtime_bundle(
    *,
    run_dir: Path,
    runtime: dict[str, Any],
    validate_only: bool,
) -> dict[str, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest: ScenarioManifestSpec = runtime["manifest"]
    control: AdjudicatorControlSpec = runtime["control"]
    files = {
        "launcher_config": str(run_dir / "launcher_config.json"),
        "rendered_system_prompt": str(run_dir / "rendered_system_prompt.txt"),
        "compiled_control": str(run_dir / "compiled_control.json"),
        "compiled_world_rules_initial": str(run_dir / "compiled_world_rules_initial.json"),
        "compiled_agent_state_initial": str(run_dir / "compiled_agent_state_initial.json"),
        "compiled_intent_batches": str(run_dir / "compiled_intent_batches.json"),
    }
    dump_json(
        run_dir / "launcher_config.json",
        {
            "run_id": run_dir.name,
            "created_at": _now_iso(),
            "validate_only": validate_only,
            "scenario_meta": manifest.scenario_meta.model_dump(),
            "paths": {
                "manifest": str(runtime["manifest_path"]),
                "scenario_dir": str(runtime["scenario_dir"]),
                "world_rules": str(runtime["world_rules_path"]),
                "map_grid": str(runtime["map_grid_path"]),
                "prompt": str(runtime["prompt_path"]),
                "agents": runtime["agent_paths"],
                "intents": runtime["intent_paths"],
            },
            "provider_route": runtime["provider_route"],
            "simulation_params": manifest.engine_config.simulation_params.model_dump(),
        },
    )
    Path(files["rendered_system_prompt"]).write_text(runtime["rendered_prompt"] + "\n", encoding="utf-8")
    dump_json(run_dir / "compiled_control.json", control.model_dump())
    dump_json(run_dir / "compiled_world_rules_initial.json", runtime["world_rules"].model_dump())
    dump_json(run_dir / "compiled_agent_state_initial.json", runtime["agent_state"].model_dump())
    dump_json(
        run_dir / "compiled_intent_batches.json",
        {"intent_batches": [item.model_dump() for item in runtime["intent_batches"]]},
    )
    return files


def _run_launcher(
    *,
    manifest_path: Path,
    output_root: Path,
    validate_only: bool,
    adjudicator_provider_override: str = "",
    flex_api_url_override: str = "",
    model_override: str = "",
) -> Path:
    runtime = _build_runtime_from_manifest(
        manifest_path,
        adjudicator_provider_override=adjudicator_provider_override,
        flex_api_url_override=flex_api_url_override,
        model_override=model_override,
    )
    run_id = _now_run_id()
    run_dir = output_root / run_id
    files = _write_runtime_bundle(
        run_dir=run_dir,
        runtime=runtime,
        validate_only=validate_only,
    )
    if validate_only:
        dump_json(
            run_dir / "validation.json",
            {
                "status": "ok",
                "message": "Scenario Manifest loaded, mounted, and compiled",
                "scenario": runtime["manifest"].scenario_meta.model_dump(),
                "provider_route": runtime["provider_route"],
                "intent_batch_count": len(runtime["intent_batches"]),
            },
        )
        print(f"[VALIDATE-ONLY] ok run_dir={run_dir}")
        return run_dir

    agent_state = runtime["agent_state"]
    world_rules = runtime["world_rules"]
    timeline_path = run_dir / "timeline.jsonl"
    timestep_files: list[dict[str, str]] = []
    backend_counts: dict[str, int] = {}
    diagnostics: dict[str, Any] = {"timesteps": []}
    tick_rate_ms = runtime["manifest"].engine_config.simulation_params.tick_rate_ms

    with timeline_path.open("w", encoding="utf-8") as timeline_handle:
        for batch_index, intent_batch in enumerate(runtime["intent_batches"], start=1):
            if batch_index > 1 and tick_rate_ms > 0:
                time.sleep(tick_rate_ms / 1000.0)
            step_dir = run_dir / f"timestep_{intent_batch.timestep_index:03d}"
            step_dir.mkdir(parents=True, exist_ok=True)
            try:
                output, agent_state, world_rules, step_diagnostics, backend = _run_adjudicator_timestep(
                    control=runtime["control"],
                    rendered_prompt=runtime["rendered_prompt"],
                    world_rules=world_rules,
                    agent_state=agent_state,
                    intent_batch=intent_batch,
                )
            except Exception as exc:
                step_diagnostics = (
                    exc.diagnostics
                    if isinstance(exc, ScenarioTimestepError)
                    else {"status": "failed", "error": str(exc)}
                )
                failure_path = step_dir / "failure.json"
                step_manifest_path = step_dir / "step_manifest.json"
                backend = runtime["control"].adjudication_backend
                failure_payload = {
                    "status": "failed",
                    "timestep_index": intent_batch.timestep_index,
                    "backend": backend,
                    "error": str(exc),
                    "diagnostics": step_diagnostics,
                }
                dump_json(failure_path, failure_payload)
                step_manifest = {
                    "status": "failed",
                    "timestep_index": intent_batch.timestep_index,
                    "backend": backend,
                    "action_count": len(intent_batch.intents),
                    "rule_appendix_count": 0,
                    "files": {"failure": str(failure_path)},
                    "diagnostics": step_diagnostics,
                }
                dump_json(step_manifest_path, step_manifest)
                timeline_handle.write(json.dumps(step_manifest, ensure_ascii=False) + "\n")
                timestep_files.append({"step_manifest": str(step_manifest_path), **step_manifest["files"]})
                diagnostics["timesteps"].append(step_manifest)

                final_state_path = run_dir / "final_agent_profiles.json"
                final_rules_path = run_dir / "final_world_rules.json"
                dump_json(final_state_path, agent_state.model_dump())
                dump_json(final_rules_path, world_rules.model_dump())
                final_manifest = {
                    "status": "failed",
                    "run_id": run_id,
                    "scenario_meta": runtime["manifest"].scenario_meta.model_dump(),
                    "world_mode": world_rules.world_mode,
                    "provider_route": runtime["provider_route"],
                    "backend_counts": backend_counts,
                    "timestep_count": batch_index - 1,
                    "files": {
                        **files,
                        "timeline": str(timeline_path),
                        "final_agent_profiles": str(final_state_path),
                        "final_world_rules": str(final_rules_path),
                        "failure": str(failure_path),
                    },
                    "timestep_files": timestep_files,
                    "diagnostics": diagnostics,
                }
                dump_json(run_dir / "final_manifest.json", final_manifest)
                raise
            backend_counts[backend] = backend_counts.get(backend, 0) + 1
            output_path = step_dir / "adjudicator_output.json"
            state_path = step_dir / "updated_agent_profiles.json"
            rules_path = step_dir / "updated_world_rules.json"
            step_manifest_path = step_dir / "step_manifest.json"
            dump_json(output_path, output)
            dump_json(state_path, agent_state.model_dump())
            dump_json(rules_path, world_rules.model_dump())
            step_manifest = {
                "timestep_index": intent_batch.timestep_index,
                "backend": backend,
                "action_count": len(intent_batch.intents),
                "rule_appendix_count": len(output.get("Rule_Appendices", [])),
                "files": {
                    "adjudicator_output": str(output_path),
                    "updated_agent_profiles": str(state_path),
                    "updated_world_rules": str(rules_path),
                },
                "diagnostics": step_diagnostics,
            }
            dump_json(step_manifest_path, step_manifest)
            timeline_handle.write(json.dumps(step_manifest, ensure_ascii=False) + "\n")
            timestep_files.append({"step_manifest": str(step_manifest_path), **step_manifest["files"]})
            diagnostics["timesteps"].append(step_manifest)

    final_state_path = run_dir / "final_agent_profiles.json"
    final_rules_path = run_dir / "final_world_rules.json"
    dump_json(final_state_path, agent_state.model_dump())
    dump_json(final_rules_path, world_rules.model_dump())
    final_manifest = {
        "run_id": run_id,
        "scenario_meta": runtime["manifest"].scenario_meta.model_dump(),
        "world_mode": world_rules.world_mode,
        "provider_route": runtime["provider_route"],
        "backend_counts": backend_counts,
        "timestep_count": len(runtime["intent_batches"]),
        "files": {
            **files,
            "timeline": str(timeline_path),
            "final_agent_profiles": str(final_state_path),
            "final_world_rules": str(final_rules_path),
        },
        "timestep_files": timestep_files,
        "diagnostics": diagnostics,
    }
    dump_json(run_dir / "final_manifest.json", final_manifest)
    print(f"[DONE] run_dir={run_dir}")
    return run_dir


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan and launch Agora-mini Scenario Manifest packages."
    )
    parser.add_argument("--scenarios-dir", type=Path, default=DEFAULT_SCENARIOS_DIR)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--scenario", type=str, default="")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--list-scenarios", action="store_true")
    parser.add_argument("--validate-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--adjudicator-provider-override",
        choices=sorted(PROVIDER_SERVER_SCRIPTS.keys()) + ["Local"],
        default="",
        help="Override manifest engine_config.adjudicator_api.provider.",
    )
    parser.add_argument(
        "--flex-api-url-override",
        type=str,
        default="",
        help="Override manifest adjudicator Flex API URL without editing the scenario package.",
    )
    parser.add_argument(
        "--model-override",
        type=str,
        default="",
        help="Override manifest adjudicator model without editing the scenario package.",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    scenarios_dir = _resolve_path(args.scenarios_dir)
    output_root = _resolve_path(args.output_dir)

    if args.list_scenarios:
        manifests = _scan_manifests(scenarios_dir)
        if not manifests:
            print(f"[System] No scenarios found under {scenarios_dir}")
            return
        for index, manifest_path in enumerate(manifests, start=1):
            print(f"{index}: {_scenario_label(manifest_path, _load_manifest(manifest_path))}")
        return

    manifest_path = _select_manifest(
        scenarios_dir=scenarios_dir,
        manifest_path=args.manifest,
        scenario_selector=args.scenario,
    )
    _run_launcher(
        manifest_path=manifest_path,
        output_root=output_root,
        validate_only=args.validate_only,
        adjudicator_provider_override=args.adjudicator_provider_override,
        flex_api_url_override=args.flex_api_url_override,
        model_override=args.model_override,
    )


if __name__ == "__main__":
    main()
