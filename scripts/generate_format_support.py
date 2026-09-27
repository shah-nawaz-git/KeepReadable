import argparse
from pathlib import Path

from keepreadable.policies.registry import PolicyRegistry
from keepreadable.validators.registry import SUPPORT_MATRIX

ROOT = Path(__file__).resolve().parents[1]

CHECKS = {
    "images": (
        "Open and verify image structure; record dimensions, mode, frames, and metadata",
        "Quick checks plus full pixel decoding of every frame",
        "Visual appearance and colour-management fidelity",
    ),
    "media": (
        "Probe container and stream metadata with ffprobe",
        "Quick checks plus full stream decoding with FFmpeg",
        "Visual or perceptual identity",
    ),
    "pdf": (
        "Header, end marker, object structure, encryption, and page count",
        "Quick checks plus syntax checks, page-object access, and independent page count",
        "PDF/A or ISO conformance and visual rendering fidelity",
    ),
    "zip": (
        "Container structure, entry metadata, encryption flags, names, and declared sizes",
        "Quick checks plus CRC reading of every unencrypted entry",
        "The archive is never extracted; application-specific meaning of entries",
    ),
    "docx": (
        "Required OOXML parts and main WordprocessingML parsing",
        "Quick checks plus all bounded XML parts and python-docx load",
        "Visual rendering and layout fidelity",
    ),
    "xlsx": (
        "Required OOXML parts and workbook XML parsing",
        "Quick checks plus all bounded XML parts and openpyxl read-only load",
        "Formula recalculation and visual rendering fidelity",
    ),
    "pptx": (
        "Required OOXML parts and presentation XML parsing",
        "Quick checks plus all bounded XML parts and python-pptx load",
        "Slide rendering, animations, and layout fidelity",
    ),
}


TIER3_TEXT = (
    "Formats outside the matrix can still be identified by Siegfried when a PRONOM signature "
    "matches. KeepReadable records the identity and policy evidence, but does not claim "
    "structural or deep readability validation for those formats."
)
POLICY_TEXT = (
    "The local policy registry is intentionally small and conservative. A REVIEW decision is "
    "guidance about access convenience, not evidence that file bytes changed."
)


def generate_document() -> str:
    lines = [
        "# Format support",
        "",
        "This file is generated from `SUPPORT_MATRIX` and `policies/formats.yml`.",
        "Run `python -m uv run python scripts/generate_format_support.py` "
        "after changing either registry.",
        "",
        "## Validation support matrix",
        "",
        "| Family | Tier | PUIDs | Extensions | Validator | Quick checks | Deep checks "
        "| Not checked |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for support in SUPPORT_MATRIX:
        quick, deep, not_checked = CHECKS[support.validator]
        cells = (
            support.family,
            support.tier.value.replace("_", " ").title(),
            ", ".join(sorted(support.puids)),
            ", ".join(f".{value}" for value in sorted(support.extensions)),
            f"`{support.validator}`",
            quick,
            deep,
            not_checked,
        )
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "## Tier 3: identify only",
            "",
            TIER3_TEXT,
            "",
            "## Policy review entries",
            "",
            POLICY_TEXT,
            "",
            "| PUID | Status | Reason code | Explanation | Source | Reviewed |",
            "|---|---|---|---|---|---|",
        ]
    )
    for entry in PolicyRegistry.load_default().entries():
        source = (
            f"[{entry.source_label}]({entry.source_url})"
            if entry.source_label and entry.source_url
            else entry.source_label or "—"
        )
        lines.append(
            f"| {entry.puid} | {entry.status.value.title()} | `{entry.reason_code}` | "
            f"{entry.explanation} | {source} | {entry.reviewed_at} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs" / "FORMAT_SUPPORT.md",
    )
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(generate_document(), encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
