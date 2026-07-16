from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from evals.public_sources import PublicSourceError, fetch_registry, load_registry

REGISTRY = Path("fixtures/public/sources.yaml")


@pytest.mark.unit
def test_public_registry_is_valid_and_allowlisted() -> None:
    registry = load_registry(REGISTRY)
    hosts = {host.lower() for host in registry["allowlisted_hosts"]}
    assert len(registry["sources"]) == 4
    for source in registry["sources"]:
        assert source["url"].startswith("https://")
        assert source["url"].split("/", 3)[2].lower() in hosts
        assert source["destination"]
        assert source["max_bytes"] > 0
        assert source["license"]["review_status"] == "fetch_only_reviewed"


@pytest.mark.unit
def test_dry_run_never_calls_opener_or_writes_files(tmp_path: Path) -> None:
    class ExplodingOpener:
        def open(self, *args, **kwargs):
            raise AssertionError("dry-run called network opener")

    records = fetch_registry(REGISTRY, tmp_path, dry_run=True, opener=ExplodingOpener())
    assert len(records) == 4
    assert {record.status for record in records} == {"dry_run"}
    assert not list(tmp_path.rglob("*"))


@pytest.mark.unit
def test_explicit_dry_run_flag_is_no_write_and_mutually_exclusive(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/fetch_public_sources.py",
            "--registry",
            str(REGISTRY),
            "--destination-root",
            str(tmp_path),
            "--dry-run",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert '"status": "dry_run"' in result.stdout
    assert not list(tmp_path.rglob("*"))

    conflicting = subprocess.run(
        [sys.executable, "scripts/fetch_public_sources.py", "--dry-run", "--fetch"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert conflicting.returncode == 2
    assert "not allowed with argument" in conflicting.stderr


class _Response:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self._position = 0
        self.headers = {"Content-Type": "application/pdf"}

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self._content)
        result = self._content[self._position : self._position + amount]
        self._position += len(result)
        return result


class _Opener:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def open(self, *args, **kwargs) -> _Response:
        return _Response(self.content)


def _fetch_registry(tmp_path: Path) -> Path:
    registry = tmp_path / "test.yaml"
    registry.write_text(
        """schema_version: '0.1'\nallowlisted_hosts: [example.org]\nsources:\n  - source_id: TEST\n    url: https://example.org/file.pdf\n    title: test\n    publisher: test\n    expected_media_types: [application/pdf]\n    max_bytes: 100\n    sha256: null\n    license: {terms: fetch, review_status: pending}\n    destination: file.pdf\n""",
        encoding="utf-8",
    )
    return registry


@pytest.mark.unit
def test_fetch_atomically_promotes_validated_bytes_in_destination_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _fetch_registry(tmp_path)
    destination_dir = tmp_path / "out"
    destination = destination_dir / "file.pdf"
    destination_dir.mkdir()
    destination.write_bytes(b"old-content")
    replacements: list[tuple[Path, Path]] = []
    original_replace = Path.replace

    def record_replace(source: Path, target: Path) -> Path:
        replacements.append((source, target))
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", record_replace)
    records = fetch_registry(
        registry, destination_dir, dry_run=False, opener=_Opener(b"new-content")
    )

    assert records[0].status == "fetched"
    assert destination.read_bytes() == b"new-content"
    assert len(replacements) == 1
    temporary, target = replacements[0]
    assert temporary.parent == destination_dir
    assert target == destination
    assert not list(destination_dir.glob(".file.pdf.*"))


@pytest.mark.unit
def test_failed_atomic_promotion_preserves_prior_target_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _fetch_registry(tmp_path)
    destination_dir = tmp_path / "out"
    destination = destination_dir / "file.pdf"
    destination_dir.mkdir()
    destination.write_bytes(b"prior-content")

    def fail_replace(source: Path, target: Path) -> Path:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PublicSourceError, match="atomic promotion failed"):
        fetch_registry(registry, destination_dir, dry_run=False, opener=_Opener(b"new-content"))

    assert destination.read_bytes() == b"prior-content"
    assert not list(destination_dir.glob(".file.pdf.*"))


@pytest.mark.unit
def test_registry_rejects_off_list_host(tmp_path: Path) -> None:
    registry = tmp_path / "bad.yaml"
    registry.write_text(
        """schema_version: '0.1'\nallowlisted_hosts: [example.org]\nsources:\n  - source_id: BAD\n    url: https://evil.example.net/file.pdf\n    title: bad\n    publisher: bad\n    expected_media_types: [application/pdf]\n    max_bytes: 10\n    sha256: null\n    license: {terms: fetch, review_status: pending}\n    destination: file.pdf\n""",
        encoding="utf-8",
    )
    with pytest.raises(PublicSourceError, match="not allow-listed"):
        load_registry(registry)
