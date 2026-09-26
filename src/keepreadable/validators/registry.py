from collections.abc import Callable
from dataclasses import dataclass

from keepreadable.config.settings import Settings
from keepreadable.domain.enums import SupportTier
from keepreadable.integrations.ffmpeg import FFmpegAdapter
from keepreadable.validators.base import Validator
from keepreadable.validators.identify_only import IdentifyOnlyValidator
from keepreadable.validators.images import PillowImageValidator
from keepreadable.validators.media import FFmpegMediaValidator
from keepreadable.validators.ooxml import OoxmlValidator
from keepreadable.validators.pdf import PdfValidator
from keepreadable.validators.zip_archive import ZipValidator


@dataclass(frozen=True, slots=True)
class FormatSupport:
    family: str
    tier: SupportTier
    puids: frozenset[str]
    extensions: frozenset[str]
    mimes: frozenset[str]
    validator: str


SUPPORT_MATRIX: tuple[FormatSupport, ...] = (
    FormatSupport(
        "JPEG",
        SupportTier.DEEP,
        frozenset(
            {
                "fmt/112",
                "fmt/1507",
                "fmt/41",
                "fmt/42",
                "fmt/43",
                "fmt/44",
                "fmt/645",
                "x-fmt/390",
                "x-fmt/391",
                "x-fmt/398",
            }
        ),
        frozenset({"jpg", "jpeg"}),
        frozenset({"image/jpeg"}),
        "images",
    ),
    FormatSupport(
        "PNG",
        SupportTier.DEEP,
        frozenset({"fmt/11", "fmt/12", "fmt/13", "fmt/935"}),
        frozenset({"png"}),
        frozenset({"image/png", "image/apng"}),
        "images",
    ),
    FormatSupport(
        "TIFF",
        SupportTier.DEEP,
        frozenset({"fmt/10", "fmt/353", "fmt/7", "fmt/8", "fmt/9"}),
        frozenset({"tif", "tiff"}),
        frozenset({"image/tiff"}),
        "images",
    ),
    FormatSupport(
        "BMP",
        SupportTier.DEEP,
        frozenset({"fmt/114", "fmt/115", "fmt/116", "fmt/117", "fmt/118", "fmt/119"}),
        frozenset({"bmp"}),
        frozenset({"image/bmp"}),
        "images",
    ),
    FormatSupport(
        "MP3",
        SupportTier.DEEP,
        frozenset({"fmt/134"}),
        frozenset({"mp3"}),
        frozenset({"audio/mpeg"}),
        "media",
    ),
    FormatSupport(
        "WAV",
        SupportTier.DEEP,
        frozenset(
            {
                "fmt/1",
                "fmt/141",
                "fmt/142",
                "fmt/143",
                "fmt/2",
                "fmt/527",
                "fmt/6",
                "fmt/703",
                "fmt/704",
                "fmt/705",
                "fmt/706",
                "fmt/707",
                "fmt/708",
                "fmt/709",
                "fmt/710",
                "fmt/711",
                "fmt/713",
            }
        ),
        frozenset({"wav"}),
        frozenset({"audio/wav", "audio/x-wav"}),
        "media",
    ),
    FormatSupport(
        "FLAC",
        SupportTier.DEEP,
        frozenset({"fmt/279"}),
        frozenset({"flac"}),
        frozenset({"audio/flac"}),
        "media",
    ),
    FormatSupport(
        "MP4",
        SupportTier.DEEP,
        frozenset({"fmt/199"}),
        frozenset({"mp4", "m4v"}),
        frozenset({"application/mp4", "video/mp4"}),
        "media",
    ),
    FormatSupport(
        "MOV",
        SupportTier.DEEP,
        frozenset({"x-fmt/384"}),
        frozenset({"mov"}),
        frozenset({"video/quicktime"}),
        "media",
    ),
    FormatSupport(
        "AVI",
        SupportTier.DEEP,
        frozenset({"fmt/5"}),
        frozenset({"avi"}),
        frozenset({"video/x-msvideo", "video/avi"}),
        "media",
    ),
    FormatSupport(
        "PDF",
        SupportTier.DEEP,
        frozenset(
            {
                "fmt/1129",
                "fmt/14",
                "fmt/144",
                "fmt/145",
                "fmt/1451",
                "fmt/146",
                "fmt/147",
                "fmt/148",
                "fmt/15",
                "fmt/157",
                "fmt/158",
                "fmt/16",
                "fmt/17",
                "fmt/18",
                "fmt/19",
                "fmt/1910",
                "fmt/1911",
                "fmt/1912",
                "fmt/20",
                "fmt/2050",
                "fmt/2052",
                "fmt/276",
                "fmt/354",
                "fmt/476",
                "fmt/477",
                "fmt/478",
                "fmt/479",
                "fmt/480",
                "fmt/481",
                "fmt/488",
                "fmt/489",
                "fmt/490",
                "fmt/491",
                "fmt/492",
                "fmt/493",
                "fmt/95",
            }
        ),
        frozenset({"pdf"}),
        frozenset({"application/pdf"}),
        "pdf",
    ),
    FormatSupport(
        "ZIP",
        SupportTier.DEEP,
        frozenset({"x-fmt/263"}),
        frozenset({"zip"}),
        frozenset({"application/zip"}),
        "zip",
    ),
    FormatSupport(
        "DOCX",
        SupportTier.STRUCTURAL,
        frozenset({"fmt/1827", "fmt/412", "fmt/494", "fmt/523"}),
        frozenset({"docx", "docm"}),
        frozenset(
            {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-word.document.macroenabled.12",
            }
        ),
        "docx",
    ),
    FormatSupport(
        "XLSX",
        SupportTier.STRUCTURAL,
        frozenset({"fmt/1828", "fmt/214", "fmt/445", "fmt/494"}),
        frozenset({"xlsx", "xlsm"}),
        frozenset(
            {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-excel.sheet.macroenabled.12",
            }
        ),
        "xlsx",
    ),
    FormatSupport(
        "PPTX",
        SupportTier.STRUCTURAL,
        frozenset({"fmt/1829", "fmt/215", "fmt/487", "fmt/494"}),
        frozenset({"pptx", "pptm"}),
        frozenset(
            {
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "application/vnd.ms-powerpoint.presentation.macroenabled.12",
            }
        ),
        "pptx",
    ),
)


class ValidatorRegistry:
    def __init__(self, *, ffmpeg: FFmpegAdapter | None) -> None:
        settings = Settings()
        self.validators: dict[str, Validator] = {
            "images": PillowImageValidator(),
            "media": FFmpegMediaValidator(ffmpeg),
            "pdf": PdfValidator(),
            "zip": ZipValidator(
                settings.zip_max_entries,
                settings.zip_max_declared_size_bytes,
                settings.zip_suspicious_ratio,
            ),
            "docx": OoxmlValidator("docx"),
            "xlsx": OoxmlValidator("xlsx"),
            "pptx": OoxmlValidator("pptx"),
            "identify-only": IdentifyOnlyValidator(),
        }

    def resolve(
        self, *, puid: str | None, extension: str, mime: str | None
    ) -> tuple[Validator, FormatSupport | None]:
        normalized_extension = extension.casefold().lstrip(".")
        normalized_mime = mime.casefold() if mime else None
        support = self._match(
            lambda item: bool(puid) and puid in item.puids,
            normalized_extension,
        )
        if support is None and normalized_mime is not None:
            support = self._match(
                lambda item: normalized_mime in item.mimes,
                normalized_extension,
            )
        if support is None:
            support = self._match(
                lambda item: normalized_extension in item.extensions,
                normalized_extension,
            )
        if support is None:
            return self.validators["identify-only"], None
        return self.validators[support.validator], support

    def tier_for(self, *, puid: str | None, extension: str, mime: str | None) -> SupportTier:
        validator, support = self.resolve(puid=puid, extension=extension, mime=mime)
        return support.tier if support is not None else validator.tier

    @staticmethod
    def _match(predicate: Callable[[FormatSupport], bool], extension: str) -> FormatSupport | None:
        matches = [item for item in SUPPORT_MATRIX if predicate(item)]
        return next(
            (item for item in matches if extension in item.extensions),
            matches[0] if matches else None,
        )
