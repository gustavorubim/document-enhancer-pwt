#!/usr/bin/env bash
set -euo pipefail

wheel="${1:?usage: scripts/smoke_install.sh DIST_WHEEL}"
test -f "$wheel"
uv run --isolated --with "$wheel" docenhance --help >/dev/null
uv run --isolated --with "$wheel" docenhance version >/dev/null
