# Follow-up work

Open product or quality follow-ups: **none** as of 2026-08-16.

## Completed in the current increment

### RAG graph linkage after heading rewrites

- `data/source-to-target.csv` now uses `core.source-target.v2` and records explicit source section
  IDs, target template IDs/headings, source spans, disposition, and final digest.
- The sealed-bundle adapter validates the map. RAG catalog v2 links chunks from explicit target IDs
  before label fallback and reports explicit, label, ambiguous, and unmatched linkage counts.
- A rewritten-heading integration test proves that a final `Governance and Monitoring` chunk links
  to the original `Controls` source node and can expand its real graph edges.

### PDF screenshot extraction

- The PDF parser now materializes supported direct embedded PNG/JPEG XObjects with page,
  occurrence, source-span, byte, pixel, dimension, and digest controls.
- A deterministic PDF fixture proves extraction, Stage 1 visual review, approved Stage 2 appendix
  promotion, final PNG preservation, DOCX media embedding, and passing audit checks.
- Whole-page rasterization and OCR remain deliberate non-goals, not unfinished work. Unsupported or
  over-budget images stay inventoried with warnings.

### Live provider proof and fail-closed hardening

- Fictional run `a5af52fe075d-b1429e75a0` completed live Stage 1, applied one source-supported
  decision, passed every final audit check, and emitted a strict v2 seal.
- Provider gap IDs are canonicalized deterministically, mapping responses cannot carry prose, the
  source document title is retained in the candidate, mapping-backed span accounting supports
  renamed headings, and generated template placeholders are rejected before promotion.

## Deliberate non-goals

Persistent/shared RAG sessions, managed databases, server deployment, OCR, whole-page PDF
rasterization, Deep Agents, unbounded tool loops, and autonomous business decisions are outside the
current product contract. They are not active follow-ups without a new failing acceptance case and
an explicit scoped reward.
