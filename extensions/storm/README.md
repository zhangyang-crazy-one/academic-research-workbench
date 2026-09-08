# Optional STORM adapter

The integration lives in `arw_storm`; model/retriever imports remain lazy and all
ML dependencies remain in the `storm` optional group. `StormWorkflowProvider`
provides the WorkflowProvider registry/resolve contract and callable advisory
execution. It does not invent a canonical workflow or admit evidence.
