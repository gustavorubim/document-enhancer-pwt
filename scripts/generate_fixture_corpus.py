#!/usr/bin/env python3
"""Generate or verify the deterministic WT9 synthetic fixture corpus."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.corpus import generate_corpus  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("fixtures/synthetic/corpus"))
    parser.add_argument(
        "--check", action="store_true", help="verify generated files without changing them"
    )
    args = parser.parse_args()
    try:
        paths = generate_corpus(args.output_dir, check=args.check)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        f"{'verified' if args.check else 'generated'} {len(paths)} corpus files in {args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
