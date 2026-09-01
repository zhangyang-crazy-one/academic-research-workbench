"""WorkflowProvider adapter for the bundled ARS workflow registry."""

from __future__ import annotations

from arw.kernel.ledger.workflows import WORKFLOW_REGISTRY, WorkflowDefinition


class ARSAdapter:
    """WorkflowProvider over the v1 registered-workflow registry."""

    def registry(self) -> tuple[WorkflowDefinition, ...]:
        return tuple(WORKFLOW_REGISTRY.values())

    def resolve(self, definition_id: str) -> WorkflowDefinition | None:
        return WORKFLOW_REGISTRY.get(definition_id)
