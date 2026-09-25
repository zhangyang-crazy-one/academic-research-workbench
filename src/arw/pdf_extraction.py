"""Bounded scholarly PDF extraction proposals and exact text locators."""

from __future__ import annotations

import io
import math
import re
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
    schema_version: Literal["arw.pdf-extraction.v1"] = "arw.pdf-extraction.v1"
    source_sha256: Sha256
    extracted_text_sha256: Sha256
    extractor_name: Literal["pypdf", "grobid", "docling"]
    extractor_version: str
    quality_state: Literal["complete", "needs_review", "failed", "malformed"]
    review_reasons: tuple[str, ...]
    page_count: int = Field(ge=0, le=MAX_PAGES)
    locators: tuple[PdfLocator, ...]
    references: tuple[ReferenceRecord, ...] = ()

    @model_validator(mode="after")
    def coherent(self):
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
           references: tuple[ReferenceRecord, ...] = ()) -> tuple[PdfExtraction, bytes]:
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
                         locators=tuple(locators), references=references), text


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
        return _build(raw_pdf, [], name="grobid", version="service-unknown", warnings=("service_unavailable",))
    return extract_grobid_tei(raw_pdf, tei, version=version)


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
    return _build(raw_pdf, pages, name="docling", version=version)


def extract_docling_local(raw_pdf: bytes, *, artifacts_path: Path) -> tuple[PdfExtraction, bytes]:
    """Use only preinstalled local Docling models; never initialize its defaults."""
    import importlib.metadata

    if artifacts_path.is_symlink() or not artifacts_path.is_dir() or not any(artifacts_path.iterdir()):
        raise ValueError("Docling needs a nonempty local model artifacts directory")
    if len(raw_pdf) > MAX_PDF_BYTES:
        raise ValueError("PDF source limit exceeded")
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
    converter = DocumentConverter(allowed_formats=[InputFormat.PDF],
                                  format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    source = DocumentStream(name="source.pdf", stream=io.BytesIO(raw_pdf))
    result = converter.convert(source, max_num_pages=MAX_PAGES, max_file_size=MAX_PDF_BYTES)
    page_numbers = sorted(result.document.pages)
    if len(page_numbers) > MAX_PAGES or page_numbers != list(range(1, len(page_numbers) + 1)):
        raise ValueError("Docling returned nonconsecutive PDF page numbers")
    pages = [result.document.export_to_markdown(page_no=number) for number in page_numbers]
    return _build(raw_pdf, pages, name="docling", version=importlib.metadata.version("docling"),
                  warnings=() if result.status == ConversionStatus.SUCCESS else ("docling_partial_or_failed",))


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
