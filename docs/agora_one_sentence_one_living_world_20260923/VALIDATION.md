# Validation — 2026-09-23

## TeX package — 2026-09-24

- Created `../agora_one_sentence_one_living_world_20260923_tex.zip` from the transitive TeX input, figure, and bibliography dependencies: **45 files, 2.41 MiB**. The package includes both PDFs, a portable XeLaTeX/BibTeX build script, and per-file SHA-256 checksums. No Python runtime, credentials, or experimental data are needed to compile it.
- Verified every checksum, then compiled both entries from a fresh extracted directory with no pre-existing LaTeX auxiliary files: **12 main-paper pages and 11 supplementary pages**. Both final logs have no unresolved references/citations, overfull boxes, missing glyphs, or LaTeX errors.
- Checked all **22 cross-PDF links** against the rebuilt destination anchors. Added `build_tex.sh`, `make_tex_package.py`, and `TEX_PACKAGE_README.md` so the compilation-only package can be regenerated.

## Current mechanism-focused revision

- Rebuilt the **12-page main paper and 11-page supplement** with `bash build.sh`. The main paper has 22 local labels and 28 cited works; the supplement has 24 local labels and 4 cited works. Overall: 46 labels, 29 distinct cited works, and 14 figure assets.
- Checked all **22 cross-PDF links** (16 main-to-supplement and 6 supplement-to-main) against destination named anchors. Extracted pages contain no unresolved `??` references. Both logs pass the release checks for unresolved citations/references, overfull boxes, alignment and font errors.
- Inspected the revised main title/abstract page and the supplementary aggregate-table page. Both render without clipping or overlapping content.
- The aggregate planner table has moved into the supplement alongside all 18 individual trajectories. No recorded result was removed. The main paper now explains the mechanism through a trace with explicit supplementary provenance.
- Verified the Clockwork Full repeat-1 example directly: at checkpoint 9 Thistle holds one `crc_016__corrosive_inkwell` and Elara holds none; event `model_r09_slot09` commits the transfer; checkpoint 13 records the reversed holdings. The scripted rejection at round 9 preserves the state hash. The supplement discloses the post-collection illustrative selection and unknown target response.
- The build rechecked archived construction/execution arithmetic and deterministically replayed **all 18 trajectories and 108 planning blocks** against frozen input/runtime hashes. All 220 failed actions preserve state. No new LLM calls or human responses were added in this revision.

## Earlier compact-ablation revision

- Built the final bundle from a clean copy excluding LaTeX auxiliary files and the disposable preparation directory; both PDFs and all 18 trajectory replays pass without model calls.
- Current outputs: **12-page main paper and 11-page supplement**, 24 and 23 local labels, 28 and 4 locally cited works; 29 distinct works and 14 figure assets overall.
- Added the compact study specified in `llm_ablation/protocol.json`: **18 trajectories, 108 planning blocks, 1,296 action slots**, one model, two fixed worlds, three configurations, three repeats. Six pilot calls remain separate.
- All **18 trajectories and 108 blocks** pass deterministic action replay: prompt treatment, returned plan, every event, and every resulting state match the frozen inputs and runtime. All **220 failed actions** leave state unchanged.
- Recorded **109 API attempts**, including one invalid-JSON/truncation retry. Input/output telemetry totals are 1,821,701 / 201,841 tokens. The legacy client preserves the failed attempt's diagnostics and token counts, but not the malformed raw text; no claim of a complete raw HTTP-response archive is made.
- Six treatment/denominator checks pass. Their purpose is to verify that removing event history preserves current tasks, current state, and the current intervention, while the catalog condition changes the declared action space.
- Checked **21 cross-PDF links** (16 main-to-supplement and 5 supplement-to-main) against destination named anchors. No unresolved references/citations, overfull boxes, font errors, or missing glyphs. Updated main-table and supplementary-table pages were visually inspected.
- Re-ran existing human, generation, and execution verifiers. `human_evaluation/` has no changes against the existing repository version: eligibility, original votes, workbooks, and analysis remain unchanged.
- The main paper reports the mixed result: Full / No event history / Catalog only give 349 / 352 / 375 successes and 14 / 24 / 0 inventory-changing actions over 432 scheduled slots each. Catalog restrictions are explicit. The prior decentralized memory intervention remains future work.

## Earlier split-only release

- Built from a clean copy without `.aux`, `.bbl`, `.log`, `.out`, or `.blg` files using `bash build.sh`; both builds and all evidence checks pass.
- Main paper: **12 pages, 22 labels, 28 cited works**. Supplement: **10 pages, 21 labels, 4 cited works**. Across both: **43 distinct labels, 29 distinct cited works, 14 figure assets**.
- Verified all **19 cross-PDF links** (15 main-to-supplement, 4 supplement-to-main) against the destination PDF named anchors. Checked extracted text for unresolved `??` references.
- Inspected both full-document page contact sheets and the supplement title page. No clipped figures or overfull boxes were found. Standard underfull line-spacing notices remain.
- Compared all **14 original content sections** against their split destinations after normalizing only intended reference wording and paths; substantive contents are preserved. No prospective experiment was promoted to a completed result.
- Re-ran the human-analysis verifier: **198 source choices, 11 eligibility rows, 93 pair/item summaries, and all three request-weighted means** agree with the completed workbook; no Excel errors.
- Re-ran construction and runtime evidence audits, including **24 generation trials, 21 trajectories, 1,512 actions, 1,365 successes, and 398 inventory/location-changing successes**.
- Source verification follows the actual `\input` graph for each document, rejects orphaned sections and wrongly scoped references, and checks each local bibliography separately.

The following notes record the earlier combined 21-page release and its human-evaluation audit. That split-only version had a 12-page main paper and 10-page supplement; the current mechanism-focused revision is described at the top of this file.

## Earlier combined release

- Downloaded the organizer's eleven returned PDFs from the existing GitHub repository. All contain seven pages, four cover fields, and eighteen valid item choices.
- Checked all returned page content streams, text and embedded visual objects against the distributed PDFs: **77/77 unchanged**. Checked field values against the selected appearance states: no answer disagreement.
- Eligibility: **10 included, V04 pending cover confirmation**. Missing checkboxes remain missing. No answers were imputed; no response was excluded based on preferred source.
- Recalculated `Results_Completed.xlsx` with LibreOffice. Independently compared **198 original choices, eleven participant statuses, 93 pair/item summaries, and all three equal-request means** against Python analysis. No Excel formula errors or external workbook links.
- Architecture main estimates: **0.400, 0.325, 0.375**. Denominators: 20, 20, 19 judgeable comparisons; all ten requests have judgeable evidence for all items. One fit abstention is kept separately. Raw wins/ties/losses remain available.
- Manuscript: **29 used references, 43 distinct labels, 14 figure PDFs**. No unresolved citations/references, missing glyphs, overfull boxes, alignment errors, or font-shape errors. Standard underfull line-spacing notices remain; they are not data or clipping errors.
- Existing evidence arithmetic still matches the frozen records: 49/56 action results, 53 two-round events, 1,052 historical events; 24 archived generations and 21 longer trajectories with 1,365/1,512 successful actions and 398 inventory/location-changing successes.
- Visually inspected the full manuscript page contact sheet and the returned V04 cover and V01 answer page. Figures distinguish image preference from world structure; full pairwise counts accompany the sparse matrices.

The checks establish faithful extraction, eligibility filtering, arithmetic, artifact preservation, and document consistency. They do not verify respondent identities, representative sampling, causal architecture effects, or independent human-subjects approval. The organizer reports online unpaid volunteers; an approval/exemption record and measured completion times were not supplied. The resulting paper states those limits.

## Model-focused presentation correction

Added and independently accounted for all 21 model/item roll-ups from the 120 included image choices. Each pair contributes to two model summaries: per-item comparison counts sum to 80, wins equal losses, and preference points sum to half the total judgeable exposures. The separate model workbook keeps exact pair data alongside the descriptive summary. Original answer data, eligibility exclusions, spreadsheet formulas, and all internal-control outcomes remain unchanged. Recompiled the 21-page manuscript without unresolved references, overfull boxes, or font errors. The internal procedure table and figure are now in the appendix; model summary and pairwise matrices are in the main human-evaluation section.
