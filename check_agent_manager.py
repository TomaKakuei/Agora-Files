import re

with open("frontend/src/AgentManager.js", 'r') as f:
    content = f.read()

calls = set(re.findall(r'this\.([a-zA-Z0-9_]+)\(', content))
print("AgentManager calls:", calls)
