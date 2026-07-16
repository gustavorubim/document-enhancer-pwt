# Prompt-pack authoring

Prompt packs are source-controlled, versioned Markdown/YAML inputs to the model gateway. The
production pack lives under `prompt_packs/<pack_id>/`; production instruction text must not be
added to Python constants, decorators, f-strings, tests that stand in for the pack, or CLI code.
The Python layer owns loading, validation, delimiters, schema rendering, digests, and snapshots.

## Layout and manifest

Each pack has a `manifest.yaml` and Markdown stage templates. Stage templates have YAML front
matter containing at least `prompt_id` and `stage`. Shared fragments are Markdown files and may
use the bounded `{{include "shared/file.md"}}` form. Includes are resolved only beneath the pack
root, must be manifest-listed, and are rejected on missing files, traversal, symlink escape, or
cycles.

The manifest is the authority for prompt IDs, semantic version, owner/status, compatibility,
template and fragment paths, exact model route, output schema, allowed inputs, tools, budgets,
retry/safety policy, variables, composition order, required reference inputs, and SHA-256 file
digests. A behavior-changing prompt edit requires a version bump and refreshed digests. Do not
use `latest` model aliases.

Required reference inputs resolve from the selected reference pack, not from duplicated prompt
prose. Each resolved file is recorded with logical name, pack ID/version/digest, relative path,
kind, file digest, and byte size. Runtime reviewer answers, steering, waivers, and source text
are inputs, not reference-pack files.

## Composition and input boundaries

The composer emits the following visible order:

1. governed instructions (shared fragments and the stage template);
2. governed reference context (with pack/file metadata);
3. untrusted source/retrieved/query data;
4. reviewer inputs;
5. schema-only output contract with exact route and JSON Schema.

Source, retrieved text, reference text, reviewer fields, and query history are data. They cannot
override instructions, request tools, change schemas, reveal prompts, or cause browsing. Keep
source/reviewer variables out of template bodies; the composer inserts them only into their
delimited data blocks. Every variable has a declared type, required/default behavior, maximum
size, and escaping policy. Use `delimited` or JSON-safe escaping for content; `plain` is not
permitted for source or reviewer inputs.

The pack must keep shell, browser, network, URL context, search, code execution, computer use,
email, and external retrieval disabled. Structured stages return one JSON object matching the
checked-in schema; they do not return prose or tool calls.

## Versioning and review lifecycle

Use semantic versions. A patch release fixes wording without changing behavior; a minor release
adds prompts or compatible variables; a major release changes output meaning, required inputs,
composition semantics, or compatibility. Reviewers should inspect the rendered prompt, route,
schema, reference metadata, diff, security lint, and golden fake output before activation.

The normal lifecycle is `draft` → `active` → `deprecated` → `retired`. Retiring a pack requires
an integrator migration plan and preserved run-artifact readability. A run snapshot stores only
template/fragment digests, resolved reference metadata/digests, variable names and redacted
variable metadata, composition order, output schema/digest, and rendered prompt digest. It never
stores credentials or unnecessary raw source text.

## Validation and service API

From the repository root:

```bash
uv run python scripts/verify_prompt_pack.py prompt_packs/gemini_core \
  --reference-pack reference_packs/enterprise_core
```

The service API used by the future CLI is available from
`document_enhancer.prompting.services`:

- `list_prompts(pack)` returns prompt ID, stage, route, schema, path, and pack version.
- `show_prompt(pack, prompt_id)` returns manifest metadata; `composed=True` returns the exact
  bounded composition after reference resolution.
- `validate(pack, reference_pack=...)` returns a JSON-safe precise report.

`load_prompt_pack` fails closed before an API call when manifest fields, file digests, includes,
schema names, routes, variables, reference bindings, size limits, or security boundaries are
invalid. Golden composition coverage must run for process, methodology, standard, and desktop
procedure document types and all three configured Gemini model families. Fake outputs are
validated through the same Pydantic roots as production calls.
