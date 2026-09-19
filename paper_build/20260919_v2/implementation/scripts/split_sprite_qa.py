import re
from pathlib import Path

def extract_functions(source: str, function_names: list[str]) -> tuple[str, str]:
    lines = source.split("\n")
    extracted = []
    remaining = []
    in_target_func = False
    
    for line in lines:
        match = re.match(r'^(\s*)def\s+([a-zA-Z0-9_]+)\(', line)
        if match:
            indent = len(match.group(1))
            name = match.group(2)
            if name in function_names and indent == 0:
                in_target_func = True
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
    source_file = base_dir / "sprite_qa.py"
    source_code = source_file.read_text()
    
    # 1. Programmatic QA
    prog_funcs = [
        "_strip_near_white_background", "_preprocess_for_qa", "_mask_bbox", 
        "final_atlas_transparency_qa", "_bbox_to_payload", "_alpha_component_summary", 
        "_frame_anchor_metrics", "_frame_requirement", "_frame_label", 
        "strict_programmatic_qa"
    ]
    prog_code, source_code = extract_functions(source_code, prog_funcs)
    
    # 2. Vision QA
    vision_funcs = [
        "_qa_label_passes", "_vision_structural_pass", "_looks_like_black_background_false_negative", 
        "_looks_like_optional_accessory_consistency_false_negative", 
        "_looks_like_minor_edge_noise_consistency_false_negative", 
        "_path_to_inline_data", "_build_vision_preview", "_normalize_vision_result", 
        "_apply_vision_false_negative_override", "run_visual_qa"
    ]
    vision_code, source_code = extract_functions(source_code, vision_funcs)
    
    common_imports = "from __future__ import annotations\nimport base64\nimport json\nimport math\nfrom pathlib import Path\nfrom typing import Any\nfrom PIL import Image, ImageChops, ImageStat\nfrom agora_ui.vertex_json_client import VertexJsonClient\nfrom .agent_assets.core import AnimationState\n"
    
    (base_dir / "sprite_qa_programmatic.py").write_text(common_imports + "\n" + prog_code)
    (base_dir / "sprite_qa_vision.py").write_text(common_imports + "\n" + vision_code)
    
    # Add imports to top of sprite_qa.py
    import_inject = (
        "from .sprite_qa_programmatic import *\n"
        "from .sprite_qa_vision import *\n"
    )
    
    parts = source_code.split("\n\n\n", 1)
    if len(parts) == 2:
        new_source = parts[0] + "\n" + import_inject + "\n\n\n" + parts[1]
    else:
        new_source = import_inject + "\n" + source_code
        
    source_file.write_text(new_source)
    print("Extraction complete for sprite_qa.py!")

if __name__ == "__main__":
    main()
