from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from document_enhancer.retrieval.chunking import chunk_markdown

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.unit
def test_chunking_preserves_heading_paths_offsets_and_stable_ids(tmp_path: Path) -> None:
    markdown = """---
document_id: DOC-1
---

# Controlled Process

Introduction.

## Roles

| Role | Duty |
| --- | --- |
| Owner | Review |

### Escalation

Escalate exceptions to Risk.
"""
    digest = hashlib.sha256(markdown.encode()).hexdigest()

    first = chunk_markdown(
        markdown,
        run_id="run-1",
        bundle_path=tmp_path,
        source_digest=digest,
        final_digest=digest,
        chunk_size=200,
        chunk_overlap=20,
    )
    second = chunk_markdown(
        markdown,
        run_id="run-1",
        bundle_path=tmp_path,
        source_digest=digest,
        final_digest=digest,
        chunk_size=200,
        chunk_overlap=20,
    )

    assert [item.chunk_id for item in first] == [item.chunk_id for item in second]
    assert [item.text for item in first] == [item.text for item in second]
    assert any(item.heading_path == ("Controlled Process", "Roles") for item in first)
    assert any(item.heading_path == ("Controlled Process", "Roles", "Escalation") for item in first)
    assert all(markdown[item.start_index : item.end_index] == item.text for item in first)
    assert "| Owner | Review |" in "\n".join(item.text for item in first)


@pytest.mark.unit
def test_chunking_splits_oversized_sections_and_rejects_invalid_overlap(tmp_path: Path) -> None:
    markdown = (
        "# Long\n\n"
        "| Role | Duty |\n| --- | --- |\n| Owner | Review |\n\n"
        "```yaml\ncontrol:\n  cadence: monthly\n```\n\n"
        + "Paragraph with controlled evidence. "
        * 100
    )
    digest = hashlib.sha256(markdown.encode()).hexdigest()

    chunks = chunk_markdown(
        markdown,
        run_id="run-long",
        bundle_path=tmp_path,
        source_digest=digest,
        final_digest=digest,
        chunk_size=400,
        chunk_overlap=50,
    )

    assert len(chunks) > 2
    assert all(len(item.text) <= 400 for item in chunks)
    rendered = "\n".join(item.text for item in chunks)
    assert "| Owner | Review |" in rendered
    assert "```yaml\ncontrol:\n  cadence: monthly\n```" in rendered
    with pytest.raises(ValueError, match="overlap"):
        chunk_markdown(
            markdown,
            run_id="run-long",
            bundle_path=tmp_path,
            source_digest=digest,
            final_digest=digest,
            chunk_size=400,
            chunk_overlap=400,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "document_type", ["process", "methodology", "standard", "desktop_procedure"]
)
def test_chunking_is_reproducible_for_every_governed_document_type(
    tmp_path: Path, document_type: str
) -> None:
    markdown = (
        ROOT / "reference_packs/enterprise_core/templates" / document_type / "example.md"
    ).read_text(encoding="utf-8")
    digest = hashlib.sha256(markdown.encode()).hexdigest()

    first = chunk_markdown(
        markdown,
        run_id=f"run-{document_type}",
        bundle_path=tmp_path,
        source_digest=digest,
        final_digest=digest,
    )
    second = chunk_markdown(
        markdown,
        run_id=f"run-{document_type}",
        bundle_path=tmp_path,
        source_digest=digest,
        final_digest=digest,
    )

    assert first
    assert [item.chunk_id for item in first] == [item.chunk_id for item in second]
    assert all(item.heading_path for item in first)
