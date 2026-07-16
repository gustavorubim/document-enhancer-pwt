# Model Change Governance Process

Status: fictional evaluation target

## Change intake

The model owner submits a change ticket with the affected methodology, model version, reason, and expected impact. The referenced loss methodology has a different name in one paragraph.

## Impact assessment

The validator assesses data, formula, control, and downstream reporting impact. A materiality threshold is mentioned without a unit or approving role.

## Approval and implementation

The Model Risk Committee approves high-impact changes. The implementation team deploys the approved version after validation evidence is attached.

## Evidence and rollback

The ticket stores validation results, approval minutes, and a rollback package. It depends on the Third-Party Risk Standard for vendor-hosted model evidence.

## Version lifecycle

The prior version is superseded after production monitoring begins. The source does not specify a current-version selection rule for cross-document retrieval.

## Reviewer-approved fixture clarifications

- Q-MCG-001: A change is material at a five-percent expected monthly-loss impact, subject to Model Risk Committee approval. (provenance: answer://fixture/Q-MCG-001)
- Q-MCG-002: The governed dependency is Monthly Loss Forecasting Methodology version 1.0. (provenance: answer://fixture/Q-MCG-002)
- Q-MCG-003: The approved version becomes current when the production-monitoring ticket is approved; the prior version becomes historical at that point. (provenance: answer://fixture/Q-MCG-003)
