# Fresh Monolithic LLM Baseline

Generated: `2026-07-29T21:26:27.252635+00:00`

This baseline uses one LLM call per world to generate a complete `builder_spec` from the same original briefs used by the strict subset. It does not run decomposed planner/rooms/items/roles/wardrobe nodes, FLUX art, Pixel launch, or publish.

## Summary

- `world_count`: 5
- `trial_count`: 5
- `generation_ok`: 5
- `merged_contract_ok`: 4
- `compile_ok`: 5
- `worlds_with_any_compile_success`: 4
- `worlds_with_majority_compile_success`: 4
- `worlds_with_majority_first_pass_success`: 2
- `strict_source_compile_worlds`: 5
- `paired_one_sided_sign_test_p`: 0.5
- `complete_trial_successes`: 4
- `complete_trial_success_rate`: 0.8
- `complete_trial_wilson_95`: [0.3755, 0.9638]
- `truncation_failure_count`: 0
- `first_pass_complete_successes`: 2
- `recovered_complete_successes`: 2
- `provider_attempt_count`: 7
- `retry_or_failure_attempt_count`: 2
- `invalid_json_attempt_count`: 2
- `mean_provider_attempts_per_trial`: 1.4
- `usage_metadata_attempt_count`: 7
- `usage_metadata_coverage`: 1.0
- `token_totals`: {'cachedContentTokenCount': 20211, 'candidatesTokenCount': 142343, 'promptTokenCount': 52267, 'totalTokenCount': 194610}
- `mean_total_tokens_per_trial`: 38922.0
- `per_world`: [{'world_name': 'Aurora Court of Migrating Cities', 'successes': 1, 'first_pass_successes': 1, 'trials': 1, 'success_rate': 1.0, 'first_pass_success_rate': 1.0, 'wilson_95': [0.2065, 1.0]}, {'world_name': 'Clockwork Rain Conservatory', 'successes': 1, 'first_pass_successes': 0, 'trials': 1, 'success_rate': 1.0, 'first_pass_success_rate': 0.0, 'wilson_95': [0.2065, 1.0]}, {'world_name': 'Mycelium Patent Bazaar', 'successes': 1, 'first_pass_successes': 1, 'trials': 1, 'success_rate': 1.0, 'first_pass_success_rate': 1.0, 'wilson_95': [0.2065, 1.0]}, {'world_name': 'Sunken Satellite Monastery', 'successes': 0, 'first_pass_successes': 0, 'trials': 1, 'success_rate': 0.0, 'first_pass_success_rate': 0.0, 'wilson_95': [0.0, 0.7935]}, {'world_name': 'Tidal Embassy of Lost Languages', 'successes': 1, 'first_pass_successes': 0, 'trials': 1, 'success_rate': 1.0, 'first_pass_success_rate': 0.0, 'wilson_95': [0.2065, 1.0]}]
- `mean_elapsed_seconds`: 111.9568
- `median_elapsed_seconds`: 86.144
- `mean_success_elapsed_seconds`: 120.36
- `mean_failure_elapsed_seconds`: 78.344
- `mean_rooms`: 8.2
- `mean_item_catalog_items`: 15.0
- `mean_main_characters`: 24.8
- `mean_inventory_items`: 215.2
- `total_fallback_inventory_items`: 0
- `mean_quality_proxy`: 0.9875
- `mean_agent_specificity_proxy`: 1.0
- `mean_inventory_usefulness_proxy`: 1.0
- `successful_mean_rooms`: 8.25
- `successful_mean_item_catalog_items`: 15.0
- `successful_mean_main_characters`: 24.75
- `successful_mean_inventory_items`: 213.75

## Per World

| World | Generation | Compile | Main Chars | Items | Inventory | Fallback | Quality | Error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Aurora Court of Migrating Cities | True | True | 25 | 15 | 228 | 0 | 0.9875 |  |
| Clockwork Rain Conservatory | True | True | 24 | 15 | 199 | 0 | 0.9875 |  |
| Mycelium Patent Bazaar | True | True | 25 | 15 | 221 | 0 | 0.9875 |  |
| Sunken Satellite Monastery | True | True | 25 | 15 | 221 | 0 | 0.9875 |  |
| Tidal Embassy of Lost Languages | True | True | 25 | 15 | 207 | 0 | 0.9875 |  |
