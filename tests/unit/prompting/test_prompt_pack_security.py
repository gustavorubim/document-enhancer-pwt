from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML

from document_enhancer.prompting.validator import validate_prompt_pack

ROOT = Path(__file__).resolve().parents[3]
PROMPT_ROOT = ROOT / "prompt_packs" / "gemini_core"


def _copy_pack(tmp_path: Path) -> Path:
    destination = tmp_path / "pack"
    shutil.copytree(PROMPT_ROOT, destination)
    return destination


def _dump_manifest(path: Path, data: dict[str, object]) -> None:
    yaml = YAML()
    yaml.default_flow_style = False
    with (path / "manifest.yaml").open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)


def _read_manifest(path: Path) -> dict[str, object]:
    yaml = YAML(typ="safe")
    return cast(dict[str, object], yaml.load((path / "manifest.yaml").read_text(encoding="utf-8")))


def test_route_mismatch_and_unknown_variable_are_reported_precisely(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)
    manifest = _read_manifest(pack)
    prompts = cast(list[dict[str, Any]], manifest["prompts"])
    prompts[0]["model_route"] = "gemini-3.5-flash"
    prompts[0]["variables"].append(
        {
            "name": "not_declared_in_body",
            "value_type": "text",
            "required": False,
            "default": "",
            "max_size": 10,
            "escaping": "delimited",
        }
    )
    _dump_manifest(pack, manifest)
    report = validate_prompt_pack(pack)
    assert not report.ok
    assert any("model route" in error for error in report.errors)


def test_yaml_aliases_are_rejected(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)
    manifest = _read_manifest(pack)
    manifest["reference_inputs"] = "*file_digests"
    # Use a direct alias in a second field; safe loading must fail before model validation.
    manifest_text = (pack / "manifest.yaml").read_text(encoding="utf-8")
    manifest_text = manifest_text.replace("file_digests:\n", "file_digests: &file_digests\n", 1)
    manifest_text += "\nmalicious_alias: *file_digests\n"
    (pack / "manifest.yaml").write_text(manifest_text, encoding="utf-8")
    report = validate_prompt_pack(pack)
    assert not report.ok
    assert any("aliases or cycles" in error for error in report.errors)


def test_include_cycle_is_rejected(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)
    first = pack / "shared" / "system.md"
    first.write_text('{{include "shared/confidentiality.md"}}\n', encoding="utf-8")
    second = pack / "shared" / "confidentiality.md"
    second.write_text('{{include "shared/system.md"}}\n', encoding="utf-8")
    manifest = _read_manifest(pack)
    file_digests = cast(dict[str, str], manifest["file_digests"])
    for relative, path in (("shared/system.md", first), ("shared/confidentiality.md", second)):
        file_digests[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    _dump_manifest(pack, manifest)
    report = validate_prompt_pack(pack)
    assert not report.ok
    assert any("Cyclic prompt include" in error for error in report.errors)


def test_path_traversal_in_reference_binding_is_rejected(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)
    manifest = _read_manifest(pack)
    reference_inputs = cast(dict[str, dict[str, object]], manifest["reference_inputs"])
    reference_inputs["template"]["path"] = "../outside.md"
    _dump_manifest(pack, manifest)
    report = validate_prompt_pack(pack)
    assert not report.ok
    assert any("Path traversal" in error or "non-canonical" in error for error in report.errors)


def test_unlisted_regular_prompt_like_file_is_rejected(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)
    extra = pack / ".hidden-prompt.md"
    extra.write_text("This is an unlisted production instruction.", encoding="utf-8")

    report = validate_prompt_pack(pack)

    assert not report.ok
    assert any(
        "every regular prompt-pack file" in error and ".hidden-prompt.md" in error
        for error in report.errors
    )
