"""Additive event-reader migrations; immutable historical bytes are never rewritten."""

MIGRATIONS = (
    (3, "1.3.0", ('learning_observation_recorded', 'research_heuristic_proposed', 'research_heuristic_evaluated', 'research_heuristic_qualified', 'research_heuristic_rejected', 'research_heuristic_promoted', 'research_heuristic_superseded')),
    (2, '1.2.0', (
        'research_memory_created', 'research_handoff_created', 'research_memory_superseded',
        'research_memory_rejected', 'research_memory_distilled', 'research_memory_activated',
        'research_memory_verified',
    )),
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
