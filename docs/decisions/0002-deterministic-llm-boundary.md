# ADR 0002: Deterministic checks surround LLM interpretation

## Decision

LLM calls may interpret and draft within approved evidence, but deterministic code owns extraction bytes, ordering, schemas, IDs, references, coverage, gates, and promotion.

## Alternatives

- Let model output define structure and acceptance.
- Use heuristic-only analysis and exclude model interpretation.

## Rationale

This preserves auditability while allowing messy document interpretation. A model cannot silently invent or delete source text.

## Consequences and evidence

Provider adapters implement the `ModelGateway` protocol and validators remain independent. Compatibility tests are offline by default; live calls are opt-in.
