# Project-bound research startup and external direction packages

`research` is a thin composition interface over the existing project identity,
canonical parent journal, ARS validators, AcceptedRef resolver, citation replay
and experiment evaluator. It never selects a model, downloads sources or
admits evidence on behalf of a user. Hooks remain observational.

## Start, inspect and recover

```bash
"<plugin-root>/bin/arw" research start --project-root ./my-research \
  --direction '修正对世界的理解' --ars-project-ref 'my-research-direction'
"<plugin-root>/bin/arw" research status --project-root ./my-research
"<plugin-root>/bin/arw" research resume --project-root ./my-research
```

The default phase is `scoping` and task kind is `other`. Broad direction text is
an immutable intent, not an approved RQ, hypothesis, narrative or paper outline.
Human experience alignment, H1/H2 and computational ontology ideas remain
candidates until separately reviewed. Existing paper/narrative selection guards
still apply to `--task-kind paper`; `--phase writing` does not bypass them.

The first command retains `.arw/research/start.json`, an exact initialization
request, stable `.arw/project.json`, and a run under `.arw/research/runs/`.
`--plan-only` retains reviewable inputs without initializing a journal. Resume
completes missing durable steps under the writer lock, using the same IDs and
bytes. It refuses changed intent, identity, manifest, journal or selected paper
context instead of overwriting accepted history. Restarting after any durable
step does not produce a second initialization event. The same project tree can
move directories; `--project-id` and `--run-id` can pin expected identities.
The legacy `memory init-project` alias uses this core identity service without
requiring a configured memory provider.

Status reports lifecycle (`RUNNING`) beside workflow stage (`initialized`),
accepted record count, recovery health and actual gate records. These fields do
not mean an experiment is running. Editable source reports core `UNVERIFIED`;
an installed qualified payload reports its checked integrity. Retrieval,
executor and science remain `not_evaluated` until their own interfaces check
them. An unrelated legacy executor `BLOCKED` does not block core research
administration. Missing dependency bytes needed for the selected operation do.

## Replaceable data packages

Examples are under `<plugin-root>/examples/research-directions/`:

- `semantics-llm/package.json`: an interpretive package, no predefined hypotheses;
  methodology is explicitly `intentionally_absent`, other unresolved stage fit
  stays `unresolved_fit`.
- `computational-pilot/package.json`: an illustrative behavioral proxy with
  baseline, equal-budget, sham, held-out, all-attempt and cost declarations.
  No empirical effect or philosophical conclusion is asserted.

Packages carry a version, canonical digest, source/license inventory, unknowns,
original ARS profile, optional bounded profile history and candidate hypotheses.
Copy and edit a package outside the plugin, then seal and inspect it:

```bash
"<plugin-root>/bin/arw" research direction seal --input ./candidate.json --output ./sealed.json
"<plugin-root>/bin/arw" research direction inspect --package ./sealed.json
"<plugin-root>/bin/arw" research direction bind --project-root ./my-research --package ./sealed.json
```

Sealing validates the original ARS profile; it does not authenticate an author
or certify construct fit. Packages are JSON data only: arbitrary commands,
unknown top-level fields and executable extensions are rejected. Inputs are
regular files, bounded to 512 KiB, with symlink ancestors rejected. The only
validator subprocess runs bundled fixed Python scripts in isolated mode; it
receives no model credentials. Profile licensing and original source
attribution remain explicit. Selecting a package grants no execution permission.

The optional `--branch-ledger` is checked by the original inquiry ledger replay,
including hash chain, project reference, profile history and author/AI branch
semantics. ARS aliases are bound into the initial run input. Another project's
alias or AcceptedRef is rejected. Binding retains immutable package/branch/case
snapshots outside the canonical ledger and reports `not_accepted`.
Use the returned relative `binding_path` with `direction check --binding-path`.
Pass explicit current `--package` / `--branch-ledger` to check drift; changed
inputs mark the older binding stale while preserving its historical snapshot.
Candidate bindings are not authority, approval, human adoption or manuscript
occurrences.

## Intake, operationalization and evidence

`direction intake --package FILE --input FILE` takes an
`arw.literature-intake.v1` document. Each reading binds the original
`ReferenceRecord`, exact version label/carrier, optional accepted source bytes,
original citation receipts, reader kind, reading status/ranges, limitations,
notes and declared affected record IDs. A PDF source may include the existing
AcceptedRef `source_locator` (PDF/extraction/quote hashes and section/paragraph
location); the adapter does not invent a second locator contract.

The report independently shows bibliographic status, source-byte availability,
operator-declared reading, human review and experiment replay scope. A citation
`verified` is metadata-only, not full text or scientific support. Successful
replay preserves `not_found` and `unavailable`. No source reference means bytes
are missing/unaccepted even if a URL or digest is present. Tool reading never
becomes human reading. Partial, failed and timed-out readings are retained.
`--previous-intake FILE` compares version, carrier and source digest for the same
reference identity and lists declared dependent notes/matrices requiring
review. An affected conclusion is not automatically false; v1 snapshots remain
unchanged and v1 claims never become v2 claims automatically.

`direction definition --input FILE [--package FILE --hypothesis-id ID]` takes an
`arw.operationalization.v1` artifact: author interpretation, rivals, local
definition, measured object/metric/relevance, alternative measurements,
confounders, refuting observations, cannot-conclude bounds, assumptions and
sought evidence. It maps these fields to the existing inquiry/profile/boundary
concepts and leaves construct validity to human review. Package + hypothesis
produce a claim digest binding the exact hypothesis, scope and definition bytes
for the existing experiment contract interface.

Both commands prepare an ordinary immutable artifact and strict parent
`ArtifactAcceptanceRequest`, then return a concrete `next_command`:

```bash
"<plugin-root>/bin/arw" artifact-accept --run-root RUN --request REQUEST
```

Preparation does not advance revision. Repeating it at the same journal prefix
returns the same request bytes. Requests at later prefixes are separate;
stale requests retain the existing runtime's revision rejection. Already
accepted content returns its original event and no new acceptance command.

An optional `bind --cases FILE` accepts `{ "cases": [...] }` with each case
naming a hypothesis, AcceptedRef operationalization/cost/attempt/evidence
records, exact contract digest/version, result digest and declared conditions.
`direction check` checks branch adoption, source bindings,
hypothesis→definition→frozen contract→original raw-result replay. It preserves
passed, failed, unsupported, late/exploratory and missing outcomes instead of
upgrading them. Opposing, null and failed records have explicit relations.
Baseline/sham/held-out/budget rows are declarations, not observed causal proof.
A complete-attempt inventory is also a declaration; cost values are accepted
observations, not authenticated billing. Missing measurements are unknown,
never inferred zero. A narrative candidate needs human review and does not
create a ClaimGraph registration or invent a manuscript occurrence.

## Executable offline walkthrough

```bash
ARW_PLUGIN_ROOT='<plugin-root>' '<plugin-python>' \
  '<plugin-root>/examples/research-directions/offline_walkthrough.py' \
  --plugin-root '<plugin-root>' --project-root ./synthetic-direction-demo
```

Choose a new output directory. `<plugin-python>` is the selected interpreter
with the ARW wheel and its declared dependencies installed. The script uses
public startup/intake/definition/binding/acceptance/resume commands and existing
parent services for freeze/provenance/numeric evaluation. It records every CLI
stdout, stderr, strict request, source/version fixture and final summary.
It retains a passing and a failing numeric attempt, null/opposing/failed
records, two synthetic versions and an inconsistent abstract, and reports
human-review boundaries. No real paper, model execution, billing authentication
or philosophical conclusion is simulated as fact. Measured command/request
counts are recorded; research tokens and elapsed time are not measured. The
owner's old three-command startup is an observational baseline, not a controlled
cost/latency comparison. A future paid pilot requires separate execution
configuration and authorization; it is not a release prerequisite.
