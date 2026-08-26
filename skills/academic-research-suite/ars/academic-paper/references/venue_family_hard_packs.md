# Venue Family Hard Packs (declared-only)

Load this file only when formatting, auditing camera-ready PDF/TeX, or when the scholar declares a `venue_family`. Do not load all packs into context by default — after the scholar picks one family, apply **only that family's** hard table.

## Why this exists

ARS already hard-gates integrity (citations, contamination, AI disclosure). It did **not** hard-gate venue layout. Agents then mixed “pretty report” styling (colored headings, single-column long reports) with “ACL/IEEE camera-ready” expectations. Venue rules differ; never collapse them into one generic academic look.

## Declared-only rule (keep)

- Scholar must pick `venue_family` explicitly, or accept `general` / `cn_tech_report`.
- Never infer family from a journal title string alone. Naming “NeurIPS / ACL / IEEE” as Target Journal does **not** auto-write the Venue Family row — ask once, then store the exact slug.
- Never invent page limits, word limits, or template versions from memory; if a numeric limit matters, ask or leave `NOT-CHECKED`.
- Official pack rows below are **pinned family norms**, not scraped live limits. When a conference year changes a number, ask the scholar to confirm.
- **Length / page-cap rows:** without a scholar-confirmed year + numeric cap, mark **`NOT-CHECKED`**. Do **not** FAIL a manuscript solely because it exceeds a remembered “typical 8/9 pages” figure.

## Audit / compliance answer contract

When auditing PDF/TeX or answering “is this camera-ready / which family?”, emit this skeleton (keep the exact slug tokens):

```markdown
## Venue Family
- Declared or recommended slug: `acl` | `neurips` | `icml` | `ieee_trans` | `acm` | `gb_cn_journal` | `cn_tech_report` | `general` | `undeclared`
- Source: scholar PCR | document self-ID | ask-once (never journal-name inference)

## Venue Family Compliance (`<slug>`)
| Hard row | Status | Evidence |
|----------|--------|----------|
| … | PASS / FAIL / NOT-CHECKED | … |

## Claims
- Camera-ready / submission-ready for `<slug>`: yes only if every hard row is PASS (no FAIL; NOT-CHECKED blocks the claim).
```

Use the **machine slug** (`cn_tech_report`), not a free paraphrase (“Chinese Technical Report”) as the PCR / compliance identity. Paraphrase may appear in prose, but the slug must appear in backticks once.

## Efficiency rule

1. Ask once for `venue_family` (intake Step 3b or formatter preflight).
2. Read **only** the matching subsection below.
3. Run that family's checklist; FAIL items block “camera-ready / submission-ready” claims.
4. If family is `general` or undeclared, do not claim ACL/IEEE compliance.

---

## Family index

| `venue_family` | Use when | Load subsection |
| ---------------- | ---------- | ----------------- |
| `acl` | ACL / EMNLP / NAACL / EACL / *ACL workshops using ACLPUB style | § ACL |
| `neurips` | NeurIPS | § NeurIPS |
| `icml` | ICML | § ICML |
| `ieee_trans` | IEEE Transactions / many IEEE journal camera-ready flows | § IEEE |
| `acm` | ACM CCS / CHI / similar `acmart` venues | § ACM |
| `gb_cn_journal` | Chinese journal / GB-oriented manuscript | § GB/CN journal |
| `cn_tech_report` | Chinese technical report / design baseline (not a conference submission) | § CN tech report |
| `general` | No venue; exploratory draft | § General |

PCR row: **Venue Family** = one of the values above (or row omitted ⇒ treat as undeclared/`general` for compliance claims).

---

## Shared hard norms (all submission families except free `general` drafts)

Apply these unless the family row explicitly overrides:

- Body and section/subsection headings: **black** (no decorative blue/teal heading colors).
- Do not rely on color alone in figures/tables; grayscale must remain readable.
- Figure/table captions are scholarly labels, not chat with the author.
- Do not claim “meets ACL/IEEE/…” unless that family was declared and its checklist passes.

| Shared layout gate | Hard expectation |
|--------------------|------------------|
| Float scheduling | Preserve callout/source order; do not place a barrier ahead of a pending starred two-column float. |
| Render audit | Compile, render every page, and inspect a contact sheet; compiler-only validation cannot support a camera-ready claim. |

Hyperlinks: ACL allows dark blue `#000099`. IEEE camera-ready often prefers black body links — follow the family row.

---

## ACL (`acl`)

Pinned to ACLPUB formatting norms (A4, two-column, Times Roman for Latin text).

| Item | Hard expectation |
| ------ | ------------------ |
| Template | Official ACL style files (`acl.sty` / ACLPUB), not a free-form `article` report skin |
| Paper | A4; two-column; ~2.5 cm margins |
| Length | Follow that year's CFP (typically long ~8 review / ~9 final content pages — **confirm year**) |
| Latin font | Times Roman (or Times New Roman / Computer Modern Roman if Times unavailable) |
| Headings | Bold **black**; prescribed sizes in ACL table |
| Abstract | English; keep within venue word guidance (~200 words common) |
| Figures | Caption below; `Figure N:` English scheme in English papers; color OK if grayscale-safe |
| Tables | Near first mention; caption above/as required by template |
| References | ACL BibTeX / natbib; prefer DOI or Anthology URL |
| Review mode | Review: anonymized + line numbers; Final: author block, usually no page numbers |
| Links | Dark blue `#000099`, not underlined/boxed |

**FAIL if:** single-column report layout sold as ACL camera-ready; colored section titles; missing ACL template; fabricated page limit.

---

## NeurIPS (`neurips`)

| Item | Hard expectation |
| ------ | ------------------ |
| Template | Official NeurIPS LaTeX style for that year |
| Layout | Style-file geometry (do not freestyle margins/fonts) |
| Length | Main body page cap per that year's CFP (**confirm year**) |
| Font | Style default (Times New Roman family typical) |
| Headings | Bold **black** via template |
| Figures | Color allowed; body + captions must read in B/W |
| References | Consistent style; BibTeX via template |
| Extra | Paper checklist / ethics blocks when required that year |

**FAIL if:** custom long single-column report claimed as NeurIPS-ready; heading recoloring; ignoring official style file.

---

## ICML (`icml`)

| Item | Hard expectation |
| ------ | ------------------ |
| Template | Official ICML style |
| Paper size | **US Letter** (not A4) unless that year explicitly says otherwise — **confirm** |
| Layout | Follow style file; do not invent dual templates |
| Headings | Template bold **black** |
| Figures | Prefer vector for plots; B/W-legible |
| Abstract | Short; follow that year's guidance |

**FAIL if:** A4 Chinese report layout claimed as ICML submission without template conversion.

---

## IEEE Transactions / journal (`ieee_trans`)

| Item | Hard expectation |
| ------ | ------------------ |
| Template | IEEE two-column Transactions/journal template |
| Font | Times / Times New Roman; embed fonts |
| Figure callouts | In text: `Fig.` + number; caption below figure |
| Table captions | Above tables |
| References | IEEE numeric `[1]`; author initials rules; complete bibliographic fields |
| Links | Prefer black for camera-ready body text |
| Authors | Affiliations, corresponding author, as required |

**FAIL if:** Chinese “图 1:” scheme left unchanged in an English IEEE submission; decorative heading colors; missing IEEE reference structure.

---

## ACM (`acm`)

| Item | Hard expectation |
| ------ | ------------------ |
| Template | `acmart` (correct document class option for the venue) |
| Metadata | CCS concepts / keywords when required |
| Headings | Template styling; **black** body/heads unless template says otherwise |
| References | ACM BibTeX style |
| Figures | Rights/permissions; AI-image policies per ACM + venue |

**FAIL if:** generic `article` class claimed as ACM camera-ready.

---

## Chinese journal / GB-oriented (`gb_cn_journal`)

Aligned with GB/T 7713.2 presentation spirit + GB/T 7714 references (journal may add house rules).

| Item | Hard expectation |
| ------ | ------------------ |
| Paper | A4 typical |
| Fonts | Headings 黑体-class; body 宋体-class (or CJK serif equivalent); **black** |
| Terms | First use: 中文全称（English full name, ABBR）；later Chinese-first |
| Figures | 图题 below; Chinese-first labels; editable/vector preferred for line art |
| Tables | 三线表; 表题 above |
| References | GB/T 7714 fields (type codes, dates, consistent punctuation) |
| Structure | Abstract + keywords + body + references; add COI/data/ethics if the journal requires |

**FAIL if:** English-primary body for a Chinese journal; colored decorative heads; bare English keywords only; non-7714 reference soup sold as national-standard compliant.

---

## Chinese technical report (`cn_tech_report`)

For design/architecture baselines (like Tow-Towers reports), **not** a substitute for conference templates.

| Item | Hard expectation |
| ------ | ------------------ |
| Paper | A4; single-column OK |
| Fonts | Unified CJK serif OK; Latin may share CJK serif to avoid mixed stacks; **black** heads/body |
| Terms | Chinese-first glossing as above |
| Figures | Chinese captions; mark generative schematics as 解释性示意图，非运行证据 |
| Tables | Three-line tables |
| References | Consistent; 7714 preferred but tech-report local packs allowed if labeled |
| Claims | May say “技术报告基线”; must **not** say “已符合 ACL/IEEE camera-ready” |

**FAIL if:** colored headings; claiming top-venue compliance without family switch + template.

---

## General (`general`)

- Use ARS defaults; keep headings black when emitting PDF.
- No venue-compliance badge.
- Still enforce integrity gates and manuscript-artifact boundary.

---

## Formatter preflight (minimal)

```
IF Venue Family declared:
  load only that subsection
  apply hard table to TeX/PDF/DOCX choices
  checklist: each hard row PASS/FAIL/NOT-CHECKED
  IF any FAIL: do not label output submission-ready for that family
ELSE:
  treat as general / ask once if user said "camera-ready" or named ACL/IEEE/…
```

## Intake prompt (one question)

> “投稿/排版族选哪个？`acl` / `neurips` / `icml` / `ieee_trans` / `acm` / `gb_cn_journal` / `cn_tech_report` / `general`。只记录你的选择，不从期刊名自动猜测。”
