# Document Enhancer delivery plan

The active architecture and acceptance criteria are in
[SIMPLIFICATION_PLAN.md](SIMPLIFICATION_PLAN.md). Workflow-quality enhancements are tracked in
[WORKFLOW_ENHANCEMENT_PLAN.md](WORKFLOW_ENHANCEMENT_PLAN.md). The product objective lives in
[AGENTS.md](AGENTS.md).

Current delivery path:

1. Drop or pass one source through the five-phase `core` workflow (`run` / `watch-inbox`).
2. Read specialist reports: macro, sections (correct/missing/improve), and dual process Mermaid.
3. Answer business ambiguities in `review/decisions.yaml` and set `approve_rewrite: true`.
4. Continue to rewrite, audit, and seal the final document bundle with portable graph exports.
5. Verify the reduced source tree, offline workflow, and opt-in live Gemini seam.
