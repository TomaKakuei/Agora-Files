from __future__ import annotations
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from agora_ui.boundary_schemas import AssetBundleSpec, AssetEventSpec, PromptBundleSpec
from agora_ui.scenario_schemas import ScenarioMapGridSpec, ScenarioManifestSpec
from asset_pipeline.process_sprite import AnimationState, DEFAULT_ANIMATION_STATES

from .clients import (
    _is_local_sprite_adapter, 
    _normalize_world_config_models, 
    _remote_backend_label, 
    _request_sprite_summary, 
    _run_prompt_reference_generation, 
    _run_remote_generation_attempt, 
    _sprite_generation_adapter
)
from asset_pipeline.sprite_qa_programmatic import final_atlas_transparency_qa
from .compositor import (
    _build_ai_studio_retry_pipeline_config, 
    _build_ai_studio_retry_world_config, 
    _build_atlas_outputs, 
    _load_room_lookup, 
    _normalize_remote_raw_sheet, 
    _publishable_generated_asset, 
    _quality_report_from_atlas_failure, 
    _read_json, 
    _relative_url, 
    _reuse_latest_raw_sheet, 
    _write_event_feeds, 
    _write_frontend_manifest, 
    _write_json, 
    _write_raw_sheet_qa_report
)
from .prompts import _build_prompt_bundle
from .schemas import PipelinePaths

def _locate_package_root(config_path: Path) -> Path:
    current = config_path.resolve()
    for candidate in [current] + list(current.parents):
        if (candidate / 'agora_ui').is_dir() and (candidate / 'asset_pipeline').is_dir():
            return candidate
    raise RuntimeError(f"Could not locate Agora_UI package root from config path: {config_path}")

def _load_agent_profile(scenario_dir: Path, agent_id: str):
    agent_path = scenario_dir / 'Agents' / f"{agent_id}.json"
    if not agent_path.exists():
        raise FileNotFoundError(f"Agent profile not found: {agent_path}")
    return _read_json(agent_path)

def parse_args(args=None):
    parser = argparse.ArgumentParser(description='Build Phaser-ready agent sprite atlases.')
    parser.add_argument('--config', required=True, help='Path to world_config.json.')
    parser.add_argument('--scenario-dir', required=True, help='Path to the scenario directory.')
    parser.add_argument('--agent-id', required=True, help='Agent id to generate.')
    parser.add_argument('--raw-sheet', help='Optional pre-generated raw character sheet.')
    parser.add_argument('--output-root', default='frontend/assets/generated')
    parser.add_argument('--event-root', default='frontend/assets/generated/events')
    parser.add_argument('--revision', help='Optional asset revision label.')
    parser.add_argument('--world-revision', help='Optional provenance world revision to persist in asset bundles/events.')
    parser.add_argument('--invoke-remote', action='store_true', help='Call configured remote APIs when endpoints exist.')
    parser.add_argument('--bootstrap-procedural-sheet', action='store_true', help='Generate a local raw 128x128-per-frame sheet for pipeline validation.')
    parser.add_argument('--write-frontend-bootstrap', action='store_true', help='Refresh frontend/bootstrap_agents.json from the scenario manifest.')
    parser.add_argument('--reuse-latest-raw-sheet', action='store_true', help='Fall back to the newest existing raw sheet for this agent when remote generation is unavailable or unsuitable.')
    if args is None:
        return parser.parse_args()
    return parser.parse_args(args)

def run_pipeline(parsed_args):
    config_path = Path(parsed_args.config).resolve()
    scenario_dir = Path(parsed_args.scenario_dir).resolve()
    package_root = _locate_package_root(config_path)
    world_config = _normalize_world_config_models(_read_json(config_path))
    map_grid = ScenarioMapGridSpec.model_validate(_read_json(scenario_dir / 'map_grid.json')).model_dump()
    manifest = ScenarioManifestSpec.model_validate(_read_json(scenario_dir / 'manifest.json')).model_dump()
    agent_profile = _load_agent_profile(scenario_dir, parsed_args.agent_id)
    room = _load_room_lookup(map_grid).get(agent_profile.get('room_id', ''))
    
    pipeline_config = world_config.get('pixel_asset_pipeline', {})
    if not pipeline_config:
        raise KeyError('world_config.json does not contain pixel_asset_pipeline.')
        
    output_root = (package_root / parsed_args.output_root).resolve()
    event_root = (package_root / parsed_args.event_root).resolve()
    
    revision = parsed_args.revision or datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    world_revision = parsed_args.world_revision or revision
    
    asset_dir = output_root / parsed_args.agent_id / revision
    asset_dir.mkdir(parents=True, exist_ok=True)
    
    paths = PipelinePaths(
        package_root=package_root,
        output_root=output_root,
        event_root=event_root,
        asset_dir=asset_dir,
        revision=revision
    )
    
    prompt_bundle = PromptBundleSpec.model_validate(_build_prompt_bundle(
        world_config=world_config,
        agent_profile=agent_profile,
        room=room,
        pipeline_config=pipeline_config,
        package_root=package_root
    )).model_dump()
    _write_json(asset_dir / 'prompt_bundle.json', prompt_bundle)
    
    sheet_layout = pipeline_config.get('sheet_layout', {})
    processing = pipeline_config.get('processing', {})
    animation_states = [AnimationState(**entry) for entry in sheet_layout.get("animation_states", DEFAULT_ANIMATION_STATES)]
    
    raw_sheet_path = asset_dir / 'raw_character_128.png'
    reference_image_path = asset_dir / 'reference_agent.png'
    
    concept_summary = {'status': 'not_requested'}
    reference_image_summary = {'status': 'not_requested'}
    sprite_summary = {'status': 'not_requested'}
    reused_raw_summary = {'status': 'not_used'}
    
    if parsed_args.raw_sheet:
        resolved_raw = Path(parsed_args.raw_sheet).resolve()
        raw_sheet_path.write_bytes(resolved_raw.read_bytes())
        sprite_summary = {'status': 'ok', 'source': str(resolved_raw)}
    elif parsed_args.reuse_latest_raw_sheet:
        try:
            reused_raw_summary = _reuse_latest_raw_sheet(package_root, parsed_args.agent_id, revision, raw_sheet_path)
            sprite_summary = reused_raw_summary
        except FileNotFoundError as e:
            print(f"CRITICAL: {e}", file=sys.stderr)
            sys.exit(1)
    elif parsed_args.invoke_remote:
        # Simplified remote generation loop without the procedural fallback!
        concept_summary, reference_image_summary, sprite_summary = _run_remote_generation_attempt(
            world_config=world_config,
            pipeline_config=pipeline_config,
            prompt_bundle=prompt_bundle,
            output_dir=asset_dir,
            raw_sheet_path=raw_sheet_path,
            reference_image_path=reference_image_path
        )
        
    # QA Check
    if raw_sheet_path.exists():
        qa_report = _write_raw_sheet_qa_report(
            raw_sheet_path=raw_sheet_path,
            sheet_layout=sheet_layout,
            processing=processing,
            animation_states=animation_states,
            output_path=asset_dir / "raw_sheet_quality_report.json"
        )
        if not qa_report.get("pass_qa", False):
            print(f"CRITICAL: QA Failed for {parsed_args.agent_id}. Halting pipeline! Error: {qa_report.get('failures')}", file=sys.stderr)
            sys.exit(1)
            
        atlas_outputs = _build_atlas_outputs(
            raw_sheet_path=raw_sheet_path,
            atlas_png=asset_dir / "character_atlas.png",
            atlas_json=asset_dir / "character_atlas.json",
            quality_report_path=asset_dir / "raw_sheet_quality_report.json",
            sheet_layout=sheet_layout,
            processing=processing,
            animation_states=animation_states
        )
        _write_asset_bundle_and_event(
            parsed_args=parsed_args,
            world_config=world_config,
            agent_profile=agent_profile,
            asset_dir=asset_dir,
            paths=paths,
            world_revision=world_revision,
            concept_summary=concept_summary,
            reference_image_summary=reference_image_summary,
            sprite_summary=sprite_summary,
            reused_raw_summary=reused_raw_summary,
            qa_report=qa_report,
            atlas_outputs=atlas_outputs,
            animation_states=animation_states,
            event_root=event_root,
            package_root=package_root,
            processing=processing
        )
        if parsed_args.write_frontend_bootstrap:
            _write_frontend_manifest(
                scenario_dir=scenario_dir,
                map_grid=map_grid,
                manifest=manifest,
                output_path=output_root / "bootstrap_agents.json",
                package_root=package_root
            )
    else:
        print(f"CRITICAL: raw_sheet_path {raw_sheet_path} does not exist after generation attempt!", file=sys.stderr)
        sys.exit(1)


from datetime import datetime, timezone

def _write_asset_bundle_and_event(
    parsed_args, world_config, agent_profile, asset_dir, paths, 
    world_revision, concept_summary, reference_image_summary, 
    sprite_summary, reused_raw_summary, qa_report, atlas_outputs,
    animation_states, event_root, package_root, processing
):
    from agora_ui.boundary_schemas import AssetBundleSpec, AssetEventSpec
    from asset_pipeline.agent_assets.compositor import _publishable_generated_asset, _write_json, _write_event_feeds
    
    atlas_png, atlas_json = atlas_outputs
    
    animations = {}
    default_anim = ""
    for state in animation_states:
        if not default_anim:
            default_anim = state.name
        is_static = state.static_frame_index is not None
        animations[state.name] = {
            "frames": [f"{state.name}_{i}.png" for i in range(state.frame_count)],
            "frameRate": state.frame_rate,
            "repeat": state.repeat,
            "static": is_static,
            "defaultFrame": f"{state.name}_0.png"
        }
    
    event = AssetEventSpec.model_validate({
        "event": "new_asset_ready",
        "id": parsed_args.agent_id,
        "display_name": agent_profile.get("display_name", parsed_args.agent_id),
        "atlas_url": f"./assets/generated/{parsed_args.agent_id}/{parsed_args.revision}/character_atlas.png",
        "json_url": f"./assets/generated/{parsed_args.agent_id}/{parsed_args.revision}/character_atlas.json",
        "revision": parsed_args.revision,
        "world_id": world_config.get("scenario_meta", {}).get("world_id", ""),
        "world_name": world_config.get("scenario_meta", {}).get("world_name", ""),
        "world_revision": world_revision,
        "default_animation": default_anim,
        "animations": animations,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }).model_dump()
    
    bundle = AssetBundleSpec.model_validate({
        "agent_id": parsed_args.agent_id,
        "revision": parsed_args.revision,
        "world_id": world_config.get("scenario_meta", {}).get("world_id", ""),
        "world_name": world_config.get("scenario_meta", {}).get("world_name", ""),
        "world_revision": world_revision,
        "concept_summary": concept_summary,
        "reference_image_summary": reference_image_summary,
        "sprite_summary": sprite_summary,
        "reused_raw_summary": reused_raw_summary,
        "atlas_png": str(asset_dir / "character_atlas.png"),
        "atlas_json": str(asset_dir / "character_atlas.json"),
        "quality_report_path": str(asset_dir / "raw_sheet_quality_report.json"),
        "raw_sheet_quality_report_path": str(asset_dir / "raw_sheet_quality_report.json"),
        "quality_summary": qa_report,
        "overall_status": "pass" if qa_report.get("pass_qa") else "failed",
        "event": event
    }).model_dump()
    
    _write_json(asset_dir / "asset_bundle.json", bundle)
    
    transparency_report = final_atlas_transparency_qa(
        image_path=str(asset_dir / "character_atlas.png"),
        processing=processing
    )

    is_publishable = _publishable_generated_asset(
        sprite_summary=sprite_summary,
        reused_raw_summary=reused_raw_summary,
        overall_status=bundle["overall_status"],
        atlas_transparency_check=transparency_report,
        raw_sheet_supplied=bool(parsed_args.raw_sheet)
    )
    
    if is_publishable:
        _write_event_feeds(paths, event)

def main():
    args = parse_args()
    run_pipeline(args)

if __name__ == '__main__':
    main()

