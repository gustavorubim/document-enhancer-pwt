---
prompt_id: audit.content-fidelity
stage: independent_content_fidelity_audit
---

Audit the enhanced document independently from the rewriter's scratch context. This stage is a
content-fidelity audit, not a full template-completeness or document-quality audit.

Check only whether the enhanced document contradicts source facts, drops source facts that were
in scope for the rewritten content, invents unsupported facts, loses approved reviewer answers, or
persists provenance that is not grounded in the supplied source or reviewer inputs. Deterministic
schema, template, table, diagram, unresolved-open-issue, and placeholder/TBD completeness checks
are owned by deterministic audit gates; do not create independent content findings solely for
those issues here.

Create a blocking finding only when the source text or approved reviewer input is materially
misrepresented, omitted from the rewritten content that claims to resolve it, or contradicted by
the enhanced document. Mark `auto_revisable` true only when the finding can be resolved by a local
textual correction using the supplied source text or approved reviewer input. Do not rewrite the
document in the audit response.
