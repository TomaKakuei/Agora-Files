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
    source_file = base_dir / "memory.py"
    source_code = source_file.read_text()
    
    # Extract Compression/Sanitization
    compression_funcs = [
        "_limit_text", "_sanitize_recent_entry", "_sanitize_long_task", 
        "_sanitize_visual_artifact", "_sanitize_textual_artifact", 
        "_compress_image_for_reasoning", "_archive_recent_entry"
    ]
    compression_code, source_code = extract_functions(source_code, compression_funcs)
    
    common_imports = "from __future__ import annotations\nimport base64\nimport json\nimport re\nimport subprocess\nimport time\nimport uuid\nfrom collections import defaultdict, deque\nfrom pathlib import Path\nfrom typing import Any\nfrom ..adjudicator_schemas import AgentRuntimeProfileSpec\n"
    
    (base_dir / "memory_compression.py").write_text(common_imports + "\n" + compression_code)
    
    # Add imports to top of memory.py
    import_inject = (
        "from .memory_compression import *\n"
    )
    
    parts = source_code.split("\n\n\n", 1)
    if len(parts) == 2:
        new_source = parts[0] + "\n" + import_inject + "\n\n\n" + parts[1]
    else:
        new_source = import_inject + "\n" + source_code
        
    source_file.write_text(new_source)
    print("Extraction complete for memory.py!")

if __name__ == "__main__":
    main()
