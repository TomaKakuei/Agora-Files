# Document-Based Human World Evaluation

This protocol evaluates generated world artifacts only. Raters receive either
the English or Chinese questionnaire PDF and do not open Agora, watch a run, or
score agent behavior. Each world is represented by the same evidence fields:
the source premise, one world map, one representative character sheet, rules,
activity loops, places, people and motives, objects, and possible player
actions.

## Administration

1. Recruit at least 30 raters who can read the selected questionnaire language.
2. Assign start codes A--E evenly (six raters per code for a 30-person study). A rater starts at that world,
   continues alphabetically, and wraps after E. This balances position while
   preserving one self-contained document.
3. Ask each rater to finish a world's evidence and response pages before moving
   to the next world. Do not provide model identities or system results.
4. Enter one row per rater-world pair in `responses_template.csv`.

## Measures

Items Q1--Q6 are equal-weight dimensions on a five-point anchored scale:

- premise realization;
- systemic coherence;
- society and character;
- spatial and material specificity;
- meaningful interaction possibilities visible in the world design;
- visual coherence.

For each rater-world pair, compute the primary World Quality score as
`25 * (mean(Q1:Q6) - 1)`, giving a 0--100 scale. Q7 is an overall judgment and
is reported separately. The three short responses capture an imagined first
action, the world's most distinctive element, and one element to improve.

## Reporting

Report each world's six dimension means, the primary World Quality mean with a
95% participant-bootstrap interval, and the separate Q7 distribution. Report
ordinal Krippendorff's alpha across raters for Q1--Q6. Code the first-action
responses into action families and the two design comments into recurring
themes; retain representative responses after removing identifying details.

English and Chinese forms use matched evidence and matched item meanings. Record
questionnaire language and report the two language groups separately as well as
the pooled result.
