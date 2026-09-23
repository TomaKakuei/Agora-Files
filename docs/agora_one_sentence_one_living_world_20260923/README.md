# Agora: One Sentence, One Living World — September 23, 2026

This complete preprint incorporates the returned English visual survey into the abstract, evaluation design, results, discussion, conclusion, and appendix. Earlier paper and questionnaire releases remain intact.

- [Paper PDF](agora_one_sentence_one_living_world_20260923.pdf)
- [Completed results Excel](human_evaluation/Results_Completed.xlsx)
- [Human-study results and reproducibility](human_evaluation/README.md)
- [Checks and limitations](VALIDATION.md)
- [Chinese revision notes](REVISION_NOTES_ZH.md)
- [29-reference citation ledger](CITATION_AUDIT.md)

Eleven PDFs were returned. Ten satisfy the released cover requirements; V04 contains all answers but leaves adulthood, English, consent, and prior-exposure confirmations blank. The organizer reports a forgotten cover, online volunteer recruitment, and no compensation. V04 remains pending participant confirmation and contributes no analytical votes.

The primary analysis contains **40 image and 20 structure comparisons, 180 item responses**. All 21 model-image pairs and all ten structure requests retain coverage. Full Agora's equal-request preference is **40.0% for exploration, 32.5% for clarity, and 37.5% for place–scene fit**. These exploratory structure judgments favor the baseline in aggregate; higher construction completion does not establish a human preference advantage. Images are one fixed scene with sparse per-pair ratings, not a model leaderboard.

## Build

```bash
bash build.sh
python human_evaluation/verify_analysis.py
```

The released PDF and tables are ready to read. Building uses XeLaTeX/BibTeX and the existing Python figure dependencies. `build.sh` checks bibliography keys, cross-references, figure assets, LaTeX diagnostics, and the archived construction/execution arithmetic. The human verifier independently checks the spreadsheet's recalculated results against decoded PDF choices.

To regenerate human tables and figures from the original returned PDFs, follow [human_evaluation/README.md](human_evaluation/README.md). That process uses pypdf, openpyxl, matplotlib, numpy, and LibreOffice; it does not make model calls. The package includes the source archive and frozen allocation.

This is a **standalone research preprint**, with 20 pages including references and appendices. No particular workshop template, anonymity requirement, page limit, approval, exemption, or submission is implied. An ethics review/exemption record and measured completion times were not supplied; these gaps are explicitly stated in the manuscript.
