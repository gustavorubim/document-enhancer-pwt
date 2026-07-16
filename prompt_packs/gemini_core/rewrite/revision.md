---
prompt_id: rewrite.revision
stage: bounded_revision
---

Return one narrow patch set for the named auto-revisable audit findings. Each section patch must
name an existing section ID, provide the complete revised body, cite only source span IDs already
attached to that section, and cite every audit finding it addresses. Do not return or replace the
document model, canonical IDs, provenance, review state, digests, tables, semantic objects,
relationships, or diagrams.

Resolve an existing open issue only when a section patch actually addresses it and both patches
cite the same approved audit finding. If a requested change needs a new fact, target, evidence
handle, or human decision, do not invent it and do not include an unsupported patch.
