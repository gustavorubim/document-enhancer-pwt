"""Content-addressed stage cache keys and dependency invalidation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..ingest.common import canonical_json, sha256_bytes

DEFAULT_CACHE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "raw_ingest": (),
    "normalize": ("raw_ingest",),
    "structure_quality": ("normalize",),
    "structure_scan": ("structure_quality",),
    "structure_recovery": ("structure_scan",),
    "selected_view": ("structure_quality", "structure_recovery"),
    "analysis": ("selected_view", "normalize"),
    "rewrite": ("analysis",),
    "audit": ("rewrite",),
    "export": ("audit",),
    "rag_build": ("export",),
}


def make_cache_key(
    stage: str,
    inputs: Mapping[str, object],
    *,
    dependencies: Mapping[str, str] | None = None,
    schema_version: str = "m3a.cache.v1",
) -> str:
    """Hash only canonical, caller-supplied input digests and configuration values."""

    payload = {
        "schema": schema_version,
        "stage": stage,
        "inputs": dict(sorted(inputs.items())),
        "dependencies": dict(sorted((dependencies or {}).items())),
    }
    return sha256_bytes(canonical_json(payload))


@dataclass(frozen=True)
class CacheDependencyGraph:
    dependencies: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_CACHE_DEPENDENCIES)
    )

    def upstream(self, stage: str) -> tuple[str, ...]:
        return tuple(self.dependencies.get(stage, ()))

    def downstream(self, stage: str) -> tuple[str, ...]:
        found: set[str] = set()
        queue = [stage]
        while queue:
            current = queue.pop(0)
            for candidate, parents in self.dependencies.items():
                if current in parents and candidate not in found:
                    found.add(candidate)
                    queue.append(candidate)
        return tuple(sorted(found))

    def invalidated_by(self, changed_stages: set[str] | frozenset[str]) -> tuple[str, ...]:
        invalidated = set(changed_stages)
        for stage in tuple(changed_stages):
            invalidated.update(self.downstream(stage))
        return tuple(sorted(invalidated))

    def key(
        self,
        stage: str,
        inputs: Mapping[str, object],
        *,
        completed_keys: Mapping[str, str] | None = None,
    ) -> str:
        parents = {
            parent: (completed_keys or {}).get(parent, "") for parent in self.upstream(stage)
        }
        return make_cache_key(stage, inputs, dependencies=parents)


__all__ = ["CacheDependencyGraph", "DEFAULT_CACHE_DEPENDENCIES", "make_cache_key"]
