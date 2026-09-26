import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, auto
from fractions import Fraction
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops
from PIL import __version__ as pillow_version

from keepreadable.analysis.hashing import hash_file
from keepreadable.analysis.normalization import extension_of
from keepreadable.config.settings import Settings
from keepreadable.domain.enums import (
    CheckStatus,
    CopyKind,
    VerificationStatus,
)
from keepreadable.domain.file_record import FileRecord
from keepreadable.domain.observation import Observation
from keepreadable.domain.preservation import CopyOperation, GeneratedCopy
from keepreadable.integrations.ffmpeg import FFmpegAdapter
from keepreadable.persistence.database import Database
from keepreadable.persistence.repositories import (
    ArchiveRepository,
    FileRecordRepository,
    GeneratedCopyRepository,
    ObservationRepository,
)
from keepreadable.utilities.cancellation import CancellationToken, OperationCancelled
from keepreadable.utilities.clock import utcnow
from keepreadable.utilities.filesystem import extended_path
from keepreadable.validators.base import ValidationDepth, ValidationResult
from keepreadable.validators.registry import ValidatorRegistry


class CopyError(Exception):
    pass


class InsufficientSpaceError(CopyError):
    pass


class SourceChangedError(CopyError):
    pass


class CopyStage(StrEnum):
    ANALYZING_SOURCE = auto()
    CHECKING_SPACE = auto()
    TRANSFORMING = auto()
    REOPENING_OUTPUT = auto()
    ANALYZING_OUTPUT = auto()
    COMPARING = auto()
    FINISHING = auto()


@dataclass(frozen=True, slots=True)
class CopyProposal:
    operation: CopyOperation
    file_record_id: int
    source_path: Path
    source_format: str
    output_format: str
    purpose: str
    trade_offs: str
    lossy: bool
    estimated_output_bytes: int | None
    destination_dir: Path
    proposed_output_name: str


class PreservationService:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        *,
        ffmpeg: FFmpegAdapter | None,
        validators: ValidatorRegistry,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.db = db
        self.settings = settings
        self.ffmpeg = ffmpeg
        self.validators = validators
        self.clock = clock

    def available_operations(self, file_record_id: int) -> list[CopyOperation]:
        record, observation, _source = self._source(file_record_id)
        if (
            not record.present
            or observation is None
            or observation.structural_status is CheckStatus.FAILED
        ):
            return []
        _validator, support = self.validators.resolve(
            puid=observation.puid,
            extension=observation.extension,
            mime=observation.mime_type,
        )
        family = support.family if support is not None else ""
        if family == "BMP":
            return [CopyOperation.BMP_TO_PNG]
        if family in {"AVI", "MOV"} and self.ffmpeg is not None:
            return [CopyOperation.VIDEO_TO_MP4]
        return []

    def propose(
        self,
        file_record_id: int,
        operation: CopyOperation,
        destination_dir: Path | None = None,
    ) -> CopyProposal:
        if operation not in self.available_operations(file_record_id):
            raise CopyError("This compatibility copy operation is not available")
        record, observation, source = self._source(file_record_id)
        assert observation is not None
        destination = destination_dir or (
            Path(self.settings.copies_default_destination)
            if self.settings.copies_default_destination
            else source.parent
        )
        extension = "mp4" if operation is CopyOperation.VIDEO_TO_MP4 else "png"
        output_name = self._available_name(destination, source.stem, extension)
        if operation is CopyOperation.VIDEO_TO_MP4:
            duration = observation.validation_details.get("duration_seconds")
            estimate = self._video_estimate(record.size, duration)
            return CopyProposal(
                operation,
                file_record_id,
                source,
                observation.detected_format or "AVI or QuickTime video",
                "MP4 container, H.264 video, AAC audio",
                "Create a compatibility copy intended for playback in current software.",
                (
                    "Lossy re-encode: the copy is intended for playback compatibility, "
                    "not as a replacement for the original."
                ),
                True,
                estimate,
                destination,
                output_name,
            )
        return CopyProposal(
            operation,
            file_record_id,
            source,
            observation.detected_format or "Windows Bitmap",
            "PNG",
            "Create a lossless compatibility copy for broader image support.",
            "Pixel values are compared after conversion; the original remains unchanged.",
            False,
            record.size,
            destination,
            output_name,
        )

    def execute(
        self,
        proposal: CopyProposal,
        *,
        cancel: CancellationToken | None = None,
        on_stage: Callable[[CopyStage], None] | None = None,
    ) -> GeneratedCopy:
        token = cancel or CancellationToken()
        temp_path: Path | None = None
        source_hash = ""
        output_hash: str | None = None
        source_analysis: dict[str, Any] = {}
        output_analysis: dict[str, Any] = {}
        verification_details: dict[str, Any] = {}
        try:
            proposal.destination_dir.mkdir(parents=True, exist_ok=True)
            before = proposal.source_path.stat()
            if (
                proposal.destination_dir / proposal.proposed_output_name
            ).resolve() == proposal.source_path.resolve():
                raise CopyError("The compatibility copy destination cannot be the source")
            self._stage(CopyStage.ANALYZING_SOURCE, on_stage)
            source_hash_result = hash_file(proposal.source_path, cancel=token)
            if source_hash_result.changed_during_read:
                raise SourceChangedError("The source changed while it was being analyzed")
            source_hash = source_hash_result.sha256
            source_validation = self._analyze(proposal.source_path, proposal.operation, token)
            source_analysis = self._analysis(source_validation)
            estimate = proposal.estimated_output_bytes
            if proposal.operation is CopyOperation.VIDEO_TO_MP4:
                estimate = self._video_estimate(
                    before.st_size, source_validation.details.get("duration_seconds")
                )
            self._stage(CopyStage.CHECKING_SPACE, on_stage)
            required = estimate if estimate is not None else before.st_size
            if shutil.disk_usage(proposal.destination_dir).free <= required:
                raise InsufficientSpaceError(
                    "There is not enough free space for this compatibility copy"
                )
            self._stage(CopyStage.TRANSFORMING, on_stage)
            temp_path = self._temporary_path(
                proposal.destination_dir,
                "mp4" if proposal.operation is CopyOperation.VIDEO_TO_MP4 else "png",
            )
            transform_details = self._transform(proposal, temp_path, source_validation, token)
            token.raise_if_cancelled()
            after = proposal.source_path.stat()
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                raise SourceChangedError("The source changed during the copy operation")
            self._stage(CopyStage.REOPENING_OUTPUT, on_stage)
            if not temp_path.is_file() or temp_path.stat().st_size == 0:
                raise CopyError("The transformation did not produce an output file")
            self._stage(CopyStage.ANALYZING_OUTPUT, on_stage)
            output_validation = self._analyze(temp_path, proposal.operation, token)
            output_analysis = self._analysis(output_validation)
            output_hash = hash_file(temp_path, cancel=token).sha256
            self._stage(CopyStage.COMPARING, on_stage)
            status, verification_details = self._compare(
                proposal,
                source_validation,
                output_validation,
                transform_details,
                temp_path,
            )
            if status is VerificationStatus.FAILED:
                verification_details.setdefault(
                    "failure_reason", "Output verification did not pass"
                )
                temp_path.unlink(missing_ok=True)
                temp_path = None
                return self._persist(
                    proposal,
                    None,
                    source_hash,
                    output_hash,
                    source_analysis,
                    output_analysis,
                    status,
                    verification_details,
                )
            self._stage(CopyStage.FINISHING, on_stage)
            final_name = self._available_name(
                proposal.destination_dir,
                proposal.source_path.stem,
                "mp4" if proposal.operation is CopyOperation.VIDEO_TO_MP4 else "png",
            )
            final_path = proposal.destination_dir / final_name
            if final_path.resolve() == proposal.source_path.resolve():
                raise CopyError("The compatibility copy destination cannot be the source")
            descriptor = os.open(final_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            try:
                os.replace(temp_path, final_path)
            except Exception:
                final_path.unlink(missing_ok=True)
                raise
            temp_path = None
            return self._persist(
                proposal,
                final_path,
                source_hash,
                output_hash,
                source_analysis,
                output_analysis,
                status,
                verification_details,
            )
        except OperationCancelled:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            self._persist_failure(
                proposal,
                source_hash,
                source_analysis,
                output_analysis,
                "cancelled",
            )
            raise
        except (CopyError, OSError) as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            self._persist_failure(
                proposal,
                source_hash,
                source_analysis,
                output_analysis,
                str(exc),
            )
            if isinstance(exc, CopyError):
                raise
            raise CopyError(str(exc)) from exc
        except Exception as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            self._persist_failure(
                proposal,
                source_hash,
                source_analysis,
                output_analysis,
                repr(exc),
            )
            raise CopyError(str(exc)) from exc

    def list_copies(self, file_record_id: int) -> list[GeneratedCopy]:
        with self.db.session() as session:
            return GeneratedCopyRepository(session).list_for_file(file_record_id)

    def _source(self, file_record_id: int) -> tuple[FileRecord, Observation | None, Path]:
        with self.db.session() as session:
            record = FileRecordRepository(session).get(file_record_id)
            if record is None:
                raise CopyError("The source file record does not exist")
            archive = ArchiveRepository(session).get(record.archive_id)
            if archive is None:
                raise CopyError("The source archive is not registered")
            observation = ObservationRepository(session).latest_for_file(file_record_id)
            return record, observation, Path(archive.root_path) / record.relative_path

    def _analyze(
        self,
        path: Path,
        operation: CopyOperation,
        cancel: CancellationToken,
    ) -> ValidationResult:
        extension = "mp4" if path.suffix.casefold() == ".mp4" else extension_of(path.name)
        validator, _support = self.validators.resolve(puid=None, extension=extension, mime=None)
        return validator.validate(path, depth=ValidationDepth.DEEP, cancel=cancel)

    def _transform(
        self,
        proposal: CopyProposal,
        temp_path: Path,
        source_validation: ValidationResult,
        cancel: CancellationToken,
    ) -> dict[str, Any]:
        if proposal.operation is CopyOperation.BMP_TO_PNG:
            with Image.open(extended_path(proposal.source_path)) as image:
                image.load()
                image.save(extended_path(temp_path), format="PNG", optimize=True)
            return {"resolution_adjusted": False}
        if self.ffmpeg is None:
            raise CopyError("FFmpeg is required for this compatibility copy")
        videos = source_validation.details.get("video_streams", [])
        first_video = videos[0] if isinstance(videos, list) and videos else {}
        width = first_video.get("width") if isinstance(first_video, dict) else None
        height = first_video.get("height") if isinstance(first_video, dict) else None
        adjusted = bool(
            isinstance(width, int) and isinstance(height, int) and (width % 2 or height % 2)
        )
        arguments = [
            "-hide_banner",
            "-nostdin",
            "-y",
            "-i",
            f"file:{extended_path(proposal.source_path)}",
            "-map",
            "0:v:0",
        ]
        if source_validation.details.get("has_audio"):
            arguments.extend(["-map", "0:a:0"])
        else:
            arguments.append("-an")
        frame_rate = first_video.get("avg_frame_rate") if isinstance(first_video, dict) else None
        if isinstance(frame_rate, str) and frame_rate not in {"", "0/0"}:
            arguments.extend(["-r", frame_rate])
        arguments.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "20"])
        arguments.extend(["-pix_fmt", "yuv420p"])
        if adjusted:
            arguments.extend(["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"])
        if source_validation.details.get("has_audio"):
            arguments.extend(["-c:a", "aac", "-b:a", "160k"])
        arguments.extend(["-movflags", "+faststart", str(temp_path)])
        result = self.ffmpeg.run(arguments, cancel=cancel)
        if result.returncode != 0 or result.timed_out:
            tail = result.stderr.decode("utf-8", errors="replace").splitlines()[-20:]
            raise CopyError("Video transformation failed: " + "\n".join(tail))
        return {
            "resolution_adjusted": adjusted,
            "expected_width": width - (width % 2) if adjusted and isinstance(width, int) else width,
            "expected_height": height - (height % 2)
            if adjusted and isinstance(height, int)
            else height,
        }

    def _compare(
        self,
        proposal: CopyProposal,
        source: ValidationResult,
        output: ValidationResult,
        transform: dict[str, Any],
        output_path: Path,
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        if proposal.operation is CopyOperation.BMP_TO_PNG:
            return self._compare_images(proposal.source_path, output_path, source, output)
        return self._compare_video(source, output, transform)

    def _compare_images(
        self,
        source_path: Path,
        output_path: Path,
        source: ValidationResult,
        output: ValidationResult,
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        comparisons: list[dict[str, Any]] = []
        if output.structural is CheckStatus.FAILED or output.readability is CheckStatus.FAILED:
            return VerificationStatus.FAILED, {
                "comparisons": [
                    {
                        "name": "output deep validation",
                        "source": "readable",
                        "output": output.summary,
                        "passed": False,
                    }
                ],
                "checks_not_performed": ["pixel equality"],
            }
        for name in ("width", "height"):
            source_value = source.details.get(name)
            output_value = output.details.get(name)
            comparisons.append(
                {
                    "name": name,
                    "source": source_value,
                    "output": output_value,
                    "passed": source_value == output_value,
                }
            )
        with (
            Image.open(extended_path(source_path)) as source_image,
            Image.open(extended_path(output_path)) as output_image,
        ):
            comparisons.append(
                {
                    "name": "mode compatibility",
                    "source": source_image.mode,
                    "output": output_image.mode,
                    "passed": source_image.mode == output_image.mode
                    or {source_image.mode, output_image.mode} <= {"RGB", "RGBA"},
                }
            )
            source_rgba = source_image.convert("RGBA")
            output_rgba = output_image.convert("RGBA")
            equal = ImageChops.difference(source_rgba, output_rgba).getbbox() is None
            comparisons.append(
                {
                    "name": "pixel equality",
                    "source": source_image.mode,
                    "output": output_image.mode,
                    "passed": equal,
                }
            )
        passed = all(comparison["passed"] for comparison in comparisons)
        return (
            VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
            {
                "comparisons": comparisons,
                "lossless_pixel_equality": equal,
                "checks_not_performed": [],
            },
        )

    def _compare_video(
        self,
        source: ValidationResult,
        output: ValidationResult,
        transform: dict[str, Any],
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        comparisons: list[dict[str, Any]] = []
        checks_not_performed: list[str] = []

        def compare(name: str, source_value: Any, output_value: Any) -> None:
            comparisons.append(
                {
                    "name": name,
                    "source": source_value,
                    "output": output_value,
                    "passed": source_value == output_value,
                }
            )

        source_duration = source.details.get("duration_seconds")
        output_duration = output.details.get("duration_seconds")
        if isinstance(source_duration, (int, float)) and isinstance(output_duration, (int, float)):
            tolerance = max(0.5, float(source_duration) * 0.02)
            comparisons.append(
                {
                    "name": "duration",
                    "source": source_duration,
                    "output": output_duration,
                    "passed": abs(float(source_duration) - float(output_duration)) <= tolerance,
                }
            )
        else:
            checks_not_performed.append("duration comparison")
        source_videos = source.details.get("video_streams", [])
        output_videos = output.details.get("video_streams", [])
        comparisons.append(
            {
                "name": "video stream count",
                "source": len(source_videos),
                "output": len(output_videos),
                "passed": len(source_videos) == len(output_videos) and len(output_videos) >= 1,
            }
        )
        compare(
            "audio presence",
            bool(source.details.get("has_audio")),
            bool(output.details.get("has_audio")),
        )
        if source_videos and output_videos:
            source_video = source_videos[0]
            output_video = output_videos[0]
            compare(
                "width",
                transform.get("expected_width", source_video.get("width")),
                output_video.get("width"),
            )
            compare(
                "height",
                transform.get("expected_height", source_video.get("height")),
                output_video.get("height"),
            )
            source_rate = self._rate(source_video.get("avg_frame_rate"))
            output_rate = self._rate(output_video.get("avg_frame_rate"))
            if source_rate is None or output_rate is None:
                checks_not_performed.append("frame rate comparison")
            else:
                comparisons.append(
                    {
                        "name": "frame rate",
                        "source": source_rate,
                        "output": output_rate,
                        "passed": abs(source_rate - output_rate)
                        <= max(source_rate, output_rate) * 0.01,
                    }
                )
        compare(
            "output full decode",
            True,
            output.readability is CheckStatus.PASSED and not output.errors,
        )
        failed = any(comparison["passed"] is False for comparison in comparisons)
        status = (
            VerificationStatus.FAILED
            if failed
            else VerificationStatus.LIMITED
            if checks_not_performed
            else VerificationStatus.PASSED
        )
        return status, {
            "comparisons": comparisons,
            "checks_not_performed": checks_not_performed,
            "tolerances": {"duration": "max(0.5 seconds, 2%)", "frame_rate": "1%"},
            "resolution_adjusted": bool(transform.get("resolution_adjusted")),
        }

    @staticmethod
    def _rate(value: object) -> float | None:
        if not isinstance(value, str) or value in {"", "0/0"}:
            return None
        try:
            return float(Fraction(value))
        except (ValueError, ZeroDivisionError):
            return None

    @staticmethod
    def _analysis(validation: ValidationResult) -> dict[str, Any]:
        return {
            **validation.details,
            "summary": validation.summary,
            "structural": validation.structural.value,
            "readability": validation.readability.value,
            "checks_performed": list(validation.checks_performed),
            "checks_not_performed": list(validation.checks_not_performed),
            "warnings": list(validation.warnings),
            "errors": list(validation.errors),
        }

    @staticmethod
    def _video_estimate(source_size: int, duration: object) -> int | None:
        if not isinstance(duration, (int, float)):
            return None
        encoded = float(duration) * (4_000_000 + 160_000) / 8
        return int(max(source_size, encoded) * 1.2)

    @staticmethod
    def _available_name(destination: Path, stem: str, extension: str) -> str:
        candidate = f"{stem}.access.{extension}"
        index = 2
        while (destination / candidate).exists():
            candidate = f"{stem}.access-{index}.{extension}"
            index += 1
        return candidate

    @staticmethod
    def _temporary_path(destination: Path, extension: str) -> Path:
        for _attempt in range(100):
            path = destination / f".keepreadable-tmp-{uuid.uuid4().hex}.{extension}"
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            os.close(descriptor)
            return path
        raise CopyError("Unable to reserve a temporary output path")

    @staticmethod
    def _stage(stage: CopyStage, callback: Callable[[CopyStage], None] | None) -> None:
        if callback is not None:
            callback(stage)

    def _persist(
        self,
        proposal: CopyProposal,
        output_path: Path | None,
        source_hash: str,
        output_hash: str | None,
        source_analysis: dict[str, Any],
        output_analysis: dict[str, Any],
        status: VerificationStatus,
        details: dict[str, Any],
    ) -> GeneratedCopy:
        generated = GeneratedCopy(
            source_file_record_id=proposal.file_record_id,
            output_path=str(output_path) if output_path is not None else None,
            copy_kind=CopyKind.ACCESS_COPY,
            operation=proposal.operation.value,
            created_at=self.clock(),
            source_hash=source_hash,
            output_hash=output_hash,
            source_analysis=source_analysis,
            output_analysis=output_analysis,
            verification_status=status,
            verification_details=details,
            tool_versions={
                "ffmpeg": (self.ffmpeg.version() or "unknown") if self.ffmpeg else "not installed",
                "pillow": pillow_version,
            },
        )
        with self.db.session() as session:
            return GeneratedCopyRepository(session).add(generated)

    def _persist_failure(
        self,
        proposal: CopyProposal,
        source_hash: str,
        source_analysis: dict[str, Any],
        output_analysis: dict[str, Any],
        reason: str,
    ) -> GeneratedCopy:
        return self._persist(
            proposal,
            None,
            source_hash,
            None,
            source_analysis,
            output_analysis,
            VerificationStatus.FAILED,
            {"failure_reason": reason, "comparisons": []},
        )
