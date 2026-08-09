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

### Editorial evidence precedence and resolved conflicts

For writing, figure, and table choices, use this order: **official target-venue
requirements → topic-matched full-text accepted-paper audit → generic
cross-venue heuristic**. This ordering applies only to non-normative editorial
choices; it cannot override ACL/ARR page limits, anonymity, ethics, template,
or submission rules.

The six official COLING 2025 PDFs in the project audit were inspected figure by
figure and table by table. They resolve four tensions in the generic visual
guidance for this paper:

- Prefer a **two-figure sequence** when the page budget permits: Figure 1 is a
  realistic task/leakage-boundary example; Figure 2 is the functional method
  chain using the same running example. Do not force failure, protocol, method,
  diagnostics, and a result metric into one overloaded Figure 1.
- A combined multi-panel Figure 1 is still valid under material page pressure
  or when the protocol boundary itself is the central contribution.
- Functional boxes and arrows are valid for Figure 2 when every module names an
  intellectual operation, repairs a stated failure mode, and visibly transforms
  the running example. Generic software/platform architecture still fails.
- The evidence link may be carried by the Figure 1 → Figure 2 → main-table
  sequence. Figure 1 does not need an embedded metric. Likewise, “4–8 rows and
  4–6 columns” is a readability heuristic, not a hard cap on a clearly grouped
  multilingual, OOD, unseen-label, or multi-setting results matrix.

### Paper-level argument

1. **Abstract:** task value → precise failure condition → task reformulation or
   method idea → two or three functional modules → datasets/metrics and one
   numeric headline → bounded generalization or resource value.
2. **Introduction:** define the task with a realistic example; organize prior
   work into two or three categories with one testable limitation each; map
   each method module to one limitation; state an early numeric result; finish
   with three contributions covering problem, mechanism, and evidence.
3. **Problem and boundary:** real schema-driven Chinese ontology recognition
   begins without task-specific gold labels; labeled-test-dependent prompt
   selection is not deployable zero-shot evidence.
4. **Method:** a reusable workflow/skill composes domain role knowledge,
   evidence grounding, schema alignment, and constrained output. Define exactly
   which information is allowed in the prompt.
5. **Evidence:** compare against matched-information baselines, then report main,
   generalization, and diagnostic evidence separately with uncertainty.
6. **Mechanism:** ablate every named module and connect each ablation to the
   failure mode that motivated the module.
7. **Boundary of claim:** establish feasibility and design conditions, not
   universal superiority or fully autonomous ontology construction.

### Main-paper artifact plan

- **Figure 1 — Task and leakage boundary:** one Chinese source example, schema
  card, permitted knowledge, forbidden gold/test information, and target
  structured output. A reader should understand what “ontology recognition”
  means without reading the method section.
- **Figure 2 — Workflow mechanism:** evidence grounding → schema alignment →
  role-conditioned constrained extraction, with the same example, the
  transformation at each stage, and a rejection/audit path visible. Avoid
  generic AI-style decorative blocks.
- **Table 1 — Data and evidence tiers:** dataset/domain/schema/task/split, plus
  main/generalization/diagnostic status.
- **Table 2 — Main result:** separate fully unseen labels, partially seen
  labels, and cross-domain settings; identify evidence/schema access for every
  matched-information baseline; report precision, recall, F1, and repeated-run
  variance or confidence intervals where applicable. Do not mix
  prompt-selection scores into the main result.
- **Table 3 — Mechanism evidence:** put the full workflow first, remove every
  named module, report direct end-to-end ΔF1, and add a local metric for the
  function claimed by that module.
- **Table 4 or compact appendix diagnostic:** schema-label renaming, definition
  paraphrase, schema-order randomization, cross-domain/model repetition,
  no-evidence rejection accuracy and hallucination rate, plus error slices for
  implicit evidence, schema ambiguity, role confusion, and no-evidence
  hallucination. Keep claim-critical robustness evidence in the main paper.
- **Appendix:** exact prompt registry and schema cards, provider/model and
  decoding manifest, per-dataset details, additional outputs/error cases, and
  reproducibility information. Keep evidence needed to judge the central claim
  in the main paper.

### Accepted-paper pattern study

This pattern is a non-normative synthesis of nine accepted papers, selected for
their proximity to this study rather than as a representative sample of every
COLING/NAACL paper. The first three are the direct writing and method exemplars;
KGPCL and KG-TRICK are adjacent presentation references and **not** direct
baselines.

| Exemplar | Role | What ARW learns from it |
|---|---|---|
| [Zero-Shot Ontology Annotation (COLING 2025)](https://aclanthology.org/2025.coling-main.542/) | Direct | Use Figure 1 for the task and a later figure for the method; separate fully unseen and partially seen labels; bind zero-shot claims to inference-time information. |
| [B²NERD (COLING 2025)](https://aclanthology.org/2025.coling-main.725/) | Direct | Quantify evidence scale early; connect taxonomy failures to functional operations; group language/OOD settings; report repeated runs, ablation deltas, and perturbation evidence. |
| [GAEF (COLING 2025)](https://aclanthology.org/2025.coling-main.274/) | Direct | Motivate role failures with a concrete example; carry it through a functional architecture; follow P/R/F1 results with module ablation and low-resource analysis. |
| [CycleOIE (COLING 2025)](https://aclanthology.org/2025.coling-main.227/) | Supporting | State the resource constraint first; separate data construction, method, main results, and mechanism analysis; put full prompts and extra detail in the appendix. |
| [KGPCL (COLING 2025)](https://aclanthology.org/2025.coling-main.359/) | Adjacent, not baseline | Borrow concept-abstraction terminology, layered presentation, ablation, and mechanism visualization only when they fit the current claim. |
| [KG-TRICK (COLING 2025)](https://aclanthology.org/2025.coling-main.611/) | Adjacent, not baseline | Borrow multilingual framing and language/frequency stratification without implying direct task comparability. |
| [Controlling OOD Gaps (COLING 2025)](https://aclanthology.org/2025.coling-main.224/) | Supporting | Define the transfer boundary; compare matched prompt conditions; ablate prompt components; test prompt-paraphrase robustness; disclose black-box/provider drift. |
| [Track-SQL (NAACL 2025)](https://aclanthology.org/2025.naacl-long.536/) | Supporting | Give modules functional names, show them in an early overview figure, and test each across datasets, difficulty conditions, and model backbones. |
| [Soft Syntactic Reinforcement for Event Extraction (NAACL 2025)](https://aclanthology.org/2025.naacl-long.479/) | Supporting | Declare datasets/splits/metrics/baselines before interpretation and test whether the claimed mechanism transfers across sentence- and document-level extraction. |

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
- ACL Anthology direct style exemplars:
  <https://aclanthology.org/2025.coling-main.542/>,
  <https://aclanthology.org/2025.coling-main.725/>, and
  <https://aclanthology.org/2025.coling-main.274/>
- ACL Anthology supporting or adjacent exemplars:
  <https://aclanthology.org/2025.coling-main.227/>,
  <https://aclanthology.org/2025.coling-main.359/>,
  <https://aclanthology.org/2025.coling-main.611/>,
  <https://aclanthology.org/2025.coling-main.224/>,
  <https://aclanthology.org/2025.naacl-long.536/>, and
  <https://aclanthology.org/2025.naacl-long.479/>
