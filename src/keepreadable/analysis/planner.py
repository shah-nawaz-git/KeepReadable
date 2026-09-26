from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum, auto

from keepreadable.domain.enums import AuditMode, ChangeKind, CheckStatus


class WorkStep(StrEnum):
    IDENTIFY = auto()
    QUICK_STRUCTURE = auto()
    HASH = auto()
    DEEP_VALIDATE = auto()
    CLASSIFY = auto()


class PlanReason(StrEnum):
    NEW_FILE = auto()
    METADATA_CHANGED = auto()
    OVERDUE_DEEP_VERIFICATION = auto()
    PREVIOUS_FAILURE = auto()
    UNTRUSTED_PREVIOUS_RESULT = auto()
    SIGNATURE_UPDATED = auto()
    FORCE_DEEP = auto()
    UNCHANGED_RECENT = auto()
    UNCHANGED_QUICK = auto()
    NEVER_DEEP_VERIFIED = auto()


@dataclass(frozen=True, slots=True)
class PlanContext:
    mode: AuditMode
    force_deep_all: bool
    now: datetime
    deep_interval_days: int
    signature_version: str | None
    policy_version: str


@dataclass(frozen=True, slots=True)
class PreviousState:
    size: int
    mtime_ns: int
    sha256: str | None
    last_deep_verified_at: datetime | None
    identified: bool
    structural_status: CheckStatus
    readability_status: CheckStatus
    change_kind: ChangeKind
    signature_version: str | None
    policy_version: str | None


@dataclass(frozen=True, slots=True)
class CurrentStat:
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class WorkPlan:
    steps: frozenset[WorkStep]
    change_kind: ChangeKind
    reason: PlanReason
    reuse_previous_identification: bool
    reuse_previous_validation: bool
    policy_changed: bool


def _initial_steps(mode: AuditMode) -> frozenset[WorkStep]:
    if mode is AuditMode.DEEP:
        return frozenset(
            {WorkStep.IDENTIFY, WorkStep.HASH, WorkStep.DEEP_VALIDATE, WorkStep.CLASSIFY}
        )
    return frozenset({WorkStep.IDENTIFY, WorkStep.QUICK_STRUCTURE, WorkStep.CLASSIFY})


def _full_plan(
    mode: AuditMode,
    change_kind: ChangeKind,
    reason: PlanReason,
    policy_changed: bool,
) -> WorkPlan:
    return WorkPlan(
        steps=_initial_steps(mode),
        change_kind=change_kind,
        reason=reason,
        reuse_previous_identification=False,
        reuse_previous_validation=False,
        policy_changed=policy_changed,
    )


def _deep_revalidation_reason(previous: PreviousState, ctx: PlanContext) -> PlanReason | None:
    failures = {CheckStatus.FAILED, CheckStatus.UNAVAILABLE}
    reason = None
    if ctx.mode is not AuditMode.DEEP:
        pass
    elif ctx.force_deep_all:
        reason = PlanReason.FORCE_DEEP
    elif previous.change_kind is ChangeKind.CHANGED_DURING_SCAN:
        reason = PlanReason.UNTRUSTED_PREVIOUS_RESULT
    elif previous.sha256 is None:
        reason = PlanReason.NEVER_DEEP_VERIFIED
    elif previous.structural_status in failures or previous.readability_status in failures:
        reason = PlanReason.PREVIOUS_FAILURE
    elif (
        previous.last_deep_verified_at is None
        or ctx.now - previous.last_deep_verified_at >= timedelta(days=ctx.deep_interval_days)
    ):
        reason = PlanReason.OVERDUE_DEEP_VERIFICATION
    return reason


def plan_file(previous: PreviousState | None, current: CurrentStat, ctx: PlanContext) -> WorkPlan:
    if previous is None:
        return _full_plan(ctx.mode, ChangeKind.NEW, PlanReason.NEW_FILE, False)

    policy_changed = ctx.policy_version != previous.policy_version
    if current.size != previous.size or current.mtime_ns != previous.mtime_ns:
        return _full_plan(
            ctx.mode, ChangeKind.MODIFIED, PlanReason.METADATA_CHANGED, policy_changed
        )

    deep_reason = _deep_revalidation_reason(previous, ctx)
    if deep_reason is not None:
        return _full_plan(ctx.mode, ChangeKind.UNCHANGED, deep_reason, policy_changed)

    signature_changed = (
        ctx.signature_version != previous.signature_version or not previous.identified
    )
    if signature_changed:
        steps = {WorkStep.IDENTIFY, WorkStep.CLASSIFY}
        if ctx.mode is AuditMode.QUICK:
            steps.add(WorkStep.QUICK_STRUCTURE)
        return WorkPlan(
            steps=frozenset(steps),
            change_kind=ChangeKind.UNCHANGED,
            reason=PlanReason.SIGNATURE_UPDATED,
            reuse_previous_identification=False,
            reuse_previous_validation=ctx.mode is AuditMode.DEEP,
            policy_changed=policy_changed,
        )

    quick_failures = {CheckStatus.FAILED, CheckStatus.WARNING, CheckStatus.UNAVAILABLE}
    if ctx.mode is AuditMode.QUICK and (
        previous.structural_status in quick_failures
        or previous.readability_status in quick_failures
    ):
        return _full_plan(
            ctx.mode,
            ChangeKind.UNCHANGED,
            PlanReason.PREVIOUS_FAILURE,
            policy_changed,
        )

    reason = (
        PlanReason.UNCHANGED_RECENT if ctx.mode is AuditMode.DEEP else PlanReason.UNCHANGED_QUICK
    )
    return WorkPlan(
        steps=frozenset({WorkStep.CLASSIFY}),
        change_kind=ChangeKind.UNCHANGED,
        reason=reason,
        reuse_previous_identification=True,
        reuse_previous_validation=True,
        policy_changed=policy_changed,
    )
