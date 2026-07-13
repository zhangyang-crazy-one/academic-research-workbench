---
phase: 01-contract-license-and-executable-baseline
audited: 2026-07-13
register_authored_at_plan_time: true
threats_total: 31
threats_open: 0
status: secured
---

# Phase 1 Security Verification

## Threat Register

| Threats | Status | Verified mitigation evidence |
|---|---|---|
| T-01-SUB, T-01-PRIV, T-01-REP, T-01-SC | CLOSED | Frozen wheelhouse lock/hash checks in `bin/arw`; positive stage allowlist and inventory in `scripts/stage-plugin`; isolated installation evidence and private-path tests. |
| T-02-STALE, T-02-REP, T-02-ELEV, T-02-SC | CLOSED | Cachebuster/fresh-host route evidence; retained attempts; hooks are observational; runtime input is the audited wheelhouse. |
| T-03-SUB, T-03-LIC, T-03-NET, T-03-SC | CLOSED | Receipt-bound source manifest, pre-vendor native legal receipt, network namespace plus strace audit, ordered patch and artifact digests. |
| T-04-LIC, T-04-PRIV, T-04-SUB, T-04-SC | CLOSED | Two-stage legal gates, technical/release split, canary scans, no-symlink positive stage inventory, generated notices/SBOM provenance. |
| T-05-WRITER, T-05-CRASH, T-05-PRIV, T-05-SC | CLOSED | Strict models, lock/replay/hash/fsync writer, SIGKILL recovery fixture, allowlisted evidence capture, frozen runtime packages. |
| T-06-TRAV, T-06-SYM, T-06-DOS, T-06-MEM, T-06-STALE, T-06-SC | CLOSED | Native descriptor-relative no-follow patch, typed no-content ceiling denials, unchanged upstream suite, separate ASan+UBSan/TSan evidence, clean restage/install, source/patch/legal hashes. |
| T-07-SCHEMA, T-07-ID, T-07-REP, T-07-PRIV, T-07-SC | CLOSED | Independent Draft 2020-12 registry/tests, per-schema and aggregate packaged digest binding, identity-named raw dossier, stage/private scans, retained pre-vendor/native/legal evidence. |

## Security Audit 2026-07-13

| Metric | Count |
|---|---:|
| Threats found in plan-time register | 31 |
| Closed | 31 |
| Open | 0 |

The review discovered a packaged-schema binding gap while verifying T-07-SCHEMA/T-07-ID. It was fixed in `21d13fc` and covered by a staged schema-tampering test before this audit was recorded.

## Accepted Risks

- SUP-04 release authorization remains `BLOCKED` until accountable intended-use, distribution, approval, and compatible permission evidence is supplied. This is preserved as a release gate; it is not accepted as a production-release exception.

## Audit Trail

- 2026-07-13: Verified all Phase 1 plan-time threat mitigations against code, retained evidence, and test outputs. `threats_open: 0`.
