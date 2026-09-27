# Grok Bot adaptation for Academic Research Workbench

This folder is **Grok Bot consumption**, not a second Codex (or Claude)
plugin install. It is the ARW-side contract for:

- consumer Grok Bot `arw` (research partner)
- sibling Grok Bot `arw-adapt` (copies/imports the portable skills here)

Codex remains the native control-plane host. Grok does not install
`academic-research-workbench` from a plugin marketplace, does not run a
local `bin/arw` on the Grok box, and does not inherit a live file-base MCP
session. `arw-adapt` is not a Codex installer.

Canonical source: `https://github.com/zhangyang-crazy-one/academic-research-workbench`.
All repo paths in this file and the copied portable skills are relative to that
repository root, starting with `grok-bot/GROK_BOT.md`. When `arw-adapt` imports,
resolve the chosen GitHub ref to its full commit SHA once, record the repository
URL and resolved SHA as import provenance, and read every portable skill and
referenced ARS file from that same commit. A CloudAgent checkout used for the
same import must report the same `git rev-parse HEAD` before its CLI output is
paired with those skills. A later import may resolve a newer commit; the
recorded SHA identifies consumed source bytes, not an exact dependency or
runtime compatibility requirement. Parent orchestration owns acceptance of
that provenance and any state, retry, or gate decision; hooks only observe.

Intended use of this repository is personal, non-commercial academic
research. ARS-derived material stays under upstream CC BY-NC 4.0. This
adaptation does **not** relicense ARS content, convert it to MIT, or
authorize commercial use. See the repo-root `README.md`, `LICENSE`,
`LICENSES/`, and `MODIFICATIONS.md`.

## Integration boundary

| Surface | On Grok Bot `arw` today |
| --- | --- |
| GitHub read of this public repo (skills, docs, schemas) | Works, when GitHub tools can fetch the path |
| Cursor CloudAgent on a **cloud VM checkout** of this repo | Works for code/CLI that the VM can actually run |
| Portable `grok-bot/skills/*/SKILL.md` recipes | Works after `arw-adapt` (or a human) copies/imports them |
| User-configured MCP connectors | Works only if the user already attached them; never assume file-base |
| Codex plugin marketplace (`codex plugin marketplace add`, `codex plugin add`) | Does **not** work inside Grok Bot |
| Claude Code plugin packaging (`docs/runtime/claude-plugin.md`) | A different host. Not a Grok path |
| Local `bin/arw` on the Grok box | Does **not** exist. Do not tell the user to clone this repo onto their machine |
| Installed plugin file-base MCP (`list_files` / `read_file` / `search_files` / `get_outline` / `get_context`) | Not running unless the user separately configured an equivalent. Do not invent file-plane results |
| Qualified-plugin / tagged-release install | Unchanged and fail-closed. This folder does not unlock `release_qualification` |
| Host canary / integration-lock fabrication | Forbidden. Never invent lock bytes, canaries, or `integration_status: PASS` |

Do not claim Grok can run the Codex plugin, a qualified stage, or
`isolated_codex_exec` host parity.

## How `arw` should invoke ARW today

Use this order. Do not skip a failed authoritative step by silently
substituting a guessed route.

1. **Read, do not duplicate.** If GitHub can fetch this repo, treat
   bundled files as the source of workflow text:
   - Codex entry: `skills/academic-research-workbench/SKILL.md`
   - ARS router: `skills/academic-research-suite/SKILL.md`
   - ARS workflows: `skills/academic-research-suite/ars/*/WORKFLOW.md`
   - Capability stubs: `skills/{literature,evidence,audit,files,research}/SKILL.md`
   - Integrity: `docs/runtime/scientific-integrity.md`
   - Route JSON schema: `schemas/v1/route-result.schema.json`
   Do **not** copy the ARS tree into Grok-local storage as a second suite.
2. **Authoritative control-plane route** (when the user needs a real
   `route --json` result, or when workflow family / gating status
   matters): ask Cursor CloudAgent to run the recipe in
   [Authoritative CloudAgent route](#authoritative-cloudagent-route).
   Return that JSON **unchanged**.
3. **If CloudAgent/route JSON is unavailable:** use the
   [Advisory workflow-file tree](#advisory-workflow-file-tree) only to
   choose which bundled `WORKFLOW.md` to *read*. Label it advisory. Do
   **not** emit a synthetic `RouteResult`, invent a `workflow_family`,
   or claim `integration_status`.
4. **Literature / related-work:** follow
   `grok-bot/skills/arw-literature/SKILL.md`. Never invent citations.
5. **Evidence / files / ledger talk:** follow
   `grok-bot/skills/arw-evidence/SKILL.md`. GitHub-readable skills are
   guidance, not run state.

`arw-adapt` should import the portable skills under `grok-bot/skills/`
into `arw` and point operators at this file. It must not instruct a
user-machine `git clone` and must not wrap Codex marketplace commands
as if they ran on Grok.

## Authoritative CloudAgent route

Request a Cursor CloudAgent (or equivalent cloud VM) **on this
repository**. The checkout lives in the cloud agent environment. That is
not a user-machine clone and is not a Codex plugin install.

### Commands

Prefer the **source-checkout Python CLI**. A clean tree has no staged
wheels, so checkout `./bin/arw route --json` fails closed with
`runtime-artifact-missing`. That stderr is **not** a `RouteResult`. Do
not invent JSON to cover it.

```bash
# Cloud VM checkout of this repo. Python >= 3.13, uv >= 0.11.28.
uv venv
uv pip install --python .venv/bin/python --editable . -r pyproject.toml
.venv/bin/python -m arw.cli route --json
```

Optional diagnostics (still fail-closed; not a second family):

```bash
.venv/bin/python -m arw.cli route --json --diagnostics
```

These are separate output contracts. Plain `route --json` writes a
`RouteResult` to stdout and returns `0` for a valid route, including a
`BLOCKED` route. `route --json --diagnostics` writes an
`arw.integration-diagnostic.v1` object to stdout; it returns `0` for
`status: PASS` and `65` for `status: BLOCKED`. Parse the diagnostics stdout
even on exit `65`, including when stderr is empty. Never validate that object
as `RouteResult`, substitute it for a route, or discard it because stderr has
no text. Report the diagnostic status and layers to the parent for decisions.

`./bin/arw route --json` is valid **only** inside a staged plugin tree
that already contains `share/arw/wheels/` (see repo `README.md`
staging). A Grok CloudAgent on a source checkout should not run
`scripts/stage-plugin` / `scripts/qualify-codex-host` /
`scripts/prepare-qualified-stage` as a workaround: those are Codex host
qualification gates, not Grok unlocks.

STORM (`storm --topic …`) is opt-in, never the default route, and is
not canonical experiment evidence. `experiment_execution` on the route
contract is `disabled`. Do not present STORM or experiment execution as
enabled because Grok asked.

### Success criteria (no silent fallback)

The route command **succeeds** only when **all** of the following hold:

- process exit code is `0`
- stdout is one JSON object (pretty or compact)
- the object contains every required `RouteResult` field:

  `schema_version`, `workflow_family`, `execution_mode`,
  `source_adapter_version`, `source_dependency_model`, `source_bundled`,
  `integration_status`, `integration_lock_sha256`,
  `release_qualification`, `reason_codes`, `experiment_execution`,
  `paper_ast_export`

- constants match the installed contract (see
  `schemas/v1/route-result.schema.json` and
  `src/arw/kernel/policy/contracts.py`):
  - `schema_version` = `"1.0.0"`
  - `workflow_family` = `"academic-pipeline"` (the control plane emits
    this family only; do not add others)
  - `execution_mode` is `"inline-role-prompts"` or `"blocked"`
  - `source_adapter_version` = `"0.1.27"`
  - `source_dependency_model` = `"bundled-pinned-adapter"`
  - `source_bundled` = `true`
  - `integration_status` is `"PASS"` or `"BLOCKED"`
  - `release_qualification` = `"BLOCKED"`
  - `experiment_execution` = `"disabled"`
  - `paper_ast_export` = `"deferred-v2"`
  - `reason_codes` is an array whose items, if any, are only
    `integration_lock_not_verified`, `integration_inputs_incomplete`,
    or `integration_lock_invalid_or_drifted`

A `BLOCKED` `integration_status` with `execution_mode: "blocked"` is a
**valid** route. Return it unchanged. It is not permission to guess a
family, skip ARS files, or pretend qualification passed.

The command **fails** when stdout is missing, not JSON, missing a
required field, or the process is non-zero (including
`runtime-artifact-missing` from checkout `bin/arw`). Then:

- report the actual stderr/exit
- do **not** emit a hand-built JSON object
- do **not** treat the advisory workflow-file tree as `route --json`
- do **not** retry with Codex marketplace install instructions

## Advisory workflow-file tree

This tree summarizes the **ARS router** in
`skills/academic-research-suite/SKILL.md`. Read its current override rules
before using the table; those rules take precedence. It selects which bundled
workflow file to read. It is **not** `bin/arw route --json` and does
**not** invent control-plane families.

If GitHub cannot fetch a path, say so. Do not reconstruct ARS policy
from memory as if it were the bundled file.

| User intent | Read first (repo path) |
| --- | --- |
| Broad paper/thesis/proposal/manuscript writing topic or tentative title without a clear, answerable research question | `skills/academic-research-suite/ars/deep-research/WORKFLOW.md` in `socratic` mode first |
| Deep research, literature review, systematic review, meta-analysis, fact-checking, research-question refinement | `skills/academic-research-suite/ars/deep-research/WORKFLOW.md` |
| Academic paper writing, outline, abstract, revision, citation formatting, AI disclosure, figures/tables, venue-family layout | `skills/academic-research-suite/ars/academic-paper/WORKFLOW.md` |
| Paper review, peer-review simulation, editorial decision, calibration, re-review | `skills/academic-research-suite/ars/academic-paper-reviewer/WORKFLOW.md` |
| End-to-end research-to-paper pipeline, integrity gates, staged review/revision | `skills/academic-research-suite/ars/academic-pipeline/WORKFLOW.md` |
| Experiment planning, human-study protocol, statistical interpretation, reproducibility planning | `skills/academic-research-suite/ars/experiment-agent/WORKFLOW.md` |
| Auditable science workbench, run ledger, paper AST/XML, semantic claims | `skills/academic-research-suite/codex/references/science_workbench_mvp.md` first, then the closest workflow above |

For that scoping override, ask 3–5 narrowing questions before outlining or
drafting. It applies to natural language and `ars-*` aliases. Follow the source
router's exceptions when the user has a clear research question, approved
study frame, data/results, literature matrix, or draft, or explicitly asks to
skip scoping. If the request spans multiple workflows, start with
`ars/academic-pipeline/WORKFLOW.md` unless the user clearly asked for
one phase or the scoping override applies.

Venue, deadline, and template questions still require the academic-paper
workflow plus a live check of official venue pages.
`skills/academic-research-suite/codex/references/annual_venue_profiles.*`
is editorial overlay, not an official deadline authority.

## Portable skills

| Path | Role |
| --- | --- |
| `grok-bot/skills/arw/SKILL.md` | Consumer bot `arw`: research partner entry |
| `grok-bot/skills/arw-route/SKILL.md` | CloudAgent `route --json` recipe + advisory tree |
| `grok-bot/skills/arw-literature/SKILL.md` | Literature / related-work triage |
| `grok-bot/skills/arw-evidence/SKILL.md` | Citation, ledger, and file-plane hygiene |

Copy those files. Do not vendor `skills/academic-research-suite/ars/`.

## What this folder does not change

- Positive-allowlist staging (`scripts/stage-plugin`) does not ship
  `grok-bot/`. Codex/Claude plugin payloads stay unchanged.
- Qualification and release gates stay fail-closed.
  `release_qualification` remains `BLOCKED` until the retained CC BY-NC
  intended-use, distribution, accountable-approval, and permission
  evidence is resolved. A README or Grok skill does not turn an
  unqualified stage into a release artifact.
- Science Workbench paper AST/export remains deferred-v2.
