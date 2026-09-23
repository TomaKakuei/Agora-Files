# Seeded-Fault Validator Benchmark

Generated: `2026-07-29T12:53:34.128597+00:00`

This benchmark mutates copies of five publish-ready world artifacts and invokes the same deterministic validators used by the production pipeline. It performs no LLM or image-generation calls.

| Seeded defect | Owner | Detected | Attribution | Clean FP |
|---|---|---:|---:|---:|
| agent_definitions_removed | agent_ir | 5/5 | 5/5 | 0/5 |
| agent_inventory_removed | agent_inventory | 5/5 | 5/5 | 0/5 |
| agent_knowledge_templates_removed | agent_knowledge | 5/5 | 5/5 | 0/5 |
| agent_property_templates_removed | agent_property | 5/5 | 5/5 | 0/5 |
| asset_world_id_mismatch | asset_provenance | 5/5 | 5/5 | 0/5 |
| asset_world_revision_mismatch | asset_provenance | 5/5 | 5/5 | 0/5 |
| atlas_opaque_background | sprite_atlas | 5/5 | 5/5 | 0/5 |
| map_dimension_shift | map_compositor | 5/5 | 5/5 | 0/5 |
| raw_sprite_sheet_cropped | sprite_source | 5/5 | 5/5 | 0/5 |
| room_definitions_removed | room_ir | 5/5 | 5/5 | 0/5 |
| semantic_component_removed | component_compositor | 4/4 | 4/4 | 0/4 |
| semantic_component_unreadable | component_compositor | 4/4 | 4/4 | 0/4 |

## Aggregate

- Detection: 58/58 (100.0%, Wilson 95% CI 93.8%-100.0%)
- Correct attribution: 58/58 (100.0%, Wilson 95% CI 93.8%-100.0%)
- False positives: 0/58 (0.0%, Wilson 95% CI 0.0%-6.2%)
- Validator latency: mean 100.33 ms, median 1.04 ms, max 1225.35 ms

The four sidecar-enabled worlds are eligible for semantic missing/readability faults. Archive of Borrowed Gravity predates the sidecar contract and is excluded only from those two fault categories.
