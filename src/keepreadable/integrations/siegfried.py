import json
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from keepreadable.integrations.subprocess_runner import Runner, run_command
from keepreadable.utilities.cancellation import CancellationToken
from keepreadable.utilities.filesystem import extended_path


@dataclass(frozen=True, slots=True)
class FormatMatch:
    namespace: str
    puid: str | None
    format_name: str | None
    version: str | None
    mime: str | None
    basis: str
    warning: str


@dataclass(frozen=True, slots=True)
class IdentificationResult:
    path: str
    size: int | None
    error: str | None
    matches: tuple[FormatMatch, ...]

    @property
    def best_match(self) -> FormatMatch | None:
        return next(
            (
                match
                for match in self.matches
                if match.namespace.casefold() == "pronom"
                and match.puid is not None
                and match.puid.upper() != "UNKNOWN"
            ),
            None,
        )

    @property
    def identified(self) -> bool:
        return self.best_match is not None

    @property
    def extension_mismatch(self) -> bool:
        return any("extension mismatch" in warning.casefold() for warning in self.warnings)

    @property
    def extension_only(self) -> bool:
        return any("match on extension only" in warning.casefold() for warning in self.warnings)

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(match.warning for match in self.matches if match.warning)


@dataclass(frozen=True, slots=True)
class SiegfriedInfo:
    version: str
    signature_file: str
    signature_created: str | None
    identifiers: str


class SiegfriedError(Exception):
    pass


class SiegfriedOutputError(SiegfriedError):
    pass


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_siegfried_json(payload: bytes) -> tuple[SiegfriedInfo, list[IdentificationResult]]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SiegfriedOutputError("Invalid Siegfried JSON output") from exc
    if not isinstance(document, dict):
        raise SiegfriedOutputError("Siegfried output must be a JSON object")
    files = document.get("files", [])
    identifiers = document.get("identifiers", [])
    if not isinstance(files, list) or not isinstance(identifiers, list):
        raise SiegfriedOutputError("Siegfried files and identifiers must be arrays")

    identifier_details = ""
    for identifier in identifiers:
        if isinstance(identifier, dict) and identifier.get("name") == "pronom":
            identifier_details = _optional_string(identifier.get("details")) or ""
            break
    info = SiegfriedInfo(
        version=_optional_string(document.get("siegfried")) or "",
        signature_file=_optional_string(document.get("signature")) or "",
        signature_created=_optional_string(document.get("created")),
        identifiers=identifier_details,
    )
    results: list[IdentificationResult] = []
    for item in files:
        if not isinstance(item, dict):
            raise SiegfriedOutputError("Siegfried file entries must be objects")
        raw_matches = item.get("matches", [])
        if not isinstance(raw_matches, list):
            raise SiegfriedOutputError("Siegfried matches must be an array")
        matches = tuple(
            FormatMatch(
                namespace=_optional_string(match.get("ns")) or "",
                puid=_optional_string(match.get("id")),
                format_name=_optional_string(match.get("format")),
                version=_optional_string(match.get("version")),
                mime=_optional_string(match.get("mime")),
                basis=_optional_string(match.get("basis")) or "",
                warning=_optional_string(match.get("warning")) or "",
            )
            for match in raw_matches
            if isinstance(match, dict)
        )
        size_value = item.get("filesize")
        results.append(
            IdentificationResult(
                path=_optional_string(item.get("filename")) or "",
                size=size_value if isinstance(size_value, int) else None,
                error=_optional_string(item.get("errors")),
                matches=matches,
            )
        )
    return info, results


def parse_version_output(text: str) -> SiegfriedInfo:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    version_match = re.search(r"\bsiegfried\s+([^\s]+)", lines[0] if lines else "", re.I)
    signature_file = ""
    signature_created = None
    for line in lines[1:]:
        signature_match = re.search(r"([^\\/\s]+\.sig)(?:\s+\(([^)]+)\))?", line)
        if signature_match:
            signature_file = signature_match.group(1)
            signature_created = signature_match.group(2)
            break
    identifiers = ""
    for line in lines:
        match = re.match(r"-\s*pronom:\s*(.+)", line, re.I)
        if match:
            identifiers = match.group(1)
            break
    return SiegfriedInfo(
        version=version_match.group(1) if version_match else "",
        signature_file=signature_file,
        signature_created=signature_created,
        identifiers=identifiers,
    )


class SiegfriedAdapter:
    def __init__(
        self,
        executable: Path,
        home: Path,
        *,
        runner: Runner = run_command,
        timeout: float = 600,
        multi: int = 1,
    ) -> None:
        self.executable = executable
        self.home = home
        self.runner = runner
        self.timeout = timeout
        self.multi = multi

    def info(self) -> SiegfriedInfo:
        result = self.runner(
            [str(self.executable), "-version", "-home", str(self.home)], timeout=15
        )
        if result.timed_out or result.returncode != 0:
            raise SiegfriedError("Unable to read Siegfried version information")
        return parse_version_output(result.stdout.decode("utf-8", errors="replace"))

    def identify(
        self,
        paths: Sequence[Path],
        *,
        cancel: CancellationToken | None = None,
    ) -> dict[str, IdentificationResult]:
        originals = {extended_path(path): str(path) for path in paths}
        list_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", delete=False, suffix=".txt"
            ) as list_file:
                list_path = Path(list_file.name)
                for sent_path in originals:
                    list_file.write(sent_path + "\n")
            result = self.runner(
                [
                    str(self.executable),
                    "-home",
                    str(self.home),
                    "-json",
                    "-multi",
                    str(self.multi),
                    "-f",
                    str(list_path),
                ],
                timeout=self.timeout,
                cancel=cancel,
            )
            if result.timed_out:
                raise SiegfriedError("Siegfried identification timed out")
            try:
                _, identified = parse_siegfried_json(result.stdout)
            except SiegfriedOutputError as exc:
                if result.returncode != 0:
                    detail = result.stderr.decode("utf-8", errors="replace").strip()
                    raise SiegfriedError(detail or "Siegfried identification failed") from exc
                raise
            by_reported_path = {item.path: item for item in identified}
            output: dict[str, IdentificationResult] = {}
            for sent_path, original_path in originals.items():
                item = by_reported_path.get(sent_path) or by_reported_path.get(original_path)
                output[original_path] = (
                    IdentificationResult(
                        path=original_path,
                        size=None,
                        error="not reported by siegfried",
                        matches=(),
                    )
                    if item is None
                    else IdentificationResult(
                        path=original_path,
                        size=item.size,
                        error=item.error,
                        matches=item.matches,
                    )
                )
            return output
        finally:
            if list_path is not None:
                list_path.unlink(missing_ok=True)
