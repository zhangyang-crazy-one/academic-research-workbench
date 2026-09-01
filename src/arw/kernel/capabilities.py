"""Capability vocabulary and routing table.

Extensions register capability names; the composition root resolves them to
provider instances. The kernel references capabilities by name only.
"""

from __future__ import annotations

# v2 capability vocabulary (stable identifiers for extension registration).
CAPABILITIES: tuple[str, ...] = (
    "files.local",
    "files.search",
    "knowledge.graph",
    "knowledge.provenance",
    "knowledge.semantic_search",
    "research.literature",
    "research.deep_survey",
    "research.experiment",
    "artifact.inspect",
    "artifact.sanitize",
    "audit.replay",
)
