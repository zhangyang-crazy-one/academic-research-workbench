# Bounded integrity hashing (#150)

This Linux-only controlled benchmark compares the original full-file SHA-256
implementation with the shared 1 MiB streaming helper. It exercises isolated
32/512 MiB sparse-file hashing and the real `verify_staged_core` reader against
one retained ARW 0.2.0 stage. Every condition runs in three fresh Python
processes. File bytes are warm; directory metadata and background system load
are not controlled, and baseline always runs first. `tracemalloc` is enabled
in both conditions, so wall times are instrumented observations.

The baseline reconstructs the exact original hash expression from main
`a796c074a3aeec4601c80daa742f2e34bf526799` in the hashing aliases of the current
verifier. It changes only process-local callables; neither mode rewrites stage
files, inventories or receipts. The same stage passes all original verification
checks in each process and returns the same inventory, identity and wheel
digests. This is a controlled preflight comparison, not an installed CLI or MCP
startup benchmark and not a complete old/new release comparison.

## Measurements

Measured 2026-10-16 on Linux with Python 3.14.6. Values below
are process peak RSS, Python allocation peak, and median instrumented wall time.
The full per-run observations, source hashes and retained artifact digests are
in [measured-results.json](measured-results.json).

| Input | Method | RSS range (MiB) | Max traced peak (MiB) | Median seconds |
| --- | --- | ---: | ---: | ---: |
| 32MiB.bin | baseline | 49.8–50.0 | 32.00 | 0.025 |
| 32MiB.bin | stream | 20.4–20.4 | 2.13 | 0.013 |
| 512MiB.bin | baseline | 530.0–530.0 | 512.00 | 0.366 |
| 512MiB.bin | stream | 20.4–20.4 | 2.13 | 0.182 |
| retained-stage | baseline | 373.7–373.9 | 296.97 | 2.828 |
| retained-stage | stream | 87.0–87.3 | 14.69 | 2.453 |

The isolated hash returns the reference digest in every case. The regression
tests also enforce an allocation peak below 4 MiB for 32 and 512 MiB payloads
through the canonical, core-integrity and integration-lock entry points.

## Reproduce

From a checkout with Python dependencies installed:

```sh
.venv/bin/python examples/benchmarks/integrity-hashing/benchmark.py \
  --stage-root /absolute/path/to/an/assembled/arw-stage \
  --output build/benchmarks/integrity-hashing
```

Omit `--stage-root` to run isolated hashing only. A supplied stage must pass the
current original verifier; the benchmark never relaxes a failed gate. Temporary
sparse inputs are created exclusively and removed after measurement. Existing
similarly named inputs are not overwritten. The stage is read-only to this
script. Output `results.json` reports a failed run by process failure rather
than retaining partial successes as a complete report.

## Remaining issue scope

No check is deduplicated and no trust cache is introduced. Logical-read counts,
process-tree RSS/PSS, installed `version`/`route`/both MCP startup, idle usage and
mutation-safe snapshot reuse remain unmeasured or unimplemented. Issue #150
remains open for those follow-ups. This change does not assert stronger
concurrent-write detection than the original verification contracts.
