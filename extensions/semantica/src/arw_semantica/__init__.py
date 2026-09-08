"""Semantica Lite provenance extension.

The extension is optional at the composition root: ARW's L0 runtime never
imports it.  It provides a bounded SQLite accountability projection only — no
embedding, graph-server, REST/MCP, or Explorer/UI surface.
"""

__all__ = [
    "ProvenanceRecord",
    "SemanticaSQLiteAdapter",
    "UnboundProvenanceError",
]


def __getattr__(name: str):
    """Lazily expose the optional adapter without importing it at L0."""

    if name in __all__:
        module = __import__("arw_semantica.adapter", fromlist=[name])
        return getattr(module, name)
    raise AttributeError(name)
