import re

with open("frontend/src/AgentManager.js", 'r') as f:
    content = f.read()

props = set(re.findall(r'this\.scene\.([a-zA-Z0-9_]+)', content))
print("AgentManager uses on this.scene:", props)
