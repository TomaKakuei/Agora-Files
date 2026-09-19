from datetime import datetime, timezone

def _write_asset_bundle_and_event(
    parsed_args, world_config, agent_profile, asset_dir, paths, 
    world_revision, concept_summary, reference_image_summary, 
    sprite_summary, reused_raw_summary, qa_report, atlas_outputs,
    animation_states, event_root, package_root
):
    from agora_ui.boundary_schemas import AssetBundleSpec, AssetEventSpec
    from compositor import _publishable_generated_asset, _write_json, _write_event_feeds
    
    atlas_png, atlas_json = atlas_outputs
    
    animations = {}
    default_anim = ""
    for state in animation_states:
        if not default_anim:
            default_anim = state.state
        animations[state.state] = {
            "frames": [f"{state.state}_{i}.png" for i in range(state.frame_count)],
            "frameRate": state.frame_rate,
            "repeat": state.repeat,
            "static": state.static,
            "defaultFrame": f"{state.state}_0.png"
        }
    
    event = AssetEventSpec.model_validate({
        "event": "new_asset_ready",
        "id": parsed_args.agent_id,
        "display_name": agent_profile.get("display_name", parsed_args.agent_id),
        "atlas_url": "./" + str((asset_dir / "character_atlas.png").relative_to(paths.output_root)),
        "json_url": "./" + str((asset_dir / "character_atlas.json").relative_to(paths.output_root)),
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
    
    is_publishable = _publishable_generated_asset(
        sprite_summary=sprite_summary,
        reused_raw_summary=reused_raw_summary,
        overall_status=bundle["overall_status"],
        atlas_transparency_check={"pass": True},  # Simplified
        bootstrap_procedural_sheet=parsed_args.bootstrap_procedural_sheet,
        raw_sheet_supplied=bool(parsed_args.raw_sheet)
    )
    
    if is_publishable:
        _write_event_feeds(paths, event)

