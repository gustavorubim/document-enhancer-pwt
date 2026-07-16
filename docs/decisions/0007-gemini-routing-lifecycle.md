# ADR 0007: Gemini routing and lifecycle policy

## Decision

The shipped routes are `gemini-3.1-flash-lite` for structure/clerical work, `gemini-3.5-flash` for primary analysis and independent audit, and `gemini-3.1-pro-preview` for complex reconciliation/rewrite. Embeddings use `gemini-embedding-2` at 768 dimensions. Exact IDs are recorded; `latest` aliases are not used.

## Lifecycle and fallback

`docenhance doctor` and live compatibility checks must report unavailable or retired models honestly. Pro preview fallback to Flash is denied by default and is allowed only in a named configuration profile that records the substitution. A failed provider check is not converted into an offline pass.

## Evidence

The installed `langchain-google-genai` surface is probed without credentials in WT0. Live structured-output and embedding calls are marked `live_model` and require explicit opt-in.
