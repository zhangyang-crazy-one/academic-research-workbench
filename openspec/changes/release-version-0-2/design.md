## Context

Release metadata and runtime checks pin 0.1.0. The requested successor includes the reviewed claims and result-plot MVP.

## Goals / Non-Goals

Goals: coherent 0.2.0 metadata, real installed version probes, and strict legacy/current stage matching. Non-goals: rewriting historical artifacts, upstream/tool version changes or bypassing release authorization.

## Decisions

Explicitly admit retained 0.1.0 and new 0.2.0 runtime bindings. A stage's pyproject version must match its plugin base version and wheel METADATA, including only the existing qualified Codex suffix grammar. MCP reports the package version. Historical SBOM and receipt rows keep their original versions/hashes; new candidates receive fresh inventories.

## Risks / Trade-offs

Installed main editable metadata is 0.1.0 → use an isolated 0.2.0-installed development environment for launcher probes. Unknown future versions remain unqualified. Formal release remains gated on separate technical and independently signed authorization evidence.
