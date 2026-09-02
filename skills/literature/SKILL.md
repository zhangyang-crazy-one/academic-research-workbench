---
name: literature
description: Literature review, citation verification, and evidence-tier checks via the bundled Academic Research Suite.
---

# literature

Literature workflows are owned by the bundled ARS skill. Delegate to
`<installed-plugin-root>/skills/academic-research-suite/` (its router and
workflow files); do not substitute an external ARS installation. The control
plane's stable contract for the run state is:

```bash
"<installed-plugin-root>/bin/arw" status --run-root <run-root> --json
```
