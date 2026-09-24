---
name: arw-evidence
description: >
  Fail-closed citation, ledger, and file-plane hygiene for Grok Bot
  arw. Read-only guidance from ARW evidence/audit/files skills. Never
  invent citations or run-state. Does not assume file-base MCP.
---

# arw-evidence

Portable Grok skill. Guidance only. It does not accept artifacts,
append the ledger, or start MCP.

## Canonical vs disposable

- The append-only ledger is the only canonical run state
  (`skills/audit/SKILL.md`, `docs/runtime/scientific-integrity.md`).
- File-base indexes, graphs, and SQLite projections are disposable.
- GitHub-readable skill text is **not** a run. Do not quote it as
  `arw status` output.

## Citations and claims

- Never invent citations, DOIs, quotes, or statistics.
- Never invent ledger events, artifact digests, passports, or human
  approvals.
- If you did not retrieve a source this turn, label it unverified or
  omit it.
- Imported experiment numbers are `external_only`. They are not ARW
  reproduction. Controlled execution is `disabled` on the route
  contract unless a separately qualified adapter exists — Grok is not
  that adapter.

## File plane

Installed MCP, when a parent has configured it, exposes only
`list_files`, `read_file`, `search_files`, `get_outline`, and
`get_context` under one registered root
(`skills/files/SKILL.md`, `docs/runtime/files-first-data-plane.md`).

On Grok:

- Do not assume that MCP is running.
- Do not invent file-plane results, outlines, or context windows.
- Do not crawl, extract, rebuild, repair, or broaden a root because
  the user asked a question. Stale or missing bytes → ask for an
  explicit parent sync or a user-supplied file. Do not "fix" it.

## Read-only pointers

| Topic | Path |
| --- | --- |
| Evidence access | `skills/evidence/SKILL.md` |
| Audit / ledger | `skills/audit/SKILL.md` |
| Provenance | `skills/provenance/SKILL.md` |
| Artifacts | `skills/artifact/SKILL.md` |
| Integrity overview | `docs/runtime/scientific-integrity.md` |
| Audit dossier bounds | `docs/runtime/audit-dossier.md` |

ARS-derived workflow text is CC BY-NC 4.0. Do not relicense it. Do not
treat this skill as release permission.
