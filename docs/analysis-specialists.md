# Analysis specialists (M4.6–M4.10)

The analysis lane provides four bounded, direct structured-model specialists and a deterministic
fan-out/fan-in coordinator. It deliberately has no dependency on the unfinished workflow or CLI
packages. A future workflow node can construct one `AnalysisRequest`, run `AnalysisOrchestrator`,
and persist the returned domain artifacts and manifests.

## Entry points

- `analysis.macro.MacroReviewer` returns one evidence-backed `MacroAnalysis` and deterministic
  Markdown.
- `analysis.sections.SectionMapper` returns one `SectionAnalysis`, deterministic Markdown, and a
  validated `SourceDispositionMap`.
- `analysis.discovery.ProcessMethodologyDiscoverer` returns typed candidate semantic objects and
  allow-listed candidate relationships. These remain unreviewed in the extracted graph layer.
- `analysis.rag_readiness.RagReadinessReviewer` returns model findings. At fan-in,
  `augment_rag_readiness` adds deterministic lint findings.
- `analysis.orchestrator.AnalysisOrchestrator` executes the four branches with at most four worker
  threads, orders their results deterministically, applies lint, and invokes
  `analysis.synthesize-findings` once.

The complete lane uses exactly five model calls: four analysis calls and one synthesis call. The
default call budget is five. A lower budget fails before any partial run begins; a consumed call
remains consumed when its provider invocation fails.

## Prompt and model boundary

Every call is composed by `PromptPackComposer` from the merged `gemini_core` prompt pack. The lane
rejects a prompt unless all of the following are true:

- The immutable prompt ID is the expected analysis prompt.
- The manifest route is exactly `gemini-3.5-flash`.
- The declared output is `analysis.schema.json`.
- No optional model tools are enabled.
- The call manifest records the same prompt ID, prompt-pack version, prompt digest, requested
  route, effective route, and model.

Source blocks are serialized as ordered JSON data and passed only through the composer's
`BEGIN UNTRUSTED SOURCE` boundary. Source text never becomes Python instructions and specialists
receive no shell, network, browser, code-execution, or file-write capability.

The persisted `AnalysisReport` schema includes Pydantic validation keywords outside Gemini's
native JSON Schema subset. Each provider call uses an exact stage report (`MacroAnalysis`,
`SectionAnalysis`, `DiscoveryAnalysis`, `RagReadinessAnalysis`, or the dedicated
`SynthesisAnalysis`) instead of sending the full union graph. The adapters remove only unsupported
provider-side keywords and close free-form maps, then promote every response through the complete
`AnalysisReport` Pydantic contract. The returned artifact is therefore valid against the
repository's authoritative schema even though Gemini receives a smaller compatible projection.

## Fail-closed invariants

### Evidence

Every finding must identify either exact source evidence or a named governed requirement. Quoted
evidence must occur in the named source span. When offsets are present, both offsets are required
and the exact source slice must equal the quote. Unknown spans, partial offsets, altered quotes,
foreign document IDs, and source-digest mismatches stop the lane.

### Full source disposition

`AnalysisRequest.authoritative_span_ids` intentionally contains every ordered raw block. The name
is retained for the workflow contract, but coverage is not filtered by the block's `substantive`
flag. Headings, body blocks, tables, figures, page furniture, boilerplate, headers, and footers all
need one explicit disposition.

The mapper requires the flattened mapping spans to equal the raw span sequence exactly. Missing,
duplicate, unknown, or reordered spans fail. Each disposition needs a rationale. Preserved, moved,
merged content needs exactly one target section; split content needs at least two ordered target
sections; omitted content must not claim a target; uncertain or blocking content remains visible.
The shared `SectionMapping.target_section_ids` contract preserves every target for a split without
duplicating the source-span disposition.

### Candidate graph

Discovery output is analysis evidence, not a final semantic graph. Every candidate object and edge
must:

- Use the shared typed ontology and allow-listed relationship endpoints.
- Have a unique stable or visibly provisional ID.
- Remain in the extracted graph layer with `unreviewed` or `in_review` status.
- Resolve to exact source-span provenance in the current document.
- Resolve both relationship endpoints inside the candidate object set.

Model-authored Mermaid is rejected. Downstream Mermaid must be generated from reviewed structured
objects; it is never a semantic source of truth.

### Deterministic RAG lint

The fan-in stage runs stable checks for:

- Heading hierarchy and every section's stable ID, including the root section.
- Provisional semantic object IDs.
- Graph-critical control, calculator, and dependency fields.
- Diagrams without code-observable logic.
- Oversized blocks that need reviewed semantic chunk boundaries.
- Candidate object provenance.
- Table identity, title, headers, and source metadata.
- Unresolved placeholders.
- Vague references and undefined acronyms.

Lint findings use deterministic IDs derived from the check, evidence spans, target object, and
missing-field details. Re-running identical inputs yields byte-equivalent lint JSON.

## Synthesis behavior

Branch results are always ordered macro, sections, discovery, then RAG readiness, regardless of
provider completion order. Before the synthesis call, exact duplicate findings are collapsed for
the prompt input and exact-evidence disagreements are recorded. The final result combines branch
and synthesis findings so the model cannot erase a reviewer disagreement.

Deduplication removes findings only when all semantic fields match apart from the finding ID and
evidence-list ordering. Findings over the same exact evidence remain separate when severity, type,
impact, proposed disposition, human-answer requirement, or blocking state differs. Those fields
are captured in `FindingConflict`. Final priority is deterministic: blocking first, then blocker,
high, medium, low, and informational severity, followed by human-answer need and stable tie-breaks.

## Offline verification

The authoritative tests are under `tests/unit/analysis/`. They run through the real
`GeminiModelGateway` with a thread-safe stage-recorded structured fake. The suite covers success,
invalid structured output, route and prompt mismatch, exact evidence failure, full-span coverage,
non-substantive footer disposition, root provisional IDs, candidate graph enforcement,
deterministic lint, prompt injection as inert data, fan-out ordering, conflicts, exact
deduplication, JSON round trips, and Markdown snapshots.

No live-model test is included. A useful live smoke would require approved credentials, data
handling, cost limits, and a shared opt-in test harness; offline tests remain authoritative.

## Integration requests

The integrator should:

1. Export the chosen analysis entry points from a shared package surface when the workflow API is
   frozen. This lane intentionally did not edit shared `__init__` files.
2. Persist each branch JSON/Markdown, the synthesis JSON/Markdown, every `PromptResolution`, and
   every `CallManifest` under the run artifact contract.
3. Add workflow cache keys over source/selected-structure, reference-pack, prompt-pack, schema,
   reviewer-input, and relevant configuration digests.
4. Consider moving the Gemini-compatible analysis-schema projection into the shared model gateway
   once provider-schema compatibility policy is centralized.
5. Extend the shared section-mapping schema with explicit multiple target section IDs if the
   rewrite/content-ledger lane needs one source span split across several targets. Preserve the
   one-source-span/one-disposition coverage invariant.
