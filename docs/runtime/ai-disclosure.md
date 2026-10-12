# AI participation disclosure

`arw disclosure summary` inventories **all included parent-accepted artifacts**,
including unreferenced text, result-plot/figure specifications and analysis
code. It reads original artifact/activity evidence, not ClaimGraph labels,
hooks, mutable projections or transcript guesses. Unaccepted external files
are outside observed coverage and must be imported before their provenance can
be associated. Imported material without history remains `unknown`.

```bash
arw disclosure summary --project-root PROJECT --run-root RUN
arw disclosure draft --project-root PROJECT --run-root RUN \
  --policy examples/disclosure-policies/arr-20261012.json > draft.json
arw disclosure replay --project-root PROJECT --run-root RUN --draft draft.json
```

Repeat `--run-root` for every explicitly included source run. Replay uses the
saved exact manifest/revision/head prefixes, so later material or policy updates
do not rewrite an earlier draft. Drafts embed the complete old policy snapshot,
generator version, summary, text and digest. No network request is needed.

## Record provenance through the parent writer

Use `AIActivityReceipt` (`ai-activity-receipt`, schema
`arw.ai-activity-receipt.v1`) for an observed activity receipt and
`AIParticipationDeclaration` (`ai-participation-declaration`, schema
`arw.ai-participation-declaration.v1`) for an explicit human statement. They
bind an exact whole-artifact `ParentArtifactRef`; target bytes and evidence
must be retained and accepted in the included prefix. Validate using the
checked schemas, then accept their canonical JSON with the existing
`arw artifact-accept --run-root RUN --request parent-request.json` workflow.
No alternate writer is introduced.

A receipt records activity ID, usage, system, model, harness and detail. Harness
and model identities are observations without compatibility pins; native and
API harnesses can be named without invoking them. Declarations additionally
retain the author's identity. Supported usage histories are `imported`,
`external_edit`, `mixed`, `grammar_only`, `ai_drafted` and
`ai_drafted_human_edited`. Multiple histories remain separately visible.
Generic accepted JSON cannot supply the receipt-observed status.

- `observed` proves the integrity/binding of accepted receipt contents. It does
  **not** independently authenticate a host/model call or establish authorship.
- `human-declared` retains an author's assertion, without promoting it to an
  observed model call or authenticated human decision.
- `unknown` means no applicable record. It never means exclusively human.

History completeness remains unproven. Missing or changed evidence cannot
supply a positive association. ClaimGraph associates manuscript observations
with this independent summary; malformed participation metadata is advisory
and cannot introduce a new scientific hard gate. Figure involvement uses the
same material inventory and proof rules. No graphical style or numeric receipt
is evidence of human authorship.

## Venue snapshots and final review

`AIDisclosurePolicy` freezes one venue/version, verification date, primary
source locator/digest, normalized guidance and template. Included snapshots
were checked on 2026-10-12:

- [ARR Responsible NLP checklist E1](https://aclrollingreview.org/responsibleNLPresearch/):
  report assistance in research, coding and writing and give section locators
  or an explanation. Its snapshot digest identifies the fetched source document.
- [IEEE AI content guidance](https://open.ieee.org/author-guidelines-for-artificial-intelligence-ai-generated-text/):
  acknowledgments should identify generated content, the system, affected
  sections and extent; editing/grammar assistance is separately distinguished.
  Direct document download returned HTTP 403. Its snapshot truthfully uses
  `retained-primary-excerpts`: the digest binds only the short retained excerpts
  observed through the primary page, not a claimed full HTML download.

The templates remain separate. Only short original normalized guidance and
source identity are redistributed, not the full policy bodies. New snapshots
receive new identities; old draft replay uses its embedded old snapshot.

Every output is a **draft**: `human_final_review: pending`,
`submission: not_performed`. The author must verify venue policy, affected
sections, external/imported edits and actual system usage before approving and
submitting a disclosure. This command neither supplies a checklist yes/no
answer nor certifies policy compliance or submits anything.
