from __future__ import annotations

from pathlib import Path

from document_enhancer.contracts import ReferencePackLoader as Port
from document_enhancer.references.loader import (
    ApplicabilityContext,
    EnterpriseReferencePackLoader,
    ReferencePackLoader,
    load_reference_pack,
    resolve_precedence,
)

PACK = Path("reference_packs/enterprise_core")


def test_wt0_loader_port_remains_the_protocol() -> None:
    assert ReferencePackLoader is Port


def test_default_pack_loads_with_stable_digests() -> None:
    pack = load_reference_pack(PACK)
    assert pack.pack_id == "enterprise_core"
    assert pack.version == "2.0.0"
    assert pack.pack_sha256 == "539ef6ad2ac59941b7e7efb1df0cb1df3f2215a0519e013861fbd2bfccd3bcdc"
    assert pack.supported_document_types == (
        "process",
        "methodology",
        "standard",
        "desktop_procedure",
    )
    assert len(pack.files) == 27


def test_enterprise_governance_contract_is_present_in_every_template_family() -> None:
    expected = {
        "process": {"TBL-PROC-GOVERNANCE", "TBL-PROC-OBLIGATIONS"},
        "methodology": {"TBL-METH-METADATA", "TBL-METH-OBLIGATIONS"},
        "standard": {"TBL-STD-GOVERNANCE", "TBL-STD-OBLIGATIONS"},
        "desktop_procedure": {"TBL-DESK-GOVERNANCE", "TBL-DESK-OBLIGATIONS"},
    }
    for document_type, table_ids in expected.items():
        requirements = (PACK / "templates" / document_type / "requirements.yaml").read_text(
            encoding="utf-8"
        )
        assert "legal entit" in requirements.lower()
        assert "jurisdiction" in requirements.lower()
        assert "evidence" in requirements.lower()
        for table_id in table_ids:
            assert table_id in requirements


def test_enterprise_context_requires_three_lines_holds_and_no_compliance_claim() -> None:
    governance = (PACK / "context/policies/document-governance.md").read_text(encoding="utf-8")
    retention = (PACK / "context/policies/records-retention.md").read_text(encoding="utf-8")
    manifest = (PACK / "manifest.yaml").read_text(encoding="utf-8")
    assert "as first line" in governance
    assert "as second line" in governance
    assert "as third line" in governance
    assert "Internal Audit **MUST NOT**" in governance
    assert "legal hold" in retention.lower()
    assert "does not establish compliance" in manifest


def test_applicability_filters_context_and_orders_by_precedence() -> None:
    pack = EnterpriseReferencePackLoader().load(PACK)
    context = ApplicabilityContext(
        document_type="process",
        tags=frozenset({"governed_document", "controlled_activity", "records"}),
    )
    resolution = pack.resolve_context(context)
    assert resolution.ok
    assert [item.reference_id for item in resolution.references] == [
        "POL-DOC-GOV-001",
        "POL-REC-001",
        "STD-CONTROL-EVID-001",
        "STD-OPS-DOC-001",
        "STYLE-CORE-001",
    ]
    assert [item.precedence for item in resolution.references] == [
        "policy",
        "policy",
        "standard",
        "standard",
        "style_guide",
    ]
    assert any("CONFLICT-001 surfaced" in conflict for conflict in resolution.conflicts)


def test_context_tags_exclude_non_applicable_sources() -> None:
    pack = load_reference_pack(PACK)
    references = pack.applicable_references(
        {"document_type": "process", "tags": ["governed_document"]}
    )
    ids = {item.reference_id for item in references}
    assert "POL-DOC-GOV-001" in ids
    assert "POL-REC-001" not in ids
    assert "STD-CONTROL-EVID-001" not in ids


def test_explicit_reviewer_steering_has_highest_precedence() -> None:
    pack = load_reference_pack(PACK)
    resolution = resolve_precedence(pack, {"document_type": "process"}, reviewer_steering=True)
    assert resolution.references[0].reference_id == "RUN-REVIEWER-STEERING"
    assert resolution.references[0].path is None
