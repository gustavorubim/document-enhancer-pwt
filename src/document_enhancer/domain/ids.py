"""Readable, deterministic identifier validation and allocation."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable

from document_enhancer.domain.enums import EntityType

IDENTIFIER_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
SPAN_ID_RE = re.compile(r"^SPAN-[A-Z0-9]{8,64}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

ENTITY_PREFIXES: dict[EntityType, str] = {
    EntityType.DOCUMENT_IDENTITY: "DOC",
    EntityType.DOCUMENT_VERSION: "DOCV",
    EntityType.SECTION: "SEC",
    EntityType.STATEMENT: "STMT",
    EntityType.TABLE: "TBL",
    EntityType.FIGURE: "FIG",
    EntityType.PROCESS: "PROC",
    EntityType.PROCESS_STEP: "STEP",
    EntityType.METHODOLOGY: "METH",
    EntityType.METHODOLOGY_STEP: "MSTEP",
    EntityType.ACTIVITY: "ACT",
    EntityType.DECISION: "DEC",
    EntityType.TRIGGER: "TRG",
    EntityType.REQUIREMENT: "REQ",
    EntityType.CONTROL: "CTRL",
    EntityType.RISK: "RISK",
    EntityType.POLICY: "POL",
    EntityType.STANDARD: "STD",
    EntityType.REGULATION: "REG",
    EntityType.APPROVAL: "APPR",
    EntityType.EVIDENCE: "EVD",
    EntityType.RECORD: "REC",
    EntityType.ROLE: "ROLE",
    EntityType.ORGANIZATION: "ORG",
    EntityType.ESCALATION_PATH: "ESC",
    EntityType.SYSTEM: "SYS",
    EntityType.DATA_ASSET: "DATA",
    EntityType.DATA_ELEMENT: "ELEM",
    EntityType.INPUT: "IN",
    EntityType.OUTPUT: "OUT",
    EntityType.CALCULATOR: "CALC",
    EntityType.MODEL: "MODEL",
    EntityType.PARAMETER: "PARAM",
    EntityType.RULE: "RULE",
    EntityType.METRIC: "METRIC",
    EntityType.THRESHOLD: "THR",
    EntityType.FORMULA: "FORM",
    EntityType.SERVICE_LEVEL: "SLA",
    EntityType.ASSUMPTION: "ASM",
    EntityType.LIMITATION: "LIM",
    EntityType.EXCEPTION: "EXC",
    EntityType.DEPENDENCY: "DEP",
    EntityType.PRECONDITION: "PRE",
    EntityType.COMPLETION_CONDITION: "DONE",
    EntityType.GLOSSARY_TERM: "TERM",
}

ENTITY_PREFIX_ALIASES: dict[EntityType, frozenset[str]] = {
    EntityType.DOCUMENT_VERSION: frozenset({"DOCV", "VER"}),
    EntityType.STATEMENT: frozenset({"STMT", "STATEMENT"}),
    EntityType.TABLE: frozenset({"TBL", "TABLE"}),
    EntityType.FIGURE: frozenset({"FIG", "FIGURE"}),
    EntityType.METHODOLOGY_STEP: frozenset({"MSTEP", "METHSTEP"}),
    EntityType.EVIDENCE: frozenset({"EVD", "EVID"}),
    EntityType.INPUT: frozenset({"IN", "INPUT"}),
    EntityType.OUTPUT: frozenset({"OUT", "OUTPUT"}),
    EntityType.MODEL: frozenset({"MODEL", "MODL"}),
}


def _slug(value: str, *, fallback: str = "ITEM") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    tokens = re.findall(r"[A-Za-z0-9]+", normalized.upper())
    return "-".join(tokens)[:48] or fallback


def validate_identifier(value: str, *, label: str = "identifier") -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"{label} must be uppercase, hyphen-separated, and human-readable; got {value!r}"
        )
    return value


def validate_entity_id(value: str, entity_type: EntityType | None = None) -> str:
    value = validate_identifier(value, label="entity id")
    if entity_type is None:
        return value
    prefix = ENTITY_PREFIXES[entity_type]
    aliases = ENTITY_PREFIX_ALIASES.get(entity_type, frozenset({prefix}))
    if value.startswith("PROV-"):
        provisional_prefix = value.split("-", 2)[1]
        if provisional_prefix not in aliases:
            raise ValueError(f"provisional id {value!r} does not match {entity_type.value}")
    elif value.split("-", 1)[0] not in aliases:
        raise ValueError(
            f"id {value!r} must use one of the prefixes {sorted(aliases)} for {entity_type.value}"
        )
    return value


def validate_span_id(value: str) -> str:
    if not isinstance(value, str) or not SPAN_ID_RE.fullmatch(value):
        raise ValueError("span_id must match SPAN-<uppercase stable token>")
    return value


def validate_sha256(value: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ValueError("digest must be a 64-character hexadecimal SHA-256 digest")
    return value.lower()


def allocate_provisional_id(
    entity_type: EntityType,
    seed: str,
    *,
    existing_ids: Iterable[str] = (),
    namespace: str = "",
) -> str:
    """Allocate a deterministic reviewable provisional ID.

    The seed, namespace, and entity type determine the base ID. Existing IDs
    are considered so allocation remains unique in the current graph.
    """

    taken = set(existing_ids)
    prefix = ENTITY_PREFIXES[entity_type]
    digest = hashlib.sha256(f"{namespace}\0{entity_type.value}\0{seed}".encode()).hexdigest()
    base = f"PROV-{prefix}-{_slug(seed)}-{digest[:10].upper()}"
    candidate = base
    counter = 2
    while candidate in taken:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def allocate_span_id(document_digest: str, ordinal: int, block_type: str, text: str) -> str:
    """Return a stable span ID independent of later document rewrites."""

    validate_sha256(document_digest)
    if ordinal < 0:
        raise ValueError("ordinal must be non-negative")
    token = (
        hashlib.sha256(f"{document_digest}\0{ordinal}\0{block_type}\0{text}".encode())
        .hexdigest()[:20]
        .upper()
    )
    return f"SPAN-{token}"


def allocate_segment_id(
    parent_span_id: str,
    char_start: int,
    char_end: int,
    slice_sha256: str,
) -> str:
    """Derive a reproducible segment ID from its parent and exact slice identity."""

    validate_span_id(parent_span_id)
    slice_sha256 = validate_sha256(slice_sha256)
    if char_start < 0 or char_end <= char_start:
        raise ValueError("segment character range must be strictly positive")
    token = (
        hashlib.sha256(f"{parent_span_id}\0{char_start}\0{char_end}\0{slice_sha256}".encode())
        .hexdigest()[:16]
        .upper()
    )
    return f"SEG-{token}"


def ensure_unique_ids(ids: Iterable[str]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for identifier in ids:
        if identifier in seen:
            duplicates.add(identifier)
        seen.add(identifier)
    if duplicates:
        values = ", ".join(sorted(duplicates))
        raise ValueError(f"duplicate IDs: {values}")


__all__ = [
    "ENTITY_PREFIXES",
    "ENTITY_PREFIX_ALIASES",
    "IDENTIFIER_RE",
    "SHA256_RE",
    "SPAN_ID_RE",
    "allocate_provisional_id",
    "allocate_segment_id",
    "allocate_span_id",
    "ensure_unique_ids",
    "validate_entity_id",
    "validate_identifier",
    "validate_sha256",
    "validate_span_id",
]
