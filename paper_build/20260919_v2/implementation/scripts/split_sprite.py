import sys
import re

with open("asset_pipeline/process_sprite.py", "r") as f:
    lines = f.readlines()

def get_indent(line):
    return len(line) - len(line.lstrip())

functions_to_move = [
    "_load_animation_states", "_strip_near_white_background", "_clear_exposed_near_white_pixels", 
    "_quantize_frame", "_frame_name", "_bbox_to_payload", "_mask_bbox", "_pad_image_to_aspect_ratio",
    "_alignment_policy", "_expand_box", "_bbox_area", "_intersection_area", "_touches_search_edge",
    "_component_sort_key", "_connected_components_numpy", "_connected_components_with_fallback",
    "_select_primary_component", "_extract_component_mask", "_expand_search_window_until_stable",
    "_frame_anchor_metrics", "_shared_scale_factor_from_extractions", "_render_component_to_target_frame",
    "_animation_frame_indices", "_resolved_animation_frame_indices", "_state_quality_report"
]

out_lines = []
utils_lines = []

in_func = False
current_func = ""

for line in lines:
    if line.startswith("def "):
        m = re.match(r"^def (\w+)", line)
        if m:
            current_func = m.group(1)
            if current_func in functions_to_move:
                in_func = True
            else:
                in_func = False
    elif in_func and line.strip() != "" and get_indent(line) == 0:
        in_func = False

    if in_func:
        utils_lines.append(line)
    else:
        out_lines.append(line)

with open("asset_pipeline/sprite_utils.py", "w") as f:
    f.write("from __future__ import annotations\nimport math\nfrom pathlib import Path\nfrom typing import Any, NamedTuple\nfrom PIL import Image, ImageDraw, ImageFilter\nimport numpy as np\n")
    f.write("class AnimationState(NamedTuple):\n    name: str\n    row_index: int\n    frames: int\n    repeat: int\n    frame_rate: int\n\n")
    f.writelines(utils_lines)

# Now add imports to process_sprite
imports = "\nfrom .sprite_utils import " + ", ".join(functions_to_move) + "\n"
for i, line in enumerate(out_lines):
    if "from PIL import" in line:
        out_lines.insert(i+1, imports)
        break

with open("asset_pipeline/process_sprite.py", "w") as f:
    f.writelines(out_lines)

print("Done splitting process_sprite.py")
