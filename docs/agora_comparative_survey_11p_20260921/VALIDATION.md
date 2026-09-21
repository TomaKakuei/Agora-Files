# Validation · 2026-09-21

No human responses are included. All spreadsheet test responses were explicitly synthetic, generated under a temporary directory, and deleted after verification.

## Instruments and allocation

- 11 distinct participant codes, Q01–Q11; each receives 4 model comparisons and 2 architecture comparisons, without a repeated exact pair within their packet.
- All 41 available exact model/prompt pairs are covered by 44 ratings: 38 pairs once, 3 pairs twice. All 10 architecture requests are covered by 22 ratings: 9 twice and 1 four times.
- Each participant sees model prompt 1 twice and prompts 2 and 3 once each. Their two architecture comparisons place Agora on A once and on B once.
- The three repeated model pairs and all architecture pairs have exactly balanced A/B positions. Across all model assignments, canonical condition 1 appears on A and B 22 times each.
- Regeneration with seed 20260921 reproduces the complete frozen allocation. Source payload/key/provenance SHA-256 values match the original 2026-09-19 corpus.

## Word and PDF

- 11 DOCX documents successfully opened and converted by LibreOffice Writer 6.4.7.2; each corresponding PDF has exactly 19 pages, 209 pages total.
- Each displayed prompt and every evidence row matches its frozen source text in both DOCX XML and extracted PDF text, after PDF whitespace/Unicode normalization. Explicit A/B identity and scene headings match the schedule.
- No model identifiers, method identifiers, source paths or decoding-key labels are present in participant text. This validates label blinding, not inability to infer origin from writing style.
- All 61,309 extracted PDF word boxes are inside their page boundaries. The cover, scoring page and longest evidence page were also visually inspected.
- No answers are prefilled. Materials, questions and scoring codes are consistent across Word, PDF and Excel. Word pagination can vary with the recipient's fonts; the bundled PDF is the fixed-page reference.

## Workbook

- 7 sheets; 11 participant registration rows; 66 comparison input rows; 6 primary/diagnostic rating fields per row, totaling 396 raw rating fields. All respondent input cells are blank in the release template.
- 3,251 formulas; no external workbook links. Input cells are unlocked, formula cells locked, and rating/background validation lists are present.
- **Actual recalculation in LibreOffice Calc**, with errors checked across all sheets, passed eight synthetic cases:
  1. Empty template: no participants included, no preference means invented.
  2. Every response favors canonical condition 1: all decoded preference values and complete macro means equal 1, regardless of A/B placement.
  3. Every response favors canonical condition 2: corresponding values equal 0.
  4. Ties on five items and unable on the sixth: ties equal 0.5; unable values are absent from preference denominators and counted separately.
  5. Prior exposure, uncertain exposure, denied consent, missing background, invalid rating, missing rating and unreturned packet: only the four remaining eligible, complete packets enter analysis.
  6. All answers unable: eligible participation is retained, means remain blank, all votes are reported as unable.
  7. One architecture request has no judgeable primary votes: full 10-request macro mean is suppressed and coverage reports 9/10.
  8. All six score choices serialized as text: still accepted and decoded correctly; an independently computed prompt-weighted architecture mean matches the spreadsheet.
- Within each item/pair, total = judgeable + unable, and judgeable = condition-1 wins + ties + condition-2 wins.
- Excel uses standard formulas and automatic calculation. Tests used LibreOffice, not the Microsoft Excel desktop application; no macros or provider API calls are required.

These are software/material checks, not participant outcomes or statistical evidence that 11 people yield a stable model ranking.
