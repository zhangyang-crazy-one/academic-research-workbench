# Submission workflow runtime

The submission workflow is an optional plugin capability layered on the current
ARW architecture.  It is not a second research database or a portal client.

## Authority boundary

- The parent runtime owns the append-only journal, immutable artifact manifests,
  artifact admission, gate events, human decisions, retries, and replay.
- `SubmissionWorkflowProvider` is resolved lazily by the composition root.  It
  validates and normalizes candidate packet/review values; it cannot append
  events or authorize readiness.  `prepare` may use this optional provider;
  canonical `record`, review import and response admission remain parent-owned
  and do not turn provider absence into an import-time write failure.
- SQLite, graph, Semantica, memory, learning, and hooks remain rebuildable or
  advisory.  Their output is never sufficient to create a packet, prove a
  human decision, or release a gate.
- The `submission` skill is a thin route to `arw submission`; it does not write
  canonical state.  There is no `submit` command.

## Runtime capability matrix

The matrix distinguishes three evidence levels: the contracts and provider
seam listed here are implemented source paths; requirements in other active
OpenSpec changes remain planning inputs until their own code and tests are
verified; submission-specific portal, full-audit, tone, and passport behavior
listed below is not implemented by this change.

| Capability | Runtime surface | Authority | Current boundary |
| --- | --- | --- | --- |
| Packet and policy contracts | `arw.kernel.state.submission`, checked schemas | parent admission | strict fields, digests, bounded components and declarations |
| Review rounds and responses | `submission-review-round`, `submission-response` artifacts | parent admission | source-bound IDs, evidence-bound closure, explicit unsupported formats |
| Optional preparation provider | `submission.prepare`, `submission.review_normalize`, `submission.check_observe` | composition root | absent provider returns `CapabilityUnavailable` |
| Verifier observation contract | `submission-verifier-observation` | parent admission | retains verifier/source version, input/output digests, coverage, limitations and per-check evidence; it does not execute or authorize a verifier |
| Writing/research-artifact inputs | existing accepted artifact references in packet components/evidence | parent artifact admission | preserves the referenced artifact manifest/content and any existing writing or visual-review limits; no filename/path is treated as authority |
| Memory/handoff/learning context | existing accepted advisory references/observations | advisory context only | can inform preparation and explanation, but cannot satisfy a required check, confirm an author, release a gate, or perform a transition |
| Parent packet admission | existing `artifact.accepted` event | parent journal | reserved kinds validate references and predecessor state under the writer |
| Readiness check | `arw submission check/status` | derived from accepted records | read-only, fail-closed, stale/fingerprint aware; status exposes readiness, qualification and external-observation axes separately |
| Qualification | `arw submission qualify` | parent `gate.evaluated` event | records readiness evidence; final author Submit remains external and human |
| Registered ready transition | `arw submission ready` | parent lifecycle event | rechecks packet/report fingerprint, fresh PASS gate and exact human approval under the writer lock |
| External result | `submission-result-observation` artifact | parent journal | user confirmation or retained platform receipt only; no network action |

## Supported and deferred behavior

Supported behavior includes local JSON preparation, digest-bound packet and
attachment references, official-policy snapshots supplied as retained evidence,
review comment/response artifacts, deterministic readiness evaluation, parent
gate recording, replay and exact artifact admission retries.  Required checks
may bind their input to category fingerprints for manuscript/bibliography,
render, policy, roster/contributions/disclosures, attachments, responses and
scoped author decisions.  A category change invalidates its dependent checks
while preserving historical receipts and unrelated category-bound checks; the
aggregate readiness fingerprint still becomes stale until requalified.

ARS Markdown patch evidence is accepted only when the retained block manifest,
patch document, apply report, base/candidate hashes and approved JSON scope
agree.  A passing adapter report is evidence rather than scientific approval.
Word/PDF automatic patching or locator remapping returns
`submission-revision-unsupported`; externally edited Word/PDF evidence can be
imported only with explicit version-bound locators.

The following are deliberately unsupported in this change: portal login or
upload, payment, email, automatic Submit, external-action retries, journal
acceptance prediction, automatic Word/PDF editing or locator remapping, and a
new claim/citation/entailment engine.  Missing strict audit evidence remains
`NOT_CHECKED`/`UNSUPPORTED` and cannot become `PASS` because a provider exited
successfully.

Deferred follow-ups are portal observation/fill adapters, cross-run submission
ownership, full manuscript claim/citation auditing, author tone profiles and a
project-level Research Passport.  They must reuse this parent-owned contract
instead of introducing parallel authority.

The installed-host qualification result and ARW/ARS license-release result are
independent from per-manuscript readiness.  A fixture or source-level test does
not claim a qualified live Codex host.

`qualify --scope confirmation` records only a narrow, exact field/response
eligibility gate (`--submission-id`, `--subject-scope`, `--subject-sha256`).
For a response successor, `--response-status addressed|not_adopted` binds the
eligibility subject to the intended closing disposition before the authenticated
author decision is recorded; the successor then carries that decision and its
predecessor identity.
The existing authenticated human-decision flow must still bind that gate and
subject before the aggregate readiness gate can be treated as approval.
`qualify --scope readiness` records the aggregate check report and its current
parent gate.  Neither scope exposes a portal or a `submit` operation.
`ready` is a parent-owned lifecycle transition, not an external submission
action; it requires a fresh aggregate PASS and an authenticated approval bound
to the exact packet/report subject.  That final approval is downstream of the
aggregate report and is intentionally excluded from the report's input
fingerprint; field/response confirmations remain fingerprinted inputs, so the
approval path cannot become circular.

## Verification boundary

The current source-level evidence includes the focused submission/schema/plugin
suite, the existing writing/artifact/gate/orchestration/memory/learning
integration suite, strict OpenSpec validation, and a successful plugin staging
run.  The installed launcher suite has one environment-blocked smoke case when
the container cannot create the host network namespace (`bwrap`/`NETLINK_ROUTE`);
that is not treated as live-host qualification.  The current host reports
`codex-cli 0.155.1`, while the newest retained v2 integration lock is for
`codex-cli 0.149.1`; its verification also reports that the staged ARW wheel
omits the integration-lock runtime.  Therefore no qualified bundle is
available for 7.5, and the live-host checkbox remains intentionally open.
Full portal automation, Word or PDF editing/remapping, and strict manuscript
audit engines remain explicitly unsupported follow-ups.  Source-level rollback
verification covers disabling the optional provider while retaining historical
packet readers, journal bytes and parent replay; rollback never rewrites or
deletes those artifacts.
