import re

with open("frontend/src/WorldScene.js", "r") as f:
    content = f.read()

# get all methods defined in WorldScene.js
defined = set()
for m in re.finditer(r'\n  ([a-zA-Z0-9_]+)\(', content):
    defined.add(m.group(1))

# find all `this.someMethod(` calls
calls = set(re.findall(r'this\.([a-zA-Z0-9_]+)\(', content))

# exclude phaser methods and standard js methods
phaser_methods = {
    'add', 'make', 'load', 'time', 'tweens', 'cameras', 'input', 'scene',
    'scale', 'sys', 'game', 'anims', 'textures', 'sound', 'events', 'registry',
    'physics', 'matter', 'facebook', 'plugins', 'children'
}

missing = calls - defined - phaser_methods
print("Missing methods called on this:", missing)
