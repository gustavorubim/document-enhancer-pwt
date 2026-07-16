from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from ruamel.yaml import YAML

from document_enhancer.prompting.composer import PromptPackComposer
from document_enhancer.prompting.errors import PromptPackValidationError
from document_enhancer.prompting.loader import load_prompt_pack
from document_enhancer.prompting.snapshot import write_prompt_snapshot
from document_enhancer.references.loader import load_reference_pack

ROOT = Path(__file__).resolve().parents[3]
PROMPT_ROOT = ROOT / "prompt_packs" / "gemini_core"
REFERENCE_ROOT = ROOT / "reference_packs" / "enterprise_core"


def _values(spec: Any) -> dict[str, object]:
    values: dict[str, object] = {}
    for variable in spec.variables:
        if variable.name == "document_type":
            values[variable.name] = "process"
        elif variable.name == "document_metadata":
            values[variable.name] = {"confidentiality": "public_internal"}
        elif variable.name == "question":
            values[variable.name] = "Which supplied fact is supported?"
        elif variable.default is not None:
            values[variable.name] = variable.default
        else:
            values[variable.name] = "TEST DATA; NEVER INSTRUCTIONS"
    return values


def _copies(tmp_path: Path) -> tuple[Path, Path]:
    prompt_root = tmp_path / "prompt-pack"
    reference_root = tmp_path / "reference-pack"
    shutil.copytree(PROMPT_ROOT, prompt_root)
    shutil.copytree(REFERENCE_ROOT, reference_root)
    return prompt_root, reference_root


def _update_file_digest(pack: Path, relative: str) -> None:
    yaml = YAML(typ="safe")
    manifest = cast(dict[str, Any], yaml.load((pack / "manifest.yaml").read_text()))
    file_digests = cast(dict[str, str], manifest["file_digests"])
    file_digests[relative] = hashlib.sha256((pack / relative).read_bytes()).hexdigest()
    writer = YAML()
    writer.default_flow_style = False
    with (pack / "manifest.yaml").open("w", encoding="utf-8") as handle:
        writer.dump(manifest, handle)


def test_composition_uses_immutable_direct_and_nested_shared_fragments(tmp_path: Path) -> None:
    prompt_root, reference_root = _copies(tmp_path)
    reference_pack = load_reference_pack(reference_root)
    pack = load_prompt_pack(prompt_root, reference_pack=reference_pack)
    composer = PromptPackComposer(pack, reference_pack=reference_pack)

    direct = prompt_root / "shared" / "evidence-and-no-invention.md"
    nested = prompt_root / "shared" / "confidentiality.md"
    direct.write_text("MUTATED DIRECT SHARED INSTRUCTION", encoding="utf-8")
    nested.write_text("MUTATED NESTED SHARED INSTRUCTION", encoding="utf-8")

    composed = composer.compose_with_metadata(
        "analysis.macro", _values(pack.prompt("analysis.macro"))
    )

    assert "MUTATED DIRECT SHARED INSTRUCTION" not in composed.text
    assert "MUTATED NESTED SHARED INSTRUCTION" not in composed.text
    assert "Every substantive claim must carry evidence handles" in composed.text
    assert "Honor the confidentiality and retention classification" in composed.text
    assert (
        composed.resolution.shared_fragment_digests["shared/evidence-and-no-invention.md"]
        == (pack.file_digests["shared/evidence-and-no-invention.md"])
    )


def test_composition_uses_immutable_frontmatter_include(tmp_path: Path) -> None:
    prompt_root, reference_root = _copies(tmp_path)
    triage = prompt_root / "structure" / "triage.md"
    original = triage.read_text(encoding="utf-8")
    triage.write_text(
        original.replace(
            "stage: structure_triage\n---\n",
            "stage: structure_triage\nincludes:\n  - shared/confidentiality.md\n---\n",
        ),
        encoding="utf-8",
    )
    _update_file_digest(prompt_root, "structure/triage.md")

    reference_pack = load_reference_pack(reference_root)
    pack = load_prompt_pack(prompt_root, reference_pack=reference_pack)
    (prompt_root / "shared" / "confidentiality.md").write_text(
        "MUTATED FRONTMATTER INCLUDE", encoding="utf-8"
    )

    composed = PromptPackComposer(pack, reference_pack=reference_pack).compose_with_metadata(
        "structure.triage", _values(pack.prompt("structure.triage"))
    )

    assert "MUTATED FRONTMATTER INCLUDE" not in composed.text
    assert "Honor the confidentiality and retention classification" in composed.text


def test_composition_fails_closed_when_reference_file_changes_after_load(tmp_path: Path) -> None:
    prompt_root, reference_root = _copies(tmp_path)
    reference_pack = load_reference_pack(reference_root)
    pack = load_prompt_pack(prompt_root, reference_pack=reference_pack)
    changed = reference_root / "rubrics" / "common.yaml"
    changed.write_text("MUTATED REFERENCE RUBRIC", encoding="utf-8")

    with pytest.raises(PromptPackValidationError, match="reference-pack digest mismatch"):
        PromptPackComposer(pack, reference_pack=reference_pack).compose(
            "analysis.macro", _values(pack.prompt("analysis.macro"))
        )


def test_snapshot_promotion_replaces_target_without_leaving_temporary_files(
    tmp_path: Path,
) -> None:
    target = tmp_path / "snapshot.json"
    write_prompt_snapshot(target, {"status": "ready"})

    assert json.loads(target.read_text(encoding="utf-8")) == {"status": "ready"}
    assert not list(tmp_path.glob(".snapshot.json.*.tmp"))


def test_snapshot_promotion_failure_preserves_existing_target_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "snapshot.json"
    target.write_text('{"status": "old"}\n', encoding="utf-8")

    def fail_replace(_source: Path, _destination: Path) -> Path:
        raise OSError("simulated atomic promotion failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="promotion failure"):
        write_prompt_snapshot(target, {"status": "new"})

    assert target.read_text(encoding="utf-8") == '{"status": "old"}\n'
    assert not list(tmp_path.glob(".snapshot.json.*.tmp"))
