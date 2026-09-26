from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.audit_service import AuditProgress
from keepreadable.ui.formatting import format_duration


class AuditProgressPanel(QFrame):
    pauseRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("surface")
        self.stage_label = QLabel("Preparing audit…")
        self.stage_label.setProperty("subheading", True)
        self.count_label = QLabel("0 of 0 files")
        self.path_label = QLabel("—")
        self.path_label.setProperty("muted", True)
        self.findings_label = QLabel("Findings so far: 0")
        self.time_label = QLabel("Elapsed: 0s · Estimated remaining: —")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.pause_button = QPushButton("Pause")
        self.pause_button.setAccessibleName("Pause audit")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setAccessibleName("Cancel audit")
        self.pause_button.clicked.connect(self._pause)
        self.cancel_button.clicked.connect(self._cancel)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.cancel_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(self.stage_label)
        layout.addWidget(self.count_label)
        layout.addWidget(self.path_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.findings_label)
        layout.addWidget(self.time_label)
        layout.addLayout(buttons)

    def update_progress(self, progress: AuditProgress) -> None:
        self.stage_label.setText(progress.stage.value.replace("_", " ").title())
        total = progress.files_total_estimate
        self.count_label.setText(f"{progress.files_processed:,} of {total:,} files")
        percent = int(progress.files_processed / total * 100) if total else 0
        self.progress_bar.setValue(min(100, percent))
        path = progress.current_path or "—"
        metrics = QFontMetrics(self.path_label.font())
        self.path_label.setText(
            metrics.elidedText(
                path,
                Qt.TextElideMode.ElideMiddle,
                max(200, self.path_label.width()),
            )
        )
        self.findings_label.setText(f"Findings so far: {progress.findings_count:,}")
        remaining = format_duration(progress.estimated_remaining_seconds)
        self.time_label.setText(
            f"Elapsed: {format_duration(progress.elapsed_seconds)} · "
            f"Estimated remaining: {remaining}"
        )

    def set_finished(self) -> None:
        self.pause_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

    def _pause(self) -> None:
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.pauseRequested.emit()

    def _cancel(self) -> None:
        answer = QMessageBox.question(
            self,
            "Cancel audit?",
            "Cancel this audit? Completed batches will remain recorded.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.pause_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self.cancelRequested.emit()
