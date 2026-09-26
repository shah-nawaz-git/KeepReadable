from pathlib import Path

from PySide6.QtCore import QModelIndex, QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.archive_service import ArchiveService
from keepreadable.application.report_service import ReportService
from keepreadable.domain.audit import AuditRun
from keepreadable.ui.dialogs.error_dialog import ErrorDialog
from keepreadable.ui.formatting import format_duration, label_for
from keepreadable.ui.models.history_table_model import HistoryTableModel
from keepreadable.ui.table import configure_table
from keepreadable.ui.widgets.pill_delegate import PillDelegate
from keepreadable.ui.widgets.status_pill import StatusPill
from keepreadable.ui.workers.task_worker import TaskWorker


class HistoryScreen(QWidget):
    def __init__(
        self,
        service: ArchiveService,
        archive_id: int | None = None,
        report_service: ReportService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.archive_id = archive_id
        self.report_service = report_service
        self.selected_run: AuditRun | None = None
        self.report_worker: TaskWorker | None = None
        self.model = HistoryTableModel()
        heading = QLabel("History")
        heading.setProperty("heading", True)
        self.table = QTableView()
        self.table.setAccessibleName("Audit history")
        self.table.setModel(self.model)
        configure_table(self.table, stretch_columns=(0,))
        self.table.setItemDelegateForColumn(1, PillDelegate(self.table))
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_heading = QLabel("Run summary")
        detail_heading.setProperty("subheading", True)
        detail_layout.addWidget(detail_heading)
        self.status_pill = StatusPill()
        detail_layout.addWidget(self.status_pill)
        self.summary_form = QFormLayout()
        self.summary_labels: dict[str, QLabel] = {}
        for key, title in (
            ("mode", "Mode"),
            ("started", "Started"),
            ("finished", "Finished"),
            ("duration", "Duration"),
            ("discovered", "Discovered"),
            ("processed", "Processed"),
            ("failed", "Failed"),
            ("skipped", "Skipped"),
            ("findings", "Findings"),
            ("policy", "Policy version"),
            ("signature", "Signature identifiers"),
            ("interruption", "Interruption reason"),
        ):
            label = QLabel("—")
            label.setWordWrap(True)
            self.summary_labels[key] = label
            self.summary_form.addRow(title, label)
        detail_layout.addLayout(self.summary_form)
        tools_heading = QLabel("Tool versions")
        tools_heading.setStyleSheet("font-weight: 600")
        detail_layout.addWidget(tools_heading)
        self.tools_table = QTableWidget(0, 2)
        self.tools_table.setHorizontalHeaderLabels(("Tool", "Version"))
        self.tools_table.verticalHeader().setVisible(False)
        self.tools_table.horizontalHeader().setStretchLastSection(True)
        detail_layout.addWidget(self.tools_table)
        self.report_button = QPushButton("Generate report…")
        self.report_button.setEnabled(False)
        self.report_button.setAccessibleName("Generate audit report")
        self.report_button.clicked.connect(self._generate_report)
        detail_layout.addWidget(self.report_button)
        detail_layout.addStretch()
        splitter = QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(detail)
        splitter.setSizes([760, 360])
        layout = QVBoxLayout(self)
        if archive_id is None:
            layout.setContentsMargins(24, 24, 24, 24)
            layout.addWidget(heading)
        else:
            layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter, 1)
        self.refresh()

    def refresh(self) -> None:
        if self.archive_id is not None:
            runs = self.service.history(self.archive_id)
        else:
            runs = [
                run
                for archive in self.service.list_archives()
                for run in self.service.history(archive.id or 0)
            ]
            runs.sort(key=lambda run: run.started_at, reverse=True)
        self.model.set_runs(runs)
        if runs:
            self.table.selectRow(0)

    def _selected(self, current: QModelIndex, _previous: QModelIndex) -> None:
        run = self.model.run_at(current.row())
        if run is not None:
            self.show_run(run)

    def show_run(self, run: AuditRun) -> None:
        self.selected_run = run
        self.report_button.setEnabled(self.report_service is not None and run.id is not None)
        duration = (run.completed_at - run.started_at).total_seconds() if run.completed_at else None
        self.status_pill.set_status(label_for(run.status))
        values = {
            "mode": label_for(run.mode),
            "started": run.started_at.strftime("%Y-%m-%d %H:%M"),
            "finished": (run.completed_at.strftime("%Y-%m-%d %H:%M") if run.completed_at else "—"),
            "duration": format_duration(duration),
            "discovered": f"{run.files_discovered:,}",
            "processed": f"{run.files_processed:,}",
            "failed": f"{run.files_failed:,}",
            "skipped": f"{run.files_skipped:,}",
            "findings": f"{run.findings_count:,}",
            "policy": run.policy_version,
            "signature": run.signature_version or "Unavailable",
            "interruption": run.interruption_reason or "—",
        }
        for key, value in values.items():
            self.summary_labels[key].setText(value)
            self.summary_labels[key].show()
        tools = sorted(run.tool_versions.items())
        self.tools_table.setRowCount(len(tools))
        for row, (name, version) in enumerate(tools):
            self.tools_table.setItem(row, 0, QTableWidgetItem(name))
            self.tools_table.setItem(row, 1, QTableWidgetItem(version))
        self.tools_table.show()

    def _generate_report(self) -> None:
        if self.report_service is None or self.selected_run is None or self.selected_run.id is None:
            return
        documents = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose report folder",
            documents,
        )
        if not selected:
            return
        run_id = self.selected_run.id
        report_service = self.report_service
        assert report_service is not None
        self.report_button.setEnabled(False)
        self.report_worker = TaskWorker(lambda: report_service.generate(run_id, Path(selected)))
        self.report_worker.taskFinished.connect(self._report_finished)
        self.report_worker.failed.connect(self._report_failed)
        self.report_worker.start()

    def _report_finished(self, result: object) -> None:
        self.report_button.setEnabled(True)
        paths = [Path(path) for path in result] if isinstance(result, list) else []
        box = QMessageBox(self)
        box.setWindowTitle("Report created")
        box.setText("Report files were created:\n" + "\n".join(str(path) for path in paths))
        open_button = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_button and paths:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths[0].parent)))

    def _report_failed(self, message: str) -> None:
        self.report_button.setEnabled(True)
        ErrorDialog("The report could not be created.", message, parent=self).exec()
