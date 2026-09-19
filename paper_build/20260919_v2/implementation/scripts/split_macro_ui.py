import re
from pathlib import Path

def extract_functions(source: str, function_names: list[str]) -> tuple[str, str]:
    """Extract full function blocks from source, returning (extracted_code, remaining_source)."""
    lines = source.split("\n")
    extracted = []
    remaining = []
    
    in_target_func = False
    current_func_indent = 0
    
    for line in lines:
        match = re.match(r'^(\s*)def\s+([a-zA-Z0-9_]+)\(', line)
        if match:
            indent = len(match.group(1))
            name = match.group(2)
            if name in function_names and indent == 0:
                in_target_func = True
                current_func_indent = indent
                extracted.append(line)
                continue
            elif in_target_func and indent == 0:
                in_target_func = False
        
        # Match class defs too just in case
        class_match = re.match(r'^(\s*)class\s+([a-zA-Z0-9_]+)', line)
        if class_match:
            indent = len(class_match.group(1))
            name = class_match.group(2)
            if name in function_names and indent == 0:
                in_target_func = True
                current_func_indent = indent
                extracted.append(line)
                continue
            elif in_target_func and indent == 0:
                in_target_func = False

        if in_target_func:
            extracted.append(line)
        else:
            remaining.append(line)
            
    return "\n".join(extracted), "\n".join(remaining)

def main():
    base_dir = Path(__file__).resolve().parent.parent
    source_file = base_dir / "build_macro_ui.py"
    source_code = source_file.read_text()
    
    # 1. Extract payload formatters
    payload_funcs = [
        "_room_prompt", "_agent_prompt", "_item_prompt", "_agent_statuses", 
        "_inventory_payload", "_currency_amount", "_agent_payload", 
        "_room_capacity_payload", "_social_groups_payload", "_relationship_edges", 
        "_agent_id_number", "_neutral_relationship_tensor", "_fallback_map_grid"
    ]
    payload_code, source_code = extract_functions(source_code, payload_funcs)
    
    # 2. Extract process manager
    process_funcs = [
        "_run_process_payload", "_systemd_unit_property", "_run_status", 
        "discover_runs", "current_run_record", "_asset_worker_payload", 
        "asset_worker_status", "launch_asset_bundle_worker", "launch_run_subprocess",
        "_pid_alive"
    ]
    process_code, source_code = extract_functions(source_code, process_funcs)
    
    # 3. Extract image generation
    image_funcs = [
        "_image_client_for_config", "_ensure_room_images", "_ensure_agent_images",
        "_collect_item_image_specs", "_ensure_item_images", "_prepare_media_jobs",
        "_room_frame_payload", "_room_cell_bounds", "_frame_agents_payload",
        "_image_request_spacing_seconds", "_character_portraits_enabled",
        "_item_image_mode", "_item_is_important_artifact", "VertexInlineImageClient"
    ]
    image_code, source_code = extract_functions(source_code, image_funcs)
    
    # Add imports to new files
    common_imports = "from __future__ import annotations\nimport os\nimport sys\nimport time\nimport json\nimport subprocess\nfrom pathlib import Path\nfrom typing import Any\nfrom agora_ui.adjudicator_schemas import ScenarioMapGridSpec\nfrom .components.html_utils import _resolve_asset_path, _static_url_if_local\n"
    
    (base_dir / "payload_formatters.py").write_text(common_imports + "\n" + payload_code)
    (base_dir / "process_manager.py").write_text(common_imports + "\n" + process_code)
    (base_dir / "image_generation.py").write_text(common_imports + "\n" + image_code)
    
    # Add imports to top of build_macro_ui.py
    import_inject = (
        "from .payload_formatters import *\n"
        "from .process_manager import *\n"
        "from .image_generation import *\n"
    )
    
    # Find where to inject (after the existing imports)
    parts = source_code.split("\n\n\n", 1)
    if len(parts) == 2:
        new_source = parts[0] + "\n" + import_inject + "\n\n\n" + parts[1]
    else:
        new_source = import_inject + "\n" + source_code
        
    source_file.write_text(new_source)
    print("Extraction complete!")

if __name__ == "__main__":
    main()
