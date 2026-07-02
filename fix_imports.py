import re
import os
import glob

# Get all exports from utils.js
with open('frontend/src/utils.js', 'r') as f:
    content = f.read()
    
exports = []
for line in content.split('\n'):
    if line.startswith('export const '):
        name = line.split('export const ')[1].split(' =')[0]
        exports.append(name)
    elif line.startswith('export function '):
        name = line.split('export function ')[1].split('(')[0]
        exports.append(name)
    elif line.startswith('export async function '):
        name = line.split('export async function ')[1].split('(')[0]
        exports.append(name)
        
print(f"Found {len(exports)} exports in utils.js")

# Find usages and add missing imports in each JS file
for filepath in glob.glob('frontend/src/*.js'):
    if filepath.endswith('utils.js') or filepath.endswith('main.js') or filepath.endswith('AgentManager.js'):
        continue
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    used_exports = []
    for exp in exports:
        # Check if the word exists as a whole word in the content
        if re.search(r'\b' + exp + r'\b', content):
            used_exports.append(exp)
            
    if not used_exports:
        continue
        
    print(f"\n{filepath} uses {len(used_exports)} exports")
    
    # Check what is currently imported
    import_match = re.search(r'import\s+\{([^}]+)\}\s+from\s+["\']./utils.js["\'];', content)
    
    if import_match:
        current_imports = [x.strip() for x in import_match.group(1).split(',')]
        missing = set(used_exports) - set(current_imports)
        if missing:
            print(f"Missing imports: {missing}")
            new_imports = current_imports + list(missing)
            new_import_str = 'import { ' + ', '.join(new_imports) + ' } from "./utils.js";'
            new_content = content[:import_match.start()] + new_import_str + content[import_match.end():]
            with open(filepath, 'w') as f:
                f.write(new_content)
            print("Fixed!")
        else:
            print("All good!")
    else:
        print("No utils.js import found! Adding one.")
        new_import_str = 'import { ' + ', '.join(used_exports) + ' } from "./utils.js";\n'
        new_content = new_import_str + content
        with open(filepath, 'w') as f:
            f.write(new_content)
        print("Fixed!")
