import json

path = "output/world_creator_drafts/creator_20260605_200912_9f9769cf/draft_manifest.json"
with open(path, "r") as f:
    d = json.load(f)

d["art_status"] = "art_queued"

with open(path, "w") as f:
    json.dump(d, f, indent=2)

print("Requeued Panjiayuan!")
