"""Deterministic, visibly delimited prompt composition."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from document_enhancer.contracts import PromptComposer
from document_enhancer.domain.run import PromptResolution, PromptSpec, PromptVariable
from document_enhancer.domain.schema_registry import schema_models
from document_enhancer.references.loader import (
    ApplicabilityContext,
    ReferencePack,
    load_reference_pack,
)

from .errors import PromptPackSecurityError, PromptPackValidationError
from .loader import (
    _expand_frontmatter_includes,
    _expand_includes,
    _parse_markdown,
    resolve_reference_inputs,
)
from .manifest import PromptPack, ResolvedReferenceInput

__all__ = ["PromptComposer", "ComposedPrompt", "PromptPackComposer"]

_VARIABLE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_SOURCE_NAMES = {
    "source",
    "source_text",
    "raw_source",
    "raw_source_text",
    "document_text",
    "retrieved_chunks",
    "retrieval_context",
    "query_context",
    "analysis_results",
    "approved_ledger",
    "enhanced_document",
    "audit_findings",
    "candidate_entities",
    "candidate_chunks",
    "answer",
    "query",
    "question",
    "history",
}
_REVIEWER_NAMES = {
    "reviewer_inputs",
    "reviewer_input",
    "answers",
    "steering",
    "waivers",
    "checklist",
}
_DISALLOWED_TOOLS = {"shell", "network", "browser", "code_execution", "computer_use"}
MAX_RENDERED_CHARS = 2_000_000


@dataclass(frozen=True)
class ComposedPrompt:
    """Prompt text plus the exact resolution metadata needed by run manifests."""

    prompt_id: str
    pack_id: str
    pack_version: str
    pack_manifest_sha256: str
    pack_sha256: str
    text: str
    resolution: PromptResolution
    resolved_references: tuple[ResolvedReferenceInput, ...]

    @property
    def digest(self) -> str:
        return self.resolution.rendered_prompt_digest


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _schema_json(schema_name: str) -> str:
    models = schema_models()
    model = models.get(schema_name)
    if model is None:
        raise PromptPackValidationError(f"unknown output schema: {schema_name}")
    return json.dumps(model.model_json_schema(), sort_keys=True, separators=(",", ":"))


def _variable_type_ok(variable: PromptVariable, value: Any) -> bool:
    kind = variable.value_type.lower().replace(" ", "")
    if kind in {"str", "string", "text", "markdown", "query", "identifier"}:
        return isinstance(value, str)
    if kind in {"int", "integer"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind in {"float", "number"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind in {"bool", "boolean"}:
        return isinstance(value, bool)
    if kind in {"list", "array", "list[str]", "array[str]"}:
        return isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value)
    if kind in {"mapping", "object", "dict", "json"}:
        return isinstance(value, (Mapping, list, tuple, str, int, float, bool))
    return True


def _escaped(value: Any, variable: PromptVariable) -> str:
    escaping = variable.escaping.lower()
    if escaping in {"json", "json_string"}:
        return _canonical(value)
    if escaping in {"yaml", "safe_yaml"}:
        # JSON is deliberately used as the safe, deterministic subset inside a Markdown
        # data block; it cannot create YAML tags or executable constructors.
        return _canonical(value)
    if isinstance(value, str):
        return value
    return _canonical(value)


def _input_block(name: str, value: Any, variable: PromptVariable) -> str:
    encoded = _escaped(value, variable)
    return (
        f"[INPUT name={name} type={variable.value_type} escaping={variable.escaping}]\n"
        f"{encoded}\n"
        f"[/INPUT name={name}]"
    )


def _contract(pack: PromptPack, key: str) -> str:
    value = pack.raw_manifest.get("composition_contract", {})
    if not isinstance(value, Mapping) or not isinstance(value.get(key), str):
        raise PromptPackValidationError(f"manifest.composition_contract.{key} is required")
    return str(value[key])


class PromptPackComposer:
    """Compose one immutable prompt entry against a selected reference pack."""

    def __init__(
        self,
        pack: PromptPack,
        *,
        reference_pack: Path | ReferencePack | None = None,
        document_type: str = "process",
        reference_context: ApplicabilityContext | dict[str, Any] | None = None,
    ) -> None:
        self.pack = pack
        self.reference_pack = (
            load_reference_pack(reference_pack)
            if isinstance(reference_pack, Path)
            else reference_pack
        )
        self.document_type = document_type
        self.reference_context = reference_context

    def compose(self, prompt_id: str, variables: Mapping[str, Any]) -> str:
        """Return only the composed prompt text for the frozen cross-lane port."""

        return self.compose_with_metadata(prompt_id, variables).text

    def compose_with_metadata(self, prompt_id: str, variables: Mapping[str, Any]) -> ComposedPrompt:
        try:
            spec = self.pack.prompt(prompt_id)
        except KeyError as exc:
            raise PromptPackValidationError(f"unknown prompt ID: {prompt_id}") from exc
        values = self._validate_variables(spec, variables)
        template = self.pack.template_for(spec)
        body = template.body
        source_or_reviewer = _SOURCE_NAMES | _REVIEWER_NAMES
        for name in _VARIABLE_RE.findall(body):
            if name in source_or_reviewer:
                raise PromptPackSecurityError(
                    f"prompt {prompt_id} places untrusted input {name!r} inside governed instructions"
                )
        body = self._replace_body_variables(body, spec, values)

        references: tuple[ResolvedReferenceInput, ...] = ()
        if self.pack.manifest.required_references:
            if self.reference_pack is None:
                raise PromptPackValidationError(
                    f"prompt {prompt_id} requires a resolved reference pack before composition"
                )
            references = resolve_reference_inputs(
                self.pack,
                self.reference_pack,
                document_type=str(values.get("document_type", self.document_type)),
                context=self.reference_context,
            )

        shared = self._shared_fragments(spec)
        governed_context = self._governed_context(spec, values, references)
        source_text = self._boundary_values(spec, values, _SOURCE_NAMES)
        reviewer_inputs = self._boundary_values(spec, values, _REVIEWER_NAMES)
        output_contract = self._output_contract(spec)
        segments = {
            "shared": shared,
            "shared_fragments": shared,
            "template": body,
            "governed_context": governed_context,
            "untrusted_source": source_text,
            "source": source_text,
            "reviewer_inputs": reviewer_inputs,
            "reviewer": reviewer_inputs,
            "output_contract": output_contract,
        }
        order = self.pack.manifest.composition_order or [
            "shared_fragments",
            "template",
            "governed_context",
            "untrusted_source",
            "reviewer_inputs",
            "output_contract",
        ]
        rendered_parts: list[str] = []
        for item in order:
            if item not in segments:
                raise PromptPackValidationError(f"unknown composition-order segment: {item}")
            rendered_parts.append(segments[item])
        rendered = "\n\n".join(part for part in rendered_parts if part.strip())
        # The budget is expressed in provider tokens; JSON Schema text is part of the governed
        # prompt and is substantially denser than ordinary prose, so use a conservative 8-char
        # conversion while retaining the absolute hard cap.
        if len(rendered) > MAX_RENDERED_CHARS or len(rendered) > spec.token_budget * 8:
            raise PromptPackSecurityError(
                f"composed prompt exceeds the bounded input budget for {prompt_id}"
            )
        if not all(
            marker in rendered
            for marker in (
                "BEGIN GOVERNED INSTRUCTIONS",
                "BEGIN GOVERNED CONTEXT",
                "BEGIN UNTRUSTED SOURCE",
                "BEGIN REVIEWER INPUTS",
                "BEGIN OUTPUT CONTRACT",
            )
        ):
            raise PromptPackSecurityError(
                f"prompt {prompt_id} is missing a required input boundary"
            )
        reference_digests = {
            f"{item.logical_name}:{item.path or 'runtime'}": item.sha256 for item in references
        }
        resolution = PromptResolution(
            prompt_id=prompt_id,
            pack_id=self.pack.pack_id,
            pack_version=self.pack.version,
            template_digest=template.digest,
            shared_fragment_digests={
                fragment: self.pack.file_digests[fragment] for fragment in spec.shared_fragments
            },
            resolved_reference_digests=reference_digests,
            variable_names=sorted(values),
            composition_order=list(order),
            rendered_prompt_digest=_digest(rendered),
            output_schema=spec.output_schema,
            resolved_at=datetime.now(UTC),
        )
        return ComposedPrompt(
            prompt_id=prompt_id,
            pack_id=self.pack.pack_id,
            pack_version=self.pack.version,
            pack_manifest_sha256=self.pack.manifest_sha256,
            pack_sha256=self.pack.pack_sha256,
            text=rendered,
            resolution=resolution,
            resolved_references=references,
        )

    def _validate_variables(self, spec: PromptSpec, variables: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(variables, Mapping):
            raise PromptPackValidationError("prompt variables must be a mapping")
        definitions = {item.name: item for item in spec.variables}
        unknown = sorted(set(variables) - set(definitions))
        if unknown:
            raise PromptPackValidationError(
                f"prompt {spec.prompt_id} received unknown variable(s): {', '.join(unknown)}"
            )
        values: dict[str, Any] = {}
        for name, variable in definitions.items():
            if name in variables:
                value = variables[name]
            elif variable.default is not None or not variable.required:
                value = variable.default if variable.default is not None else ""
            else:
                raise PromptPackValidationError(
                    f"prompt {spec.prompt_id} is missing required variable: {name}"
                )
            if not _variable_type_ok(variable, value):
                raise PromptPackValidationError(
                    f"prompt {spec.prompt_id} variable {name!r} has type {type(value).__name__}; expected {variable.value_type}"
                )
            encoded = _escaped(value, variable)
            if "\x00" in encoded:
                raise PromptPackSecurityError(f"prompt variable {name!r} contains a NUL byte")
            if variable.max_size is not None and len(encoded) > variable.max_size:
                raise PromptPackSecurityError(
                    f"prompt variable {name!r} exceeds its maximum size of {variable.max_size}"
                )
            values[name] = value
        return values

    def _replace_body_variables(self, body: str, spec: PromptSpec, values: dict[str, Any]) -> str:
        definitions = {item.name: item for item in spec.variables}

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in definitions:
                raise PromptPackValidationError(
                    f"prompt {spec.prompt_id} uses unknown variable: {name}"
                )
            return _escaped(values[name], definitions[name])

        return _VARIABLE_RE.sub(replace, body)

    def _shared_fragments(self, spec: PromptSpec) -> str:
        fragments: list[str] = []
        for relative in spec.shared_fragments:
            raw = self.pack.file_bytes(relative)
            front, body = _parse_markdown(raw, relative=relative)
            declared = _expand_frontmatter_includes(
                self.pack.root,
                relative,
                front,
                self.pack.file_digests,
                self.pack.file_contents,
            )
            fragments.append(
                _expand_includes(
                    self.pack.root,
                    relative,
                    "\n\n".join(part for part in (declared, body) if part),
                    self.pack.file_digests,
                    file_contents=self.pack.file_contents,
                )
            )
        return (
            _contract(self.pack, "instructions_open")
            + "\n"
            + _contract(self.pack, "instructions_preamble")
            + "\n\n"
            + "\n\n".join(fragments)
            + "\n"
            + _contract(self.pack, "instructions_close")
        )

    def _governed_context(
        self,
        spec: PromptSpec,
        values: dict[str, Any],
        references: tuple[ResolvedReferenceInput, ...],
    ) -> str:
        parts = [
            _contract(self.pack, "context_open"),
            _contract(self.pack, "context_preamble"),
        ]
        for item in references:
            parts.append(
                f"[REFERENCE logical_name={item.logical_name} path={item.path} kind={item.kind} "
                f"pack_id={item.pack_id} pack_version={item.pack_version} sha256={item.sha256}]\n"
                f"{item.content}\n[/REFERENCE]"
            )
        for name, value in values.items():
            if name in {
                "document_type",
                "target_section",
                "target_object",
                "document_metadata",
                "query_metadata",
            }:
                variable = next(variable for variable in spec.variables if variable.name == name)
                parts.append(_input_block(name, value, variable))
        parts.append(_contract(self.pack, "context_close"))
        return "\n".join(parts)

    def _boundary_values(self, spec: PromptSpec, values: dict[str, Any], names: set[str]) -> str:
        parts = [
            _contract(self.pack, "source_open")
            if names == _SOURCE_NAMES
            else _contract(self.pack, "reviewer_open")
        ]
        found = False
        definitions = {item.name: item for item in spec.variables}
        for name, value in values.items():
            if name in names:
                found = True
                parts.append(_input_block(name, value, definitions[name]))
        if not found:
            parts.append("[NONE SUPPLIED]")
        parts.append(
            _contract(self.pack, "source_close")
            if names == _SOURCE_NAMES
            else _contract(self.pack, "reviewer_close")
        )
        return "\n".join(parts)

    def _output_contract(self, spec: PromptSpec) -> str:
        if any(tool.lower() in _DISALLOWED_TOOLS for tool in spec.optional_tools):
            raise PromptPackSecurityError(f"prompt {spec.prompt_id} enables a prohibited tool")
        schema = _schema_json(spec.output_schema)
        return (
            _contract(self.pack, "output_open")
            + "\n"
            + _contract(self.pack, "output_preamble")
            + f"\nModel route: {spec.model_route}\n"
            f"Output schema name: {spec.output_schema}\nJSON Schema: {schema}\n"
            + _contract(self.pack, "output_close")
        )
