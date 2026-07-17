#!/usr/bin/env bash
set -euo pipefail

# This is the fast feedback loop for the only supported authoring path.
mode="${1:-fast}"
if [[ "$mode" != "fast" && "$mode" != "full" ]]; then
  echo "usage: scripts/gate_core.sh [fast|full]" >&2
  exit 2
fi

export PYTHONPATH="${PWD}/src${PYTHONPATH:+:${PYTHONPATH}}"
python_bin="${PYTHON_BIN:-}"
if [[ -z "$python_bin" && -x "${PWD}/.venv/bin/python" ]]; then
  python_bin="${PWD}/.venv/bin/python"
fi
if [[ -z "$python_bin" ]]; then
  python_bin="$(command -v python || true)"
fi
if [[ -z "$python_bin" ]]; then
  echo "python is required for the core gate" >&2
  exit 3
fi
ty_bin="${TY_BIN:-}"
if [[ -z "$ty_bin" ]]; then
  ty_bin="$(command -v ty || true)"
fi
if [[ -z "$ty_bin" && -x "${PWD}/.venv/bin/ty" ]]; then
  ty_bin="${PWD}/.venv/bin/ty"
fi
if [[ -z "$ty_bin" ]]; then
  echo "ty is required for the core gate" >&2
  exit 3
fi
"$python_bin" -m ruff format --check src/document_enhancer/core tests/unit/core tests/e2e
"$python_bin" -m ruff check src/document_enhancer/core tests/unit/core tests/e2e
"$ty_bin" check src/document_enhancer/core tests/unit/core tests/e2e
"$python_bin" -c 'from pathlib import Path; from document_enhancer.core.recipes import load_recipe; recipe = load_recipe(Path("reference_packs/enterprise_core"), document_type="process"); assert len(recipe.recipe_digest) == 64'

if [[ "$mode" == "fast" ]]; then
  "$python_bin" -m pytest -q tests/unit/core
else
  "$python_bin" -m pytest -q tests/unit/core tests/e2e/test_core_characterization.py tests/e2e/test_core_document_types.py
fi
