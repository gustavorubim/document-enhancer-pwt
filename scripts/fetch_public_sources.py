#!/usr/bin/env python3
"""Dry-run-first fetcher for the allow-listed public-source registry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.public_sources import PublicSourceError, fetch_registry, records_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("fixtures/public/sources.yaml"))
    parser.add_argument("--destination-root", type=Path, default=Path("fixtures/public/downloads"))
    parser.add_argument("--source-id", action="append", dest="source_ids")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print planned fetches without network or file writes (default)",
    )
    mode.add_argument(
        "--fetch",
        action="store_true",
        help="opt into downloading and atomically promoting validated bytes",
    )
    args = parser.parse_args()
    try:
        records = fetch_registry(
            args.registry,
            args.destination_root,
            dry_run=not args.fetch,
            source_ids=set(args.source_ids) if args.source_ids else None,
        )
    except PublicSourceError as exc:
        parser.error(str(exc))
    print(records_json(records), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
