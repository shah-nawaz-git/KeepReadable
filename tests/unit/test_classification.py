from dataclasses import replace
from datetime import datetime

import pytest

from keepreadable.analysis.classification import (
    ClassifiedFile,
    FileWorkResult,
    IdentificationOutcome,
    classify_file,
)
from keepreadable.analysis.hashing import HashResult
from keepreadable.analysis.planner import CurrentStat, PlanReason, WorkPlan, WorkStep
from keepreadable.domain.audit import AuditRun
from keepreadable.domain.enums import (
    AuditMode,
    AuditStatus,
    ChangeKind,
    CheckStatus,
    FindingCode,
    FindingSeverity,
    HealthState,
    PolicyStatus,
    SupportTier,
)
from keepreadable.domain.file_record import FileRecord
from keepreadable.domain.observation import Observation
from keepreadable.integrations.siegfried import FormatMatch, IdentificationResult
from keepreadable.policies.registry import PolicyRegistry
from keepreadable.validators.base import (
    EvidenceCode,
    ValidationDepth,
    ValidationResult,
)

NOW = datetime(2026, 9, 26, 12)
POLICY = PolicyRegistry.load_default()
RUN = AuditRun(
    id=2,
    archive_id=1,
    mode=AuditMode.DEEP,
    status=AuditStatus.RUNNING,
    started_at=NOW,
    completed_at=None,
    policy_version="1.0",
    signature_version="sig",
)
RECORD = FileRecord(
    id=1,
    archive_id=1,
    relative_path="image.jpg",
    normalized_path="image.jpg",
    size=100,
    mtime_ns=200,
    filesystem_identity=None,
    first_seen_audit_id=2,
    last_seen_audit_id=2,
    present=True,
    last_health=None,
    last_deep_verified_at=None,
    last_sha256=None,
)


def plan(
    change: ChangeKind = ChangeKind.NEW,
    *,
    identify: bool = True,
    validate: bool = True,
    hash_file: bool = False,
    reuse_identification: bool = False,
    reuse_validation: bool = False,
    policy_changed: bool = False,
) -> WorkPlan:
    steps = {WorkStep.CLASSIFY}
    if identify:
        steps.add(WorkStep.IDENTIFY)
    if validate:
        steps.add(WorkStep.DEEP_VALIDATE)
    if hash_file:
        steps.add(WorkStep.HASH)
    return WorkPlan(
        frozenset(steps),
        change,
        PlanReason.NEW_FILE,
        reuse_identification,
        reuse_validation,
        policy_changed,
    )


def identification(*, mismatch: bool = False, puid: str = "fmt/11") -> IdentificationOutcome:
    match = FormatMatch(
        "pronom",
        puid,
        "Portable Network Graphics",
        "1.0",
        "image/png",
        "bytes",
        ("extension mismatch" if mismatch else ""),
    )
    return IdentificationOutcome(
        True,
        IdentificationResult("image.jpg", 100, None, (match,)),
        "sig",
    )


def validation(*codes: EvidenceCode) -> ValidationResult:
    return ValidationResult(
        "test",
        "1",
        SupportTier.DEEP,
        ValidationDepth.DEEP,
        CheckStatus.FAILED if EvidenceCode.STRUCTURAL_FAILURE in codes else CheckStatus.PASSED,
        CheckStatus.FAILED
        if any(
            code in codes
            for code in (EvidenceCode.DECODE_FAILURE, EvidenceCode.UNEXPECTED_TRUNCATION)
        )
        else CheckStatus.PASSED,
        "Requested checks produced evidence.",
        {"measured": 1},
        (),
        ("technical",),
        tuple(codes),
        ("test",),
        (),
    )


def previous() -> Observation:
    return Observation(
        id=1,
        file_record_id=1,
        audit_run_id=1,
        observed_size=100,
        observed_mtime_ns=200,
        sha256="a" * 64,
        hashed_at=NOW,
        extension="jpg",
        detected_format="PNG",
        format_version="1.0",
        puid="fmt/11",
        mime_type="image/png",
        extension_matches_signature=True,
        identification_warning=None,
        structural_status=CheckStatus.PASSED,
        readability_status=CheckStatus.PASSED,
        policy_status=PolicyStatus.NORMAL,
        policy_reason=None,
        health=HealthState.HEALTHY,
        change_kind=ChangeKind.UNCHANGED,
        validator_name="old",
        validator_version="1",
        support_tier=SupportTier.DEEP,
        validation_details={"old": True},
        created_at=NOW,
    )


def work(
    work_plan: WorkPlan,
    *,
    identified: IdentificationOutcome | None = None,
    hashed: HashResult | None = None,
    validated: ValidationResult | None = None,
    error: str | None = None,
) -> FileWorkResult:
    return FileWorkResult(
        RECORD,
        work_plan,
        CurrentStat(100, 200),
        identified,
        hashed,
        validated,
        error,
        False,
    )


def codes(result: ClassifiedFile) -> set[str]:
    return {finding.code for finding in result.findings}


def test_unknown_and_unavailable_identification_differ() -> None:
    unknown = classify_file(
        work(
            plan(validate=False),
            identified=IdentificationOutcome(
                True,
                IdentificationResult("image.jpg", 100, None, ()),
                "sig",
            ),
        ),
        None,
        POLICY,
        RUN,
        NOW,
    )
    unavailable = classify_file(
        work(
            plan(validate=False),
            identified=IdentificationOutcome(False, None, None),
        ),
        None,
        POLICY,
        RUN,
        NOW,
    )
    assert FindingCode.UNKNOWN_FORMAT in codes(unknown)
    assert FindingCode.UNKNOWN_FORMAT not in codes(unavailable)
    assert unavailable.observation.identification_warning == "identification tool unavailable"
    assert unavailable.observation.health is HealthState.UNKNOWN


def test_extension_mismatch_finding() -> None:
    result = classify_file(
        work(plan(), identified=identification(mismatch=True), validated=validation()),
        None,
        POLICY,
        RUN,
        NOW,
    )
    finding = next(item for item in result.findings if item.code == FindingCode.EXTENSION_MISMATCH)
    assert finding.severity is FindingSeverity.MEDIUM
    assert result.observation.health is HealthState.REVIEW


@pytest.mark.parametrize(
    ("change", "severity"),
    [(ChangeKind.UNCHANGED, FindingSeverity.HIGH), (ChangeKind.MODIFIED, FindingSeverity.MEDIUM)],
)
def test_integrity_mismatch_severity(change: ChangeKind, severity: FindingSeverity) -> None:
    digest = HashResult("b" * 64, 100, 100, 200, 100, 200)
    result = classify_file(
        work(
            plan(change, hash_file=True),
            identified=identification(),
            hashed=digest,
            validated=validation(),
        ),
        previous(),
        POLICY,
        RUN,
        NOW,
    )
    finding = next(item for item in result.findings if item.code == FindingCode.INTEGRITY_MISMATCH)
    assert finding.severity is severity
    assert result.deep_verified


def test_changed_during_read_has_no_baseline() -> None:
    digest = HashResult("b" * 64, 100, 100, 200, 101, 201)
    result = classify_file(
        work(
            plan(hash_file=True), identified=identification(), hashed=digest, validated=validation()
        ),
        previous(),
        POLICY,
        RUN,
        NOW,
    )
    assert result.observation.sha256 is None
    assert result.observation.change_kind is ChangeKind.CHANGED_DURING_SCAN
    assert FindingCode.FILE_CHANGED_DURING_SCAN in codes(result)
    assert not result.deep_verified


@pytest.mark.parametrize(
    ("evidence_code", "finding_code"),
    [
        (EvidenceCode.STRUCTURAL_FAILURE, FindingCode.STRUCTURAL_FAILURE),
        (EvidenceCode.DECODE_FAILURE, FindingCode.DECODE_FAILURE),
        (EvidenceCode.UNEXPECTED_TRUNCATION, FindingCode.UNEXPECTED_TRUNCATION),
        (EvidenceCode.VALIDATION_WARNING, FindingCode.VALIDATION_WARNING),
        (EvidenceCode.PROTECTED_CONTENT, FindingCode.PROTECTED_CONTENT),
        (EvidenceCode.VALIDATION_LIMITED, FindingCode.VALIDATION_UNAVAILABLE),
    ],
)
def test_validation_code_mapping(evidence_code: EvidenceCode, finding_code: FindingCode) -> None:
    result = classify_file(
        work(plan(), identified=identification(), validated=validation(evidence_code)),
        None,
        POLICY,
        RUN,
        NOW,
    )
    assert finding_code in codes(result)
    assert all(len(item.evidence.get("errors", "")) <= 2048 for item in result.findings)
    details = result.observation.validation_details
    assert details["checks_performed"] == ["test"]
    assert details["checks_not_performed"] == []
    assert details["summary"] == "Requested checks produced evidence."
    assert details["warnings"] == []
    assert details["identification_engine"] == "siegfried"


def test_carry_forward_policy_change_and_scan_error() -> None:
    carried = classify_file(
        work(
            plan(
                identify=False,
                validate=False,
                reuse_identification=True,
                reuse_validation=True,
                policy_changed=True,
            )
        ),
        replace(previous(), policy_status=PolicyStatus.REVIEW),
        POLICY,
        RUN,
        NOW,
    )
    assert carried.observation.detected_format == "PNG"
    assert carried.observation.validator_name == "old"
    assert FindingCode.POLICY_CLASSIFICATION_CHANGED in codes(carried)

    failed = classify_file(work(plan(), error="permission denied"), None, POLICY, RUN, NOW)
    assert failed.observation.health is HealthState.UNKNOWN
    assert FindingCode.SCAN_ERROR in codes(failed)
