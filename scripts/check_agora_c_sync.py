import os
import sys
import shutil
from pathlib import Path

def sync_repo(source_dir, target_dir):
    source = Path(source_dir)
    target = Path(target_dir)
    
    EXCLUDE_DIRS = {
        '.git', '.pytest_cache', '__pycache__', 'node_modules', 
        'output', 'drafts', 'data', 'assets', 'scratch',
        '.gemini', '.TinyTeX'
    }
    
    EXCLUDE_EXTS = {
        '.bak', '.log', '.db', '.sqlite', '.pyc', '.png', '.jpg', '.jpeg', '.gif'
    }
    
    # Do not sync files > 1MB
    MAX_SIZE = 1024 * 1024
    
    for root, dirs, files in os.walk(source):
        # Filter directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]
        
        rel_path = os.path.relpath(root, source)
        target_root = target / rel_path if rel_path != '.' else target
        
        target_root.mkdir(parents=True, exist_ok=True)
        
        for file in files:
            if any(file.endswith(ext) for ext in EXCLUDE_EXTS):
                continue
            if file.startswith('.') and file != '.gitignore':
                continue
                
            src_file = Path(root) / file
            if not src_file.is_file():
                continue
                
            # Filter by size
            if src_file.stat().st_size > MAX_SIZE:
                print(f"Skipping {src_file} (too large)")
                continue
                
            target_file = target_root / file
            
            # Copy file
            shutil.copy2(src_file, target_file)
            print(f"Synced {rel_path}/{file}")

if __name__ == '__main__':
    sync_repo('/home/yz_wang/yz_main/agora_2.0', '/home/yz_wang/yz_main/agora-C')
