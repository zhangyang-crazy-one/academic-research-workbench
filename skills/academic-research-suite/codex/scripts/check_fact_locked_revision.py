#!/usr/bin/env python3
"""Fact-locked revision gate for results-presentation rewrites.

Use when an author asks to rewrite result descriptions, captions, or the
discussion of tables and figures to foreground comparisons, magnitudes and
consistency — while keeping every underlying quantitative fact unchanged.

The gate reuses the upstream #570 token extractor
(``ars/scripts/check_revision_token_conservation.py``) and adds the
set-level and table-row checks such a rewrite needs:

  F1  **new values** — any numeric token in the revision that occurs nowhere
      in the source. A fact-locked rewrite may re-state or regroup existing
      numbers; it may not introduce a derived ratio, percentage, count, or
      rounded variant. Always ``fail``.
  F2  **dropped values** — any numeric token in the source that no longer
      occurs anywhere in the revision. Deleting a reported fact changes the
      paper's content; ``fail`` unless the value is explicitly waived with
      ``--allow-drop`` (for layout widths or an erroneous cross-reference).
  F3  **table rows** — every LaTeX ``tabular`` or Markdown table data row that
      carries a number is reduced to the multiset of its normalized cells
      (formatting such as ``\\textbf`` and braces removed). Rows may be
      reordered, columns moved, and descriptive cells added, but each source
      row's labels and values must survive together in one distinct revision
      row; a source row with no such match is a
      ``fail`` (a value changed, moved between rows, or was deleted). A
      revision row with no source counterpart (for example a new comparison
      key whose labels contain digits) is a ``warn``: F1 already blocks new
      values, and the attachment of re-stated numbers is checked by hand.
  F4  **citations** — the upstream citation-token multiset (markers, bracket
      groups, author-year) and the set of LaTeX ``\\cite`` keys must be
      unchanged, except explicitly mapped bracket-to-key migrations. Mapped
      identities also conserve occurrence counts. ``fail`` on any other delta.

Contract boundaries:

  - **Necessary, not sufficient.** Exact-token checks cannot see negation,
    comparison direction, the arm or view a number is attached to inside
    prose, modality, or causal strength. The report always carries the
    human semantic checklist; a PASS is never a semantic-fidelity verdict.
  - Counts of repeated mentions may change freely (re-stating a headline
    number in a new comparison paragraph is the point of the rewrite).
  - Exit codes: 0 = no ``fail``; 1 = at least one ``fail``; 2 = usage/IO.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = Path(__file__).resolve()
SUITE_ROOT = SCRIPT.parents[2]
UPSTREAM_TOKEN_SCRIPT = (
    SUITE_ROOT / "ars" / "scripts" / "check_revision_token_conservation.py"
)
TABULAR_RE = re.compile(r"\\begin\{tabular\*?\}.*?\\end\{tabular\*?\}", re.DOTALL)
MD_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
TABULAR_SPEC_RE = re.compile(
    r"\\begin\{tabular\*?\}(\{[^}]*\})?\{(?:[^{}]|\{[^{}]*\})*\}"
)
LATEX_CITE_RE = re.compile(r"\\cite[a-zA-Z]*\*?(?:\[[^\]]*\]){0,2}\{([^}]+)\}")
CELL_FORMAT_RE = re.compile(
    r"\\(?:textbf|textit|textsc|emph|underline|mathbf|mathrm|bm|boldsymbol|hline|midrule|"
    r"toprule|bottomrule)\b"
)

SEMANTIC_CHECKLIST = (
    (
        "Each numeric claim is still attached to the same arm, baseline, metric, "
        "cohort, and evaluation view as in the source."
    ),
    "Comparison direction and sign are unchanged (gain vs. loss, above vs. below).",
    (
        "Multiplicative or ordinal wording (doubles, largest, order of magnitude) is "
        "verifiable from the source numbers without computing a new reported value."
    ),
    (
        "Load-bearing qualifiers survive: intervals that include zero, post hoc or "
        "exploratory status, conditional/common-valid diagnostics, and scope limits."
    ),
    "Associational wording is not upgraded to causal wording.",
)


def _load_upstream() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_revision_token_conservation", UPSTREAM_TOKEN_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load upstream extractor: {UPSTREAM_TOKEN_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _table_rows(text: str) -> list[str]:
    rows: list[str] = []
    for block in TABULAR_RE.findall(text):
        body = TABULAR_SPEC_RE.sub("", block, count=1)
        for line in body.splitlines():
            if "&" in line and "\\\\" in line:
                rows.append(line.strip())
    for line in text.splitlines():
        stripped = line.strip()
        if (
            stripped.startswith("|")
            and stripped.count("|") >= 3
            and not MD_SEPARATOR_RE.match(stripped)
        ):
            rows.append(stripped)
    return rows


def _cells(upstream: ModuleType, row: str) -> tuple[str, ...]:
    """Order-insensitive cell signature: labels and values must stay together."""
    row = upstream.normalize_text(row)
    if row.lstrip().startswith("|"):
        raw_cells = row.strip().strip("|").split("|")
    else:
        raw_cells = row.split("\\\\", 1)[0].split("&")
    cells = []
    for cell in raw_cells:
        cleaned = CELL_FORMAT_RE.sub("", cell)
        cleaned = re.sub(r"[{}$]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            cells.append(cleaned)
    return tuple(sorted(cells))


def _row_signatures(upstream: ModuleType, text: str) -> list[tuple[str, ...]]:
    return [
        _cells(upstream, row)
        for row in _table_rows(text)
        if upstream.extract_numbers(row)
    ]


def _match_rows(
    source_rows: list[tuple[str, ...]], revision_rows: list[tuple[str, ...]]
) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]]]:
    """Match each source row to a distinct revision row containing all its cells.

    A revision row may add cells (a new descriptive column) but must keep every
    source cell of the row it matches. Exact matches are consumed first so an
    added column elsewhere cannot steal a row's exact counterpart.
    """
    remaining = list(revision_rows)
    lost: list[tuple[str, ...]] = []
    pending: list[tuple[str, ...]] = []
    for row in source_rows:
        if row in remaining:
            remaining.remove(row)
        else:
            pending.append(row)
    for row in pending:
        need = Counter(row)
        match = next((cand for cand in remaining if not (need - Counter(cand))), None)
        if match is None:
            lost.append(row)
        else:
            remaining.remove(match)
    return lost, remaining


def _latex_cite_keys(text: str) -> set[str]:
    return {
        key.strip()
        for group in LATEX_CITE_RE.findall(text)
        for key in group.split(",")
        if key.strip()
    }


def _citation_mapping(entries: tuple[str, ...]) -> dict[str, str]:
    """Accept only explicit singleton bracket-number to bibliography-key pairs."""
    mapping: dict[str, str] = {}
    for entry in entries:
        match = re.fullmatch(r"\s*\[(\d+)\]\s*=\s*([A-Za-z][A-Za-z0-9_:.-]*)\s*", entry)
        if not match:
            raise ValueError(f"invalid citation mapping {entry!r}; expected [4]=r4")
        number, key = match.groups()
        if number in mapping or key in mapping.values():
            raise ValueError("citation mappings must have unique numbers and keys")
        mapping[number] = key
    return mapping


def _canonical_citations(
    upstream: ModuleType, text: str, mapping: dict[str, str]
) -> str:
    # Decode Pandoc's escaped brackets before tokenization. Match a complete
    # citation group: [4] must never rewrite the 4 inside [4, 5] or [4-6].
    text = upstream.normalize_text(text).replace("{[}", "[").replace("{]}", "]")

    def replace(match: re.Match[str]) -> str:
        number = match.group(0)[1:-1]
        return (
            "\\cite{" + mapping[number] + "}" if number in mapping else match.group(0)
        )

    return upstream.SQUARE_CITATION_RE.sub(replace, text)


def _without_mapped_key_numbers(text: str, keys: set[str]) -> str:
    # A citation migration exempts its citation label, never a same-valued fact
    # elsewhere in the prose. Also avoid treating digits in a mapped key as data.
    def replace(match: re.Match[str]) -> str:
        remaining = [
            key for key in match.group(1).split(",") if key.strip() not in keys
        ]
        start, end = match.span(1)
        return (
            match.group(0)[: start - match.start()]
            + ",".join(remaining)
            + match.group(0)[end - match.start() :]
        )

    return LATEX_CITE_RE.sub(replace, text)


def _mapped_citation_counts(text: str, keys: set[str]) -> Counter:
    # Match the upstream extractor's treatment of hidden HTML comments.
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    return Counter(
        key.strip()
        for group in LATEX_CITE_RE.findall(text)
        for key in group.split(",")
        if key.strip() in keys
    )


def _finding(
    check: str, severity: str, detail: str, values: list[str]
) -> dict[str, Any]:
    return {"check": check, "severity": severity, "detail": detail, "values": values}


def audit(
    source: str,
    revision: str,
    *,
    allow_drop: tuple[str, ...] = (),
    citation_map: tuple[str, ...] = (),
) -> dict[str, Any]:
    upstream = _load_upstream()
    mapping = _citation_mapping(citation_map)
    source = _canonical_citations(upstream, source, mapping)
    revision = _canonical_citations(upstream, revision, mapping)
    mapped_keys = set(mapping.values())
    source_numeric = _without_mapped_key_numbers(source, mapped_keys)
    revision_numeric = _without_mapped_key_numbers(revision, mapped_keys)
    source_numbers = upstream.extract_numbers(source_numeric)
    revision_numbers = upstream.extract_numbers(revision_numeric)
    findings: list[dict[str, Any]] = []

    new_values = sorted(set(revision_numbers) - set(source_numbers))
    if new_values:
        findings.append(
            _finding(
                "F1",
                "fail",
                "numeric values in the revision that occur nowhere in the source",
                new_values,
            )
        )
    allowed = {upstream.normalize_text(value).strip() for value in allow_drop}
    dropped = sorted(set(source_numbers) - set(revision_numbers))
    waived = [value for value in dropped if value in allowed]
    unwaived = [value for value in dropped if value not in allowed]
    if unwaived:
        findings.append(
            _finding(
                "F2",
                "fail",
                "source values that no longer occur in the revision",
                unwaived,
            )
        )

    source_rows = _row_signatures(upstream, source)
    revision_rows = _row_signatures(upstream, revision)
    lost_rows, gained_rows = _match_rows(source_rows, revision_rows)
    if lost_rows:
        findings.append(
            _finding(
                "F3",
                "fail",
                "source table rows whose numbers no longer survive together in any "
                "revision row (a value changed, moved between rows, or was deleted)",
                [" | ".join(sig) for sig in sorted(lost_rows)],
            )
        )
    if gained_rows:
        findings.append(
            _finding(
                "F3",
                "warn",
                "revision table rows with no source counterpart; F1 already blocks new "
                "values, so confirm each re-stated number keeps its original attachment",
                [" | ".join(sig) for sig in sorted(gained_rows)],
            )
        )

    citations = upstream.audit_pair(source, revision)["citations_delta"]
    source_keys, revision_keys = _latex_cite_keys(source), _latex_cite_keys(revision)
    citation_changes = (
        [f"-{k}" for k in citations.get("removed", {})]
        + [f"+{k}" for k in citations.get("added", {})]
        + [f"-\\cite{{{k}}}" for k in sorted(source_keys - revision_keys)]
        + [f"+\\cite{{{k}}}" for k in sorted(revision_keys - source_keys)]
    )
    source_mapped = _mapped_citation_counts(source, mapped_keys)
    revision_mapped = _mapped_citation_counts(revision, mapped_keys)
    for key in sorted(mapped_keys):
        if source_mapped[key] != revision_mapped[key]:
            citation_changes.append(
                f"mapped citation {key}: {source_mapped[key]} -> {revision_mapped[key]} occurrences"
            )
    if citation_changes:
        findings.append(
            _finding(
                "F4",
                "fail",
                "citation tokens or LaTeX cite keys changed",
                citation_changes,
            )
        )

    multiset = upstream.audit_pair(source_numeric, revision_numeric)["numbers_delta"]
    return {
        "schema": "arw.fact-locked-revision-report.v1",
        "passed": not any(item["severity"] == "fail" for item in findings),
        "findings": findings,
        "waived_drops": waived,
        "citation_mapping": {f"[{number}]": key for number, key in mapping.items()},
        "table_rows": {"source": len(source_rows), "revision": len(revision_rows)},
        "mention_count_delta": multiset,
        "semantic_checklist": list(SEMANTIC_CHECKLIST),
        "limitations": [
            (
                "Token checks cannot verify which arm, view, or metric a number is "
                "attached to in prose; complete the semantic checklist by hand."
            ),
            "Mention-count changes are informational and are not failures.",
        ],
    }


def _render(report: dict[str, Any]) -> str:
    lines = [f"fact-locked revision: {'PASS' if report['passed'] else 'FAIL'}"]
    for item in report["findings"]:
        shown = ", ".join(item["values"][:20])
        lines.append(
            f"  [{item['severity']}] {item['check']} {item['detail']}: {shown}"
        )
    if report["waived_drops"]:
        lines.append("  waived drops: " + ", ".join(report["waived_drops"]))
    if report["citation_mapping"]:
        lines.append(
            "  citation mapping: "
            + ", ".join(
                f"{number}={key}" for number, key in report["citation_mapping"].items()
            )
        )
    lines.append(
        f"  table rows checked: source {report['table_rows']['source']}, "
        f"revision {report['table_rows']['revision']}"
    )
    lines.append("  semantic checklist (manual):")
    lines.extend(f"    - {item}" for item in report["semantic_checklist"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().splitlines()[0]
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", type=Path, required=True)
    parser.add_argument(
        "--allow-drop",
        action="append",
        default=[],
        metavar="VALUE",
        help="waive one dropped source value (repeatable); record the reason",
    )
    parser.add_argument(
        "--citation-map",
        action="append",
        default=[],
        metavar="[NUMBER]=KEY",
        help="explicit citation equivalence, e.g. '[4]=r4' (repeatable); verify against bibliography",
    )
    parser.add_argument("--json", action="store_true", help="emit the JSON report")
    args = parser.parse_args(argv)
    try:
        source = args.source.read_text(encoding="utf-8")
        revision = args.revision.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"cannot read input: {exc}", file=sys.stderr)
        return 2
    try:
        report = audit(
            source,
            revision,
            allow_drop=tuple(args.allow_drop),
            citation_map=tuple(args.citation_map),
        )
    except ValueError as exc:
        print(f"invalid arguments: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.json
        else _render(report)
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
