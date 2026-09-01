"""FileProvider adapters for the v1 file-plane implementations.

Both wrap the existing strict services without changing behavior:
- LocalFilesAdapter drives the in-repo pure-Python server path.
- FileBaseMCPAdapter keeps the vendored native MCP binary reachable.
"""

from __future__ import annotations

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
from arw.files import FilesQueryGeneration
from arw.files_mcp import FilesMcpServer


class LocalFilesAdapter:
    """FileProvider over the in-repo Python files MCP server (read-only)."""

    def __init__(self, generation: FilesQueryGeneration) -> None:
        self._server = FilesMcpServer(generation)

    def list_files(self, request: FilesListRequest) -> FilesListResult:
        import time

        return self._server.list_files(request, deadline=time.monotonic() + 5.0)

    def read_file(
        self, request: FilesReadRequest
    ) -> FilesReadSuccess | FilesReadStale | FilesReadDenied:
        import time

        return self._server.read_file(request, deadline=time.monotonic() + 5.0)

    def search_files(self, request: FilesSearchRequest) -> FilesSearchResult:
        import time

        return self._server.search_files(request, deadline=time.monotonic() + 5.0)

    def get_outline(self, request: FilesOutlineRequest) -> FilesOutlineResult:
        import time

        return self._server.get_outline(request, deadline=time.monotonic() + 5.0)

    def get_context(self, request: FilesContextRequest) -> FilesContextResult:
        import time

        return self._server.get_context(request, deadline=time.monotonic() + 5.0)
