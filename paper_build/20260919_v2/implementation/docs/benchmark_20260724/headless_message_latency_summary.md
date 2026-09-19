# Agora Message-Only Headless Agent Reply Latency

Generated: `2026-07-25T17:29:31.729961+00:00`

This measures a real Pixel UI page in headless Firefox. The probe opens the live world, waits for the message composer, sends one user message, polls live state, and records the first completed AI Studio reply.

## Summary

- `world_count`: 5
- `ok_count`: 5
- `error_count`: 0
- `boot_ready_ms`: {'count': 5, 'mean': 21385.1, 'median': 21306.501, 'p95': 21840.828, 'min': 20818.957, 'max': 21866.789}
- `message_persist_ms`: {'count': 5, 'mean': 995.6, 'median': 948.0, 'p95': 1190.4, 'min': 900.0, 'max': 1243.0}
- `agent_reply_ms`: {'count': 5, 'mean': 3148.6, 'median': 3481.0, 'p95': 3539.8, 'min': 2499.0, 'max': 3551.0}
- `provider_latency_ms`: {'count': 5, 'mean': 1671.0, 'median': 1731.0, 'p95': 1780.8, 'min': 1407.0, 'max': 1791.0}

## Per-World Runs

| World | Access | Status | Model | Boot Ready ms | Persist ms | Agent Reply ms | Provider ms | Error |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Clockwork Rain Conservatory | `a0d595161b975dd0` | ok | gemini-3.1-flash-lite-preview | 21866.789 | 980 | 3551 | 1791 |  |
| Aurora Court of Migrating Cities | `cfa9e1aa1ed06a38` | ok | gemini-3.1-flash-lite-preview | 21736.985 | 900 | 3481 | 1740 |  |
| Mycelium Patent Bazaar | `995cad4cf9d281d9` | ok | gemini-3.1-flash-lite-preview | 20818.957 | 907 | 2499 | 1407 |  |
| Tidal Embassy of Lost Languages | `21c6573255c5933f` | ok | gemini-3.1-flash-lite-preview | 21196.267 | 1243 | 3495 | 1686 |  |
| Sunken Satellite Monastery | `82f0356e41af144a` | ok | gemini-3.1-flash-lite-preview | 21306.501 | 948 | 2717 | 1731 |  |
