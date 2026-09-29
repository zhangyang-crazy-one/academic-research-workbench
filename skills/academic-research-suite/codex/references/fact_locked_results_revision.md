# Fact-Locked Results Revision

Use this protocol when an author asks to make existing results easier to read
without changing them. Typical phrasings: "foreground the comparisons",
"make the improvement magnitude clearer", "say which baseline and metric each
number compares", or "rewrite the result descriptions and captions but keep
every number".

It is an author-side revision profile under `ars/academic-paper/WORKFLOW.md`
(`revision` mode). It is **not** a reviewer action: the reviewer read-only rule
still applies to `academic-paper-reviewer`.

## Scope Lock

Allowed edits:

- result paragraphs, table and figure captions, and the prose that discusses
  tables and figures;
- result sentences in the abstract, contribution list, and conclusion, when
  they restate reported results;
- a comparison-key table that contains labels only (no values);
- layout-only table changes: row order, text-column order, alignment, and
  minus-sign normalization;
- mechanical fixes found by `scripts/check_manuscript_hygiene.py`, such as
  hard-coded `Section 4.1` or `{[}4{]}` becoming `\ref`/`\cite`, and
  unreferenced figures gaining an in-text reference.

Forbidden edits:

- any new numeric value, including derived ratios, relative percentages,
  differences not already reported, counts of table cells, or rounded
  variants of reported values;
- deleting a reported value, unless it is recorded as an explicit waiver;
- moving a value to another table row, arm, view, cohort, or metric;
- changing the comparison direction, sign, uncertainty statement, post hoc or
  exploratory status, or conditional/common-valid status of a result;
- upgrading associational wording ("is associated with", "observed
  contrast") to causal or mechanistic wording ("drives", "lever", "causes");
- new experiments, new analyses, or new sources.

## Comparison Tuple

Open every result paragraph with the full comparison tuple:

| Slot | Question the sentence must answer |
| --- | --- |
| Treatment | Which method, arm, or condition? |
| Reference | Which baseline or reference arm? |
| Metric | Which metric, with what scoring rule? |
| Evaluation set | Which dataset, cohort, split, or partition? |
| Condition | Which evaluation view, protocol, or setting (for example acquisition view, candidate pool, decoding settings)? |

When several results share most slots, state the shared slots once in a
section opener or a comparison-key table, then open each paragraph with the
slots that vary.

## Emphasis Dimensions

Organize each comparison with the dimensions below. Include only those the
reported numbers support.

1. **Magnitude.** Lead with the size of the difference and its interval.
   Multiplicative wording is allowed only when it can be checked directly
   from the reported numbers and does not print a new value. For example,
   "more than doubles" is allowed when treatment > 2 × reference;
   "more than an order of magnitude larger" is allowed when one contrast
   exceeds ten times the other. If the claim fails in any view you mention,
   use weaker wording such as "the relative gain is largest on …".
2. **Pattern.** Say where the difference comes from using reported
   components: precision versus recall, false positives versus true
   positives, or per-stratum rows.
3. **Consistency across conditions.** State direction and size across the
   reported partitions, views, and sensitivity analyses. Name every
   exception explicitly. Say which intervals include zero; never let a
   consistent sign stand in for a reliable effect.
4. **Output availability or other confounds.** Keep the source's statements
   about failures, conditional intersections, and execution differences next
   to the results they qualify.
5. **Practical meaning.** Translate the contrast into a design implication
   in the source's own register, bounded by the scope limits the source
   already states.

## Gate

Run both checks before presenting the revision:

```bash
python3 skills/academic-research-suite/codex/scripts/check_fact_locked_revision.py \
  --source <original.tex|md> --revision <revised.tex|md> \
  [--allow-drop <value> ...] --json

python3 skills/academic-research-suite/codex/scripts/check_manuscript_hygiene.py \
  <revised package dir> --json
```

`check_fact_locked_revision.py` reuses the upstream #570 extractor in
`ars/scripts/check_revision_token_conservation.py`. It fails on new values
(F1), unwaived dropped values (F2), source table rows whose numbers no longer
survive together (F3), and citation-token changes (F4). A new label-only row
is a warning. Each `--allow-drop` must carry a reason in the change log, for
example "LaTeX column width" or "erroneous cross-reference replaced by
`\ref`".

A PASS is necessary, not sufficient. Complete the semantic checklist that the
report prints: attachment of every number to the same arm, view, and metric;
direction; verifiable multiplicative wording; surviving qualifiers; and no
causal upgrade. Record the result in the change log.

## Deliverables

- The revised file, written next to the original (never overwrite the
  frozen manuscript).
- A change log with:
  - base and revision hashes;
  - the gate reports;
  - each waived drop and its reason;
  - every wording change that the semantic checklist flagged and how it was
    resolved;
  - the sections left untouched;
  - open items for the author, such as length growth against a page limit
    and TeX compilation still pending.

## Real-Use Provenance

This profile came from a 2026-09 pre-submission review of a 32,521-source
taxonomy-discovery manuscript. The author asked for exactly this rewrite. The
first draft passed the naive number-set check but still contained three
semantic slips, which the checklist caught:

- a "roughly triples" claim that held in one view only;
- a range ("29 to 31 points") that printed two new values;
- a causal "dominant lever" phrasing.

The same draft also silently dropped a reported validity rate, which F2
caught.
