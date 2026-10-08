# Bind direct-native reads to the daemon session

Issue #72: a shared file-base daemon inherits the first client's `CBM_ALLOWED_ROOT`, while the ARW `read_file` patch currently reads that process environment for every client. A second client's request can therefore read the wrong root or be denied according to the first client.

Constrain direct-native reads to the canonical allowed root installed on the current MCP session. The existing request root ID remains a process capability; until the daemon context carries an ID, a session whose canonical root or requested ID differs from the process capability is denied with `root_session_mismatch`. The store-backed and legacy Python files paths are outside this change.
