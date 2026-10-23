"""Bounded scholarly PDF extraction proposals and exact text locators."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from arw.file_models import ExtractionRegistration
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.policy.citations import ReferenceRecord
from arw.kernel.state.models import Sha256, StrictModel

MAX_PDF_BYTES = 8_388_608
MAX_TEXT_BYTES = 8_388_608
MAX_PAGES = 500


class PdfLocator(StrictModel):
    schema_version: Literal["arw.pdf-locator.v1"] = "arw.pdf-locator.v1"
    source_sha256: Sha256
    extracted_text_sha256: Sha256
    extractor_name: Literal["pypdf", "grobid", "docling"]
    extractor_version: str
    kind: Literal["page", "section", "paragraph", "table", "figure", "reference", "region"]
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    label: str | None = None
    bbox: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("PDF locator must contain text")
        if self.kind == "region" and (self.bbox is None or self.extractor_name == "pypdf"):
            raise ValueError("PDF region requires structural coordinates")
        if self.bbox is not None and (not all(math.isfinite(value) for value in self.bbox) or
                                      self.bbox[2] <= self.bbox[0] or self.bbox[3] <= self.bbox[1]):
            raise ValueError("PDF coordinates must be finite and ordered")
        return self


class PdfExtraction(StrictModel):
    schema_version: Literal["arw.pdf-extraction.v1", "arw.pdf-extraction.v2"] = "arw.pdf-extraction.v2"
    source_sha256: Sha256
    extracted_text_sha256: Sha256
    extractor_name: Literal["pypdf", "grobid", "docling"]
    extractor_version: str
    quality_state: Literal["complete", "needs_review", "failed", "malformed"]
    review_reasons: tuple[str, ...]
    page_count: int = Field(ge=0, le=MAX_PAGES)
    locators: tuple[PdfLocator, ...]
    references: tuple[ReferenceRecord, ...] = ()
    configuration_sha256: Sha256 | None = None
    model_manifest_sha256: Sha256 | None = None
    unsupported_structures: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self):
        if self.schema_version == "arw.pdf-extraction.v2" and self.configuration_sha256 is None:
            raise ValueError("v2 PDF extraction requires configuration identity")
        if (self.schema_version == "arw.pdf-extraction.v2" and self.extractor_name == "docling"
                and self.quality_state == "complete" and self.model_manifest_sha256 is None):
            raise ValueError("complete Docling extraction requires model identity")
        if self.quality_state == "complete" and (not self.locators or self.review_reasons):
            raise ValueError("complete extraction needs text and no review reason")
        if self.quality_state != "complete" and not self.review_reasons:
            raise ValueError("degraded extraction needs review reasons")
        for locator in self.locators:
            if locator.source_sha256 != self.source_sha256 or locator.extracted_text_sha256 != self.extracted_text_sha256:
                raise ValueError("locator digest mismatch")
            if locator.extractor_name != self.extractor_name or locator.extractor_version != self.extractor_version:
                raise ValueError("locator extractor identity mismatch")
        return self


class PdfHumanReviewItem(StrictModel):
    schema_version: Literal["arw.pdf-human-review.v1"] = "arw.pdf-human-review.v1"
    source_sha256: Sha256
    extracted_text_sha256: Sha256
    reasons: tuple[str, ...] = Field(min_length=1)
    requested_action: Literal["inspect_pdf_or_supply_reviewed_ocr"] = "inspect_pdf_or_supply_reviewed_ocr"


def pdf_human_review_item(extraction: PdfExtraction) -> PdfHumanReviewItem | None:
    if extraction.quality_state == "complete":
        return None
    return PdfHumanReviewItem(source_sha256=extraction.source_sha256,
                              extracted_text_sha256=extraction.extracted_text_sha256,
                              reasons=extraction.review_reasons)


def verify_pdf_locator(extraction: PdfExtraction, text: bytes, locator: PdfLocator) -> bytes:
    if sha256_hex(text) != extraction.extracted_text_sha256 or locator not in extraction.locators:
        raise ValueError("PDF extraction or locator digest mismatch")
    if locator.end > len(text):
        raise ValueError("PDF locator outside text")
    return text[locator.start:locator.end]


def source_locator_from_pdf(extraction: PdfExtraction, text: bytes, locator: PdfLocator, *,
                            pdf_source_path: str, extraction_manifest_path: str,
                            extraction_manifest_sha256: str, source_artifact_id: str,
                            source_event_id: str, source_event_sha256: str,
                            producing_activity_id: str):
    """Propose a v2 locator; parent acceptance verifies retained artifacts."""
    from arw.kernel.state.provenance import SourceLocator

    quote = verify_pdf_locator(extraction, text, locator)
    kinds = {"page": "pdf_page", "paragraph": "pdf_paragraph", "section": "pdf_section",
             "reference": "reference_entry", "region": "pdf_region"}
    if locator.kind not in kinds:
        raise ValueError("PDF structure has no canonical locator kind")
    return SourceLocator.model_validate({
        "schema_version": "arw.source-locator.v2",
        "source_artifact_id": source_artifact_id, "source_sha256": extraction.extracted_text_sha256,
        "source_event_id": source_event_id, "source_event_sha256": source_event_sha256,
        "producing_activity_id": producing_activity_id,
        "location": {"schema_version": "arw.pdf-location.v1", "kind": kinds[locator.kind],
                     "page": locator.page, "start": locator.start, "end": locator.end,
                     "label": locator.label, "bbox": locator.bbox,
                     "pdf_source_path": pdf_source_path, "pdf_sha256": extraction.source_sha256,
                     "extraction_manifest_path": extraction_manifest_path,
                     "extraction_manifest_sha256": extraction_manifest_sha256,
                     "extractor_name": extraction.extractor_name,
                     "extractor_version": extraction.extractor_version},
        "quote_sha256": sha256_hex(quote),
    })


def _build(raw: bytes, pages: list[str], *, name: Literal["pypdf", "grobid", "docling"], version: str,
           warnings: tuple[str, ...] = (), structural: list[tuple[int, str, str | None, str, tuple[float, float, float, float] | None]] | None = None,
           references: tuple[ReferenceRecord, ...] = (), configuration: dict | None = None,
           model_manifest_sha256: str | None = None,
           unsupported_structures: tuple[str, ...] = ()) -> tuple[PdfExtraction, bytes]:
    if len(pages) > MAX_PAGES:
        raise ValueError("PDF page limit exceeded")
    encoded = [page.encode("utf-8") for page in pages]
    text = b"\f".join(encoded)
    if len(text) > MAX_TEXT_BYTES:
        raise ValueError("PDF extraction output limit exceeded")
    source_digest, text_digest = sha256_hex(raw), sha256_hex(text)
    locators: list[PdfLocator] = []
    offset = 0
    for number, page in enumerate(encoded, 1):
        if page.strip():
            locators.append(PdfLocator(source_sha256=source_digest, extracted_text_sha256=text_digest,
                                       extractor_name=name, extractor_version=version,
                                       kind="page", page=number, start=offset, end=offset + len(page)))
            # Paragraph boundaries are byte offsets in retained UTF-8, not character offsets.
            for match in re.finditer(rb"[^\r\n\f]+(?:[\r\n](?![\r\n])[^\r\n\f]+)*", page):
                if match.group().strip():
                    locators.append(PdfLocator(source_sha256=source_digest, extracted_text_sha256=text_digest,
                                               extractor_name=name, extractor_version=version,
                                               kind="paragraph", page=number,
                                               start=offset + match.start(), end=offset + match.end()))
        offset += len(page) + (number < len(encoded))
    if structural:
        page_offsets = []
        cursor = 0
        for page in encoded:
            page_offsets.append(cursor)
            cursor += len(page) + 1
        search_offsets: dict[int, int] = {}
        for page_number, kind, label, fragment, bbox in structural:
            if not 1 <= page_number <= len(encoded):
                raise ValueError("structured PDF page is outside extraction")
            needle = fragment.encode("utf-8")
            start = encoded[page_number - 1].find(needle, search_offsets.get(page_number, 0))
            if start < 0:
                raise ValueError("structured PDF text is absent from retained page")
            search_offsets[page_number] = start + len(needle)
            locators.append(PdfLocator(source_sha256=source_digest, extracted_text_sha256=text_digest,
                                       extractor_name=name, extractor_version=version,
                                       kind=kind, page=page_number, start=page_offsets[page_number - 1] + start,
                                       end=page_offsets[page_number - 1] + start + len(needle), label=label))
            if bbox is not None:
                locators.append(PdfLocator(source_sha256=source_digest, extracted_text_sha256=text_digest,
                                           extractor_name=name, extractor_version=version,
                                           kind="region", page=page_number, start=page_offsets[page_number - 1] + start,
                                           end=page_offsets[page_number - 1] + start + len(needle), label=label,
                                           bbox=bbox))
    reasons = list(warnings)
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-z0-9.-]+)?", version) and name != "pypdf":
        reasons.append("extractor_version_unknown")
    if not locators:
        reasons.append("no_extractable_text")
    elif sum(len(page.strip()) for page in encoded) < 40:
        reasons.append("low_text_coverage")
    quality = ("malformed" if "malformed_pdf" in reasons else "failed" if "extraction_failed" in reasons
               else "needs_review" if reasons else "complete")
    return PdfExtraction(source_sha256=source_digest, extracted_text_sha256=text_digest,
                         extractor_name=name, extractor_version=version,
                         quality_state=quality,
                         review_reasons=tuple(dict.fromkeys(reasons)), page_count=len(pages),
                         locators=tuple(locators), references=references,
                         configuration_sha256=sha256_hex(canonical_json_bytes({
                             "provider": name, "adapter": "arw.pdf.v2",
                             "max_pdf_bytes": MAX_PDF_BYTES, "max_text_bytes": MAX_TEXT_BYTES,
                             "max_pages": MAX_PAGES, "options": configuration or {}})),
                         model_manifest_sha256=model_manifest_sha256,
                         unsupported_structures=unsupported_structures), text


def extract_pdf_bytes(raw: bytes) -> tuple[PdfExtraction, bytes]:
    """Default offline extraction. The caller supplies bounded, allowed-root bytes."""
    if len(raw) > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds source limit")
    if not raw.startswith(b"%PDF-"):
        return _build(raw, [], name="pypdf", version="unknown", warnings=("malformed_pdf",))
    try:
        import pypdf
    except ImportError as error:
        raise RuntimeError("pypdf extra is required for PDF extraction") from error
    try:
        reader = pypdf.PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            return _build(raw, [], name="pypdf", version=pypdf.__version__, warnings=("encrypted_pdf",))
        if len(reader.pages) > MAX_PAGES:
            raise ValueError("PDF page limit exceeded")
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception:  # noqa: BLE001 - pypdf raises several unrelated parser errors.
        return _build(raw, [], name="pypdf", version=pypdf.__version__, warnings=("extraction_failed",))
    return _build(raw, pages, name="pypdf", version=pypdf.__version__)


def extract_grobid_tei(raw_pdf: bytes, tei: bytes, *, version: str) -> tuple[PdfExtraction, bytes]:
    """Parse fixture or explicitly obtained loopback GROBID TEI without fetching."""
    if len(raw_pdf) > MAX_PDF_BYTES or len(tei) > MAX_TEXT_BYTES or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", tei, re.IGNORECASE):
        raise ValueError("unsafe PDF or TEI input")
    root = ET.fromstring(tei)
    pages: dict[int, list[str]] = {}
    structural: list[tuple[int, str, str | None, str, tuple[float, float, float, float] | None]] = []
    references: list[ReferenceRecord] = []
    parent = {child: node for node in root.iter() for child in node}
    current_page = 1
    page_mapping_seen = False
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "pb":
            marker = node.attrib.get("n", "")
            if marker.isdigit() and int(marker) >= 1:
                current_page = int(marker)
                page_mapping_seen = True
            continue
        if tag not in {"p", "head", "figure", "table", "biblStruct"}:
            continue
        if tag == "p" and parent.get(node) is not None and parent[node].tag.rsplit("}", 1)[-1] in {"figure", "table"}:
            continue
        marker = next((x.attrib.get("n") for x in node.iter() if x.tag.rsplit("}", 1)[-1] == "pb"), None)
        if marker is not None and marker.isdigit() and int(marker) >= 1:
            current_page = int(marker)
            page_mapping_seen = True
        text = " ".join(" ".join(node.itertext()).split())
        if not text:
            continue
        pages.setdefault(current_page, []).append(text)
        kind = {"p": "paragraph", "head": "section", "figure": "figure", "table": "table", "biblStruct": "reference"}[tag]
        label = node.attrib.get("n") or node.attrib.get("{http://www.w3.org/XML/1998/namespace}id")
        if tag == "biblStruct":
            title = next((" ".join(" ".join(child.itertext()).split()) for child in node.iter() if child.tag.rsplit("}", 1)[-1] == "title"), "")
            authors = tuple(" ".join(" ".join(child.itertext()).split()) for child in node.iter() if child.tag.rsplit("}", 1)[-1] == "author")
            date = next((child.attrib.get("when", "") for child in node.iter() if child.tag.rsplit("}", 1)[-1] == "date"), "")
            doi = next(("".join(child.itertext()).strip() for child in node.iter() if child.tag.rsplit("}", 1)[-1] == "idno" and child.attrib.get("type", "").casefold() == "doi"), None)
            if title and authors and date[:4].isdigit():
                identity = sha256_hex(canonical_json_bytes({"title": title, "authors": authors, "year": date[:4], "doi": doi}))[:24]
                reference = ReferenceRecord(reference_id=f"pdfref.{identity}", citation_key=label or f"pdfref{identity}",
                                            title=title, authors=authors, year=int(date[:4]), doi=doi)
                references.append(reference)
                label = reference.reference_id
        bbox = None
        coords = node.attrib.get("coords", "")
        match = re.fullmatch(r"(\d+),([0-9]+(?:\.[0-9]+)?),([0-9]+(?:\.[0-9]+)?),([0-9]+(?:\.[0-9]+)?),([0-9]+(?:\.[0-9]+)?)", coords)
        if match and int(match.group(1)) == current_page:
            x, y, width, height = map(float, match.groups()[1:])
            if all(math.isfinite(value) for value in (x, y, width, height, x + width, y + height)) and width > 0 and height > 0:
                bbox = (x, y, x + width, y + height)
        structural.append((current_page, kind, label, text, bbox))
    if not pages:
        return _build(raw_pdf, [], name="grobid", version=version)
    if max(pages) > MAX_PAGES:
        raise ValueError("TEI page limit exceeded")
    return _build(raw_pdf, ["\n\n".join(pages.get(n, [])) for n in range(1, max(pages) + 1)],
                  name="grobid", version=version,
                  warnings=() if page_mapping_seen else ("page_mapping_unknown",), structural=structural,
                  references=tuple(references))


def extract_grobid(raw_pdf: bytes, *, endpoint: str, allow_local_service: bool = False) -> tuple[PdfExtraction, bytes]:
    if not allow_local_service:
        raise PermissionError("GROBID requires explicit local service opt-in")
    from urllib.parse import urlsplit, urlunsplit
    from urllib.request import Request
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.path != "/api/processFulltextDocument"
            or parsed.query or parsed.fragment or parsed.port is None):
        raise ValueError("GROBID endpoint must be loopback HTTP")
    if len(raw_pdf) > MAX_PDF_BYTES:
        raise ValueError("PDF source limit exceeded")
    boundary = "arw-grobid-pdf-boundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"input\"; filename=\"source.pdf\"\r\nContent-Type: application/pdf\r\n\r\n".encode()
            + raw_pdf + f"\r\n--{boundary}--\r\n".encode())
    # Never resolve localhost through host DNS or send this request through an
    # environment proxy. Pin it to a literal loopback address before opening.
    host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
    authority = f"[{host}]:{parsed.port}" if host == "::1" else f"{host}:{parsed.port}"
    pinned_endpoint = urlunsplit(("http", authority, parsed.path, "", ""))
    request = Request(pinned_endpoint, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            raise ValueError("GROBID redirect forbidden")
    try:
        with build_opener(ProxyHandler({}), NoRedirect).open(request, timeout=15) as response:
            if response.geturl() != pinned_endpoint:
                raise ValueError("GROBID redirect left loopback")
            tei = response.read(MAX_TEXT_BYTES + 1)
            version = response.headers.get("X-GROBID-Version", "service-unknown")
    except OSError:
        return _build(raw_pdf, [], name="grobid", version="service-unknown", warnings=("service_unavailable",),
                      configuration={"endpoint": endpoint, "timeout_seconds": 15, "allow_local_service": True})
    extraction, text = extract_grobid_tei(raw_pdf, tei, version=version)
    extraction = extraction.model_copy(update={"configuration_sha256": sha256_hex(canonical_json_bytes({
        "tei_configuration_sha256": extraction.configuration_sha256, "endpoint": endpoint,
        "timeout_seconds": 15, "allow_local_service": True}))})
    return extraction, text


def extract_docling(raw_pdf: bytes, *, converter: object | None = None, version: str = "unknown") -> tuple[PdfExtraction, bytes]:
    """Only a caller-supplied, preinitialized local converter is accepted."""
    if converter is None:
        raise RuntimeError("Docling requires an explicitly supplied offline converter and installed assets")
    if getattr(converter, "offline_assets_verified", False) is not True:
        raise RuntimeError("Docling converter must attest preinstalled offline assets")
    if len(raw_pdf) > MAX_PDF_BYTES:
        raise ValueError("PDF source limit exceeded")
    # No library import or model construction here: those could download assets.
    pages = converter.extract_pages(raw_pdf)
    if not isinstance(pages, list) or not all(isinstance(p, str) for p in pages):
        raise ValueError("Docling converter returned invalid pages")
    return _build(raw_pdf, pages, name="docling", version=version,
                  warnings=("docling_model_identity_unverified",),
                  unsupported_structures=("model_identity", "structured_items"))


ASSET_MANIFEST = "arw-docling-assets.json"
MAX_ASSET_BYTES = 8 * 1024**3
MAX_ASSET_FILES = 512


def verify_docling_assets(artifacts_path: Path) -> str:
    """Verify a caller-supplied inventory, not a license or model-quality attestation."""
    if artifacts_path.is_symlink() or not artifacts_path.is_dir() or not any(artifacts_path.iterdir()):
        raise ValueError("Docling needs a nonempty local model artifacts directory")
    from arw.kernel.core.canonical import strict_json_loads
    raw = read_retained_bytes(artifacts_path, ASSET_MANIFEST, max_bytes=262_144)
    manifest = strict_json_loads(raw)
    if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "files"}
            or manifest["schema_version"] != "arw.docling-assets.v1"
            or not isinstance(manifest["files"], list)
            or not 1 <= len(manifest["files"]) <= MAX_ASSET_FILES):
        raise ValueError("invalid Docling asset manifest")
    expected = set()
    total = 0
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size_bytes"}:
            raise ValueError("invalid Docling asset entry")
        relative = entry["path"]
        if (not isinstance(relative, str) or not relative or relative.startswith("/")
                or any(part in {"", ".", ".."} for part in relative.split("/"))
                or relative == ASSET_MANIFEST or relative in expected):
            raise ValueError("unsafe Docling asset path")
        expected.add(relative)
        size = entry["size_bytes"]
        if (type(size) is not int or size < 1 or size > MAX_ASSET_BYTES
                or not isinstance(entry["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            raise ValueError("invalid Docling asset digest or size")
        total += size
        if total > MAX_ASSET_BYTES:
            raise ValueError("Docling asset byte limit exceeded")
        # Match retained-source reads: open every component relative to a held root,
        # reject links/FIFOs, and stream weights instead of retaining gigabytes.
        if os.open not in os.supports_dir_fd or not getattr(os, "O_NOFOLLOW", 0):
            raise ValueError("safe Docling asset verification unsupported")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        directory = os.open(artifacts_path, flags | os.O_DIRECTORY)
        content = None
        digest = hashlib.sha256()
        try:
            parts = relative.split("/")
            for part in parts[:-1]:
                child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
                os.close(directory)
                directory = child
            content = os.open(parts[-1], flags, dir_fd=directory)
            before = os.fstat(content)
            if not stat.S_ISREG(before.st_mode) or before.st_size != size:
                raise ValueError("Docling asset size or file type mismatch")
            remaining = size
            while remaining:
                chunk = os.read(content, min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("Docling asset changed during verification")
                digest.update(chunk)
                remaining -= len(chunk)
            after = os.fstat(content)
            if (os.read(content, 1) or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns):
                raise ValueError("Docling asset changed during verification")
        except OSError as error:
            raise ValueError("Docling asset unavailable or unsafe") from error
        finally:
            if content is not None:
                os.close(content)
            os.close(directory)
        if digest.hexdigest() != entry["sha256"]:
            raise ValueError("Docling asset digest mismatch")
    # Reject hidden unlisted assets and symlink directories; never walk arbitrary roots.
    actual = set()
    count = 0
    for directory, dirs, files in os.walk(artifacts_path, followlinks=False):
        count += len(dirs) + len(files)
        if count > 2 * MAX_ASSET_FILES:
            raise ValueError("Docling asset inventory limit exceeded")
        for name in dirs + files:
            if (Path(directory) / name).is_symlink():
                raise ValueError("symlink Docling asset is forbidden")
        actual.update((Path(directory) / name).relative_to(artifacts_path).as_posix() for name in files)
    if actual != expected | {ASSET_MANIFEST}:
        raise ValueError("Docling asset inventory mismatch")
    return sha256_hex(canonical_json_bytes(manifest))


def _docling_structure(document):
    """Retain item text/cells and physical provenance; never parse Markdown or bibliography prose."""
    numbers = sorted(document.pages)
    if len(numbers) > MAX_PAGES or numbers != list(range(1, len(numbers) + 1)):
        raise ValueError("Docling returned nonconsecutive PDF page numbers")
    pages = [[] for _ in numbers]
    structural, unsupported, warnings = [], set(), set()
    size = 0
    count = 0
    headings = []
    if not callable(getattr(document, "iterate_items", None)):
        raise TypeError("unsupported Docling structure API")
    for item, _ in document.iterate_items():
        count += 1
        if count > 20_000:
            raise ValueError("Docling item limit exceeded")
        label = getattr(item.label, "value", item.label)
        kind = {"section_header": "section", "title": "section", "reference": "reference",
                "table": "table"}.get(label, "paragraph")
        text = getattr(item, "text", "")
        if label == "table":
            cells = item.data.table_cells
            if len(cells) > 20_000:
                raise ValueError("Docling table cell limit exceeded")
            text = "\t".join(cell.text for cell in cells)
            unsupported.add("table_cell_locators")
        if not isinstance(text, str):
            raise TypeError("invalid Docling item text")
        if not text.strip():
            continue
        provenance = item.prov
        # Multi-page items require charspan partitioning; do not assign all text to the first page.
        if len(provenance) != 1:
            warnings.add("docling_item_page_mapping_unknown")
            continue
        prov = provenance[0]
        if type(prov.page_no) is not int or prov.page_no not in document.pages:
            raise ValueError("Docling item page is outside extraction")
        page = document.pages[prov.page_no]
        bbox = None
        box, dimensions = prov.bbox, page.size
        if box is not None and dimensions is not None:
            width, height = dimensions.width, dimensions.height
            origin = getattr(box.coord_origin, "value", box.coord_origin)
            if origin == "BOTTOMLEFT":
                coords = (box.l, height - box.t, box.r, height - box.b)
            elif origin == "TOPLEFT":
                coords = (box.l, box.t, box.r, box.b)
            else:
                coords = None
            if coords is not None and width > 0 and height > 0:
                bbox = (coords[0] / width, coords[1] / height, coords[2] / width, coords[3] / height)
                if not (all(math.isfinite(x) and 0 <= x <= 1 for x in bbox)
                        and bbox[0] < bbox[2] and bbox[1] < bbox[3]):
                    raise ValueError("invalid Docling bbox")
        if bbox is None:
            unsupported.add("bbox")
        if kind != "table" and getattr(prov, "charspan", (0, len(text))) != (0, len(text)):
            warnings.add("docling_item_charspan_mapping_unknown")
            continue
        identity = item.self_ref
        if kind == "section":
            level = getattr(item, "level", 1)
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, text))
            identity = " / ".join(part for _, part in headings)
        elif kind == "reference":
            unsupported.add("reference_metadata")
        elif label == "caption":
            # A caption can belong to a table or picture. Only explicit picture parents qualify.
            parent = getattr(item, "parent", None)
            parent_label = getattr(parent.resolve(document), "label", None) if parent else None
            if getattr(parent_label, "value", parent_label) == "picture":
                kind = "figure"
            else:
                unsupported.add("figure_caption_identity")
        size += len(text.encode("utf-8")) + 2
        if size > MAX_TEXT_BYTES:
            raise ValueError("PDF extraction output limit exceeded")
        pages[prov.page_no - 1].append(text)
        structural.append((prov.page_no, kind, identity, text, bbox))
    return ["\n\n".join(page) for page in pages], structural, tuple(sorted(unsupported)), tuple(sorted(warnings))


def extract_docling_local(raw_pdf: bytes, *, artifacts_path: Path) -> tuple[PdfExtraction, bytes]:
    """Use only digest-verified local Docling assets; never initialize its defaults."""
    import importlib.metadata

    if len(raw_pdf) > MAX_PDF_BYTES:
        raise ValueError("PDF source limit exceeded")
    model_digest = verify_docling_assets(artifacts_path)
    try:
        from docling.datamodel.base_models import DocumentStream, InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import (
            ConversionStatus,
            DocumentConverter,
            PdfFormatOption,
        )
    except ImportError as error:
        raise RuntimeError("optional Docling package is unavailable") from error
    options = PdfPipelineOptions(artifacts_path=artifacts_path.resolve(strict=True),
                                 enable_remote_services=False, allow_external_plugins=False,
                                 do_ocr=False)
    configuration = options.model_dump(mode="json")
    converter = DocumentConverter(allowed_formats=[InputFormat.PDF],
                                  format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    source = DocumentStream(name="source.pdf", stream=io.BytesIO(raw_pdf))
    result = converter.convert(source, max_num_pages=MAX_PAGES, max_file_size=MAX_PDF_BYTES)
    pages, structural, unsupported, warnings = _docling_structure(result.document)
    if verify_docling_assets(artifacts_path) != model_digest:
        raise ValueError("Docling asset manifest changed during conversion")
    return _build(raw_pdf, pages, name="docling", version=importlib.metadata.version("docling"),
                  warnings=warnings + (() if result.status == ConversionStatus.SUCCESS else ("docling_partial_or_failed",)),
                  structural=structural, configuration=configuration,
                  model_manifest_sha256=model_digest, unsupported_structures=unsupported)


def extract_pdf_from_root(root: Path, relative_path: str) -> tuple[PdfExtraction, bytes]:
    return extract_pdf_bytes(read_retained_bytes(root, relative_path, max_bytes=MAX_PDF_BYTES))


def register_pdf_extraction(service, root_id: str, source_file_id: str, relative_path: str, extraction: PdfExtraction, text: bytes, *, registration_id: str, extracted_at: str) -> ExtractionRegistration:
    """Parent-operated bridge to the existing immutable files registration."""
    root = service.load_root(root_id)
    source = read_retained_bytes(Path(root.canonical_path), relative_path, max_bytes=MAX_PDF_BYTES)
    if sha256_hex(source) != extraction.source_sha256 or sha256_hex(text) != extraction.extracted_text_sha256:
        raise ValueError("PDF or extraction digest mismatch")
    if extraction.quality_state != "complete":
        raise ValueError("PDF extraction needs human review before registration")
    import tempfile
    registration = ExtractionRegistration(schema_version="1.0.0", registration_id=registration_id,
                                          source_file_id=source_file_id, source_digest=extraction.source_sha256,
                                          extracted_text_digest=extraction.extracted_text_sha256,
                                          extractor_name=extraction.extractor_name,
                                          extractor_version=extraction.extractor_version,
                                          extracted_at=extracted_at, quality_state="complete", access_state="accessible")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "text.txt"
        path.write_bytes(text)
        service.register_extraction(root_id, registration, path)
    return registration


PDF_WORKER_LIMITS = {"address_space_bytes": 4 * 1024**3, "cpu_seconds": 30,
                     "file_bytes": 32 * 1024**2, "open_files": 64}
PDF_WORKER_TIMEOUT = 45


class PdfWorkerError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def extract_pdf_isolated(raw_pdf: bytes, *, provider: str = "pypdf",
                         artifacts_path: Path | None = None, endpoint: str | None = None,
                         allow_local_service: bool = False,
                         timeout_seconds: float = PDF_WORKER_TIMEOUT) -> tuple[PdfExtraction, bytes]:
    """Bytes-only parser child; the sole optional filesystem input is the explicit model root."""
    import base64
    import os
    import signal
    import subprocess
    import sys
    import tempfile

    if len(raw_pdf) > MAX_PDF_BYTES:
        raise ValueError("PDF source limit exceeded")
    if provider not in {"pypdf", "docling", "grobid"}:
        raise ValueError("unsupported PDF provider")
    if os.name != "posix":
        raise PdfWorkerError("pdf_resource_limits_unsupported")
    if not 0 < timeout_seconds <= PDF_WORKER_TIMEOUT:
        raise ValueError("PDF worker timeout outside allowed limit")
    if artifacts_path is not None and any(path.is_symlink() for path in (artifacts_path, *artifacts_path.parents)):
        raise ValueError("symlink Docling asset root is forbidden")
    try:
        model_root = str(artifacts_path.resolve(strict=True)) if artifacts_path else None
    except OSError as error:
        raise ValueError("Docling asset root is unavailable") from error
    request = {"content": base64.b64encode(raw_pdf).decode("ascii"), "provider": provider,
               "timeout_seconds": timeout_seconds,
               "artifacts_path": model_root,
               "endpoint": endpoint, "allow_local_service": allow_local_service}
    # Model/network libraries see offline flags before import; no credentials are read or forwarded.
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "SYSTEMROOT")
           if key in os.environ}
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    paths = [str(Path(__file__).resolve().parents[1])]
    paths.extend(str(Path(part).resolve()) for part in os.environ.get("PYTHONPATH", "").split(os.pathsep) if part)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    with tempfile.TemporaryDirectory(prefix="arw-pdf-") as directory:
        env.update(HOME=directory, TMPDIR=directory, HF_HOME=directory)
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            child = subprocess.Popen([sys.executable, "-m", "arw.pdf_extraction"],
                                     stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                     env=env, cwd=directory, start_new_session=True)
            try:
                child.communicate(canonical_json_bytes(request), timeout=timeout_seconds)
            except subprocess.TimeoutExpired as error:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
                raise PdfWorkerError("pdf_worker_timeout") from error
            finally:
                # The worker has no legitimate descendants after conversion.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if child.returncode:
                raise PdfWorkerError("pdf_worker_resource_limit_or_failure")
            stdout.seek(0)
            response = stdout.read(PDF_WORKER_LIMITS["file_bytes"] + 1)
            if len(response) > PDF_WORKER_LIMITS["file_bytes"]:
                raise PdfWorkerError("pdf_worker_output_limit")
    from arw.kernel.core.canonical import strict_json_loads
    try:
        result = strict_json_loads(response)
        if result["status"] != "ok":
            raise PdfWorkerError(result["reason"])
        if result["limits"] != PDF_WORKER_LIMITS:
            raise ValueError("PDF worker limits differ")
        extraction = PdfExtraction.model_validate_json(json.dumps(result["extraction"]))
        text = base64.b64decode(result["text"], validate=True)
        if (len(text) > MAX_TEXT_BYTES or extraction.source_sha256 != sha256_hex(raw_pdf)
                or extraction.extracted_text_sha256 != sha256_hex(text)
                or extraction.extractor_name != provider):
            raise ValueError("PDF worker identity mismatch")
        # Membership and digest checks are already established by the enclosing model.
        # Avoid quadratic locator membership scans on large structured output.
        if any(locator.end > len(text) for locator in extraction.locators):
            raise ValueError("PDF worker locator outside text")
        return extraction, text
    except (ValueError, KeyError, TypeError) as error:
        raise PdfWorkerError("pdf_worker_invalid_response") from error


def _pdf_worker_main():
    import base64
    import contextlib
    import sys

    wire = sys.stdout
    try:
        import resource
        for name, key in (("RLIMIT_AS", "address_space_bytes"), ("RLIMIT_CPU", "cpu_seconds"),
                          ("RLIMIT_FSIZE", "file_bytes"), ("RLIMIT_NOFILE", "open_files")):
            limit = PDF_WORKER_LIMITS[key]
            resource.setrlimit(getattr(resource, name), (limit, limit))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        import signal

        signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
    except (ImportError, AttributeError, OSError, ValueError):
        wire.write(json.dumps({"status": "unsupported", "reason": "pdf_resource_limits_unsupported"}))
        return
    try:
        from arw.kernel.core.canonical import strict_json_loads
        raw = sys.stdin.buffer.read(2 * MAX_PDF_BYTES + 1)
        if len(raw) > 2 * MAX_PDF_BYTES:
            raise ValueError("oversized PDF request")
        request = strict_json_loads(raw)
        content = base64.b64decode(request["content"], validate=True)
        if len(content) > MAX_PDF_BYTES:
            raise ValueError("oversized PDF source")
        provider = request["provider"]
        if provider != "grobid":
            def offline(event, args):
                if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
                    raise PermissionError("PDF worker network is disabled")
            sys.addaudithook(offline)
        # Provider logging must not corrupt the bounded machine protocol.
        with contextlib.redirect_stdout(sys.stderr):
            if provider == "pypdf":
                extraction, text = extract_pdf_bytes(content)
            elif provider == "docling":
                extraction, text = extract_docling_local(content, artifacts_path=Path(request["artifacts_path"]))
            elif provider == "grobid":
                extraction, text = extract_grobid(content, endpoint=request["endpoint"],
                                                 allow_local_service=request["allow_local_service"])
            else:
                raise ValueError("unsupported provider")
        extraction = extraction.model_copy(update={"configuration_sha256": sha256_hex(canonical_json_bytes({
            "adapter_configuration_sha256": extraction.configuration_sha256,
            "limits": PDF_WORKER_LIMITS, "wall_seconds": request["timeout_seconds"],
            "offline": provider != "grobid"}))})
        result = {"status": "ok", "limits": PDF_WORKER_LIMITS,
                  "extraction": extraction.model_dump(mode="json"),
                  "text": base64.b64encode(text).decode("ascii")}
    except (ImportError, RuntimeError):
        result = {"status": "unsupported", "reason": "pdf_provider_unavailable"}
    except Exception:  # noqa: BLE001 -- never expose parser internals or input bytes.
        result = {"status": "failed", "reason": "pdf_provider_input_or_conversion_failed"}
    payload = canonical_json_bytes(result)
    if len(payload) > PDF_WORKER_LIMITS["file_bytes"]:
        payload = b'{"status":"failed","reason":"pdf_worker_output_limit"}'
    wire.buffer.write(payload)


if __name__ == "__main__":
    _pdf_worker_main()
