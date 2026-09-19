# Deterministic World Quality Audit

- Decomposed: `/home/yz_wang/yz_main/agora_2.0/docs/benchmark_20260724/decomposed_controlled_low_heldout_20260729`
- Monolithic: `/home/yz_wang/yz_main/agora_2.0/docs/benchmark_20260724/monolithic_baseline_low_24k_quality_heldout_20260729`
- Metrics are deterministic and frozen in the evaluator source.
- Sign tests are exploratory and unadjusted across metrics.

| Metric | Decomposed | Monolithic | D wins | M wins | Ties | p |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| component_id_unique_rate | 1.0 | 1.0 | 0 | 0 | 5 | 1.0 |
| component_room_coverage_rate | 1.0 | 1.0 | 0 | 0 | 5 | 1.0 |
| fallback_inventory_count | 0.0 | 0.0 | 0 | 0 | 5 | 1.0 |
| home_base_valid_rate | 1.0 | 1.0 | 0 | 0 | 5 | 1.0 |
| inventory_name_unique_rate | 0.9855 | 0.9828 | 3 | 2 | 0 | 0.5 |
| max_role_repetition_share | 0.0563 | 0.113 | 3 | 1 | 1 | 0.3125 |
| merchant_inventory_pass_rate | 1.0 | 0.85 | 2 | 0 | 3 | 0.25 |
| premise_agents_recall | 0.4692 | 0.559 | 2 | 3 | 0 | 0.8125 |
| premise_branch_macro_recall | 0.3514 | 0.3755 | 2 | 3 | 0 | 0.8125 |
| premise_items_recall | 0.3359 | 0.2444 | 4 | 1 | 0 | 0.1875 |
| premise_rooms_recall | 0.3406 | 0.405 | 0 | 4 | 1 | 1.0 |
| premise_visual_recall | 0.2599 | 0.2935 | 0 | 3 | 2 | 1.0 |
| relational_agent_rate | 0.2897 | 0.2497 | 2 | 2 | 1 | 0.6875 |
| role_unique_rate | 0.944 | 0.7077 | 3 | 1 | 1 | 0.3125 |
| room_assignment_entropy | 0.9428 | 0.956 | 2 | 3 | 0 | 0.8125 |
| room_occupancy_coverage | 1.0 | 0.9778 | 1 | 0 | 4 | 0.5 |
| room_visual_canon_adherence | 0.8 | 0.6583 | 4 | 1 | 0 | 0.1875 |
| wardrobe_canon_term_coverage | 0.4771 | 0.212 | 5 | 0 | 0 | 0.03125 |
