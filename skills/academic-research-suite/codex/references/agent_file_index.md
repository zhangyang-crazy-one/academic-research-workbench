# Downstream ARS Codex adapter reference

Original material: academic-research-skills by Imbad0202, CC BY-NC 4.0.
Modified by Academic Research Workbench: moved intact from the adapter router
for progressive loading; see repository MODIFICATIONS.md for provenance.

+## Canonical Agent Files

Use these exact filenames. Do not invent hyphenated alternatives or rename files
from memory.

`ars/deep-research/agents/`:
`bibliography_agent.md`, `devils_advocate_agent.md`,
`editor_in_chief_agent.md`, `ethics_review_agent.md`,
`meta_analysis_agent.md`, `monitoring_agent.md`,
`report_compiler_agent.md`, `research_architect_agent.md`,
`research_question_agent.md`, `risk_of_bias_agent.md`,
`socratic_mentor_agent.md`, `source_verification_agent.md`,
`synthesis_agent.md`, `timeline_extraction_agent.md`.

`ars/academic-paper/agents/`:
`abstract_bilingual_agent.md`, `argument_builder_agent.md`,
`citation_compliance_agent.md`, `draft_writer_agent.md`,
`formatter_agent.md`, `intake_agent.md`,
`literature_strategist_agent.md`, `peer_reviewer_agent.md`,
`revision_coach_agent.md`, `socratic_mentor_agent.md`,
`structure_architect_agent.md`, `visualization_agent.md`.

`ars/academic-paper-reviewer/agents/`:
`devils_advocate_reviewer_agent.md`, `domain_reviewer_agent.md`,
`editorial_synthesizer_agent.md`, `eic_agent.md`,
`field_analyst_agent.md`, `methodology_reviewer_agent.md`,
`perspective_reviewer_agent.md`.

`ars/academic-pipeline/agents/`:
`claim_ref_alignment_audit_agent.md`, `collaboration_depth_agent.md`,
`integrity_verification_agent.md`,
`pipeline_orchestrator_agent.md`, `state_tracker_agent.md`.

`ars/experiment-agent/agents/`:
`code_runner_agent.md`, `study_manager_agent.md`.

## Shared Resources

Use `ars/shared/` for cross-workflow contracts and quality gates:

- `ars/shared/handoff_schemas.md` defines inter-stage artifact schemas.
- `ars/shared/style_calibration_protocol.md` defines writing voice calibration.
- `ars/shared/manuscript_artifact_boundary.md` defines the separation between
  user-facing collaboration notes and manuscript-facing text, figures, tables,
  captions, and exports.
- `ars/academic-paper/references/ai_scientific_image_generation.md` defines
  image-model use boundaries for scientific schematics, policy/disclosure
  checks, prompt brief templates, negative constraints, and final figure audits.
- `ars/academic-paper/references/academic_svg_box_diagram_standards.md` defines
  semantic contracts, restrained visual grammar, constant-scale arrows,
  relationship-label spacing, rail and bracket junction geometry, explicit
  feedback targets, and rendered-image audits for explicitly requested strict
  academic SVG box diagrams only.
- `ars/shared/mode_spectrum.md` defines fidelity, balanced, and originality modes.
- `ars/shared/model_tiering.md` defines the optional judgment/execution
  classification; Codex applies it only when per-dispatch model selection exists.
- `ars/shared/cross_model_verification.md` defines risk-stratified verification,
  blind disagreement checkpoints, the canonical dispatcher handoff envelope,
  the fixed-seat cross-model reviewer track, re-review judge independence,
  provider grounding guards, model-id status, and the contained citation-only
  Codex subscription transport.
- `ars/shared/references/evidence_row_protocol.md` defines source-bound Phase E
  evidence rows; `ars/shared/contracts/revision/` separates non-ranking roadmaps
  from author adjudication and current revision evidence.
- `ars/shared/references/human_subjects_authority_protocol.md`,
  `ars/shared/references/review_pathway_rule_trace_protocol.md`, and
  `ars/shared/references/submission_packet_manifest_protocol.md` define the
  institution-owned human-subjects authority, navigation, and packet boundaries.
- `ars/shared/review_criteria_registry.json` and
  `ars/shared/references/review_criteria_consumer_protocol.md` bind one
  author-confirmed review target across formative, internal, and external review.
- `ars/shared/research_workflow_profiles/field_general.json` plus the closed
  `ars/shared/contracts/research_workflow/` schemas define the default-off
  profile selection/correction substrate; `ars/shared/contracts/passport/inquiry_ledger_ref.schema.json`
  and `ars/scripts/inquiry_branch_ledger.py` define the separately opt-in local
  branch ledger.
- `ars/shared/contracts/cross_model/promotion_bakeoff_sealed_*.schema.json`
  defines future promotion-bakeoff commitment/reveal records. The associated
  history-aware tree verifier is upstream-only in this re-rooted package, while
  its hermetic contract tests remain available.
- `ars/shared/bibliographic_integrity_signals.md` and
  `ars/shared/references/cross_document_consistency_advisory_protocol.md` keep
  bibliographic, retraction, preregistration, and cross-document signals
  provenance-bearing and advisory rather than clean-document certificates.
- `ars/academic-pipeline/references/claim_verification_protocol.md` defines the
  v3.18 high-impact-first sampling gate plus advisory-only scope-conformance
  and search-bounded novelty classifications, and the v3.19 revision-round
  claim-strength drift audit.
- `ars/shared/references/claim_strength_ladder.md` and
  `ars/scripts/check_revision_token_conservation.py` define the v3.19 semantic
  and deterministic revision-drift guards.
- `ars/shared/contracts/passport/human_read_log.schema.json` defines optional
  user-owned read-scope attestations. Missing scope remains `unknown`; partial
  coverage remains visible and is never promoted to full coverage.
- `ars/shared/contracts/degradation_registry.json` indexes every graceful-
  degradation mechanism, its emitted state, authority, downstream consumer,
  and terminal-policy effect without replacing the underlying authority.
- `ars/shared/agents/compliance_agent.md` defines compliance checks.
- `ars/shared/compliance_checkpoint_protocol.md`, `ars/shared/prisma_trAIce_protocol.md`, and `ars/shared/raise_framework.md` define integrity and reporting gates.
- `ars/scripts/` contains upstream validators and reference adapters.
- `ars/examples/` contains upstream non-PDF fixtures and templates.
- `ars/docs/design/` contains upstream design specs referenced by ARS protocols.
- `ars/commands/` contains upstream Claude slash-command prompt recipes.
- `ars/hooks/` contains upstream Claude hook metadata preserved for traceability.
- `ars/tests/` contains upstream fixture corpora used by validator tests.

When an ARS file points to `shared/...`, resolve it as `ars/shared/...`.
When it points to another workflow, resolve it under `ars/<workflow>/...`.
When it points to root-level `scripts/...`, `examples/...`, or `docs/...`, resolve
it under `ars/scripts/...`, `ars/examples/...`, or `ars/docs/...`.

