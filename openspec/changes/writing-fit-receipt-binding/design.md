# Design

The selected-narrative `FitSnapshot` gains an optional strict
`arw.writing-candidate-receipt-binding.v1` record, present exactly when
`accepted_binding_kind=writing_candidate_receipt`. It freezes the original run
and accepted artifact manifest bytes and digests, accepted event ID/digest,
accepted receipt digest, candidate path/digest, and canonical nested realization
digest. The existing accepted content field remains the exact receipt bytes;
the existing manuscript field remains the exact retained candidate bytes.
Source and human-review accepted proofs are added to the frozen evidence set.

One validator runs during live capture and offline replay after frozen proofs
are reconstructed. It checks each digest and run/manifest/event relation,
the receipt's `accepted_after_human_review` marker and accepted review artifact,
source and review binding identities, proposal and verification hashes,
versioned/legacy citation scopes, the candidate against the retained manuscript,
and the nested realization against its canonical digest, source path/hash and
selected narrative. An explicit sidecar must be canonically equal to the nested
realization. A mismatch rejects input integrity before producing a report.

The prior `realization_sidecar` and `manuscript_source` branches retain their
existing accepted-byte equality checks and can parse old snapshots without the
new optional field. The report adds receipt provenance only for the new mode,
so historical report bytes remain stable.
