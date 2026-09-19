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
    source_file = base_dir / "testing.py"
    source_code = source_file.read_text()
    
    html_funcs = [
        "_render_headless_pixel_harness", 
        "_render_pixel_live_snapshot", 
        "_render_phaser_minimal_harness"
    ]
    html_code, source_code = extract_functions(source_code, html_funcs)
    
    common_imports = "from __future__ import annotations\n"
    
    (base_dir / "testing_html.py").write_text(common_imports + "\n" + html_code)
    
    # Add imports to top of testing.py
    import_inject = (
        "from .testing_html import *\n"
    )
    
    parts = source_code.split("\n\n\n", 1)
    if len(parts) == 2:
        new_source = parts[0] + "\n" + import_inject + "\n\n\n" + parts[1]
    else:
        new_source = import_inject + "\n" + source_code
        
    source_file.write_text(new_source)
    print("Extraction complete for testing.py!")

if __name__ == "__main__":
    main()
