from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel

from keepreadable.application.container import AppContext
from keepreadable.config.settings import Settings
from keepreadable.domain.enums import AuditMode, AuditStatus, FindingCode, HealthState
from keepreadable.integrations.tool_locator import ToolLocator
from keepreadable.persistence.repositories import FindingRepository, ObservationRepository
from keepreadable.ui.main_window import MainWindow
from keepreadable.ui.screens.settings_screen import SettingsScreen
from tests.fixture_factory import make_jpeg, make_wav_stdlib

pytestmark = [pytest.mark.e2e, pytest.mark.ui]


def test_context_and_audits_with_all_external_tools_missing(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    locator = ToolLocator(
        tools_dir=tmp_path / "missing-data-tools",
        environ={},
        which=lambda _name: None,
        default_user_tools_dir=tmp_path / "missing-default-tools",
    )
    context = AppContext.create(
        tmp_path / "data",
        Settings(worker_count=2, persistence_batch_size=10, identification_batch_size=10),
        tool_locator=locator,
    )
    assert context.siegfried is None
    assert context.ffmpeg is None
    window = MainWindow(context)
    qtbot.addWidget(window)
    settings = window.settings_page
    assert isinstance(settings, SettingsScreen)
    visible_text = " ".join(widget.text() for widget in settings.findChildren(QLabel))
    assert visible_text.count("Missing") >= 2
    assert "Unavailable checks" in visible_text

    root = tmp_path / "archive"
    root.mkdir()
    make_jpeg(root / "image.jpg")
    make_wav_stdlib(root / "audio.wav")
    archive = context.archive_service.add_archive("Missing Tools", root)
    assert archive.id is not None
    quick = context.audit_engine.start(archive.id, AuditMode.QUICK)
    deep = context.audit_engine.start(archive.id, AuditMode.DEEP)
    assert quick.status is AuditStatus.COMPLETED
    assert deep.status is AuditStatus.COMPLETED
    records = {
        record.relative_path: record
        for record in context.file_service.list_files(archive.id, 0, 10)
    }
    assert records["image.jpg"].last_health is HealthState.UNKNOWN
    assert records["audio.wav"].last_health is HealthState.REVIEW
    image_observation = context.file_service.file_detail(
        records["image.jpg"].id or 0
    ).latest_observation
    assert image_observation is not None
    assert image_observation.structural_status.value == "passed"
    with context.db.session() as session:
        findings = FindingRepository(session).current_run_level_for_archive(archive.id)
        tools = [
            finding.evidence.get("tool")
            for finding in findings
            if finding.code == FindingCode.TOOL_UNAVAILABLE.value
            and finding.state.value in {"open", "acknowledged"}
        ]
        assert sorted(tools) == ["ffmpeg", "siegfried"]
        assert ObservationRepository(session).count_for_run(deep.id or 0) == 2
