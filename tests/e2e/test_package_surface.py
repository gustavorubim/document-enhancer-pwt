import pytest

from document_enhancer import __version__
from document_enhancer.prompting.loader import bundled_prompt_pack_path
from document_enhancer.references.loader import bundled_reference_pack_path


@pytest.mark.e2e
def test_package_surface_is_versioned() -> None:
    assert __version__ == "0.1.0"


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
