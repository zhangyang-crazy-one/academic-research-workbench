# Modifications and Source Partitioning

Academic Research Workbench preserves each upstream source identity and records local changes as ordered, digest-bound patch inputs.

## academic-research-skills

- Upstream revision: `c22c17eed8a5753aa60681be9734919f2e2f5b42`
- Adapter version: `0.1.19`
- Materialized source: `vendor/sources/academic-research-skills`
- Local source modifications: none; the snapshot is bundled unchanged.
- License: CC BY-NC 4.0. Attribution and modification-marking duties remain in force.

## experiment-agent

- Upstream revision: `9b063fa895eaf1f63ac99ac03f924f8d31aa8d26`
- Materialized source: `vendor/sources/experiment-agent`
- Local source modifications: none; the snapshot is bundled unchanged.
- License: CC BY-NC 4.0. Attribution and modification-marking duties remain in force.

## file-base

- Upstream revision: `ee68144af5453addda995a27cce8142999f318fb`
- Materialized source: `vendor/sources/file-base`
- License: MIT, with the preserved generated third-party notices for bundled dependencies.
- Ordered patch 0001: `vendor/patches/file-base/0001-file-base-server-name.patch`
- Patch SHA-256: `dd6022c69819804db015019058feaecebf0ee9c31e5cc55eb8bad6b47003da1a`
- Effect: applies the existing server-name/file-discovery integration patch without rewriting the upstream legal tooling.

The machine-readable source manifest is authoritative for exact tree, patch, artifact, and legal-input digests. Later patches must be appended in order and must update this document, the manifest, generated notices, and the SBOM.
