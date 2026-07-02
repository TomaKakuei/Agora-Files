import os
import glob
import re

files = glob.glob("frontend/src/*.js")
for file in files:
    with open(file, 'r') as f:
        content = f.read()
    calls = set(re.findall(r'this\.scene\.([a-zA-Z0-9_]+)\(', content))
    if calls:
        print(f"{file} calls on this.scene: {calls}")
