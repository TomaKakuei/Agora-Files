# Deterministic World Quality Audit

- Decomposed: `/home/yz_wang/yz_main/agora_2.0/docs/benchmark_20260724/decomposed_controlled_low_20260729`
- Monolithic: `/home/yz_wang/yz_main/agora_2.0/docs/benchmark_20260724/monolithic_baseline_low_24k_quality_20260729`
- Metrics are deterministic and frozen in the evaluator source.
- Sign tests are exploratory and unadjusted across metrics.

| Metric | Decomposed | Monolithic | D wins | M wins | Ties | p |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| component_id_unique_rate | 1.0 | 1.0 | 0 | 0 | 10 | 1.0 |
| component_room_coverage_rate | 1.0 | 1.0 | 0 | 0 | 10 | 1.0 |
| fallback_inventory_count | 0.0 | 0.0 | 0 | 0 | 10 | 1.0 |
| home_base_valid_rate | 1.0 | 1.0 | 0 | 0 | 10 | 1.0 |
| inventory_name_unique_rate | 0.9603 | 0.9914 | 3 | 4 | 3 | 0.773438 |
| max_role_repetition_share | 0.0698 | 0.0982 | 3 | 1 | 6 | 0.3125 |
| merchant_inventory_pass_rate | 1.0 | 0.825 | 4 | 0 | 6 | 0.0625 |
| premise_agents_recall | 0.4632 | 0.5593 | 2 | 7 | 1 | 0.980469 |
| premise_branch_macro_recall | 0.3555 | 0.3571 | 5 | 3 | 2 | 0.363281 |
| premise_items_recall | 0.3483 | 0.2325 | 8 | 2 | 0 | 0.054688 |
| premise_rooms_recall | 0.3426 | 0.3903 | 1 | 8 | 1 | 0.998047 |
| premise_visual_recall | 0.2677 | 0.2464 | 3 | 3 | 4 | 0.65625 |
| relational_agent_rate | 0.2448 | 0.2998 | 2 | 5 | 3 | 0.9375 |
| role_unique_rate | 0.972 | 0.8538 | 3 | 1 | 6 | 0.3125 |
| room_assignment_entropy | 0.9528 | 0.957 | 5 | 4 | 1 | 0.5 |
| room_occupancy_coverage | 0.9833 | 0.9889 | 1 | 1 | 8 | 0.75 |
| room_visual_canon_adherence | 0.9 | 0.8125 | 5 | 1 | 4 | 0.109375 |
| wardrobe_canon_term_coverage | 0.5071 | 0.3212 | 9 | 1 | 0 | 0.010742 |
