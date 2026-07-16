# Synthetic fixture corpus

`fixtures/synthetic/corpus/manifest.json` indexes five fictional families: monthly loss forecasting
methodology, quarterly access review process, incident escalation desktop procedure, third-party
risk standard, and cross-document model-change governance process.

Every family has clean, mild, medium, and severe Markdown and DOCX artifacts generated from the same
facts. The methodology and desktop-procedure families also have text PDFs at every degradation
level. Controlled degradation includes missing heading styles, bold/all-caps/table headings,
inconsistent numbering, a mismatched table of contents, repeated page furniture, manual breaks/page
artifacts, misplaced tables, multi-topic content, topic-inferred boundaries, untrusted prompt-like
text, and malformed diagram/ID content.

Each family `gold.json` contains raw block order, text digests, source boundaries/hierarchy,
structure routing, facts, clarification questions and seeded reviewer answers, semantic objects and
edges with provenance, dispositions for every substantive clean span, seeded defect labels, and a
source/answer-backed enhanced target. `cross_document_questions.json` covers direct fact,
multi-section synthesis, control-to-risk and dependency paths, current/superseded behavior,
ambiguous follow-up, metadata filters, and answerable/partial/unanswerable cases with stable logical
chunks, paths, facts, citations, forbidden claims, and abstentions.

Generate and verify byte-stable artifacts with:

```bash
uv run python scripts/generate_fixture_corpus.py
uv run python scripts/generate_fixture_corpus.py --check
```

The corpus contains no copied proprietary text, random IDs, timestamps, credentials, live-model
outputs, or downloaded public documents. Public extraction fixtures are registry-only under
`fixtures/public/sources.yaml` and are never organization-specific gold.
