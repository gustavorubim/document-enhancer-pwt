"""Opt-in live Gemini probes; never prints credentials or source content."""

from __future__ import annotations

import json
import sys

from pydantic import BaseModel

from document_enhancer.compatibility import run_live_spikes


class _Probe(BaseModel):
    ok: bool
    note: str


def main() -> int:
    import os

    if os.getenv("DOCENHANCE_RUN_LIVE") != "1":
        print("live checks are opt-in: set DOCENHANCE_RUN_LIVE=1", file=sys.stderr)
        return 2
    results = run_live_spikes(_Probe)
    json.dump(results, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if all(item["status"] == "pass" for item in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
