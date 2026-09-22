# Validation — 2026-09-22

All respondent inputs in the released PDFs, Word documents and Excel workbook are blank. No actual participant outcomes are supplied.

## Materials and source mapping

- 49 frozen source files have verified SHA-256 values: 7 genuine world maps, 14 genuine character atlases, 27 world specifications and the original visual-case manifest.
- For all seven visual conditions, asset-manifest world IDs match the frozen world specifications. Original recorded model-to-world builder paths have byte-identical builder contents to the copies used here.
- Every structural room name, resident count, prop count and example label matches the underlying specification. All source rooms are included, and no home assignments or room-to-room routes are invented.
- Regenerating allocation reproduces all 11 schedules. Each person receives four image and two structure rounds without duplicate exact pairs.
- All 21 image pairs are covered: 20 twice, one four times. All 10 structure pairs are covered: nine twice, one four times. Every exact pair has balanced A/B orientation; Agora is A once and B once for every participant's two structure rounds.

## Participant files

- Eleven native fillable PDFs, exactly seven pages each; 22 named fields per PDF (3 consent/eligibility checkboxes, 1 prior-exposure radio group, 18 preference groups). No answer is selected by default.
- Eleven Word documents opened successfully in LibreOffice Writer and exported to seven pages each. Each contains six image-based comparison panels and 18 editable answer cells.
- All participant text and workbook text are English-only. No model/method identity labels occur in extracted participant PDF text. This is label blinding; it cannot rule out guesses based on visual style.
- All 10,290 extracted PDF word boxes are within their pages. Comparison pages contain 62–269 extracted words including place labels, diagram counts, scene, questions and repeated answer choices; they have no long evidence paragraphs.
- The cover, actual image page and structure page were visually inspected. World maps preserve the full source image; character crops use the same exact recorded 64 × 64 idle frame for every sample.

## Interactive PDF verification

`verify_pdf_interaction.py` used Firefox's real PDF viewer to check consent, select A / B / Same / Not sure in distinct groups, save the modified PDF bytes with the viewer's own `saveDocument()` operation, and reopen that file. All selected answers persisted and untouched questions stayed blank. Firefox's native OS Save dialog was not automated; the document save/serialization and reopening were verified directly. The synthetic filled file was deleted from its temporary directory.

## Workbook verification

- Six English sheets, 11 registration rows, 66 comparison rows and **198 blank choice cells**. No external workbook links or macros.
- Seven temporary synthetic workbooks were actually recalculated by LibreOffice Calc, covering: empty input; all Source 1 preferences; all Source 2 preferences; Same plus Not sure on separate items; eligibility/exposure/missing/invalid exclusions; all Not sure; and a missing structure scene.
- No formula errors occurred. Canonical preference values were respectively 1, 0 and 0.5 as expected; Not sure was excluded from preference denominators and counted separately. Raw A/B choices were correctly decoded even when display positions reversed.
- Only the four valid packets entered the exclusion test; no low score, tie or abstention was used as an exclusion criterion.
- A structure scene with no judgeable Q1 votes caused coverage to report 9/10 and suppressed the complete equal-request mean. Empty templates did not display fabricated zero preferences.
- Word/Calc checks used LibreOffice 6.4.7.2, not Microsoft Office desktop. Browser verification used the installed Playwright Firefox build.

These checks establish file, instrument and calculation correctness. They are not human study results and do not make a small exploratory study a stable model ranking.
