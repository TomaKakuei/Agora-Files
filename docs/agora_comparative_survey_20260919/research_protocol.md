# Comparative artifact study protocol

Status: ready for pilot administration; not externally preregistered and no human outcomes collected. The source generation corpus is historical. Freeze the final instrument, material hashes, sample target, exclusion rules, and analysis before formal human responses. Record any pilot-driven amendment as a new version; do not mix versions silently.

## Questions and estimands

- Model comparison: perceived written-design preference for existing successful artifacts produced by different recorded models through the same Agora generation graph, conditional on the same prompt and available artifacts.
- Architecture comparison: perceived written-design preference for full compositional Agora versus single-pass generation on ten shared archived requests. Compare complete systems at their actual, unequal total computation. This does not identify a compute-controlled effect of decomposition or a temporal old/new-version effect.
- Primary item: overall world design. Five separate secondary items diagnose premise realization, rules/activities, people/social connections, places/objects, and possible actions. The dimensions are not summed into a validated psychological scale.
- No claims about visual quality, runtime success, human co-play, long-term memory, real social fidelity, or novel-prompt generalization follow from this instrument.

## Corpus and selection

Model corpus: 24 attempted generations (8 models × 3 prompts, one archived replicate each). All 17 complete worlds are included, yielding 41 within-prompt pairs. No generated world exists for Luna; two other models only have the first prompt available. Keep all seven failed attempts visible in the objective completion table. Do not impute human dislikes for absent artifacts or present conditional preference as unconditional model quality.

Architecture corpus: all 10 first-replicate pairs, chosen by replicate index before any human judgments. Both arms have readable builder specs. A failed compilation/contract check does not remove existing textual material; record completion separately. This differs from the paper's majority-over-three world completion statistic. The shared original request JSON is verified identical for each pair. Briefs may contain several sentences and authoring constraints.

Source-derived display rules apply to every artifact: concept 60 words; first three rules at 28 words per displayed subfield; first two loops, label/summary/pressure at 28 words each; first three characters, identity/role at 12 words each and goal at 30; first three rooms, name 12 and purpose 28; first three objects, name/description at 20 each; first three actions at 24 per subfield; first two player entries at 28 per subfield. Source order is retained. No aesthetic selection, generated paraphrase, fallback world, or source-specific field quota is allowed. Evidence is English in both interface languages. The selected excerpts evaluate standardized views, not exhaustive world contents.

## Allocation and blinding

The public file contains only random candidate/pair IDs and source text, without model/method identities, objective scores, or compilation labels. Keep the decoding key and this protocol away from participants during collection. Blinding hides identity labels; source style can still reveal clues. Recruiters should not announce the hoped-for winner.

Each participant receives 2 model and 2 architecture comparisons. The 41-code base schedule presents every model pair twice, once in each A/B orientation. A mirrored second schedule reverses both position and presentation order. Across S001–S082 every model pair is seen four times, and every architecture pair 16 or 18 times. Within each pair, orientation is exactly balanced. The overall order alternates comparison types, with both types occurring first. A participant never receives the same pair twice, though a prompt or artifact may recur with a different opponent. Record this dependence through participant-level analysis.

The 82-code schedule is a coverage plan, not a power guarantee. Predeclare the actual participant target before formal collection. With only four ratings per exact model/prompt pair in one cycle, model results are exploratory; inspect intervals and raw counts. For greater precision, replicate the complete schedule with new unique participant IDs before collecting further data. Do not reuse a code or decide to stop because a preferred winner becomes significant.

## Pilot and participation

Use P001–P008 for 5–8 pilot participants; these codes never enter formal analysis by default. Ask participants afterward whether any item was unclear, how long it took, and whether they interpreted “insufficient evidence” as intended. Changes following pilot feedback require re-freezing the instrument and new materials where necessary.

Recruit adults able to independently read the English evidence. Do not require AI expertise or recruit only developers. Record coarse game experience and prior exposure. Before distribution, the researcher supplies a contact, a return channel, retention period, any compensation, and institutional human-study requirements. The instrument contains voluntary consent, skip/exit options, withdrawal-by-code instructions, and a separate optional quotation permission. It does not assert an ethics approval that has not been obtained.

## Predefined analysis

Decode identities only after frozen response validation. Primary population excludes pilot codes, ineligible/no-consent responses, and participants answering yes/unsure to previous development or detailed-result exposure. Save all exclusions and separately disclose any sensitivity analysis including exposed participants. Duplicate codes or mismatched assignments are validation errors to resolve explicitly. Do not exclude low ratings, ties, abstentions, or short completion times based on desired outcomes.

For the primary endpoint, a preference for condition 1 scores 1, a tie 0.5, and a preference for condition 2 scores 0. “Much” and “slightly” are pooled for this predeclared endpoint, while their original ordinal distribution is retained. Insufficient evidence is missing for preference, not a tie or zero; report its rate by pair and dimension. The optional both-poor response diagnoses ties at low perceived quality and is never used to reclassify the primary endpoint.

Report each prompt separately. For an architecture summary, compute the unweighted mean of the ten prompt-specific preference estimates. For each model pair, average only its common predeclared prompts, with prompt-specific counts and coverage. No comparison involving a one-prompt model is generalized to the three-prompt corpus. Missing prompt coverage must be clearly flagged; a partial average is provisional rather than the planned full summary.

Resample participants with all of their ratings together (2,000 draws, fixed seed). Within each draw recompute prompt-specific means and then the macro mean. A draw lacking a rated fixed prompt is discarded; with fewer than 80% valid draws, suppress the interval rather than silently change the estimand. These intervals reflect participant variation conditional on this fixed corpus, not generation randomness or unseen prompts. Three model prompts and one generation per cell cannot support broad model-population inference. Do not treat four responses from one participant as four independent participants. Report language and experience composition; language-specific analyses require adequate coverage and are descriptive.

Do not pool six dimensions as repeated ratings of one construct or compute one Krippendorff alpha across them. Inter-rater disagreement may be substantive preference variation. No confirmatory significance tests, automatic Elo leaderboard, or multiplicity-unadjusted significance stars are planned for this small corpus. Qualitative comments may be coded transparently; quoting requires separate consent and identity review.

## Data handling and reproducibility

The HTML performs no network requests. Drafts are stored on the participant's browser, and JSON is explicitly downloaded. Return channels and their metadata are administered by the researcher; do not claim that an email return is anonymous to the recruiter. Keep recruitment/contact records separate from coded research responses. The supplied analysis produces a private row-level CSV and aggregate CSVs. No raw response publication is implied by consent to aggregate research use.

Source records, hashes, exact original requests, candidate maps, schedule, generation script, response validator, and analysis script are supplied to the researcher. A participants-only ZIP excludes every decoding key and researcher source file. Synthetic software tests are kept in temporary directories and never enter the paper.

References: Howcroft et al. (2020), https://aclanthology.org/2020.inlg-1.23/; Chiang et al. (2024), https://arxiv.org/abs/2403.04132; Kapoor et al. (2024), https://arxiv.org/abs/2407.01502.
