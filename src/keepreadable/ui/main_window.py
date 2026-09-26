from PySide6.QtCore import QSettings
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from keepreadable.application.audit_service import AuditProgress
from keepreadable.application.container import AppContext
from keepreadable.domain.enums import AuditMode
from keepreadable.ui.controller import AuditController
from keepreadable.ui.dialogs.add_archive_dialog import AddArchiveDialog
from keepreadable.ui.dialogs.error_dialog import ErrorDialog
from keepreadable.ui.screens.archive_screen import ArchiveScreen
from keepreadable.ui.screens.archives_screen import ArchivesScreen
from keepreadable.ui.screens.findings_screen import FindingsScreen
from keepreadable.ui.screens.history_screen import HistoryScreen
from keepreadable.ui.screens.settings_screen import SettingsScreen
from keepreadable.ui.screens.welcome_screen import WelcomeScreen


class MainWindow(QMainWindow):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.controller = AuditController(context.audit_engine)
        self.controller.failed.connect(self._audit_failed)
        self.controller.progress.connect(self._status_progress)
        self.controller.finished.connect(lambda _run: self.statusBar().clearMessage())
        self.setWindowTitle("KeepReadable")
        self.setMinimumSize(1100, 720)
        self.settings = QSettings("KeepReadable", "KeepReadable")
        geometry = self.settings.value("mainWindowGeometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.sidebar = QListWidget()
        self.sidebar.setAccessibleName("Main navigation")
        self.sidebar.addItems(("Archives", "Findings", "History", "Settings"))
        self.sidebar.setFixedWidth(180)
        self.stack = QStackedWidget()
        self.archives_page: QWidget
        self._create_archives_page()
        self.findings_page = FindingsScreen(
            context.findings_service,
            context.archive_service,
            context.file_service,
        )
        self.history_page = HistoryScreen(context.archive_service)
        self.settings_page = SettingsScreen(context)
        self.stack.addWidget(self.findings_page)
        self.stack.addWidget(self.history_page)
        self.stack.addWidget(self.settings_page)
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack)
        self.setCentralWidget(container)
        self.sidebar.currentRowChanged.connect(self._navigate)
        self.sidebar.setCurrentRow(0)

    def _create_archives_page(self) -> None:
        page: QWidget
        if self.context.archive_service.list_archives():
            page = ArchivesScreen(self.context.archive_service)
            page.addArchiveRequested.connect(self.add_archive)
            page.archiveActivated.connect(self.open_archive)
        else:
            page = WelcomeScreen()
            page.addArchiveRequested.connect(self.add_archive)
        if hasattr(self, "archives_page"):
            index = self.stack.indexOf(self.archives_page)
            self.stack.removeWidget(self.archives_page)
            self.archives_page.deleteLater()
            self.stack.insertWidget(max(0, index), page)
        else:
            self.stack.addWidget(page)
        self.archives_page = page

    def _navigate(self, row: int) -> None:
        if row == 0:
            self._create_archives_page()
            self.stack.setCurrentWidget(self.archives_page)
        elif row == 1:
            self.findings_page.refresh()
            self.stack.setCurrentWidget(self.findings_page)
        elif row == 2:
            self.history_page.refresh()
            self.stack.setCurrentWidget(self.history_page)
        elif row == 3:
            self.settings_page.refresh_tools()
            self.stack.setCurrentWidget(self.settings_page)

    def add_archive(self) -> None:
        dialog = AddArchiveDialog(self.context.archive_service, self)
        if dialog.exec() != AddArchiveDialog.DialogCode.Accepted:
            return
        try:
            archive = self.context.archive_service.add_archive(dialog.archive_name, dialog.root)
        except ValueError as exc:
            ErrorDialog("The archive could not be added.", str(exc), parent=self).exec()
            return
        self._create_archives_page()
        answer = QMessageBox.question(
            self,
            "Run a Quick Audit now?",
            "The archive was added. Run a Quick Audit now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes and archive.id is not None:
            self.open_archive(archive.id)
            self.controller.start(archive.id, AuditMode.QUICK)

    def open_archive(self, archive_id: int) -> None:
        screen = ArchiveScreen(self.context, self.controller, archive_id)
        screen.removed.connect(self._archive_removed)
        self.stack.addWidget(screen)
        self.stack.setCurrentWidget(screen)

    def _archive_removed(self) -> None:
        self.sidebar.setCurrentRow(0)
        self._create_archives_page()

    def _status_progress(self, progress: AuditProgress) -> None:
        self.statusBar().showMessage(
            f"{progress.stage.value.title()} Audit running — "
            f"{progress.files_processed:,} / {progress.files_total_estimate:,} files"
        )

    def _audit_failed(self, message: str) -> None:
        if "archive root is unavailable" in message.casefold():
            ErrorDialog(
                "This archive is not connected.",
                "Reconnect the drive or folder and try again.",
                parent=self,
            ).exec()
        else:
            ErrorDialog("The audit could not continue.", message, parent=self).exec()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller.is_running:
            answer = QMessageBox.question(
                self,
                "Pause audit and close?",
                "Pause the audit and close KeepReadable?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.controller.pause()
            if not self.controller.wait(30_000):
                event.ignore()
                return
        self.settings.setValue("mainWindowGeometry", self.saveGeometry())
        event.accept()
