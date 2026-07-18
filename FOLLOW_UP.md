# Follow-up work

- Add an authorized, de-identified evaluation set spanning all four document types.
- Measure section-boundary accuracy, review usefulness, rewrite fidelity, audit finding recall,
  unsupported-claim rate, latency, token use, and cost.
- Exercise difficult DOCX/PDF layouts and image-only PDFs; OCR and multimodal extraction remain
  separate future work.
- Define production provider identity, data residency, quotas, cost limits, retention, and deletion
  policies.
- Run the opt-in Gemini end-to-end verification in a credentialed non-production environment.
- Add a future external graph or RAG consumer only through the sealed `core.graph.v1` export.
- Recreate a clean `.venv` if the editable install becomes polluted by sync-duplicated files.
