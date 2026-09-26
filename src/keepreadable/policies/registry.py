from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from keepreadable.domain.enums import PolicyStatus


class PolicyError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    status: PolicyStatus
    reason_code: str
    explanation: str
    source_label: str | None
    source_url: str | None
    policy_version: str


@dataclass(frozen=True, slots=True)
class PolicyEntry:
    puid: str
    status: PolicyStatus
    reason_code: str
    explanation: str
    source_label: str | None
    source_url: str | None
    reviewed_at: str


class _EntryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PolicyStatus
    reason_code: str
    explanation: str
    source_label: str | None = None
    source_url: str | None = None
    reviewed_at: str


class _RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str
    formats: dict[str, _EntryModel]


class PolicyRegistry:
    def __init__(self, model: _RegistryModel) -> None:
        self.policy_version = model.policy_version
        self._formats = model.formats

    @classmethod
    def load_default(cls) -> PolicyRegistry:
        resource = files("keepreadable.policies").joinpath("formats.yml")
        try:
            payload = yaml.safe_load(resource.read_text(encoding="utf-8"))
            return cls(_RegistryModel.model_validate(payload))
        except (OSError, yaml.YAMLError, ValidationError, TypeError) as exc:
            raise PolicyError("Unable to load the default format policy") from exc

    @classmethod
    def load(cls, path: Path) -> PolicyRegistry:
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            return cls(_RegistryModel.model_validate(payload))
        except (OSError, yaml.YAMLError, ValidationError, TypeError) as exc:
            raise PolicyError(f"Unable to load format policy: {path}") from exc

    def classify(self, puid: str | None) -> PolicyDecision:
        if puid is None or puid.upper() == "UNKNOWN":
            return PolicyDecision(
                PolicyStatus.UNKNOWN,
                "unidentified",
                "The format could not be identified confidently, so no policy guidance applies.",
                None,
                None,
                self.policy_version,
            )
        entry = self._formats.get(puid)
        if entry is None:
            return PolicyDecision(
                PolicyStatus.NORMAL,
                "no_known_concerns",
                "No format-specific access concerns are recorded in the current policy set.",
                None,
                None,
                self.policy_version,
            )
        return PolicyDecision(
            entry.status,
            entry.reason_code,
            entry.explanation,
            entry.source_label,
            entry.source_url,
            self.policy_version,
        )

    def entries(self) -> list[PolicyEntry]:
        return [
            PolicyEntry(
                puid,
                entry.status,
                entry.reason_code,
                entry.explanation,
                entry.source_label,
                entry.source_url,
                entry.reviewed_at,
            )
            for puid, entry in sorted(self._formats.items())
        ]
