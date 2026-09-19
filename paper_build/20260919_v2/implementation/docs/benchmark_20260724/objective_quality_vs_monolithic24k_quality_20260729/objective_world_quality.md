# Deterministic World Quality Audit

- Decomposed: `/home/yz_wang/yz_main/agora_2.0/docs/benchmark_20260724/decomposed_controlled_low_20260729`
- Monolithic: `/home/yz_wang/yz_main/agora_2.0/docs/benchmark_20260724/monolithic_baseline_low_24k_quality_20260729`
- Metrics are deterministic and frozen in the evaluator source.
- Sign tests are exploratory and unadjusted across metrics.

| Metric | Decomposed | Monolithic | D wins | M wins | Ties | p |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| component_id_unique_rate | 1.0 | 1.0 | 0 | 0 | 5 | 1.0 |
| component_room_coverage_rate | 1.0 | 1.0 | 0 | 0 | 5 | 1.0 |
| fallback_inventory_count | 0.0 | 0.0 | 0 | 0 | 5 | 1.0 |
| home_base_valid_rate | 1.0 | 1.0 | 0 | 0 | 5 | 1.0 |
| inventory_name_unique_rate | 0.935 | 1.0 | 0 | 2 | 3 | 1.0 |
| max_role_repetition_share | 0.0833 | 0.0833 | 0 | 0 | 5 | 1.0 |
| merchant_inventory_pass_rate | 1.0 | 0.8 | 2 | 0 | 3 | 0.25 |
| premise_agents_recall | 0.4573 | 0.5596 | 0 | 4 | 1 | 1.0 |
| premise_branch_macro_recall | 0.3595 | 0.3388 | 3 | 0 | 2 | 0.125 |
| premise_items_recall | 0.3607 | 0.2207 | 4 | 1 | 0 | 0.1875 |
| premise_rooms_recall | 0.3446 | 0.3755 | 1 | 4 | 0 | 0.96875 |
| premise_visual_recall | 0.2755 | 0.1993 | 3 | 0 | 2 | 0.125 |
| relational_agent_rate | 0.2 | 0.35 | 0 | 3 | 2 | 1.0 |
| role_unique_rate | 1.0 | 1.0 | 0 | 0 | 5 | 1.0 |
| room_assignment_entropy | 0.9629 | 0.9579 | 3 | 1 | 1 | 0.3125 |
| room_occupancy_coverage | 0.9667 | 1.0 | 0 | 1 | 4 | 1.0 |
| room_visual_canon_adherence | 1.0 | 0.9667 | 1 | 0 | 4 | 0.5 |
| wardrobe_canon_term_coverage | 0.537 | 0.4305 | 4 | 1 | 0 | 0.1875 |
