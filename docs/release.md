# Release verification

The default release gate is offline. It never calls Gemini or downloads public sources. Run it in
the developer checkout exactly as documented in `AGENTS.md`, including fixture and evaluation drift
checks. Then prove independence from that checkout with:

```bash
scripts/verify_release.sh HEAD
```

The script creates a temporary clone with `git clone --no-local`, checks out the tested commit in
detached mode, confirms the clone is clean, runs frozen sync, Ruff format/lint, ty, all non-live and
non-public tests, schema/reference/prompt/fixture/evaluation checks, and builds the distributions.
It then changes to a separate directory, installs only the wheel through `uv --isolated`, runs the
CLI, validates the bundled prompt/reference packs, and starts a governed workflow through the
expected human-review pause (exit 10). The separate M8 offline demo proves full audit/export/RAG
completion. The temporary clone, install root, and UV cache are deleted on exit.

Successful stdout is one JSON object containing `clean_clone_gate=passed`,
`isolated_wheel=passed`, the tested commit and wheel SHA-256, plus zero provider/public calls. Save
that object with the release record.

The repository-level four-document governed proof is separate from gold replay. It invokes the
actual CLI for the checked-in complete process, methodology, standard, and desktop-procedure
examples with `enterprise_core` selected, crosses Gate 1, pauses for Gate 2 approval, resumes
through strict audit and package/catalog promotion, then runs offline `rag search` and `rag ask`:

```bash
uv run python scripts/run_governed_dod_proof.py \
  --output .document-enhancer/governed-dod --force
```

The resulting `governed-dod-result.json` records each run ID, audit status, package row counts,
catalog generation, search count, answer status/citation count, and zero provider calls/public
downloads. An altered or incomplete source does not qualify for this exact-digest governed-example
path and remains fail-closed at strict audit.

A live report is separate and opt-in:

```bash
DOCENHANCE_RUN_LIVE=1 uv run python scripts/run_live_evaluations.py \
  --output evals/reports/m8-live.json
```

The live script reads credentials only from the process environment. It records each exact route as
passed, unavailable, retired, or failed, along with safe latency/usage/fallback metadata. Do not
commit a report containing organization-specific project/location metadata without review.

Public downloads are also separate. Validate the registry without network or writes:

```bash
uv run python scripts/fetch_public_sources.py --dry-run
```

Actual fetches require `--fetch`; the script permits only allow-listed HTTPS official hosts, blocks
redirects, enforces one pinned media type, response size, SHA-256, safe destination, and reviewed
fetch-only usage terms. Downloaded documents are not committed or treated as organization-specific
gold without an independent redistribution review.
