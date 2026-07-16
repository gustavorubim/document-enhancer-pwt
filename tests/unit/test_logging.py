from document_enhancer.logging import redact, safe_event


def test_redaction_removes_provider_credentials() -> None:
    text = "GOOGLE_API_KEY=demo-value"
    assert "demo-value" not in redact(text)
    assert "REDACTED" in redact(text)


def test_safe_event_is_metadata_only() -> None:
    event = safe_event("model_call", model="gemini-3.5-flash", api_key="secret")
    assert event["model"] == "gemini-3.5-flash"
    assert event["api_key"] == "[REDACTED]"
