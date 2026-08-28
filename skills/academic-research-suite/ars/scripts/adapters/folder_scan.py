#!/usr/bin/env python3
"""folder_scan: produce a literature_corpus passport from a directory of
files (typically PDFs). Parses citation metadata from filenames using
best-effort conventions. Never parses PDF content.

Filename conventions recognized:
  - {Family}_{Year}_{title_slug}.{ext}  (underscore-separated)
  - {Family}{Year}{optional_title_slug}.{ext}  (concatenated)
  - Unicode {Family}{separator}{Year}{separator}{title}.{ext}, where separator
    is underscore, hyphen, period, or ASCII space
  - fallback: first capitalized Latin word before the year.

Files whose filename cannot be parsed for both family and year are rejected.
Unicode family tokens are accepted only when every code point is a letter,
combining mark, documented apostrophe, or documented hyphen.

Usage:
  python scripts/adapters/folder_scan.py \\
      --input <dir> --passport <out.yaml> --rejection-log <out.yaml>
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import unicodedata
from pathlib import Path

# pi-lens-ignore: jscpd:duplicate
# Allow running as a script: ensure repo root is importable for
# `from scripts.adapters._common import ...`
_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.adapters._common import (
    make_citation_key,
    now_iso,
    path_to_file_uri,
    write_passport,
    write_rejection_log,
)

ADAPTER_NAME = "folder_scan.py"
ADAPTER_VERSION = "1.2.0"

# Family_Year_title style: "Wang_2023_formative_feedback.pdf"
RE_FAMILY_UNDERSCORE = re.compile(
    r"^([A-Z][A-Za-z]*)_((?:19|20)\d{2})(?:_(.*?))?\.[A-Za-z0-9]+$"
)
# Family{Year} style: "Chen2024_AIAssessment.pdf" or "Chen2024.pdf"
RE_FAMILY_YEAR = re.compile(
    r"^([A-Z][A-Za-z]*)((?:19|20)\d{2})[_\-.\s]?(.*?)\.[A-Za-z0-9]+$"
)
# fallback year anywhere
RE_ANY_YEAR = re.compile(r"((?:19|20)\d{2})")
RE_FIRST_CAPITAL = re.compile(r"\b([A-Z][A-Za-z]+)\b")
RE_UNICODE_SEPARATED = re.compile(
    r"^(.+?)([_\-. ])((?:19|20)\d{2})(?:([_\-. ])(.*))?\.[A-Za-z0-9]+$"
)
_FAMILY_PUNCTUATION = frozenset({"'", "’", "-", "‐", "‑"})
_CITATION_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_:-]*$")


def _parse_year(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _is_unicode_family(value: str) -> bool:
    """Return whether ``value`` satisfies the explicit safe family grammar."""

    has_letter = False
    for character in value:
        category = unicodedata.category(character)
        if category.startswith("L"):
            has_letter = True
            continue
        if category.startswith("M") or character in _FAMILY_PUNCTUATION:
            continue
        return False
    return has_letter


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _surrogate_safe_text(value: str) -> str:
    return value.encode("utf-8", errors="backslashreplace").decode("utf-8")


def _unicode_citation_key_base(*, family: str, year: int, title: str) -> str:
    """Derive an ASCII base from a private NFKC copy, never display fields."""

    normalized = unicodedata.normalize("NFKC", f"{family}\0{year}\0{title}")
    token = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"ref{year}{token}"


def _unique_ascii_citation_key(base: str, existing: set[str]) -> str:
    """Apply the shared adapter's a..z, aa..zz collision policy locally."""

    if not _CITATION_KEY.fullmatch(base):
        raise ValueError("Unicode citation-key base is not schema-valid ASCII")
    if base not in existing:
        existing.add(base)
        return base
    suffixes = list("abcdefghijklmnopqrstuvwxyz") + [
        first + second
        for first in "abcdefghijklmnopqrstuvwxyz"
        for second in "abcdefghijklmnopqrstuvwxyz"
    ]
    for suffix in suffixes:
        candidate = f"{base}{suffix}"
        if candidate not in existing:
            existing.add(candidate)
            return candidate
    raise RuntimeError("exhausted citation key suffix space")


def parse_filename(name: str) -> dict | None:
    """Return {'family', 'year', 'title', 'title_hint'} or None if unparseable.

    `title` is the human-facing title written into the passport entry.
    `title_hint` is the substring used to derive the citation_key's
    third component — it MUST exclude the family token, otherwise
    make_citation_key would produce keys like ``chen2024chen``.
    """
    # pi-lens-ignore: jscpd:duplicate
    m = RE_FAMILY_UNDERSCORE.match(name)
    if m:
        family = m.group(1)
        year = _parse_year(m.group(2))
        if year is None:
            return None
        tail = (m.group(3) or "").strip()
        tail_words = tail.replace("_", " ").strip()
        title = f"{family} {year} {tail_words}".strip()
        return {
            "family": family,
            "year": year,
            "title": title,
            "title_hint": tail_words,
        }

    # pi-lens-ignore: jscpd:duplicate
    m = RE_FAMILY_YEAR.match(name)
    if m:
        family = m.group(1)
        year = _parse_year(m.group(2))
        if year is None:
            return None
        tail = (m.group(3) or "").strip()
        stem = Path(name).stem
        # Display title keeps the original stem layout (with _ → space).
        title = stem.replace("_", " ")
        return {
            "family": family,
            "year": year,
            "title": title,
            "title_hint": tail.replace("_", " "),
        }

    m = RE_UNICODE_SEPARATED.match(name)
    if m and not m.group(1).isascii():
        family = m.group(1)
        if not _is_unicode_family(family):
            return None
        stem = Path(name).stem
        tail = m.group(5) or ""
        year = _parse_year(m.group(3))
        if year is None:
            return None
        return {
            "family": family,
            "year": year,
            "title": stem,
            "title_hint": tail,
        }

    year_match = RE_ANY_YEAR.search(name)
    if year_match:
        before_year = name.split(year_match.group(1))[0]
        fam_match = RE_FIRST_CAPITAL.search(before_year)
        if fam_match:
            year = _parse_year(year_match.group(1))
            if year is None:
                return None
            return {
                "family": fam_match.group(1),
                "year": year,
                "title": Path(name).stem.replace("_", " "),
                "title_hint": "",
            }
    return None


def _missing_fields_for(name: str) -> list[str]:
    """Diagnostic for the rejection_log."""
    if not RE_ANY_YEAR.search(name):
        return ["authors", "year"]
    return ["authors"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    # pi-lens-ignore: jscpd:duplicate
    ap.add_argument("--input", type=Path, required=True, help="Directory to scan")
    ap.add_argument("--passport", type=Path, required=True)
    ap.add_argument("--rejection-log", dest="rejection_log", type=Path, required=True)
    args = ap.parse_args()

    if not args.input.exists() or not args.input.is_dir():
        print(f"ERROR: input directory not found: {args.input}", file=sys.stderr)
        return 1

    entries: list[dict] = []
    rejected: list[dict] = []
    existing_keys: set[str] = set()

    input_root = args.input.resolve()
    files = sorted(
        p for p in args.input.rglob("*") if p.is_file() and p.name != ".gitkeep"
    )
    for f in files:
        # Use path relative to --input so two files with the same basename
        # in different subdirectories remain distinguishable in both the
        # passport (via source_pointer) and the rejection log.
        try:
            rel = f.relative_to(args.input)
        except ValueError:
            # Defensive: rglob shouldn't yield this, but fall back to
            # basename if it ever does.
            rel = Path(f.name)
        rel_str = rel.as_posix()
        if _contains_surrogate(f.name) or _contains_surrogate(rel_str):
            safe_relative = _surrogate_safe_text(rel_str)
            rejected.append(
                {
                    "source": safe_relative,
                    "reason": "other",
                    "detail": "filename contains undecodable bytes",
                    "raw": safe_relative,
                    "missing_fields": [],
                }
            )
            continue
        if f.is_symlink():
            try:
                f.resolve().relative_to(input_root)
            except ValueError:
                rejected.append(
                    {
                        "source": rel_str,
                        "reason": "other",
                        "detail": "symlink resolves outside the input root",
                        "raw": rel_str,
                        "missing_fields": [],
                    }
                )
                continue
        parsed = parse_filename(f.name)
        if not parsed:
            rejected.append(
                {
                    "source": rel_str,
                    # pi-lens-ignore: typos:unknown
                    "reason": "authors_unparseable",
                    "raw": rel_str,
                    "missing_fields": _missing_fields_for(f.name),
                }
            )
            continue

        if parsed["family"].isascii():
            citation_key = make_citation_key(
                family=parsed["family"],
                year=parsed["year"],
                title_hint=parsed["title_hint"],
                existing=existing_keys,
            )
        else:
            citation_key = _unique_ascii_citation_key(
                _unicode_citation_key_base(
                    family=parsed["family"],
                    year=parsed["year"],
                    title=parsed["title"],
                ),
                existing_keys,
            )
        entries.append(
            {
                "citation_key": citation_key,
                "title": parsed["title"],
                "authors": [{"family": parsed["family"]}],
                "year": parsed["year"],
                "source_pointer": path_to_file_uri(f),
                "obtained_via": "folder-scan",
                "obtained_at": now_iso(),
                "adapter_name": ADAPTER_NAME,
                "adapter_version": ADAPTER_VERSION,
                # v3.10 (spec §3 PR-B item 13): a filename scan carries no structured
                # source-type metadata, so venue_type is always unknown/unknown —
                # never inferred from the filename (R-L3-2-D). Emitted as a pair to
                # honor the schema pair invariant.
                "venue_type": "unknown",
                "venue_type_provenance": "unknown",
            }
        )

    write_passport(args.passport, entries)
    write_rejection_log(
        args.rejection_log,
        adapter_name=ADAPTER_NAME,
        adapter_version=ADAPTER_VERSION,
        rejected=rejected,
        input_source=str(args.input),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
