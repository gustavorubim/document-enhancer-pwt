"""Prompt-pack linting, compatibility checks, and precise validation reports."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from document_enhancer.domain.schema_registry import schema_models
from document_enhancer.references.loader import ReferencePack, load_reference_pack

from .errors import (
    PromptPackError,
    PromptPackValidationReport,
)
from .loader import (
    _INCLUDE_RE,
    _expand_frontmatter_includes,
    _expand_includes,
    _load,
    _parse_markdown,
    _read_file,
    resolve_reference_inputs,
)
from .manifest import PromptPack

__all__ = ["validate_prompt_pack", "PromptPackValidationReport"]

EXPECTED_ROUTES: dict[str, str] = {
    "structure.triage": "gemini-3.1-flash-lite",
    "structure.recover-window": "gemini-3.1-flash-lite",
    "structure.reconcile-boundaries": "gemini-3.1-flash-lite",
    "analysis.macro": "gemini-3.5-flash",
    "analysis.sections": "gemini-3.5-flash",
    "analysis.process-methodology-discovery": "gemini-3.5-flash",
    "analysis.rag-readiness": "gemini-3.5-flash",
    "analysis.synthesize-findings": "gemini-3.5-flash",
    "clarification.questions": "gemini-3.1-flash-lite",
    "clarification.rewrite-checklist": "gemini-3.1-flash-lite",
    "rewrite.section": "gemini-3.1-pro-preview",
    "rewrite.semantic-objects": "gemini-3.1-pro-preview",
    "rewrite.revision": "gemini-3.1-pro-preview",
    "audit.content-fidelity": "gemini-3.5-flash",
    "audit.remediation-routing": "gemini-3.5-flash",
    "rag.history-aware-query": "gemini-3.1-flash-lite",
    "rag.entity-linking": "gemini-3.1-flash-lite",
    "rag.retrieval-grading": "gemini-3.1-flash-lite",
    "rag.grounded-answer": "gemini-3.5-flash",
    "rag.citation-audit": "gemini-3.1-flash-lite",
}

EXPECTED_SCHEMAS: dict[str, str] = {
    "structure.triage": "structure-scan.schema.json",
    "structure.recover-window": "structure-recovery.schema.json",
    "structure.reconcile-boundaries": "structure-recovery.schema.json",
    "analysis.macro": "analysis.schema.json",
    "analysis.sections": "analysis.schema.json",
    "analysis.process-methodology-discovery": "analysis.schema.json",
    "analysis.rag-readiness": "analysis.schema.json",
    "analysis.synthesize-findings": "analysis.schema.json",
    "clarification.questions": "questions.schema.json",
    "clarification.rewrite-checklist": "rewrite-checklist.schema.json",
    "rewrite.section": "semantic-document.schema.json",
    "rewrite.semantic-objects": "semantic-document.schema.json",
    "rewrite.revision": "semantic-document.schema.json",
    "audit.content-fidelity": "audit.schema.json",
    "audit.remediation-routing": "audit.schema.json",
    "rag.history-aware-query": "rag-query.schema.json",
    "rag.entity-linking": "entity.schema.json",
    "rag.retrieval-grading": "analysis.schema.json",
    "rag.grounded-answer": "rag-answer.schema.json",
    "rag.citation-audit": "audit.schema.json",
}

EXPECTED_REFERENCES = {
    "common_rubric",
    "document_type_rubric",
    "template",
    "template_requirements",
    "ontology_entity_types",
    "ontology_relationship_types",
    "style_guide",
    "applicable_policies",
    "glossary",
}
_ALLOWED_ESCAPING = {"delimited", "json", "json_string", "yaml", "safe_yaml", "markdown", "plain"}
_FORBIDDEN_TOOL_RE = re.compile(r"\b(shell|network|browser|code_execution|computer_use)\b", re.I)
_VARIABLE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_SECRET_RE = re.compile(
    r"(?:GOOGLE_API_KEY|GEMINI_API_KEY|BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY|sk-[A-Za-z0-9]{12,})"
)


def _prompt_errors(
    pack: PromptPack, reference_pack: ReferencePack | None
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    details: dict[str, Any] = {
        "pack_id": pack.pack_id,
        "version": pack.version,
        "manifest_sha256": pack.manifest_sha256,
        "pack_sha256": pack.pack_sha256,
        "prompt_count": len(pack.manifest.prompts),
        "prompts": [],
    }
    if pack.pack_id == "gemini_core":
        missing = sorted(set(EXPECTED_ROUTES) - {item.prompt_id for item in pack.manifest.prompts})
        if missing:
            errors.append("manifest.prompts is missing required prompt IDs: " + ", ".join(missing))
        if set(pack.manifest.required_references) != EXPECTED_REFERENCES:
            errors.append(
                "manifest.required_references must contain exactly: "
                + ", ".join(sorted(EXPECTED_REFERENCES))
            )
        contract = pack.raw_manifest.get("composition_contract")
        if not isinstance(contract, Mapping):
            errors.append("manifest.composition_contract is required")
        else:
            required_contract_keys = {
                "instructions_open",
                "instructions_preamble",
                "instructions_close",
                "context_open",
                "context_preamble",
                "context_close",
                "source_open",
                "source_close",
                "reviewer_open",
                "reviewer_close",
                "output_open",
                "output_preamble",
                "output_close",
            }
            missing_contract = sorted(
                key for key in required_contract_keys if not isinstance(contract.get(key), str)
            )
            if missing_contract:
                errors.append(
                    "manifest.composition_contract is missing: " + ", ".join(missing_contract)
                )

    models = schema_models()
    for prompt in pack.manifest.prompts:
        entry: dict[str, Any] = {
            "prompt_id": prompt.prompt_id,
            "stage": prompt.stage,
            "model_route": prompt.model_route,
            "output_schema": prompt.output_schema,
            "template_path": prompt.template_path,
        }
        details["prompts"].append(entry)
        template = pack.template_for(prompt)
        placeholders = set(_VARIABLE_RE.findall(template.body))
        definitions = {variable.name: variable for variable in prompt.variables}
        unknown = sorted(placeholders - set(definitions))
        if unknown:
            errors.append(
                f"prompt {prompt.prompt_id}: unknown variable(s) in template: {', '.join(unknown)}"
            )
        if prompt.output_schema not in models:
            errors.append(
                f"prompt {prompt.prompt_id}: unknown output schema {prompt.output_schema}"
            )
        expected_route = EXPECTED_ROUTES.get(prompt.prompt_id)
        if expected_route is not None and prompt.model_route != expected_route:
            errors.append(
                f"prompt {prompt.prompt_id}: model route {prompt.model_route!r} does not match required {expected_route!r}"
            )
        expected_schema = EXPECTED_SCHEMAS.get(prompt.prompt_id)
        if expected_schema is not None and prompt.output_schema != expected_schema:
            errors.append(
                f"prompt {prompt.prompt_id}: output schema {prompt.output_schema!r} does not match required {expected_schema!r}"
            )
        if prompt.token_budget > 250_000 or prompt.output_budget > 100_000:
            errors.append(
                f"prompt {prompt.prompt_id}: token/output budgets exceed the hard safety bound"
            )
        if _FORBIDDEN_TOOL_RE.search(" ".join(prompt.optional_tools)):
            errors.append(f"prompt {prompt.prompt_id}: prohibited optional tool configured")
        for variable in prompt.variables:
            if variable.escaping not in _ALLOWED_ESCAPING:
                errors.append(
                    f"prompt {prompt.prompt_id}.variables.{variable.name}: unknown escaping policy {variable.escaping!r}"
                )
            if variable.name in _SOURCE_NAMES_OR_REVIEWER and variable.max_size is None:
                errors.append(
                    f"prompt {prompt.prompt_id}.variables.{variable.name}: untrusted/reviewer input requires max_size"
                )
            if variable.name in _SOURCE_NAMES_OR_REVIEWER and variable.escaping == "plain":
                errors.append(
                    f"prompt {prompt.prompt_id}.variables.{variable.name}: plain escaping is not allowed for data inputs"
                )
        if any(name in placeholders for name in _SOURCE_NAMES_OR_REVIEWER):
            errors.append(
                f"prompt {prompt.prompt_id}: source or reviewer data must be appended by the composer, not interpolated into instructions"
            )
        if _SECRET_RE.search(template.body):
            errors.append(
                f"prompt {prompt.prompt_id}: possible credential or private-key material in Markdown"
            )
        entry["template_digest"] = template.digest

        for fragment in prompt.shared_fragments:
            try:
                raw_fragment = _read_file(pack.root, fragment)
                front, fragment_body = _parse_markdown(raw_fragment, relative=fragment)
                declared = _expand_frontmatter_includes(
                    pack.root, fragment, front, pack.file_digests
                )
                _expand_includes(
                    pack.root,
                    fragment,
                    "\n\n".join(part for part in (declared, fragment_body) if part),
                    pack.file_digests,
                )
            except PromptPackError as exc:
                errors.extend(
                    f"prompt {prompt.prompt_id} shared fragment {fragment}: {error}"
                    for error in getattr(exc, "errors", (str(exc),))
                )

        # A prompt may refer to an include only through the loader's resolved body. This check
        # catches an unresolved literal include left behind by a malformed syntax variant.
        if _INCLUDE_RE.search(template.body):
            errors.append(
                f"prompt {prompt.prompt_id}: unresolved include remains in composed template"
            )

    if reference_pack is not None:
        for document_type in _document_types(pack):
            try:
                references = resolve_reference_inputs(
                    pack, reference_pack, document_type=document_type
                )
            except PromptPackError as exc:
                errors.append(f"reference resolution for document_type={document_type}: {exc}")
                continue
            details.setdefault("resolved_references", {})[document_type] = [
                item.snapshot() for item in references
            ]
            if not references and pack.manifest.required_references:
                errors.append(f"no required references resolved for document_type={document_type}")

        # Rubric leakage means copying governed criteria into a production prompt body instead
        # of resolving the versioned reference file. Compare meaningful lines, not short labels.
        for file_entry in reference_pack.files:
            if file_entry.kind != "rubric":
                continue
            try:
                rubric_text = reference_pack.path(file_entry.path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line in rubric_text.splitlines():
                normalized = " ".join(line.split())
                if len(normalized) < 48:
                    continue
                if any(
                    normalized in " ".join(pack.template_for(prompt).body.split())
                    for prompt in pack.manifest.prompts
                ):
                    errors.append(
                        f"rubric leakage: rubric text from {file_entry.path} is duplicated in a production prompt"
                    )
                    break
    return errors, details


_SOURCE_NAMES_OR_REVIEWER = {
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
    "reviewer_inputs",
    "reviewer_input",
    "answers",
    "steering",
    "waivers",
    "checklist",
}


def _document_types(pack: PromptPack) -> tuple[str, ...]:
    value = pack.raw_manifest.get(
        "document_types", ("process", "methodology", "standard", "desktop_procedure")
    )
    if isinstance(value, str):
        return (value,)
    return tuple(value) if isinstance(value, (list, tuple)) else ()


def validate_prompt_pack(
    location: Path | PromptPack,
    *,
    reference_pack: Path | ReferencePack | None = None,
) -> PromptPackValidationReport:
    """Validate a pack without exposing source text in errors or details."""

    errors: list[str] = []
    details: dict[str, Any] = {}
    try:
        pack = location if isinstance(location, PromptPack) else _load(Path(location))
        resolved_reference: ReferencePack | None
        if isinstance(reference_pack, ReferencePack):
            resolved_reference = reference_pack
        elif reference_pack is not None:
            resolved_reference = load_reference_pack(Path(reference_pack))
        else:
            resolved_reference = None
        errors, details = _prompt_errors(pack, resolved_reference)
    except PromptPackError as exc:
        errors = list(getattr(exc, "errors", (str(exc),)))
    except (OSError, TypeError, ValueError) as exc:
        errors = [str(exc)]
    return PromptPackValidationReport(errors=tuple(errors), details=details)
