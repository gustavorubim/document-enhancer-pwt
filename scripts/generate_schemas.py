"""Generate or verify deterministic JSON Schemas for domain artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from document_enhancer.domain.schema_registry import schema_models


def render_schema(model: type[BaseModel]) -> str:
    schema = model.model_json_schema()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def generate(output_dir: Path, *, check: bool = False) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    differences: list[str] = []
    for filename, model in sorted(schema_models().items()):
        destination = output_dir / filename
        rendered = render_schema(model)
        if check:
            if not destination.exists():
                differences.append(f"missing {destination}")
            elif destination.read_text(encoding="utf-8") != rendered:
                differences.append(f"out of date {destination}")
        else:
            destination.write_text(rendered, encoding="utf-8")
    if differences:
        for difference in differences:
            print(difference, file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if checked-in schemas drift")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "schemas",
    )
    args = parser.parse_args()
    return generate(args.output_dir, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
