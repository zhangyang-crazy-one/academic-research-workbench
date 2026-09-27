"""Resolve exact source locators from retained, canonically accepted artifacts."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path, PurePosixPath

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.manifests import (
    ManifestError,
    _read_direct_file,
    load_artifact_manifest,
)
from arw.kernel.state.models import ArtifactAcceptedPayload
from arw.kernel.state.provenance import (
    ByteChunk,
    LineRange,
    MarkdownSection,
    PdfLocation,
    PreciseProvenanceRecord,
    SourceLocator,
    TextPage,
    decode_provenance,
)

MAX_SOURCE_BYTES = 8_388_608


class SourceLocatorError(ValueError):
    code = "source-locator-invalid"


def read_retained_bytes(
    root: Path, relative: str, *, max_bytes: int = MAX_SOURCE_BYTES
) -> bytes:
    """Bound regular-file reads and reject traversal and symlink ancestors."""
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or "\\" in relative
        or "\x00" in relative
        or any(p in {"", ".", ".."} for p in relative.split("/"))
    ):
        raise SourceLocatorError("source path is not a normalized relative path")
    root = Path(root)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise SourceLocatorError("source root contains a symlink")
    if not 1 <= max_bytes <= MAX_SOURCE_BYTES:
        raise SourceLocatorError("source read budget is invalid")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        if os.open not in os.supports_dir_fd or not getattr(os, "O_NOFOLLOW", 0):
            cursor = root
            for part in path.parts:
                cursor /= part
                if cursor.is_symlink():
                    raise SourceLocatorError("source path contains a symlink")
            return _read_direct_file(cursor, max_bytes=max_bytes)
        descriptor = os.open(root, flags | os.O_DIRECTORY)
        try:
            for part in path.parts[:-1]:
                child = os.open(part, flags | os.O_DIRECTORY, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            content = os.open(path.name, flags, dir_fd=descriptor)
            try:
                before = os.fstat(content)
                if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
                    raise SourceLocatorError("source is not a bounded regular file")
                chunks = []
                total = 0
                while total <= max_bytes:
                    block = os.read(content, min(65536, max_bytes + 1 - total))
                    if not block:
                        break
                    chunks.append(block)
                    total += len(block)
                after = os.fstat(content)
                if (
                    total > max_bytes
                    or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns
                ):
                    raise SourceLocatorError(
                        "source changed or exceeded its read budget"
                    )
                return b"".join(chunks)
            finally:
                os.close(content)
        finally:
            os.close(descriptor)
    except (OSError, ManifestError) as error:
        raise SourceLocatorError("retained source is unavailable or unsafe") from error


def located_bytes(raw: bytes, locator: SourceLocator) -> bytes:
    location = locator.location
    if isinstance(location, PdfLocation):
        if location.end > len(raw):
            raise SourceLocatorError("PDF span is outside retained extraction")
        return raw[location.start:location.end]
    if isinstance(location, ByteChunk):
        if location.end > len(raw):
            raise SourceLocatorError("chunk is outside retained source")
        return raw[location.start : location.end]
    try:
        text = raw.decode("utf-8")
    except UnicodeError as error:
        raise SourceLocatorError(
            "text locators require retained UTF-8 source or extraction"
        ) from error
    if isinstance(location, LineRange):
        lines = text.splitlines(keepends=True)
        if location.end > len(lines):
            raise SourceLocatorError("line range is outside retained source")
        return "".join(lines[location.start - 1 : location.end]).encode("utf-8")
    if isinstance(location, TextPage):
        pages = text.split("\f")
        if location.page > len(pages):
            raise SourceLocatorError("page is outside retained text extraction")
        return pages[location.page - 1].encode("utf-8")
    if isinstance(location, MarkdownSection):
        headings = list(
            re.finditer(
                r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", text, re.MULTILINE
            )
        )
        matches = [h for h in headings if h.group(2).strip() == location.heading]
        if len(matches) < location.occurrence:
            raise SourceLocatorError("section occurrence is absent")
        match = matches[location.occurrence - 1]
        stop = next(
            (
                h.start()
                for h in headings
                if h.start() > match.start() and len(h.group(1)) <= len(match.group(1))
            ),
            len(text),
        )
        return text[match.start() : stop].encode("utf-8")
    raise SourceLocatorError("unsupported locator")


def resolve_source_locator(root: Path, locator: SourceLocator, events) -> None:
    event = next((e for e in events if e.event_id == locator.source_event_id), None)
    if (
        event is None
        or event.event_sha256 != locator.source_event_sha256
        or not isinstance(event.payload, ArtifactAcceptedPayload)
        or event.payload.artifact_id != locator.source_artifact_id
        or event.payload.artifact_sha256 != locator.source_sha256
    ):
        raise SourceLocatorError(
            "locator source is not bound to its canonical acceptance"
        )
    manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
    if (
        manifest.artifact_id != locator.source_artifact_id
        or manifest.content_sha256 != locator.source_sha256
    ):
        raise SourceLocatorError("source manifest does not match locator")
    raw = read_retained_bytes(root, manifest.content_path)
    if sha256_hex(raw) != locator.source_sha256:
        raise SourceLocatorError("retained source digest mismatch")
    if isinstance(locator.location, PdfLocation):
        from arw.pdf_extraction import PdfExtraction

        location = locator.location
        pdf = read_retained_bytes(root, location.pdf_source_path)
        if sha256_hex(pdf) != location.pdf_sha256:
            raise SourceLocatorError("retained PDF digest mismatch")
        manifest_bytes = read_retained_bytes(root, location.extraction_manifest_path)
        if sha256_hex(manifest_bytes) != location.extraction_manifest_sha256:
            raise SourceLocatorError("PDF extraction manifest digest mismatch")
        try:
            extraction = PdfExtraction.model_validate_json(manifest_bytes)
        except ValueError as error:
            raise SourceLocatorError("PDF extraction manifest is invalid") from error
        if (extraction.quality_state != "complete" or
                extraction.source_sha256 != location.pdf_sha256 or
                extraction.extracted_text_sha256 != locator.source_sha256 or
                extraction.extractor_name != location.extractor_name or
                extraction.extractor_version != location.extractor_version):
            raise SourceLocatorError("PDF extraction is not complete or digest bound")
        kind = {"pdf_page": "page", "pdf_paragraph": "paragraph", "pdf_section": "section",
                "pdf_region": "region", "reference_entry": "reference"}[location.kind]
        if not any(item.kind == kind and item.page == location.page and
                   item.start == location.start and item.end == location.end and
                   item.label == location.label and item.bbox == location.bbox
                   for item in extraction.locators):
            raise SourceLocatorError("PDF location is absent from retained extraction")
        if location.kind == "reference_entry" and not any(
            ref.reference_id == location.label for ref in extraction.references
        ):
            raise SourceLocatorError("PDF reference identity is absent")
    if sha256_hex(located_bytes(raw, locator)) != locator.quote_sha256:
        raise SourceLocatorError("located quote digest mismatch")


def validate_precise_provenance(
    root: Path, raw: bytes, events, *, artifact_id: str
) -> None:
    record = decode_provenance(raw)
    if not isinstance(record, PreciseProvenanceRecord):
        return
    if (
        record.artifact_id != artifact_id
        or record.ledger_event_id is not None
        or record.ledger_event_digest is not None
    ):
        raise SourceLocatorError(
            "provenance payload has an invalid artifact identity or future binding"
        )
    if canonical_json_bytes(record.artifact_payload()) != raw:
        raise SourceLocatorError("provenance bytes are not canonical")
    resolve_source_locator(root, record.source_locator, events)
