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
    source_file = base_dir / "generation.py"
    source_code = source_file.read_text()
    
    # 1. Schemas
    schema_funcs = [
        "_builder_spec_schema", "_world_config_critique_schema"
    ]
    schema_code, source_code = extract_functions(source_code, schema_funcs)
    
    # 2. Prompts
    prompt_funcs = [
        "_render_builder_prompt", "_world_config_critique_prompt", "_world_summary_prompt"
    ]
    prompt_code, source_code = extract_functions(source_code, prompt_funcs)
    
    # 3. Critique Loops & Fallbacks
    critique_funcs = [
        "_focus_profile", "_synthesized_gameplay_loops", "_fallback_conflict_hooks", 
        "_fallback_custom_actions", "_config_snapshot_for_critique", "_normalized_critique_dict", 
        "_critique_compiled_world_config", "_merge_gameplay_loops", 
        "_apply_compiler_critique_to_builder_spec"
    ]
    critique_code, source_code = extract_functions(source_code, critique_funcs)
    
    common_imports = "from __future__ import annotations\nimport json\nimport time\nimport traceback\nfrom typing import Any\nfrom agora_ui.vertex_json_client import VertexJsonClient\n"
    
    (base_dir / "generation_schemas.py").write_text(common_imports + "\n" + schema_code)
    
    prompt_imports = common_imports + "from .generation_schemas import *\n"
    (base_dir / "generation_prompts.py").write_text(prompt_imports + "\n" + prompt_code)
    
    critique_imports = common_imports + "from .generation_schemas import *\nfrom .generation_prompts import *\n"
    (base_dir / "critique_loop.py").write_text(critique_imports + "\n" + critique_code)
    
    # Add imports to top of generation.py
    import_inject = (
        "from .generation_schemas import *\n"
        "from .generation_prompts import *\n"
        "from .critique_loop import *\n"
    )
    
    parts = source_code.split("\n\n\n", 1)
    if len(parts) == 2:
        new_source = parts[0] + "\n" + import_inject + "\n\n\n" + parts[1]
    else:
        new_source = import_inject + "\n" + source_code
        
    source_file.write_text(new_source)
    print("Extraction complete for generation.py!")

if __name__ == "__main__":
    main()
