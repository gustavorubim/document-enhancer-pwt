"""Parser dispatch and the deterministic ingest/normalize pipeline."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from document_enhancer.errors import UnsupportedInputError

from .docx import DocxParser
from .markdown import MarkdownParser, TextParser
from .models import NormalizedDocument, RawDocument, RecoveryThresholds
from .normalize import normalize_document
from .pdf import PdfParser


class ParserLike(Protocol):
    supported_suffixes: frozenset[str]

    def can_parse(self, source: Path) -> bool: ...

    def parse(self, source: Path) -> RawDocument: ...


class ParserRegistry:
    """Ordered parser registry compatible with the WT0 ``DocumentParser`` port."""

    def __init__(self, parsers: Iterable[ParserLike] | None = None) -> None:
        self.parsers = tuple(
            parsers
            or (
                MarkdownParser(),
                TextParser(),
                DocxParser(),
                PdfParser(),
            )
        )

    def parser_for(self, source: Path) -> ParserLike:
        for parser in self.parsers:
            if parser.can_parse(source):
                return parser
        supported = sorted(
            suffix for parser in self.parsers for suffix in parser.supported_suffixes
        )
        raise UnsupportedInputError(
            f"Unsupported input suffix: {source.suffix or '<none>'}",
            detail=f"supported={', '.join(supported)}",
        )

    def parse(self, source: Path) -> RawDocument:
        parser = self.parser_for(source)
        return parser.parse(source)


class DocumentIngestor:
    """High-level deterministic parser plus normalization facade."""

    def __init__(
        self,
        *,
        registry: ParserRegistry | None = None,
        thresholds: RecoveryThresholds | None = None,
    ) -> None:
        self.registry = registry or ParserRegistry()
        self.thresholds = thresholds or RecoveryThresholds()

    def parse(self, source: Path) -> RawDocument:
        return self.registry.parse(source)

    def ingest(self, source: Path) -> NormalizedDocument:
        return normalize_document(self.parse(source), thresholds=self.thresholds)


def parse_source(source: Path, *, registry: ParserRegistry | None = None) -> RawDocument:
    return (registry or ParserRegistry()).parse(source)


def ingest_source(
    source: Path,
    *,
    registry: ParserRegistry | None = None,
    thresholds: RecoveryThresholds | None = None,
) -> NormalizedDocument:
    raw = parse_source(source, registry=registry)
    return normalize_document(raw, thresholds=thresholds)


__all__ = ["DocumentIngestor", "ParserRegistry", "ingest_source", "parse_source"]
