from contextlib import suppress

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.audit_service import AuditProgress
from keepreadable.application.container import AppContext
from keepreadable.domain.audit import AuditRun
from keepreadable.domain.enums import AuditMode, AuditStatus, HealthState
from keepreadable.ui.controller import AuditController
from keepreadable.ui.dialogs.file_detail_dialog import FileDetailDialog
from keepreadable.ui.formatting import format_bytes, pluralize, relative_time
from keepreadable.ui.models.files_table_model import FilesTableModel
from keepreadable.ui.screens.findings_screen import FindingsView
from keepreadable.ui.screens.history_screen import HistoryScreen
from keepreadable.ui.table import configure_table
from keepreadable.ui.theme import palette
from keepreadable.ui.widgets.audit_progress_panel import AuditProgressPanel
from keepreadable.ui.widgets.pill_delegate import PillDelegate
from keepreadable.ui.widgets.stat_tile import StatTile
from keepreadable.ui.widgets.status_pill import StatusPill


class ArchiveScreen(QWidget):
    removed = Signal()

    def __init__(
        self,
        context: AppContext,
        controller: AuditController,
        archive_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        self.controller = controller
        self.archive_id = archive_id
        archive = next(
            item for item in context.archive_service.list_archives() if item.id == archive_id
        )
        self.title = QLabel(archive.name)
        self.title.setProperty("heading", True)
        self.path = QLabel(archive.root_path)
        self.path.setProperty("muted", True)
        self.path.setWordWrap(True)
        self.availability = StatusPill("Available")
        quick = QPushButton("Quick Audit")
        quick.setAccessibleName("Run Quick Audit")
        quick.clicked.connect(lambda: controller.start(archive_id, AuditMode.QUICK))
        deep = QPushButton("Deep Audit")
        deep.setProperty("primary", True)
        deep.setAccessibleName("Run Deep Audit")
        deep.clicked.connect(lambda: controller.start(archive_id, AuditMode.DEEP))
        more = QPushButton("More")
        more.setAccessibleName("More archive actions")
        menu = QMenu(more)
        verify_all = menu.addAction("Deep verify all files")
        verify_all.triggered.connect(lambda: controller.start(archive_id, AuditMode.DEEP, True))
        remove = menu.addAction("Remove archive registration…")
        remove.triggered.connect(self._remove)
        more.setMenu(menu)
        actions = QHBoxLayout()
        actions.addWidget(quick)
        actions.addWidget(deep)
        actions.addWidget(more)
        header_text = QVBoxLayout()
        header_text.addWidget(self.title)
        header_text.addWidget(self.path)
        header_text.addWidget(self.availability)
        header = QHBoxLayout()
        header.addLayout(header_text)
        header.addStretch()
        header.addLayout(actions)
        self.progress_panel = AuditProgressPanel()
        self.progress_panel.setVisible(False)
        self.progress_panel.pauseRequested.connect(controller.pause)
        self.progress_panel.cancelRequested.connect(controller.cancel)
        controller.progress.connect(self._progress)
        controller.finished.connect(self._finished)
        self.tabs = QTabWidget()
        self.overview_tab = self._build_overview()
        self.files_tab = self._build_files()
        self.findings_view = FindingsView(
            context.findings_service,
            context.archive_service,
            context.file_service,
            archive_id,
            preservation_service=context.preservation_service,
        )
        self.history_view = HistoryScreen(context.archive_service, archive_id)
        self.tabs.addTab(self.overview_tab, "Overview")
        self.tabs.addTab(self.files_tab, "Files")
        self.tabs.addTab(self.findings_view, "Findings")
        self.tabs.addTab(self.history_view, "History")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addLayout(header)
        layout.addWidget(self.progress_panel)
        layout.addWidget(self.tabs)
        self.refresh()

    def _build_overview(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.file_tile = StatTile("Files")
        self.size_tile = StatTile("Total size")
        self.quick_tile = StatTile("Last Quick Audit")
        self.deep_tile = StatTile("Last Deep Audit")
        tiles = QGridLayout()
        for index, tile in enumerate(
            (self.file_tile, self.size_tile, self.quick_tile, self.deep_tile)
        ):
            tiles.addWidget(tile, 0, index)
        layout.addLayout(tiles)
        self.health_pills: dict[HealthState, StatusPill] = {}
        health_widget = QWidget()
        health_widget.setMaximumWidth(480)
        health_grid = QGridLayout(health_widget)
        for row, health in enumerate(HealthState):
            pill = StatusPill()
            pill.set_health(health)
            self.health_pills[health] = pill
            health_grid.addWidget(pill, row, 0)
            count = QLabel("0 files")
            count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            count.setObjectName(f"health-{health.value}")
            health_grid.addWidget(count, row, 1)
        health_grid.setColumnStretch(0, 1)
        layout.addWidget(health_widget)
        self.coverage_label = QLabel()
        self.coverage_label.setWordWrap(True)
        self.coverage_bar = QProgressBar()
        self.coverage_bar.setTextVisible(False)
        self.coverage_bar.setFixedHeight(8)
        self.coverage_percent = QLabel("0 %")
        coverage_row = QHBoxLayout()
        coverage_row.addWidget(self.coverage_bar, 1)
        coverage_row.addWidget(self.coverage_percent)
        self.coverage_note = QLabel("Files outside this window have not been re-verified recently")
        self.coverage_note.setProperty("muted", True)
        layout.addWidget(self.coverage_label)
        layout.addLayout(coverage_row)
        layout.addWidget(self.coverage_note)
        self.quick_note = QLabel(
            "Quick Audit checks identification and structure only; it is not a deep "
            "integrity verification."
        )
        self.quick_note.setWordWrap(True)
        layout.addWidget(self.quick_note)
        top_heading = QLabel("Top findings")
        top_heading.setProperty("subheading", True)
        layout.addWidget(top_heading)
        self.top_findings_widget = QWidget()
        self.top_findings_layout = QVBoxLayout(self.top_findings_widget)
        self.top_findings_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.top_findings_widget)
        layout.addStretch()
        return widget

    def _build_files(self) -> QWidget:
        widget = QWidget()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search paths")
        self.health_filter = QComboBox()
        self.health_filter.addItem("All health states", None)
        for health in HealthState:
            self.health_filter.addItem(health.value.title(), health)
        controls = QHBoxLayout()
        controls.addWidget(self.search)
        controls.addWidget(self.health_filter)
        self.files_model = FilesTableModel(self.context.file_service, self.archive_id)
        self.files_model.fetchMore()
        self.files_table = QTableView()
        self.files_table.setAccessibleName("Archive files")
        self.files_table.setModel(self.files_model)
        configure_table(self.files_table, stretch_columns=(0, 4))
        self.files_table.setItemDelegateForColumn(3, PillDelegate(self.files_table))
        self.files_table.doubleClicked.connect(self._open_file)
        self.files_table.activated.connect(self._open_file)
        self.search.textChanged.connect(self._filter_files)
        self.health_filter.currentIndexChanged.connect(self._filter_files)
        layout = QVBoxLayout(widget)
        layout.addLayout(controls)
        layout.addWidget(self.files_table)
        return widget

    def refresh(self) -> None:
        overview = self.context.archive_service.overview(self.archive_id)
        colours = {
            "available": palette.HEALTHY,
            "relocated": palette.REVIEW,
            "unavailable": palette.UNREADABLE,
        }
        availability_text = overview.availability.value.replace("_", " ").title()
        if overview.availability.value == "relocated":
            availability_text = f"Relocated to {overview.root}"
        elif overview.availability.value == "unavailable":
            availability_text = "Not connected"
        self.availability.set_status(availability_text, colours[overview.availability.value])
        self.file_tile.set_value(f"{overview.file_count:,}")
        self.size_tile.set_value(format_bytes(overview.total_bytes))
        self.quick_tile.set_value(
            relative_time(overview.last_quick_run.started_at)
            if overview.last_quick_run
            else "Never"
        )
        self.deep_tile.set_value(
            relative_time(overview.last_deep_run.started_at) if overview.last_deep_run else "Never"
        )
        for health, _pill in self.health_pills.items():
            label = self.overview_tab.findChild(QLabel, f"health-{health.value}")
            if label is not None:
                count = overview.health_counts.get(health, 0)
                label.setText(pluralize(count, "file"))
        self.coverage_label.setText(
            f"Deep verification coverage — {overview.coverage_percent:.0f} % of files "
            f"verified within the last {overview.interval_days} days"
        )
        self.coverage_bar.setValue(int(overview.coverage_percent))
        self.coverage_percent.setText(f"{overview.coverage_percent:.0f} %")
        latest = overview.last_deep_run or overview.last_quick_run
        self.quick_note.setVisible(latest is not None and latest.mode is AuditMode.QUICK)
        while self.top_findings_layout.count():
            item = self.top_findings_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        if not overview.top_findings:
            empty = QLabel("No current findings")
            empty.setProperty("muted", True)
            self.top_findings_layout.addWidget(empty)
            empty.show()
        for finding in overview.top_findings:
            row = QFrame()
            row.setProperty("surface", True)
            row_layout = QHBoxLayout(row)
            severity = StatusPill()
            severity.set_status(
                finding.severity.value.title(),
                palette.severity_colour(finding.severity),
            )
            text = QPushButton(finding.title)
            text.setFlat(True)
            text.setStyleSheet(
                "QPushButton { border: none; background: transparent; color: #1F2933; "
                "text-align: left; font-weight: 600; padding: 4px; }"
            )
            text.setAccessibleName(f"Open finding {finding.title}")
            text.clicked.connect(lambda _checked=False: self.tabs.setCurrentIndex(2))
            path = QLabel("Archive-level finding")
            if finding.file_record_id is not None:
                with suppress(ValueError):
                    path.setText(
                        self.context.file_service.file_detail(
                            finding.file_record_id
                        ).record.relative_path
                    )
            path.setProperty("muted", True)
            row_layout.addWidget(severity)
            row_layout.addWidget(text, 1)
            row_layout.addWidget(path)
            self.top_findings_layout.addWidget(row)
            row.show()
        self.files_model.set_filters(self._selected_health(), self.search.text())
        self.findings_view.refresh()
        self.history_view.refresh()

    def _selected_health(self) -> HealthState | None:
        value = self.health_filter.currentData()
        return HealthState(value) if value is not None else None

    def _filter_files(self) -> None:
        self.files_model.set_filters(self._selected_health(), self.search.text())

    def _open_file(self, index: QModelIndex) -> None:
        record = self.files_model.record_at(index.row())
        if record is not None and record.id is not None:
            FileDetailDialog(
                self.context.file_service.file_detail(record.id),
                self,
                preservation_service=self.context.preservation_service,
            ).exec()

    def _progress(self, progress: AuditProgress) -> None:
        if progress.run_id is None:
            return
        self.progress_panel.setVisible(True)
        self.progress_panel.update_progress(progress)

    def _finished(self, run: object) -> None:
        if isinstance(run, AuditRun) and run.archive_id == self.archive_id:
            self.progress_panel.set_finished()
            self.progress_panel.setVisible(False)
            self.refresh()
            if run.status is AuditStatus.FAILED:
                QMessageBox.warning(self, "Audit stopped", run.error_summary or "Audit failed")

    def _remove(self) -> None:
        answer = QMessageBox.question(
            self,
            "Remove archive registration?",
            "Remove this archive registration? Files on disk will not be changed.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.context.archive_service.remove_archive(self.archive_id)
            self.removed.emit()
