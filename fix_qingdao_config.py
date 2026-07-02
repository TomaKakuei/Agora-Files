import json

path = 'output/world_creator_drafts/creator_20260608_051817_8e89884e/revisions/r001/world_config.json'
with open(path, 'r') as f:
    config = json.load(f)

# Fix agent_id in main_characters
count = 1
for char in config.get('main_characters', []):
    if char['agent_id'] == 'qingdao_cold_chain_seafood_exchange_999999999_ma':
        char['agent_id'] = f"qingdao_cold_chain_seafood_exchange_999999999_main_{count:02d}"
        count += 1

# Fix always_activate_agent_ids
activation = config.get('activation', {})
old_ids = activation.get('always_activate_agent_ids', [])
if old_ids:
    new_ids = []
    # If they are all just 25 copies of the same truncated id, let's restore them
    for i in range(1, len(old_ids) + 1):
        new_ids.append(f"qingdao_cold_chain_seafood_exchange_999999999_main_{i:02d}")
    activation['always_activate_agent_ids'] = new_ids

with open(path, 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
print("Fixed world_config.json!")
