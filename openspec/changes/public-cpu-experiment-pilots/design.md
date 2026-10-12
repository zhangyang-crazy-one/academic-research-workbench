## Context

The evaluator is deliberately offline; parent provenance admission must not execute arbitrary artifacts. The owner authorized these CPU pilots as development work. Execution is a separately invoked, bounded local Python process with public, inspected code.

## Goals / Non-Goals

Retain actual execution measurements and immutable results for three mathematical mini-experiments. Do not establish scientific validity, controlled_execution qualification, statistical significance, historical pre-data-collection timing or publication-level benchmark accuracy.

## Decisions

Use composite trapezoid integration of x², central finite differences for sin at zero, and seeded Monte Carlo area estimation of pi. All inputs are analytic/publicly generated and redistributable with the provided code. No external datasets or dependencies. Freeze before starting the runner; ingest its raw CSV and configuration digests with the existing parent authority API. Evaluate/replay via actual arw CLI processes. After a deliberately overstrict trapezoid v1 fails, freeze v2 using the same already accepted provenance and retain both results. Evidence proves only parent contract-before-provenance acceptance; runner timestamps are observations, not stronger authority.

## Risks / Trade-offs

Analytic convenience sample -> report scope. Floating differences across platforms -> tolerances and exact retained-byte replay. Cost billing absent -> unknown, not zero. Writing output twice -> refuse nonempty destination rather than overwrite evidence. Worker timeout -> preserve stdout/stderr and fail, never retry silently.
