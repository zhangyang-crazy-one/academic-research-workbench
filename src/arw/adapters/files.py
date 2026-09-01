"""FileProvider adapters for the v1 file-plane implementations.

LocalFilesAdapter wraps the in-repo pure-Python server path without changing
behavior. The vendored native file-base MCP binary is NOT adapted here: no
v2 consumer selects it through this port yet, and building a subprocess
JSON-RPC client adapter is speculative until plugin-first-routing (PR5)
switches the Codex default provider — the native binary remains reachable
via the existing `python -m arw.files_mcp` / `_graph-mcp` entry points and
the pinned MCP goldens in tests/compat.
"""

from __future__ import annotations

from arw.file_contracts import CursorError
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
from arw.files_mcp import FilesMcpServer, ToolError


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

        try:
            return self._server.list_files(request, deadline=time.monotonic() + 5.0)
        except (CursorError, ToolError) as error:
            code = getattr(error, 'code', 'tool_error')
            raise FileProviderError(code, str(error)) from error

    def read_file(
        self, request: FilesReadRequest
    ) -> FilesReadSuccess | FilesReadStale | FilesReadDenied:
        self._check_root(request.root_id)
        import time

        try:
            return self._server.read_file(request, deadline=time.monotonic() + 5.0)
        except (CursorError, ToolError) as error:
            code = getattr(error, 'code', 'tool_error')
            raise FileProviderError(code, str(error)) from error

    def search_files(self, request: FilesSearchRequest) -> FilesSearchResult:
        self._check_root(request.root_id)
        import time

        try:
            return self._server.search_files(request, deadline=time.monotonic() + 5.0)
        except (CursorError, ToolError) as error:
            code = getattr(error, 'code', 'tool_error')
            raise FileProviderError(code, str(error)) from error

    def get_outline(self, request: FilesOutlineRequest) -> FilesOutlineResult:
        self._check_root(request.root_id)
        import time

        try:
            return self._server.get_outline(request, deadline=time.monotonic() + 5.0)
        except (CursorError, ToolError) as error:
            code = getattr(error, 'code', 'tool_error')
            raise FileProviderError(code, str(error)) from error

    def get_context(self, request: FilesContextRequest) -> FilesContextResult:
        self._check_root(request.root_id)
        import time

        try:
            return self._server.get_context(request, deadline=time.monotonic() + 5.0)
        except (CursorError, ToolError) as error:
            code = getattr(error, 'code', 'tool_error')
            raise FileProviderError(code, str(error)) from error
