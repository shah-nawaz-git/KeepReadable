from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import IO, Protocol
from urllib.parse import urlparse

from keepreadable.integrations.tool_locator import ToolLocator, ToolName
from keepreadable.integrations.tool_manifest import ToolArtifact, ToolManifest, ToolMember
from keepreadable.utilities.cancellation import CancellationToken
from keepreadable.utilities.clock import utcnow


class _DownloadResponse(Protocol):
    def read(self, size: int = -1) -> bytes: ...

    def __enter__(self) -> _DownloadResponse: ...

    def __exit__(self, *args: object) -> None: ...


@dataclass(frozen=True, slots=True)
class BootstrapPlanItem:
    tool: str
    version: str
    url: str
    sha256: str
    size_hint: int | None
    destination: Path


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    tool: str
    installed: bool
    version: str | None
    detail: str | None


class BootstrapError(Exception):
    pass


class ToolBootstrapper:
    def __init__(
        self,
        manifest: ToolManifest,
        tools_dir: Path,
        *,
        opener: Callable[[str], _DownloadResponse] = urllib.request.urlopen,
        download_cache: Path | None = None,
    ) -> None:
        self.manifest = manifest
        self.tools_dir = tools_dir
        self.opener = opener
        self.download_cache = download_cache

    def _selected_tools(self, tools: Sequence[str] | None) -> list[str]:
        selected = list(self.manifest.tools) if tools is None else list(dict.fromkeys(tools))
        unknown = [tool for tool in selected if tool not in self.manifest.tools]
        if unknown:
            raise BootstrapError(f"Unknown tools: {', '.join(unknown)}")
        return selected

    def plan(self, tools: Sequence[str] | None = None) -> list[BootstrapPlanItem]:
        planned: list[BootstrapPlanItem] = []
        for tool in self._selected_tools(tools):
            spec = self.manifest.tools[tool]
            destination = self.tools_dir / tool
            for artifact in spec.artifacts:
                self._validate_url(artifact.url)
                planned.append(
                    BootstrapPlanItem(
                        tool=tool,
                        version=spec.version,
                        url=artifact.url,
                        sha256=artifact.sha256,
                        size_hint=artifact.size_hint,
                        destination=destination,
                    )
                )
        return planned

    def install(
        self,
        tools: Sequence[str] | None = None,
        *,
        progress: Callable[[str, int, int | None], None] | None = None,
        cancel: CancellationToken | None = None,
    ) -> list[BootstrapResult]:
        selected = self._selected_tools(tools)
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        if self.download_cache is not None:
            self.download_cache.mkdir(parents=True, exist_ok=True)
        for tool in selected:
            self._install_tool(tool, progress, cancel)
        inventory = ToolLocator(tools_dir=self.tools_dir).inventory()
        results: list[BootstrapResult] = []
        for tool in selected:
            relevant = (
                [inventory[ToolName.SIEGFRIED]]
                if tool == "siegfried"
                else [inventory[ToolName.FFMPEG], inventory[ToolName.FFPROBE]]
            )
            installed = all(status.installed for status in relevant)
            version = next((status.version for status in relevant if status.version), None)
            detail = (
                None if installed else "; ".join(status.detail or "failed" for status in relevant)
            )
            results.append(BootstrapResult(tool, installed, version, detail))
        return results

    def _install_tool(
        self,
        tool: str,
        progress: Callable[[str, int, int | None], None] | None,
        cancel: CancellationToken | None,
    ) -> None:
        spec = self.manifest.tools[tool]
        destination = self.tools_dir / tool
        destination.mkdir(parents=True, exist_ok=True)
        installed_artifacts: list[str] = []
        for artifact in spec.artifacts:
            archive, temporary = self._obtain_archive(tool, artifact, progress, cancel)
            try:
                installed_artifacts.extend(
                    self._extract_members(archive, destination, artifact.members, cancel)
                )
                if self.download_cache is not None and temporary:
                    cache_path = self.download_cache / artifact.name
                    os.replace(archive, cache_path)
                    temporary = False
            finally:
                if temporary:
                    archive.unlink(missing_ok=True)
        hashes: str | dict[str, str]
        if len(spec.artifacts) == 1:
            hashes = spec.artifacts[0].sha256
        else:
            hashes = {artifact.name: artifact.sha256 for artifact in spec.artifacts}
        metadata = {
            "tool": tool,
            "version": spec.version,
            "sha256": hashes,
            "installed_at": utcnow().isoformat(timespec="seconds") + "Z",
            "artifacts": installed_artifacts,
        }
        metadata_path = destination / "installed.json"
        temporary_metadata = Path(f"{metadata_path}.tmp")
        temporary_metadata.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary_metadata, metadata_path)

    def _obtain_archive(
        self,
        tool: str,
        artifact: ToolArtifact,
        progress: Callable[[str, int, int | None], None] | None,
        cancel: CancellationToken | None,
    ) -> tuple[Path, bool]:
        self._validate_url(artifact.url)
        if self.download_cache is not None:
            cached = self.download_cache / artifact.name
            if cached.is_file() and self._sha256(cached) == artifact.sha256:
                return cached, False
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f"{tool}-", suffix=".download", dir=self.tools_dir
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        downloaded = 0
        try:
            with self.opener(artifact.url) as response, temporary.open("wb") as output:
                while True:
                    if cancel is not None:
                        cancel.raise_if_cancelled()
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress is not None:
                        progress(tool, downloaded, artifact.size_hint)
            actual_hash = self._sha256(temporary)
            if actual_hash != artifact.sha256:
                raise BootstrapError(
                    f"Checksum mismatch for {artifact.name}: expected {artifact.sha256}, "
                    f"received {actual_hash}"
                )
            return temporary, True
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _extract_members(
        self,
        archive: Path,
        destination: Path,
        members: tuple[ToolMember, ...],
        cancel: CancellationToken | None,
    ) -> list[str]:
        installed: list[str] = []
        destination_root = destination.resolve()
        with zipfile.ZipFile(archive) as package:
            for member in members:
                self._validate_member_name(member.from_)
                self._validate_member_name(member.to)
                try:
                    source = package.getinfo(member.from_)
                except KeyError as exc:
                    raise BootstrapError(f"Archive member not found: {member.from_}") from exc
                target = destination / Path(PurePosixPath(member.to))
                resolved_target = target.resolve()
                if not resolved_target.is_relative_to(destination_root):
                    raise BootstrapError(f"Archive target escapes destination: {member.to}")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary_target = Path(f"{target}.tmp")
                try:
                    with package.open(source) as input_file, temporary_target.open("wb") as output:
                        self._copy_member(input_file, output, cancel)
                    os.replace(temporary_target, target)
                finally:
                    temporary_target.unlink(missing_ok=True)
                installed.append(member.to)
        return installed

    @staticmethod
    def _copy_member(
        source: IO[bytes], destination: IO[bytes], cancel: CancellationToken | None
    ) -> None:
        while chunk := source.read(1 << 20):
            if cancel is not None:
                cancel.raise_if_cancelled()
            destination.write(chunk)

    @staticmethod
    def _validate_url(url: str) -> None:
        if urlparse(url).scheme.casefold() != "https":
            raise BootstrapError(f"Tool URL must use HTTPS: {url}")

    @staticmethod
    def _validate_member_name(name: str) -> None:
        posix = PurePosixPath(name)
        windows = PureWindowsPath(name)
        if posix.is_absolute() or windows.is_absolute() or windows.drive or ".." in posix.parts:
            raise BootstrapError(f"Unsafe archive member: {name}")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1 << 20):
                digest.update(chunk)
        return digest.hexdigest()

    def is_installed(self, tool: str) -> bool:
        if tool not in self.manifest.tools:
            return False
        destination = self.tools_dir / tool
        metadata_path = destination / "installed.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        expected = {
            member.to
            for artifact in self.manifest.tools[tool].artifacts
            for member in artifact.members
        }
        return metadata.get("version") == self.manifest.tools[tool].version and all(
            (destination / member).is_file() for member in expected
        )
