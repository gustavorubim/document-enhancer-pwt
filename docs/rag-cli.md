# Local RAG CLI

The RAG commands read the promoted cumulative catalog. They do not modify enhanced documents and
they never give retrieved text tools, network access, or instruction authority.

```bash
docenhance rag search "monthly review owner" --explain
docenhance rag ask "Who records the monthly review?" --explain
docenhance rag chat
docenhance rag chat --session SES-MONTHLY-001
docenhance rag sources ANSWER-ID
docenhance rag graph ROLE-REVIEWER --depth 2
docenhance rag stats
```

`search` fuses the profile-matched vector channel, SQLite FTS5, and bounded graph expansion with
deterministic weighted Reciprocal Rank Fusion. Its output includes channel ranks/scores, stable
chunk IDs, graph paths, active filters, the catalog generation, and latency. Metadata filters are
applied inside every retriever. Current document versions are the default; use
`--include-history` only for deliberate historical retrieval.

`ask` and `chat` retrieve before generation, enforce a context budget, validate structured
claim-level citations, run a grounding audit, and allow at most one retrieval retry and one
grounding repair. If evidence remains insufficient or grounding fails, the visible result is
`insufficient`, never an unqualified answer. `--offline` uses deterministic local fakes for tests
and demonstrations; normal use resolves the governed RAG prompt IDs and configured Gemini routes.

Chat is in-memory unless `--session ID` is supplied. A saved session stores visible user and final
assistant messages, stable citations, retrieval diagnostics, and model metadata—never hidden
reasoning. Its catalog generation and filters remain pinned until `/refresh`. Useful slash commands
are `/sources`, `/explain`, `/filters`, `/clear`, `/session`, `/refresh`, `/help`, and `/exit`.

All non-interactive commands support stable `--json`. JSON and non-TTY output contain no ANSI
control sequences. Set `NO_COLOR=1` or pass the root option `docenhance --no-color ...` to disable
color in human-readable output.

The vector adapter validates migration/integrity state, embedding profile, dimensions, vector
digests, and chunk coverage before search. It uses pinned SQLiteVec when selected and supports only
the explicit bounded exact-scan fallback. Corrupt data and profile mismatches fail closed.
