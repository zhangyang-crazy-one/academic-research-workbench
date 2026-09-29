# Manuscript Package Hygiene Audit

`scripts/check_manuscript_hygiene.py` is a deterministic, advisory scan of a
manuscript package directory. It targets mechanical defects that narrative
review tends to miss: every panel member reads for argument and evidence,
and nobody opens the SVG or counts dots per inch.

Run it before a submission package, a camera-ready export, or a public
release, and after any fact-locked rewrite:

```bash
python3 skills/academic-research-suite/codex/scripts/check_manuscript_hygiene.py \
  <package dir> [--min-dpi 300] [--json] [--strict]
```

## Checks

| ID | Class | Detects | Default severity |
| --- | --- | --- | --- |
| H1 | deterministic | Absolute local paths (`/home/<user>/`, `/Users/<user>/`, `C:\Users\`, `file://`) in text files. The report redacts the user segment. | fail |
| H2 | heuristic | Markdown links and JSON path strings or keys that do not resolve inside the package, for example workspace paths such as `experiments/...` | warn |
| H3 | heuristic | Hard-coded numeric citations (`{[}4{]}`, `[12]`) in LaTeX that otherwise uses `\cite` | warn |
| H4 | heuristic | Hard-coded cross-reference numbers (`Section 4.1`, `Table 3`, `Fig. 2`) instead of `\ref`; Markdown numbering often contradicts the class numbering (IEEEtran prints IV-A) | warn |
| H5 | heuristic | Figure or table labels never referenced in the text | warn |
| H6 | deterministic | Embedded SVG rasters whose effective print resolution is below `--min-dpi` | fail |
| H7 | deterministic (needs pypdf) | PDFs that are one full-page raster with no vector text (warn), and embedded PDF images below `--min-dpi` (fail). Reports `not_checked` when pypdf is unavailable. | warn / fail |

Citation `[Sec.~3, Fig.~1]` optional arguments and `thebibliography` bodies are
masked before H3 and H4, and LaTeX comments are ignored.

## Boundaries

- Advisory by default: exit 0 unless `--strict` is set and a `fail` exists.
- Detection only. The script never edits, moves, or redacts package files,
  and the scholar decides each fix.
- H6 ignores SVG transforms and uses the declared display width. H7 follows
  `cm` and Form XObject matrices but not every PDF construct. Treat an H7
  `not_checked` as "not checked", never as a pass.
- A clean report is not an anonymity or camera-ready verdict. The #394
  submission-package verifier (`ars/scripts/verify_submission_package.py`)
  remains the authority for reference integrity, venue limits, and
  blind-copy residue.

## Real-Use Provenance

A 2026-09 pre-submission review of a taxonomy-discovery manuscript found each
of these by hand after an earlier internal review had passed the package:

- a method figure whose illustration was a 168×113 px raster printed at about
  100 dpi (H6);
- figure PDFs that were single full-page rasters (H7);
- `Section 4.1` in an IEEEtran paper (H4);
- a hard-coded `{[}4{]}` in a table caption (H3);
- two figures never cited in the text (H5);
- workspace paths in the evidence JSON (H2);
- a reviewer note containing a home-directory path (H1).

Run against that package, the script reproduces every one of these findings,
and the fact-locked revision's manuscript source produces no finding.
