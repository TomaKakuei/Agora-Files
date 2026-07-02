import re
import os

with open("frontend/src/utils.js", "r") as f:
    utils_content = f.read()

exports = re.findall(r'export (?:const|function|async function) ([a-zA-Z0-9_]+)', utils_content)

for filename in os.listdir("frontend/src"):
    if not filename.endswith(".js") or filename == "utils.js":
        continue
    with open(f"frontend/src/{filename}", "r") as f:
        content = f.read()
    
    # Check what is currently imported
    import_match = re.search(r'import\s+\{([^}]+)\}\s+from\s+["\']\./utils\.js["\']', content)
    imported = set()
    if import_match:
        imported = {x.strip() for x in import_match.group(1).split(',')}
    
    missing = []
    for exp in exports:
        # Avoid matching substrings by using word boundaries
        if re.search(rf'\b{exp}\b', content) and exp not in imported:
            missing.append(exp)
    
    if missing:
        print(f"{filename} is missing imports: {missing}")
