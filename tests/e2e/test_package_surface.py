from pathlib import Path

import pytest

from document_enhancer import __version__
from document_enhancer.cli import _resolve_pack_paths
from document_enhancer.domain import BlockSegment, allocate_segment_id
from document_enhancer.prompting.loader import bundled_prompt_pack_path
from document_enhancer.references.loader import bundled_reference_pack_path


@pytest.mark.e2e
def test_package_surface_is_versioned() -> None:
    assert __version__ == "0.1.0"


@pytest.mark.e2e
def test_split_segment_contract_is_public() -> None:
    assert BlockSegment.__name__ == "BlockSegment"
    assert allocate_segment_id("SPAN-ABCDEFGH", 0, 1, "a" * 64).startswith("SEG-")


@pytest.mark.e2e
def test_source_checkout_resolves_default_reference_pack() -> None:
    pack = bundled_reference_pack_path()

    assert (pack / "manifest.yaml").is_file()
    assert (pack / "templates" / "process" / "template.md").is_file()


@pytest.mark.e2e
def test_source_checkout_resolves_default_prompt_pack() -> None:
    pack = bundled_prompt_pack_path()

    assert (pack / "manifest.yaml").is_file()
    assert (pack / "structure" / "triage.md").is_file()
    assert (pack / "rag" / "grounded-answer.md").is_file()


@pytest.mark.e2e
def test_missing_source_relative_defaults_resolve_to_bundled_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    prompt, reference = _resolve_pack_paths(
        Path("prompt_packs/gemini_core"), Path("reference_packs/enterprise_core")
    )
    assert (prompt / "manifest.yaml").is_file()
    assert (reference / "manifest.yaml").is_file()
