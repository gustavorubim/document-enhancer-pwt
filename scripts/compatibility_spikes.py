"""Run the offline WT0 ecosystem probes without exposing credentials."""

from __future__ import annotations

import json
import sys

from document_enhancer.compatibility import run_offline_spikes


def main() -> int:
    results = run_offline_spikes()
    json.dump(results, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if all(item["status"] == "pass" for item in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
