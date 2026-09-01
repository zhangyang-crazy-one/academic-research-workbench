"""FileProvider port: bounded read-only file retrieval.

Derived from the v1 file-plane MCP contracts (`arw.file_contracts`,
`arw.files_mcp.FilesMcpServer`). Implementations must preserve the v1 error
taxonomy and caps; golden fixtures in `tests/compat` pin the wire behavior.
"""

from __future__ import annotations

from typing import Protocol

from arw.file_models import (
    FilesContextRequest,
    FilesContextResult,
    FilesListRequest,
    FilesListResult,
    FilesOutlineRequest,
    FilesOutlineResult,
    FilesReadDenied,
    FilesReadRequest,
    FilesReadStale,
    FilesReadSuccess,
    FilesSearchRequest,
    FilesSearchResult,
)


class FileProvider(Protocol):
    """Read-only bounded file retrieval against one registered root."""

    def list_files(self, request: FilesListRequest) -> FilesListResult: ...

    def read_file(
        self, request: FilesReadRequest
    ) -> FilesReadSuccess | FilesReadStale | FilesReadDenied: ...

    def search_files(self, request: FilesSearchRequest) -> FilesSearchResult: ...

    def get_outline(self, request: FilesOutlineRequest) -> FilesOutlineResult: ...

    def get_context(self, request: FilesContextRequest) -> FilesContextResult: ...
