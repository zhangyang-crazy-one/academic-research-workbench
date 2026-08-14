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

The modified Academic Research Suite is bundled at
`<installed-plugin-root>/skills/academic-research-suite/`; use that exact router and
its workflow files for ARS tasks. Do not substitute an external ARS installation.

This installed skill is the canonical model-invocable route. Plugin-native custom-agent
distribution is unproven; when delegation is later requested, use native Codex subagents
with immutable assignment-injected ARS role instructions. The companion hook is
observational only, may be skipped until trusted, and is never an authorization or
canonical-state boundary. Only future explicit control-plane mutation commands may write
accepted state; `route` is read-only.

For local research files, the installed MCP receives one parent-supplied root
capability and exposes only `list_files`, `read_file`, `search_files`,
`get_outline`, and `get_context`. Treat stale metadata as a request for an
explicit parent sync; never infer permission to crawl, extract, rebuild, repair,
or broaden the configured root from an agent query.
For local research files, the installed MCP receives one parent-supplied root
capability and exposes only `list_files`, `read_file`, `search_files`,
`get_outline`, and `get_context`. Treat stale metadata as a request for an
explicit parent sync; never infer permission to crawl, extract, rebuild, repair,
or broaden the configured root from an agent query.

## Optional deep research (STORM)

When the user explicitly asks for an experiment-planning pass, deep thinking, or a
survey-style literature synthesis, you may offer the opt-in STORM pipeline:

```bash
"<installed-plugin-root>/bin/arw" storm --topic "<topic>" --output-dir <dir>
```

STORM performs retrieval-grounded multi-perspective research and writes a
citation-backed draft article plus an `arw-storm-receipt.json` audit receipt into
`<output-dir>/<topic>/`. It is never part of the default route, does not touch the
run ledger, and requires the operator to have model credentials available
(`GEMINI_API_KEY` / `GOOGLE_GEMINI_BASE_URL`, or explicit `--api-key`/`--api-base`)
and a retriever key (`TAVILY_API_KEY`, or pass `--retriever duckduckgo` for the
keyless fallback). Run it only when the user consents; treat its output as
pre-writing research material, never as canonical experiment evidence.
