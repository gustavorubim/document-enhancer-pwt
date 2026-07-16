# Security and data handling foundation

Source documents, references, and retrieved chunks are untrusted data. Model adapters have no shell, browser, URL-fetch, code-execution, email, or document-write tools. DOCX parsing rejects active/macro content and unsafe ZIP members, inventories but never follows external relationships, and PDF parsing never fetches links or performs OCR. Canonical path, bounded input, safe YAML depth/node, prompt variable, and catalog integrity checks fail closed.

Credentials are accepted only through provider-native process environment or ADC mechanisms, never CLI arguments or committed TOML. The public configuration view contains no credential fields. Live evaluation scripts do not open dotenv files.

Operational logging is diagnostic metadata to stderr. It redacts key/token/password-shaped values; event logs use hashes or bounded identifiers instead of source content. External tracing is explicit opt-in and recorded. SQLite text, graph, FTS, embeddings, questions, and saved sessions inherit source confidentiality and retention requirements.

`tests/security/` covers prompt injection, path traversal, malicious formats and ZIP members, YAML hazards, secrets/redaction, oversized hostile content, catalog corruption, citation/grounding failures, and prohibited tool boundaries. `uv run pytest tests/security -m security` runs the focused suite.
