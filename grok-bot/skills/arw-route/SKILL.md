---
name: arw-route
description: >
  Request an ARW route-equivalent from Grok Bot: CloudAgent
  `python -m arw.cli route --json` with explicit success criteria, or
  an advisory ARS workflow-file tree that does not invent families.
---

# arw-route

Two layers. Do not mix them.

- **Control-plane route:** `RouteResult` JSON from
  `python -m arw.cli route --json` (or staged `bin/arw route --json`).
  `workflow_family` is only `academic-pipeline`.
- **ARS workflow-file selection:** which bundled `WORKFLOW.md` to
  read. That table is not a `RouteResult` and must not be serialized
  as one.

Canonical source: `https://github.com/zhangyang-crazy-one/academic-research-workbench`.
Read the entire `grok-bot/GROK_BOT.md` before using this imported skill, from
the same resolved source commit. For one import, `arw-adapt` records the
repository URL and resolved commit SHA as import provenance. Load every
portable skill and referenced ARS file from that commit, and pair CLI output
only from that same commit. If a CloudAgent checkout supplies CLI output,
require `git rev-parse HEAD` to equal
the recorded SHA and `git status --porcelain` to be empty; otherwise do not
pair its CLI output with this skill import. The SHA identifies source bytes,
not a dependency or runtime compatibility pin. The parent accepts provenance
and controls state and gates.

## A. Authoritative CloudAgent route

Ask Cursor CloudAgent to use its **cloud VM checkout** of this
repository. Do not clone onto the user's machine. Do not install the
Codex plugin marketplace.

```bash
uv venv
uv pip install --python .venv/bin/python --editable . -r pyproject.toml
.venv/bin/python -m arw.cli route --json
```

Do **not** use checkout `./bin/arw route --json`. That launcher needs
staged `share/arw/wheels/` and fails closed with
`runtime-artifact-missing` on a source tree. Do not invent JSON after
that failure. Do not run `stage-plugin` / `qualify-codex-host` as a
Grok unlock.

### Success criteria

Succeed only if all are true:

- exit code `0`
- stdout is one JSON object
- required keys present: `schema_version`, `workflow_family`,
  `execution_mode`, `source_adapter_version`,
  `source_dependency_model`, `source_bundled`, `integration_status`,
  `integration_lock_sha256`, `release_qualification`, `reason_codes`,
  `experiment_execution`, `paper_ast_export`
- `schema_version` = `1.0.0`
- `workflow_family` = `academic-pipeline`
- `execution_mode` ∈ {`inline-role-prompts`, `blocked`}
- `source_adapter_version` = `0.1.27`
- `source_dependency_model` = `bundled-pinned-adapter`
- `source_bundled` = `true`
- `integration_status` ∈ {`PASS`, `BLOCKED`}
- `release_qualification` = `BLOCKED`
- `experiment_execution` = `disabled`
- `paper_ast_export` = `deferred-v2`
- `reason_codes` items, if any, ∈
  {`integration_lock_not_verified`, `integration_inputs_incomplete`,
  `integration_lock_invalid_or_drifted`}

Return the JSON **unchanged**. `BLOCKED` + `execution_mode: blocked`
is success of the command, not a cue to guess a family.
On any other plain-route outcome: report stderr/exit. No synthetic
`RouteResult` and no silent fallback that claims to be `route --json`.
Schema: `schemas/v1/route-result.schema.json`.

### Diagnostics are a separate contract

`python -m arw.cli route --json --diagnostics` writes an
`arw.integration-diagnostic.v1` object to **stdout**, not a `RouteResult`.
Its exit code is `0` for `status: PASS` and `65` for `status: BLOCKED`.
On exit `65`, parse and report stdout even if stderr is empty; do not discard
the diagnostic object or validate it against
`schemas/v1/route-result.schema.json`. Send the diagnostic status and layers
to the parent for gate decisions.

## B. Advisory workflow-file tree

Use only when the plain route command did not produce `RouteResult`, or when
the user only needs which ARS file to read. Say **advisory**. Read
`skills/academic-research-suite/SKILL.md` at the same source revision first;
its overrides take precedence over this summary. Do not add families.

| User intent | Read first |
| --- | --- |
| Broad paper/thesis/proposal/manuscript writing topic or tentative title without a clear, answerable research question | `skills/academic-research-suite/ars/deep-research/WORKFLOW.md` in `socratic` mode first |
| Literature, deep research, SLR, meta-analysis, fact-check, RQ refinement | `skills/academic-research-suite/ars/deep-research/WORKFLOW.md` |
| Writing, outline, abstract, revision, citations, venue layout | `skills/academic-research-suite/ars/academic-paper/WORKFLOW.md` |
| Peer review, editorial, calibration, re-review | `skills/academic-research-suite/ars/academic-paper-reviewer/WORKFLOW.md` |
| End-to-end pipeline / integrity gates | `skills/academic-research-suite/ars/academic-pipeline/WORKFLOW.md` |
| Experiment planning / protocols / stats interpretation | `skills/academic-research-suite/ars/experiment-agent/WORKFLOW.md` |
| Ledger / science workbench / paper AST | `skills/academic-research-suite/codex/references/science_workbench_mvp.md` then closest row above |

For the scoping override, ask 3–5 narrowing questions before outlining or
drafting. Apply it to natural language and `ars-*` aliases. Follow the source
router's exceptions for a clear research question, approved study frame,
data/results, literature matrix, draft, or an explicit request to skip scoping.
Spanning phases → `academic-pipeline` unless the user named one phase or the
scoping override applies.
If GitHub cannot fetch the file, stop and say so.
