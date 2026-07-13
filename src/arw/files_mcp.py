"""One-root, read-only MCP server for immutable file generations."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import time
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from arw.canonical import canonical_json_bytes, strict_json_loads
from arw.file_contracts import CursorCodec, CursorError
from arw.file_models import (
    CONTRACT_LIMITS,
    RANKING_VERSION,
    TOKENIZER_ID,
    FileSearchHit,
    FileListEntry,
    FilesContextResult,
    FilesContextRequest,
    FilesListRequest,
    FilesListResult,
    FilesOutlineResult,
    FilesOutlineRequest,
    FilesReadDenied,
    FilesReadRequest,
    FilesReadStale,
    FilesReadSuccess,
    FilesSearchResult,
    FilesSearchRequest,
    OutlineNode,
    SourceLocation,
)
from arw.files import FilesAdminError, FilesQueryGeneration, load_query_generation


MAX_LIVE_FILE_BYTES = 64 * 1024 * 1024
MAX_SEARCH_CANDIDATES = 10_000
MAX_CONTEXT_BYTES = CONTRACT_LIMITS["read_bytes"]
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


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class _IndexedFile:
    file_id: str
    relative_path: str
    file_type: str
    source_digest: str
    index_state: str
    degraded_reason: str | None
    extraction_registration_sha256: str | None
    body: str | None


@dataclass(frozen=True)
class _RankedMatch:
    indexed: _IndexedFile
    score: float
    location: SourceLocation
    snippet: str | None


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


def _byte_offset(text: str, character_offset: int) -> int:
    return len(text[:character_offset].encode("utf-8"))


def _source_location(text: str, start: int, end: int) -> SourceLocation:
    start_line = text.count("\n", 0, start) + 1
    end_line = text.count("\n", 0, max(start, end - 1)) + 1
    return SourceLocation(
        start_byte=_byte_offset(text, start),
        end_byte=_byte_offset(text, end),
        start_line=start_line,
        end_line=end_line,
    )


def _bounded_snippet(text: str, start: int, end: int, maximum: int) -> str | None:
    if maximum == 0:
        return None
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    candidate = text[line_start:line_end]
    if len(candidate.encode("utf-8")) <= maximum:
        return candidate
    matched = text[start:end]
    matched_bytes = matched.encode("utf-8")
    if len(matched_bytes) >= maximum:
        output = bytearray()
        for character in matched:
            encoded = character.encode("utf-8")
            if len(output) + len(encoded) > maximum:
                break
            output.extend(encoded)
        return output.decode("utf-8")
    left_budget = (maximum - len(matched_bytes)) // 2
    right_budget = maximum - len(matched_bytes) - left_budget
    prefix = bytearray()
    for character in reversed(text[line_start:start]):
        encoded = character.encode("utf-8")
        if len(prefix) + len(encoded) > left_budget:
            break
        prefix[:0] = encoded
    suffix = bytearray()
    for character in text[end:line_end]:
        encoded = character.encode("utf-8")
        if len(suffix) + len(encoded) > right_budget:
            break
        suffix.extend(encoded)
    return prefix.decode("utf-8") + matched + suffix.decode("utf-8")


def _line_spans(text: str) -> list[tuple[str, int, int, int, int]]:
    spans: list[tuple[str, int, int, int, int]] = []
    character = 0
    byte = 0
    for line_number, raw in enumerate(text.splitlines(keepends=True), start=1):
        content = raw.rstrip("\r\n")
        character_end = character + len(content)
        byte_end = byte + len(content.encode("utf-8"))
        spans.append((content, character, character_end, byte, byte_end))
        character += len(raw)
        byte += len(raw.encode("utf-8"))
    if not spans and text == "":
        return []
    if text and not text.splitlines(keepends=True):
        spans.append((text, 0, len(text), 0, len(text.encode("utf-8"))))
    return spans


def _outline_nodes(file_type: str, text: str) -> tuple[str | None, list[OutlineNode]]:
    lines = _line_spans(text)
    nodes: list[OutlineNode] = []
    if file_type == "markdown":
        parser = "markdown-outline-v1"
        for index, (line, _, _, start_byte, end_byte) in enumerate(lines):
            atx = re.match(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", line)
            if atx:
                title = atx.group(2).strip()
                nodes.append(
                    OutlineNode(
                        level=len(atx.group(1)),
                        kind="markdown_heading",
                        title=title,
                        location=SourceLocation(
                            start_byte=start_byte,
                            end_byte=end_byte,
                            start_line=index + 1,
                            end_line=index + 1,
                        ),
                    )
                )
                continue
            if index == 0 or not re.match(r"^[ \t]*(?:=+|-+)[ \t]*$", line):
                continue
            previous, _, _, previous_start, previous_end = lines[index - 1]
            title = previous.strip()
            if title:
                nodes.append(
                    OutlineNode(
                        level=1 if "=" in line else 2,
                        kind="markdown_heading",
                        title=title,
                        location=SourceLocation(
                            start_byte=previous_start,
                            end_byte=end_byte,
                            start_line=index,
                            end_line=index + 1,
                        ),
                    )
                )
        return parser, nodes
    if file_type == "latex":
        parser = "latex-outline-v1"
        levels = {
            "part": 1,
            "chapter": 1,
            "section": 1,
            "subsection": 2,
            "subsubsection": 3,
            "paragraph": 4,
            "subparagraph": 5,
        }
        pattern = re.compile(
            r"^[ \t]*\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\{([^{}]+)\}"
        )
        for index, (line, _, _, start_byte, end_byte) in enumerate(lines):
            match = pattern.match(line)
            if match:
                command, title = match.groups()
                nodes.append(
                    OutlineNode(
                        level=levels[command],
                        kind=f"latex_{command}",
                        title=title.strip(),
                        location=SourceLocation(
                            start_byte=start_byte,
                            end_byte=end_byte,
                            start_line=index + 1,
                            end_line=index + 1,
                        ),
                    )
                )
        return parser, nodes
    if file_type == "bibtex":
        parser = "bibtex-outline-v1"
        pattern = re.compile(r"^[ \t]*@([A-Za-z]+)[ \t]*\{[ \t]*([^,\s}]+)")
        for index, (line, _, _, start_byte, end_byte) in enumerate(lines):
            match = pattern.match(line)
            if match:
                nodes.append(
                    OutlineNode(
                        level=1,
                        kind="bibtex_entry",
                        title=match.group(2),
                        location=SourceLocation(
                            start_byte=start_byte,
                            end_byte=end_byte,
                            start_line=index + 1,
                            end_line=index + 1,
                        ),
                    )
                )
        return parser, nodes
    if file_type == "source":
        parser = "source-outline-v1"
        python_pattern = re.compile(
            r"^[ \t]*(?:(async)[ \t]+)?(def|class)[ \t]+([A-Za-z_][A-Za-z0-9_]*)"
        )
        generic_pattern = re.compile(
            r"^[ \t]*(?:export[ \t]+)?(?:function|class|interface|struct|enum)[ \t]+([A-Za-z_][A-Za-z0-9_]*)"
        )
        for index, (line, _, _, start_byte, end_byte) in enumerate(lines):
            python = python_pattern.match(line)
            if python:
                asynchronous, shape, title = python.groups()
                kind = "source_class" if shape == "class" else "source_function"
                if asynchronous:
                    kind = "source_async_function"
            else:
                generic = generic_pattern.match(line)
                if not generic:
                    continue
                title = generic.group(1)
                kind = "source_symbol"
            nodes.append(
                OutlineNode(
                    level=1,
                    kind=kind,
                    title=title,
                    location=SourceLocation(
                        start_byte=start_byte,
                        end_byte=end_byte,
                        start_line=index + 1,
                        end_line=index + 1,
                    ),
                )
            )
        return parser, nodes
    return None, []


class FilesMcpServer:
    def __init__(self, generation: FilesQueryGeneration) -> None:
        self.generation = generation
        self.codec = CursorCodec(secret=generation.cursor_secret)
        self.hit_codec = CursorCodec(secret=generation.cursor_secret, clock=lambda: 0)
        self.identity_by_id = {item.file_id: item for item in generation.identity.records}
        self.generation_by_id = {item.file_id: item for item in generation.manifest.files}

    def _database_rows(
        self,
        sql: str,
        parameters: tuple[object, ...],
        *,
        deadline: float,
    ) -> list[sqlite3.Row]:
        if time.monotonic() > deadline:
            raise ToolError("timeout", "query exceeded the server deadline")
        uri = f"file:{self.generation.database_path}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        denied = {
            sqlite3.SQLITE_ATTACH,
            sqlite3.SQLITE_ALTER_TABLE,
            sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_CREATE_TEMP_INDEX,
            sqlite3.SQLITE_CREATE_TEMP_TABLE,
            sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
            sqlite3.SQLITE_CREATE_TEMP_VIEW,
            sqlite3.SQLITE_CREATE_TRIGGER,
            sqlite3.SQLITE_CREATE_VIEW,
            sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_DETACH,
            sqlite3.SQLITE_DROP_INDEX,
            sqlite3.SQLITE_DROP_TABLE,
            sqlite3.SQLITE_DROP_TEMP_INDEX,
            sqlite3.SQLITE_DROP_TEMP_TABLE,
            sqlite3.SQLITE_DROP_TEMP_TRIGGER,
            sqlite3.SQLITE_DROP_TEMP_VIEW,
            sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_DROP_VIEW,
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_REINDEX,
            sqlite3.SQLITE_TRANSACTION,
            sqlite3.SQLITE_UPDATE,
        }
        connection.set_authorizer(
            lambda action, _one, _two, _database, _trigger: (
                sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK
            )
        )
        connection.set_progress_handler(
            lambda: 1 if time.monotonic() > deadline else 0,
            1_000,
        )
        try:
            return connection.execute(sql, parameters).fetchall()
        except sqlite3.OperationalError as error:
            if "interrupted" in str(error).lower() or time.monotonic() > deadline:
                raise ToolError("timeout", "query exceeded the server deadline") from error
            raise ToolError("query_failed", "immutable generation query failed") from error
        finally:
            connection.close()

    @staticmethod
    def _indexed_from_row(row: sqlite3.Row) -> _IndexedFile:
        return _IndexedFile(
            file_id=str(row["file_id"]),
            relative_path=str(row["relative_path"]),
            file_type=str(row["file_type"]),
            source_digest=str(row["source_digest"]),
            index_state=str(row["index_state"]),
            degraded_reason=(
                None if row["degraded_reason"] is None else str(row["degraded_reason"])
            ),
            extraction_registration_sha256=(
                None
                if row["extraction_registration_sha256"] is None
                else str(row["extraction_registration_sha256"])
            ),
            body=None if row["body"] is None else str(row["body"]),
        )

    def _indexed_file(self, file_id: str, *, deadline: float) -> _IndexedFile | None:
        rows = self._database_rows(
            """
            SELECT file_id, relative_path, file_type, source_digest, index_state,
                   degraded_reason, extraction_registration_sha256, body
              FROM files WHERE file_id = ?
            """,
            (file_id,),
            deadline=deadline,
        )
        return None if not rows else self._indexed_from_row(rows[0])

    def _live_digest(
        self,
        indexed: _IndexedFile,
        *,
        deadline: float,
    ) -> tuple[str | None, bool]:
        try:
            live = _read_live(
                Path(self.generation.root.canonical_path),
                indexed.relative_path,
                deadline=deadline,
            )
        except LiveReadError as error:
            if error.code == "timeout":
                raise ToolError("timeout", str(error)) from error
            return None, False
        except OSError:
            return None, False
        return live.digest, live.digest == indexed.source_digest

    def _check_generation(self, generation_id: str) -> None:
        if generation_id != self.generation.selected.generation_id:
            raise ToolError(
                "generation_mismatch", "request does not bind the startup-selected generation"
            )

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
        if name == "search_files":
            return self.search_files(request, deadline=deadline), False
        if name == "get_outline":
            return self.get_outline(request, deadline=deadline), False
        if name == "get_context":
            return self.get_context(request, deadline=deadline), False
        raise ToolError("unknown_tool", "tool is not registered")

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

    @staticmethod
    def _normalize_query(mode: str, query: str) -> tuple[str, list[str]]:
        if mode == "exact":
            normalized = unicodedata.normalize("NFC", query)
            return normalized, [normalized]
        normalized = " ".join(unicodedata.normalize("NFKC", query).casefold().split())
        terms = normalized.split(" ")
        if not terms or any(not term for term in terms):
            raise ToolError("query_empty", "full-text query has no searchable terms")
        return normalized, terms

    def _rank_search_rows(
        self,
        request: FilesSearchRequest,
        normalized_query: str,
        terms: list[str],
        *,
        deadline: float,
    ) -> list[_RankedMatch]:
        rows = self._database_rows(
            f"""
            SELECT file_id, relative_path, file_type, source_digest, index_state,
                   degraded_reason, extraction_registration_sha256, body
              FROM files
             WHERE index_state = 'indexed' AND body IS NOT NULL
             ORDER BY file_id
             LIMIT {MAX_SEARCH_CANDIDATES + 1}
            """,
            (),
            deadline=deadline,
        )
        if len(rows) > MAX_SEARCH_CANDIDATES:
            raise ToolError("candidate_budget_exceeded", "search candidate ceiling exceeded")
        ranked: list[_RankedMatch] = []
        for row in rows:
            if time.monotonic() > deadline:
                raise ToolError("timeout", "search exceeded the server deadline")
            indexed = self._indexed_from_row(row)
            assert indexed.body is not None
            if request.mode == "exact":
                normalized_body = unicodedata.normalize("NFC", indexed.body)
                start = normalized_body.find(normalized_query)
                if start < 0:
                    continue
                end = start + len(normalized_query)
                score = float(normalized_body.count(normalized_query))
            else:
                folded = unicodedata.normalize("NFKC", indexed.body).casefold()
                positions = [folded.find(term) for term in terms]
                if any(position < 0 for position in positions):
                    continue
                first_index = min(range(len(positions)), key=lambda index: positions[index])
                start = positions[first_index]
                end = start + len(terms[first_index])
                score = round(
                    sum(folded.count(term) for term in terms) / len(terms),
                    6,
                )
            location = _source_location(indexed.body, start, end)
            ranked.append(
                _RankedMatch(
                    indexed=indexed,
                    score=score,
                    location=location,
                    snippet=_bounded_snippet(
                        indexed.body,
                        start,
                        end,
                        request.max_snippet_bytes,
                    ),
                )
            )
        ranked.sort(
            key=lambda match: (
                -match.score,
                match.indexed.file_id,
                match.location.start_byte,
            )
        )
        return ranked

    def search_files(
        self,
        request: FilesSearchRequest,
        *,
        deadline: float,
    ) -> FilesSearchResult:
        normalized_query, terms = self._normalize_query(request.mode, request.query)
        parameters = {
            "mode": request.mode,
            "normalized_query": normalized_query,
            "max_hits": request.max_hits,
            "max_snippet_bytes": request.max_snippet_bytes,
            "tokenizer_id": TOKENIZER_ID,
            "ranking_version": RANKING_VERSION,
        }
        offset = 0
        if request.cursor is not None:
            envelope = self.codec.decode(
                request.cursor,
                operation="search_files",
                root_id=request.root_id,
                parameters=parameters,
                generation_id=self.generation.selected.generation_id,
            )
            offset = int(envelope.position.get("offset", -1))
            if offset < 0:
                raise CursorError("cursor_position_invalid", "search cursor position is invalid")
        ranked = self._rank_search_rows(
            request,
            normalized_query,
            terms,
            deadline=deadline,
        )
        page = ranked[offset : offset + request.max_hits]
        hits: list[FileSearchHit] = []
        for match in page:
            current_digest, current = self._live_digest(match.indexed, deadline=deadline)
            if current:
                location_payload = match.location.model_dump(mode="json")
                hit_id = self.hit_codec.issue(
                    operation="search_hit",
                    root_id=request.root_id,
                    parameters={"anchor_version": "search-hit-v1"},
                    position=location_payload,
                    ttl_seconds=3_600,
                    generation_id=self.generation.selected.generation_id,
                    file_id=match.indexed.file_id,
                    expected_digest=match.indexed.source_digest,
                    range_mode="context",
                )
                hits.append(
                    FileSearchHit(
                        hit_id=hit_id,
                        file_id=match.indexed.file_id,
                        relative_path=match.indexed.relative_path,
                        file_type=match.indexed.file_type,
                        indexed_digest=match.indexed.source_digest,
                        current_digest=current_digest,
                        extraction_registration_sha256=(
                            match.indexed.extraction_registration_sha256
                        ),
                        freshness="current",
                        sync_required=False,
                        score=match.score,
                        location=match.location,
                        snippet=match.snippet,
                    )
                )
            else:
                hits.append(
                    FileSearchHit(
                        hit_id=None,
                        file_id=match.indexed.file_id,
                        relative_path=match.indexed.relative_path,
                        file_type=match.indexed.file_type,
                        indexed_digest=match.indexed.source_digest,
                        current_digest=current_digest,
                        extraction_registration_sha256=(
                            match.indexed.extraction_registration_sha256
                        ),
                        freshness="stale_metadata",
                        sync_required=True,
                        score=None,
                        location=None,
                        snippet=None,
                    )
                )
        next_offset = offset + len(page)
        next_cursor = None
        if next_offset < len(ranked):
            next_cursor = self.codec.issue(
                operation="search_files",
                root_id=request.root_id,
                parameters=parameters,
                position={"offset": next_offset},
                ttl_seconds=300,
                generation_id=self.generation.selected.generation_id,
            )
        if time.monotonic() > deadline:
            raise ToolError("timeout", "search exceeded the server deadline")
        return FilesSearchResult(
            schema_version="1.0.0",
            root_id=request.root_id,
            generation_id=self.generation.selected.generation_id,
            mode=request.mode,
            normalized_query=normalized_query,
            tokenizer_id=TOKENIZER_ID,
            ranking_version=RANKING_VERSION,
            hits=hits,
            next_cursor=next_cursor,
            complete_page=True,
        )

    def get_outline(
        self,
        request: FilesOutlineRequest,
        *,
        deadline: float,
    ) -> FilesOutlineResult:
        self._check_generation(request.generation_id)
        indexed = self._indexed_file(request.file_id, deadline=deadline)
        if indexed is None:
            raise ToolError("file_not_found", "file ID is absent from the selected generation")
        current_digest, current = self._live_digest(indexed, deadline=deadline)
        base = {
            "schema_version": "1.0.0",
            "root_id": request.root_id,
            "generation_id": request.generation_id,
            "file_id": request.file_id,
            "indexed_digest": indexed.source_digest,
            "current_digest": current_digest,
            "extraction_registration_sha256": indexed.extraction_registration_sha256,
        }
        if request.expected_digest != indexed.source_digest or not current:
            return FilesOutlineResult(
                **base,
                status="stale_conflict",
                parser_version=None,
                nodes=[],
                next_cursor=None,
            )
        if indexed.index_state != "indexed" or indexed.body is None:
            return FilesOutlineResult(
                **base,
                status="degraded",
                parser_version=None,
                nodes=[],
                next_cursor=None,
            )
        parser_version, nodes = _outline_nodes(indexed.file_type, indexed.body)
        if not nodes:
            return FilesOutlineResult(
                **base,
                status="no_structure",
                parser_version=parser_version,
                nodes=[],
                next_cursor=None,
            )
        parameters = {
            "max_nodes": request.max_nodes,
            "parser_version": parser_version,
        }
        offset = 0
        if request.cursor is not None:
            envelope = self.codec.decode(
                request.cursor,
                operation="get_outline",
                root_id=request.root_id,
                parameters=parameters,
                generation_id=request.generation_id,
                file_id=request.file_id,
                expected_digest=request.expected_digest,
                range_mode="nodes",
            )
            offset = int(envelope.position.get("offset", -1))
            if offset < 0:
                raise CursorError("cursor_position_invalid", "outline cursor position is invalid")
        page = nodes[offset : offset + request.max_nodes]
        next_offset = offset + len(page)
        next_cursor = None
        if next_offset < len(nodes):
            next_cursor = self.codec.issue(
                operation="get_outline",
                root_id=request.root_id,
                parameters=parameters,
                position={"offset": next_offset},
                ttl_seconds=300,
                generation_id=request.generation_id,
                file_id=request.file_id,
                expected_digest=request.expected_digest,
                range_mode="nodes",
            )
        return FilesOutlineResult(
            **base,
            status="ok",
            parser_version=parser_version,
            nodes=page,
            next_cursor=next_cursor,
        )

    @staticmethod
    def _context_window(
        body: str,
        anchor: SourceLocation,
        *,
        before_lines: int,
        after_lines: int,
    ) -> tuple[SourceLocation, str, bool]:
        body_bytes = body.encode("utf-8")
        if anchor.end_byte > len(body_bytes):
            raise ToolError("anchor_out_of_range", "context anchor exceeds the indexed body")
        try:
            body_bytes[: anchor.start_byte].decode("utf-8")
            body_bytes[: anchor.end_byte].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ToolError("anchor_not_utf8_boundary", "context anchor splits a UTF-8 sequence") from error
        raw_lines = body.splitlines(keepends=True)
        if not raw_lines:
            raise ToolError("anchor_out_of_range", "context anchor names an empty body")
        starts: list[int] = []
        offset = 0
        for line in raw_lines:
            starts.append(offset)
            offset += len(line.encode("utf-8"))
        start_index = max(0, bisect_right(starts, anchor.start_byte) - 1)
        last_byte = max(anchor.start_byte, anchor.end_byte - 1)
        end_index = max(start_index, bisect_right(starts, last_byte) - 1)
        window_start = max(0, start_index - before_lines)
        window_end = min(len(raw_lines), end_index + after_lines + 1)
        context = "".join(raw_lines[window_start:window_end])
        if len(context.encode("utf-8")) > MAX_CONTEXT_BYTES:
            raise ToolError("context_budget_exceeded", "context exceeds the byte ceiling")
        start_byte = starts[window_start]
        end_byte = starts[window_end] if window_end < len(starts) else len(body_bytes)
        location = SourceLocation(
            start_byte=start_byte,
            end_byte=end_byte,
            start_line=window_start + 1,
            end_line=window_end,
        )
        return location, context, window_start > 0 or window_end < len(raw_lines)

    def get_context(
        self,
        request: FilesContextRequest,
        *,
        deadline: float,
    ) -> FilesContextResult:
        self._check_generation(request.generation_id)
        indexed = self._indexed_file(request.file_id, deadline=deadline)
        if indexed is None:
            raise ToolError("file_not_found", "file ID is absent from the selected generation")
        current_digest, current = self._live_digest(indexed, deadline=deadline)
        base = {
            "schema_version": "1.0.0",
            "root_id": request.root_id,
            "generation_id": request.generation_id,
            "file_id": request.file_id,
            "indexed_digest": indexed.source_digest,
            "current_digest": current_digest,
            "extraction_registration_sha256": indexed.extraction_registration_sha256,
        }
        if request.expected_digest != indexed.source_digest or not current:
            return FilesContextResult(
                **base,
                status="stale_conflict",
                location=None,
                context=None,
                truncated=False,
            )
        if indexed.index_state != "indexed" or indexed.body is None:
            return FilesContextResult(
                **base,
                status="degraded",
                location=None,
                context=None,
                truncated=False,
            )
        if request.hit_id is not None:
            envelope = self.hit_codec.decode(
                request.hit_id,
                operation="search_hit",
                root_id=request.root_id,
                parameters={"anchor_version": "search-hit-v1"},
                generation_id=request.generation_id,
                file_id=request.file_id,
                expected_digest=request.expected_digest,
                range_mode="context",
            )
            try:
                anchor = SourceLocation.model_validate(envelope.position)
            except ValidationError as error:
                raise CursorError("cursor_position_invalid", "search hit anchor is invalid") from error
        else:
            assert request.location is not None
            anchor = request.location
        location, context, truncated = self._context_window(
            indexed.body,
            anchor,
            before_lines=request.before_lines,
            after_lines=request.after_lines,
        )
        if time.monotonic() > deadline:
            raise ToolError("timeout", "context query exceeded the server deadline")
        return FilesContextResult(
            **base,
            status="ok",
            location=location,
            context=context,
            truncated=truncated,
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
        except (CursorError, LiveReadError, ToolError) as error:
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
