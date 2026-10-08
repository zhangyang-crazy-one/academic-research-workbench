# Direct-native session-root confinement

## ADDED Requirements

### Requirement: Read from the current session capability

The direct-native `read_file` handler SHALL use the canonical allowed root installed on the current MCP session. It SHALL first require a configured process capability whose root ID equals the request root ID; otherwise it SHALL keep the existing public `root_denied` result. It SHALL then compare the session root to the canonical process capability root; a mismatch SHALL return `root_session_mismatch`. Both denials occur before opening a file or returning content.

#### Scenario: Shared daemon receives another root with the same ID
- **WHEN** client A starts a daemon and client B supplies another root with the same root ID
- **THEN** B's `read_file` is denied with `root_session_mismatch` and no content from A or B is returned.

#### Scenario: Shared daemon receives another root with a different ID
- **WHEN** clients share a daemon and B's request root ID differs from the daemon's process capability ID
- **THEN** B's `read_file` is denied with the existing `root_denied` reason and no content is returned.

### Requirement: Advertise a usable capability only

The daemon's `tools/list` SHALL advertise `read_file` only when its current session root matches the process root capability and the process root ID is configured. An unconfigured session SHALL NOT gain file access from the daemon's process environment.

#### Scenario: Existing daemon has no root capability
- **WHEN** a configured client attaches to a daemon started without a root capability
- **THEN** `read_file` is absent from the tool list and a direct call returns `root_denied`.

#### Scenario: Configured daemon receives a session without a root
- **WHEN** an unconfigured client attaches to a daemon whose process capability names the requested root ID
- **THEN** `read_file` is absent from the tool list and a direct call returns `root_session_mismatch`.

### Requirement: Preserve confined read behavior

For a compatible session, the existing symlink, traversal, absolute-path, sensitive-path, byte, line, regular-file, and UTF-8 limits SHALL remain enforced.

#### Scenario: Compatible session requests a denied path or exceeds a read limit
- **WHEN** a compatible session requests a symlink or traversal path, or exceeds the byte or line ceiling
- **THEN** the existing confined-read denial is returned without content beyond the authorized root or requested limits.
