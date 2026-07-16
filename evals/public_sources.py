"""Allow-listed, dry-run-first public-source registry and safe fetch helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


class PublicSourceError(ValueError):
    """A registry or fetch request failed a safety policy."""


@dataclass(frozen=True)
class FetchRecord:
    source_id: str
    status: str
    url: str
    destination: str
    bytes_written: int = 0
    sha256: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "url": self.url,
            "destination": self.destination,
            "bytes_written": self.bytes_written,
            "sha256": self.sha256,
            "reason": self.reason,
        }


def _yaml() -> YAML:
    yaml = YAML(typ="safe")
    yaml.allow_duplicate_keys = False
    return yaml


def load_registry(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = _yaml().load(handle)
    except (OSError, ValueError, YAMLError) as exc:
        raise PublicSourceError(f"unable to read public-source registry: {path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != "0.1":
        raise PublicSourceError("registry schema_version must be 0.1")
    hosts = data.get("allowlisted_hosts")
    sources = data.get("sources")
    if not isinstance(hosts, list) or not hosts or not all(isinstance(host, str) for host in hosts):
        raise PublicSourceError("allowlisted_hosts must be a non-empty list of host names")
    if not isinstance(sources, list) or not sources:
        raise PublicSourceError("sources must be a non-empty list")
    for source in sources:
        _validate_source(source, {host.lower() for host in hosts})
    return data


def _validate_source(source: Any, allowlisted_hosts: set[str]) -> None:
    if not isinstance(source, dict):
        raise PublicSourceError("each public source must be an object")
    required = {
        "source_id",
        "url",
        "title",
        "publisher",
        "expected_media_types",
        "max_bytes",
        "license",
    }
    missing = sorted(required - set(source))
    if missing:
        raise PublicSourceError(f"source is missing required fields: {', '.join(missing)}")
    parsed = urllib.parse.urlsplit(str(source["url"]))
    if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname:
        raise PublicSourceError(f"source URL must be HTTPS without credentials: {source['url']}")
    if parsed.hostname.lower() not in allowlisted_hosts:
        raise PublicSourceError(f"source host is not allow-listed: {parsed.hostname}")
    decoded_path = urllib.parse.unquote(parsed.path)
    if any(part in {".", ".."} for part in decoded_path.split("/")):
        raise PublicSourceError(f"source URL path contains traversal: {source['url']}")
    media_types = source["expected_media_types"]
    if (
        not isinstance(media_types, list)
        or not media_types
        or not all(isinstance(item, str) for item in media_types)
    ):
        raise PublicSourceError(
            f"expected_media_types must be a non-empty list: {source['source_id']}"
        )
    if not isinstance(source["max_bytes"], int) or source["max_bytes"] <= 0:
        raise PublicSourceError(f"max_bytes must be positive: {source['source_id']}")
    digest = source.get("sha256")
    if digest is not None and (
        not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise PublicSourceError(
            f"sha256 must be a lowercase 64-character digest or null: {source['source_id']}"
        )
    license_info = source["license"]
    if (
        not isinstance(license_info, dict)
        or not license_info.get("terms")
        or not license_info.get("review_status")
    ):
        raise PublicSourceError(
            f"license must include terms and review_status: {source['source_id']}"
        )


def _safe_destination(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise PublicSourceError(f"destination escapes fetch root: {relative}")
    if any(part in {"", ".", ".."} for part in Path(relative).parts):
        raise PublicSourceError(f"destination contains unsafe path components: {relative}")
    return candidate


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise PublicSourceError(f"redirect blocked: {newurl}")


def _response_media_type(response: Any) -> str:
    value = response.headers.get("Content-Type", "")
    return value.split(";", 1)[0].strip().lower()


def fetch_registry(
    registry_path: Path,
    destination_root: Path,
    *,
    dry_run: bool = True,
    source_ids: set[str] | None = None,
    opener: Any | None = None,
) -> list[FetchRecord]:
    """Validate and optionally fetch registry entries without executing content."""

    registry = load_registry(registry_path)
    allowed_hosts = {host.lower() for host in registry["allowlisted_hosts"]}
    selected = [
        source
        for source in registry["sources"]
        if source_ids is None or source["source_id"] in source_ids
    ]
    if source_ids:
        missing = source_ids - {source["source_id"] for source in selected}
        if missing:
            raise PublicSourceError(f"unknown source IDs: {', '.join(sorted(missing))}")
    records: list[FetchRecord] = []
    for source in selected:
        parsed = urllib.parse.urlsplit(source["url"])
        if parsed.hostname.lower() not in allowed_hosts:
            raise PublicSourceError(f"source host is not allow-listed: {parsed.hostname}")
        destination = _safe_destination(destination_root, str(source["destination"]))
        if dry_run:
            records.append(
                FetchRecord(source["source_id"], "dry_run", source["url"], str(destination))
            )
            continue
        active_opener = opener or urllib.request.build_opener(_NoRedirectHandler())
        try:
            response = active_opener.open(
                urllib.request.Request(
                    source["url"], headers={"User-Agent": "document-enhancer-public-fetch/0.1"}
                ),
                timeout=20,
            )
            media_type = _response_media_type(response)
            expected = {item.lower() for item in source["expected_media_types"]}
            if media_type not in expected:
                raise PublicSourceError(
                    f"unexpected media type for {source['source_id']}: {media_type}"
                )
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > source["max_bytes"]:
                raise PublicSourceError(f"declared response is oversized for {source['source_id']}")
            content = _read_bounded(response, source["max_bytes"])
        except (OSError, ValueError, urllib.error.URLError) as exc:
            if isinstance(exc, PublicSourceError):
                raise
            raise PublicSourceError(f"fetch failed for {source['source_id']}: {exc}") from exc
        digest = hashlib.sha256(content).hexdigest()
        if source.get("sha256") and digest != source["sha256"]:
            raise PublicSourceError(f"digest mismatch for {source['source_id']}")
        _atomic_promote(destination, content)
        records.append(
            FetchRecord(
                source["source_id"],
                "fetched",
                source["url"],
                str(destination),
                len(content),
                digest,
            )
        )
    return records


def _read_bounded(response: BinaryIO, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(64 * 1024, maximum - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise PublicSourceError(f"response exceeds configured maximum of {maximum} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _atomic_promote(destination: Path, content: bytes) -> None:
    """Promote validated bytes through a same-directory temporary file."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(destination)
        temporary_path = None
    except OSError as exc:
        raise PublicSourceError(f"atomic promotion failed for {destination}") from exc
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def records_json(records: list[FetchRecord]) -> str:
    return json.dumps([record.as_dict() for record in records], indent=2, sort_keys=True) + "\n"
