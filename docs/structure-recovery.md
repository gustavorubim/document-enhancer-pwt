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

## Prompt and reference scope

Every structure prompt now declares an explicit zero-reference scope. Triage, window recovery,
and boundary reconciliation receive only their governed prompt-pack instructions, safe document
metadata, and the bounded source/window inputs supplied by this service. Enterprise reference
files are not composed into structure prompts. WT3 does not duplicate production prompt text or
modify shared prompt/gateway files.

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

Compound blocks may be split through the authoritative optional `BlockDisposition.segments`
contract while preserving one top-level disposition for the raw span. Segment offsets are Python
code-point character offsets into the exact immutable block text. Validation requires at least two
positive, ordered, contiguous segments with full block coverage, exact slice SHA-256 digests, and
deterministic `SEG-*` identities. Gaps, overlaps, reordering, UTF-8 byte offsets, text mutation,
bad digests, or bad IDs fail closed.

Selected-view artifacts retain the validated segment IDs, offsets, disposition/section mapping,
confidence, rationale, and slice digest. Different splits for the same overlap span are retained
in their per-window proposals and represented as an explicit uncertain disagreement; no candidate
split is silently selected. At most one governed boundary-reconciliation call may resolve that
conflict. Low-confidence segment choices keep their metadata but mark the parent selected-view
disposition as machine-readable `uncertain`.

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
