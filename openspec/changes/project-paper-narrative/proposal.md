# Project paper narrative selection

## Problem

ARS Phase 2 can produce an outline from a session-local interpretation of
paper type. A later agent, handoff, or resumed session can choose another
exposition, even when the author already selected a method. Vendored examples
also prescribe counts such as 3–5 sub-arguments and minimum paragraph lengths
that do not fit every contribution. A prompt reminder alone cannot prevent a
stale worker from replacing a newer project decision.

## Proposed change

Add a provider-neutral, project-scoped paper narrative record with a reasoned
first selection, append-only version history, current status, and explicit
author-approved changes. Bind paper runs and writing/agent operations to the
current version. ARS adapter guidance carries that version into Phase 2
Outline + Evidence Map, Phase 3 Argument Blueprint, and drafting, including
`ars-plan` and `ars-outline`. Non-paper runs remain outside this requirement.

The record selects argument order and evidentiary approach. It cannot freeze
facts, results, or conclusions. Route names are defaults for broad contribution
types, with a justified custom route. Six functions define a complete
argument, not six mandatory sections. A hypothesis can be absent and negative
results can be a valid final contribution.

## Scope

The canonical state lives in the project, with stable identity, hash-chained
events, version and digest checks, and read guards at provider-neutral runtime
boundaries. The change includes CLI commands, run binding, ARS adapter and user
documentation, and focused regression tests. It does not alter the vendored
upstream ARS source or require a model provider, plugin installation, or
manuscript upload.
