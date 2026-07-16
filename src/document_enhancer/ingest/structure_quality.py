"""Deterministic parser-quality signals and recovery routing."""

from __future__ import annotations

import re
from collections import Counter

from .models import (
    RawDocument,
    RecoveryThresholds,
    StructureQualityReport,
    StructureRoutingDecision,
)

_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+")


def _numbering_continuity(document: RawDocument) -> float:
    values: list[tuple[int, ...]] = []
    for block in document.blocks:
        if block.block_type not in {"heading", "list"}:
            continue
        match = _NUMBER_RE.match(block.text)
        if match:
            values.append(tuple(int(part) for part in match.group(1).split(".")))
    if len(values) < 2:
        return 1.0 if not values else 0.75
    good = 0
    for previous, current in zip(values, values[1:], strict=False):
        if (
            current[-1] == previous[-1] + 1
            or current[:-1] == previous
            or current[: len(previous)] == previous
        ):
            good += 1
    return good / (len(values) - 1)


def _toc_mismatches(document: RawDocument) -> int:
    headings = {
        str(block.attributes.get("title", block.text)).strip().lower()
        for block in document.blocks
        if block.block_type == "heading"
    }
    toc_blocks = [
        block
        for block in document.blocks
        if "table of contents" in block.text.lower() or block.attributes.get("toc")
    ]
    if not toc_blocks:
        return 0
    entries: list[str] = []
    for block in document.blocks:
        if block.block_type == "list" and block.ordinal > toc_blocks[0].ordinal:
            entries.extend(
                line.strip().lstrip("-+* ").split("  ", maxsplit=1)[0].strip().lower()
                for line in block.text.splitlines()
                if line.strip()
            )
    if not entries:
        return 1
    return sum(
        1 for entry in entries if entry and not any(entry in heading for heading in headings)
    )


def assess_structure(document: RawDocument) -> StructureQualityReport:
    substantive = [block for block in document.blocks if block.text.strip()]
    headings = [block for block in substantive if block.block_type == "heading"]
    heading_density = len(headings) / max(1, len(substantive))
    styles = [re.sub(r"\d+$", "", block.style or block.block_type).lower() for block in headings]
    style_consistency = (Counter(styles).most_common(1)[0][1] / len(styles)) if styles else 0.0
    numbering = _numbering_continuity(document)
    toc_mismatches = _toc_mismatches(document)
    tables = [block for block in substantive if block.block_type == "table"]
    layout_tables = [
        block
        for block in tables
        if int(block.attributes.get("column_count", 0) or 0) >= 4
        or len(block.text.splitlines()) == 1
    ]
    layout_table_score = len(layout_tables) / max(1, len(tables)) if tables else 0.0
    counts = Counter(
        block.text.strip().lower() for block in substantive if len(block.text.strip()) <= 160
    )
    repeated_furniture_count = sum(count - 1 for count in counts.values() if count > 1)
    long_blocks = [block for block in substantive if len(block.text) > 1200]
    if headings:
        first_heading = min(block.ordinal for block in headings)
        orphans = [block for block in substantive if block.ordinal < first_heading]
    else:
        orphans = substantive if len(substantive) > 1 else []
    orphan_ratio = len(orphans) / max(1, len(substantive))
    long_ratio = len(long_blocks) / max(1, len(substantive))
    warning_count = sum(warning.severity == "warning" for warning in document.warnings)
    error_count = sum(warning.severity == "error" for warning in document.warnings)
    heading_signal = min(1.0, heading_density / 0.20) if headings else 0.0
    furniture_signal = max(0.0, 1.0 - repeated_furniture_count / max(1, len(substantive)))
    warning_signal = max(0.0, 1.0 - (warning_count + 2 * error_count) / max(1, len(substantive)))
    toc_signal = 1.0 if toc_mismatches == 0 else max(0.0, 1.0 - toc_mismatches / 5)
    orphan_signal = max(0.0, 1.0 - orphan_ratio)
    long_signal = max(0.0, 1.0 - long_ratio)
    score = (
        0.18 * heading_signal
        + 0.16 * style_consistency
        + 0.12 * numbering
        + 0.12 * toc_signal
        + 0.10 * (1.0 - layout_table_score)
        + 0.12 * furniture_signal
        + 0.10 * orphan_signal
        + 0.05 * long_signal
        + 0.05 * warning_signal
    )
    warnings: list[str] = []
    if not headings and len(substantive) > 1:
        warnings.append("no_headings")
    if repeated_furniture_count:
        warnings.append("repeated_page_furniture_candidate")
    if layout_table_score > 0:
        warnings.append("layout_table_candidate")
    if toc_mismatches:
        warnings.append("toc_mismatch")
    if long_ratio:
        warnings.append("long_block_candidate")
    if error_count:
        warnings.append("parser_errors")
    return StructureQualityReport(
        substantive_block_count=len(substantive),
        heading_count=len(headings),
        heading_density=heading_density,
        heading_style_consistency=style_consistency,
        numbering_continuity=numbering,
        toc_mismatch_count=toc_mismatches,
        layout_table_score=layout_table_score,
        repeated_furniture_count=repeated_furniture_count,
        orphan_block_ratio=orphan_ratio,
        long_block_ratio=long_ratio,
        parser_warning_count=warning_count,
        parser_error_count=error_count,
        structure_score=max(0.0, min(1.0, score)),
        warnings=tuple(warnings),
    )


def route_structure(
    report: StructureQualityReport, thresholds: RecoveryThresholds | None = None
) -> StructureRoutingDecision:
    thresholds = thresholds or RecoveryThresholds()
    reasons: list[str] = []
    if report.structure_score < thresholds.minimum_structure_score:
        reasons.append("structure_score_below_threshold")
    if report.heading_style_consistency < thresholds.minimum_heading_consistency:
        reasons.append("heading_style_inconsistent")
    if report.toc_mismatch_count > thresholds.maximum_toc_mismatches:
        reasons.append("toc_mismatch")
    if report.orphan_block_ratio > thresholds.maximum_orphan_ratio:
        reasons.append("orphan_blocks")
    if report.long_block_ratio > thresholds.maximum_long_block_ratio:
        reasons.append("long_blocks")
    if report.parser_warning_count > thresholds.maximum_parser_warnings:
        reasons.append("parser_warnings")
    if report.parser_error_count:
        reasons.append("parser_errors")
    if report.layout_table_score >= 0.5:
        reasons.append("layout_table_signal")
    return StructureRoutingDecision(
        mode="llm_recovery" if reasons else "parser",
        reasons=tuple(dict.fromkeys(reasons)),
        score=report.structure_score,
    )


__all__ = ["assess_structure", "route_structure"]
