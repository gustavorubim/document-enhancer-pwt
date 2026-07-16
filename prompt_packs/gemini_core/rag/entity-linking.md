---
prompt_id: rag.entity-linking
stage: rag_entity_linking
---

Link query mentions to supplied candidate semantic entities and aliases. Return only supported
links, unresolved mentions, confidence, and evidence handles. Do not create a new canonical ID,
merge incompatible types, or treat a similar name as identity without evidence.
