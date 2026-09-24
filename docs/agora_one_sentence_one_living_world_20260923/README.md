# Agora: One Sentence, One Living World — September 23, 2026

The preprint is maintained as a **12-page main paper** and **11-page supplement**, each with its own LaTeX entry, PDF, and bibliography. The main paper develops the mechanism connecting premise-generated world structure, situated actions, coordinator checks, and persistent consequences. The existing visual survey remains in the results, with its complete protocol in the supplement. Earlier dated paper and questionnaire releases remain intact.

- [Main paper PDF](agora_one_sentence_one_living_world_20260923.pdf) — 12 pages, including references
- [Supplement PDF](agora_one_sentence_one_living_world_20260923_supplement.pdf) — 11 pages, S1–S11
- [Standalone TeX package](../agora_one_sentence_one_living_world_20260923_tex.zip) — main paper, supplement, required figures/tables, bibliography, and a TeX-only build script
- [Main LaTeX entry](agora_one_sentence_one_living_world_20260923.tex) / [supplement LaTeX entry](agora_one_sentence_one_living_world_20260923_supplement.tex)
- [Current manuscript status (Chinese)](STATUS_ZH.md)
- [Supplementary planner diagnostics and complete ablation records](llm_ablation/README.md)
- [Model-comparison results Excel](human_evaluation/Model_Comparison_Results.xlsx)
- [Complete response workbook, including internal controls](human_evaluation/Results_Completed.xlsx)
- [Human-study results and reproducibility](human_evaluation/README.md)
- [Checks and limitations](VALIDATION.md)
- [Chinese revision notes](REVISION_NOTES_ZH.md)
- [29-reference citation ledger](CITATION_AUDIT.md)

Eleven PDFs were returned. Ten satisfy the released cover requirements; V04 contains all answers but leaves adulthood, English, consent, and prior-exposure confirmations blank. The organizer reports a forgotten cover, online volunteer recruitment, and no compensation. V04 remains pending participant confirmation and contributes no analytical votes.

The existing human-evaluation study contains **40 image comparisons, all 21 pairs among seven model configurations, and 120 item responses**. Exploration, map readability, and character fit are reported with the exact-pair counts. These judgments characterize preserved artifacts from the same Agora pipeline and premise; sparse, unequal opponent weights limit their interpretation.

The other **20 structure comparisons are an internal generation-procedure control**, not Agora versus an independent world-generation system. Their entire protocol, unfavorable results, and figure are retained in the supplement. Both conditions use Agora's representation; unequal budgets prevent a compute-controlled causal claim. **Human comparisons of world structure across the seven models were not collected.** The image questions cannot fill that gap.

## TeX package

Download the 45-file [TeX package](../agora_one_sentence_one_living_world_20260923_tex.zip), extract it, and run `bash build.sh` with XeLaTeX and BibTeX on PATH. This package compiles both documents without Python, experiment data, or model calls. Each original packaged file has a checksum in `SHA256SUMS.txt`. Packaging instructions are in [TEX_PACKAGE_README.md](TEX_PACKAGE_README.md); regenerate the archive using `python make_tex_package.py`.

## Build and verify the full evidence bundle

```bash
bash build.sh
python human_evaluation/verify_analysis.py
python human_evaluation/summarize_models.py
```

The released PDFs and tables are ready to read. `bash build.sh` builds both documents, resolves their two-way references, and replays all 18 frozen ablation trajectories locally; it makes no new model calls. Building uses XeLaTeX/BibTeX and the existing Python figure dependencies. `build.sh` checks bibliography keys, cross-references, figure assets, LaTeX diagnostics, and the archived construction/execution arithmetic. The human verifier independently checks the spreadsheet's recalculated results against decoded PDF choices.

To regenerate human tables and figures from the original returned PDFs, follow [human_evaluation/README.md](human_evaluation/README.md). That process uses pypdf, openpyxl, matplotlib, numpy, and LibreOffice; it does not make model calls. The package includes the source archive and frozen allocation.

This is a **standalone research preprint**, with 12 main-paper pages and 11 supplementary pages, including each document's references. No particular workshop template, anonymity requirement, page limit, approval, exemption, or submission is implied. An ethics review/exemption record and measured completion times were not supplied; these gaps are explicitly stated in the manuscript.

## Editing the two documents

- Main narrative: `sections/introduction.tex`, `method.tex`, `results.tex`, `human_results.tex`, `extended_results.tex`, and `discussion.tex`.
- Supplementary content: `supplement/repro.tex`, `extended.tex`, `ablation.tex`, `historical.tex`, `human.tex`, `internal_generation_control.tex`, `intervention.tex`, `cases.tex`, and `tidal.tex`.
- Shared resources: `paper_style.tex`, `references.bib`, `figures/`, and automatically generated tables in `sections/generated/`. These tables remain at their existing paths so the original analysis scripts can regenerate them.

The main paper cites supplementary labels as `supp-…`; the supplement cites main-paper labels as `main-…`. Local labels have no prefix. Supplementary sections, figures, tables, equations, and pages use S numbering. Bibliography numbering is independent (28 main-paper works, 4 supplementary works, 29 distinct works overall). The build does not import the other document's bibliography.

Keep both PDFs in the same directory for cross-PDF links; whether a link opens the companion PDF depends on the viewer. Run `bash build.sh` after changing either source so both sets of auxiliary labels are current. No manual copying of reference numbers is needed.

## Mechanism evidence and supplementary diagnostics

The main argument follows three links: shared representation contracts and local repair; generated action opportunities and contextual proposals; coordinator checks followed by persistent state updates. An archived Clockwork example traces a proposed item transfer through its committed mutation to the next planner observation. A rejected unowned transfer provides a failure example. The supplement records the source events and illustrative selection rule.

The human study is fixed at its existing scope. All **18 additional LLM trajectories, 108 planned calls, and 1,296 planned action slots** are retained. Their aggregate and per-trajectory configuration tables are in the supplement, alongside the full ablation protocol and interpretation limits. These diagnostics describe the planner and handlers; they do not rank the value of the proposed mechanism. All raw plans and state transitions are included and replay-checked.

The earlier local-memory intervention remains a future-work protocol in the supplement. Current human-study limitations remain stated; additional recruitment and new performance comparisons are outside this revision's scope.
