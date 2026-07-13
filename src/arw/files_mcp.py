"""One-root, read-only MCP server for immutable file generations."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from arw.canonical import canonical_json_bytes, strict_json_loads
from arw.file_contracts import CursorCodec, CursorError
from arw.file_models import (
    CONTRACT_LIMITS,
    FileListEntry,
    FilesContextRequest,
    FilesListRequest,
    FilesListResult,
    FilesOutlineRequest,
    FilesReadDenied,
    FilesReadRequest,
    FilesReadStale,
    FilesReadSuccess,
    FilesSearchRequest,
)
from arw.files import FilesAdminError, FilesQueryGeneration, load_query_generation


MAX_LIVE_FILE_BYTES = 64 * 1024 * 1024
SENSITIVE_COMPONENTS = {
    ".env",
    ".git",
    ".ssh",
    "credential",
    "credentials",
    "secret",
    "secrets",
}

TOOL_MODELS = {
    "list_files": FilesListRequest,
    "read_file": FilesReadRequest,
    "search_files": FilesSearchRequest,
    "get_outline": FilesOutlineRequest,
    "get_context": FilesContextRequest,
}


@dataclass(frozen=True)
class _LiveFile:
    body: bytes
    digest: str
    size_bytes: int


class LiveReadError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _sensitive(relative_path: str) -> bool:
    for component in PurePosixPath(relative_path).parts:
        lowered = component.lower()
        if (
            lowered in SENSITIVE_COMPONENTS
            or lowered.startswith(".env.")
            or lowered.endswith((".key", ".pem", ".p12"))
        ):
            return True
    return False


def _read_live(root: Path, relative_path: str, *, deadline: float) -> _LiveFile:
    if time.monotonic() > deadline:
        raise LiveReadError("timeout", "live verification exceeded the server deadline")
    if _sensitive(relative_path):
        raise LiveReadError("sensitive_path", "sensitive path names are not readable")
    parts = PurePosixPath(relative_path).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise LiveReadError("path_traversal", "path is not a normalized relative path")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    directory_fd = os.open(root, directory_flags)
    opened_directories = [directory_fd]
    file_fd: int | None = None
    try:
        for component in parts[:-1]:
            child = os.open(component, directory_flags, dir_fd=directory_fd)
            metadata = os.fstat(child)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(child)
                raise LiveReadError("not_directory", "path component is not a directory")
            opened_directories.append(child)
            directory_fd = child
        try:
            file_fd = os.open(parts[-1], os.O_RDONLY | nofollow, dir_fd=directory_fd)
        except FileNotFoundError as error:
            raise LiveReadError("deleted", "file no longer exists") from error
        except OSError as error:
            raise LiveReadError("symlink_escape", "file cannot be opened without following links") from error
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise LiveReadError("not_regular_file", "path does not name a regular file")
        if before.st_size > MAX_LIVE_FILE_BYTES:
            raise LiveReadError("source_too_large", "file exceeds the live verification ceiling")
        chunks: list[bytes] = []
        remaining = MAX_LIVE_FILE_BYTES + 1
        while remaining:
            if time.monotonic() > deadline:
                raise LiveReadError("timeout", "live verification exceeded the server deadline")
            chunk = os.read(file_fd, min(1 << 20, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0 and os.read(file_fd, 1):
            raise LiveReadError("source_too_large", "file exceeds the live verification ceiling")
        after = os.fstat(file_fd)
        try:
            path_now = os.stat(parts[-1], dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError as error:
            raise LiveReadError("descriptor_changed", "path changed after descriptor open") from error
        stable = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) and (after.st_dev, after.st_ino) == (path_now.st_dev, path_now.st_ino)
        if not stable:
            raise LiveReadError("descriptor_changed", "file changed during live verification")
        body = b"".join(chunks)
        return _LiveFile(
            body=body,
            digest=hashlib.sha256(body).hexdigest(),
            size_bytes=len(body),
        )
    finally:
        if file_fd is not None:
            os.close(file_fd)
        for descriptor in reversed(opened_directories):
            os.close(descriptor)


def _json_text(payload: object) -> str:
    return canonical_json_bytes(payload).decode("utf-8").rstrip("\n")


def _tool_envelope(payload: object, *, error: bool = False) -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": _json_text(payload)}],
        "isError": error,
    }


class FilesMcpServer:
    def __init__(self, generation: FilesQueryGeneration) -> None:
        self.generation = generation
        self.codec = CursorCodec(secret=generation.cursor_secret)
        self.identity_by_id = {item.file_id: item for item in generation.identity.records}
        self.generation_by_id = {item.file_id: item for item in generation.manifest.files}

    def tools(self) -> list[dict[str, object]]:
        descriptions = {
            "list_files": "List bounded generation metadata with live freshness.",
            "read_file": "Read one bounded live byte or UTF-8 line range.",
            "search_files": "Search the selected immutable generation.",
            "get_outline": "Return a bounded deterministic document outline.",
            "get_context": "Return bounded same-file context for one anchor.",
        }
        return [
            {
                "name": name,
                "description": descriptions[name],
                "inputSchema": model.model_json_schema(mode="validation"),
            }
            for name, model in TOOL_MODELS.items()
        ]

    def handle_tool(self, name: str, arguments: object) -> tuple[object, bool]:
        model = TOOL_MODELS.get(name)
        if model is None:
            return {"error_code": "unknown_tool", "message": "tool is not registered"}, True
        try:
            request = model.model_validate(arguments)
        except ValidationError as error:
            return {"error_code": "invalid_request", "message": str(error)}, True
        if request.root_id != self.generation.root.root_id:
            return {"error_code": "root_denied", "message": "request names another root"}, True
        deadline = time.monotonic() + (CONTRACT_LIMITS["timeout_ms"] / 1000)
        if name == "list_files":
            return self.list_files(request, deadline=deadline), False
        if name == "read_file":
            result = self.read_file(request, deadline=deadline)
            return result, result.status not in {"ok", "stale_conflict", "encoding_error"}
        return {
            "error_code": "tool_not_ready",
            "message": f"{name} requires the format/search projection plan",
        }, True

    def list_files(self, request: FilesListRequest, *, deadline: float) -> FilesListResult:
        parameters = {"max_files": request.max_files}
        offset = 0
        if request.cursor is not None:
            envelope = self.codec.decode(
                request.cursor,
                operation="list_files",
                root_id=request.root_id,
                parameters=parameters,
                generation_id=self.generation.selected.generation_id,
            )
            offset = int(envelope.position.get("offset", -1))
            if offset < 0:
                raise CursorError("cursor_position_invalid", "list cursor position is invalid")
        records = sorted(
            self.generation.identity.records,
            key=lambda item: (item.file_id, item.relative_path),
        )
        entries: list[FileListEntry] = []
        for record in records[offset : offset + request.max_files]:
            generation_file = self.generation_by_id[record.file_id]
            live: _LiveFile | None
            try:
                live = _read_live(
                    Path(self.generation.root.canonical_path),
                    record.relative_path,
                    deadline=deadline,
                )
            except LiveReadError as error:
                if error.code == "timeout":
                    raise
                live = None
            except OSError:
                live = None
            if record.file_type == "pdf":
                extraction_state = (
                    "registered" if generation_file.index_state == "indexed" else "degraded"
                )
            elif record.file_type == "binary":
                extraction_state = "not_applicable"
            else:
                extraction_state = "direct_text"
            current_digest = None if live is None else live.digest
            entries.append(
                FileListEntry(
                    file_id=record.file_id,
                    relative_path=record.relative_path,
                    file_type=record.file_type,
                    size_bytes=record.size_bytes if live is None else live.size_bytes,
                    current_digest=current_digest,
                    indexed_digest=record.digest,
                    extraction_state=extraction_state,
                    freshness="current" if current_digest == record.digest else "stale_metadata",
                )
            )
        next_offset = offset + len(entries)
        next_cursor = None
        if next_offset < len(records):
            next_cursor = self.codec.issue(
                operation="list_files",
                root_id=request.root_id,
                parameters=parameters,
                position={"offset": next_offset},
                ttl_seconds=300,
                generation_id=self.generation.selected.generation_id,
            )
        return FilesListResult(
            schema_version="1.0.0",
            root_id=request.root_id,
            selected_generation_id=self.generation.selected.generation_id,
            files=entries,
            next_cursor=next_cursor,
            complete_page=True,
        )

    def _read_denied(
        self, request: FilesReadRequest, status: str, code: str, message: str
    ) -> FilesReadDenied:
        return FilesReadDenied(
            schema_version="1.0.0",
            status=status,
            root_id=request.root_id,
            file_id=request.file_id,
            relative_path=request.relative_path,
            error_code=code,
            message=message,
        )

    def read_file(
        self, request: FilesReadRequest, *, deadline: float
    ) -> FilesReadSuccess | FilesReadStale | FilesReadDenied:
        record = self.identity_by_id.get(request.file_id)
        if record is None or record.relative_path != request.relative_path:
            return self._read_denied(
                request, "denied", "identity_mismatch", "file ID and relative path do not match"
            )
        if _sensitive(request.relative_path):
            return self._read_denied(
                request, "denied", "sensitive_path", "sensitive path names are not readable"
            )
        try:
            live = _read_live(
                Path(self.generation.root.canonical_path),
                request.relative_path,
                deadline=deadline,
            )
        except LiveReadError as error:
            if error.code == "timeout":
                return self._read_denied(request, "timeout", "timeout", str(error))
            if error.code in {"deleted", "descriptor_changed", "symlink_escape"}:
                stale_code = "deleted" if error.code == "deleted" else "descriptor_changed"
                return FilesReadStale(
                    schema_version="1.0.0",
                    status="stale_conflict",
                    root_id=request.root_id,
                    file_id=request.file_id,
                    relative_path=request.relative_path,
                    expected_digest=request.expected_digest or record.digest,
                    current_digest=None,
                    error_code=stale_code,
                    message=str(error),
                )
            return self._read_denied(request, "denied", error.code, str(error))
        except OSError as error:
            return self._read_denied(request, "denied", "read_failed", str(error))
        expected = request.expected_digest or live.digest
        if request.expected_digest is not None and request.expected_digest != live.digest:
            return FilesReadStale(
                schema_version="1.0.0",
                status="stale_conflict",
                root_id=request.root_id,
                file_id=request.file_id,
                relative_path=request.relative_path,
                expected_digest=request.expected_digest,
                current_digest=live.digest,
                error_code="digest_mismatch",
                message="live file digest differs from the expected digest",
            )

        mode = "bytes" if request.byte_range is not None else "lines"
        parameters: dict[str, object] = {"relative_path": request.relative_path}
        if request.byte_range is not None:
            parameters["max_bytes"] = request.byte_range.max_bytes
            position = request.byte_range.start
        else:
            assert request.line_range is not None
            parameters["max_lines"] = request.line_range.max_lines
            position = request.line_range.start_line
        if request.cursor is not None:
            envelope = self.codec.decode(
                request.cursor,
                operation="read_file",
                root_id=request.root_id,
                parameters=parameters,
                generation_id=self.generation.selected.generation_id,
                file_id=request.file_id,
                expected_digest=expected,
                range_mode=mode,
            )
            key = "offset" if mode == "bytes" else "line"
            position = int(envelope.position.get(key, -1))
            if position < (0 if mode == "bytes" else 1):
                raise CursorError("cursor_position_invalid", "read cursor position is invalid")

        if request.byte_range is not None:
            end = min(len(live.body), position + request.byte_range.max_bytes)
            content = base64.b64encode(live.body[position:end]).decode("ascii")
            truncated = end < len(live.body)
            next_position = {"offset": end}
            encoding = "bytes"
        else:
            assert request.line_range is not None
            try:
                text_body = live.body.decode("utf-8")
            except UnicodeDecodeError:
                return self._read_denied(
                    request, "encoding_error", "invalid_utf8", "line ranges require strict UTF-8"
                )
            lines = text_body.splitlines(keepends=True)
            start_index = min(len(lines), position - 1)
            end_index = min(len(lines), start_index + request.line_range.max_lines)
            content = "".join(lines[start_index:end_index])
            if len(content.encode("utf-8")) > CONTRACT_LIMITS["read_bytes"]:
                return self._read_denied(
                    request,
                    "budget_exceeded",
                    "read_bytes_exceeded",
                    "line result exceeds the byte ceiling",
                )
            truncated = end_index < len(lines)
            next_position = {"line": end_index + 1}
            encoding = "utf-8"
        next_cursor = None
        if truncated:
            next_cursor = self.codec.issue(
                operation="read_file",
                root_id=request.root_id,
                parameters=parameters,
                position=next_position,
                ttl_seconds=300,
                generation_id=self.generation.selected.generation_id,
                file_id=request.file_id,
                expected_digest=expected,
                range_mode=mode,
            )
        return FilesReadSuccess(
            schema_version="1.0.0",
            status="ok",
            root_id=request.root_id,
            file_id=request.file_id,
            relative_path=request.relative_path,
            current_digest=live.digest,
            encoding=encoding,
            content=content,
            truncated=truncated,
            next_cursor=next_cursor,
        )

    def handle(self, request: object) -> dict[str, object] | None:
        if not isinstance(request, dict):
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
        identifier = request.get("id")
        if identifier is None:
            return None
        method = request.get("method")
        params = request.get("params", {})
        try:
            if method == "initialize":
                result: object = {
                    "protocolVersion": "2025-03-26",
                    "serverInfo": {"name": "academic-research-files", "version": "1.0.0"},
                    "capabilities": {"tools": {"listChanged": False}},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.tools()}
            elif method == "tools/call" and isinstance(params, dict):
                name = params.get("name")
                arguments = params.get("arguments", {})
                payload, error = self.handle_tool(name if isinstance(name, str) else "", arguments)
                if hasattr(payload, "model_dump"):
                    payload = payload.model_dump(mode="json")
                result = _tool_envelope(payload, error=error)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": identifier,
                    "error": {"code": -32601, "message": "Method not found"},
                }
        except (CursorError, LiveReadError) as error:
            result = _tool_envelope({"error_code": error.code, "message": str(error)}, error=True)
        return {"jsonrpc": "2.0", "id": identifier, "result": result}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="academic-research-files")
    parser.add_argument("--control-root", required=True, type=Path)
    parser.add_argument("--root-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments.count("--control-root") != 1 or arguments.count("--root-id") != 1:
        print(
            "files-mcp: startup-error: exactly one control root and root ID are required",
            file=sys.stderr,
        )
        return 64
    args = build_parser().parse_args(arguments)
    try:
        generation = load_query_generation(args.control_root, args.root_id)
    except FilesAdminError as error:
        print(f"files-mcp: startup-error: {error.code}: {error}", file=sys.stderr)
        return 78
    server = FilesMcpServer(generation)
    for raw_line in sys.stdin.buffer:
        try:
            request = strict_json_loads(raw_line)
        except (UnicodeError, ValueError) as error:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {error}"},
            }
        else:
            response = server.handle(request)
        if response is not None:
            sys.stdout.buffer.write(canonical_json_bytes(response))
            sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
