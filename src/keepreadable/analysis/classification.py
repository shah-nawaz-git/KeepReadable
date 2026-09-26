from dataclasses import dataclass
from datetime import datetime
from typing import Any

from keepreadable.analysis.finding_texts import finding_text
from keepreadable.analysis.hashing import HashResult
from keepreadable.analysis.normalization import extension_of
from keepreadable.analysis.planner import CurrentStat, WorkPlan
from keepreadable.domain.audit import AuditRun
from keepreadable.domain.enums import (
    ChangeKind,
    CheckStatus,
    FindingCategory,
    FindingCode,
    FindingSeverity,
    HealthState,
    PolicyStatus,
    SupportTier,
)
from keepreadable.domain.file_record import FileRecord
from keepreadable.domain.finding import Finding
from keepreadable.domain.health import classify_health
from keepreadable.domain.observation import Observation
from keepreadable.integrations.siegfried import IdentificationResult
from keepreadable.policies.registry import PolicyRegistry
from keepreadable.validators.base import EvidenceCode, ValidationResult


@dataclass(frozen=True, slots=True)
class IdentificationOutcome:
    available: bool
    result: IdentificationResult | None
    signature_version: str | None


@dataclass(frozen=True, slots=True)
class FileWorkResult:
    record: FileRecord
    plan: WorkPlan
    stat: CurrentStat
    identification: IdentificationOutcome | None
    hash: HashResult | None
    validation: ValidationResult | None
    error: str | None
    vanished: bool


@dataclass(frozen=True, slots=True)
class ClassifiedFile:
    observation: Observation
    findings: list[Finding]
    deep_verified: bool
    new_sha256: str | None


def _finding(
    code: FindingCode,
    severity: FindingSeverity,
    category: FindingCategory,
    work: FileWorkResult,
    run: AuditRun,
    now: datetime,
    evidence: dict[str, Any],
    observed: str | None = None,
    title: str | None = None,
) -> Finding:
    text = finding_text(code)
    return Finding(
        file_record_id=work.record.id,
        audit_run_id=run.id or 0,
        code=code.value,
        severity=severity,
        category=category,
        title=title or text.title,
        description=text.description(observed),
        evidence=evidence,
        created_at=now,
        resolved_at=None,
    )


def _validation_finding(
    code: EvidenceCode,
    validation: ValidationResult,
    work: FileWorkResult,
    run: AuditRun,
    now: datetime,
) -> Finding | None:
    mapping = {
        EvidenceCode.STRUCTURAL_FAILURE: (
            FindingCode.STRUCTURAL_FAILURE,
            FindingSeverity.HIGH,
            FindingCategory.UNREADABLE,
        ),
        EvidenceCode.DECODE_FAILURE: (
            FindingCode.DECODE_FAILURE,
            FindingSeverity.HIGH,
            FindingCategory.UNREADABLE,
        ),
        EvidenceCode.UNEXPECTED_TRUNCATION: (
            FindingCode.UNEXPECTED_TRUNCATION,
            FindingSeverity.HIGH,
            FindingCategory.UNREADABLE,
        ),
        EvidenceCode.VALIDATION_WARNING: (
            FindingCode.VALIDATION_WARNING,
            FindingSeverity.LOW,
            FindingCategory.STRUCTURAL_WARNING,
        ),
        EvidenceCode.PROTECTED_CONTENT: (
            FindingCode.PROTECTED_CONTENT,
            FindingSeverity.INFO,
            FindingCategory.PROTECTED,
        ),
        EvidenceCode.VALIDATION_LIMITED: (
            FindingCode.VALIDATION_UNAVAILABLE,
            FindingSeverity.INFO,
            FindingCategory.VALIDATION_UNAVAILABLE,
        ),
    }
    mapped = mapping.get(code)
    if mapped is None:
        return None
    finding_code, severity, category = mapped
    errors = "\n".join(validation.errors)[:2048]
    evidence = {
        **validation.details,
        "errors": errors,
        "checks_performed": list(validation.checks_performed),
        "checks_not_performed": list(validation.checks_not_performed),
    }
    return _finding(
        finding_code,
        severity,
        category,
        work,
        run,
        now,
        evidence,
        observed=validation.summary,
    )


def classify_file(
    work: FileWorkResult,
    previous: Observation | None,
    policy: PolicyRegistry,
    run: AuditRun,
    now: datetime,
) -> ClassifiedFile:
    findings: list[Finding] = []
    extension = extension_of(work.record.relative_path)
    detected_format = format_version = puid = mime_type = None
    extension_matches: bool | None = None
    identification_warning = None

    if work.plan.reuse_previous_identification and previous is not None:
        detected_format = previous.detected_format
        format_version = previous.format_version
        puid = previous.puid
        mime_type = previous.mime_type
        extension_matches = previous.extension_matches_signature
        identification_warning = previous.identification_warning
    elif work.identification is not None:
        outcome = work.identification
        if not outcome.available:
            identification_warning = "identification tool unavailable"
        elif outcome.result is not None and outcome.result.identified:
            match = outcome.result.best_match
            assert match is not None
            detected_format = match.format_name
            format_version = match.version
            puid = match.puid
            mime_type = match.mime
            extension_matches = not outcome.result.extension_mismatch
            if outcome.result.extension_mismatch:
                findings.append(
                    _finding(
                        FindingCode.EXTENSION_MISMATCH,
                        FindingSeverity.MEDIUM,
                        FindingCategory.EXTENSION_MISMATCH,
                        work,
                        run,
                        now,
                        {
                            "extension": extension,
                            "detected_format": detected_format,
                            "puid": puid,
                        },
                    )
                )
        elif outcome.result is not None:
            findings.append(
                _finding(
                    FindingCode.UNKNOWN_FORMAT,
                    FindingSeverity.LOW,
                    FindingCategory.UNKNOWN_FORMAT,
                    work,
                    run,
                    now,
                    {"extension": extension},
                )
            )

    structural = CheckStatus.NOT_CHECKED
    readability = CheckStatus.NOT_CHECKED
    validator_name = validator_version = None
    support_tier = SupportTier.IDENTIFY_ONLY
    validation_details: dict[str, Any] = {}
    if work.plan.reuse_previous_validation and previous is not None:
        structural = previous.structural_status
        readability = previous.readability_status
        validator_name = previous.validator_name
        validator_version = previous.validator_version
        support_tier = previous.support_tier
        validation_details = dict(previous.validation_details)
    elif work.validation is not None:
        validation = work.validation
        structural = validation.structural
        readability = validation.readability
        validator_name = validation.validator_name
        validator_version = validation.validator_version
        support_tier = validation.tier
        validation_details = dict(validation.details)
        for code in dict.fromkeys(validation.codes):
            result = _validation_finding(code, validation, work, run, now)
            if result is not None:
                findings.append(result)

    sha256 = previous.sha256 if previous is not None else work.record.last_sha256
    hashed_at = previous.hashed_at if previous is not None else None
    deep_verified = False
    change_kind = work.plan.change_kind
    new_sha256: str | None = None
    if work.hash is not None:
        hashed_at = now
        if work.hash.changed_during_read:
            sha256 = None
            change_kind = ChangeKind.CHANGED_DURING_SCAN
            findings.append(
                _finding(
                    FindingCode.FILE_CHANGED_DURING_SCAN,
                    FindingSeverity.LOW,
                    FindingCategory.SCAN_ERROR,
                    work,
                    run,
                    now,
                    {
                        "size_before": work.hash.size_before,
                        "size_after": work.hash.size_after,
                        "mtime_ns_before": work.hash.mtime_ns_before,
                        "mtime_ns_after": work.hash.mtime_ns_after,
                    },
                )
            )
        else:
            sha256 = work.hash.sha256
            new_sha256 = sha256
            deep_verified = True
            if previous is not None and previous.sha256 and previous.sha256 != sha256:
                severity = (
                    FindingSeverity.HIGH
                    if work.plan.change_kind is ChangeKind.UNCHANGED
                    else FindingSeverity.MEDIUM
                )
                findings.append(
                    _finding(
                        FindingCode.INTEGRITY_MISMATCH,
                        severity,
                        FindingCategory.INTEGRITY_CHANGE,
                        work,
                        run,
                        now,
                        {
                            "previous_sha256": previous.sha256,
                            "current_sha256": sha256,
                            "previous_verified_at": (
                                previous.hashed_at.isoformat() if previous.hashed_at else None
                            ),
                            "metadata_changed": work.plan.change_kind is ChangeKind.MODIFIED,
                        },
                    )
                )

    if work.error is not None or work.vanished:
        structural = CheckStatus.NOT_CHECKED
        readability = CheckStatus.NOT_CHECKED
        puid = None
        findings.append(
            _finding(
                FindingCode.SCAN_ERROR,
                FindingSeverity.MEDIUM,
                FindingCategory.SCAN_ERROR,
                work,
                run,
                now,
                {"error": (work.error or "file vanished")[:2048]},
            )
        )

    decision = policy.classify(puid)
    if decision.status is PolicyStatus.REVIEW:
        findings.append(
            _finding(
                FindingCode.FORMAT_REVIEW,
                FindingSeverity.LOW,
                FindingCategory.FORMAT_REVIEW,
                work,
                run,
                now,
                {
                    "reason_code": decision.reason_code,
                    "explanation": decision.explanation,
                    "source_label": decision.source_label,
                    "source_url": decision.source_url,
                },
                observed=decision.explanation,
            )
        )
    if (
        previous is not None
        and previous.policy_status is not decision.status
        and work.plan.policy_changed
    ):
        findings.append(
            _finding(
                FindingCode.POLICY_CLASSIFICATION_CHANGED,
                FindingSeverity.INFO,
                FindingCategory.POLICY_CHANGE,
                work,
                run,
                now,
                {
                    "previous_status": previous.policy_status.value,
                    "current_status": decision.status.value,
                },
            )
        )

    identified = puid is not None and not (work.error or work.vanished)
    health = classify_health(
        identified=identified,
        extension_matches=extension_matches,
        structural=structural,
        readability=readability,
        policy=decision.status,
    )
    if work.error is not None or work.vanished:
        health = HealthState.UNKNOWN
    observation = Observation(
        file_record_id=work.record.id or 0,
        audit_run_id=run.id or 0,
        observed_size=work.stat.size,
        observed_mtime_ns=work.stat.mtime_ns,
        sha256=sha256,
        hashed_at=hashed_at,
        extension=extension,
        detected_format=detected_format,
        format_version=format_version,
        puid=puid,
        mime_type=mime_type,
        extension_matches_signature=extension_matches,
        identification_warning=identification_warning,
        structural_status=structural,
        readability_status=readability,
        policy_status=decision.status,
        policy_reason=decision.explanation,
        health=health,
        change_kind=change_kind,
        validator_name=validator_name,
        validator_version=validator_version,
        support_tier=support_tier,
        validation_details=validation_details,
        created_at=now,
    )
    return ClassifiedFile(observation, findings, deep_verified, new_sha256)
