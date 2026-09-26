from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.archive_service import ArchiveService
from keepreadable.domain.audit import AuditRun
from keepreadable.ui.formatting import format_duration, label_for
from keepreadable.ui.models.history_table_model import HistoryTableModel
from keepreadable.ui.table import configure_table
from keepreadable.ui.widgets.pill_delegate import PillDelegate
from keepreadable.ui.widgets.status_pill import StatusPill


class HistoryScreen(QWidget):
    def __init__(
        self,
        service: ArchiveService,
        archive_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.archive_id = archive_id
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
        report = QPushButton("Report")
        report.setEnabled(False)
        report.setToolTip("Available in a later step")
        report.setAccessibleName("Report available in a later step")
        detail_layout.addWidget(report)
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
        tools = sorted(run.tool_versions.items())
        self.tools_table.setRowCount(len(tools))
        for row, (name, version) in enumerate(tools):
            self.tools_table.setItem(row, 0, QTableWidgetItem(name))
            self.tools_table.setItem(row, 1, QTableWidgetItem(version))
