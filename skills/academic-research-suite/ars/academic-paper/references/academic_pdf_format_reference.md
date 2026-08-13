# Academic PDF Format Reference

Use this reference when converting Markdown reports or manuscripts to an
academic-style PDF. It supplements `formatter_agent.md` for cases where the
input is a Markdown report rather than a complete journal manuscript.

## Rendering Route

- Prefer Pandoc to LaTeX plus `tectonic` or XeLaTeX.
- Do not use browser/HTML-to-PDF for academic paper deliverables unless no
  LaTeX-capable engine is available and the limitation is explicitly reported.
- Keep the source Markdown unchanged. Generate a normalized build copy with YAML
  metadata and a LaTeX header.

## Title And Heading Rules

- Use the first Markdown `#` heading as PDF metadata title, then remove it from
  the body build copy to avoid duplicate title blocks.
- If the source already contains literal numbering such as `1.` and `1.1`, set
  `numbersections: false` and preserve the source numbering.
- If the source body starts at `##`, pass `--shift-heading-level-by=-1` so the
  PDF does not render every body heading as a subsection.
- Use a two-level table of contents for long reports unless the target venue
  forbids it.
- Section and subsection headings must be **black**. Do not apply decorative
  blue/teal heading colors. Colored headings look like product reports and fail
  ACL/IEEE/GB scholarly norms. If a venue family is declared, follow
  `venue_family_hard_packs.md` for that family only.

## Table Rules

- Use `booktabs` and `longtable`.
- Use three-line tables by default: top rule, mid rule, bottom rule.
- Avoid full grid borders unless a venue template requires them.
- For wide Markdown pipe tables:
  - Reduce `\tabcolsep` to 2-4 pt.
  - Apply `\footnotesize` or `\small` at `longtable` start.
  - Use breakable monospace settings for code-like method names.
  - Treat remaining overfull warnings from long identifiers as layout warnings,
    not content changes; do not silently rename methods to fit a column.
- Check that row and column counts are preserved after conversion.

## Formula Rules

- Preserve `$...$` and `$$...$$` math from Markdown.
- Load `amsmath` and `mathtools`.
- Keep displayed equations centered and separated from body text.
- Do not rewrite formulas during formatting; fix only escaping or LaTeX syntax
  needed for compilation.

## CJK And Mixed-Language Rules

- Use XeTeX-compatible CJK fonts. Prefer stable TTF/OTF fonts over variable TTC
  fonts when `xdvipdfmx` reports font-table failures.
- Pair a serif Latin body font with a serif CJK body font. A practical
  default is Times New Roman (or a metric-compatible Times family) for Latin,
  STIX Two Math for formulas when needed, and Noto Serif CJK SC/TC static OTF
  for Chinese. For Chinese-only technical reports that must avoid mixed Latin
  stacks, a single CJK serif family for both scripts is acceptable.
- Avoid CJK **sans-serif** fallback fonts for body text unless no serif CJK font
  is available.
- Use `xurl` for URL line breaking and a small monospace font for code tokens.
- When the scholar declared a `venue_family`, prefer that family's font/paper
  rules over this default (see `venue_family_hard_packs.md`).

## Minimal Build Pattern

```bash
python3 normalize_report.py
pandoc report.academic.md \
  --from=markdown+tex_math_dollars+pipe_tables+fenced_code_blocks+raw_html \
  --shift-heading-level-by=-1 \
  --pdf-engine=tectonic \
  --include-in-header=academic_pdf_header.tex \
  -o report.academic.pdf
```

## Final Checks

- `pdfinfo` succeeds and reports the expected page size.
- `pdftotext` extracts the title, table of contents, headings, and body text.
- At least one formula page and one table page are visually inspected from a
  rendered PNG preview.
- The build log contains no fatal LaTeX errors. Overfull warnings should be
  reviewed; long unbreakable identifiers may remain if changing them would alter
  reported method names.
