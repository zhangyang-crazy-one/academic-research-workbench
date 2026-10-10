# Historical journal segment boundaries

A fixed run prefix validates the actual consecutive segment paths needed to reach its requested revision and head digest. It does not enumerate later segment entries, follow later symlinks, or apply current-directory extra-entry checks to unrelated future files. Storage ancestors and every selected segment remain checked before reading.

Current replay preserves its full original discovery contract: exact segment names, contiguous numbering, regular files, no symlink entries, and no undeclared legacy/segmented layout paths. Fixed prefixes reject missing/gapped required segments, unsafe selected segments, invalid hashes, missing initialization, and invalid original recovery boundaries. A torn suffix after the requested record remains outside the historical view.

The existing reducer, manifest semantics and recovery validation are shared without copying event validators. Authentication's ContextVar query-scoped replay session and anchor work budget remain intact.

Twelve real-run boundary tests cover future symlinks/directories/extra entries/gaps/undeclared legacy paths, selected-segment missing/gap/symlink/directory/hash failures, multiple needed segments, ignored future torn suffixes, and preserved recovery receipt validation. Combined prefix/authentication/recovery/segmented/golden checks produced 50 passing tests; one additional recovery-schema assertion currently fails because the incoming authentication commit has not refreshed its embedded CanonicalEvent schemas. That independent schema refresh belongs to the integration branch.
