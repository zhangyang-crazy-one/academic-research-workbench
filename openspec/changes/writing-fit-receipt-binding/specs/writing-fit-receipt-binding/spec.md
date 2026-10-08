# Writing candidate narrative-fit binding

## ADDED Requirements

### Requirement: Accepted writing receipt fit input
The selected-narrative fit workflow SHALL accept a reviewed and accepted
`writing-derived` draft as a manuscript input. It SHALL retain the original
accepted receipt bytes and use a versioned binding for the candidate path and
digest, nested realization canonical digest, accepted manifest/event, and paper
run manifest. The candidate SHALL match the retained manuscript bytes and the
realization source path/digest and selected narrative. The source and approved
human-review proofs SHALL match the receipt's references.

#### Scenario: Reviewed writing revision
Given a paper run with an accepted blueprint, source, human review and
`writing-derived` draft, narrative-fit capture produces a bound snapshot and an
advisory report. A fresh offline process replays the frozen snapshot to the
same report without reading the live run.

#### Scenario: Explicit realization sidecar
Given the same accepted writing receipt and an explicitly supplied sidecar,
capture succeeds only if the sidecar's canonical realization matches the
receipt's nested realization.

### Requirement: Shared capture and replay integrity
Capture and replay SHALL use the same validator for receipt, candidate,
realization, accepted manifest/event, run manifest and review/source references.
Tampered or mismatched bytes, digests, paths, scope, event references or source
associations SHALL fail before a fit report is emitted.

#### Scenario: Mismatched source with recomputed outer hashes
Even when a frozen receipt, accepted manifest and event hashes are recomputed
after changing its source reference, replay rejects the mismatched accepted
source proof.

### Requirement: Historical fit binding compatibility
Snapshots using `realization_sidecar` or `manuscript_source` SHALL continue to
replay using their original accepted-byte equality rules, with no writing
binding required and no added report fields.

#### Scenario: Two historical modes
Standalone accepted realization and accepted manuscript-source snapshots
deserialize without the new optional binding and reproduce their prior reports.
