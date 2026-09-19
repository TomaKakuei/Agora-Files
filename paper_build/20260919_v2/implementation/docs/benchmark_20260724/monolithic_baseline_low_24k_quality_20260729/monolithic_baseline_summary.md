# Fresh Monolithic LLM Baseline

Generated: `2026-07-29T21:26:26.556641+00:00`

This baseline uses one LLM call per world to generate a complete `builder_spec` from the same original briefs used by the strict subset. It does not run decomposed planner/rooms/items/roles/wardrobe nodes, FLUX art, Pixel launch, or publish.

## Summary

- `world_count`: 5
- `trial_count`: 15
- `generation_ok`: 15
- `merged_contract_ok`: 9
- `compile_ok`: 15
- `worlds_with_any_compile_success`: 4
- `worlds_with_majority_compile_success`: 3
- `worlds_with_majority_first_pass_success`: 3
- `strict_source_compile_worlds`: 5
- `paired_one_sided_sign_test_p`: 0.25
- `complete_trial_successes`: 9
- `complete_trial_success_rate`: 0.6
- `complete_trial_wilson_95`: [0.3575, 0.8018]
- `truncation_failure_count`: 0
- `first_pass_complete_successes`: 9
- `recovered_complete_successes`: 0
- `provider_attempt_count`: 15
- `retry_or_failure_attempt_count`: 0
- `invalid_json_attempt_count`: 0
- `mean_provider_attempts_per_trial`: 1.0
- `usage_metadata_attempt_count`: 15
- `usage_metadata_coverage`: 1.0
- `token_totals`: {'cachedContentTokenCount': 60645, 'candidatesTokenCount': 221053, 'promptTokenCount': 112695, 'totalTokenCount': 333748}
- `mean_total_tokens_per_trial`: 22249.87
- `per_world`: [{'world_name': 'Archive of Borrowed Gravity', 'successes': 3, 'first_pass_successes': 3, 'trials': 3, 'success_rate': 1.0, 'first_pass_success_rate': 1.0, 'wilson_95': [0.4385, 1.0]}, {'world_name': 'Cartographer Lung Exchange', 'successes': 3, 'first_pass_successes': 3, 'trials': 3, 'success_rate': 1.0, 'first_pass_success_rate': 1.0, 'wilson_95': [0.4385, 1.0]}, {'world_name': 'Intertidal Embassy for Extinct Rivers', 'successes': 2, 'first_pass_successes': 2, 'trials': 3, 'success_rate': 0.6667, 'first_pass_success_rate': 0.6667, 'wilson_95': [0.2077, 0.9385]}, {'world_name': 'Museum of Future Debts', 'successes': 1, 'first_pass_successes': 1, 'trials': 3, 'success_rate': 0.3333, 'first_pass_success_rate': 0.3333, 'wilson_95': [0.0615, 0.7923]}, {'world_name': 'Night Market of Unfinished Weather', 'successes': 0, 'first_pass_successes': 0, 'trials': 3, 'success_rate': 0.0, 'first_pass_success_rate': 0.0, 'wilson_95': [0.0, 0.5615]}]
- `mean_elapsed_seconds`: 55.6687
- `median_elapsed_seconds`: 55.752
- `mean_success_elapsed_seconds`: 55.8594
- `mean_failure_elapsed_seconds`: 55.3827
- `mean_rooms`: 6.0
- `mean_item_catalog_items`: 15.0
- `mean_main_characters`: 12.0
- `mean_inventory_items`: 105.8
- `total_fallback_inventory_items`: 0
- `mean_quality_proxy`: 0.9875
- `mean_agent_specificity_proxy`: 1.0
- `mean_inventory_usefulness_proxy`: 1.0
- `successful_mean_rooms`: 6.0
- `successful_mean_item_catalog_items`: 15.0
- `successful_mean_main_characters`: 12.0
- `successful_mean_inventory_items`: 106.8889

## Per World

| World | Generation | Compile | Main Chars | Items | Inventory | Fallback | Quality | Error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Cartographer Lung Exchange | True | True | 12 | 15 | 110 | 0 | 0.9875 |  |
| Archive of Borrowed Gravity | True | True | 12 | 15 | 103 | 0 | 0.9875 |  |
| Intertidal Embassy for Extinct Rivers | True | True | 12 | 15 | 110 | 0 | 0.9875 |  |
| Night Market of Unfinished Weather | True | True | 12 | 15 | 103 | 0 | 0.9875 |  |
| Museum of Future Debts | True | True | 12 | 15 | 103 | 0 | 0.9875 |  |
| Cartographer Lung Exchange | True | True | 12 | 15 | 110 | 0 | 0.9875 |  |
| Archive of Borrowed Gravity | True | True | 12 | 15 | 103 | 0 | 0.9875 |  |
| Intertidal Embassy for Extinct Rivers | True | True | 12 | 15 | 103 | 0 | 0.9875 |  |
| Night Market of Unfinished Weather | True | True | 12 | 15 | 110 | 0 | 0.9875 |  |
| Museum of Future Debts | True | True | 12 | 15 | 103 | 0 | 0.9875 |  |
| Cartographer Lung Exchange | True | True | 12 | 15 | 110 | 0 | 0.9875 |  |
| Archive of Borrowed Gravity | True | True | 12 | 15 | 110 | 0 | 0.9875 |  |
| Intertidal Embassy for Extinct Rivers | True | True | 12 | 15 | 103 | 0 | 0.9875 |  |
| Night Market of Unfinished Weather | True | True | 12 | 15 | 103 | 0 | 0.9875 |  |
| Museum of Future Debts | True | True | 12 | 15 | 103 | 0 | 0.9875 |  |
