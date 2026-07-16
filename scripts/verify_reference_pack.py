#!/usr/bin/env python3
"""Verify one reference pack without network access or provider credentials."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from document_enhancer.references.errors import ReferencePackError
from document_enhancer.references.loader import (
    ApplicabilityContext,
    EnterpriseReferencePackLoader,
    ReferencePackValidator,
)

DOCUMENT_TYPES = ("process", "methodology", "standard", "desktop_procedure")
DEFAULT_TAGS = frozenset({"governed_document", "controlled_activity", "records"})


def _check_contexts(pack_path: Path, document_types: list[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    conflicts: list[str] = []
    loader = EnterpriseReferencePackLoader()
    try:
        pack = loader.load(pack_path)
    except ReferencePackError as exc:
        return [str(exc)], conflicts
    for document_type in document_types:
        context = ApplicabilityContext(document_type=document_type, tags=DEFAULT_TAGS)
        resolution = pack.resolve_context(context)
        conflicts.extend(resolution.conflicts)
        if not resolution.ok:
            errors.extend(resolution.errors)
        rendered_empty = pack.render(document_type, {})
        rendered_populated = pack.render(
            document_type,
            {
                "document": {
                    "id": "DOC-VERIFY-0001",
                    "title": "Fictional verification render",
                    "version": "DOCV-VERIFY-0001-V1",
                    "status": "draft",
                    "owner": "ROLE-DOC-VERIFY",
                    "effective_date": "2026-01-01",
                    "next_review_date": "2027-01-01",
                },
                "sections": {"purpose": "Rendered test content."},
            },
        )
        for label, rendered in (("empty", rendered_empty), ("populated", rendered_populated)):
            if "<!--" in rendered:
                errors.append(f"{document_type} {label} output contains an HTML comment")
            if "{{" in rendered or "}}" in rendered:
                errors.append(f"{document_type} {label} output contains an unresolved placeholder")
            if "AUTHORING:" in rendered:
                errors.append(f"{document_type} {label} output contains authoring instructions")
    return errors, conflicts


def verify(path: Path, document_type: str | None = None) -> dict[str, Any]:
    validator = ReferencePackValidator()
    report = validator.report(path)
    errors = list(report.errors)
    conflicts: list[str] = []
    selected = [document_type] if document_type else list(DOCUMENT_TYPES)
    if not errors:
        context_errors, conflicts = _check_contexts(path, selected)
        errors.extend(context_errors)
    result: dict[str, Any] = {
        "pack": str(path),
        "ok": not errors,
        "document_types": selected,
        "errors": errors,
        "warnings": list(report.warnings),
        "conflicts": conflicts,
        "details": report.details,
    }
    if not errors:
        pack = EnterpriseReferencePackLoader().load(path)
        result["pack_id"] = pack.pack_id
        result["version"] = pack.version
        result["pack_sha256"] = pack.pack_sha256
        result["file_count"] = len(pack.files)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path, help="Reference-pack directory containing manifest.yaml")
    parser.add_argument(
        "--document-type", choices=DOCUMENT_TYPES, help="Verify one document type only"
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)
    result = verify(args.pack, args.document_type)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["ok"]:
        print(
            f"Reference pack OK: {result['pack_id']} {result['version']} "
            f"({result['file_count']} files, {', '.join(result['document_types'])})"
        )
    else:
        print("Reference pack FAILED:", file=sys.stderr)
        for error in result["errors"]:
            print(f"- {error}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
