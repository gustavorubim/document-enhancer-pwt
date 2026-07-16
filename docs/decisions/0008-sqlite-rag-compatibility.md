# ADR 0008: SQLite RAG uses tested adapters and an explicit fallback

## Decision

SQLite FTS5 is the lexical baseline. The exact `sqlite-vec==0.1.6` package is pinned behind a local LangChain `VectorStore` adapter, with `BaseRetriever` composition and an exact cosine scan reserved for an explicitly bounded small-catalog fallback.

## Embedding compatibility

Document inputs use the deterministic `title: ... — section | text: ...` profile, while query inputs use Gemini Embedding 2's `task: search result | query: ...` profile. Model, dimensions, format version, and digest are part of the profile; vectors from different profiles cannot be compared.

## Consequences and evidence

WT0 proves FTS5, `sqlite-vec==0.1.6` extension loading, a `vec0` insert/query on macOS arm64 with the locked Python 3.13 environment, LangChain adapter classes, a `BaseRetriever.invoke` nearest-vector result, and hard exact-scan size/profile rejection boundaries offline. Later RAG work must validate vector encoding, integrity, and provider availability before promoting a catalog. The live Gemini Embedding 2 probe preserves the asymmetric document/query text formats and uses the same model and dimensionality without forcing legacy `task_type` values; if the pinned wrapper or endpoint requires a different API shape, that is reported as unavailable rather than hidden.
