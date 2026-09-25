---
name: arw-literature
description: >
  Literature and related-work triage using Academic Research Workbench
  bundled ARS files as read-only references when GitHub can fetch this
  repo. Never invent citations. Does not require local bin/arw.
---

# arw-literature

Portable Grok skill. Related-work and literature **triage**, not a
silent systematic review and not a `RouteResult`.

Bundled ARS stays in-repo. Point at it; do not copy the tree.

Canonical source: `https://github.com/zhangyang-crazy-one/academic-research-workbench`.
Read the entire `grok-bot/GROK_BOT.md` before using this imported skill, from
the same resolved source commit. For one import, `arw-adapt` records the
repository URL and resolved commit SHA as import provenance. Load every
portable skill and referenced ARS file from that commit, and pair CLI output
only from that same commit. If a CloudAgent checkout supplies CLI output,
require `git rev-parse HEAD` to equal
the recorded SHA and `git status --porcelain` to be empty; otherwise do not
pair its CLI output with this skill import. The SHA identifies source bytes,
not a dependency or runtime compatibility pin.

## References (read when GitHub allows)

| Need | Path |
| --- | --- |
| ARS router | `skills/academic-research-suite/SKILL.md` |
| Deep research / lit-review / SLR workflow | `skills/academic-research-suite/ars/deep-research/WORKFLOW.md` |
| Codex ARS route | `skills/academic-research-suite/SKILL.md` |
| Integrity / evidence-tier language | `docs/runtime/scientific-integrity.md` |
| Venue overlay (recheck official pages) | `skills/academic-research-suite/codex/references/annual_venue_profiles.md` |

If a path is unreadable, say `unavailable`. Do not fill gaps with a
remembered ARS policy as if it were the bundled file.

## Procedure

1. Name the question, inclusion intent, and what would count as
   enough for *this* turn (triage vs requested SLR).
2. Read `deep-research/WORKFLOW.md` before claiming a systematic
   method. A related-work sketch is not PRISMA.
3. Collect only sources you can point to: user-supplied files, GitHub
   fetches, or live search results with URLs/DOIs you actually saw.
4. For each item keep: bibliographic locator (DOI/arXiv/URL), what
   was verified vs inferred, and evidence access language from
   `docs/runtime/scientific-integrity.md`
   (`publicly_verified`, `locally_supplied`, `restricted`,
   `unavailable`, `human_review_required`). A local PDF is not public
   verification.
5. Never invent citations, quotes, page numbers, venues, or years.
   If search fails, return fewer items. Unverified names stay labeled
   unverified.
6. Do not write ledger events or call `bin/arw status`. GitHub-read
   skills are guidance, not run state.
7. STORM-style surveys need explicit user consent plus a CloudAgent
   that can actually run the optional pipeline. Output is pre-writing
   material, never canonical experiment evidence.

Codex `skills/academic-research-suite/SKILL.md` routes literature through the
bundled ARS workflow. Grok cannot take the installed `bin/arw` path. Read
the same bundled files; do not pretend the control plane ran.
