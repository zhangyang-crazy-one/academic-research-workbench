---
name: academic-research-workbench
description: Route domain-general academic research tasks through the installed Academic Research Workbench control plane.
---

# Academic Research Workbench

Resolve the plugin root as the parent of this installed `skills/` directory, then run the
installed launcher from that root:

```bash
"<installed-plugin-root>/bin/arw" route --json
```

Return the command's JSON result unchanged. It must declare the ARS workflow family,
execution mode, source adapter version, and disabled experiment status. Do not infer a
different family, mode, domain ontology, or experiment permission outside that result.

This installed skill is the canonical model-invocable route. Plugin-native custom-agent
distribution is unproven; when delegation is later requested, use native Codex subagents
with immutable assignment-injected ARS role instructions. The companion hook is
observational only, may be skipped until trusted, and is never an authorization or
canonical-state boundary. Only future explicit control-plane mutation commands may write
accepted state; `route` is read-only.
