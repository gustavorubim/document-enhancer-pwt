# Security corpus and tests

Source text, retrieved chunks, fixture metadata, and reference files are untrusted data. The WT9 security corpus includes prompt-injection text as source content, hostile layout markers, malformed Mermaid/IDs, screenshot-as-authority claims, ambiguous instructions, and cross-document references. Tests assert that these strings remain data and do not grant tools, change evaluator policy, or create secrets.

## Public-source governance

`fixtures/public/sources.yaml` is a fetch-on-demand registry. Every entry has an HTTPS URL, an allow-listed host, expected media types, a maximum byte size, provenance, license/terms review status, and an optional pinned SHA-256. No document is downloaded during ordinary tests.

`scripts/fetch_public_sources.py` defaults to dry-run. An explicit `--fetch` is required to write bytes. The safe fetch path:

- rejects non-HTTPS URLs, credentials in URLs, off-list hosts, URL traversal, and unsafe destination paths;
- disables redirects, including redirects to an otherwise off-list host;
- checks the response media type and declared/actual size before writing;
- streams with a hard byte bound and verifies a pinned digest when present;
- stores bytes only; it never opens, imports, renders, executes, or sends the downloaded content onward.

License review is for fetching only. A public document must not be committed or treated as organization-specific gold without a separate redistribution and authority review.

## Offline security checks

The owned tests cover fixture secret/proprietary-pattern scans, injection presence and labeling, safe YAML loading, dry-run no-write behavior, unknown/off-list sources, path traversal, redirect rejection, oversized responses, unexpected media, digest mismatch, and the stable `not_evaluated` report semantics. The existing WT0 logging redaction test remains part of the full suite.

Run the focused checks with:

```bash
uv run pytest tests/unit/evals tests/security tests/e2e/test_fixture_corpus.py -q
```

The suite uses fake response objects for failure paths; it does not contact a public host. Live public downloads are intentionally outside ordinary offline CI and require the explicit `public_download` lane when that marker is added by the integrator.

## Deferred security integration

M3 must add active-content and embedded-relationship checks for DOCX/PDF. M4/M5 must prove prompt composition and tool allow-lists. M6/M7R must prove that retrieved injection text remains quoted evidence and cannot alter graph writes, catalog state, answer policy, or citations. WT9 should add those integration tests after the corresponding APIs merge rather than asserting behavior against absent artifacts.
