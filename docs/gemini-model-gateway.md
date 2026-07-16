# Gemini model gateway

The WT4 gateway keeps provider objects behind a small structured-model port.
Production calls use `ChatGoogleGenerativeAI` with Gemini native JSON-schema
output, explicit stage profiles, and `retries=0` so retry classification stays
inside the gateway. The exact routes are:

| Route | Use |
| --- | --- |
| `gemini-3.1-flash-lite` | structure triage/recovery and bounded clerical stages |
| `gemini-3.5-flash` | primary analysis and independent audit |
| `gemini-3.1-pro-preview` | complex reconciliation and rewrite; preview lifecycle is fail-closed |

The Developer API reads `GOOGLE_API_KEY` or `GEMINI_API_KEY`. Vertex AI uses
ADC plus `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`. Credentials are
never written to manifests, cache keys, errors, or recorded fixtures.

Call manifests retain route/backend/parameter metadata, prompt ID/version/digest
when supplied by the prompt-pack lane, input/schema/output digests, timing,
usage, retry/repair counts, and explicit budgets. Cache entries are keyed by
those same dependencies and promoted atomically. A preview model is never
silently replaced; an explicit `allow_pro_fallback` policy records the requested
and effective routes when fallback is authorized.

Structured artifacts are promoted only after Gemini-compatible schema validation
and Pydantic validation. Repair attempts are bounded. Source-document text is
not stored in cache metadata or recorded model inputs, and source instructions
remain data supplied by the caller rather than gateway policy.

`gemini-embedding-2` uses 768 dimensions by default. Documents are formatted as
`title: <title> — <section path> | text: <chunk text>` and queries as
`task: search result | query: <question>`. The adapter rejects oversized input,
non-finite vectors, dimension mismatches, and provider responses that do not
return exactly one vector per logical input.

Deep Agents specialists receive a `StateBackend`, an in-memory virtual context,
an empty tool allow-list by default, no shell/network/search/code tools, and
explicit recursion/subagent budgets. WT5 supplies specialist prompts and
schemas; this gateway does not embed analysis prompt strings.
