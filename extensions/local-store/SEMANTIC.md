# Optional semantic retrieval

Semantic retrieval helps an author select accepted literature for closer reading.
It is an advisory ranking path; it cannot accept claims, change the canonical
journal, or establish research efficacy. Existing FTS and graph queries remain
available without it.

Install explicitly with `uv sync --frozen --extra semantic`. The optional extra
pins `sqlite-vec==0.1.9` (MIT OR Apache-2.0); no model is shipped or downloaded.
Only explicit capability resolution loads the native extension, and extension
loading is disabled again immediately afterward. Minimal store migration creates
ordinary empty metadata/document tables without importing sqlite-vec. Explicit
build creates the dimension-bound vec0 table.

```bash
arw semantic build --store /WORK/projection.db --run-root /WORK/run \
  --model /WORK/model.json --model-sha256 MODEL_SHA256 \
  --artifact-id paper.example
arw semantic search --store /WORK/projection.db --run-root /WORK/run \
  --model /WORK/model.json --model-sha256 MODEL_SHA256 --query 'cardiac response'
```

`rebuild` takes the same arguments as `build`. `search --lexical-id ID` and
`--graph-id ID` consume ordered results from existing retrieval paths and perform
reciprocal rank fusion (`k=60`); each result retains path ranks and its canonical
artifact/event hashes. Fusion inputs must belong to the explicitly selected
corpus. The caller maps file/graph result identities to accepted artifact IDs;
this adapter does not assume that file IDs are artifact IDs.

The Python `EmbeddingBackend` Protocol allows an explicitly configured trusted
backend. CLI supports a digest-pinned offline `arw.token-vectors.v1` JSON model:
`format`, `model_id`, `version`, `dimensions`, and `tokens` mapping casefolded words
to finite numeric vectors. The backend averages Unicode word token vectors and
normalizes the result. It is useful for bounded vocabularies and fixtures, not a
qualified general language model. Chinese tokenization is limited to contiguous
Unicode word runs; it does not perform Chinese word segmentation. Unknown-only
text or a zero vector is rejected. External providers must return finite Python
numeric vectors and record their model and implementation identity; this CLI
never executes an import string or downloads a model from research input.

Model ID/version/content digest/dimensions/implementation, sqlite-vec version and
vector-index format are recorded. Drift blocks querying and ordinary build;
explicit rebuild is required. Source artifact hashes and acceptance events are
validated from canonical bytes both during build and on every search. An index
cannot be reused for a different canonical run. Search opens read-only and never
creates, migrates or generates corpus embeddings. It generates only the explicit
query embedding and does not retain query text.

The selection is bounded to 128 accepted UTF-8 text artifacts, 64 KiB each and
4 MiB total; dimensions to 2,048; model file to 1 MiB and 4,096 tokens; query to
4 KiB; each fusion list to 128 IDs; results to 50. Binary/NUL/empty source inputs,
unsafe symlinks, changed accepted bytes and unknown fusion IDs fail explicitly.
Only selected source text is passed to the backend. A custom Python backend is
trusted code: its runtime/network behavior is its operator's responsibility.

The numbered migration is store schema `0003`; semantic metadata and vectors
are disposable. Rebuild replaces only semantic data in one explicit transaction;
backend or database failure preserves the previous valid projection. Delete the
index and regenerate from selected accepted artifacts plus the pinned model.
Existing unrelated projection tables are preserved by semantic rebuild.

Run the standalone acceptance example:

```bash
uv run --frozen --extra semantic python \
  extensions/local-store/examples/semantic_literature.py NEW_OUTPUT_DIRECTORY
```

It records source selection for a cardiac manuscript, verifies a synonym query,
rebuilds and compares results, and retains a fixture author-choice record. Its
model, documents and author are fixtures; research effectiveness is unmeasured.
Tests exercise the actual sqlite-vec engine, not a mock distance calculator.
Full GraphRAG and external graph servers remain out of scope pending a separate
benchmark-driven decision.

API references: [sqlite-vec Python binding](https://alexgarcia.xyz/sqlite-vec/python.html)
and [KNN queries](https://alexgarcia.xyz/sqlite-vec/features/knn.html), checked
2026-09-08. The package pin is in the semantic extra and `uv.lock`.
