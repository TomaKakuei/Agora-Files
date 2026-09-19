#!/usr/bin/env python3
"""Generate and compile unified agent profiles from JSONC workflow inputs."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from .flex_client import FlexClient
from .foundation_schemas import (
    AgentProfileCompileResult,
    AgentProfileSpec,
    AgentProfileWorkflow,
    AgentSeed,
    AgentSeedList,
    GeneratedAgentProfiles,
)
from .jsonc_utils import dump_json, dump_jsonc, load_jsonc_path


SCRIPT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE_DIR = SCRIPT_DIR / "data" / "templates" / "foundation"
DEFAULT_SEED_FILE = DEFAULT_TEMPLATE_DIR / "agent_seed_list.jsonc"
DEFAULT_WORKFLOW_FILE = DEFAULT_TEMPLATE_DIR / "agent_profile_workflow.jsonc"
DEFAULT_OUTPUT_ROOT = SCRIPT_DIR / "output" / "agent_profile_workflow"


def _resolve_path(path_like: Union[str, Path]) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path.resolve()
    local = (SCRIPT_DIR / path).resolve()
    if local.exists():
        return local
    return (Path.cwd() / path).resolve()


def _now_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _merge_unique_strings(*lists: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for items in lists:
        for raw in items:
            item = str(raw).strip()
            if not item or item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return merged


def _build_profile_schema_hint() -> dict[str, Any]:
    return {
        "profile_brief": "string",
        "core_values": ["string", "string", "string"],
        "gender_presentation": "string",
        "appearance_prompt": "string",
        "voice_style": "string",
        "stance": "string",
        "runtime_tags": ["string"],
        "attributes": {"attribute_name": 0},
    }


def _build_generation_prompt(seed: AgentSeed, workflow: AgentProfileWorkflow) -> str:
    return (
        "Generate a reusable agent profile preset.\n"
        f"agent_id: {seed.agent_id}\n"
        f"display_name: {seed.display_name}\n"
        f"reference_source: {seed.reference_source}\n"
        f"reference_profile: {seed.reference_profile}\n"
        f"seed_profile_brief: {seed.profile_brief}\n"
        f"seed_voice_style: {seed.voice_style}\n"
        f"seed_stance: {seed.stance}\n"
        f"seed_runtime_tags: {seed.runtime_tags}\n"
        f"seed_attributes: {seed.attributes}\n"
        f"seed_gender_presentation: {seed.gender_presentation}\n"
        f"seed_appearance_prompt: {seed.appearance_prompt}\n"
        f"default_core_values: {workflow.default_core_values}\n"
        f"default_attributes: {workflow.default_attributes}\n"
        f"default_runtime_tags: {workflow.default_runtime_tags}\n"
        f"default_voice_style: {workflow.default_voice_style}\n"
        f"default_stance: {workflow.default_stance}\n\n"
        "Return JSON only with these keys exactly:\n"
        "{"
        '"profile_brief": string, '
        '"core_values": string[], '
        '"gender_presentation": string, '
        '"appearance_prompt": string, '
        '"voice_style": string, '
        '"stance": string, '
        '"runtime_tags": string[], '
        '"attributes": object'
        "}\n"
        "Rules:\n"
        "- `profile_brief` must be concise but specific.\n"
        "- `core_values` should contain 3 to 6 items.\n"
        "- `attributes` values must be integers in 0..100.\n"
        "- `gender_presentation` should be concise, respectful, and coherent with the profile.\n"
        "- `appearance_prompt` must be a concrete video-generation character prompt: age range, ethnicity/race, background story location/environment, silhouette, attire (including important body accessories), colors, posture, and one or two distinctive details.\n"
        "- Make appearance and gender presentation fit the personality, role, and reference description without relying on stereotypes.\n"
        "- Prefer stable traits that are reusable across scenarios.\n"
        "- Do not include markdown fences or commentary.\n"
    )


def _compile_profile_from_seed(
    seed: AgentSeed,
    workflow: AgentProfileWorkflow,
    *,
    generated_payload: Optional[dict[str, Any]],
    generated_from: str,
) -> AgentProfileSpec:
    generated_payload = dict(generated_payload or {})
    core_values = _merge_unique_strings(
        list(generated_payload.get("core_values", []) or []),
        seed.user_core_values,
        workflow.default_core_values,
    )
    attributes = dict(workflow.default_attributes)
    attributes.update(seed.attributes)
    for key, raw in dict(generated_payload.get("attributes", {}) or {}).items():
        attributes[str(key)] = int(raw)
    profile_brief = (
        str(generated_payload.get("profile_brief", "")).strip()
        or seed.profile_brief.strip()
        or seed.reference_profile.strip()
        or f"{seed.display_name} reusable runtime profile."
    )
    voice_style = (
        str(generated_payload.get("voice_style", "")).strip()
        or seed.voice_style.strip()
        or workflow.default_voice_style.strip()
    )
    gender_presentation = (
        str(generated_payload.get("gender_presentation", "")).strip()
        or seed.gender_presentation.strip()
    )
    appearance_prompt = (
        str(generated_payload.get("appearance_prompt", "")).strip()
        or seed.appearance_prompt.strip()
    )
    stance = (
        str(generated_payload.get("stance", "")).strip()
        or seed.stance.strip()
        or workflow.default_stance.strip()
    )
    runtime_tags = _merge_unique_strings(
        workflow.default_runtime_tags,
        seed.runtime_tags,
        list(generated_payload.get("runtime_tags", []) or []),
    )
    return AgentProfileSpec(
        agent_id=seed.agent_id,
        display_name=seed.display_name,
        reference_source=seed.reference_source,
        reference_profile=seed.reference_profile,
        profile_brief=profile_brief,
        core_values=core_values,
        attributes=attributes,
        gender_presentation=gender_presentation,
        appearance_prompt=appearance_prompt,
        voice_style=voice_style,
        stance=stance,
        runtime_tags=runtime_tags,
        generated_from=generated_from,
    )


def _generate_profile_payload(
    client: FlexClient,
    seed: AgentSeed,
    workflow: AgentProfileWorkflow,
) -> dict[str, Any]:
    return client.generate_json(
        prompt=_build_generation_prompt(seed, workflow),
        system_instruction=(
            "You are a strict JSON generator for reusable multi-agent runtime presets. "
            "Return JSON only and keep field names exactly as requested."
        ),
        model=workflow.model or None,
        temperature=0.25,
        max_output_tokens=900,
        thinking_level="medium",
        response_schema=_build_profile_schema_hint(),
        timeout_seconds=120.0,
    )


def _build_profile(
    client: Optional[FlexClient],
    seed: AgentSeed,
    workflow: AgentProfileWorkflow,
    *,
    generation_log: list[dict[str, Any]],
) -> AgentProfileSpec:
    if seed.user_core_values:
        profile = _compile_profile_from_seed(
            seed,
            workflow,
            generated_payload={},
            generated_from="seed_user",
        )
        generation_log.append(
            {
                "agent_id": seed.agent_id,
                "mode": "seed_user",
                "status": "ok",
                "used_api": False,
            }
        )
        return profile

    if seed.generation_mode == "user":
        profile = _compile_profile_from_seed(
            seed,
            workflow,
            generated_payload={},
            generated_from="workflow_default",
        )
        generation_log.append(
            {
                "agent_id": seed.agent_id,
                "mode": "workflow_default",
                "status": "ok",
                "used_api": False,
            }
        )
        return profile

    if client is None:
        raise RuntimeError(
            f"agent {seed.agent_id} requires API generation but no Flex client is available"
        )

    last_error = "unknown error"
    for attempt in range(1, workflow.max_retries + 1):
        try:
            generated = _generate_profile_payload(client, seed, workflow)
            profile = _compile_profile_from_seed(
                seed,
                workflow,
                generated_payload=generated,
                generated_from="seed_auto",
            )
            generation_log.append(
                {
                    "agent_id": seed.agent_id,
                    "mode": "seed_auto",
                    "status": "ok",
                    "attempt": attempt,
                    "used_api": True,
                }
            )
            return profile
        except Exception as exc:
            last_error = str(exc)
            generation_log.append(
                {
                    "agent_id": seed.agent_id,
                    "mode": "seed_auto",
                    "status": "retry_error",
                    "attempt": attempt,
                    "used_api": True,
                    "error": last_error,
                }
            )

    generation_log.append(
        {
            "agent_id": seed.agent_id,
            "mode": "seed_auto",
            "status": "failed",
            "used_api": True,
            "error": last_error,
        }
    )

    raise RuntimeError(f"failed to build profile for {seed.agent_id}: {last_error}")


def _load_seed_list(path: Path) -> AgentSeedList:
    payload = load_jsonc_path(path)
    return AgentSeedList.model_validate(payload)


def _load_workflow(path: Path) -> AgentProfileWorkflow:
    payload = load_jsonc_path(path)
    return AgentProfileWorkflow.model_validate(payload)


def _load_generated_profiles(path: Path) -> GeneratedAgentProfiles:
    payload = load_jsonc_path(path)
    return GeneratedAgentProfiles.model_validate(payload)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the unified agent profile workflow using JSONC inputs."
    )
    parser.add_argument("--seed-file", type=Path, default=DEFAULT_SEED_FILE)
    parser.add_argument("--workflow-file", type=Path, default=DEFAULT_WORKFLOW_FILE)
    parser.add_argument("--generated-profiles-file", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--flex-api-url",
        type=str,
        default="",
        help="Optional runtime override for workflow.flex_api_url.",
    )
    parser.add_argument(
        "--model-override",
        type=str,
        default="",
        help="Optional runtime override for workflow.model.",
    )
    parser.add_argument(
        "--compile-only",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Compile an existing generated profiles JSONC file instead of calling the API.",
    )
    parser.add_argument(
        "--validate-only",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Validate the workflow inputs and write validation artifacts only.",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()

    seed_path = _resolve_path(args.seed_file)
    workflow_path = _resolve_path(args.workflow_file)
    workflow = _load_workflow(workflow_path)
    if str(args.flex_api_url).strip():
        workflow.flex_api_url = str(args.flex_api_url).strip()
    if str(args.model_override).strip():
        workflow.model = str(args.model_override).strip()
    seed_list = _load_seed_list(seed_path)

    run_id = _now_run_id()
    output_root_input = (
        Path(workflow.output_subdir)
        if Path(args.output_dir) == DEFAULT_OUTPUT_ROOT
        else Path(args.output_dir)
    )
    output_root = _resolve_path(output_root_input)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    config_payload = {
        "run_id": run_id,
        "created_at": _now_iso(),
        "paths": {
            "seed_file": str(seed_path),
            "workflow_file": str(workflow_path),
            "generated_profiles_file": str(_resolve_path(args.generated_profiles_file))
            if args.generated_profiles_file is not None
            else "",
        },
        "compile_only": bool(args.compile_only),
        "validate_only": bool(args.validate_only),
        "workflow": workflow.model_dump(),
        "seed_count": len(seed_list.agents),
    }
    dump_json(run_dir / "config.json", config_payload)

    if args.validate_only:
        dump_json(
            run_dir / "validation.json",
            {
                "status": "ok",
                "message": "agent profile workflow inputs validated",
            },
        )
        print(f"[VALIDATE-ONLY] ok run_dir={run_dir}")
        return

    generated_profiles_file = (
        _resolve_path(args.generated_profiles_file)
        if args.generated_profiles_file is not None
        else None
    )

    generation_log: list[dict[str, Any]] = []
    if args.compile_only:
        if generated_profiles_file is None:
            raise RuntimeError("--compile-only requires --generated-profiles-file")
        generated_profiles = _load_generated_profiles(generated_profiles_file)
        profiles = generated_profiles.profiles
        generation_log.append(
            {
                "mode": "compile_only",
                "status": "ok",
                "generated_profiles_file": str(generated_profiles_file),
            }
        )
        generated_at = generated_profiles.generated_at
    else:
        client = FlexClient(api_url=workflow.flex_api_url)
        try:
            profiles = [
                _build_profile(client, seed, workflow, generation_log=generation_log)
                for seed in seed_list.agents
            ]
        except Exception as exc:
            dump_json(run_dir / "generation_log.json", {"events": generation_log})
            dump_json(
                run_dir / "failure.json",
                {
                    "status": "failed",
                    "stage": "profile_generation",
                    "error": str(exc),
                    "events": generation_log,
                },
            )
            raise
        generated_at = _now_iso()
        generated_payload = GeneratedAgentProfiles(
            workflow_name=workflow.workflow_name,
            generated_at=generated_at,
            profiles=profiles,
        )
        dump_jsonc(
            run_dir / workflow.generated_profile_filename,
            generated_payload.model_dump(),
            comment_lines=[
                "Generated agent profiles. You may edit this JSONC file by hand and rerun with --compile-only.",
                "已生成的 Agent Profile JSONC，可手动修改后再用 --compile-only 重新编译。",
            ],
        )

    compiled = AgentProfileCompileResult(
        workflow_name=workflow.workflow_name,
        generated_at=generated_at,
        profile_count=len(profiles),
        profiles=profiles,
        diagnostics={
            "seed_file": str(seed_path),
            "workflow_file": str(workflow_path),
            "compile_only": bool(args.compile_only),
        },
    )
    dump_json(run_dir / workflow.compiled_profile_filename, compiled.model_dump())
    dump_json(run_dir / "generation_log.json", {"events": generation_log})
    print(f"[DONE] run_dir={run_dir}")


if __name__ == "__main__":
    main()
