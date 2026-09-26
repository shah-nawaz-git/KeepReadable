from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.preservation_service import (
    CopyProposal,
    CopyStage,
    PreservationService,
)
from keepreadable.domain.enums import VerificationStatus
from keepreadable.domain.preservation import GeneratedCopy
from keepreadable.ui.formatting import format_bytes, label_for
from keepreadable.ui.theme import palette
from keepreadable.ui.widgets.status_pill import StatusPill
from keepreadable.ui.workers.task_worker import TaskWorker
from keepreadable.utilities.cancellation import CancellationToken


class CopyDialog(QDialog):
    stageChanged = Signal(object)

    def __init__(
        self,
        service: PreservationService,
        proposal: CopyProposal,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.proposal = proposal
        self.token = CancellationToken()
        self.worker: TaskWorker | None = None
        self.setWindowTitle("Create compatibility copy")
        self.resize(720, 520)
        self.stack = QStackedWidget()
        self.confirmation_page = self._confirmation_page()
        self.running_page = self._running_page()
        self.result_page = self._result_page()
        self.stack.addWidget(self.confirmation_page)
        self.stack.addWidget(self.running_page)
        self.stack.addWidget(self.result_page)
        layout = QVBoxLayout(self)
        layout.addWidget(self.stack)
        self.stageChanged.connect(self._stage)

    def _confirmation_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        heading = QLabel("The original will not be changed.")
        heading.setProperty("subheading", True)
        layout.addWidget(heading)
        form = QFormLayout()
        form.addRow("Source format", QLabel(self.proposal.source_format))
        form.addRow("Proposed output", QLabel(self.proposal.output_format))
        purpose = QLabel(self.proposal.purpose)
        purpose.setWordWrap(True)
        form.addRow("Purpose", purpose)
        trade_offs = QLabel(self.proposal.trade_offs)
        trade_offs.setWordWrap(True)
        form.addRow("Known trade-offs", trade_offs)
        estimate = (
            format_bytes(self.proposal.estimated_output_bytes)
            if self.proposal.estimated_output_bytes is not None
            else "Unknown"
        )
        form.addRow("Estimated output size", QLabel(estimate))
        self.destination_label = QLabel(str(self.proposal.destination_dir))
        browse = QPushButton("Browse…")
        browse.setAccessibleName("Browse compatibility copy destination")
        browse.clicked.connect(self._browse)
        destination = QHBoxLayout()
        destination.addWidget(self.destination_label, 1)
        destination.addWidget(browse)
        form.addRow("Destination", destination)
        layout.addLayout(form)
        layout.addStretch()
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        create = QPushButton("Create compatibility copy")
        create.setProperty("primary", True)
        create.setAccessibleName("Create compatibility copy")
        create.clicked.connect(self._start)
        actions.addWidget(cancel)
        actions.addWidget(create)
        layout.addLayout(actions)
        return page

    def _running_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.stage_label = QLabel("Analyzing source…")
        self.stage_label.setProperty("subheading", True)
        self.running_progress = QProgressBar()
        self.running_progress.setRange(0, 0)
        cancel = QPushButton("Cancel")
        cancel.setAccessibleName("Cancel compatibility copy")
        cancel.clicked.connect(self.token.cancel)
        layout.addStretch()
        layout.addWidget(self.stage_label)
        layout.addWidget(self.running_progress)
        layout.addWidget(cancel)
        layout.addStretch()
        return page

    def _result_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.result_heading = QLabel("Copy created")
        self.result_heading.setProperty("heading", True)
        self.verification_pill = StatusPill()
        self.comparison_table = QTableWidget(0, 4)
        self.comparison_table.setHorizontalHeaderLabels(("Check", "Original", "Copy", "Result"))
        self.comparison_table.verticalHeader().setVisible(False)
        self.comparison_table.horizontalHeader().setStretchLastSection(True)
        self.output_label = QLabel()
        self.output_label.setWordWrap(True)
        limitation = QLabel(
            "Verification compared measurable characteristics; it does not establish "
            "visual or perceptual identity."
        )
        limitation.setWordWrap(True)
        limitation.setProperty("muted", True)
        open_folder = QPushButton("Open folder")
        open_folder.setAccessibleName("Open compatibility copy folder")
        open_folder.clicked.connect(self._open_folder)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addWidget(open_folder)
        actions.addStretch()
        actions.addWidget(close)
        layout.addWidget(self.result_heading)
        layout.addWidget(self.verification_pill)
        layout.addWidget(self.comparison_table)
        layout.addWidget(self.output_label)
        layout.addWidget(limitation)
        layout.addLayout(actions)
        return page

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Choose compatibility copy destination", str(self.proposal.destination_dir)
        )
        if selected:
            self.proposal = replace(self.proposal, destination_dir=Path(selected))
            self.destination_label.setText(selected)

    def _start(self) -> None:
        self.stack.setCurrentWidget(self.running_page)
        self.worker = TaskWorker(
            lambda: self.service.execute(
                self.proposal,
                cancel=self.token,
                on_stage=self.stageChanged.emit,
            )
        )
        self.worker.taskFinished.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _stage(self, stage: CopyStage) -> None:
        self.stage_label.setText(label_for(stage) + "…")

    def _finished(self, result: object) -> None:
        if not isinstance(result, GeneratedCopy):
            self._failed("The compatibility copy result was unavailable")
            return
        self.result_heading.setText(
            "Copy created"
            if result.verification_status in {VerificationStatus.PASSED, VerificationStatus.LIMITED}
            else "Copy not created"
        )
        colours = {
            VerificationStatus.PASSED: palette.HEALTHY,
            VerificationStatus.LIMITED: palette.REVIEW,
            VerificationStatus.FAILED: palette.UNREADABLE,
            VerificationStatus.NOT_RUN: palette.UNKNOWN,
        }
        self.verification_pill.set_status(
            label_for(result.verification_status), colours[result.verification_status]
        )
        comparisons = result.verification_details.get("comparisons", [])
        self.comparison_table.setRowCount(len(comparisons))
        for row, comparison in enumerate(comparisons):
            values = (
                comparison.get("name", ""),
                comparison.get("source", "—"),
                comparison.get("output", "—"),
                "Passed" if comparison.get("passed") else "Failed",
            )
            for column, value in enumerate(values):
                self.comparison_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.output_label.setText(result.output_path or "No output file was retained.")
        self.stack.setCurrentWidget(self.result_page)

    def _failed(self, message: str) -> None:
        self.result_heading.setText("Copy not created")
        self.verification_pill.set_status("Failed", palette.UNREADABLE)
        self.output_label.setText(message)
        self.stack.setCurrentWidget(self.result_page)

    def _open_folder(self) -> None:
        text = self.output_label.text()
        if text and Path(text).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(text).parent)))
