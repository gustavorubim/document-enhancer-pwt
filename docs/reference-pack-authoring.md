# Reference-pack authoring and versioning

Reference packs are source-controlled, versioned context for document enhancement. A pack supplies templates, machine requirements, bounded ontology vocabulary, rubrics, and contextual policy or standard guidance. Pack content is governed data: it is never treated as instructions for an agent, and it must not contain copied proprietary material.

The default pack is [`reference_packs/enterprise_core`](../reference_packs/enterprise_core/). Its stable pack ID is `enterprise_core`, and its current semantic version is recorded in `manifest.yaml`.

## Pack contract

Every pack has this shape:

```text
<pack>/
├── manifest.yaml
├── ontology/
├── templates/<document-type>/
│   ├── template.md
│   ├── requirements.yaml
│   └── example.md
├── context/
│   ├── glossary/
│   ├── policies/
│   ├── standards/
│   └── style_guides/
└── rubrics/
```

`manifest.yaml` must declare the pack ID, semantic version, owner, status, effective dates, supported document types, template/requirements/example paths, ontology paths, rubric paths, context sources, precedence order, conflict policy, acknowledgements, and SHA-256 digests for every pack file except the manifest itself.

Paths are relative, canonical POSIX paths. Absolute paths, backslashes, `.` segments, `..` segments, NUL bytes, missing files, symlinks that resolve outside the pack root, and unlisted files are rejected. YAML is loaded with the WT0 safe parser with duplicate keys disabled, size/depth/node bounds, string-only mapping keys, and no custom Python tags.

## Adding or changing a template

1. Choose a new document-type key or use one of `process`, `methodology`, `standard`, and `desktop_procedure`.
2. Add `template.md`, `requirements.yaml`, and a complete fictional `example.md` under that type.
3. Put all required headings and authoritative tables in `template.md`. Authoring instructions may be HTML comments, but rendered output must not contain comments, `{{ ... }}` placeholders, or authoring text.
4. Give every section and table a stable uppercase requirement ID. Declare cardinality, expected content, ontology hooks, lint rules, and one or more rubric criterion IDs in `requirements.yaml`.
5. Give every table descriptive required columns. Tables that carry authoritative content must include stable IDs, ownership, units or periods when relevant, and evidence or source context.
6. Add a complete mapping from every section/table requirement to rubric criterion IDs in the document-type rubric.
7. Keep the example fully fictional and executable enough to demonstrate the contract. Do not use customer names, copied policy paragraphs, secrets, or external instructions.

The renderer supports only dotted lookups such as `{{ document.title }}`. Missing values become visible `TBD`; the renderer does not execute expressions. Use `TBD`, an issue, or a waiver for unknown facts rather than inventing owners, thresholds, approvals, IDs, or dates.

## Context and precedence

Context sources are declared with a stable `reference_id`, `kind`, path, and `applies_when` selector. Selectors may filter by document type, business domain, jurisdiction, confidentiality, document status, tags, and effective date. A source is included only when all declared filters match.

The default order is highest to lowest:

1. Explicit reviewer steering for the current run.
2. Regulation.
3. Policy.
4. Standard.
5. Template requirements and document-type rubric.
6. Style guide.
7. Source-document style.

Conflicts are surfaced with both reference IDs. Equal-precedence conflicts are validation errors. A higher-precedence source may control the result only with a visible conflict record and rationale; lower-precedence guidance is not silently deleted. Context documents should state these relationships explicitly, as the fictional enterprise pack does for lifecycle governance and retention evidence.

## Ontology and rubric rules

Keep the ontology small and allow-listed. Add an entity only when a document type needs a stable, retrievable object with provenance. Add a relationship only with valid source/target types and a named graph layer. Do not create generic authoritative `RELATED_TO` edges. Renaming a canonical object must not change its stable ID.

All rubrics use the evidence-backed 0–4 scale: absent, weak, partial, complete, and exemplary. Each criterion declares evidence, severity, and hard-blocker semantics. A waiver explains an accepted gap and its downstream impact; it never increases the underlying score or hides an expired blocker.

## Versioning and digests

Use semantic versions. Increment:

- `PATCH` for wording or non-behavioral corrections that preserve the machine contract.
- `MINOR` for additive sections, columns, terms, context, or rubric criteria that remain backward-compatible.
- `MAJOR` for changed IDs, removed sections/columns, changed precedence semantics, changed required fields, or changed rendering behavior.

Every behavior-changing pack edit must update `version`, review the owner/effective dates, and regenerate every listed file digest. The manifest digest is the SHA-256 of canonical JSON for the manifest after removing `manifest_sha256` and `pack_sha256`; the pack digest is the SHA-256 of canonical JSON for the sorted `[{"path", "sha256"}]` file list. These digests exclude `manifest.yaml` to avoid a recursive self-digest.

Run the offline gate from the repository root:

```bash
uv sync --frozen
uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core
uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core --json
```

The digest values in a committed manifest must be regenerated after any pack file change. A reviewer should inspect the rendered empty and populated templates, examples, context applicability, precedence conflicts, and the exact diff before accepting a new version.

## Review checklist

- [ ] All files are listed and have current SHA-256 digests.
- [ ] No path escapes the pack root and no unsafe YAML tag or duplicate key is present.
- [ ] Every supported document type has a template, requirements map, and complete fictional example.
- [ ] Every required section/table has a rubric mapping; every mapping resolves.
- [ ] Required ontology hooks, IDs, controlled terms, context references, and precedence levels resolve.
- [ ] Empty and populated renders contain no HTML comments, placeholders, or authoring instructions.
- [ ] Policy/standard conflicts are explicit and the resolution follows declared precedence.
- [ ] No proprietary copied material, secrets, external links that become instructions, or unreviewed factual claims were introduced.
- [ ] The verifier, owned tests, Ruff, ty, offline pytest, `git diff --check`, and secret scan pass.
