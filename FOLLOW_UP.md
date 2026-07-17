# Post-v1 follow-ups

These items extend validation, production readiness, and product scope after the verified v1
implementation. They are not blockers or missing MVP plumbing.

## Real-world validation

- [ ] Add bounded per-section or per-window discovery for long documents, followed by
  deterministic candidate merge, conflict handling, deduplication, and whole-source coverage
  validation before promotion.
- [ ] Build an authorized, de-identified evaluation set covering methodology documents,
  standards, processes, and desktop procedures across several enterprise domains.
- [ ] Measure section-boundary accuracy, clarification-question precision and recall, rewrite
  fidelity, audit finding recall, unsupported-claim rate, latency, token use, and cost.
- [ ] Run blinded reviewer sessions to assess question usefulness, approval effort, output
  usability, and traceability back to source evidence.
- [ ] Evaluate multi-document and version-aware RAG/graph retrieval, including citations,
  metadata filters, relationship traversal, conflicting sources, and abstention behavior.
- [ ] Exercise DOCX/PDF edge cases, including tables, headers and footers, malformed layouts,
  embedded images, and image-only pages.
- [ ] Add public-download fixtures only after documenting source provenance, license terms, and
  redistribution permission.

## Operational hardening

- [ ] Add digest-keyed caching for governed reference and prompt context so repeated stages reuse
  only byte-identical, version-compatible inputs and retain auditable cache evidence.
- [ ] Monitor Gemini model lifecycle and pin reviewed replacements before preview-model retirement,
  especially for the Pro route.
- [ ] Define the production Gemini deployment policy: API versus Vertex AI, region and residency,
  workload identity, quota limits, retry policy, and cost alerts.
- [ ] Load-test SQLite and sqlite-vec for expected corpus size and concurrency; document backup,
  restore, compaction, and migration procedures.
- [ ] Define retention, purge, and secure-deletion behavior for sources, prompts, generated
  artifacts, embeddings, graph data, and audit records.
- [ ] Add production encryption, least-privilege access controls, secret rotation, and tenant/data
  isolation appropriate to the deployment environment.
- [ ] Add redacted observability, rate limiting, failure alerts, and operating runbooks without
  exposing document content or credentials.

## Explicit follow-on features

- [ ] Add OCR and multimodal extraction for scanned PDFs, screenshots, and image-based diagrams.
- [ ] Add bounded batch orchestration with resumability, per-document isolation, prioritization,
  and consolidated reporting.
- [ ] Add enterprise identity, row-level authorization, and an optional review/approval UI.
- [ ] Add high-fidelity DOCX/PDF render-back with visual regression checks.
- [ ] Add adapters for external graph and vector stores while preserving provenance and embedding
  compatibility contracts.
- [ ] Integrate canonical enterprise registries for controls, systems, roles, policies,
  calculators, and dependencies.
- [ ] Keep calculators, macros, spreadsheets, and other referenced source artifacts non-executable;
  any future execution capability requires a separately reviewed sandbox and security model.
