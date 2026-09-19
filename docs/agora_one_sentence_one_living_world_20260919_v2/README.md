# Agora: One Sentence, One Living World — evidence revision 2

Revised September 19, 2026. The earlier September 19 and September 9 releases remain intact.

- [Paper PDF](agora_one_sentence_one_living_world_20260919.pdf)
- [Chinese revision notes](REVISION_NOTES_V2_ZH.md)
- [Source citation ledger](CITATION_AUDIT.md): 29 cited primary-source references
- [Separate comparative questionnaire](../agora_comparative_survey_20260919/README_ZH.md)

This revision adds a reproducible retrospective audit of 24 existing cross-model generation trials and 21 existing scripted 24-round execution traces. It does not make new model calls or report uncollected human results. It corrects the scope of the earlier multi-sentence input briefs and distinguishes centralized block planning from locally observed agent interaction.

## Build and verify

```bash
bash build.sh
python figure_sources/reproduce_and_verify.py
```

The build runs XeLaTeX/BibTeX and validates citations, labels, figure paths, earlier evidence arithmetic, and the new raw-record audit. Figure reproduction regenerates all 12 PNGs and verifies their bytes in the current font/Matplotlib environment. The new audit also runs independently:

```bash
python figure_sources/audit_extended_evidence.py --check
```

`figure_sources/input_snapshot/extended_evidence/` contains all 24 generation result records, all 21 raw trajectory bundles, interpretive source-code snapshots, and source hashes. No identity-visible model-judge scores are used in the added findings. `human_evaluation_legacy/` retains the old September 9 forms only as historical material; distribute the separate new comparative questionnaire instead.

This remains a standalone preprint. A venue-specific submission still requires the target workshop's official template, anonymity rules, and page limit. No manuscript was submitted or published by this revision.
