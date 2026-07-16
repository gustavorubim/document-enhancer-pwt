# ADR 0004: Human review is a persisted workflow gate

## Decision

Blocking questions and rewrite approvals are durable inputs with explicit statuses, identities, and waivers. A run may pause and resume without repeating unchanged work.

## Alternatives

- Ask questions only in an ephemeral chat.
- Accept model-generated answers automatically.

## Rationale

Review decisions are part of the artifact provenance and must survive process termination.

## Consequences and evidence

Workflow/checkpoint implementations must expose waiting and resume states. WT0 reserves the exit code and ports; later lanes implement the persisted graph.
