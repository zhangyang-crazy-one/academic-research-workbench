# Learning privacy and retention

Learning is opt-in per project and can be disabled for individual runs.
Disabled writes produce no new observation, heuristic, or promotion record.
Historical decoding and explicit inspection remain available. Disabling project
activation also suppresses automatic applicable-lesson suggestions.

Only structured canonical events and accepted artifact references are projected.
Full transcripts and raw prompts are not a learning input format. Observation
summaries use deterministic event vocabulary; they do not copy source bodies.
Secret-shape checks run before candidate/receipt publication and inspect accepted
source data when learning consumes it. They are defense in depth, not a proof
that all personal information or secrets have been detected.

Inputs are bounded and immutable file access rejects symlink/root escapes.
Imports reset candidate trust and status; external approval labels do not become
local authority. Model-generated text and recalled memories cannot execute tools
or rewrite skills through this extension.

`purge --digest SHA256 --consent --authorization-artifact-id ID` requires a
previously accepted authorization artifact with `action: purge_learning` and
the exact `content_digest`. A durable tombstone is published before unlinking
the body. Retries finish interrupted deletion. The canonical hashchain remains
unchanged; reads requiring that body return `BodyUnavailable`. Rebuild preserves
the unavailable state and does not advertise that deleted bytes are recoverable.
Purge does not delete separately retained original source artifacts; their
retention is governed by their own explicit authorization.
