# Phase 7: Installed E2E Recovery and Release Qualification - Discussion Log

> **Audit trail only.** Decisions are captured in `07-CONTEXT.md`.

**Date:** 2026-07-16
**Phase:** 7-installed-e2e-recovery-and-release-qualification
**Areas discussed:** Representative E2E journey, Recovery fault-injection matrix, Install and compatibility matrix, Evidence and resource boundary

## Representative E2E journey

| Option | Description | Selected |
|--------|-------------|----------|
| Extend Phase 6 fixture | Reuse canonical scientific evidence and add installed E2E/recovery stages | ✓ |
| Independent fixture | Create a separate Phase 7 corpus | |
| Complete ARS workflow | Run every ARS intermediate in the fixture | |

**User's choice:** Extend Phase 6 fixture.
**Notes:** ARS is invoked through a real external exact adapter smoke using deterministic local fixtures and networking disabled. The current local Codex ARS adapter tree is the exact integration input; its local reshaping is preserved, but it is not bundled into the ARW stage or auto-tracked as latest.

## Recovery fault-injection matrix

| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic boundary matrix | Stable fault IDs at write/fsync/lock/host boundaries | ✓ |
| Property-based random injection | Hypothesis-driven random fault positions | |
| Manual scenarios | Small hand-selected set | |

**User's choice:** Deterministic boundary matrix, then proceed with recommended defaults.
**Notes:** Parent replay classifies tail versus middle-chain damage; sidecar evidence is parent-owned; scenarios run serially in independent roots.

## Install and compatibility matrix

| Option | Description | Selected |
|--------|-------------|----------|
| Exact current host baseline | Codex CLI 0.144.4 and retained tuple are the only technical PASS baseline | ✓ |
| Broad version range | Qualify multiple moving CLI versions | |
| Best-effort compatibility | Allow degraded/unknown versions | |

**User's choice:** Recommended defaults for all remaining questions.
**Notes:** Local marketplace, hidden source checkout, offline network, fresh homes, explicit `ARW_ARS_ROOT`, layered MCP/CLI/hook/stage gates.

## Evidence and resource boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Bounded evidence bundle | Canonical/sidecar hashes and redacted summaries only | ✓ |
| Full logs and payloads | Retain complete transcripts/intermediates | |
| Final verdict only | Keep no replay inputs | |

**User's choice:** Recommended defaults for all remaining questions.
**Notes:** Serial repo-local temporary roots prevent memory spikes; technical PASS and release BLOCKED remain independent.

## the agent's Discretion

- Exact fixture/fault IDs, wrappers, unsupported-version report format, and
  evidence directory names within the locked boundaries.

## Deferred Ideas

- Separately publishing an ARS fork or automatically tracking latest ARS.
- Bundling ARS workflows into the ARW stage.

