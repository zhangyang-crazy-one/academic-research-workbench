"""WorkflowProvider port: registered research workflow planning/execution.

Derived from the v1 workflow registry (`arw.kernel.ledger.workflows`) and the
Phase 4 assignment/result envelopes (`arw.kernel.state.orchestration_models`).
"""

from __future__ import annotations

from typing import Protocol

from arw.kernel.ledger.workflows import WorkflowDefinition


class WorkflowProvider(Protocol):
    """Expose registered workflow definitions and resolve by definition id."""

    def registry(self) -> tuple[WorkflowDefinition, ...]: ...

    def resolve(self, definition_id: str) -> WorkflowDefinition | None: ...
