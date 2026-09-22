# Visual world survey: 11 English participant packets

Updated 2026-09-22. This **replaces the text-heavy Q01-Q11 instrument** for the requested image and world-structure study. It uses new codes **V01-V11** and a separate blank English workbook. No human results are included.

## Files to use

- `Visual_Survey_11_Participants.zip`: 11 fillable PDFs and 11 editable Word files. Give each of 11 people only their own numbered packet, in either format.
- `Results_Entry.xlsx`: researcher-only entry and automatic descriptive summaries. Enter cover answers on **Participants**, then **A / B / Same / Not sure** on **Responses**. All input cells are blue and initially empty.
- `participants/Survey_V01.pdf` through `Survey_V11.pdf`: **7 landscape A4 pages each**, including one short introductory page.
- `Researcher_Complete_Package.zip`: instruments, workbook, frozen sources, allocation and build/validation scripts. Do not distribute this complete package to participants.

Each person sees **4 image comparisons and 2 structure comparisons**, with only **3 short questions per page: 18 choices total**. There are no long rules, inventories, JSON fields or programming questions to read. The PDF has real clickable radio buttons and checkboxes; it can also be printed. Word answers are editable cells. All participant instructions, questions, options, filenames and workbook sheets are in English. The estimated 10-15 minutes has not yet been measured with human participants.

Preview an [image comparison](preview_images.png), a [structure comparison](preview_structure.png), or the [complete V01 PDF](participants/Survey_V01.pdf).

## What the pictures and diagrams represent

**Image comparisons:** genuine archived maps and character images from seven existing Gemini/GPT model runs on the same promise-city prompt. The recorded world maps are displayed whole. Each side shows the first two requested characters, using their first idle-down atlas frame with equal framing. The images are not retouched, replaced, regenerated or selected for beauty. These are visual outputs of the existing complete pipeline, including its shared image generator, rather than a claim that the language model itself rendered the pixels.

Only the first of the three archived model prompts has matched rendered assets. The new image study therefore covers **21 pairs on this one scene**, not the old text study's 41 pairs across three prompts. All 21 visual pairs appear twice; one seed-selected pair appears four times, giving 44 judgments. The missing Luna world is not fabricated. The workbook does not turn absent generations into human preference losses.

**Structure comparisons:** full Agora versus single-pass generation, using the same 10 paired archived requests and their fixed first replicates. Each diagram contains every source room, the number of characters whose `home_base` names that room, and the number of large scene components; the first component's label is shown as an example. A single shared drawing style represents both conditions. Tree lines mean **world-to-place containment**, not paths or physical adjacency. The diagrams do not claim to show a room-connection graph, behavior over time or runtime navigation.

There are no matched rendered images for these single-pass baselines. **No unrelated picture or newly invented baseline artwork is substituted.** Image quality and structure judgments stay separate in the workbook. Both architecture outputs have readable source data even when an objective contract check failed, so source failures do not silently remove a condition from human review.

The short scene line is a plain-English summary of the shared original request, identical for A and B. Original requests and the full world records remain available for audit. Room labels and counts come from the original outputs, not a rewritten story.

## Allocation and endpoints

- Eleven people, six distinct pairs per person; no one sees the same exact pair twice.
- 44 image ratings: 20 exact pairs get two people each and one pair gets four. Every pair has A/B orientations exactly balanced.
- 22 structure ratings: nine requests get two people each and one gets four. Every participant sees Agora on A once and on B once; every request is orientation-balanced.
- The two page types rotate in order. Extra pairs and allocation are fixed with seed `20260922`, without access to human judgments. See `researcher_only/dataset.json`.
- Q1 is **Which world would you rather explore?** It measures stated interest from the supplied evidence, not actual play experience. Image diagnostics are map readability and character-world fit; structure diagnostics are world clarity and place-scene fit. Do not merge these different diagnostics or add the three items into a validated scale.

Preference for the canonical first source scores 1, Same scores 0.5, preference for the other source scores 0. Not sure is missing preference and is counted separately. All raw four-way choices remain in the workbook. Structure summaries weight the 10 requests equally and appear only when all ten have judgeable votes for that item. Image results are reported separately for each pair on the one shared scene.

The primary population requires a returned packet, adult/English/consent confirmation, no prior development or detailed-result exposure, and all 18 valid choices. Not sure is a valid choice, not an incomplete response. All exclusions remain visible; do not exclude people based on which source they prefer. No actual responses, p-values, significance stars, Elo ranking or invented confidence intervals are supplied.

**Eleven people support a small exploratory artifact study.** Two or four judgments per visual pair are not a stable model ranking. Image results do not generalize to the two prompts lacking images. The architecture comparison retains the original unequal total generation budgets; it is not a compute-controlled causal estimate.

## Administration

Use `INVITATION_TEMPLATE.txt` to supply a contact, return channel, retention arrangement and compensation information. No new personal identifiers or comments are requested in the questionnaire. Returning a file via email/chat may reveal the sender to the recruiter; keep those contact records separately.

Distribute one V-code file per person, without researcher identities, scores or expected winners. Respondents choose one PDF or Word copy and return it once. The PDFs do not transmit data. Printouts can be scanned or photographed. Some basic PDF viewers do not save form edits; use a viewer that saves completed forms, or use the supplied Word/print alternative.

Do not combine V-code responses with old Q, S or P versions. The previous text-heavy instrument has been superseded for this task. A change after piloting should receive a new version; do not silently mix instruments.

## Source limitations

Character sampling is restricted to the first two requested characters for all seven models, to keep the survey short and matched. Terra has only two publishable characters among three requested; the third's failure is recorded in the private dataset, and is not shown as a made-up character. This study does not evaluate animation, the omitted third character, visual completion of every requested asset, or human interaction with a running world. Source asset revisions include their original pipeline repair steps; judgments apply to those archived final assets.

Structure is a deliberately simplified view of place membership and props. It does not measure social-relationship quality, institutional causality or full spatial topology. The source records permit later studies of those different constructs.

## Rebuild and verification

`prepare_materials.py` originally froze the local experiment assets and recorded SHA-256 hashes. The release contains those frozen inputs, so they are sufficient for the document renderer and workbook generator. Re-running source preparation needs the original workspace paths listed in its manifest.

```bash
# This workstation has ReportLab/Pillow in system Python and spreadsheet
# libraries in its default Python environment.
/usr/bin/python3 render_surveys.py
python build_workbook.py
python validate_release.py
python package_release.py
```

The scripts need ReportLab, Pillow, XlsxWriter, openpyxl, LibreOffice and Poppler. No new model calls or generated research outcomes are involved. Verification checks source hashes, exact structure counts, balanced allocation, English-only participant text, genuine empty PDF fields, page bounds, Word rendering and actual spreadsheet recalculation on temporary synthetic inputs.

An additional `python verify_pdf_interaction.py` check requires Playwright with Firefox and verifies real form selection, saved PDF bytes and reopened answers. Test files are temporary and are deleted.
