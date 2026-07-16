# ADR 0003: Support four loss-aware input families

## Decision

V1 accepts Markdown, text, DOCX, and text-based PDF through separate parser ports. Scanned PDFs fail clearly unless a later OCR policy is approved.

## Alternatives

- Accept only Markdown.
- Add OCR and pixel-perfect round-tripping in the foundation.

## Rationale

These inputs cover the target enterprise corpus while keeping provenance and unsupported constructs explicit.

## Consequences and evidence

The parser protocol reports source capabilities and warnings. Concrete parsers belong to the ingestion lane; WT0 only freezes the port.
