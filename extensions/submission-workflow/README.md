# Optional submission workflow provider

This extension supplies strict preparation and normalization for the
`submission-workflow-contracts` capability.  It is resolved lazily by the ARW
composition root and may be absent without breaking the kernel or existing
CLI/MCP contracts.

The provider contract is `arw.submission-provider.v1`; observations retain
per-check source identity/version, input/output digests, coverage and
limitations.  A successful adapter call is still only an observation until the
parent admits it as an immutable artifact.

The provider does not append journal events, accept artifacts, evaluate gates,
write SQLite, call a journal portal, or authorize Submit.  The parent control
plane must admit every returned value as an immutable artifact and make all
readiness, provenance, retry, and human-decision decisions.
