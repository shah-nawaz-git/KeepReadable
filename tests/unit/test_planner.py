from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import pytest

from keepreadable.analysis.planner import (
    CurrentStat,
    PlanContext,
    PlanReason,
    PreviousState,
    WorkStep,
    plan_file,
)
from keepreadable.domain.enums import AuditMode, ChangeKind, CheckStatus

NOW = datetime(2026, 9, 26, 12, 0)
QUICK_STEPS = frozenset({WorkStep.IDENTIFY, WorkStep.QUICK_STRUCTURE, WorkStep.CLASSIFY})
DEEP_STEPS = frozenset(
    {WorkStep.IDENTIFY, WorkStep.HASH, WorkStep.DEEP_VALIDATE, WorkStep.CLASSIFY}
)
CLASSIFY_ONLY = frozenset({WorkStep.CLASSIFY})
DEEP_REIDENTIFY = frozenset({WorkStep.IDENTIFY, WorkStep.CLASSIFY})
CURRENT = CurrentStat(size=100, mtime_ns=200)
PREVIOUS = PreviousState(
    size=100,
    mtime_ns=200,
    sha256="a" * 64,
    last_deep_verified_at=NOW - timedelta(days=10),
    identified=True,
    structural_status=CheckStatus.PASSED,
    readability_status=CheckStatus.PASSED,
    change_kind=ChangeKind.UNCHANGED,
    signature_version="signatures-1",
    policy_version="policy-1",
)


@dataclass(frozen=True)
class PlannerCase:
    name: str
    mode: AuditMode
    previous: PreviousState | None
    current: CurrentStat
    context_changes: dict[str, object]
    steps: frozenset[WorkStep]
    change_kind: ChangeKind
    reason: PlanReason
    reuse_identification: bool
    reuse_validation: bool
    policy_changed: bool = False


def case(
    name: str,
    mode: AuditMode,
    *,
    previous: PreviousState | None = PREVIOUS,
    current: CurrentStat = CURRENT,
    context_changes: dict[str, object] | None = None,
    steps: frozenset[WorkStep] = CLASSIFY_ONLY,
    change_kind: ChangeKind = ChangeKind.UNCHANGED,
    reason: PlanReason,
    reuse_identification: bool = True,
    reuse_validation: bool = True,
    policy_changed: bool = False,
) -> PlannerCase:
    return PlannerCase(
        name,
        mode,
        previous,
        current,
        context_changes or {},
        steps,
        change_kind,
        reason,
        reuse_identification,
        reuse_validation,
        policy_changed,
    )


CASES = [
    case(
        "new quick",
        AuditMode.QUICK,
        previous=None,
        steps=QUICK_STEPS,
        change_kind=ChangeKind.NEW,
        reason=PlanReason.NEW_FILE,
        reuse_identification=False,
        reuse_validation=False,
    ),
    case(
        "new deep",
        AuditMode.DEEP,
        previous=None,
        steps=DEEP_STEPS,
        change_kind=ChangeKind.NEW,
        reason=PlanReason.NEW_FILE,
        reuse_identification=False,
        reuse_validation=False,
    ),
    *[
        case(
            f"size changed {mode.value}",
            mode,
            current=replace(CURRENT, size=101),
            steps=QUICK_STEPS if mode is AuditMode.QUICK else DEEP_STEPS,
            change_kind=ChangeKind.MODIFIED,
            reason=PlanReason.METADATA_CHANGED,
            reuse_identification=False,
            reuse_validation=False,
        )
        for mode in AuditMode
    ],
    *[
        case(
            f"mtime changed {mode.value}",
            mode,
            current=replace(CURRENT, mtime_ns=201),
            steps=QUICK_STEPS if mode is AuditMode.QUICK else DEEP_STEPS,
            change_kind=ChangeKind.MODIFIED,
            reason=PlanReason.METADATA_CHANGED,
            reuse_identification=False,
            reuse_validation=False,
        )
        for mode in AuditMode
    ],
    case("unchanged quick", AuditMode.QUICK, reason=PlanReason.UNCHANGED_QUICK),
    case("unchanged recent deep", AuditMode.DEEP, reason=PlanReason.UNCHANGED_RECENT),
    case(
        "overdue ignored by quick",
        AuditMode.QUICK,
        previous=replace(PREVIOUS, last_deep_verified_at=NOW - timedelta(days=180)),
        reason=PlanReason.UNCHANGED_QUICK,
    ),
    case(
        "overdue deep",
        AuditMode.DEEP,
        previous=replace(PREVIOUS, last_deep_verified_at=NOW - timedelta(days=180)),
        steps=DEEP_STEPS,
        reason=PlanReason.OVERDUE_DEEP_VERIFICATION,
        reuse_identification=False,
        reuse_validation=False,
    ),
    *[
        case(
            f"failed structural {mode.value}",
            mode,
            previous=replace(PREVIOUS, structural_status=CheckStatus.FAILED),
            steps=QUICK_STEPS if mode is AuditMode.QUICK else DEEP_STEPS,
            reason=PlanReason.PREVIOUS_FAILURE,
            reuse_identification=False,
            reuse_validation=False,
        )
        for mode in AuditMode
    ],
    *[
        case(
            f"unavailable readability {mode.value}",
            mode,
            previous=replace(PREVIOUS, readability_status=CheckStatus.UNAVAILABLE),
            steps=QUICK_STEPS if mode is AuditMode.QUICK else DEEP_STEPS,
            reason=PlanReason.PREVIOUS_FAILURE,
            reuse_identification=False,
            reuse_validation=False,
        )
        for mode in AuditMode
    ],
    case(
        "warning quick retries",
        AuditMode.QUICK,
        previous=replace(PREVIOUS, readability_status=CheckStatus.WARNING),
        steps=QUICK_STEPS,
        reason=PlanReason.PREVIOUS_FAILURE,
        reuse_identification=False,
        reuse_validation=False,
    ),
    case(
        "warning deep remains recent",
        AuditMode.DEEP,
        previous=replace(PREVIOUS, readability_status=CheckStatus.WARNING),
        reason=PlanReason.UNCHANGED_RECENT,
    ),
    case(
        "unidentified quick",
        AuditMode.QUICK,
        previous=replace(PREVIOUS, identified=False),
        steps=QUICK_STEPS,
        reason=PlanReason.SIGNATURE_UPDATED,
        reuse_identification=False,
        reuse_validation=False,
    ),
    case(
        "unidentified deep",
        AuditMode.DEEP,
        previous=replace(PREVIOUS, identified=False),
        steps=DEEP_REIDENTIFY,
        reason=PlanReason.SIGNATURE_UPDATED,
        reuse_identification=False,
    ),
    case(
        "signature updated quick",
        AuditMode.QUICK,
        context_changes={"signature_version": "signatures-2"},
        steps=QUICK_STEPS,
        reason=PlanReason.SIGNATURE_UPDATED,
        reuse_identification=False,
        reuse_validation=False,
    ),
    case(
        "signature updated deep",
        AuditMode.DEEP,
        context_changes={"signature_version": "signatures-2"},
        steps=DEEP_REIDENTIFY,
        reason=PlanReason.SIGNATURE_UPDATED,
        reuse_identification=False,
    ),
    case(
        "policy updated quick",
        AuditMode.QUICK,
        context_changes={"policy_version": "policy-2"},
        reason=PlanReason.UNCHANGED_QUICK,
        policy_changed=True,
    ),
    case(
        "policy updated deep",
        AuditMode.DEEP,
        context_changes={"policy_version": "policy-2"},
        reason=PlanReason.UNCHANGED_RECENT,
        policy_changed=True,
    ),
    case(
        "force deep ignored by quick",
        AuditMode.QUICK,
        context_changes={"force_deep_all": True},
        reason=PlanReason.UNCHANGED_QUICK,
    ),
    case(
        "force deep",
        AuditMode.DEEP,
        context_changes={"force_deep_all": True},
        steps=DEEP_STEPS,
        reason=PlanReason.FORCE_DEEP,
        reuse_identification=False,
        reuse_validation=False,
    ),
    case(
        "changed during scan ignored by quick",
        AuditMode.QUICK,
        previous=replace(PREVIOUS, change_kind=ChangeKind.CHANGED_DURING_SCAN),
        reason=PlanReason.UNCHANGED_QUICK,
    ),
    case(
        "changed during scan deep",
        AuditMode.DEEP,
        previous=replace(PREVIOUS, change_kind=ChangeKind.CHANGED_DURING_SCAN),
        steps=DEEP_STEPS,
        reason=PlanReason.UNTRUSTED_PREVIOUS_RESULT,
        reuse_identification=False,
        reuse_validation=False,
    ),
    case(
        "missing hash ignored by quick",
        AuditMode.QUICK,
        previous=replace(PREVIOUS, sha256=None),
        reason=PlanReason.UNCHANGED_QUICK,
    ),
    case(
        "never deep verified",
        AuditMode.DEEP,
        previous=replace(PREVIOUS, sha256=None),
        steps=DEEP_STEPS,
        reason=PlanReason.NEVER_DEEP_VERIFIED,
        reuse_identification=False,
        reuse_validation=False,
    ),
    case(
        "missing deep date ignored by quick",
        AuditMode.QUICK,
        previous=replace(PREVIOUS, last_deep_verified_at=None),
        reason=PlanReason.UNCHANGED_QUICK,
    ),
    case(
        "missing deep date",
        AuditMode.DEEP,
        previous=replace(PREVIOUS, last_deep_verified_at=None),
        steps=DEEP_STEPS,
        reason=PlanReason.OVERDUE_DEEP_VERIFICATION,
        reuse_identification=False,
        reuse_validation=False,
    ),
]


@pytest.mark.parametrize("planner_case", CASES, ids=lambda item: item.name)
def test_plan_file_table(planner_case: PlannerCase) -> None:
    context = PlanContext(
        mode=planner_case.mode,
        force_deep_all=False,
        now=NOW,
        deep_interval_days=180,
        signature_version="signatures-1",
        policy_version="policy-1",
    )
    context = replace(context, **planner_case.context_changes)
    expected = (
        planner_case.steps,
        planner_case.change_kind,
        planner_case.reason,
        planner_case.reuse_identification,
        planner_case.reuse_validation,
        planner_case.policy_changed,
    )

    first = plan_file(planner_case.previous, planner_case.current, context)
    second = plan_file(planner_case.previous, planner_case.current, context)

    assert first == second
    assert (
        first.steps,
        first.change_kind,
        first.reason,
        first.reuse_previous_identification,
        first.reuse_previous_validation,
        first.policy_changed,
    ) == expected
    assert WorkStep.CLASSIFY in first.steps
