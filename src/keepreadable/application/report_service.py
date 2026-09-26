import os
import re
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from jinja2 import Environment, select_autoescape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from keepreadable import __version__
from keepreadable.config.settings import Settings
from keepreadable.domain.audit import AuditRun
from keepreadable.domain.enums import (
    AuditMode,
    CheckStatus,
    FindingCode,
    HealthState,
    SupportTier,
)
from keepreadable.persistence.database import Database
from keepreadable.persistence.repositories import (
    ArchiveRepository,
    AuditRunRepository,
    FileRecordRepository,
    FindingRepository,
    GeneratedCopyRepository,
    ObservationRepository,
)
from keepreadable.utilities.clock import utcnow
from keepreadable.validators.registry import ValidatorRegistry


def _label(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw).replace("_", " ").capitalize()


@dataclass(frozen=True, slots=True)
class ReportCounts:
    files_discovered: int
    files_processed: int
    files_failed: int
    files_skipped: int
    healthy: int
    review: int
    unreadable: int
    unknown: int
    unexpected_changes: int
    protected: int
    tier3_identified_only: int


@dataclass(frozen=True, slots=True)
class ReportFinding:
    severity: str
    code: str
    title: str
    relative_path: str | None
    description: str
    evidence: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReportCopy:
    source_path: str
    output_path: str | None
    operation: str
    verification_status: str
    comparisons: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class ReportData:
    archive_name: str
    root_path: str
    generated_at: datetime
    run: AuditRun
    mode_label: str
    policy_version: str
    signature_version: str | None
    tool_versions: dict[str, str]
    counts: ReportCounts
    coverage: tuple[int, int, float, int]
    findings: list[ReportFinding]
    findings_more_count: int
    generated_copies: list[ReportCopy]
    limitations: list[str]
    skipped_summary: dict[str, int]


class ReportService:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        validators: ValidatorRegistry,
    ) -> None:
        self.db = db
        self.settings = settings
        self.validators = validators

    def build(self, run_id: int) -> ReportData:
        generated_at = utcnow()
        with self.db.session() as session:
            runs = AuditRunRepository(session)
            run = runs.get(run_id)
            if run is None:
                raise ValueError(f"Audit run {run_id} does not exist")
            archive = ArchiveRepository(session).get(run.archive_id)
            if archive is None:
                raise ValueError(f"Archive {run.archive_id} does not exist")
            observations = ObservationRepository(session).list_for_run(run_id)
            health_counts = Counter(item.health for item in observations)
            protected = sum(
                item.readability_status is CheckStatus.PROTECTED for item in observations
            )
            tier3 = sum(
                item.support_tier is SupportTier.IDENTIFY_ONLY and item.puid is not None
                for item in observations
            )
            finding_repository = FindingRepository(session)
            unexpected = sum(
                finding.code == FindingCode.INTEGRITY_MISMATCH.value
                for finding in finding_repository.latest_findings(run.archive_id)
            )
            all_findings = finding_repository.list(run_id=run_id)
            file_repository = FileRecordRepository(session)
            severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
            report_findings = [
                ReportFinding(
                    finding.severity.value,
                    finding.code,
                    finding.title,
                    self._relative_path(file_repository, finding.file_record_id),
                    finding.description,
                    self._finding_evidence(finding.evidence),
                )
                for finding in all_findings
            ]
            report_findings.sort(
                key=lambda item: (
                    severity_order.get(item.severity, 4),
                    (item.relative_path or "").casefold(),
                )
            )
            more_count = max(0, len(report_findings) - 500)
            report_findings = report_findings[:500]
            coverage = file_repository.deep_verification_coverage(
                run.archive_id, self.settings.deep_verification_interval_days
            )
            verified, total = coverage
            report_coverage = (
                verified,
                total,
                verified / total * 100 if total else 0.0,
                self.settings.deep_verification_interval_days,
            )
            copies = []
            for generated in GeneratedCopyRepository(session).list_for_archive(run.archive_id):
                source = file_repository.get(generated.source_file_record_id)
                copies.append(
                    ReportCopy(
                        source.relative_path if source else "Unknown source",
                        generated.output_path,
                        generated.operation,
                        generated.verification_status.value,
                        list(generated.verification_details.get("comparisons", [])),
                    )
                )
        counts = ReportCounts(
            run.files_discovered,
            run.files_processed,
            run.files_failed,
            run.files_skipped,
            health_counts[HealthState.HEALTHY],
            health_counts[HealthState.REVIEW],
            health_counts[HealthState.UNREADABLE],
            health_counts[HealthState.UNKNOWN],
            unexpected,
            protected,
            tier3,
        )
        skipped = Counter(
            item.get("reason", "unknown")
            for item in run.resume_state.get("skipped", [])
            if isinstance(item, dict)
        )
        limitations = self._limitations(run, counts, report_coverage)
        return ReportData(
            archive.name,
            archive.root_path,
            generated_at,
            run,
            _label(run.mode),
            run.policy_version,
            run.signature_version,
            dict(run.tool_versions),
            counts,
            report_coverage,
            report_findings,
            more_count,
            copies,
            limitations,
            dict(skipped),
        )

    def render_html(self, data: ReportData) -> str:
        template_text = (
            files("keepreadable.reporting.templates")
            .joinpath("report.html.j2")
            .read_text(encoding="utf-8")
        )
        environment = Environment(
            autoescape=select_autoescape(default=True),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        environment.filters["label"] = _label
        return environment.from_string(template_text).render(data=data)

    def render_pdf(self, data: ReportData, path: Path) -> None:
        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                "KRTitle",
                parent=styles["Title"],
                textColor=colors.HexColor("#1F2933"),
                alignment=TA_CENTER,
                spaceAfter=14,
            )
        )
        styles.add(
            ParagraphStyle(
                "KRSmall",
                parent=styles["BodyText"],
                fontSize=8,
                leading=10,
            )
        )
        document = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            rightMargin=16 * mm,
            leftMargin=16 * mm,
            topMargin=16 * mm,
            bottomMargin=18 * mm,
        )
        story: list[Flowable] = [
            Paragraph("KeepReadable Audit Report", styles["KRTitle"]),
            Paragraph(escape(data.archive_name), styles["Heading1"]),
            Paragraph(escape(data.root_path), styles["KRSmall"]),
            Spacer(1, 8),
        ]
        story.extend(self._pdf_summary(data, styles))
        story.append(Paragraph("Results", styles["Heading2"]))
        result_rows = [
            ["Healthy", data.counts.healthy],
            ["Review", data.counts.review],
            ["Unreadable", data.counts.unreadable],
            ["Unknown", data.counts.unknown],
            ["Protected", data.counts.protected],
        ]
        story.append(self._pdf_table([["State", "Files"], *result_rows]))
        story.append(Spacer(1, 8))
        story.append(Paragraph("Findings", styles["Heading2"]))
        finding_rows: list[list[object]] = [["Severity", "Finding", "Path"]]
        for finding in data.findings:
            finding_rows.append(
                [
                    finding.severity.title(),
                    Paragraph(escape(finding.title), styles["KRSmall"]),
                    Paragraph(escape(finding.relative_path or "Archive-level"), styles["KRSmall"]),
                ]
            )
        if data.findings_more_count:
            finding_rows.append(["", f"and {data.findings_more_count} more", ""])
        story.append(self._pdf_table(finding_rows, (24 * mm, 85 * mm, 65 * mm)))
        story.append(Spacer(1, 8))
        story.append(Paragraph("Compatibility copies", styles["Heading2"]))
        copy_rows: list[list[object]] = [["Source", "Output", "Status"]]
        for item in data.generated_copies:
            copy_rows.append(
                [
                    Paragraph(escape(item.source_path), styles["KRSmall"]),
                    Paragraph(escape(item.output_path or "No output retained"), styles["KRSmall"]),
                    item.verification_status.title(),
                ]
            )
        if len(copy_rows) == 1:
            copy_rows.append(["None recorded", "", ""])
        story.append(self._pdf_table(copy_rows, (58 * mm, 88 * mm, 28 * mm)))
        story.append(Spacer(1, 8))
        story.append(Paragraph("Limitations", styles["Heading2"]))
        for limitation in data.limitations:
            story.append(Paragraph(f"• {escape(limitation)}", styles["BodyText"]))
        document.build(
            story,
            onFirstPage=self._pdf_footer,
            onLaterPages=self._pdf_footer,
        )

    def generate(
        self,
        run_id: int,
        output_dir: Path,
        *,
        formats: Sequence[str] = ("html", "pdf"),
    ) -> list[Path]:
        requested = [value.casefold() for value in formats]
        if not requested or any(value not in {"html", "pdf"} for value in requested):
            raise ValueError("Report formats must be html and/or pdf")
        data = self.build(run_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", data.archive_name.casefold()).strip("-")
        slug = slug or "archive"
        stamp = data.generated_at.strftime("%Y%m%d-%H%M")
        stem = f"KeepReadable-{slug}-{stamp}-{data.run.mode.value}"
        generated: list[Path] = []
        for report_format in requested:
            final_path = self._available_path(output_dir, stem, report_format)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".keepreadable-report-",
                suffix=f".{report_format}",
                dir=output_dir,
            )
            os.close(descriptor)
            temporary_path = Path(temporary_name)
            try:
                if report_format == "html":
                    temporary_path.write_text(self.render_html(data), encoding="utf-8")
                else:
                    self.render_pdf(data, temporary_path)
                os.replace(temporary_path, final_path)
            finally:
                temporary_path.unlink(missing_ok=True)
            generated.append(final_path)
        return generated

    @staticmethod
    def _relative_path(repository: FileRecordRepository, file_record_id: int | None) -> str | None:
        if file_record_id is None:
            return None
        record = repository.get(file_record_id)
        return record.relative_path if record is not None else None

    @staticmethod
    def _finding_evidence(evidence: dict[str, object]) -> dict[str, object]:
        allowed = {
            "detected_format",
            "puid",
            "previous_sha256",
            "current_sha256",
            "sha256",
            "summary",
        }
        return {
            key: value
            for key, value in evidence.items()
            if key in allowed and value not in (None, "")
        }

    def _limitations(
        self,
        run: AuditRun,
        counts: ReportCounts,
        coverage: tuple[int, int, float, int],
    ) -> list[str]:
        limitations: list[str] = []
        if run.mode is AuditMode.QUICK:
            limitations.append(
                "This was a Quick Audit: files were identified and structurally checked, "
                "but checksums and full decoding were not performed."
            )
        verified, total, _percent, days = coverage
        if verified < total:
            limitations.append(
                f"{total - verified} files have not been deep-verified within the last {days} days."
            )
        missing_tools = [
            name for name, version in run.tool_versions.items() if version == "not installed"
        ]
        if missing_tools:
            limitations.append(
                "Checks requiring these tools were unavailable: "
                + ", ".join(sorted(missing_tools))
                + "."
            )
        if counts.tier3_identified_only:
            limitations.append(
                f"{counts.tier3_identified_only} files were identified but have no deep "
                "readability validator in this version."
            )
        if counts.protected:
            limitations.append(
                f"{counts.protected} protected or encrypted files were not validated internally."
            )
        limitations.extend(
            [
                "Compatibility-copy verification compares measurable characteristics only.",
                "No PDF/A or other standards conformance was validated.",
                (
                    f"This report describes what was checked on "
                    f"{run.started_at.strftime('%Y-%m-%d')}; it is not a guarantee of "
                    "future readability."
                ),
            ]
        )
        return limitations

    @staticmethod
    def _available_path(directory: Path, stem: str, suffix: str) -> Path:
        candidate = directory / f"{stem}.{suffix}"
        index = 2
        while candidate.exists():
            candidate = directory / f"{stem}-{index}.{suffix}"
            index += 1
        return candidate

    @staticmethod
    def _pdf_table(rows: list[list[object]], widths: tuple[float, ...] | None = None) -> Table:
        table = Table(rows, colWidths=widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E3ECFD")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1F2933")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9DEE5")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#FAFBFC")],
                    ),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return table

    def _pdf_summary(self, data: ReportData, styles: Any) -> list[Flowable]:
        rows: list[list[object]] = [
            ["Mode", data.mode_label],
            ["Started", data.run.started_at.strftime("%Y-%m-%d %H:%M")],
            ["Policy", data.policy_version],
            ["Signature", data.signature_version or "Unavailable"],
            ["Processed", f"{data.counts.files_processed:,}"],
            ["Failed", f"{data.counts.files_failed:,}"],
        ]
        return [
            Paragraph("Audit summary", styles["Heading2"]),
            self._pdf_table([["Field", "Value"], *rows], (45 * mm, 129 * mm)),
            Spacer(1, 8),
        ]

    @staticmethod
    def _pdf_footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#52606D"))
        canvas.drawString(16 * mm, 10 * mm, f"Generated by KeepReadable {__version__}")
        canvas.drawRightString(194 * mm, 10 * mm, f"Page {document.page}")
        canvas.restoreState()
