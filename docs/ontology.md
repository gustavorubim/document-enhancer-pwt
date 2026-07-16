# Enterprise ontology v0.1

This document is the authoring and review contract for the bounded ontology in
`document_enhancer.domain`. The checked-in Pydantic models and generated JSON
Schemas are authoritative for machine artifacts; this page explains the
extension policy around them.

## Identity and versions

Every graph object has an uppercase, readable, immutable ID with an entity
prefix. A rename changes `name` or `canonical_name`, never the ID. A
`DocumentIdentity` is the durable identity of a document. A `DocumentVersion`
holds its version label, status, effective interval, and source/enhanced
digests. A version must point back to exactly one document identity; a version
label is never appended to the permanent document ID.

Provisional IDs are deterministic and visibly prefixed with `PROV-`. They are
valid for review artifacts, but a passing authoritative export must list them
explicitly in `provisional_ids` and downstream consumers may exclude them.

## Provenance and graph layers

Every semantic node and relationship carries provenance. It identifies the
document, optionally the document version and source span, the origin
(`source`, `answer`, `steering`, `reference`, or `model`), authority, layer,
extraction method, review state, and temporal validity. Source-origin claims
must cite a stable `SPAN-...` ID. Model-origin or inferred claims must include
confidence. Accepted or waived claims include reviewer identity.

The graph layers are ordered from 1 to 4:

1. `authoritative`: template/sidecar structure and explicit governed IDs;
2. `governed`: reference-pack and registry facts;
3. `extracted`: narrative interpretation and proposed semantic facts;
4. `retrieval`: search associations and derived retrieval metadata.

An inferred claim cannot be authoritative or governed. A higher-numbered layer
cannot overwrite a lower-numbered layer. Relationships are allow-listed by
predicate and endpoint type; generic `RELATED_TO` is intentionally absent.
Cross-document references must use `RELATED_TO_DOCUMENT`, with the referenced
document represented explicitly when a graph needs to resolve it.

### Split-block structure recovery

Structure recovery preserves exactly one top-level `BlockDisposition` for each
raw source span. When a compound block needs deterministic structural splitting,
the disposition may carry two or more typed `BlockSegment` records. Segments are
metadata over the immutable original block; they do not create new raw spans or
authoritative source objects.

Each segment uses Python `str` character/code-point offsets, not UTF-8 byte
offsets, and declares `offset_unit=python_characters`. The proposal validator
requires contiguous positive ranges from `0` through `len(original_text)`, in
source order, with no overlap or gap. It recomputes the SHA-256 of each exact
`original_text[char_start:char_end]` slice and rejects any mismatch, out-of-range
offset, Unicode/byte-offset assumption, or unknown section reference. A segment
inherits its source provenance from the parent raw span and may add only its
typed section/disposition metadata.

Segment IDs are derived as `SEG-` plus a 16-character uppercase hexadecimal
token from the parent `SPAN-...` ID, the two character offsets, and the slice
digest. A model may not choose a
different syntactically valid ID. Changing the offsets or digest changes the
expected ID and invalidates the proposal. Unsplit dispositions remain valid
without a `segments` field.

## Adding an ontology extension

Extensions are reviewed changes, not per-run invention. To add a new entity or
relationship type:

1. Propose the name, prefix, definition, lifecycle owner, and security impact.
2. Add the enum member and entity-specific ID prefix in the domain models.
3. Define required provenance, temporal/version, review, and minimum fields.
4. Add every permitted relationship endpoint pair explicitly to the allow-list.
5. Add positive and negative contract fixtures, including dangling-reference,
   wrong-endpoint, missing-provenance, and layer-authority cases.
6. Regenerate schemas with `python scripts/generate_schemas.py` and review the
   schema diff.
7. Update this document and any reference-pack ontology files in the owning
   lane, then record compatibility and migration notes.

An extension must not use an untyped attribute or generic predicate as a
shortcut. If the concept is only retrieval metadata, keep it outside the
business ontology or give it a dedicated retrieval contract.

## Deprecation and migration

Existing IDs and predicates are immutable. Deprecating an entity or predicate
means:

- mark the object or relationship `review_status=deprecated`;
- retain it for historical versions and audit trails;
- add a typed replacement and an explicit migration mapping;
- do not reuse the old ID or prefix for a different meaning;
- keep old schemas readable until the declared compatibility window closes.

Removing a predicate or field requires a versioned schema change and a
migration test. A deprecated object may remain in a historical semantic sidecar
but must not be emitted as a new authoritative fact. If a migration cannot
preserve reference resolution or temporal meaning, it fails closed and emits a
reconciliation issue.

## Schema and round-trip policy

All persisted domain models reject unknown top-level fields. Forward-compatible
metadata belongs under an explicitly modeled `extensions`/`attributes` field;
adding an arbitrary field to an artifact is not forward compatibility. JSON and
YAML are parsed through the same Pydantic model, and schema drift is checked by
`python scripts/generate_schemas.py --check`.
