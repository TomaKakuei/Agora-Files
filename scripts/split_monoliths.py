import re
import os

def split_process_sprite():
    with open("asset_pipeline/process_sprite.py", "r") as f:
        lines = f.readlines()
        
    functions_to_move = [
        "_load_animation_states", "_strip_near_white_background", "_clear_exposed_near_white_pixels", 
        "_quantize_frame", "_frame_name", "_bbox_to_payload", "_mask_bbox", "_pad_image_to_aspect_ratio",
        "_alignment_policy", "_expand_box", "_bbox_area", "_intersection_area", "_touches_search_edge",
        "_component_sort_key", "_connected_components_numpy", "_connected_components_with_fallback",
        "_select_primary_component", "_extract_component_mask", "_expand_search_window_until_stable",
        "_frame_anchor_metrics", "_shared_scale_factor_from_extractions", "_render_component_to_target_frame",
        "_animation_frame_indices", "_resolved_animation_frame_indices", "_state_quality_report"
    ]
    
    utils_lines = []
    out_lines = []
    in_func = False
    brace_depth = 0
    paren_depth = 0
    
    for line in lines:
        if line.startswith("def "):
            m = re.match(r"^def ([a-zA-Z0-9_]+)", line)
            if m and m.group(1) in functions_to_move:
                in_func = True
            else:
                in_func = False
                
        if in_func:
            utils_lines.append(line)
        else:
            out_lines.append(line)
            
        # Detect end of function by checking if we're back to top level and not inside a docstring/tuple
        # Actually a simpler way is just to check indentation on non-empty lines IF we already passed the def header
        if in_func and line.strip() and not line.startswith("def "):
            if not line.startswith(" ") and not line.startswith("\t") and not line.startswith(")"):
                if not line.startswith("}") and not line.startswith("]"):
                    in_func = False
                    out_lines.append(line) # put the top-level line back
                    utils_lines.pop() # remove from utils

    with open("asset_pipeline/sprite_utils.py", "w") as f:
        f.write("from __future__ import annotations\nimport math\nfrom pathlib import Path\nfrom typing import Any, NamedTuple\nfrom PIL import Image, ImageDraw, ImageFilter\nimport numpy as np\n")
        f.write("class AnimationState(NamedTuple):\n    name: str\n    row_index: int\n    frames: int\n    repeat: int\n    frame_rate: int\n    static_frame_index: int | None = None\n\n")
        f.writelines(utils_lines)
        
    imports = "from .sprite_utils import " + ", ".join(functions_to_move) + "\n"
    for i, line in enumerate(out_lines):
        if "from PIL import" in line:
            out_lines.insert(i+1, imports)
            break
            
    with open("asset_pipeline/process_sprite.py", "w") as f:
        f.writelines(out_lines)

def split_testing_html():
    with open("macro_ui/routes/testing_html.py", "r") as f:
        lines = f.readlines()
        
    # We will just split it in half by moving some routes to a testing_html_extra.py
    # and importing them into testing.py where testing_html is imported.
    # For now we'll just extract the first 600 lines that aren't the router into testing_html_core.py
    print("testing_html splitting not implemented yet.")
        
if __name__ == "__main__":
    split_process_sprite()
    print("Done splitting process_sprite.py")
