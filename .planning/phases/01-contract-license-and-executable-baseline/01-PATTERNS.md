# Phase 1: Contract, License, and Executable Baseline - Pattern Map

**Mapped:** 2026-07-13
**Files analyzed:** 52 proposed paths or file families
**Analogs found:** 11 / 52
**Concrete analog files used:** 5

This is a greenfield runtime repository. The only close local implementation analogs are the Codex `plugin-creator` scaffold/validator and the supplied Paper4Master file-base build, launcher, and MCP configuration. Runtime authority, schema, confinement, licensing, evidence, and test behavior must follow `01-CONTEXT.md` and `01-RESEARCH.md`; they do not have trustworthy local code analogs.

## File Classification

### Plugin, package, runtime, and schemas

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `.python-version` | config | batch | None | none |
| `pyproject.toml` | config | batch | None | none |
| `uv.lock` | config | batch | None | none |
| `.codex-plugin/plugin.json` | config | request-response discovery | `plugin-creator/scripts/create_basic_plugin.py` | exact contract |
| `.mcp.json` | config | request-response / stdio | `Paper4Master/.mcp.json` | role + shape; unsafe values must change |
| `hooks/hooks.json` | config | event-driven | None; `plugin-creator` creates only the directory | none; host probe required |
| `skills/academic-research-workbench/SKILL.md` | route | request-response | `plugin-creator/scripts/validate_plugin.py` skill validation | contract-only |
| `src/arw/cli.py` | controller | request-response | `plugin-creator/scripts/validate_plugin.py` CLI | role-match |
| `src/arw/canonical.py` | utility | transform | None | none |
| `src/arw/models.py` | model | transform / validation | None | none |
| `src/arw/journal.py` | service | event-driven + file-I/O | None | none |
| `src/arw/evidence.py` | service | file-I/O / batch | None | none |
| `schemas/v1/run-manifest.schema.json` | config/model | transform / validation | None | none |
| `schemas/v1/event.schema.json` | config/model | event-driven / validation | None | none |
| `schemas/v1/route-result.schema.json` | config/model | request-response / validation | None | none |
| `schemas/v1/mcp-read-request.schema.json` | config/model | request-response / validation | None | none |
| `schemas/v1/mcp-read-result.schema.json` | config/model | request-response / validation | None | none |
| `schemas/v1/source-manifest.schema.json` | config/model | batch / validation | None | none |
| `schemas/v1/version-report.schema.json` | config/model | request-response / validation | None | none |

### Supply chain, licensing, and executable scripts

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `vendor/sources/ars/**` | config/vendor input | batch + file-I/O | None | none; materialized input |
| `vendor/sources/file-base/**` | config/vendor input | batch + file-I/O | None | none; materialized input |
| `vendor/patches/file-base/0001-file-base-server-name.patch` | config/migration input | batch / transform | Supplied Paper4Master patch named by its build wrapper | exact bytes to copy, not an implementation pattern |
| `vendor/source-manifest.json` | config/model | batch / validation | None | none |
| `vendor/LICENSES/**` | config/legal input | batch | None | none |
| `LICENSES/**` | config/legal output | batch | None | none |
| `THIRD_PARTY_NOTICES.md` | config/legal output | batch | None | none |
| `MODIFICATIONS.md` | config/legal output | batch | None | none |
| `supply-chain/use-distribution.json` | config/model | batch / validation | None | none |
| `scripts/verify-sources` | utility | batch + file-I/O | `Paper4Master/scripts/build-file-base-mcp` | partial role-match |
| `scripts/build-file-base` | utility | batch + file-I/O | `Paper4Master/scripts/build-file-base-mcp` | exact role; provenance logic must change |
| `scripts/file-base-mcp` | service launcher | streaming / stdio | `Paper4Master/scripts/file-base-mcp` | exact role; defaults must change |
| `scripts/stage-plugin` | utility | batch + file-I/O | `Paper4Master/scripts/build-file-base-mcp` | partial role-match |
| `scripts/smoke-staged-plugin` | utility | batch / request-response | None | none |
| `scripts/verify-phase-1` | utility | batch / event orchestration | `Paper4Master/scripts/build-file-base-mcp` | partial shell structure only |

### Tests and fixtures

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `tests/unit/test_canonical.py` | test | transform | None | none |
| `tests/schema/test_schema_drift.py` | test | batch / validation | None | none |
| `tests/schema/test_cross_language.py` | test | request-response / validation | None | none |
| `tests/integration/test_version_report.py` | test | request-response | None | none |
| `tests/integration/test_source_materialization.py` | test | batch + file-I/O | None | none |
| `tests/integration/test_digest_drift.py` | test | batch / transform | None | none |
| `tests/integration/test_license_gate.py` | test | batch / validation | None | none |
| `tests/integration/test_run_init.py` | test | event-driven + file-I/O | None | none |
| `tests/integration/test_journal_replay.py` | test | event-driven + file-I/O | None | none |
| `tests/integration/test_mcp_confinement.py` | test | request-response + file-I/O | None | none |
| `tests/staged/test_manifest_install.py` | test | batch / request-response | `plugin-creator/scripts/validate_plugin.py` | partial: validator under test |
| `tests/staged/test_skill_route.py` | test | request-response | None | none |
| `tests/staged/test_mcp_launcher.py` | test | streaming / request-response | Paper4Master launcher plus `.mcp.json` | partial baseline |
| `tests/staged/test_supply_chain_inventory.py` | test | batch / validation | None | none |
| `tests/staged/test_private_exclusions.py` | test | batch + file-I/O | None | none |
| `tests/fixtures/recovery/seed/**` | test fixture | event-driven + file-I/O | None | none |
| `tests/fixtures/confinement/**` | test fixture | request-response + file-I/O | None | none |
| `tests/fixtures/private-canaries/**` | test fixture | batch + file-I/O | None | none |

Generated `build/stage/**`, `build/marketplace/**`, `build/evidence/**`, and run roots are outputs, not checked-in authority. Their producers are classified above.

## Pattern Assignments

### `.codex-plugin/plugin.json` (config, request-response discovery)

**Analog:** `/home/zhangyangrui/.codex/skills/.system/plugin-creator/scripts/create_basic_plugin.py`

**Manifest shape to copy** (lines 58-77):

```python
payload: dict[str, Any] = {
    "name": plugin_name,
    "version": "0.1.0",
    "description": f"{display_name} plugin",
    "author": {"name": "Local developer"},
    "skills": "./skills/",
    "interface": {
        "displayName": display_name,
        "shortDescription": f"Use {display_name} in Codex.",
        "longDescription": f"{display_name} adds a local Codex plugin scaffold.",
        "developerName": "Local developer",
        "category": DEFAULT_CATEGORY,
        "capabilities": [],
        "defaultPrompt": f"Help me use {display_name}.",
    },
}
if with_mcp:
    payload["mcpServers"] = "./.mcp.json"
```

**Preserve:**

- Exact normalized name `academic-research-workbench`, strict semver, real description and `author.name`.
- Relative `"skills": "./skills/"` and `"mcpServers": "./.mcp.json"`.
- Required interface keys: `displayName`, `shortDescription`, `longDescription`, `developerName`, `category`, `capabilities`, and `defaultPrompt`.
- Validate the staged copy with `plugin-creator/scripts/validate_plugin.py`, not only the source tree.

**Deliberately replace/omit:**

- Do not copy the sample `MIT` license. Use the mixed-license `LicenseRef` value proven acceptable by the validator probe and preserve component licenses separately.
- Do not add top-level `hooks`: `validate_plugin.py` lines 93-105 do not include it in accepted manifest keys, and `plugin-json-spec.md` lines 205-217 states validation rejects it.
- Do not add `apps` because Phase 1 creates no `.app.json`.
- Do not leave scaffold publisher text or generic prompts.

**Validation/error pattern** (`validate_plugin.py` lines 34-43): collect all errors, print a stable list, and exit nonzero. The executor should preserve that behavior in the staged manifest test.

---

### `skills/academic-research-workbench/SKILL.md` (route, request-response)

**Analog:** `/home/zhangyangrui/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py`

This is a contract analog, not a workflow-content analog. Lines 414-453 establish the minimum routable skill shape:

```python
skill_md_path = skill_root / "SKILL.md"
if not contents.startswith("---\n"):
    errors.append(f"skill `{skill_root.name}` must start with YAML frontmatter")
...
skill_name = frontmatter.get("name")
description = frontmatter.get("description")
...
if disable_model_invocation not in (None, False):
    errors.append(
        f"skill `{skill_root.name}` frontmatter field `disable-model-invocation` must be false"
    )
```

**Preserve:** YAML frontmatter with non-empty `name` and `description`; keep model invocation enabled. The body should be thin and route to the Python control plane, returning a schema-valid ARS workflow family and execution mode.

**Do not infer:** plugin-native custom-agent registration, full ARS orchestration, or experiment execution. Those are unproven/deferred.

---

### `.mcp.json` (config, stdio request-response)

**Analog:** `/home/zhangyangrui/orca/projects/Paper4Master/.mcp.json`

**Object shape to preserve** (lines 1-12):

```json
{
  "mcpServers": {
    "file-base": {
      "command": ".../scripts/file-base-mcp",
      "env": {
        "CBM_ALLOWED_ROOT": "...",
        "CBM_CACHE_DIR": "...",
        "CBM_LOG_LEVEL": "warn"
      }
    }
  }
}
```

Plugin validation expects `.mcp.json` to contain only top-level `mcpServers`, with a non-empty server-name-to-object map (`plugin-creator/scripts/validate_plugin.py` lines 345-370).

**Preserve:** server name `file-base`, launcher command, explicit environment map, and warning-level logging.

**Deliberately replace:**

- Paper4Master line 4 is an absolute developer path. The workbench must use the staged/cache-local launcher behavior proven by an installed-package canary.
- Paper4Master lines 6-7 hard-code source-project allowed root/cache. Phase 1 must inject repository-owned fixture roots and a disposable cache, never a developer project or home path.
- The environment selects capabilities; it is not the security implementation. Path, symlink, sensitive-name, and budget enforcement remains inside the MCP process.

---

### `hooks/hooks.json` (config, event-driven)

**Analog:** none.

`plugin-creator` can create a `hooks/` directory but supplies no valid hook stub, and its current plugin manifest validator rejects a top-level `hooks` field. Create only a companion file that passes the supported host contract discovered by the Phase 1 hook canary. Hooks must remain observational/no-op and must never write accepted state. If the host contract cannot be proven, preserve the raw failed probe and do not invent a schema.

---

### `src/arw/cli.py` (controller, request-response)

**Analog:** `/home/zhangyangrui/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py`

**CLI shell pattern** (lines 28-43):

```python
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a local Codex plugin.")
    parser.add_argument("plugin_path", help="Path to the plugin root directory")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plugin_root = Path(args.plugin_path).expanduser().resolve()
    errors = validate_plugin(plugin_root)
    if errors:
        ...
        raise SystemExit(1)
```

**Copy:** standard-library `argparse`, `pathlib.Path`, a small `main()`, explicit exit status, and delegation into testable functions.

**Extend for this phase:** subcommands `route`, `init`, `append`, `replay`, `version`, and `doctor`; JSON stdout for machine surfaces; diagnostics on stderr; no mutable checkout queries in `version`. There is no local analog for typed runtime errors or sole-writer mutation, so implement those from the checked-in schemas and research contract.

---

### `src/arw/canonical.py`, `models.py`, `journal.py`, and `evidence.py`

**Analog:** none.

Use the Phase 1 contract directly:

- `models.py`: Pydantic `ConfigDict(strict=True, extra="forbid")`, explicit schema-version literals, constrained IDs/hashes/relative paths, and a discriminated event union containing only `run.initialized` and `baseline.probe_recorded`.
- `canonical.py`: one canonical UTF-8 JSON serialization with `sort_keys=True`, compact separators, `ensure_ascii=False`, `allow_nan=False`, and exactly one trailing newline. Compute SHA-256 excluding `event_sha256` over the exact bytes later appended.
- `journal.py`: lock, replay/validate tail and revision, compare expected revision, append one complete line, flush, `fsync`, release. The first `prev_event_sha256` is 64 zeroes. A derived projection is never required for replay.
- `evidence.py`: preserve argv, relative working directory, allowlisted environment keys, timestamps, versions, stdout/stderr, exit status, and concise machine verdict. Never dump the full environment.

No authentication pattern applies in Phase 1. Local process access and explicit allowed-root capabilities are the only access-control boundary.

---

### `schemas/v1/*.schema.json` (models/config, validation)

**Analog:** none.

All seven schemas are generated from strict models, checked in, and independently validated as Draft 2020-12. Preserve the research split rather than combining unrelated contracts:

- `run-manifest.schema.json`
- `event.schema.json`
- `route-result.schema.json`
- `mcp-read-request.schema.json`
- `mcp-read-result.schema.json`
- `source-manifest.schema.json`
- `version-report.schema.json`

The MCP request/result union must remain fixture-sized: relative path, allowed-root capability identifier, `max_bytes`, and either success content or a typed denial with no content. The independent validator signature from research is:

```python
jsonschema.Draft202012Validator.check_schema(schema)
jsonschema.Draft202012Validator(schema).validate(payload)
```

Do not add production indexing/search schemas in Phase 1.

---

### `scripts/build-file-base` (utility, batch/file-I-O)

**Analog:** `/home/zhangyangrui/orca/projects/Paper4Master/scripts/build-file-base-mcp`

**Shell and path pattern to copy** (lines 1-9, 27-31):

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
...
make -C "$CBM_SRC" -f Makefile.cbm cbm
mkdir -p "$LOCAL_BIN_DIR"
cp "$UPSTREAM_BIN" "$LOCAL_BIN"
chmod +x "$LOCAL_BIN"
```

**Copy:** strict shell mode, launcher-relative project discovery, explicit source/binary variables, upstream Make target, deterministic destination, executable bit, and actionable nonzero failures.

**Replace:**

- Lines 5-6 assume mutable `.external` source and a non-numbered patch path.
- Lines 17-25 use marker `grep` checks and patch a checkout in place. Replace with exact revision/tree digest verification, ordered patch digest verification, clean temporary materialization, `git apply --check`, `git apply`, and post-patch/binary digests.
- Lines 12-13 recommend a runtime network clone. Release/stage builds must use materialized checked-in inputs and work offline.
- Never mutate `vendor/sources/file-base/**` during the build.

---

### `scripts/file-base-mcp` (service launcher, stdio streaming)

**Analog:** `/home/zhangyangrui/orca/projects/Paper4Master/scripts/file-base-mcp`

**Launcher pattern to copy** (lines 1-10, 17):

```bash
#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CBM_BIN="$PROJECT_ROOT/.file-base/bin/file-base"

if [[ ! -x "$CBM_BIN" ]]; then
  echo "file-base MCP binary is missing: $CBM_BIN" >&2
  exit 127
fi

exec "$CBM_BIN" "$@"
```

**Copy:** stable script-relative binary resolution, executable preflight, stderr diagnostics, exit `127` for missing executable, and `exec` so stdio/signals/exit status belong to the MCP process.

**Replace:** Paper4Master lines 13-15 default allowed root and cache to the source project. The staged launcher must require or derive only installed fixture/capability configuration and a disposable cache. It must not silently grant the plugin root or user home as an allowed read root.

---

### `scripts/verify-sources`, `stage-plugin`, and `verify-phase-1`

**Analog:** Paper4Master build wrapper for shell mechanics only.

Use `#!/usr/bin/env bash`, `set -euo pipefail`, script-relative root resolution, explicit paths, and nonzero failures. Do not copy its mutable checkout, marker grep, or network-clone behavior.

- `verify-sources`: verify revision, pre/post-patch tree, patch order/hash, license hashes, lock hash, and expected artifacts.
- `stage-plugin`: assemble from a positive allowlist. Never copy the repository wholesale and delete forbidden files afterward.
- `verify-phase-1`: orchestrate clean materialize/build/stage, tests, install canaries, runtime/MCP probes, and evidence summary while preserving each command's raw output.

`scripts/smoke-staged-plugin` has no local code analog. It must use an isolated repo-owned marketplace and isolated `HOME`/`CODEX_HOME`, install the exact stage, start a fresh Codex execution, and fail on any source-checkout/home path in captured commands.

---

### Vendor, source manifest, licenses, and release classification

**Analog:** none, except the named Paper4Master patch is copied byte-for-byte as ordered patch `0001`.

Required deliberate behavior:

- Pin file-base revision `ee68144af5453addda995a27cce8142999f318fb` and patch SHA-256 `dd6022c69819804db015019058feaecebf0ee9c31e5cc55eb8bad6b47003da1a`.
- Record ARS adapter `0.1.19`, source revision `c22c17eed8a5753aa60681be9734919f2e2f5b42`, experiment-agent revision `9b063fa895eaf1f63ac99ac03f924f8d31aa8d26`, and exact materialized tree digests.
- Keep CC BY-NC 4.0 ARS/experiment-agent and MIT file-base identities separate in `vendor/source-manifest.json`, `LICENSES/`, notices, modifications, and SBOM references.
- `supply-chain/use-distribution.json` defaults release qualification to `BLOCKED` when classification or permission is missing. This may coexist with a technical `PASS`.
- Stage component-specific license files; do not represent the collective plugin as simply MIT.

The source manifest record needs stable component ID, version, upstream URL, revision, deterministic tree/archive digest, staged paths, ordered patches, license IDs/file digests, modification notice, third-party notice, lock/SBOM reference, and use/distribution decision reference.

---

### Tests and fixtures

**Analog:** no test suite exists in the target repository or supplied analog sources.

Use the exact responsibilities below rather than deriving tests from implementation details:

| Test/Fixture | Pattern to implement |
|---|---|
| `tests/unit/test_canonical.py` | Fixed IDs/timestamps produce byte-identical canonical lines and hashes; reject NaN/coercion/extra fields. |
| `tests/schema/test_schema_drift.py` | Generate schemas and fail on checked-in diff. |
| `tests/schema/test_cross_language.py` | Independently validate Python fixtures and C/MCP responses with `Draft202012Validator`. |
| `tests/integration/test_version_report.py` | Assert plugin/runtime/ARS/file-base/patch/schema/platform identity comes from build metadata. |
| `test_source_materialization.py` / `test_digest_drift.py` | Rebuild clean inputs; mutate each source/patch/lock/artifact digest class and require failure. |
| `test_license_gate.py` | Unknown or unsatisfied classification yields release `BLOCKED` while technical checks can pass. |
| `test_run_init.py` | Init writes strict run manifest plus first `run.initialized` event. |
| `test_journal_replay.py` | Test lock contention, sequence/hash/revision chain, SIGKILL after journal `fsync`, replay, and no duplicate append. |
| `test_mcp_confinement.py` | Exercise traversal, absolute path, symlink escape, unconfigured root, sensitive path, over-budget, and one bounded valid read; assert no denied secret bytes anywhere. |
| `test_manifest_install.py` | Validate the staged tree with plugin-creator, then install from isolated marketplace. |
| `test_skill_route.py` | Fresh installed Codex invocation returns a declared ARS workflow family/mode. |
| `test_mcp_launcher.py` | Preserve raw result of staged-relative launch canary; reject source absolute paths. |
| `test_supply_chain_inventory.py` | Assert licenses, notices, modifications, SBOM, source/build manifests, and digests are staged. |
| `test_private_exclusions.py` | Assert papers, extracted text, runs, credentials, indexes, and private canaries are absent from stage. |

Recovery fixtures use fixed IDs, fixed UTC timestamps, immutable input, workflow family/mode, and capabilities. Confinement fixtures must include CJK and LaTeX success content, oversized content, `.env`, an escaping symlink, an unconfigured second root, and an outside secret canary. Windows junction behavior remains unclaimed in the Linux-only Phase 1 baseline.

## Shared Patterns

### Paths and staged execution

**Sources:** Paper4Master scripts lines 4-9; Phase 1 contract.

Resolve repository/install locations from the launcher or script itself. Never embed Paper4Master, Examination, a developer home, or the source checkout in staged files. All install, route, launcher, runtime, and MCP tests run against the exact staged/installed bytes.

### Validation

**Source:** `plugin-creator/scripts/validate_plugin.py` and checked-in Draft 2020-12 schemas.

Use the plugin validator for plugin packaging and independent `jsonschema` validation for runtime/MCP contracts. Validation errors must be complete, machine-observable, and nonzero; no `[TODO: ...]` placeholders or permissive unknown fields.

### Error handling and process behavior

**Sources:** `plugin-creator/scripts/validate_plugin.py` lines 34-43; Paper4Master launcher lines 7-17.

- CLI/build failures return nonzero and place diagnostics on stderr.
- JSON success/denial payloads remain parseable on stdout.
- Shell scripts use `set -euo pipefail`.
- Launchers use `exec` for signal and exit-code fidelity.
- Typed MCP denials contain no content.
- Every probe records raw stdout, stderr, exit/signal, command metadata, and a concise verdict.

### Authentication and authorization

There is no authentication surface in Phase 1. Do not add remote identity/session machinery. Authorization is limited to explicit allowed-root capability configuration plus MCP-internal enforcement; hooks and shell wrappers are not the boundary.

### Canonical authority

Only the short-lived Python CLI may append accepted state. Hooks, workers, SQLite, indexes, transcripts, logs, and evidence summaries are projections or observations. Canonical events are deterministic, sequence ordered, revision checked, hash chained, locked, and `fsync`ed.

### Supply-chain and legal verdicts

Clean materialization and digest verification precede staging. Staging is allowlist-based. Technical qualification and release qualification are separate fields: unresolved CC BY-NC use/distribution is evidence-producing `BLOCKED`, not an omitted or falsified gate.

## No Analog Found

The planner should use `01-RESEARCH.md` contracts and tests for these groups rather than copy nearby code:

| File Group | Role | Data Flow | Reason |
|---|---|---|---|
| `.python-version`, `pyproject.toml`, `uv.lock` | config | batch | Target has no Python package baseline. |
| `hooks/hooks.json` | config | event-driven | Supplied plugin scaffold has no supported stub; host contract must be probed. |
| `canonical.py`, `models.py`, `journal.py`, `evidence.py` | utility/model/service | transform, event-driven, file-I/O | No local sole-writer/hash-chain/evidence implementation exists. |
| `schemas/v1/*.schema.json` | model/config | validation | No checked-in cross-language schemas exist. |
| `vendor/source-manifest.json`, license/notice/classification files | config/model | batch | Paper4Master wrapper does not implement digest-complete provenance or mixed-license qualification. |
| `scripts/smoke-staged-plugin` | utility | batch / request-response | No installed isolated-marketplace smoke runner exists. |
| All unit/schema/integration tests except validator reuse | test | mixed | Neither supplied analog includes a reusable test suite for these contracts. |
| Recovery, confinement, and private-canary fixtures | test fixture | file-I/O | Must be designed from Phase 1 requirements. |
| MCP-internal confinement changes under vendored file-base | service | request-response + file-I/O | Supplied wrapper/env configuration is not an enforcement implementation; no reliable analog was inspected. |

## Metadata

**Analog search scope:** target repository root; `/home/zhangyangrui/.codex/skills/.system/plugin-creator`; and only the supplied Paper4Master build launcher/config files. No unrelated repositories were scanned.

**Target repository state:** greenfield runtime; only `AGENTS.md`, planning artifacts, and one architecture document currently exist.

**Concrete analog files scanned:**

1. `plugin-creator/scripts/create_basic_plugin.py`
2. `plugin-creator/scripts/validate_plugin.py`
3. `Paper4Master/scripts/build-file-base-mcp`
4. `Paper4Master/scripts/file-base-mcp`
5. `Paper4Master/.mcp.json`

**Contract references read:** plugin-creator `SKILL.md`, `plugin-json-spec.md`, `installing-and-updating.md`, project `AGENTS.md`, `01-CONTEXT.md`, and `01-RESEARCH.md`.

**Pattern extraction date:** 2026-07-13
