# Third-Party Source Materialization

`vendor/sources/` is intentionally ignored by Git. It contains complete
third-party source snapshots and generated parser assets, which exceed 1 GiB
and are not first-party plugin code.

Before a source build or legal verification, run:

```bash
./scripts/materialize-sources
```

The command fetches the exact commits recorded in `source-manifest.json`,
checks their Git-tree and content-tree hashes, and atomically creates the local
`vendor/sources/` work area. It must run online. Subsequent
`scripts/offline-exec` build and verification steps consume that local copy.

Do not add `vendor/sources/` back to Git. Commit source-manifest changes,
patches, license notices, and SBOM updates instead.
