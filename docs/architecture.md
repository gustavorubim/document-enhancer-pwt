# Architecture foundation

WT0 freezes a dependency-light port layer in `document_enhancer.contracts`. Parsers, artifact repositories, reference and prompt packs, model gateways, specialists, validators, retrievers, and exporters are protocols so later lanes can evolve implementation details without coupling the workflow to SDK objects.

The product boundary is local-first. Provider credentials stay outside the configuration model, provider tools are disabled by default, and the compatibility suite constructs SDK objects without making calls. `docenhance doctor` reports capability and configuration shape; it does not claim that later enhancement or RAG milestones are complete.
