# Security and data handling foundation

Source documents and reference materials are untrusted data. WT0 does not provide shell, browser, URL-fetch, or document-write tools to model adapters. Credentials are accepted only through provider-native environment or ADC mechanisms, never CLI arguments or committed TOML. The public configuration view contains no credential fields.

Operational logging is diagnostic metadata to stderr. It redacts key/token/password-shaped values, and future event logs must use hashes or bounded identifiers instead of source content. The external `.env` is preserved for local verification and is never copied into the worktree.
