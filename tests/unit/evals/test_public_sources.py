from __future__ import annotations

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
def test_registry_rejects_off_list_host(tmp_path: Path) -> None:
    registry = tmp_path / "bad.yaml"
    registry.write_text(
        """schema_version: '0.1'\nallowlisted_hosts: [example.org]\nsources:\n  - source_id: BAD\n    url: https://evil.example.net/file.pdf\n    title: bad\n    publisher: bad\n    expected_media_types: [application/pdf]\n    max_bytes: 10\n    sha256: null\n    license: {terms: fetch, review_status: pending}\n    destination: file.pdf\n""",
        encoding="utf-8",
    )
    with pytest.raises(PublicSourceError, match="not allow-listed"):
        load_registry(registry)
