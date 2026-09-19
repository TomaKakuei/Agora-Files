# Agora Multimodal Capability Audit

Generated: `2026-07-27T22:37:09.738081+00:00`

This audit distinguishes implemented cross-modal conditioning from visual quality and from declared-but-unobserved runtime media paths.

## Aggregate Findings

- Worlds audited: `5`
- Room prompt coverage: `1.000`
- Packaged room-floor coverage: `1.000`
- Retained rejected floor attempts: `10`
- Worlds with generated wardrobe policy: `5/5`
- Packaged agent atlases: `125`
- Agent prompts carrying the generated wardrobe policy: `1.000`
- Animated states with only one unique frame: `1.000`
- Agent atlases with persisted sprite vision QA: `0.000`
- Maps matching the frontend margin-derived dimensions: `0/5`
- Persisted map-QA verdicts: `0/5`
- Worlds with component generation enabled: `0/5`
- Observed interaction image/video artifacts: `0/0`

## Per-World Evidence

| World | Rooms | Floor plates | Atlases | Policy prompts | Duplicate animated states | Map contract |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Clockwork Rain Conservatory | 8 | 8 | 25 | 25 | 75/75 | mismatch |
| Aurora Court of Migrating Cities | 8 | 8 | 25 | 25 | 75/75 | mismatch |
| Mycelium Patent Bazaar | 8 | 8 | 25 | 25 | 75/75 | mismatch |
| Tidal Embassy of Lost Languages | 8 | 8 | 25 | 25 | 75/75 | mismatch |
| Sunken Satellite Monastery | 8 | 8 | 25 | 25 | 75/75 | mismatch |

## Interpretation

The system has real semantic-to-visual conditioning: every audited room carries a room-specific prompt and packaged floor plate, and every world carries a generated wardrobe policy. The audit does not show corresponding production quality. Current character atlases expose static repeated frames under animated labels, sprite vision QA is not connected to the production path, map dimensions disagree with the frontend's configured margin, and map-QA verdicts are not persisted with the final revision. Component/icon generation and interaction-time image/video paths are configured or implemented in code but are not evidenced by the audited artifacts.
