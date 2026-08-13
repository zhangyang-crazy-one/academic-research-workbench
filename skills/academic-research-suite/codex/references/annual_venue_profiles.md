# Annual Venue Profiles: October 2026 NLP/IR Window

Verified: **2026-08-09**. Machine-readable authority:
`annual_venue_profiles.json`.

This is a Codex-side, time-sensitive overlay for the stable venue-family packs
under vendored ARS. It does not replace a conference call for papers. Browse
the official pages again before making a submission decision.

## Resolution rule

Resolve a target in two layers:

1. Apply the **review-system profile** (for example, the October 2026 ARR
   format, anonymity, page limit, platform, and author obligations).
2. Apply the **venue-year profile** (for example, COLING 2027 commitment,
   notification, dates, location, and venue-specific call).

For a conflicting fact, use this order:

1. official venue-year page;
2. official review-system page;
3. official publisher or template repository;
4. stable venue-family pack;
5. secondary index.

Keep the displaced value and its source in the audit note. Do not silently
resolve conflicts. A profile older than 14 days is adequate only for rough
planning; deadline-dependent action always requires a fresh official check.

## Relevant October shortlist

| Target | Actual submission point | Format contract | Fit for Chinese LLM4O |
|---|---|---|---|
| COLING 2027 | ARR, 2026-10-12 23:59 AoE | ACL/ARR, long 8 or short 4 content pages | **Primary recommendation** |
| NAACL 2027 | ARR, 2026-10-12 23:59 AoE | Same ACL/ARR submission contract | Same-cycle alternative |
| ECIR 2027 full | Abstract 2026-09-21; paper 2026-10-05 23:59 GMT | Springer LNCS, 12 pages including appendices | Conditional IR/RAG reframe only |

The meeting transcription's “COLING ... 10 月 12 日 ... CCF B” advice is
consistent with the official COLING and NAACL 2027 sites. The current CCF
directory context should be checked against the institution's rule: CCF states
that its conference classification applies to full/regular papers rather than
short, demo, findings, or workshop papers.

## ARR October 2026 hard checklist

Treat every item below as a pre-submission gate:

- Use the current official ACL style files; do not modify the style or substitute
  another conference template.
- Long papers have at most 8 content pages; short papers have at most 4.
- Add a dedicated `Limitations` section after the conclusion and before the
  references. Missing it is a desk-rejection condition.
- Remove author names and affiliations. Anonymize repositories and
  supplementary materials; do not use download-tracking file-host links.
- Keep appendices after the references in the official double-column format.
  Reviewers are not required to read them, so claim-critical content belongs in
  the main paper.
- Do not submit elsewhere while the paper is under ARR review.
- Every author completes ARR reviewer registration within 48 hours after the
  deadline and fulfills any assigned review obligation.
- Complete the Responsible NLP checklist accurately and disclose applicable
  generative-AI writing or coding assistance.

COLING's official venue page gives a **2026-12-23** commitment date. Do not
replace it with ARR's **2026-12-20** cycle-end date. NAACL's official site had
not announced its commitment or notification date at verification time; retain
that uncertainty.

## Template-learning brief for the Chinese LLM4O paper

The following is **ARW editorial guidance, not an official venue rule**. Learn
the argument pattern from recent ACL/COLING/NAACL information-extraction and
resources/evaluation papers, but do not imitate surface wording.

### Paper-level argument

1. **Problem and boundary:** real schema-driven Chinese ontology recognition
   begins without task-specific gold labels; labeled-test-dependent prompt
   selection is not deployable zero-shot evidence.
2. **Method:** a reusable workflow/skill composes domain role knowledge,
   evidence grounding, schema alignment, and constrained output. Define exactly
   which information is allowed in the prompt.
3. **Evidence:** compare against matched-information baselines, then report main,
   generalization, and diagnostic evidence separately with uncertainty.
4. **Mechanism:** ablate every named module and connect each ablation to the
   failure mode that motivated the module.
5. **Boundary of claim:** establish feasibility and design conditions, not
   universal superiority or fully autonomous ontology construction.

### Main-paper artifact plan

- **Figure 1 — Task and leakage boundary:** one Chinese source example, schema
  card, permitted knowledge, forbidden gold/test information, and target
  structured output. A reader should understand what “ontology recognition”
  means without reading the method section.
- **Figure 2 — Workflow mechanism:** evidence grounding → schema alignment →
  role-conditioned constrained extraction, with data flow and the function of
  each module visible. Avoid generic AI-style decorative blocks.
- **Table 1 — Data and evidence tiers:** dataset/domain/schema/task/split, plus
  main/generalization/diagnostic status.
- **Table 2 — Main result:** matched-information baselines, comparable task
  metrics, acceptability audit metrics, and confidence intervals. Do not mix
  prompt-selection scores into the main result.
- **Table 3 — Mechanism evidence:** module ablations and boundary probes; every
  module named in Figure 2 needs a corresponding test.
- **Appendix:** exact prompt registry and schema cards, provider/model and
  decoding manifest, per-dataset details, additional outputs/error cases, and
  reproducibility information. Keep evidence needed to judge the central claim
  in the main paper.

### Accepted-paper pattern study

This pattern is a non-normative synthesis of four accepted papers, selected for
their proximity to this study rather than as a representative sample of every
COLING/NAACL paper:

| Exemplar | What ARW learns from it |
|---|---|
| [CycleOIE (COLING 2025)](https://aclanthology.org/2025.coling-main.227/) | State the resource constraint first; separate data construction, method, main results, and mechanism analysis; put full prompts and extra detail in the appendix. |
| [Controlling OOD Gaps (COLING 2025)](https://aclanthology.org/2025.coling-main.224/) | Define the transfer boundary; compare matched prompt conditions; ablate prompt components; test prompt-paraphrase robustness; disclose black-box/provider drift. |
| [Track-SQL (NAACL 2025)](https://aclanthology.org/2025.naacl-long.536/) | Give modules functional names, show them in an early overview figure, and test each across datasets, difficulty conditions, and model backbones. |
| [Soft Syntactic Reinforcement for Event Extraction (NAACL 2025)](https://aclanthology.org/2025.naacl-long.479/) | Declare datasets/splits/metrics/baselines before interpretation and test whether the claimed mechanism transfers across sentence- and document-level extraction. |

The reusable template is therefore a set of **argument slots**, not copied
section headings: boundary → gap → functional modules → matched evaluation →
mechanism evidence → transfer/robustness → bounded conclusion. For prompt-based
work, a component ablation alone is insufficient; include semantically
equivalent prompt rephrasings so a gain is not attributable to one lucky
wording.

### Venue choice gate

- Choose **COLING 2027** for the current claim framing.
- Keep **NAACL 2027** as the same-cycle alternative because no format rewrite is
  needed, but strengthen the generalizable methodological contribution.
- Choose **ECIR 2027** only after changing the research question and experiments
  to an actual retrieval/RAG or ontology-backed search contribution. Do not
  relabel the current extraction paper merely to match ECIR keywords.

## Official sources

- ARR dates: <https://aclrollingreview.org/dates>
- ARR call and hard rules: <https://aclrollingreview.org/cfp>
- ARR author workflow: <https://aclrollingreview.org/authors>
- Official ACL template: <https://github.com/acl-org/acl-style-files>
- COLING 2027: <https://2027.coling-iccl.org/>
- NAACL 2027: <https://2027.naacl.org/>
- ECIR 2027 full-paper call: <https://www.ecir2027.co.uk/call-for-full-papers>
- CCF 2026 directory announcement: <https://www.ccf.org.cn/Academic_Evaluation/By_category/>
- ACL Anthology style exemplars: <https://aclanthology.org/2025.coling-main.227/>,
  <https://aclanthology.org/2025.coling-main.224/>,
  <https://aclanthology.org/2025.naacl-long.536/>, and
  <https://aclanthology.org/2025.naacl-long.479/>
