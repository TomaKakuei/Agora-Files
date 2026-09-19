# Validation — evidence revision 2

- XeLaTeX / BibTeX build passes: 17 PDF pages, main text ends on page 9; references occupy parts of pages 9–10.
- 29 actually cited bibliography entries, 35 unique labels, no unresolved citations/references or overfull boxes; minor underfull spacing notices remain.
- All 12 publication PNGs reproduced byte-for-byte from frozen inputs in the current environment.
- Independent audit recomputes 24 generation records and 21 trajectories, including all 1,512 attempted actions, 1,365 successes, 147 failures, 314 approvals, 150 approvals with non-speech effects, and 398 inventory/location-changing successes.
- Every failed model action and all 21 injected invalid-transfer probes have equal before/after state hashes. All 21 final serialization round trips agree.
- PDF bounding-box check: 11,483 extracted words, none outside the page. Cover, new result figures, tables, and appendix pages visually inspected.
- PDF SHA-256: `b1d7b9cd965f7a4c1e3c26edce1e5daf801de1277d5b7e0f36252efb4982dd25`.
- No new model calls or human responses. New findings are retrospective analyses of existing records.
