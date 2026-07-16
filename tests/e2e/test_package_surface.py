import pytest

from document_enhancer import __version__


@pytest.mark.e2e
def test_package_surface_is_versioned() -> None:
    assert __version__ == "0.1.0"
