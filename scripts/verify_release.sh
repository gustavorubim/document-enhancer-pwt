#!/usr/bin/env bash
set -euo pipefail

source_root="$(git rev-parse --show-toplevel)"
tested_ref="${1:-HEAD}"
temporary_root="$(mktemp -d "${TMPDIR:-/tmp}/document-enhancer-release.XXXXXX")"
trap 'rm -rf "$temporary_root"' EXIT

clone="$temporary_root/clean-clone"
dist="$temporary_root/dist"
install_root="$temporary_root/isolated-install"
uv_cache="$temporary_root/uv-cache"

git clone --quiet --no-local "$source_root" "$clone"
git -C "$clone" checkout --quiet --detach "$tested_ref"
test -z "$(git -C "$clone" status --porcelain)"

(
  cd "$clone"
  uv sync --frozen
  uv run ruff format --check .
  uv run ruff check .
  uv run ty check
  uv run pytest -m "not live_model and not public_download"
  uv run python scripts/generate_schemas.py --check
  uv run python scripts/verify_reference_pack.py reference_packs/enterprise_core
  uv run python scripts/verify_prompt_pack.py prompt_packs/gemini_core --reference-pack reference_packs/enterprise_core
  uv run python scripts/generate_fixture_corpus.py --check
  uv run python scripts/run_evaluations.py --check
  uv build --out-dir "$dist"
  git diff --check
  test -z "$(git status --porcelain)"
)

wheel="$(find "$dist" -maxdepth 1 -type f -name '*.whl' -print -quit)"
test -n "$wheel"
mkdir -p "$install_root"
cp "$clone/fixtures/synthetic/corpus/monthly_loss_forecasting_methodology/clean.md" \
  "$install_root/source.md"

(
  cd "$install_root"
  export UV_CACHE_DIR="$uv_cache"
  uv run --isolated --with "$wheel" docenhance version >version.txt
  uv run --isolated --with "$wheel" docenhance --help >help.txt
  uv run --isolated --with "$wheel" docenhance run source.md \
    --document-type methodology \
    --run-dir "$install_root/runs" \
    --no-gate2 \
    --no-catalog-ingest \
    --json >run.json
  uv run --isolated --with "$wheel" docenhance audit \
    "$(python -c 'import json; print(json.load(open("run.json"))["run_id"])')" \
    --run-dir "$install_root/runs" \
    --json >audit.json
  grep -q '"status": "succeeded"' run.json
  grep -q '"status": "pass"' audit.json
)

tested_commit="$(git -C "$clone" rev-parse HEAD)"
wheel_digest="$(shasum -a 256 "$wheel" | awk '{print $1}')"
printf '{"clean_clone_gate":"passed","isolated_wheel":"passed","network_tests":"not_run","public_downloads":0,"provider_calls":0,"tested_commit":"%s","wheel_sha256":"%s"}\n' \
  "$tested_commit" "$wheel_digest"
