# Paper Cost and Localized-Repair Evidence

Generated: `2026-07-29T14:11:22.841695+00:00`

## Text Generation

| World | Decomposed wall time (s) | Outer attempts | Specialist calls (estimated) |
|---|---:|---:|---:|
| Cartographer Lung Exchange | 985.0 | 1 | 10 |
| Archive of Borrowed Gravity | 167.0 | 1 | 10 |
| Intertidal Embassy for Extinct Rivers | 228.0 | 1 | 10 |
| Night Market of Unfinished Weather | 145.0 | 1 | 10 |
| Museum of Future Debts | 158.0 | 1 | 10 |

Decomposed median wall time: **167.0 s** (range 145.0-985.0 s); outer retries: **0**.

Complete monolithic baseline: **6/15**; truncation failures: **9**; mean wall time **117.8 s**.

## Observational Local Repair Trace

| Rooms regenerated | Agents reused | Duration (s) |
|---:|---:|---:|
| 3 | 12 | 57.887 |
| 6 | 12 | 96.755 |
| 4 | 12 | 58.434 |
| 2 | 12 | 63.278 |
| 1 | 12 | 21.186 |
| 1 | 12 | 19.715 |
| 1 | 12 | 20.091 |
| 2 | 12 | 27.162 |

Across the archived same-world trace, localized repairs have median duration **27.162 s** versus **96.755 s** for the six-room repair (71.9% lower). All records reuse at least 12 agent sprites.

The repair trace is observational and is not presented as a randomized timing experiment. It supports the narrower claim that structured localization reduces repair fan-out while preserving already validated sprites.
