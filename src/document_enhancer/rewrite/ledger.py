"""Deterministic source-span ledger construction and coverage checks."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from document_enhancer.domain.enums import LedgerDisposition
from document_enhancer.domain.ids import validate_span_id
from document_enhancer.domain.questions import ContentLedger, ContentLedgerEntry


@dataclass(frozen=True)
class LedgerCoverage:
    """Machine-readable exact coverage result."""

    valid: bool
    expected_span_ids: tuple[str, ...]
    covered_span_ids: tuple[str, ...]
    missing_span_ids: tuple[str, ...]
    duplicate_span_ids: tuple[str, ...]
    unexpected_span_ids: tuple[str, ...]
    errors: tuple[str, ...] = ()


def _blocks(normalized: object) -> tuple[object, ...]:
    direct = getattr(normalized, "blocks", None)
    if direct is not None:
        return tuple(direct)
    raw = getattr(normalized, "raw", None)
    blocks = getattr(raw, "blocks", None)
    if blocks is not None:
        return tuple(blocks)
    if isinstance(normalized, Mapping):
        direct = normalized.get("blocks")
        if isinstance(direct, Sequence):
            return tuple(direct)
        raw = normalized.get("raw")
        if isinstance(raw, Mapping):
            raw_blocks = raw.get("blocks")
            if isinstance(raw_blocks, Sequence):
                return tuple(raw_blocks)
    raise ValueError("normalized document does not expose ordered source blocks")


def _value(block: object, name: str, default: Any = None) -> Any:
    if isinstance(block, Mapping):
        return block.get(name, default)
    return getattr(block, name, default)


def _slug(value: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", value.lower())
    return "-".join(tokens) or "source"


def _section_specs(target_sections: Sequence[Mapping[str, object]] | None) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    for item in target_sections or ():
        section_id = str(item.get("id", item.get("section_id", "")))
        heading = str(item.get("heading", item.get("title", section_id)))
        if not section_id:
            continue
        specs.append(
            {
                "section_id": section_id,
                "heading": heading,
                "anchor": str(item.get("anchor", _slug(heading))),
            }
        )
    return specs


def _pick_anchor(block: object, specs: Sequence[Mapping[str, str]]) -> str | None:
    if not specs:
        return None
    heading_path = _value(block, "heading_path", ()) or ()
    source_text = str(_value(block, "text", ""))
    haystack = " ".join([*(str(value) for value in heading_path), source_text]).lower()
    best: tuple[int, str] | None = None
    for spec in specs:
        tokens = [
            token for token in re.findall(r"[a-z0-9]+", spec["heading"].lower()) if len(token) > 3
        ]
        score = sum(token in haystack for token in tokens)
        if best is None or score > best[0]:
            best = (score, spec["anchor"])
    if best is not None and best[0] > 0:
        return best[1]
    overview = next(
        (spec["anchor"] for spec in specs if "overview" in spec["heading"].lower()), None
    )
    if overview:
        return overview
    return specs[0]["anchor"]


def _source_digest(normalized: object) -> str:
    raw = getattr(normalized, "raw", None)
    value = getattr(raw, "source_digest", None) or getattr(normalized, "source_digest", None)
    if isinstance(normalized, Mapping):
        raw_map = normalized.get("raw")
        if isinstance(raw_map, Mapping):
            value = raw_map.get("source_digest", value)
        value = normalized.get("source_digest", value)
    if not isinstance(value, str):
        raise ValueError("normalized document has no source digest")
    return value


def build_content_ledger(
    normalized: object,
    *,
    document_id: str,
    target_sections: Sequence[Mapping[str, object]] | None = None,
    dispositions: Mapping[str, LedgerDisposition | str | Mapping[str, object]] | None = None,
) -> ContentLedger:
    """Create exactly one deterministic disposition for every normalized source span.

    ``dispositions`` is an optional reviewed override.  It cannot add a span, remove a span, or
    silently split text; any such mismatch is rejected by the coverage validator.
    """

    blocks = _blocks(normalized)
    specs = _section_specs(target_sections)
    source_digest = _source_digest(normalized)
    entries: list[ContentLedgerEntry] = []
    for ordinal, block in enumerate(blocks):
        span_id = validate_span_id(
            str(_value(block, "source_span_id", _value(block, "span_id", "")))
        )
        text = str(_value(block, "text", ""))
        override = (dispositions or {}).get(span_id)
        disposition = LedgerDisposition.RETAINED
        target_anchor = _pick_anchor(block, specs)
        rationale = "Source span is retained verbatim until an approved checklist action changes its disposition."
        omitted_reason = None
        if isinstance(override, Mapping):
            raw_disposition = override.get("disposition", disposition)
            target_anchor = (
                str(override.get("target_anchor", target_anchor))
                if override.get("target_anchor")
                else target_anchor
            )
            rationale = str(override.get("rationale", rationale))
            override_map = cast(Mapping[str, object], override)
            omitted_reason = (
                str(override_map["omitted_reason"]) if override_map.get("omitted_reason") else None
            )
        else:
            raw_disposition = override or disposition
        disposition = LedgerDisposition(raw_disposition)
        if disposition is LedgerDisposition.OMITTED and not omitted_reason:
            omitted_reason = "Omitted only by an explicit reviewed disposition."
        entry_token = (
            hashlib.sha256(f"{source_digest}\0{ordinal}\0{span_id}".encode())
            .hexdigest()[:16]
            .upper()
        )
        entries.append(
            ContentLedgerEntry(
                ledger_entry_id=f"LEDGER-{entry_token}",
                source_span_id=span_id,
                disposition=disposition,
                target_anchor=target_anchor,
                rationale=rationale,
                omitted_reason=omitted_reason,
                source_text_digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                source_ordinal=ordinal,
            )
        )
    ledger_token = (
        hashlib.sha256(
            (
                source_digest + "\0" + "\0".join(entry.model_dump_json() for entry in entries)
            ).encode()
        )
        .hexdigest()[:16]
        .upper()
    )
    ledger = ContentLedger(
        ledger_id=f"LEDGER-{ledger_token}",
        document_id=document_id,
        entries=entries,
        complete=True,
        digest=hashlib.sha256(
            "\n".join(entry.model_dump_json() for entry in entries).encode()
        ).hexdigest(),
    )
    ledger.assert_coverage(
        validate_span_id(str(_value(block, "source_span_id", _value(block, "span_id", ""))))
        for block in blocks
    )
    return ledger


def validate_content_ledger(
    ledger: ContentLedger,
    source_span_ids: Iterable[str],
    *,
    source_texts: Mapping[str, str] | None = None,
) -> LedgerCoverage:
    """Validate complete, unique coverage and optional source-text digests."""

    expected = tuple(validate_span_id(str(span_id)) for span_id in source_span_ids)
    covered = tuple(entry.source_span_id for entry in ledger.entries)
    counts: dict[str, int] = {}
    for span_id in covered:
        counts[span_id] = counts.get(span_id, 0) + 1
    missing = tuple(sorted(set(expected) - set(covered)))
    duplicates = tuple(sorted(span_id for span_id, count in counts.items() if count > 1))
    unexpected = tuple(sorted(set(covered) - set(expected)))
    errors = list(ledger.coverage_errors(expected))
    if source_texts:
        for entry in ledger.entries:
            text = source_texts.get(entry.source_span_id)
            if text is not None and entry.source_text_digest:
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if digest != entry.source_text_digest:
                    errors.append(f"source text digest mismatch: {entry.source_span_id}")
    valid = not errors and ledger.complete
    return LedgerCoverage(
        valid=valid,
        expected_span_ids=expected,
        covered_span_ids=covered,
        missing_span_ids=missing,
        duplicate_span_ids=duplicates,
        unexpected_span_ids=unexpected,
        errors=tuple(errors),
    )


create_content_ledger = build_content_ledger
validate_ledger_coverage = validate_content_ledger


__all__ = [
    "LedgerCoverage",
    "build_content_ledger",
    "create_content_ledger",
    "validate_content_ledger",
    "validate_ledger_coverage",
]
