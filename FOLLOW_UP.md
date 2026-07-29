# Follow-up work

## RAG graph linkage after heading rewrites

- Observed on sealed run `5e43c27208ec-b1b4c8bfbb`: the catalog contains 32 chunks, 73 graph
  nodes, and 66 graph edges, but exact unique-label matching links only 1 chunk. The final rewrite
  renamed or consolidated most source headings. Semantic/FTS retrieval and graph expansion from the
  linked Appendix section work, so this does not block the current CLI.
- Improve the sealed export or source-to-target map to carry deterministic final-heading-to-source
  section IDs into chunk metadata. Prefer explicit IDs over fuzzy entity matching, preserve
  ambiguous/unmatched counts, and add a rewritten-heading integration fixture before broadening the
  linker.

## PDF screenshot extraction

- PDF image objects are still inventoried with page provenance but are not materialized into the
  screenshot appendix. Add bounded raster extraction only when a representative PDF fixture and a
  supported image-decoding dependency are available; do not rasterize whole pages or introduce OCR
  on the authoring path.
