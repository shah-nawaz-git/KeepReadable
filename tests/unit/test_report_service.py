from html.parser import HTMLParser
from pathlib import Path

import pikepdf
from pypdf import PdfReader

from keepreadable.application.container import AppContext
from keepreadable.config.settings import Settings
from keepreadable.domain.enums import (
    AuditMode,
    AuditStatus,
    FindingCategory,
    FindingSeverity,
)
from keepreadable.domain.finding import Finding
from keepreadable.persistence.repositories import FileRecordRepository, FindingRepository
from keepreadable.utilities.clock import utcnow
from tests.fixture_factory import make_jpeg, make_unknown_binary


class TagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)


def audited_context(tmp_path: Path) -> tuple[AppContext, int, int, int]:
    context = AppContext.create(
        tmp_path / "data",
        Settings(worker_count=2, persistence_batch_size=10, identification_batch_size=10),
    )
    root = tmp_path / "Family Archive"
    root.mkdir()
    make_jpeg(root / "ünicode & family.jpg")
    make_unknown_binary(root / "mystery")
    archive = context.archive_service.add_archive("Family Archive", root)
    assert archive.id is not None
    quick = context.audit_engine.start(archive.id, AuditMode.QUICK)
    deep = context.audit_engine.start(archive.id, AuditMode.DEEP)
    assert quick.status is AuditStatus.COMPLETED
    assert deep.status is AuditStatus.COMPLETED
    with context.db.session() as session:
        record = next(
            item
            for item in FileRecordRepository(session).list_present(archive.id, 0, 10)
            if item.relative_path == "ünicode & family.jpg"
        )
        FindingRepository(session).add_batch(
            [
                Finding(
                    file_record_id=record.id,
                    audit_run_id=deep.id or 0,
                    code="validation_warning",
                    severity=FindingSeverity.LOW,
                    category=FindingCategory.STRUCTURAL_WARNING,
                    title="<script>alert(1)</script>",
                    description=(
                        "A warning was observed.\n\nIt may need review.\n\n"
                        "The evidence is limited.\n\nReview the file."
                    ),
                    evidence={"summary": "Unicode evidence ü"},
                    created_at=utcnow(),
                    resolved_at=None,
                )
            ]
        )
    return context, archive.id, quick.id or 0, deep.id or 0


def test_report_data_html_pdf_and_conflict_names(tmp_path: Path) -> None:
    context, archive_id, quick_id, deep_id = audited_context(tmp_path)
    quick_data = context.report_service.build(quick_id)
    assert any("This was a Quick Audit" in item for item in quick_data.limitations)
    data = context.report_service.build(deep_id)
    overview = context.archive_service.overview(archive_id)
    assert data.archive_name == "Family Archive"
    assert data.counts.files_processed == overview.file_count
    assert data.policy_version
    assert data.signature_version
    assert data.tool_versions
    assert data.limitations
    assert any(finding.title == "<script>alert(1)</script>" for finding in data.findings)
    assert any(finding.relative_path == "ünicode & family.jpg" for finding in data.findings)

    html = context.report_service.render_html(data)
    collector = TagCollector()
    collector.feed(html)
    assert "script" not in collector.tags
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "ünicode &amp; family.jpg" in html
    assert data.mode_label in html
    assert data.policy_version in html
    assert data.signature_version in html

    pdf_path = tmp_path / "report.pdf"
    context.report_service.render_pdf(data, pdf_path)
    with pikepdf.open(pdf_path) as pdf:
        assert len(pdf.pages) >= 1
    text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf_path).pages)
    assert "Family Archive" in text
    assert "Limitations" in text

    forbidden = (
        "corrupt",
        "guaranteed",
        "permanently",
        "future-proof",
        "100% healthy",
        "archival master",
        "fully valid",
    )
    assert not any(word in html.casefold() for word in forbidden)
    assert not any(word in text.casefold() for word in forbidden)

    output = tmp_path / "reports"
    first = context.report_service.generate(deep_id, output)
    second = context.report_service.generate(deep_id, output)
    assert len(first) == 2
    assert len(second) == 2
    assert all(path.exists() for path in [*first, *second])
    assert all("-2." in path.name for path in second)
