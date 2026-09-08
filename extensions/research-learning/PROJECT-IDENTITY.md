# Stable project identity

Learning resolves `.arw/project.json` through the core `ProjectIdentity` schema.
This same portable identity contract may be used by memory, but importing the
memory extension is unnecessary. An absolute host path is not a project ID.
Missing, malformed, changed, or symlinked identity fails closed. There is no
fallback to global scope.

New candidates default to project scope and may be explicitly run-local. Their
owning run must be within the selected project. Run registration binds a
relative root, run ID, project ID, and immutable run-manifest digest. Moving the
whole project preserves identities and relative registrations. Run identity
collisions or root escape are refused.

Lifecycle operations use the candidate's originating run. Evidence may come
from other explicitly registered runs in the same project. Query operations do
not enumerate external project roots. Broader promotion requires a reviewed
cross-project attestation and explicit transfer authorization, and still stores
the promoted advisory item under the original project identity. It never makes
the item implicitly active in another project.

Applicability includes task, model, retrieval coverage, call and output budgets,
and metric. `applicable` requires an exact match and exposes the suggested action
and evidence before an author decision. `use` inspects a separately accepted
author decision and differentiates its action from the suggestion. An outcome
marked unmeasured cannot contain a claimed numeric improvement. A measured
outcome must bind prior accepted metric evidence.
