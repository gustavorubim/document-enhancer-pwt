"""M7.1-M7.5 and M7.9 audit orchestration and artifact rendering."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from document_enhancer.artifacts.atomic import atomic_write_bytes, atomic_write_json
from document_enhancer.audit.content import (
    ContentAuditor,
    ContentAuditRequest,
    OfflineDeterministicContentAuditor,
)
from document_enhancer.audit.deterministic import run_deterministic_audit
from document_enhancer.audit.diffing import (
    mapping_csv,
    semantic_diff,
    source_target_mapping,
    textual_diff,
)
from document_enhancer.domain.audit import Audit, AuditRoutingDecision, IndependentAuditResult
from document_enhancer.domain.enums import AuditStatus
from document_enhancer.domain.questions import ContentLedger, WaiversArtifact
from document_enhancer.domain.semantic import SemanticDocument
from document_enhancer.ingest.models import RawDocument
from document_enhancer.rewrite import EnhancedDocumentModel, RevisionCounters


def build_audit(
    *,
    run_id: str,
    model: EnhancedDocumentModel,
    semantic: SemanticDocument,
    ledger: ContentLedger,
    raw: RawDocument,
    source_markdown: str,
    enhanced_markdown: str,
    counters: RevisionCounters,
    requirements: Mapping[str, object] | None = None,
    waivers: WaiversArtifact | None = None,
    reviewer_inputs: Mapping[str, object] | None = None,
    content_auditor: ContentAuditor | None = None,
) -> Audit:
    checks = run_deterministic_audit(
        model=model,
        semantic=semantic,
        ledger=ledger,
        raw=raw,
        requirements=requirements,
        waivers=waivers,
    )
    deterministic_blockers = [item for item in checks if item.blocking and not item.passed]
    if deterministic_blockers:
        independent = IndependentAuditResult(
            audit_id="INDAUD-NOT-RUN-DETERMINISTIC-FAILURE",
            status="unavailable",
            findings=[],
            provider="not-run",
            isolated_context=True,
            generated_at=semantic.generated_at,
        )
    else:
        auditor = content_auditor or OfflineDeterministicContentAuditor()
        try:
            independent = auditor.audit(
                ContentAuditRequest(
                    document_id=model.document.id,
                    source_markdown=source_markdown,
                    enhanced_markdown=enhanced_markdown,
                    semantic_document=semantic,
                    reviewer_inputs=dict(reviewer_inputs or {}),
                )
            )
        except Exception:
            independent = IndependentAuditResult(
                audit_id="INDAUD-PROVIDER-UNAVAILABLE",
                status="unavailable",
                findings=[],
                provider=type(auditor).__name__,
                isolated_context=True,
                generated_at=semantic.generated_at,
            )
    content_blockers = [item for item in independent.findings if item.blocking]
    unresolved_ids = [
        item.finding_id
        for item in semantic.open_issues
        if item.blocking
        and item.finding_id
        not in {waiver.target_id for waiver in (waivers.waivers if waivers else ())}
    ]
    blocker_ids = [
        *(item.check_id for item in deterministic_blockers),
        *(item.finding_id for item in content_blockers),
        *unresolved_ids,
    ]
    if independent.status != "pass" and not content_blockers:
        blocker_ids.append("INDEPENDENT-AUDIT-NOT-PASSED")
    auto_revision_candidates = [*deterministic_blockers, *content_blockers]
    auto_revisable = (
        bool(auto_revision_candidates)
        and all(item.auto_revisable for item in auto_revision_candidates)
        and not unresolved_ids
    )
    remaining = max(0, counters.max_audit_revisions - counters.audit_revision)
    if not blocker_ids and independent.status == "pass":
        route, reason, status = (
            "export",
            "all deterministic and independent gates passed",
            AuditStatus.PASS,
        )
    elif auto_revisable and remaining:
        route, reason, status = (
            "auto_revise",
            "all blockers are safely auto-revisable",
            AuditStatus.FAIL,
        )
    elif auto_revisable:
        route, reason, status = "failed", "audit revision budget exhausted", AuditStatus.FAIL
    else:
        route, reason, status = (
            "human_review",
            "one or more failures require human resolution",
            AuditStatus.WAITING,
        )
    mapping = source_target_mapping(ledger)
    text_diff = textual_diff(source_markdown, enhanced_markdown)
    graph_diff = semantic_diff([], [], semantic)
    token = (
        hashlib.sha256(
            (run_id + "\0" + model.document.id + "\0" + (model.markdown_digest or "")).encode()
        )
        .hexdigest()[:16]
        .upper()
    )
    return Audit(
        audit_id=f"AUDIT-{token}",
        document_id=model.document.id,
        version_id=model.version.id,
        status=status,
        deterministic_checks=list(checks),
        independent_audit=independent,
        waivers=list(waivers.waivers if waivers else ()),
        revision_count=counters.audit_revision,
        routing=AuditRoutingDecision(
            route=route,
            reason=reason,
            blocker_ids=blocker_ids,
            audit_revision=counters.audit_revision,
            remaining_audit_revisions=remaining,
        ),
        textual_diff=text_diff,
        semantic_diff=graph_diff,
        source_to_target=list(mapping),
        unresolved_issue_ids=unresolved_ids,
        generated_at=semantic.generated_at,
        summary=reason,
    )


def render_audit_report(audit: Audit) -> str:
    failed = [item for item in audit.deterministic_checks if not item.passed]
    lines = [
        "# Final audit report",
        "",
        f"- Status: **{audit.status.value.upper()}**",
        f"- Route: `{audit.routing.route}`",
        f"- Independent audit: `{audit.independent_audit.status}` via `{audit.independent_audit.provider}`",
        f"- Deterministic checks: {len(audit.deterministic_checks) - len(failed)} passed, {len(failed)} failed",
        f"- Blocking IDs: {', '.join(audit.routing.blocker_ids) if audit.routing.blocker_ids else 'none'}",
        f"- Waivers: {', '.join(item.waiver_id for item in audit.waivers) if audit.waivers else 'none'}",
        "",
        "## Deterministic checks",
        "",
    ]
    for item in audit.deterministic_checks:
        lines.append(
            f"- {'PASS' if item.passed else 'FAIL'} `{item.check_id}` — {item.name}: {item.details}"
        )
    lines.extend(["", "## Independent findings", ""])
    if audit.independent_audit.findings:
        for item in audit.independent_audit.findings:
            lines.append(f"- {item.severity.upper()} `{item.finding_id}` — {item.summary}")
    else:
        lines.append("- none")
    lines.extend(["", "## Final decision", "", audit.routing.reason, ""])
    return "\n".join(lines)


def write_audit_artifacts(audit: Audit, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        directory / "deterministic.json",
        {
            "schema_version": "m7.deterministic-audit.v1",
            "status": audit.status.value,
            "checks": [item.model_dump(mode="json") for item in audit.deterministic_checks],
        },
    )
    atomic_write_json(directory / "content.json", audit.independent_audit.model_dump(mode="json"))
    atomic_write_bytes(directory / "textual.diff.md", audit.textual_diff.encode("utf-8"))
    atomic_write_json(directory / "semantic.diff.yaml", audit.semantic_diff.model_dump(mode="json"))
    atomic_write_bytes(
        directory / "source-to-target.csv", mapping_csv(audit.source_to_target).encode("utf-8")
    )
    atomic_write_json(directory / "audit.json", audit.model_dump(mode="json"))
    atomic_write_bytes(directory / "report.md", render_audit_report(audit).encode("utf-8"))


__all__ = ["build_audit", "render_audit_report", "write_audit_artifacts"]
