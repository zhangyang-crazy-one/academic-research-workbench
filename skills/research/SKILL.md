---
name: research
description: Entry point for domain-general research tasks; routes through the ARW control plane's canonical router.
---

# research

Invoke the canonical router and return its result unchanged:

```bash
"<installed-plugin-root>/bin/arw" route --json
```

The route result declares the workflow family, execution mode, source adapter
version, and gating status. Do not infer routing decisions outside that result.
For full research pipelines, delegate to the `academic-research-suite` skill.
