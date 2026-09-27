"""Deterministic bibliographic checks. Receipts are observations, not admission."""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.ledger.manifests import _safe_directory, _write_once
from arw.kernel.state.models import Sha256, StrictModel, UtcTimestamp

Provider = Literal["crossref", "openalex", "dblp", "arxiv"]
CheckStatus = Literal[
    "verified", "not_found", "retracted", "unknown", "unavailable", "ambiguous"
]
UseRole = Literal["supporting", "background", "research_object"]
MAX_RESPONSE_BYTES = 1_048_576
PARSER_VERSION = "1.0.0"


class ReferenceRecord(StrictModel):
    schema_version: Literal["arw.reference.v1"] = "arw.reference.v1"
    reference_id: Annotated[str, StringConstraints(min_length=3, max_length=128)]
    citation_key: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    title: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    authors: tuple[str, ...] = Field(min_length=1, max_length=100)
    year: int = Field(ge=1000, le=2100)
    doi: str | None = None
    arxiv_id: str | None = None
    source_manifest_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def identifiers(self):
        if any(not author.strip() for author in self.authors):
            raise ValueError("reference authors must be nonempty")
        if self.doi is not None and not re.fullmatch(
            r"10\.\d{4,9}/\S+", self.doi, re.IGNORECASE
        ):
            raise ValueError("invalid DOI")
        if self.arxiv_id is not None and not re.fullmatch(
            r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?", self.arxiv_id, re.IGNORECASE
        ):
            raise ValueError("invalid arXiv ID")
        return self


class ReferenceUse(StrictModel):
    schema_version: Literal["arw.reference-use.v1"] = "arw.reference-use.v1"
    use_id: str
    reference_id: str
    claim_id: str
    role: UseRole


def reference_from_source_manifest(source) -> ReferenceRecord:
    """Bind the shared reference identity to an existing ARS research source."""
    from arw.kernel.policy.research_integrity import (
        ResearchSourceManifest,
        research_integrity_sha256,
    )

    if not isinstance(source, ResearchSourceManifest):
        raise TypeError("reference source must be a ResearchSourceManifest")
    authors = tuple(
        str(
            getattr(author, "literal", None)
            or " ".join(
                part
                for part in (
                    getattr(author, "given", None),
                    getattr(author, "family", None),
                )
                if part
            )
        )
        for author in source.authors
    )
    return ReferenceRecord(
        reference_id=source.source_id,
        citation_key=source.citation_key,
        title=source.title,
        authors=authors,
        year=source.year,
        doi=source.doi,
        arxiv_id=source.arxiv_id,
        source_manifest_sha256=research_integrity_sha256(source),
    )


class CheckReceipt(StrictModel):
    schema_version: Literal["arw.citation-check.v1"] = "arw.citation-check.v1"
    reference_sha256: Sha256
    check_id: str
    batch_id: str | None = None
    provider: Provider
    query: str
    response_sha256: Sha256
    http_status: int | None = Field(default=None, ge=100, le=599)
    parser_version: Literal["1.0.0"] = "1.0.0"
    observed_at: UtcTimestamp
    status: CheckStatus
    matched_id: str | None = None
    retraction_evidence: str | None = None
    error_code: str | None = None
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def digest_and_status(self):
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,127}", self.check_id):
            raise ValueError("invalid citation check ID")
        body = self.model_dump(
            mode="json", exclude={"receipt_sha256"}, exclude_none=False
        )
        if self.batch_id is None:
            body.pop("batch_id")  # Legacy v1 receipts retain their original digest.
        elif not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,127}", self.batch_id):
            raise ValueError("invalid citation batch ID")
        if sha256_hex(canonical_json_bytes(body)) != self.receipt_sha256:
            raise ValueError("citation check receipt digest mismatch")
        if self.status in {"verified", "retracted"} and not self.matched_id:
            raise ValueError("matched checks require identity")
        if self.status == "retracted" and not self.retraction_evidence:
            raise ValueError("retraction requires evidence")
        if self.status == "unavailable" and not self.error_code:
            raise ValueError("unavailable requires a transport error code")
        return self


def _normalize(value: str) -> str:
    return re.sub(r"\W+", "", value.casefold(), flags=re.UNICODE)


def _doi(value: str) -> str:
    value = urllib.parse.unquote(value).casefold().strip()
    return value.removeprefix("https://doi.org/").removeprefix("http://doi.org/")


def _query(reference: ReferenceRecord, provider: Provider) -> str:
    if provider == "arxiv" and reference.arxiv_id:
        return reference.arxiv_id
    if reference.doi and provider in {"crossref", "openalex"}:
        return _doi(reference.doi)
    return reference.title


def _candidates(provider: Provider, raw: bytes) -> list[dict[str, object]]:
    if provider == "arxiv":
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("XML entity declarations forbidden")
        root = ET.fromstring(raw)
        if root.tag != "{http://www.w3.org/2005/Atom}feed":
            raise ValueError("arXiv Atom feed missing")
        ns = {"a": "http://www.w3.org/2005/Atom"}
        result = []
        for entry in root.findall("a:entry", ns):
            result.append(
                {
                    "id": (entry.findtext("a:id", default="", namespaces=ns)).rsplit(
                        "/", 1
                    )[-1],
                    "title": entry.findtext("a:title", default="", namespaces=ns),
                    "year": (entry.findtext("a:published", default="", namespaces=ns))[
                        :4
                    ],
                    "authors": [
                        a.findtext("a:name", default="", namespaces=ns)
                        for a in entry.findall("a:author", ns)
                    ],
                    "retracted": "this paper has been withdrawn"
                    in entry.findtext(
                        "{http://arxiv.org/schemas/atom}comment", default=""
                    ).casefold(),
                }
            )
        return result
    value = strict_json_loads(raw)
    if not isinstance(value, dict):
        raise TypeError("provider response must be object")
    if provider == "crossref":
        message = value.get("message")
        if not isinstance(message, dict):
            raise ValueError("Crossref message missing")
        if "items" not in message and "DOI" not in message:
            raise ValueError("Crossref work or items missing")
        items = message.get("items", [message])
        if not isinstance(items, list):
            raise TypeError("Crossref items malformed")
        return [
            {
                "id": x.get("DOI", ""),
                "doi": x.get("DOI"),
                "title": (x.get("title") or [""])[0],
                "year": str((x.get("published", {}).get("date-parts") or [[""]])[0][0]),
                "authors": [a.get("family", "") for a in x.get("author", [])],
                "retracted": any(
                    "retract" in str(y.get("type", "")).casefold()
                    for y in x.get("update-to", [])
                    if isinstance(y, dict)
                ),
            }
            for x in items
            if isinstance(x, dict)
        ]
    if provider == "openalex":
        if "results" not in value and "id" not in value:
            raise ValueError("OpenAlex result missing")
        items = value.get("results", [value])
        if not isinstance(items, list):
            raise TypeError("OpenAlex results malformed")
        return [
            {
                "id": x.get("id", ""),
                "doi": x.get("doi"),
                "title": x.get("display_name", ""),
                "year": str(x.get("publication_year", "")),
                "authors": [
                    a.get("author", {}).get("display_name", "")
                    for a in x.get("authorships", [])
                ],
                "retracted": bool(x.get("is_retracted")),
            }
            for x in items
            if isinstance(x, dict)
        ]
    if "result" not in value:
        raise ValueError("DBLP result missing")
    hits = value.get("result", {}).get("hits", {}).get("hit", [])
    if isinstance(hits, dict):
        hits = [hits]
    if not isinstance(hits, list):
        raise TypeError("DBLP hits malformed")
    return [
        {
            "id": x.get("info", {}).get("key", ""),
            "doi": x.get("info", {}).get("doi"),
            "title": x.get("info", {}).get("title", ""),
            "year": str(x.get("info", {}).get("year", "")),
            "authors": x.get("info", {}).get("authors", {}).get("author", []),
            "retracted": False,
        }
        for x in hits
        if isinstance(x, dict)
    ]


def _result(
    reference: ReferenceRecord, provider: Provider, raw: bytes
) -> tuple[CheckStatus, str | None, str | None]:
    try:
        candidates = _candidates(provider, raw)
    except (ValueError, TypeError, IndexError, KeyError, ET.ParseError):
        return "unknown", None, None
    matched = []
    incomplete_identity = False
    for item in candidates:
        identifier = str(item.get("id") or "")
        if reference.arxiv_id and provider == "arxiv":
            agrees = identifier.casefold() == reference.arxiv_id.casefold()
        elif reference.doi and item.get("doi"):
            agrees = _doi(str(item["doi"])) == _doi(reference.doi)
        elif reference.doi and provider in {"crossref", "openalex"}:
            incomplete_identity = True
            agrees = False
        else:
            authors_val = item.get("authors")
            authors = authors_val if isinstance(authors_val, (list, tuple)) else []
            authors_text = " ".join(str(a) for a in authors)
            agrees = (
                _normalize(str(item.get("title", ""))) == _normalize(reference.title)
                and str(item.get("year", "")) == str(reference.year)
                and any(
                    _normalize(a) in _normalize(authors_text) for a in reference.authors
                )
            )
        if agrees:
            matched.append(item)
    if len(matched) > 1:
        return "ambiguous", None, None
    if not matched:
        # Title searches and truncated result windows cannot establish absence.
        conclusive = (
            provider in {"crossref", "openalex"} and reference.doi is not None
        ) or (provider == "arxiv" and reference.arxiv_id is not None)
        return (
            ("not_found" if conclusive and not incomplete_identity else "unknown"),
            None,
            None,
        )
    item = matched[0]
    retracted = bool(item.get("retracted"))
    return (
        "retracted" if retracted else "verified",
        str(item.get("id")),
        "provider_retraction_metadata" if retracted else None,
    )


def check_response(
    reference: ReferenceRecord,
    provider: Provider,
    raw: bytes,
    *,
    observed_at: str,
    http_status: int = 200,
    check_id: str | None = None,
    batch_id: str | None = None,
) -> CheckReceipt:
    """Evaluate supplied bytes only; never opens a network connection."""
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("provider response exceeds byte limit")
    if http_status == 404 and provider in {"crossref", "openalex"} and reference.doi:
        status, matched_id, retraction = "not_found", None, None
    elif http_status == 429 or 500 <= http_status <= 599:
        status, matched_id, retraction = "unavailable", None, None
    elif http_status != 200:
        status, matched_id, retraction = "unknown", None, None
    else:
        status, matched_id, retraction = _result(reference, provider, raw)
    reference_digest = sha256_hex(
        canonical_json_bytes(reference.model_dump(mode="json"))
    )
    if check_id is None:
        check_id = (
            "check."
            + sha256_hex(
                canonical_json_bytes(
                    [reference_digest, provider, sha256_hex(raw), observed_at]
                )
            )[:24]
        )
    body = {
        "schema_version": "arw.citation-check.v1",
        "reference_sha256": reference_digest,
        "check_id": check_id,
        "provider": provider,
        "query": _query(reference, provider),
        "response_sha256": sha256_hex(raw),
        "http_status": http_status,
        "parser_version": PARSER_VERSION,
        "observed_at": observed_at,
        "status": status,
        "matched_id": matched_id,
        "retraction_evidence": retraction,
        "error_code": f"http_{http_status}" if status == "unavailable" else None,
    }
    if batch_id is not None:
        body["batch_id"] = batch_id
    return CheckReceipt.model_validate(
        {**body, "receipt_sha256": sha256_hex(canonical_json_bytes(body))}
    )


def check_unavailable(
    reference: ReferenceRecord,
    provider: Provider,
    *,
    observed_at: str,
    error_code: str,
    check_id: str | None = None,
    batch_id: str | None = None,
) -> CheckReceipt:
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", error_code):
        raise ValueError("invalid transport error code")
    reference_digest = sha256_hex(
        canonical_json_bytes(reference.model_dump(mode="json"))
    )
    if check_id is None:
        check_id = (
            "check."
            + sha256_hex(
                canonical_json_bytes(
                    [reference_digest, provider, error_code, observed_at]
                )
            )[:24]
        )
    body = {
        "schema_version": "arw.citation-check.v1",
        "reference_sha256": reference_digest,
        "check_id": check_id,
        "provider": provider,
        "query": _query(reference, provider),
        "response_sha256": sha256_hex(b""),
        "http_status": None,
        "parser_version": PARSER_VERSION,
        "observed_at": observed_at,
        "status": "unavailable",
        "matched_id": None,
        "retraction_evidence": None,
        "error_code": error_code,
    }
    if batch_id is not None:
        body["batch_id"] = batch_id
    return CheckReceipt.model_validate(
        {**body, "receipt_sha256": sha256_hex(canonical_json_bytes(body))}
    )


def fetch_response(
    reference: ReferenceRecord, provider: Provider, *, allow_network: bool = False
) -> bytes:
    """Opt-in fixed-host transport. Tests should inject fixture bytes instead."""
    if not allow_network:
        raise PermissionError("citation network lookup requires explicit opt-in")
    query = urllib.parse.quote(_query(reference, provider), safe="")
    urls = {
        "crossref": f"https://api.crossref.org/works/{query}"
        if reference.doi
        else f"https://api.crossref.org/works?query.bibliographic={query}&rows=5",
        "openalex": f"https://api.openalex.org/works/https://doi.org/{query}"
        if reference.doi
        else f"https://api.openalex.org/works?search={query}&per-page=5",
        "dblp": f"https://dblp.org/search/publ/api?q={query}&format=json&h=5",
        "arxiv": f"https://export.arxiv.org/api/query?search_query=id:{query}&max_results=5"
        if reference.arxiv_id
        else f"https://export.arxiv.org/api/query?search_query=all:{query}&max_results=5",
    }
    request = urllib.request.Request(
        urls[provider], headers={"User-Agent": "ARW/0.1 citation-verification"}
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("provider redirect forbidden")

    with urllib.request.build_opener(NoRedirect).open(request, timeout=8) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("provider response exceeds byte limit")
    return raw


def publish_check(root: Path, receipt: CheckReceipt, raw: bytes) -> None:
    if sha256_hex(raw) != receipt.response_sha256:
        raise ValueError("response digest mismatch")
    responses = _safe_directory(root, ("citations", "responses", "sha256"), create=True)
    receipts = _safe_directory(root, ("citations", "receipts", "sha256"), create=True)
    _write_once(responses / receipt.response_sha256, raw)
    _write_once(
        receipts / f"{receipt.receipt_sha256}.json",
        canonical_json_bytes(
            receipt.model_dump(
                mode="json", exclude={"batch_id"} if receipt.batch_id is None else None
            )
        ),
    )


def replay_check(
    root: Path, reference: ReferenceRecord, receipt_sha256: str
) -> CheckReceipt:
    if not re.fullmatch(r"[0-9a-f]{64}", receipt_sha256):
        raise ValueError("invalid receipt address")
    directory = _safe_directory(root, ("citations", "receipts", "sha256"), create=False)
    path = directory / f"{receipt_sha256}.json"
    if path.is_symlink():
        raise ValueError("unsafe receipt")
    receipt = CheckReceipt.model_validate(strict_json_loads(path.read_bytes()))
    if receipt.receipt_sha256 != receipt_sha256:
        raise ValueError("receipt address mismatch")
    response = (
        _safe_directory(root, ("citations", "responses", "sha256"), create=False)
        / receipt.response_sha256
    )
    if response.is_symlink() or response.stat().st_size > MAX_RESPONSE_BYTES:
        raise ValueError("unsafe response")
    raw = response.read_bytes()
    if sha256_hex(raw) != receipt.response_sha256:
        raise ValueError("response digest mismatch")
    replayed = (
        check_unavailable(
            reference,
            receipt.provider,
            observed_at=receipt.observed_at,
            error_code=receipt.error_code,
            check_id=receipt.check_id,
            batch_id=receipt.batch_id,
        )
        if receipt.status == "unavailable"
        and receipt.error_code is not None
        and receipt.http_status is None
        else check_response(
            reference,
            receipt.provider,
            raw,
            observed_at=receipt.observed_at,
            http_status=receipt.http_status or 200,
            check_id=receipt.check_id,
            batch_id=receipt.batch_id,
        )
    )
    if replayed != receipt:
        raise ValueError("offline citation replay mismatch")
    return receipt


def load_check_history(
    root: Path, reference: ReferenceRecord
) -> tuple[CheckReceipt, ...]:
    """Scan immutable receipts so callers cannot omit an old blocker."""
    directory = _safe_directory(root, ("citations", "receipts", "sha256"), create=False)
    entries = sorted(directory.iterdir())
    if len(entries) > 10_000:
        raise ValueError("citation receipt inventory exceeds limit")
    reference_digest = sha256_hex(
        canonical_json_bytes(reference.model_dump(mode="json"))
    )
    receipts = []
    for path in entries:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65_536:
            raise ValueError("unsafe citation receipt inventory")
        receipt = CheckReceipt.model_validate(strict_json_loads(path.read_bytes()))
        if receipt.receipt_sha256 != path.stem:
            raise ValueError("citation receipt address mismatch")
        if receipt.reference_sha256 == reference_digest:
            receipts.append(replay_check(root, reference, receipt.receipt_sha256))
    return tuple(
        sorted(receipts, key=lambda item: (item.observed_at, item.receipt_sha256))
    )


def validate_citation_artifact(root: Path, request, events) -> None:
    """Parent acceptance boundary for a reference or a replayable receipt."""
    from arw.kernel.ledger.manifests import load_artifact_manifest
    from arw.kernel.ledger.source_locations import read_retained_bytes
    from arw.kernel.state.models import ArtifactAcceptedPayload

    if request.media_type != "application/json":
        raise ValueError("citation artifacts require application/json")
    raw = read_retained_bytes(root, request.content_path, max_bytes=65_536)
    if request.artifact_kind == "reference-record":
        strict_json_loads(raw)
        reference = ReferenceRecord.model_validate_json(raw)
        if raw != canonical_json_bytes(reference.model_dump(mode="json")):
            raise ValueError("reference artifact is not canonical JSON")
        return
    if request.artifact_kind == "reference-use":
        strict_json_loads(raw)
        use = ReferenceUse.model_validate_json(raw)
        if raw != canonical_json_bytes(use.model_dump(mode="json")):
            raise ValueError("reference use artifact is not canonical JSON")
        for event in events:
            if event.event_type != "artifact.accepted" or not isinstance(
                event.payload, ArtifactAcceptedPayload
            ):
                continue
            manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
            if manifest.artifact_kind != "reference-record":
                continue
            reference_raw = read_retained_bytes(
                root, manifest.content_path, max_bytes=65_536
            )
            if sha256_hex(reference_raw) != manifest.content_sha256:
                raise ValueError("accepted reference bytes changed")
            reference = ReferenceRecord.model_validate_json(reference_raw)
            if reference.reference_id == use.reference_id:
                return
        raise ValueError("reference use has no parent-accepted reference")
    strict_json_loads(raw)
    receipt = CheckReceipt.model_validate_json(raw)
    if (
        request.content_path
        != f"citations/receipts/sha256/{receipt.receipt_sha256}.json"
    ):
        raise ValueError("citation receipt is outside its immutable address")
    if raw != canonical_json_bytes(
        receipt.model_dump(
            mode="json", exclude={"batch_id"} if receipt.batch_id is None else None
        )
    ):
        raise ValueError("citation receipt is not canonical JSON")
    for event in events:
        if not isinstance(event.payload, ArtifactAcceptedPayload):
            continue
        manifest = load_artifact_manifest(root, event.payload.manifest_sha256)
        if (
            manifest.artifact_kind != "reference-record"
            or manifest.content_sha256 != receipt.reference_sha256
        ):
            continue
        reference_raw = read_retained_bytes(
            root, manifest.content_path, max_bytes=65_536
        )
        if sha256_hex(reference_raw) != receipt.reference_sha256:
            raise ValueError("accepted reference bytes changed")
        strict_json_loads(reference_raw)
        reference = ReferenceRecord.model_validate_json(reference_raw)
        if replay_check(root, reference, receipt.receipt_sha256) != receipt:
            raise ValueError("citation receipt replay differs")
        return
    raise ValueError("citation receipt has no parent-accepted reference")


def accepted_citation_evidence(
    root: Path, reference: ReferenceRecord, use: ReferenceUse, events
) -> tuple[str, str, tuple[tuple[str, CheckReceipt], ...]]:
    """Read only accepted manifests, replaying each accepted receipt from retained bytes."""
    from arw.kernel.ledger.manifests import load_artifact_manifest
    from arw.kernel.ledger.source_locations import read_retained_bytes
    from arw.kernel.state.models import ArtifactAcceptedPayload

    if use.reference_id != reference.reference_id:
        raise ValueError("reference use identity mismatch")
    ref_digest = sha256_hex(canonical_json_bytes(reference.model_dump(mode="json")))
    use_digest = sha256_hex(canonical_json_bytes(use.model_dump(mode="json")))
    ref_manifest = None
    use_manifest = None
    accepted: list[tuple[str, CheckReceipt]] = []
    for event in events:
        if event.event_type != "artifact.accepted" or not isinstance(
            event.payload, ArtifactAcceptedPayload
        ):
            continue
        digest = event.payload.manifest_sha256
        manifest = load_artifact_manifest(root, digest)
        if manifest.artifact_kind not in {
            "reference-record",
            "reference-use",
            "citation-check-receipt",
        }:
            continue
        raw = read_retained_bytes(root, manifest.content_path, max_bytes=65_536)
        if sha256_hex(raw) != manifest.content_sha256:
            raise ValueError("accepted citation artifact bytes changed")
        if (
            manifest.artifact_kind == "reference-record"
            and manifest.content_sha256 == ref_digest
        ):
            if ReferenceRecord.model_validate_json(raw) != reference:
                raise ValueError("accepted reference differs")
            ref_manifest = digest
        elif (
            manifest.artifact_kind == "reference-use"
            and manifest.content_sha256 == use_digest
        ):
            if ReferenceUse.model_validate_json(raw) != use:
                raise ValueError("accepted reference use differs")
            use_manifest = digest
        elif manifest.artifact_kind == "citation-check-receipt":
            receipt = CheckReceipt.model_validate_json(raw)
            if receipt.reference_sha256 == ref_digest:
                if (
                    manifest.content_path
                    != f"citations/receipts/sha256/{receipt.receipt_sha256}.json"
                ):
                    raise ValueError("accepted citation receipt address differs")
                if replay_check(root, reference, receipt.receipt_sha256) != receipt:
                    raise ValueError("accepted citation receipt replay differs")
                accepted.append((digest, receipt))
    if ref_manifest is None or use_manifest is None:
        raise ValueError("reference and use require parent-accepted artifacts")
    if len(accepted) > 126:
        raise ValueError(
            "accepted citation receipt history exceeds gate evidence limit"
        )
    return ref_manifest, use_manifest, tuple(accepted)


def aggregate_status(
    receipts: Sequence[CheckReceipt], *, applicable: Sequence[Provider]
) -> CheckStatus:
    if not applicable:
        return "unknown"
    latest = {
        p: max(
            (r for r in receipts if r.provider == p),
            key=lambda r: (r.observed_at, r.receipt_sha256),
            default=None,
        )
        for p in applicable
    }
    statuses = [r.status if r is not None else "unknown" for r in latest.values()]
    if "retracted" in statuses:
        return "retracted"
    if "ambiguous" in statuses:
        return "ambiguous"
    if "verified" in statuses:
        return "verified"
    if "unavailable" in statuses:
        return "unavailable"
    if "unknown" in statuses:
        return "unknown"
    return "not_found"


def evaluate_use(
    use: ReferenceUse,
    reference: ReferenceRecord,
    receipts: Sequence[CheckReceipt],
    *,
    applicable: Sequence[Provider],
) -> dict[str, object]:
    if use.reference_id != reference.reference_id:
        raise ValueError("reference use identity mismatch")
    digest = sha256_hex(canonical_json_bytes(reference.model_dump(mode="json")))
    if any(receipt.reference_sha256 != digest for receipt in receipts):
        raise ValueError("citation receipt names another reference")
    if len(set(applicable)) != len(applicable) or not applicable:
        raise ValueError("applicable providers must be nonempty and unique")
    if any(r.provider not in applicable for r in receipts):
        raise ValueError("citation receipt is outside applicable providers")
    # A legacy receipt is its own batch. Shared timestamps never imply a batch.
    batches: dict[str, list[CheckReceipt]] = {}
    for receipt in receipts:
        batches.setdefault(receipt.batch_id or receipt.receipt_sha256, []).append(
            receipt
        )
    for batch in batches.values():
        if len({r.provider for r in batch}) != len(batch):
            raise ValueError("citation batch contains duplicate provider checks")
    ordered = sorted(
        batches.values(),
        key=lambda batch: max((r.observed_at, r.receipt_sha256) for r in batch),
    )
    current_batch = ordered[-1] if ordered else []
    current = aggregate_status(current_batch, applicable=applicable)
    prior_blockers = []
    if use.role == "supporting":
        for batch in ordered:
            if any(r.status == "retracted" for r in batch):
                prior_blockers.extend(
                    r.receipt_sha256 for r in batch if r.status == "retracted"
                )
            elif aggregate_status(batch, applicable=applicable) == "not_found":
                prior_blockers.extend(
                    r.receipt_sha256 for r in batch if r.status == "not_found"
                )
    open_blockers = sorted(set(prior_blockers))
    if open_blockers or (
        use.role == "supporting" and current in {"not_found", "retracted"}
    ):
        verdict = "BLOCK"
    elif use.role == "research_object" and any(
        r.status == "retracted" for r in receipts
    ):
        verdict = "HUMAN_REVIEW"
    elif current == "verified":
        verdict = "PASS"
    else:
        verdict = "HUMAN_REVIEW"
    return {
        "use_id": use.use_id,
        "status": current,
        "verdict": verdict,
        "open_blocker_receipts": open_blockers,
    }


def contamination_signals(receipts: Sequence[CheckReceipt]) -> dict[str, bool]:
    """Only conclusive check results produce true/false lookup signals."""
    latest = {
        p: max(
            (x for x in receipts if x.provider == p),
            key=lambda r: (r.observed_at, r.receipt_sha256),
            default=None,
        )
        for p in ("crossref", "openalex", "arxiv")
    }
    return {
        f"{p}_unmatched": r.status == "not_found"
        for p, r in latest.items()
        if r is not None and r.status in {"not_found", "verified", "retracted"}
    }
