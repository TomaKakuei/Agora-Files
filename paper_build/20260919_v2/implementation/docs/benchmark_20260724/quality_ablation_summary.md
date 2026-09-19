# Agora 10-World Quality and Ablation Evidence

Generated: `2026-07-25T17:03:59.636063+00:00`

## Summary

- `world_count`: 10
- `agent_count`: 250
- `published_worlds`: 10
- `pixel_read_worlds`: 10
- `pixel_launch_worlds`: 10
- `total_inventory_items`: 5433
- `total_generated_inventory_items`: 1920
- `total_fallback_inventory_items`: 124
- `generated_inventory_item_rate`: 0.3534
- `fallback_inventory_item_rate`: 0.0228
- `agents_with_generated_inventory`: 175
- `agents_with_fallback_inventory`: 51
- `total_wardrobe_policy_units`: 96
- `floor_qa_rejections`: 16
- `compiler_repairs_requested`: 0
- `compiler_repairs_applied`: 0
- `mean_quality_proxy`: 0.8237
- `world_coherence_proxy_mean`: 1.0
- `agent_specificity_proxy_mean`: 0.85
- `inventory_usefulness_proxy_mean`: 0.2936
- `visual_policy_proxy_mean`: 0.975
- `playability_gate_proxy_mean`: 1.0

## Current Strict Inventory Subset

Fallback inventory is reported separately for the current strict subset so legacy artifacts do not dilute the claim about the latest inventory hardfail pipeline.

- `world_count`: 5
- `agent_count`: 125
- `published_worlds`: 5
- `pixel_read_worlds`: 5
- `pixel_launch_worlds`: 5
- `total_inventory_items`: 2974
- `total_generated_inventory_items`: 1311
- `total_fallback_inventory_items`: 0
- `generated_inventory_item_rate`: 0.4408
- `fallback_inventory_item_rate`: 0.0
- `agents_with_generated_inventory`: 125
- `agents_with_fallback_inventory`: 0
- `total_wardrobe_policy_units`: 63
- `floor_qa_rejections`: 12
- `compiler_repairs_requested`: 0
- `compiler_repairs_applied`: 0
- `mean_quality_proxy`: 0.9331
- `world_coherence_proxy_mean`: 1.0
- `agent_specificity_proxy_mean`: 1.0
- `inventory_usefulness_proxy_mean`: 0.4405
- `visual_policy_proxy_mean`: 1.225
- `playability_gate_proxy_mean`: 1.0

| Strict-Subset World | Access | Agents | Inv. Items | Generated | Fallback | Agents with Fallback |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Aurora Court of Migrating Cities | `cfa9e1aa1ed06a38` | 25 | 547 | 251 | 0 | 0 |
| Clockwork Rain Conservatory | `a0d595161b975dd0` | 25 | 594 | 282 | 0 | 0 |
| Mycelium Patent Bazaar | `995cad4cf9d281d9` | 25 | 676 | 298 | 0 | 0 |
| Sunken Satellite Monastery | `82f0356e41af144a` | 25 | 561 | 219 | 0 | 0 |
| Tidal Embassy of Lost Languages | `21c6573255c5933f` | 25 | 596 | 261 | 0 | 0 |

## Fallback-Allowed Historical Baseline

This baseline uses completed legacy worlds that published while generic fallback inventory was still accepted. It is a historical counterfactual rather than a freshly generated monolithic baseline.

- `world_count`: 2
- `agent_count`: 50
- `published_worlds`: 2
- `pixel_read_worlds`: 2
- `pixel_launch_worlds`: 2
- `total_inventory_items`: 914
- `total_generated_inventory_items`: 0
- `total_fallback_inventory_items`: 123
- `generated_inventory_item_rate`: 0.0
- `fallback_inventory_item_rate`: 0.1346
- `agents_with_generated_inventory`: 0
- `agents_with_fallback_inventory`: 50
- `total_wardrobe_policy_units`: 10
- `floor_qa_rejections`: 0
- `compiler_repairs_requested`: 0
- `compiler_repairs_applied`: 0
- `mean_quality_proxy`: 0.578
- `world_coherence_proxy_mean`: 1.0
- `agent_specificity_proxy_mean`: 0.5
- `inventory_usefulness_proxy_mean`: -0.1411
- `visual_policy_proxy_mean`: 0.5312
- `playability_gate_proxy_mean`: 1.0

| Baseline World | Access | Agents | Inv. Items | Generated | Fallback | Agents with Fallback | Quality Mean |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Clockwork Renaissance | `197bb42f896502ff` | 25 | 518 | 0 | 48 | 25 | 0.694 |
| Orbital Trade Station 42670 | `45be24acdedff899` | 25 | 396 | 0 | 75 | 25 | 0.4621 |

## Strict vs Fallback Baseline

| Condition | Worlds | Agents | Inv. Items | Generated Rate | Fallback Rate | Agents with Fallback | Mean Quality Proxy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Current strict pipeline | 5 | 125 | 2974 | 0.4408 | 0.0 | 0 | 0.9331 |
| Fallback-allowed historical baseline | 2 | 50 | 914 | 0.0 | 0.1346 | 50 | 0.578 |

## Per-World Quality Proxies

| World | Access | Agents | Inv. Items | Fallback | Wardrobe Rules | Floor QA Rejects | Pixel | Launch | Quality Mean |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Aurora Court of Migrating Cities | `cfa9e1aa1ed06a38` | 25 | 547 | 0 | 5 | 0 | True | True | 0.9543 |
| Bioluminescent Library Reef | `b4b94ba6a4576151` | 25 | 493 | 1 | 4 | 0 | True | True | 0.9631 |
| Clockwork Rain Conservatory | `a0d595161b975dd0` | 25 | 594 | 0 | 4 | 0 | True | True | 0.9449 |
| Clockwork Renaissance | `197bb42f896502ff` | 25 | 518 | 48 | 3 | 0 | True | True | 0.694 |
| Lunar Salvage Bazaar | `9b267c7108754d45` | 25 | 702 | 0 | 3 | 4 | True | True | 0.9526 |
| Mycelium Patent Bazaar | `995cad4cf9d281d9` | 25 | 676 | 0 | 4 | 2 | True | True | 0.9257 |
| Orbital Trade Station 42670 | `45be24acdedff899` | 25 | 396 | 75 | 0 | 0 | True | True | 0.4621 |
| Qingdao Cold-Chain Seafood Exchange 42653 | `d3be36e2f3b3d037` | 25 | 350 | 0 | 0 | 0 | True | True | 0.5 |
| Sunken Satellite Monastery | `82f0356e41af144a` | 25 | 561 | 0 | 4 | 4 | True | True | 0.9156 |
| Tidal Embassy of Lost Languages | `21c6573255c5933f` | 25 | 596 | 0 | 4 | 6 | True | True | 0.9251 |

## Ablation Evidence

| Ablation | Observed Full-Pipeline Signal | Stage-Local Counterfactual |
| --- | --- | --- |
| No wardrobe policy | 96 policy units across 10 worlds | 0 policy units; sprite prompts lose world-specific attire/palette constraints |
| Fallback-allowed inventory | strict subset: 0 fallback items, 0/125 agents with fallback inventory; baseline: 123 fallback items, 50/50 agents with fallback inventory | generic inventory was accepted instead of hardfailed |
| No compiler critique | 0 worlds requested repair; 0 repairs applied | equivalent for worlds where critique did not request repair; unsafe when repair is requested |
| No floor visual QA | 16 rejected floor candidates | those candidates would become possible published map artifacts |

