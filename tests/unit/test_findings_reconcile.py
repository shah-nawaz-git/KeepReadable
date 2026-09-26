from datetime import datetime

from keepreadable.analysis.findings import reconcile
from keepreadable.domain.enums import FindingCategory, FindingSeverity, FindingState
from keepreadable.domain.finding import Finding

NOW = datetime(2026, 9, 26)


def finding(
    code: str, state: FindingState, finding_id: int | None = None, value: int = 1
) -> Finding:
    return Finding(
        id=finding_id,
        file_record_id=1,
        audit_run_id=1,
        code=code,
        severity=FindingSeverity.LOW,
        category=FindingCategory.STRUCTURAL_WARNING,
        title=code,
        description=code,
        evidence={"value": value},
        state=state,
        created_at=NOW,
        resolved_at=None,
    )


def test_reconcile_add_refresh_ignore_and_resolve() -> None:
    existing = [
        finding("same", FindingState.OPEN, 1),
        finding("ack", FindingState.ACKNOWLEDGED, 2),
        finding("ignored", FindingState.IGNORED, 3),
        finding("gone", FindingState.OPEN, 4),
    ]
    new = [
        finding("same", FindingState.OPEN, value=2),
        finding("ack", FindingState.OPEN, value=3),
        finding("ignored", FindingState.OPEN),
        finding("new", FindingState.OPEN),
    ]
    result = reconcile(existing, new, NOW)
    assert [item.code for item in result.to_add] == ["new"]
    assert result.to_resolve_ids == [4]
    assert {item.code: item.evidence for item in result.to_update} == {
        "same": {"value": 2},
        "ack": {"value": 3},
    }
