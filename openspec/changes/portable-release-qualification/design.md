## Context

The owner supersedes previous formal-release instructions tying release to three fresh Codex homes, six paid calls and an exact host installation. ARW already has a host-independent core integrity boundary.

## Goals / Non-Goals

Goals: permissive platform compatibility, authentic package-install and lifecycle checks, transferable receipts. Runtime authentication, scientific admission and original publication-authority policy are unchanged.

## Decisions

Add a distinct `arw.release-qualification.v1` profile with a closed command plan: ordinary stage validation and a stdlib installed-core probe. The latter executes the candidate launcher from a separate working directory and private fresh HOME, checking core integrity, bounded file inspection, initialization, status and journal replay. It uses no model platform. Record Python/platform information as observations, never as an exact release tuple.

The default prepare-qualified-stage uses this profile when no explicit platform-lock inputs are selected. Explicit legacy inputs still invoke the historical platform diagnostic. candidate-bundle, check-release-candidate and the offline evidence consumer select the new reader by its receipt filename and reject mixed profiles. Original CI artifact hashes/source commit and owner OIDC authority remain authoritative.

Installed-stage identity binds each regular file's relative path, content digest and executable permission bits. A newly generated transfer manifest cannot admit a permission change made after qualification. The producer and private core probe explicitly pass their running interpreter through ARW_BUILD_PYTHON / ARW_PYTHON; the launcher retains its minimum compatibility check without depending on interpreter discovery on PATH. Authentication variables remain excluded.

## Risks / Trade-offs

Provider-internal behavior and native plugin trust are deployment concerns; core package verification does not claim live qualification of all platforms. Exact candidate hashes preserve provenance without imposing exact tool versions. Stream receipts attest observed local execution; independent CI signatures and owner release authority remain required for publication.

## Migration Plan

Use the generic qualification root with existing candidate-bundle --qualification-root and unchanged release workflows. Old strict scripts remain optional diagnostics. No historical PASS/BLOCKED record is modified.
