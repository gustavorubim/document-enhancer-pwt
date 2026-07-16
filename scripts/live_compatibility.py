"""Opt-in live Gemini probes; never prints credentials or source content."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from pydantic import BaseModel

from document_enhancer.compatibility import load_external_env, run_live_spikes


class _Probe(BaseModel):
    ok: bool
    note: str


def main() -> int:
    if os.getenv("DOCENHANCE_RUN_LIVE") != "1":
        print("live checks are opt-in: set DOCENHANCE_RUN_LIVE=1", file=sys.stderr)
        return 2
    env_file = Path("/Users/gvrubim/Documents/document-enhancer/.env")
    load_external_env(env_file)
    results = run_live_spikes(_Probe)
    json.dump(results, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if all(item["status"] == "pass" for item in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
