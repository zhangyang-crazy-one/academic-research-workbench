# Bounded citation scopes in writing receipts

Issue #76 identifies a writing receipt that can exceed the retained-file read
limit even though both manuscript texts meet their 1 MiB limits. Each citation
currently copies its entire assertion sentence for source and candidate. This
prevents a reviewer-approved revision from being read or replayed after
publication.

The writing prepare/record workflow will store versioned citation-to-sentence
indexes over the already retained source and candidate text. It will check the
complete canonical receipt against the 8 MiB retained-source limit before
publishing either a receipt or an accepted paper candidate. Historical
sentence-valued bindings remain readable with their original scope semantics.

This change only alters receipt representation and admission. It does not infer
semantic equivalence or relax the human review and mechanical fact gates.
