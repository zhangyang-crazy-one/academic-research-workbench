---
name: evidence
description: Evidence access and integrity for research artifacts — bounded, digest-pinned reads.
---

# evidence

Evidence access flows through the control plane's artifact/evidence plane.
Run-state and evidence status are read via the stable contract:

```bash
"<installed-plugin-root>/bin/arw" status --run-root <run-root> --json
```

Treat stale metadata as a request for an explicit parent sync; never infer
permission to crawl, extract, or rebuild from a query.
