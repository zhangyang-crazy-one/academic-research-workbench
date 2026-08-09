---
name: ars-academic-paper-team
runtime: codex-agent-team
enabled_when: "ARS_CODEX_FULL_RUNTIME=1 and ARS_CODEX_AGENT_TEAM=1"
source_workflow: "ars/academic-paper/WORKFLOW.md"
---

# ARS Academic Paper Team for Codex

Use for `academic-paper` modes in opt-in full-runtime agent-team mode. Inline
mode remains the default fallback.

## Dispatch Shape

- `plan` mode uses `socratic_mentor_agent.md`, `intake_agent.md`, and
  `structure_architect_agent.md`; it produces a plan and missing-evidence map,
  not a full draft.
- `outline-only` uses `structure_architect_agent.md` and
  `argument_builder_agent.md`.
- `full` mode keeps the generator/evaluator contract from upstream:
  `draft_writer_agent.md` must commit its drafting plan before self-scoring, and
  `peer_reviewer_agent.md` must evaluate after draft visibility.
- `citation-check` uses `citation_compliance_agent.md` and must separate
  missing, mismatched, unverifiable, and format-only citation issues.
- `format-convert` uses `formatter_agent.md`; unresolved high-warning claim
  audit annotations remain blocking when claim audit mode was enabled upstream.

## Output Contract

Preserve Material Passport fields, citation locators, claim-audit annotations,
and venue disclosure requirements. Do not add unsupported claims from model
memory; mark material gaps explicitly.

When a concrete venue and year are named, load
`codex/references/annual_venue_profiles.json` before the stable venue-family
pack. Compose the review-system contract with the venue-year contract, cite the
official source for every current deadline or format rule, and preserve
`not_announced` values. The venue-year official page overrides a shared review
schedule for venue-specific milestones. Re-browse official sources before any
deadline-dependent action.
