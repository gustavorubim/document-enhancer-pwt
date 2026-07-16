from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

import pytest
from evals.public_sources import (
    PublicSourceError,
    _NoRedirectHandler,
    fetch_registry,
    load_registry,
)


@pytest.mark.security
def test_synthetic_corpus_has_injection_as_data_but_no_secret_shapes() -> None:
    corpus = Path("fixtures/synthetic/corpus")
    text = "\n".join(path.read_text(encoding="utf-8") for path in corpus.rglob("*.md"))
    lowered = text.lower()
    assert "ignore prior instructions" in lowered
    assert "begin private key" not in lowered
    assert "sk-" not in lowered
    assert "AIza" not in text
    assert "password=" not in lowered
    assert "api_key=" not in lowered

    severe_gold = json.loads(
        Path(corpus, "incident_escalation_desktop_procedure", "gold.json").read_text(
            encoding="utf-8"
        )
    )
    untrusted = [
        block for block in severe_gold["variants"]["severe"]["raw_blocks"] if block["untrusted"]
    ]
    assert len(untrusted) == 1
    assert "hidden system prompt" in untrusted[0]["text"]


@pytest.mark.security
def test_safe_yaml_loader_does_not_construct_python_objects(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.yaml"
    path.write_text(
        """schema_version: '0.1'\nallowlisted_hosts: [example.org]\nsources:\n  - source_id: BAD\n    url: https://example.org/file.pdf\n    title: bad\n    publisher: bad\n    expected_media_types: [application/pdf]\n    max_bytes: 10\n    sha256: null\n    license: {terms: fetch, review_status: pending}\n    destination: !!python/object/apply:os.system ['echo unsafe']\n""",
        encoding="utf-8",
    )
    with pytest.raises(PublicSourceError, match="unable to read public-source registry"):
        load_registry(path)


@pytest.mark.security
def test_fetch_rejects_destination_traversal_and_off_list_mutation(tmp_path: Path) -> None:
    registry = tmp_path / "bad.yaml"
    registry.write_text(
        """schema_version: '0.1'\nallowlisted_hosts: [example.org]\nsources:\n  - source_id: BAD\n    url: https://example.org/file.pdf\n    title: bad\n    publisher: bad\n    expected_media_types: [application/pdf]\n    max_bytes: 10\n    sha256: null\n    license: {terms: fetch, review_status: pending}\n    destination: ../escape.pdf\n""",
        encoding="utf-8",
    )
    with pytest.raises(PublicSourceError, match="escapes fetch root|unsafe path"):
        fetch_registry(registry, tmp_path / "downloads", dry_run=True)


@pytest.mark.security
def test_fetch_blocks_redirects_oversize_media_and_digest_mismatch(tmp_path: Path) -> None:
    class FakeHeaders:
        def __init__(self, content_type: str, content_length: str | None = None) -> None:
            self.values = {"Content-Type": content_type}
            if content_length is not None:
                self.values["Content-Length"] = content_length

        def get(self, key: str, default: str = "") -> str:
            return self.values.get(key, default)

    class FakeResponse:
        def __init__(
            self,
            content: bytes,
            content_type: str = "application/pdf",
            content_length: str | None = None,
        ) -> None:
            self.content = content
            self.position = 0
            self.headers = FakeHeaders(content_type, content_length)

        def read(self, amount: int = -1) -> bytes:
            if amount < 0:
                amount = len(self.content)
            result = self.content[self.position : self.position + amount]
            self.position += len(result)
            return result

    class FakeOpener:
        def __init__(self, response: FakeResponse) -> None:
            self.response = response

        def open(self, *args, **kwargs) -> FakeResponse:
            return self.response

    def write_registry(name: str, *, max_bytes: int, media: str, digest: str | None = None) -> Path:
        path = tmp_path / f"{name}.yaml"
        digest_value = "null" if digest is None else f"'{digest}'"
        path.write_text(
            f"""schema_version: '0.1'\nallowlisted_hosts: [example.org]\nsources:\n  - source_id: TEST\n    url: https://example.org/file.pdf\n    title: test\n    publisher: test\n    expected_media_types: [{media}]\n    max_bytes: {max_bytes}\n    sha256: {digest_value}\n    license: {{terms: fetch, review_status: pending}}\n    destination: file.pdf\n""",
            encoding="utf-8",
        )
        return path

    with pytest.raises(PublicSourceError, match="oversized"):
        fetch_registry(
            write_registry("length", max_bytes=2, media="application/pdf"),
            tmp_path / "out",
            dry_run=False,
            opener=FakeOpener(FakeResponse(b"abc", content_length="3")),
        )
    with pytest.raises(PublicSourceError, match="media type"):
        fetch_registry(
            write_registry("media", max_bytes=10, media="application/pdf"),
            tmp_path / "out",
            dry_run=False,
            opener=FakeOpener(FakeResponse(b"abc", content_type="text/html")),
        )
    with pytest.raises(PublicSourceError, match="digest mismatch"):
        fetch_registry(
            write_registry("digest", max_bytes=10, media="application/pdf", digest="0" * 64),
            tmp_path / "out",
            dry_run=False,
            opener=FakeOpener(FakeResponse(b"abc")),
        )

    with pytest.raises(PublicSourceError, match="redirect blocked"):
        _NoRedirectHandler().redirect_request(
            urllib.request.Request("https://example.org/file.pdf"),
            None,
            302,
            "Found",
            {},
            "https://evil.example.net/file.pdf",
        )

    assert hashlib.sha256(b"abc").hexdigest() != "0" * 64
    assert load_registry(Path("fixtures/public/sources.yaml"))["default_mode"] == "dry_run"
