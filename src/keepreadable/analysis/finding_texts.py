from dataclasses import dataclass

from keepreadable.domain.enums import FindingCode


@dataclass(frozen=True, slots=True)
class FindingText:
    title: str
    observed: str
    matters: str
    known: str
    action: str

    def description(self, observed: str | None = None) -> str:
        return "\n\n".join((observed or self.observed, self.matters, self.known, self.action))


FINDING_TEXTS: dict[str, FindingText] = {
    FindingCode.INTEGRITY_MISMATCH: FindingText(
        "Checksum differs from the previous deep verification",
        "The SHA-256 checksum differs from the last deep verification.",
        "Bytes have changed since then.",
        "Possible causes include legitimate editing, re-saving, or an unwanted change.",
        (
            "Review the file and its recent history, then acknowledge the finding "
            "if the change was expected."
        ),
    ),
    FindingCode.STRUCTURAL_FAILURE: FindingText(
        "File structure could not be read",
        "The selected validator could not read the expected file structure.",
        "Some software may be unable to open or interpret the file.",
        "Only the reported structural checks were attempted.",
        "Try opening a copy with trusted software and retain the original unchanged.",
    ),
    FindingCode.DECODE_FAILURE: FindingText(
        "File content could not be decoded",
        "The validator could not decode all requested content.",
        "Some content may not be accessible through the tested decoder.",
        "The result applies only to the decoder and checks shown in the details.",
        "Review the technical details and test a copy with another trusted application.",
    ),
    FindingCode.UNEXPECTED_TRUNCATION: FindingText(
        "File data ended unexpectedly",
        "A validator reached the end of the file before completing a requested check.",
        "The tested structure or content could not be read completely.",
        "The validator details identify which check stopped.",
        "Compare with another copy if available and retain this file unchanged.",
    ),
    FindingCode.VALIDATION_WARNING: FindingText(
        "Validation warning",
        "A validator reported a warning during its checks.",
        "The warning may need review even though other checks completed.",
        "The technical details preserve the validator's evidence.",
        "Review the warning and test a copy with the software you normally use.",
    ),
    FindingCode.EXTENSION_MISMATCH: FindingText(
        "File extension differs from detected format",
        "The filename extension does not match the detected file format.",
        "Software that relies on extensions may choose the wrong application.",
        "The detected format and signature evidence are recorded with this finding.",
        "Review the file; do not rename the original until you understand why the names differ.",
    ),
    FindingCode.UNKNOWN_FORMAT: FindingText(
        "Format could not be identified",
        "The format could not be identified from the available signature evidence.",
        "Format-specific guidance and deep checks may be limited.",
        "This result does not imply damage to the file.",
        "Try opening a copy with the software that created it and record what you learn.",
    ),
    FindingCode.FORMAT_REVIEW: FindingText(
        "Format may benefit from an access copy",
        "The current policy set marks this format for review.",
        "A current compatibility format may be easier to access with different software.",
        "The policy source and explanation are included in the evidence.",
        "Keep the original and consider creating a verified compatibility copy.",
    ),
    FindingCode.VALIDATION_UNAVAILABLE: FindingText(
        "Validation was limited",
        "A requested validation step was not completed.",
        "The file has less validation evidence than files whose checks completed.",
        "The details state which checks were and were not performed.",
        "Review the details and retry when the required tool or resources are available.",
    ),
    FindingCode.TOOL_UNAVAILABLE: FindingText(
        "Validation tool unavailable",
        "An external validation tool was not available.",
        "Some identification or readability checks could not run.",
        "Other completed checks remain recorded.",
        "Install the pinned tool and run another audit when convenient.",
    ),
    FindingCode.SCAN_ERROR: FindingText(
        "This file could not be checked",
        "The audit encountered an error while checking this file.",
        "No conclusion about file readability can be drawn from an incomplete check.",
        "The technical error is recorded in the evidence.",
        "Retry the audit and review file permissions or availability if it happens again.",
    ),
    FindingCode.PROTECTED_CONTENT: FindingText(
        "Protected content was not deeply validated",
        "Password protection or encryption prevented content checks.",
        "Readability could not be tested without the required access information.",
        "Container-level evidence may still have been recorded.",
        "Open a copy with the appropriate password and trusted software when available.",
    ),
    FindingCode.FILE_CHANGED_DURING_SCAN: FindingText(
        "File changed while being read",
        "File metadata changed while the audit was reading it.",
        "The checksum is not retained as a baseline because the read was not stable.",
        "The file will be eligible for verification during the next audit.",
        "Avoid editing the file during the next audit and run it again.",
    ),
    FindingCode.FILE_MISSING: FindingText(
        "File no longer found at its previous location",
        "A previously recorded path was not found during this audit.",
        "The audit cannot distinguish every move from a removal without matching evidence.",
        "The original path and any matching new path are recorded when available.",
        "Review the archive location and confirm whether the file was intentionally moved.",
    ),
    FindingCode.DUPLICATE_CONTENT: FindingText(
        "Byte-identical copies detected",
        "Multiple present files share the same size and SHA-256 checksum.",
        "These copies may be intentional or may use unnecessary storage.",
        "Only byte identity was checked; filenames and intended roles may differ.",
        "Review the listed paths before making any storage decisions.",
    ),
    FindingCode.POLICY_CLASSIFICATION_CHANGED: FindingText(
        "Policy classification changed",
        "Policy classification changed. The file itself did not change.",
        "Guidance can change as the local policy set is reviewed.",
        "The current and previous policy statuses are recorded.",
        "Review the new guidance; no file modification is required by KeepReadable.",
    ),
}


def finding_text(code: str) -> FindingText:
    return FINDING_TEXTS.get(code, FINDING_TEXTS[FindingCode.SCAN_ERROR])
