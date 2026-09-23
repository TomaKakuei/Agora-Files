# Agora: One Sentence, One Living World — September 23, 2026

This complete preprint incorporates the returned English visual survey into the abstract, evaluation design, results, discussion, conclusion, and appendix. Earlier paper and questionnaire releases remain intact.

- [Paper PDF](agora_one_sentence_one_living_world_20260923.pdf)
- [Model-comparison results Excel](human_evaluation/Model_Comparison_Results.xlsx)
- [Complete response workbook, including internal controls](human_evaluation/Results_Completed.xlsx)
- [Human-study results and reproducibility](human_evaluation/README.md)
- [Checks and limitations](VALIDATION.md)
- [Chinese revision notes](REVISION_NOTES_ZH.md)
- [29-reference citation ledger](CITATION_AUDIT.md)

Eleven PDFs were returned. Ten satisfy the released cover requirements; V04 contains all answers but leaves adulthood, English, consent, and prior-exposure confirmations blank. The organizer reports a forgotten cover, online volunteer recruitment, and no compensation. V04 remains pending participant confirmation and contributes no analytical votes.

The main human-evaluation result is the **seven-model comparison inside the same Agora pipeline: 40 image comparisons, 21 model pairs, and 120 item responses**. A new table reports each configuration's observed exploration, map-readability, and character-fit votes; the exact-pair matrices remain. Gemini 2.5 Flash receives 8/10 exploration preferences and 7/9 judgeable character-fit preferences. GPT-5.6 Terra and Sol receive 11/13 and 9/11 map-readability preferences. The pooled per-model summary was added after collection; opponent weights differ, and it is not a general model ranking.

The other **20 structure comparisons are an internal generation-procedure control**, not Agora versus an independent world-generation system. Their entire protocol, unfavorable results, and figure are retained in the appendix. Both conditions use Agora's representation; unequal budgets prevent a compute-controlled causal claim. **Human comparisons of world structure across the seven models were not collected.** The image questions cannot fill that gap.

## Build

```bash
bash build.sh
python human_evaluation/verify_analysis.py
python human_evaluation/summarize_models.py
```

The released PDF and tables are ready to read. Building uses XeLaTeX/BibTeX and the existing Python figure dependencies. `build.sh` checks bibliography keys, cross-references, figure assets, LaTeX diagnostics, and the archived construction/execution arithmetic. The human verifier independently checks the spreadsheet's recalculated results against decoded PDF choices.

To regenerate human tables and figures from the original returned PDFs, follow [human_evaluation/README.md](human_evaluation/README.md). That process uses pypdf, openpyxl, matplotlib, numpy, and LibreOffice; it does not make model calls. The package includes the source archive and frozen allocation.

This is a **standalone research preprint**, with 21 pages including references and appendices. No particular workshop template, anonymity requirement, page limit, approval, exemption, or submission is implied. An ethics review/exemption record and measured completion times were not supplied; these gaps are explicitly stated in the manuscript.
