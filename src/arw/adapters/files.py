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


class FileProviderError(RuntimeError):
    """Typed failure carrying the v1 file-plane error taxonomy."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LocalFilesAdapter:
    """FileProvider over the in-repo Python files MCP server (read-only)."""

    def __init__(self, generation: FilesQueryGeneration) -> None:
        self._server = FilesMcpServer(generation)

    def _check_root(self, root_id: str) -> None:
        """Preserve the MCP root_denied check that handle_tool performs."""
        if root_id != self._server.generation.root.root_id:
            raise FileProviderError("root_denied", "request names another root")

    def list_files(self, request: FilesListRequest) -> FilesListResult:
        self._check_root(request.root_id)
        import time

        return self._server.list_files(request, deadline=time.monotonic() + 5.0)

    def read_file(
        self, request: FilesReadRequest
    ) -> FilesReadSuccess | FilesReadStale | FilesReadDenied:
        self._check_root(request.root_id)
        import time

        return self._server.read_file(request, deadline=time.monotonic() + 5.0)

    def search_files(self, request: FilesSearchRequest) -> FilesSearchResult:
        self._check_root(request.root_id)
        import time

        return self._server.search_files(request, deadline=time.monotonic() + 5.0)

    def get_outline(self, request: FilesOutlineRequest) -> FilesOutlineResult:
        self._check_root(request.root_id)
        import time

        return self._server.get_outline(request, deadline=time.monotonic() + 5.0)

    def get_context(self, request: FilesContextRequest) -> FilesContextResult:
        self._check_root(request.root_id)
        import time

        return self._server.get_context(request, deadline=time.monotonic() + 5.0)
