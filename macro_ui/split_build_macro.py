import re

with open('build_macro_ui.py', 'r') as f:
    lines = f.readlines()

asset_methods = [
    'def _image_client_for_config',
    'def _resolve_asset_path',
    'def _item_image_mode',
    'def _item_is_important_artifact',
    'def _ensure_item_images',
    'def _character_portraits_enabled',
    'def _ensure_agent_portraits',
    'def _ensure_room_images',
    'def _build_asset_set_manifest',
]

core_methods = []
asset_lines = []
imports = []
in_asset = False
brace_count = 0

for line in lines:
    if line.startswith('import ') or line.startswith('from '):
        imports.append(line)
        continue
        
    match = re.match(r'^def ([a-zA-Z0-9_]+)\(', line)
    if match:
        method_name = f"def {match.group(1)}"
        if method_name in asset_methods:
            in_asset = True
            
    if in_asset:
        asset_lines.append(line)
        if line.startswith('def ') and not method_name in asset_methods:
             in_asset = False
             core_methods.append(line)
    else:
        core_methods.append(line)

with open('build_macro_assets.py', 'w') as f:
    f.writelines(imports)
    f.write('\n\n')
    f.writelines(asset_lines)

print(f"Created build_macro_assets.py with {len(asset_lines)} lines")
