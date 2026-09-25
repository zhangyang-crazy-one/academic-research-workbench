# Optional STORM adapter

The integration lives in `arw_storm`; model/retriever imports remain lazy and all
ML dependencies remain in the `storm` optional group. `StormWorkflowProvider`
provides the WorkflowProvider registry/resolve contract and callable advisory
execution. It does not invent a canonical workflow or admit evidence.

Configure a documented model provider explicitly. For example, set
`OPENAI_API_KEY` and run `arw storm --topic "My topic" --provider openai`, or
set `GEMINI_API_KEY` and select `--provider gemini`. The provider determines the
default LiteLLM model (`openai/gpt-4o-mini` or `gemini/gemini-2.5-flash`);
`--model` may select another model with the same provider prefix. STORM does
not use Codex/Pi session credentials. Missing provider or key configuration
fails before constructing a model, and error messages identify the required
environment variable without printing its value.

For a separately configured OpenAI-compatible endpoint, supply
`--provider openai-compatible --model openai/MODEL --api-base HTTPS_URL
--api-key-env ENV_NAME`, with `ENV_NAME` set in the environment. The endpoint
and credential source must both be chosen by the operator. Raw API keys are
not accepted as command-line arguments. Tavily retrieval separately needs
`TAVILY_API_KEY`; `--retriever duckduckgo` avoids that key.
