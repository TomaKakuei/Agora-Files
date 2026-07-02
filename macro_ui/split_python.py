import re

with open('build_macro_ui.py', 'r') as f:
    lines = f.readlines()

def get_method_boundaries():
    boundaries = {}
    current_method = None
    start_line = 0
    
    for i, line in enumerate(lines):
        match = re.match(r'^def ([a-zA-Z0-9_]+)\(', line)
        if match:
            if current_method:
                boundaries[current_method] = (start_line, i - 1)
            current_method = match.group(1)
            start_line = i
            
    if current_method:
        boundaries[current_method] = (start_line, len(lines) - 1)
        
    return boundaries

boundaries = get_method_boundaries()

def extract_methods(method_names):
    extracted = []
    for name in method_names:
        if name in boundaries:
            start, end = boundaries[name]
            # Include decorators if present
            while start > 0 and lines[start-1].startswith('@'):
                start -= 1
            extracted.extend(lines[start:end+1])
    return extracted

package_methods = [
    'export_world_package_from_config', 'load_world_config_from_access_code', 'generalized_world_config_template', 
    '_resolve_run_config_path', '_resolve_scenario_dir', '_room_prompt', '_agent_prompt', '_item_prompt', 
    '_agent_statuses', '_inventory_payload', '_currency_amount', '_agent_payload', '_room_capacity_payload', 
    '_social_groups_payload', '_relationship_edges', '_agent_id_number', '_neutral_relationship_tensor', 
    '_load_agents_from_scenario', '_load_cached_runtime_agents', '_fallback_map_grid', '_state_by_round', 
    '_timeline_by_round', '_completed_rounds', '_run_process_payload', '_systemd_unit_property', '_run_status', 
    'discover_runs', 'current_run_record', '_asset_worker_payload', 'asset_worker_status', 'launch_asset_bundle_worker'
]

asset_methods = [
    '_image_client_for_config', '_ensure_room_images', '_ensure_agent_images', '_collect_item_image_specs', 
    '_ensure_item_images', '_prepare_media_jobs', '_room_frame_payload', '_room_cell_bounds', '_frame_agents_payload',
    '_image_request_spacing_seconds', '_character_portraits_enabled', '_item_image_mode', '_item_is_important_artifact'
]

imports = [line for line in lines if line.startswith('import ') or line.startswith('from ')]

with open('build_macro_ui_package.py', 'w') as f:
    f.writelines(imports)
    f.write('\n\n')
    f.writelines(extract_methods(package_methods))

with open('build_macro_ui_assets.py', 'w') as f:
    f.writelines(imports)
    f.write('\n\n')
    f.writelines(extract_methods(asset_methods))

# Main gets the rest
main_lines = []
for i, line in enumerate(lines):
    in_extracted = False
    for name in package_methods + asset_methods:
        if name in boundaries:
            start, end = boundaries[name]
            if start <= i <= end:
                in_extracted = True
                break
    if not in_extracted:
        main_lines.append(line)

# Let's add the imports back to the main file just in case they were stripped by something, but they weren't stripped above
with open('build_macro_ui.py', 'w') as f:
    f.writelines(main_lines)

print(f"Created build_macro_ui_package.py and build_macro_ui_assets.py, and updated build_macro_ui.py")
