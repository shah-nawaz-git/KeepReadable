from keepreadable.domain.enums import SupportTier
from keepreadable.validators.identify_only import IdentifyOnlyValidator
from keepreadable.validators.images import PillowImageValidator
from keepreadable.validators.media import FFmpegMediaValidator
from keepreadable.validators.ooxml import OoxmlValidator
from keepreadable.validators.pdf import PdfValidator
from keepreadable.validators.registry import ValidatorRegistry


def test_resolve_by_puid_mime_and_extension_fallback() -> None:
    registry = ValidatorRegistry(ffmpeg=None)
    by_puid, png = registry.resolve(puid="fmt/11", extension="bin", mime=None)
    by_mime, pdf = registry.resolve(puid=None, extension="bin", mime="application/pdf")
    by_extension, mp4 = registry.resolve(puid=None, extension=".mp4", mime=None)

    assert isinstance(by_puid, PillowImageValidator)
    assert png is not None and png.family == "PNG"
    assert isinstance(by_mime, PdfValidator)
    assert pdf is not None and pdf.family == "PDF"
    assert isinstance(by_extension, FFmpegMediaValidator)
    assert mp4 is not None and mp4.family == "MP4"


def test_shared_encrypted_office_puid_uses_extension() -> None:
    registry = ValidatorRegistry(ffmpeg=None)
    validator, support = registry.resolve(puid="fmt/494", extension="xlsx", mime=None)
    assert isinstance(validator, OoxmlValidator)
    assert validator.kind == "xlsx"
    assert support is not None and support.family == "XLSX"


def test_unknown_uses_identify_only_tier_three() -> None:
    registry = ValidatorRegistry(ffmpeg=None)
    validator, support = registry.resolve(puid="UNKNOWN", extension="bin", mime=None)
    assert isinstance(validator, IdentifyOnlyValidator)
    assert support is None
    assert (
        registry.tier_for(puid="UNKNOWN", extension="bin", mime=None) is SupportTier.IDENTIFY_ONLY
    )
