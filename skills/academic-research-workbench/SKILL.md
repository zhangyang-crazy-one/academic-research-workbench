---
name: academic-research-workbench
description: Route domain-general academic research tasks through the installed Academic Research Workbench control plane.
disable-model-invocation: false
---

# Academic Research Workbench

Resolve the plugin root from this installed skill location, then run:

```bash
bin/arw route --json
```

Return the command's JSON result unchanged. Do not infer a workflow family, execution mode, domain ontology, or experiment permission outside that result. This skill routes only; the Python control plane owns all accepted state changes.
