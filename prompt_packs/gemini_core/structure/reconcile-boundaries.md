---
prompt_id: structure.reconcile-boundaries
stage: structure_boundary_reconciliation
---

Reconcile adjacent recovered windows and the parser outline into one ordered structural view.
Resolve only boundary and hierarchy disagreements. Preserve every raw span exactly once, retain
alternative boundaries when evidence is insufficient, and mark low-confidence or ambiguous
decisions for review. Do not merge source text, invent headings, or change block contents.
