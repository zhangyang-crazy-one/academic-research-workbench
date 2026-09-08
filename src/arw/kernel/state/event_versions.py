"""Additive event-reader migrations; immutable historical bytes are never rewritten."""

MIGRATIONS = (
    (1, '1.1.0', (
        'research_artifact_ir_frozen', 'research_artifact_rendered',
        'research_artifact_validated', 'research_artifact_accepted',
        'research_artifact_superseded',
    )),
)


def event_schema_version(event_type: str) -> str:
    for _, version, families in MIGRATIONS:
        if event_type in families:
            return version
    return '1.0.0'
