---
name: graph
description: Research-graph queries (claims, sources, experiments, reviews, gates) against the rebuildable projection.
---

# graph

The research graph is a disposable projection over the canonical ledger.
Query it through the graph capability; the store is never canonical truth.
Run-state position is read via:

```bash
"<installed-plugin-root>/bin/arw" status --run-root <run-root> --json
```
