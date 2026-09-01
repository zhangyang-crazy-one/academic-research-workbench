"""Repository-bundled extension packages (`arw_ext.*`).

These packages live alongside the kernel in the same wheel but are not part of
the kernel import surface.  The kernel never depends on `arw_ext`; each
extension depends on the kernel through the public ports and the
`arw.kernel.core.canonical` helpers.  See
``tests/compat/test_local_store_dependency_direction.py`` for the enforcement.
"""

from __future__ import annotations

__all__ = ["local_store"]