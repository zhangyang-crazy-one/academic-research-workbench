## Context

The parent journal already admits immutable artifacts; the learning extension records observations and successor heuristics, while the memory extension validates source links and successor handoffs. Neither provides a typed mechanism diagnosis. The CLI can add a read-only core path without writing another ledger or requiring an optional extension in the base install.

## Goals / Non-Goals

**Goals:** Verify source bytes and event identities, compare failure observations with an earlier accepted acceptance contract, emit bounded competing hypotheses and probes, and preserve prior exclusions across authenticated handoffs.

**Non-Goals:** Running probes, editing products or acceptance criteria, claiming a causal root cause, promoting heuristics, or creating memory automatically.

## Decisions

- Use three small input contracts stored as ordinary parent-accepted `learning-evidence` artifacts: frozen acceptance cases, failed attempt receipts, and edit records. Require the acceptance event to precede each failure event. Accept no hidden-cause field; strict models reject extra fields.
- Resolve each requested artifact by a unique accepted event, immutable manifest, bounded retained bytes, and matching content hash. Replay the journal and validate accepted manifests first. The report cites event ID/hash and artifact ID/hash for every pattern and hypothesis judgment.
- Apply deterministic predicates to observations: negated value, unit mismatch, and sample-ID mapping. A compatible pattern is `kept`, a contradicted necessary pattern is `ruled_out`, and missing data is `unresolved`. All causal conclusions remain `unknown`. Advisory probes name mutually different expected outcomes; actual probe evidence remains null until separately accepted evidence exists.
- A prior diagnosis is read only if it was separately accepted as an artifact. Optional memory handoff resolution uses `research.memory.read`, which already validates canonical links and lifecycle; require the handoff to cite that prior diagnosis with its exact digest and event. A later handoff must declare its predecessor through the existing memory `supersedes` relation. Ruled-out mechanisms are not re-recommended, and contradictory successor evidence blocks rather than silently reversing a prior ruling.
- `arw learn diagnose` emits report JSON and its canonical digest; it never publishes the report. A parent may separately admit it and create a memory handoff through existing commands.

## Risks / Trade-offs

- [Pattern compatibility can be coincidental] → Status is advisory, causal status remains unknown, and proposed probes are not marked executed.
- [An input list may omit history] → Absence claims remain unknown; only present accepted evidence can establish recurrence or opposing edits.
- [Memory extension may be absent] → Base diagnosis runs without it; a requested handoff returns typed `CapabilityUnavailable`.

## Migration Plan

Add standalone schema documents and a new read-only command. Existing learning, memory, and parent event contracts remain unchanged.
