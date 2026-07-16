import pytest

from document_enhancer.logging import redact


@pytest.mark.security
def test_redaction_covers_common_google_token_shapes() -> None:
    assert redact("access_token=demo-token") == "access_token=[REDACTED]"
    assert "secret-value" not in redact("secret=secret-value")
