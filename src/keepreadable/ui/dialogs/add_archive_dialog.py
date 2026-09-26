from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.archive_service import ArchiveService
from keepreadable.ui.workers.task_worker import TaskWorker


class AddArchiveDialog(QDialog):
    def __init__(self, service: ArchiveService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.worker: TaskWorker | None = None
        self.setWindowTitle("Add an Archive")
        self.resize(560, 260)
        self.location_edit = QLineEdit()
        self.name_edit = QLineEdit()
        self.availability_label = QLabel("Choose a folder")
        self.estimate_label = QLabel("Estimated files: —")
        self.validation_label = QLabel("")
        self.validation_label.setStyleSheet("color: #C53030")
        browse = QPushButton("Browse…")
        browse.setAccessibleName("Browse for archive folder")
        browse.clicked.connect(self._browse)
        location_row = QHBoxLayout()
        location_row.addWidget(self.location_edit)
        location_row.addWidget(browse)
        form = QFormLayout()
        form.addRow("Location", location_row)
        form.addRow("Name", self.name_edit)
        form.addRow("Drive availability", self.availability_label)
        form.addRow("", self.estimate_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Add Archive")
        ok.setAccessibleName("Add Archive")
        self.buttons.accepted.connect(self._validate)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.validation_label)
        layout.addWidget(self.buttons)
        self.setTabOrder(self.location_edit, browse)
        self.setTabOrder(browse, self.name_edit)
        QTimer.singleShot(0, self.location_edit.setFocus)

    @property
    def root(self) -> Path:
        return Path(self.location_edit.text())

    @property
    def archive_name(self) -> str:
        return self.name_edit.text().strip()

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose archive folder")
        if not selected:
            return
        path = Path(selected)
        self.location_edit.setText(str(path))
        if not self.name_edit.text().strip():
            self.name_edit.setText(path.name)
        self.availability_label.setText("Available" if path.is_dir() else "Not available")
        self.estimate_label.setText("Estimated files: checking…")
        self.worker = TaskWorker(lambda: self.service.estimate_file_count(path))
        self.worker.taskFinished.connect(
            lambda value: self.estimate_label.setText(f"Estimated files: {int(value):,}")
        )
        self.worker.failed.connect(
            lambda _message: self.estimate_label.setText("Estimated files: unavailable")
        )
        self.worker.start()

    def _validate(self) -> None:
        if not self.root.is_dir():
            self.validation_label.setText("Choose an available folder.")
            return
        if not self.archive_name:
            self.validation_label.setText("Enter a name for this archive.")
            return
        self.accept()
