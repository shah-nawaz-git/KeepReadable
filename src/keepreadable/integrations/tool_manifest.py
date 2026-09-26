from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ToolMember(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    from_: str = Field(alias="from")
    to: str


class ToolArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    url: str
    sha256: str
    members: tuple[ToolMember, ...]
    size_hint: int | None = None


class SignatureInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    droid: str
    container: str


class ToolSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    license: str
    homepage: str
    purpose: str
    artifacts: tuple[ToolArtifact, ...]
    signature: SignatureInfo | None = None


class ToolManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int
    tools: dict[str, ToolSpec]


def load_tool_manifest(path: Path | None = None) -> ToolManifest:
    payload = (
        path.read_bytes()
        if path is not None
        else files("keepreadable.resources").joinpath("tools.lock.json").read_bytes()
    )
    return ToolManifest.model_validate_json(payload)
