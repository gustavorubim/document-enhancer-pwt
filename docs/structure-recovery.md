# M3B structure recovery

The deterministic parser remains the source of truth for bytes, order, block text, locations,
assets, and warnings. `StructureRecoveryService` adds a bounded, optional structure layer around
that parser result. It adapts each local `span-*` ID to a deterministic WT1 `SPAN-*` ID for
structured model contracts and maps the selected result back to the local span IDs without
changing parser provenance.

## Modes

- `off`: no model calls; select the validated parser view and record that recovery was disabled.
- `parser`: no model calls; select the parser view and record the explicit parser decision.
- `auto`: always call `structure.triage` on `gemini-3.1-flash-lite`, including for a clean outline.
  Deterministic quality signals, the scan decision, and boundary disagreement decide whether
  window recovery is needed.
- `recover`: skip triage and run bounded window recovery. This is useful when a caller has already
  decided that parser structure is insufficient.
- `force`: skip triage and force bounded window recovery, subject to the same validation and
  budgets. It does not bypass safety or promotion gates.

The prompt pack, not Python, owns prompt text, shared references, output schemas, and model-route
selection. Source content is placed in the prompt pack's untrusted-data boundary. Tools are not
available to any structure route.

## Cross-lane integration dependency

The WT3 implementation is offline-green and remains fail-closed when the live gateway cannot
produce a native structured result. The first credential-backed smoke exposed a WT11 prompt-pack
scope issue: all nine reference files were injected into the structure prompts, and composing the
empty-source structure prompt was 48,806 characters. The resulting `BudgetExceededError` is a
prompt-scope integration finding, not a structure-routing or validation failure in this lane.
WT11 is correcting this with explicit per-prompt reference scopes and empty reference scopes for
the structure routes. After that shared correction is merged, rerun the opt-in scan and recovery
smoke on the combined baseline. WT3 deliberately does not duplicate prompt text or modify shared
prompt/gateway files.

## Windows, validation, and promotion

Windows are contiguous raw blocks with deterministic character limits and stable overlap. Every
window proposal must cover its supplied authoritative spans exactly once, in source order, with
the exact source text digest. The merge de-duplicates only identical shared-boundary facts. A
conflict is retained as an explicit disagreement/`uncertain` disposition; one
`structure.reconcile-boundaries` call is allowed only when conflicts require it.

Promotion is fail-closed. Validation rejects nonexistent IDs, duplicates, gaps, reordering,
digest mutation, reversed/crossing section boundaries, bad nesting, invalid associations, and
ambiguity loss. A failed scan or proposal leaves the parser-selected view active. Recovery
artifacts are retained separately for inspection, but are never treated as a successful selected
view unless full validation passes.

The authoritative WT1 `StructureRecoveryProposal`/`BlockDisposition` contract identifies whole
source spans and carries a source-text digest, but it has no split-offset fields. WT3 therefore
does not invent a lane-local split contract: deterministic compound-block splitting cannot be
represented or validated end-to-end here. Such blocks remain whole and fail closed when exact
coverage requires a split; central domain/prompt schema correction is required before that M3.13
path can be enabled.

## Artifact contract

M3B writes independent, content-addressed artifacts for the scan, window map, per-window
proposals, optional reconciliation, recovered proposal, validation report, selected view, call
manifests, prompt resolutions, and aggregate metadata. Call manifests contain route/model,
prompt/schema/input/output/cache digests, retries, and resolution status; they never contain
prompt text, raw source, or credentials. Revisions use atomic staging/promotion and retain the
prior version. Aggregate calls, prompt resolutions, and recovery metadata use the neutral
`structure_metadata` stage; the upstream `structure_scan` stage contains only its scan artifact.
Existing M3A deferred reservations and promoted M3B structure artifacts may be replaced only
through the explicit atomic revision path.

The service intentionally does not manufacture scan or recovered model results in `off` and
`parser` modes. Scanned/image-only PDFs and unsafe constructs remain parser-level fail-closed
conditions and are not sent to recovery as a way to infer missing text.
