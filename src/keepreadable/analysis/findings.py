from dataclasses import dataclass, replace
from datetime import datetime

from keepreadable.domain.enums import FindingState
from keepreadable.domain.finding import Finding


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    to_add: list[Finding]
    to_resolve_ids: list[int]
    to_update: list[Finding]


def reconcile(existing_open: list[Finding], new: list[Finding], now: datetime) -> ReconcileResult:
    active = {
        finding.code: finding
        for finding in existing_open
        if finding.state in {FindingState.OPEN, FindingState.ACKNOWLEDGED}
    }
    ignored = {finding.code for finding in existing_open if finding.state is FindingState.IGNORED}
    produced = {finding.code for finding in new}
    additions: list[Finding] = []
    updates: list[Finding] = []
    seen: set[str] = set()
    for finding in new:
        if finding.code in seen or finding.code in ignored:
            continue
        seen.add(finding.code)
        existing = active.get(finding.code)
        if existing is None:
            additions.append(finding)
        else:
            updates.append(
                replace(
                    existing,
                    evidence=finding.evidence,
                    title=finding.title,
                    description=finding.description,
                    resolved_at=None,
                )
            )
    resolve_ids = [
        finding.id
        for code, finding in active.items()
        if code not in produced and finding.id is not None
    ]
    return ReconcileResult(additions, resolve_ids, updates)
