"""Deterministic clarification-question synthesis.

The model boundary ends before this module. Findings are treated as evidence-backed
signals; this module may ask for missing information, but it never supplies an answer.
"""

from __future__ import annotations

import hashlib
import re
import string
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from difflib import SequenceMatcher
from typing import Any, cast

from document_enhancer.domain.analysis import Finding, FindingSet
from document_enhancer.domain.enums import (
    FindingSeverity,
    QuestionCategory,
    QuestionPriority,
    QuestionStatus,
)
from document_enhancer.domain.questions import Question, QuestionsArtifact

from .models import QuestionSynthesisResult

_CATEGORY_ORDER = {
    QuestionCategory.STEERING: 0,
    QuestionCategory.OWNERSHIP: 1,
    QuestionCategory.MISSING: 2,
    QuestionCategory.AMBIGUITY: 3,
    QuestionCategory.CONFLICT: 4,
    QuestionCategory.VALIDATION: 5,
    QuestionCategory.CONTROL: 6,
    QuestionCategory.CALCULATION: 7,
    QuestionCategory.DEPENDENCY: 8,
    QuestionCategory.EXCEPTION: 9,
}

_KEYWORDS: dict[QuestionCategory, tuple[str, ...]] = {
    QuestionCategory.STEERING: ("steering", "audience", "tone", "restructure", "terminology"),
    QuestionCategory.OWNERSHIP: ("owner", "role", "accountable", "approver", "responsib"),
    QuestionCategory.CONTROL: ("control", "evidence", "frequency", "risk", "approval"),
    QuestionCategory.CALCULATION: (
        "calculator",
        "calculation",
        "formula",
        "threshold",
        "unit",
        "parameter",
        "spreadsheet",
        "model",
    ),
    QuestionCategory.DEPENDENCY: ("depend", "system", "input", "output", "data", "prerequisite"),
    QuestionCategory.EXCEPTION: ("exception", "override", "fallback", "escalat", "failure"),
    QuestionCategory.CONFLICT: ("conflict", "contradict", "inconsistent", "disagree"),
    QuestionCategory.AMBIGUITY: ("ambig", "vague", "unclear", "pronoun", "which", "meaning"),
    QuestionCategory.VALIDATION: ("validat", "test", "verify", "check", "review"),
    QuestionCategory.MISSING: ("missing", "absent", "required", "not documented", "gap"),
}

_EXPECTED_SHAPES = {
    QuestionCategory.STEERING: "State the approved audience, tone, terminology, and restructuring constraints.",
    QuestionCategory.OWNERSHIP: "Name the accountable role, performer, approver, and escalation owner, or state that the field is not applicable.",
    QuestionCategory.MISSING: "Provide the authoritative fact with its owner and effective date, or explicitly mark it TBD/not applicable with a reason.",
    QuestionCategory.AMBIGUITY: "Quote the intended meaning and identify the exact term, condition, or target that should replace the ambiguity.",
    QuestionCategory.CONFLICT: "Identify the authoritative statement and explain how the conflicting statement should be reconciled.",
    QuestionCategory.VALIDATION: "Provide the validation method, expected result, evidence location, and reviewer.",
    QuestionCategory.CONTROL: "Provide the control objective, performer, frequency/event, evidence, failure response, and escalation.",
    QuestionCategory.CALCULATION: "Provide the formula/calculator, inputs, units, parameters, thresholds, validation status, and fallback.",
    QuestionCategory.DEPENDENCY: "Name the dependency, owner/provider, readiness condition, timing, failure impact, and fallback.",
    QuestionCategory.EXCEPTION: "State the exception condition, authorized role, justification/evidence, validity period, and escalation or recovery path.",
}


def _text(value: object) -> str:
    return str(value or "")


def _normalized_words(value: str) -> tuple[str, ...]:
    value = value.casefold().translate(str.maketrans("", "", string.punctuation))
    return tuple(re.findall(r"[a-z0-9]+", value))


def _normalized_text(value: str) -> str:
    return " ".join(_normalized_words(value))


def infer_category(finding: Finding | Mapping[str, Any]) -> QuestionCategory:
    """Map free-form specialist labels to the bounded clarification vocabulary."""

    if isinstance(finding, Finding):
        raw_category = finding.category.casefold().replace("-", "_").replace(" ", "_")
        for category in QuestionCategory:
            if category.value == raw_category or category.value in raw_category:
                return category
        values = " ".join(
            _text(value)
            for value in (
                finding.category,
                finding.finding_type.value,
                finding.impact,
                finding.proposed_disposition,
                finding.target_template_section,
                finding.target_object_id,
            )
        ).casefold()
    else:
        raw_category = _text(finding.get("category")).casefold().replace("-", "_").replace(" ", "_")
        for category in QuestionCategory:
            if category.value == raw_category or category.value in raw_category:
                return category
        values = " ".join(_text(value) for value in finding.values()).casefold()
    ranked = [
        (sum(1 for keyword in keywords if keyword in values), _CATEGORY_ORDER[category], category)
        for category, keywords in _KEYWORDS.items()
    ]
    best = max(ranked, key=lambda item: (item[0], -item[1]))
    return best[2] if best[0] else QuestionCategory.MISSING


def question_priority(
    finding: Finding | Mapping[str, Any],
    category: QuestionCategory,
    *,
    strict: bool = False,
) -> tuple[QuestionPriority, bool]:
    if isinstance(finding, Finding):
        severity = finding.severity
        blocking_signal = finding.blocking or severity is FindingSeverity.BLOCKER
        human_required = finding.requires_human_answer
    else:
        severity = FindingSeverity(str(finding.get("severity", "medium")))
        blocking_signal = (
            bool(finding.get("blocking", False)) or severity is FindingSeverity.BLOCKER
        )
        human_required = bool(finding.get("requires_human_answer", True))
    critical_category = category in {
        QuestionCategory.CONFLICT,
        QuestionCategory.CONTROL,
        QuestionCategory.CALCULATION,
        QuestionCategory.DEPENDENCY,
        QuestionCategory.EXCEPTION,
        QuestionCategory.OWNERSHIP,
    }
    blocking = blocking_signal or (strict and human_required and critical_category)
    if blocking:
        return QuestionPriority.BLOCKING, True
    if severity is FindingSeverity.HIGH:
        return QuestionPriority.HIGH, False
    if severity is FindingSeverity.MEDIUM:
        return QuestionPriority.MEDIUM, False
    return QuestionPriority.LOW, False


def _finding_key(finding: Finding, category: QuestionCategory) -> tuple[str, ...]:
    return (
        category.value,
        _text(finding.target_template_section).casefold(),
        _text(finding.target_object_id).casefold(),
        _text(finding.requirement_id).casefold(),
        _normalized_text(finding.proposed_disposition),
    )


def _semantic_similarity(left: str, right: str) -> float:
    left_words = set(_normalized_words(left))
    right_words = set(_normalized_words(right))
    if not left_words or not right_words:
        return SequenceMatcher(None, _normalized_text(left), _normalized_text(right)).ratio()
    overlap = len(left_words & right_words) / len(left_words | right_words)
    return max(
        overlap, SequenceMatcher(None, _normalized_text(left), _normalized_text(right)).ratio()
    )


def _question_text(finding: Finding, category: QuestionCategory) -> str:
    subject = finding.target_template_section or finding.target_object_id or finding.category
    issue = finding.impact.strip()
    disposition = finding.proposed_disposition.strip()
    if issue:
        return f"What is the authoritative resolution for {subject}: {issue}"
    return f"Please resolve the {category.value} issue for {subject}: {disposition}"


def _evidence_key(item: object) -> tuple[str, str]:
    return (str(getattr(item, "span_id", "")), str(getattr(item, "quote", "")))


def _merge_questions(values: Sequence[Question]) -> Question:
    selected = min(values, key=lambda value: value.question_id)
    evidence = {_evidence_key(item): item for value in values for item in value.evidence}
    source_ids = sorted({item for value in values for item in value.source_finding_ids})
    dependencies = sorted({item for value in values for item in value.depends_on_question_ids})
    examples = sorted({item for value in values for item in value.examples})
    return selected.model_copy(
        update={
            "evidence": [evidence[key] for key in sorted(evidence)],
            "source_finding_ids": source_ids,
            "depends_on_question_ids": dependencies,
            "examples": examples,
        }
    )


def _stable_question_id(question: Question) -> str:
    payload = "\0".join(
        (
            question.category.value,
            question.target_section_id or "",
            question.target_object_id or "",
            question.question,
        )
    )
    return f"Q-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:14].upper()}"


def order_questions(questions: Iterable[Question]) -> list[Question]:
    """Topologically order questions while retaining deterministic priority order."""

    values = {question.question_id: question for question in questions}
    indegree = {question_id: 0 for question_id in values}
    children: dict[str, list[str]] = defaultdict(list)
    for question in values.values():
        for dependency in question.depends_on_question_ids:
            if dependency in values and dependency != question.question_id:
                indegree[question.question_id] += 1
                children[dependency].append(question.question_id)
    ready = sorted(
        (question for question_id, question in values.items() if indegree[question_id] == 0),
        key=lambda item: (
            _CATEGORY_ORDER[item.category],
            item.priority.value,
            item.question_id,
        ),
    )
    ordered: list[Question] = []
    while ready:
        question = ready.pop(0)
        ordered.append(question)
        for child_id in sorted(children[question.question_id]):
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                ready.append(values[child_id])
                ready.sort(
                    key=lambda item: (
                        _CATEGORY_ORDER[item.category],
                        item.priority.value,
                        item.question_id,
                    )
                )
    if len(ordered) != len(values):
        cycle = sorted(question_id for question_id, degree in indegree.items() if degree)
        raise ValueError("question prerequisite cycle: " + ", ".join(cycle))
    return ordered


def synthesize_questions(
    findings: FindingSet | Iterable[Finding] | object,
    *,
    document_id: str | None = None,
    version_id: str | None = None,
    strict_blocking: bool = False,
    prerequisite_map: Mapping[str, Sequence[str]] | None = None,
) -> QuestionSynthesisResult:
    """Create questions from findings with exact and conservative semantic deduplication."""

    if hasattr(findings, "synthesis"):
        synthesized = cast(Any, findings)
        findings = cast(FindingSet, synthesized.synthesis.finding_set)
    if isinstance(findings, FindingSet):
        document_id = document_id or findings.document_id
        values = list(findings.findings)
    else:
        values = list(cast(Iterable[Finding], findings))
    if not document_id:
        raise ValueError("document_id is required when synthesizing from raw findings")

    candidates: list[Question] = []
    exact_seen: set[tuple[object, ...]] = set()
    exact_duplicates = 0
    for finding in values:
        category = infer_category(finding)
        priority, blocking = question_priority(finding, category, strict=strict_blocking)
        text = _question_text(finding, category)
        exact_key = _finding_key(finding, category) + (_normalized_text(text),)
        if exact_key in exact_seen:
            exact_duplicates += 1
            continue
        exact_seen.add(exact_key)
        question = Question(
            question_id="Q-PENDING-01",
            category=category,
            priority=priority,
            blocking=blocking,
            question=text,
            why_it_matters=finding.impact,
            evidence=list(finding.evidence),
            source_finding_ids=[finding.finding_id],
            target_section_id=finding.target_template_section,
            target_object_id=finding.target_object_id,
            expected_answer_shape=_EXPECTED_SHAPES[category],
            allowed_statuses=[
                QuestionStatus.ANSWERED,
                QuestionStatus.DEFERRED,
                QuestionStatus.NOT_APPLICABLE,
                QuestionStatus.WAIVED,
            ],
        )
        question = question.model_copy(update={"question_id": _stable_question_id(question)})
        candidates.append(question)

    groups: list[list[Question]] = []
    for candidate in sorted(candidates, key=lambda item: item.question_id):
        match: list[Question] | None = None
        for group in groups:
            anchor = group[0]
            same_scope = (
                anchor.category is candidate.category
                and anchor.target_section_id == candidate.target_section_id
                and anchor.target_object_id == candidate.target_object_id
            )
            if same_scope and _semantic_similarity(anchor.question, candidate.question) >= 0.86:
                match = group
                break
        if match is None:
            groups.append([candidate])
        else:
            match.append(candidate)
    semantic_duplicates = sum(max(0, len(group) - 1) for group in groups)
    merged = [_merge_questions(group) for group in groups]

    by_finding: dict[str, str] = {}
    for question in merged:
        for finding_id in question.source_finding_ids:
            by_finding[finding_id] = question.question_id
    updated: list[Question] = []
    for question in merged:
        dependencies: set[str] = set()
        for finding_id in question.source_finding_ids:
            for dependency in (prerequisite_map or {}).get(finding_id, ()):
                dependency_question_id = by_finding.get(dependency, dependency)
                if dependency_question_id != question.question_id:
                    dependencies.add(dependency_question_id)
        # A deterministic category policy creates useful ordering without pretending to know a
        # business answer: controls/calculations/dependencies/exceptions follow ownership and
        # ambiguity questions when those questions actually exist.
        prerequisite_categories = {
            QuestionCategory.CONTROL: {QuestionCategory.OWNERSHIP, QuestionCategory.MISSING},
            QuestionCategory.CALCULATION: {QuestionCategory.AMBIGUITY, QuestionCategory.MISSING},
            QuestionCategory.DEPENDENCY: {QuestionCategory.OWNERSHIP, QuestionCategory.MISSING},
            QuestionCategory.EXCEPTION: {QuestionCategory.OWNERSHIP, QuestionCategory.CONTROL},
        }.get(question.category, set())
        dependencies.update(
            other.question_id
            for other in merged
            if other.category in prerequisite_categories
            and other.question_id != question.question_id
        )
        updated.append(
            question.model_copy(update={"depends_on_question_ids": sorted(dependencies)})
        )
    ordered = order_questions(updated)
    artifact = QuestionsArtifact(document_id=document_id, version_id=version_id, questions=ordered)
    mapping = {question.question_id: list(question.source_finding_ids) for question in ordered}
    return QuestionSynthesisResult(
        questions=artifact,
        source_finding_ids_by_question=mapping,
        exact_duplicate_count=exact_duplicates,
        semantic_duplicate_count=semantic_duplicates,
        blocking_question_ids=[question.question_id for question in ordered if question.blocking],
    )


__all__ = [
    "infer_category",
    "order_questions",
    "question_priority",
    "synthesize_questions",
]
