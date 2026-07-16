# ADR 0001: Human and semantic artifacts are dual sources

## Decision

Every successful enhancement will produce a human-readable Markdown artifact and a semantic sidecar from one validated intermediate representation.

## Alternatives

- Generate prose only and infer a graph later.
- Treat the sidecar as authoritative and render prose opportunistically.

## Rationale

The plan requires readable documents and deterministic retrieval/graph contracts. A shared intermediate model makes drift testable and keeps stable IDs, provenance, and relationships visible to both audiences.

## Consequences and evidence

Later rewrite and audit lanes must validate both outputs together. The WT0 protocol boundary carries generic artifacts so this decision does not require a storage implementation yet.
