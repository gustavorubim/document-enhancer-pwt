# ADR 0006: Local-first data handling is the default

## Decision

The CLI writes local artifacts, sends content only to an explicitly configured approved provider, and keeps external tracing and provider tools disabled unless explicitly enabled by policy.

## Alternatives

- Hosted observability by default.
- Implicit web/search/tool access for document agents.

## Rationale

Enterprise source documents and derived catalogs share a confidentiality class. Local-first behavior reduces accidental exfiltration and makes the workflow reproducible.

## Consequences and evidence

Configuration excludes secrets, logging redacts credential-shaped values, and doctor reports capability without exposing environment values.
