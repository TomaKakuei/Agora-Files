# Validation · 2026-09-19

- `python verify_bundle.py`: 1,686 frozen source files, 83,644,532 bytes (79.77 MiB), all SHA-256 values verified; the full directory, including generated local outputs, remains below 10,000,000,000 bytes.
- `bash reproduce.sh`: successfully built the 17-page manuscript without model API calls; checked 29 cited references, 35 labels and 12 figure assets. No unresolved references/citations, overfull boxes, alignment errors or font errors; minor underfull spacing warnings remain.
- All 12 publication PNGs matched freshly rendered outputs byte for byte in the recorded environment.
- The extended audit reproduced 24 generation trials and 21 execution trajectories: 1,512 actions, 1,365 successes and 147 failures. Failed actions and all 21 scripted rejection probes preserved their before/after state hashes.
- Re-analysis of the three included historical stories reproduced 1,052 events. The five included accepted `mw3` stories reproduced 53 events and passed the analysis script's identity checks.
- Selected upload files and nested ZIP members were scanned for common credential formats. The only two flagged literals were a README placeholder and an environment-mocking test fixture; no provider credential was identified by this scan.

This validates the packaged paper and its archived evidence. It does not establish new model results, completed human evaluation, or reproducibility of historical model calls on a current provider endpoint.
