from pathlib import Path

import pytest

from keepreadable.domain.enums import PolicyStatus
from keepreadable.policies.registry import PolicyError, PolicyRegistry


def test_default_policy_review_normal_and_unknown() -> None:
    policy = PolicyRegistry.load_default()
    assert policy.policy_version == "1.0"
    review = policy.classify("fmt/40")
    assert review.status is PolicyStatus.REVIEW
    assert review.reason_code == "legacy_binary_office"
    assert review.source_url is not None
    normal = policy.classify("fmt/11")
    assert normal.status is PolicyStatus.NORMAL
    assert normal.reason_code == "no_known_concerns"
    unknown = policy.classify("UNKNOWN")
    assert unknown.status is PolicyStatus.UNKNOWN
    assert unknown.reason_code == "unidentified"
    assert "could not be identified confidently" in unknown.explanation
    assert len(policy.entries()) >= 40


def test_malformed_policy_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.yml"
    path.write_text("policy_version: 1\nformats: []\n", encoding="utf-8")
    with pytest.raises(PolicyError):
        PolicyRegistry.load(path)
