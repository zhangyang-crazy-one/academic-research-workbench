# Direct-native session-root confinement

## ADDED Requirements

### Requirement: Read from the current session capability

The direct-native `read_file` handler SHALL use the canonical allowed root installed on the current MCP session. It SHALL compare that root to the canonical process capability root and SHALL require the request root ID to equal the process capability ID. A mismatch SHALL return `root_session_mismatch` before opening a file or returning content.

#### Scenario: Shared daemon receives another root with the same ID
- **WHEN** client A starts a daemon and client B supplies another root with the same root ID
- **THEN** B's `read_file` is denied with `root_session_mismatch` and no content from A or B is returned.

#### Scenario: Shared daemon receives another root with a different ID
- **WHEN** clients share a daemon but B's root or root ID differs from its process capability
- **THEN** B's `read_file` is denied with `root_session_mismatch`.

### Requirement: Advertise a usable capability only

The daemon's `tools/list` SHALL advertise `read_file` only when its current session root matches the process root capability and the process root ID is configured. An unconfigured session SHALL NOT gain file access from the daemon's process environment.

#### Scenario: Existing daemon has no root capability
- **WHEN** a configured client attaches to a daemon started without a root capability
- **THEN** `read_file` is absent from the tool list and a direct call returns `root_session_mismatch`.

### Requirement: Preserve confined read behavior

For a compatible session, the existing symlink, traversal, absolute-path, sensitive-path, byte, line, regular-file, and UTF-8 limits SHALL remain enforced.

#### Scenario: Compatible session requests a denied path or exceeds a read limit
- **WHEN** a compatible session requests a symlink or traversal path, or exceeds the byte or line ceiling
- **THEN** the existing confined-read denial is returned without content beyond the authorized root or requested limits.
