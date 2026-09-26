from enum import StrEnum

import pytest

from keepreadable.domain.enums import (
    AuditMode,
    AuditStatus,
    ChangeKind,
    CheckStatus,
    CopyKind,
    FindingCategory,
    FindingCode,
    FindingSeverity,
    FindingState,
    HealthState,
    PolicyStatus,
    SupportTier,
    VerificationStatus,
)


@pytest.mark.parametrize(
    "enum_type",
    [
        AuditMode,
        AuditStatus,
        ChangeKind,
        CheckStatus,
        CopyKind,
        FindingCategory,
        FindingCode,
        FindingSeverity,
        FindingState,
        HealthState,
        PolicyStatus,
        SupportTier,
        VerificationStatus,
    ],
)
def test_domain_enums_have_string_values(enum_type: type[StrEnum]) -> None:
    assert enum_type
    assert all(isinstance(member.value, str) for member in enum_type)
