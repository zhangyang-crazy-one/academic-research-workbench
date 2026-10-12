# Advisory review concerns and PROV

```bash
arw review diagnose --project-root PROJECT --run-root RUN > concerns.json
arw review replay --project-root PROJECT --run-root RUN --input concerns.json
arw review prov --project-root PROJECT --run-root RUN --input concerns.json > claims-prov.jsonld
arw review verify --project-root PROJECT --run-root RUN --input one-concern.json
```

Repeat `--run-root` for every included source run. `ReviewConcern` binds a
concrete original manuscript occurrence or the ID/revision/digest of a
registered semantic claim, plus its full historical SnapshotManifest. The
original snapshot, cross-log closure, claim registration and precise occurrence
validators check the target. A changed manuscript/claim digest, missing source
or out-of-prefix dependency cannot supply a valid association. Replay validates
target provenance and exact record identity; it does not establish that an
author's diagnostic judgment is correct or currently applicable.

The read-only rules request evidence/scope clarification for a registered claim
without supporting evidence and explicit registration of unregistered or
unchecked occurrences. They do not predict review outcomes. Records contain
`advisory: true`, a proposition type, message and source identity. There is **no
score, rank, gate or qualify integration**. Saving, replaying or accepting a
concern cannot authenticate a claim. Additional author annotations can use the
checked schema and `review verify`; adding fields such as scores is rejected.

## Taxonomy and external corpus boundary

The six optional proposition types follow the conceptual distinctions in
[AMPERE](https://aclanthology.org/N19-1219/): `EVALUATION`, `REQUEST`, `FACT`,
`REFERENCE`, `QUOTE`, `NON-ARG`. Rule-generated suggestions are `REQUEST`.
[NLPeer](https://github.com/UKPLab/nlpeer) motivates explicit source/manuscript
version linkage. Neither reference supplies training data, empirical accuracy
or a scientific predicate in this implementation.

Optional [Argumentative Zoning](https://www.cl.cam.ac.uk/~sht25/az.html)
annotations are `BKG`, `OTH`, `OWN`, `AIM`, `TXT`, `CTR`, `BAS`. They remain absent
unless explicitly supplied; no automatic zoning classifier is claimed.
Only taxonomy names and source references are used. No paper/review corpus,
trained weights or dataset payload is downloaded, packaged or redistributed.
Any later corpus intake requires separate source/license review first.

## PROV JSON-LD in a new RO-Crate

The export uses the [PROV-O ontology](https://www.w3.org/TR/prov-o/) and
[RO-Crate context](https://w3id.org/ro/crate/1.1). Snapshot/target/concern entities
retain immutable identities; annotation/rule activities link through
`prov:used`, `prov:wasDerivedFrom`, and `prov:wasGeneratedBy`. The emitter checks
all local references and avoids remote context fetching. It does not assert a
paid model execution, predictive accuracy, scientific validity or human
approval.

To retain/export the body, accept `claims-prov.jsonld` through the existing
parent `arw artifact-accept` command, with artifact kind `claims-prov`, media
`application/ld+json` and the actual file SHA-256. Then explicitly select that
artifact using the original exporter:

```bash
arw artifact ro-crate-export --run-root RUN --output with-prov.zip \
  --include-artifact-id artifact.claims-prov
arw artifact ro-crate-verify --crate with-prov.zip --run-root RUN
```

The existing selection/privacy/byte/source-binding checks remain in force.
PROV is a selected source file in the crate, not an injection into the existing
`ro-crate-metadata.json`. No archive is overwritten. A newly created crate gets
its own digest; any earlier crate and its metadata retain their original bytes.

The integration case accepts the actual JSON-LD body through the original
parent writer and verifies structure, bytes, live source binding and the
RO-Crate **base profile** using the original verifier. Full workflow/provenance
profile completeness remains that verifier's separate result; this feature
does not promote it. These are canonical integration fixtures, not a real model
or third-party corpus qualification run.

Clickable reading-view manuscript HTML is optional and remains unsupported in
this delivery. Concerns JSON and PROV source links provide the implemented
headless author workflow.
