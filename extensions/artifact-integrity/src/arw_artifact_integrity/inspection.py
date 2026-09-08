"""Pure, bounded Unicode diagnostics; no filesystem or canonical writes."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Sequence

from arw.adapters.artifacts import ArtifactIntegrityAdapter
from arw.ports.artifacts import (
    ArtifactInspection,
    DetectorResult,
    UnicodeFinding,
    UnicodeSanitization,
)

MAX_INPUT_BYTES = 1024 * 1024
MAX_FINDINGS = 256
DETECTORS = (
    "unicode",
    "exif",
    "xmp",
    "pdf_properties",
    "docx_properties",
    "c2pa",
    "statistical",
)


def category(codepoint: int) -> str | None:
    if (
        codepoint in {0x061C, 0x200E, 0x200F}
        or 0x202A <= codepoint <= 0x202E
        or 0x2066 <= codepoint <= 0x2069
    ):
        return "bidi"
    if 0xE0000 <= codepoint <= 0xE007F:
        return "tag"
    if (
        codepoint in {0xA0, 0x1680, 0x202F, 0x205F, 0x3000}
        or 0x2000 <= codepoint <= 0x200A
    ):
        return "exotic_space"
    if (
        codepoint in {0xAD, 0x034F, 0x180E, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF}
        or 0x2061 <= codepoint <= 0x2064
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0xE0100 <= codepoint <= 0xE01EF
    ):
        return "invisible"
    return None


def codepoint_name(value: int) -> str:
    return f"U+{value:04X}"


class ArtifactIntegrityInspector(ArtifactIntegrityAdapter):
    """The legacy receipt evaluator plus a bytes-first Unicode inspector."""

    def inspect_bytes(
        self, content: bytes, *, detectors: Sequence[str] | None = None
    ) -> ArtifactInspection:
        if not isinstance(content, bytes):
            raise TypeError("inspection requires bytes")
        if detectors is not None and len(detectors) > 32:
            raise ValueError("invalid or excessive detector selection")
        if detectors is not None and any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) for name in detectors):
            raise ValueError("invalid detector selection")
        if len(content) <= MAX_INPUT_BYTES and content.startswith((b"%PDF-", b"PK", b"\x89PNG", b"\xff\xd8")):
            from .binary import inspect_binary
            return inspect_binary(content, detectors)
        reason = "scanned_unicode_only"
        text = None
        if len(content) > MAX_INPUT_BYTES:
            reason = "input_too_large"
        elif content.startswith(
            (
                b"%PDF-",
                b"PK\x03\x04",
                b"PK\x05\x06",
                b"\x89PNG",
                b"\xff\xd8",
                b"GIF87a",
                b"GIF89a",
                b"II*\x00",
                b"MM\x00*",
                b"RIFF",
                b"{\\rtf",
                b"\xd0\xcf\x11\xe0",
            )
        ):
            reason = "unsupported_container"
        elif b"\x00" in content:
            reason = "binary_nul"
        else:
            try:
                text = content.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                reason = "invalid_utf8"
        results = {
            name: DetectorResult(
                status="unsupported", reason_code="detector_not_implemented"
            )
            for name in DETECTORS
        }
        for name in detectors or ():
            if name not in results:
                if (
                    not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name)
                    or len(results) >= 32
                ):
                    raise ValueError("invalid or excessive detector selection")
                results[name] = DetectorResult(
                    status="unsupported", reason_code="unknown_detector"
                )
        findings = []
        counts: Counter[str] = Counter()
        byte_offset = 0
        if text is not None:
            for offset, character in enumerate(text):
                family = category(ord(character))
                if family:
                    counts[family] += 1
                    if len(findings) < MAX_FINDINGS:
                        findings.append(
                            UnicodeFinding(
                                codepoint=codepoint_name(ord(character)),
                                category=family,
                                character_offset=offset,
                                byte_offset=byte_offset,
                            )
                        )
                byte_offset += len(character.encode("utf-8"))
            results["unicode"] = DetectorResult(
                status="detected" if counts else "not_detected",
                reason_code="bounded_unicode_scan",
            )
        else:
            results["unicode"] = DetectorResult(
                status="unsupported", reason_code=reason
            )
        total = sum(counts.values())
        return ArtifactInspection(
            status="inspected" if text is not None else "unsupported",
            reason_code=reason,
            content_sha256=hashlib.sha256(content).hexdigest()
            if len(content) <= MAX_INPUT_BYTES
            else None,
            input_bytes=len(content),
            detectors=results,
            findings=findings,
            category_counts=dict(counts),
            total_findings=total,
            truncated=total > MAX_FINDINGS,
        )

    def sanitize_bytes(
        self, content: bytes, *, privacy: bool, remove_codepoints: Sequence[str]
    ) -> UnicodeSanitization:
        if privacy is not True:
            raise ValueError("privacy_authorization_required")
        if not remove_codepoints or len(remove_codepoints) > 256:
            raise ValueError("explicit_codepoint_selection_required")
        selected = set()
        for value in remove_codepoints:
            if not re.fullmatch(r"U\+[0-9A-Fa-f]{4,6}", value):
                raise ValueError("invalid_codepoint_selection")
            codepoint = int(value.removeprefix("U+"), 16)
            if category(codepoint) is None:
                raise ValueError("unsupported_codepoint_selection")
            selected.add(codepoint)
        before = self.inspect_bytes(content)
        if before.status != "inspected":
            raise ValueError(before.reason_code)
        text = content.decode("utf-8")
        removed = Counter(
            codepoint_name(ord(character))
            for character in text
            if ord(character) in selected
        )
        derived = "".join(
            character for character in text if ord(character) not in selected
        )
        encoded = derived.encode("utf-8")
        # UTF-8 has a unique byte representation; no normalization or newline
        # translation occurs. Rebuild retained bytes independently for the gate.
        verified = encoded == b"".join(
            character.encode("utf-8")
            for character in text
            if ord(character) not in selected
        )
        return UnicodeSanitization(
            selected_codepoints=[codepoint_name(value) for value in sorted(selected)],
            derived_text=derived,
            removed_counts=dict(sorted(removed.items())),
            only_selected_changed=verified,
            before=before,
            after=self.inspect_bytes(encoded),
        )
