import json

path = 'output/world_creator_drafts/creator_20260608_051817_8e89884e/draft_manifest.json'
with open(path, 'r') as f:
    manifest = json.load(f)

# Set status to art_queued
manifest['status'] = 'art_queued'
manifest['art_status'] = 'art_queued'

with open(path, 'w') as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
print("Requeued Qingdao!")
