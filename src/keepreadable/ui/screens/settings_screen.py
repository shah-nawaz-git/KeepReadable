from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.container import AppContext
from keepreadable.config.settings import save_settings
from keepreadable.integrations.bootstrap import ToolBootstrapper
from keepreadable.integrations.tool_locator import ToolName
from keepreadable.integrations.tool_manifest import load_tool_manifest
from keepreadable.ui.workers.bootstrap_worker import BootstrapWorker


class SettingsScreen(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.bootstrap_worker: BootstrapWorker | None = None
        layout = QVBoxLayout(self)
        heading = QLabel("Settings")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        self.tools_group = QGroupBox("Tools")
        self.tools_form = QFormLayout(self.tools_group)
        layout.addWidget(self.tools_group)
        self.install_button = QPushButton("Install missing tools…")
        self.install_button.setAccessibleName("Install missing tools")
        self.install_button.clicked.connect(self._install_tools)
        layout.addWidget(self.install_button)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        verification = QGroupBox("Verification")
        form = QFormLayout(verification)
        self.interval = QSpinBox()
        self.interval.setRange(1, 3650)
        self.interval.setValue(context.settings.deep_verification_interval_days)
        self.workers = QSpinBox()
        self.workers.setRange(1, 64)
        self.workers.setValue(context.settings.worker_count)
        self.media_workers = QSpinBox()
        self.media_workers.setRange(1, 16)
        self.media_workers.setValue(context.settings.media_decode_workers)
        form.addRow("Deep verification interval (days)", self.interval)
        form.addRow("Worker count", self.workers)
        form.addRow("Media decode workers", self.media_workers)
        save = QPushButton("Save verification settings")
        save.setAccessibleName("Save verification settings")
        save.clicked.connect(self._save)
        form.addRow("", save)
        layout.addWidget(verification)
        locations = QGroupBox("Locations")
        location_form = QFormLayout(locations)
        database_path = Path(str(context.db.path))
        location_form.addRow("Database", QLabel(str(database_path)))
        location_form.addRow("Logs folder", self._folder_row(database_path.parent / "logs"))
        location_form.addRow("Tools folder", self._folder_row(context.tool_locator.tools_dir))
        layout.addWidget(locations)
        privacy = QGroupBox("Privacy")
        privacy_form = QFormLayout(privacy)
        for label, value in (
            ("Account required", "No"),
            ("Cloud upload", "No"),
            ("Remote processing", "No"),
            ("File contents transmitted", "No"),
            ("Telemetry", "No"),
        ):
            privacy_form.addRow(label, QLabel(value))
        layout.addWidget(privacy)
        layout.addStretch()
        self.refresh_tools()

    def refresh_tools(self) -> None:
        while self.tools_form.rowCount():
            self.tools_form.removeRow(0)
        inventory = self.context.tool_locator.inventory()
        unavailable: list[str] = []
        for name in ToolName:
            status = inventory[name]
            text = (
                f"Installed · {status.version or 'version unavailable'}"
                if status.installed
                else "Missing"
            )
            self.tools_form.addRow(name.value.title(), QLabel(text))
            if not status.installed:
                unavailable.append(name.value)
        self.tools_form.addRow("veraPDF", QLabel("Not configured (optional)"))
        if unavailable:
            self.tools_form.addRow(
                "Unavailable checks",
                QLabel(
                    "Format identification is limited without Siegfried. Media probing "
                    "and full media decoding are limited without FFmpeg and ffprobe."
                ),
            )
        self.install_button.setVisible(bool(unavailable))

    @staticmethod
    def _folder_row(path: Path) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(str(path)))
        button = QPushButton("Open folder")
        button.setAccessibleName(f"Open folder {path}")
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
        layout.addWidget(button)
        return widget

    def _save(self) -> None:
        updated = self.context.settings.model_copy(
            update={
                "deep_verification_interval_days": self.interval.value(),
                "worker_count": self.workers.value(),
                "media_decode_workers": self.media_workers.value(),
            }
        )
        database_path = Path(str(self.context.db.path))
        save_settings(updated, database_path.parent / "settings.json")
        QMessageBox.information(self, "Settings saved", "Verification settings were saved.")

    def _install_tools(self) -> None:
        manifest = load_tool_manifest()
        plan = ToolBootstrapper(manifest, self.context.tool_locator.tools_dir).plan()
        lines = [f"{item.tool} {item.version}\n{item.url}\nSHA-256: {item.sha256}" for item in plan]
        answer = QMessageBox.question(
            self,
            "Install missing tools?",
            "KeepReadable will download and verify these pinned archives:\n\n" + "\n\n".join(lines),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        bootstrapper = ToolBootstrapper(manifest, self.context.tool_locator.tools_dir)
        self.bootstrap_worker = BootstrapWorker(bootstrapper)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.bootstrap_worker.bootstrapFinished.connect(self._bootstrap_finished)
        self.bootstrap_worker.failed.connect(self._bootstrap_failed)
        self.bootstrap_worker.start()

    def _bootstrap_finished(self, _result: object) -> None:
        self.progress.setVisible(False)
        self.refresh_tools()

    def _bootstrap_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        QMessageBox.warning(self, "Tool installation", message)
