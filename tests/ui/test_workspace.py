from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QPushButton

from keepreadable.application.audit_service import AuditProgress, AuditStage
from keepreadable.application.container import AppContext
from keepreadable.config.settings import Settings
from keepreadable.domain.enums import AuditMode, AuditStatus, FindingState
from keepreadable.integrations.tool_locator import ToolName, ToolStatus
from keepreadable.ui.controller import AuditController
from keepreadable.ui.dialogs.add_archive_dialog import AddArchiveDialog
from keepreadable.ui.dialogs.error_dialog import ErrorDialog
from keepreadable.ui.dialogs.file_detail_dialog import FileDetailDialog
from keepreadable.ui.dialogs.resume_dialog import ResumeChoice, ResumeDialog
from keepreadable.ui.main_window import MainWindow
from keepreadable.ui.screens.archive_screen import ArchiveScreen
from keepreadable.ui.screens.archives_screen import ArchivesScreen
from keepreadable.ui.screens.findings_screen import FindingsScreen
from keepreadable.ui.screens.history_screen import HistoryScreen
from keepreadable.ui.screens.settings_screen import SettingsScreen
from keepreadable.ui.screens.welcome_screen import WelcomeScreen
from keepreadable.ui.widgets.archive_row import ArchiveRow
from keepreadable.ui.widgets.audit_progress_panel import AuditProgressPanel
from keepreadable.ui.widgets.status_pill import StatusPill
from tests.fixture_factory import make_jpeg, truncate_file

pytestmark = pytest.mark.ui


def context(tmp_path: Path) -> AppContext:
    return AppContext.create(
        tmp_path / "data",
        Settings(
            worker_count=2,
            persistence_batch_size=10,
            identification_batch_size=10,
        ),
    )


def test_first_launch_shows_welcome(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = MainWindow(context(tmp_path))
    qtbot.addWidget(window)
    window.show()
    assert isinstance(window.archives_page, WelcomeScreen)
    assert window.findChild(QPushButton, "") is not None


def test_add_archive_dialog_browse_and_archive_appears(
    qtbot: pytest.QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_context = context(tmp_path)
    root = tmp_path / "archive"
    root.mkdir()
    make_jpeg(root / "image.jpg")
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(root),
    )
    dialog = AddArchiveDialog(app_context.archive_service)
    qtbot.addWidget(dialog)
    dialog._browse()
    qtbot.waitUntil(lambda: "checking" not in dialog.estimate_label.text(), timeout=5000)
    assert dialog.name_edit.text() == "archive"
    archive = app_context.archive_service.add_archive(dialog.archive_name, dialog.root)
    assert archive in app_context.archive_service.list_archives()


def test_archive_rows_render_health_pills(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app_context = context(tmp_path)
    root = tmp_path / "archive"
    root.mkdir()
    make_jpeg(root / "image.jpg")
    archive = app_context.archive_service.add_archive("Photos", root)
    assert archive.id is not None
    app_context.audit_engine.start(archive.id, AuditMode.QUICK)
    screen = ArchivesScreen(app_context.archive_service)
    qtbot.addWidget(screen)
    screen.show()
    rows = screen.findChildren(ArchiveRow)
    assert len(rows) == 1
    assert rows[0].findChildren(StatusPill)


def test_archive_overview_and_quick_deep_workers(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app_context = context(tmp_path)
    root = tmp_path / "archive"
    root.mkdir()
    make_jpeg(root / "image.jpg")
    archive = app_context.archive_service.add_archive("Photos", root)
    assert archive.id is not None
    controller = AuditController(app_context.audit_engine)
    screen = ArchiveScreen(app_context, controller, archive.id)
    qtbot.addWidget(screen)
    screen.show()
    with qtbot.waitSignal(controller.finished, timeout=60_000) as quick_signal:
        assert controller.start(archive.id, AuditMode.QUICK)
    assert quick_signal.args[0].status is AuditStatus.COMPLETED
    screen.refresh()
    assert screen.file_tile.value_label.text() == "1"
    assert screen.files_model.records[0].last_format is not None
    assert "JPEG" in str(screen.files_model.data(screen.files_model.index(0, 4)))
    with qtbot.waitSignal(controller.finished, timeout=60_000) as deep_signal:
        assert controller.start(archive.id, AuditMode.DEEP)
    assert deep_signal.args[0].status is AuditStatus.COMPLETED


def test_progress_panel_and_cancel_confirmation(
    qtbot: pytest.QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = AuditProgressPanel()
    qtbot.addWidget(panel)
    panel.show()
    progress = AuditProgress(
        run_id=1,
        stage=AuditStage.PROCESSING,
        files_discovered=100,
        files_total_estimate=100,
        files_processed=42,
        files_failed=0,
        files_skipped=0,
        findings_count=3,
        current_path="a/very/long/path/to/a/file.jpg",
        elapsed_seconds=12,
        bytes_hashed=1000,
        estimated_remaining_seconds=None,
    )
    panel.update_progress(progress)
    assert panel.count_label.text() == "42 of 100 files"
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    with qtbot.waitSignal(panel.cancelRequested):
        qtbot.mouseClick(panel.cancel_button, Qt.MouseButton.LeftButton)
    assert not panel.cancel_button.isEnabled()


def test_file_detail_resume_and_error_dialog_behaviour(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app_context = context(tmp_path)
    root = tmp_path / "archive"
    root.mkdir()
    make_jpeg(root / "image.jpg")
    archive = app_context.archive_service.add_archive("Photos", root)
    assert archive.id is not None
    assert (
        app_context.audit_engine.start(archive.id, AuditMode.QUICK).status is AuditStatus.COMPLETED
    )
    record = app_context.file_service.list_files(archive.id, 0, 10)[0]
    detail = FileDetailDialog(app_context.file_service.file_detail(record.id or 0))
    qtbot.addWidget(detail)
    detail.show()
    assert "image.jpg" in detail.windowTitle()
    assert detail.actions_layout.count() >= 2
    labels = [label.text() for label in detail.findChildren(QLabel)]
    assert "Passed" in labels
    assert "Not checked" in labels
    assert any(text.startswith("• ") for text in labels)

    history = HistoryScreen(app_context.archive_service, archive.id)
    qtbot.addWidget(history)
    history.show()
    assert history.summary_labels["mode"].text() == "Quick"
    assert history.summary_labels["processed"].text() == "1"

    resume = ResumeDialog(1)
    qtbot.addWidget(resume)
    resume.show()
    resume_button = next(
        button for button in resume.findChildren(QPushButton) if button.text() == "Resume"
    )
    qtbot.mouseClick(resume_button, Qt.MouseButton.LeftButton)
    assert resume.choice is ResumeChoice.RESUME

    error = ErrorDialog("Could not continue", "Test reason", "technical details")
    qtbot.addWidget(error)
    error.show()
    assert not error.details.isVisible()
    qtbot.mouseClick(error.toggle, Qt.MouseButton.LeftButton)
    assert error.details.isVisible()


def test_findings_filter_detail_and_acknowledge(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app_context = context(tmp_path)
    root = tmp_path / "archive"
    root.mkdir()
    truncate_file(make_jpeg(root / "truncated.jpg"), 0.6)
    archive = app_context.archive_service.add_archive("Review", root)
    assert archive.id is not None
    app_context.audit_engine.start(archive.id, AuditMode.QUICK)
    screen = FindingsScreen(
        app_context.findings_service,
        app_context.archive_service,
        app_context.file_service,
    )
    qtbot.addWidget(screen)
    screen.show()
    severity = screen.view.model.items[0].finding.severity
    screen.view.severity_filter.setCurrentIndex(screen.view.severity_filter.findData(severity))
    assert screen.view.model.rowCount() >= 1
    screen.view.table.selectRow(0)
    qtbot.waitUntil(lambda: screen.view.current is not None)
    assert all(label.text() for label in screen.view.paragraphs)
    acknowledge = next(
        button for button in screen.findChildren(QPushButton) if button.text() == "Acknowledge"
    )
    qtbot.mouseClick(acknowledge, Qt.MouseButton.LeftButton)
    assert screen.view.model.items[0].finding.state is FindingState.ACKNOWLEDGED
    assert not screen.view.acknowledge_button.isEnabled()
    assert screen.view.reopen_button.isEnabled()


def test_settings_plainly_reports_missing_tools(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    app_context = context(tmp_path)

    class FakeLocator:
        tools_dir = tmp_path / "tools"

        @staticmethod
        def inventory() -> dict[ToolName, ToolStatus]:
            return {
                ToolName.SIEGFRIED: ToolStatus(
                    ToolName.SIEGFRIED, False, None, None, "not found", None
                ),
                ToolName.FFMPEG: ToolStatus(
                    ToolName.FFMPEG, True, Path("ffmpeg.exe"), "8.1.2", None, "path"
                ),
                ToolName.FFPROBE: ToolStatus(
                    ToolName.FFPROBE, True, Path("ffprobe.exe"), "8.1.2", None, "path"
                ),
            }

    fake_context = replace(app_context, tool_locator=FakeLocator())
    screen = SettingsScreen(fake_context)
    qtbot.addWidget(screen)
    screen.show()
    labels = [label.text() for label in screen.findChildren(QLabel)]
    assert screen.install_button.isVisible()
    assert "Missing" in labels
    assert any("Unavailable checks" in text for text in labels)


def test_progress_burst_keeps_cancel_action_responsive(
    qtbot: pytest.QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = AuditProgressPanel()
    qtbot.addWidget(panel)
    panel.show()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    progress = AuditProgress(
        run_id=1,
        stage=AuditStage.PROCESSING,
        files_discovered=10_000,
        files_total_estimate=10_000,
        files_processed=0,
        files_failed=0,
        files_skipped=0,
        findings_count=0,
        current_path="file.txt",
        elapsed_seconds=1,
        bytes_hashed=0,
        estimated_remaining_seconds=None,
    )

    def burst() -> None:
        for index in range(10_000):
            panel.update_progress(replace(progress, files_processed=index))
            if index == 100:
                panel.cancel_button.click()

    started = time.monotonic()
    QTimer.singleShot(0, burst)
    with qtbot.waitSignal(panel.cancelRequested, timeout=2_000):
        pass
    assert time.monotonic() - started < 2
    panel.close()
