from pathlib import Path
from typing import Any

from keepreadable.domain.enums import CheckStatus, SupportTier
from keepreadable.integrations.ffmpeg import FFmpegAdapter, FFprobeError, ProbeResult
from keepreadable.integrations.subprocess_runner import ToolNotFoundError
from keepreadable.utilities.cancellation import CancellationToken
from keepreadable.validators.base import (
    EvidenceCode,
    ValidationDepth,
    ValidationResult,
    guard_validation,
    unavailable_result,
)


class FFmpegMediaValidator:
    name = "ffmpeg-media"
    tier = SupportTier.DEEP

    def __init__(self, adapter: FFmpegAdapter | None) -> None:
        self.adapter = adapter

    def version(self) -> str:
        if self.adapter is None:
            return ""
        return self.adapter.version() or ""

    @guard_validation
    def validate(
        self,
        path: Path,
        *,
        depth: ValidationDepth,
        cancel: CancellationToken | None = None,
    ) -> ValidationResult:
        if self.adapter is None or self.adapter.ffprobe is None:
            return self._unavailable(depth)
        if cancel is not None:
            cancel.raise_if_cancelled()
        try:
            probe = self.adapter.probe(path, cancel=cancel)
        except ToolNotFoundError:
            return self._unavailable(depth)
        except FFprobeError as exc:
            return self._probe_failure(depth, exc)
        details = self._details(probe)
        if depth is ValidationDepth.QUICK:
            return self._quick_result(probe, details)
        return self._deep_result(path, probe, details, cancel)

    def _quick_result(self, probe: ProbeResult, details: dict[str, Any]) -> ValidationResult:
        return ValidationResult(
            self.name,
            self.version(),
            self.tier,
            ValidationDepth.QUICK,
            CheckStatus.PASSED,
            CheckStatus.NOT_CHECKED,
            "Media container and stream metadata were read.",
            details,
            probe.warnings,
            (),
            (EvidenceCode.VALIDATION_WARNING,) if probe.warnings else (),
            ("container probe", "stream metadata"),
            ("full stream decode",),
        )

    def _deep_result(
        self,
        path: Path,
        probe: ProbeResult,
        details: dict[str, Any],
        cancel: CancellationToken | None,
    ) -> ValidationResult:
        assert self.adapter is not None
        if cancel is not None:
            cancel.raise_if_cancelled()
        try:
            decoded = self.adapter.decode_to_null(path, cancel=cancel)
        except ToolNotFoundError:
            return self._unavailable(ValidationDepth.DEEP)
        if decoded.timed_out:
            return ValidationResult(
                self.name,
                self.version(),
                self.tier,
                ValidationDepth.DEEP,
                CheckStatus.PASSED,
                CheckStatus.NOT_CHECKED,
                "Media decoding did not finish within the time limit.",
                details,
                probe.warnings,
                decoded.error_lines,
                (EvidenceCode.VALIDATION_LIMITED,),
                ("container probe", "stream metadata", "partial stream decode"),
                ("complete stream decode",),
            )
        if not decoded.success:
            truncation = self._truncation_evidence("\n".join(decoded.error_lines))
            return ValidationResult(
                self.name,
                self.version(),
                self.tier,
                ValidationDepth.DEEP,
                CheckStatus.PASSED,
                CheckStatus.FAILED,
                (
                    "Media decoding ended before all requested stream data was read."
                    if truncation
                    else "One or more media streams could not be decoded."
                ),
                details,
                probe.warnings,
                decoded.error_lines,
                (
                    EvidenceCode.UNEXPECTED_TRUNCATION
                    if truncation
                    else EvidenceCode.DECODE_FAILURE,
                ),
                ("container probe", "stream metadata", "full stream decode"),
                (),
            )
        return ValidationResult(
            self.name,
            self.version(),
            self.tier,
            ValidationDepth.DEEP,
            CheckStatus.PASSED,
            CheckStatus.PASSED,
            "Media container, stream metadata, and full stream decoding were checked.",
            details,
            probe.warnings,
            (),
            (EvidenceCode.VALIDATION_WARNING,) if probe.warnings else (),
            ("container probe", "stream metadata", "full stream decode"),
            (),
        )

    def _unavailable(self, depth: ValidationDepth) -> ValidationResult:
        return unavailable_result(
            self.name,
            self.tier,
            depth,
            "FFmpeg is not installed, so this media file could not be checked.",
        )

    def _probe_failure(self, depth: ValidationDepth, error: FFprobeError) -> ValidationResult:
        truncation = self._truncation_evidence(str(error))
        return ValidationResult(
            self.name,
            self.version(),
            self.tier,
            depth,
            CheckStatus.FAILED,
            CheckStatus.NOT_CHECKED,
            (
                "Media container data ended before stream metadata could be read."
                if truncation
                else "Media container metadata could not be read."
            ),
            {},
            (),
            (repr(error),),
            (
                EvidenceCode.UNEXPECTED_TRUNCATION
                if truncation
                else EvidenceCode.STRUCTURAL_FAILURE,
            ),
            ("container probe",),
            ("full stream decode",),
        )

    @staticmethod
    def _truncation_evidence(text: str) -> bool:
        lowered = text.casefold()
        direct = ("moov atom not found", "truncat", "end of file", "incomplete", "eof")
        return any(value in lowered for value in direct)

    @staticmethod
    def _details(probe: ProbeResult) -> dict[str, Any]:
        return {
            "container": probe.format_name,
            "duration_seconds": probe.duration,
            "bit_rate": probe.bit_rate,
            "video_streams": [
                {
                    "codec": stream.codec_name,
                    "width": stream.width,
                    "height": stream.height,
                    "avg_frame_rate": stream.avg_frame_rate,
                    "pix_fmt": stream.pix_fmt,
                }
                for stream in probe.video_streams
            ],
            "audio_streams": [
                {
                    "codec": stream.codec_name,
                    "sample_rate": stream.sample_rate,
                    "channels": stream.channels,
                }
                for stream in probe.audio_streams
            ],
            "stream_count": len(probe.streams),
            "has_audio": bool(probe.audio_streams),
            "has_video": bool(probe.video_streams),
        }
