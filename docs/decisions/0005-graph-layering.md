# ADR 0005: Semantic graph layers are explicit

## Decision

Authoritative structural, governed domain, extracted semantic, and retrieval-association graphs are distinct layers. Higher-numbered layers cannot overwrite lower-numbered facts.

## Alternatives

- One unrestricted graph with generic relationships.
- Keep graph data only in a later external database.

## Rationale

Typed, provenance-bearing relationships enable safe retrieval and future exports without presenting inference as governance.

## Consequences and evidence

The `Exporter` and `Retriever` ports remain backend-neutral. Later schema and RAG tests must reject generic authoritative edges and dangling references.
