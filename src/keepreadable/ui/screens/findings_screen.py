from collections.abc import Iterable
from enum import StrEnum

from PySide6.QtCore import QModelIndex, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.archive_service import ArchiveService
from keepreadable.application.file_service import FileService
from keepreadable.application.findings_service import FindingDisplay, FindingsService
from keepreadable.application.preservation_service import PreservationService
from keepreadable.domain.enums import FindingCategory, FindingSeverity, FindingState
from keepreadable.ui.dialogs.file_detail_dialog import FileDetailDialog
from keepreadable.ui.models.findings_table_model import FindingsTableModel
from keepreadable.ui.table import configure_table
from keepreadable.ui.theme import palette
from keepreadable.ui.widgets.empty_state import EmptyState
from keepreadable.ui.widgets.pill_delegate import PillDelegate
from keepreadable.ui.widgets.status_pill import StatusPill


class FindingsView(QWidget):
    def __init__(
        self,
        findings_service: FindingsService,
        archive_service: ArchiveService,
        file_service: FileService,
        archive_id: int | None = None,
        preservation_service: PreservationService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.findings_service = findings_service
        self.archive_service = archive_service
        self.file_service = file_service
        self.archive_id = archive_id
        self.preservation_service = preservation_service
        self.current: FindingDisplay | None = None
        self.severity_filter = self._enum_combo("All severities", list(FindingSeverity))
        self.category_filter = self._enum_combo("All categories", list(FindingCategory))
        self.state_filter = self._enum_combo("All statuses", list(FindingState))
        self.archive_filter = QComboBox()
        self.archive_filter.addItem("All archives", None)
        for archive in archive_service.list_archives():
            self.archive_filter.addItem(archive.name, archive.id)
        if archive_id is not None:
            self.archive_filter.setCurrentIndex(max(0, self.archive_filter.findData(archive_id)))
            self.archive_filter.setEnabled(False)
        filters = QHBoxLayout()
        for combo in (
            self.severity_filter,
            self.category_filter,
            self.archive_filter,
            self.state_filter,
        ):
            combo.currentIndexChanged.connect(self.refresh)
            filters.addWidget(combo)
        filters.addStretch()
        self.model = FindingsTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Findings")
        self.table.setModel(self.model)
        configure_table(self.table, stretch_columns=(1, 3))
        self.table.setItemDelegateForColumn(0, PillDelegate(self.table))
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        self.table.doubleClicked.connect(self._open_file_detail)
        self.empty = EmptyState(
            "No findings",
            "Current findings that need review will appear here after an audit.",
        )
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addWidget(self.table, 1)
        table_layout.addWidget(self.empty)
        detail_content = QWidget()
        detail_layout = QVBoxLayout(detail_content)
        self.detail_title = QLabel("Select a finding")
        self.detail_title.setProperty("subheading", True)
        self.context_label = QLabel("")
        self.context_label.setProperty("muted", True)
        self.context_label.setWordWrap(True)
        pills = QHBoxLayout()
        self.severity_pill = StatusPill()
        self.status_pill = StatusPill()
        pills.addWidget(self.severity_pill)
        pills.addWidget(self.status_pill)
        pills.addStretch()
        detail_layout.addWidget(self.detail_title)
        detail_layout.addLayout(pills)
        detail_layout.addWidget(self.context_label)
        self.paragraphs = [QLabel("") for _ in range(4)]
        for heading, label in zip(
            (
                "What was observed",
                "Why it matters",
                "What KeepReadable knows",
                "What you can do",
            ),
            self.paragraphs,
            strict=True,
        ):
            title = QLabel(heading)
            title.setStyleSheet("font-weight: 600")
            label.setWordWrap(True)
            detail_layout.addWidget(title)
            detail_layout.addWidget(label)
        evidence_heading = QLabel("Evidence")
        evidence_heading.setStyleSheet("font-weight: 600")
        detail_layout.addWidget(evidence_heading)
        self.evidence_table = QTableWidget(0, 2)
        self.evidence_table.setHorizontalHeaderLabels(("Fact", "Value"))
        self.evidence_table.verticalHeader().setVisible(False)
        self.evidence_table.horizontalHeader().setStretchLastSection(True)
        detail_layout.addWidget(self.evidence_table)
        actions = QHBoxLayout()
        self.acknowledge_button = QPushButton("Acknowledge")
        self.ignore_button = QPushButton("Ignore")
        self.reopen_button = QPushButton("Reopen")
        for button, state in (
            (self.acknowledge_button, FindingState.ACKNOWLEDGED),
            (self.ignore_button, FindingState.IGNORED),
            (self.reopen_button, FindingState.OPEN),
        ):
            button.setAccessibleName(button.text())
            button.clicked.connect(lambda _checked=False, value=state: self._set_state(value))
            actions.addWidget(button)
        self.open_button = QPushButton("Open file location")
        self.open_button.setAccessibleName("Open file location")
        self.open_button.clicked.connect(self._open_location)
        actions.addWidget(self.open_button)
        actions.addStretch()
        detail_layout.addLayout(actions)
        detail_layout.addStretch()
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setWidget(detail_content)
        splitter = QSplitter()
        splitter.addWidget(table_container)
        splitter.addWidget(detail_scroll)
        splitter.setSizes([700, 440])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(filters)
        layout.addWidget(splitter, 1)
        self.refresh()

    @staticmethod
    def _enum_combo(label: str, values: Iterable[StrEnum]) -> QComboBox:
        combo = QComboBox()
        combo.addItem(label, None)
        for value in values:
            combo.addItem(value.value.replace("_", " ").title(), value)
        return combo

    def refresh(self) -> None:
        severity_value = self.severity_filter.currentData()
        category_value = self.category_filter.currentData()
        state_value = self.state_filter.currentData()
        items = self.findings_service.list_findings(
            archive_id=self.archive_id or self.archive_filter.currentData(),
            severity=(FindingSeverity(severity_value) if severity_value is not None else None),
            category=(FindingCategory(category_value) if category_value is not None else None),
            state=FindingState(state_value) if state_value is not None else None,
            limit=1000,
        )
        self.model.set_items(items)
        self.table.setVisible(bool(items))
        self.empty.setVisible(not items)
        if items:
            self.table.selectRow(0)

    def _selected(self, current: QModelIndex, _previous: QModelIndex) -> None:
        item = self.model.item_at(current.row())
        if item is None:
            return
        self.current = item
        finding = item.finding
        self.detail_title.setText(finding.title)
        self.severity_pill.set_status(
            finding.severity.value.title(),
            palette.severity_colour(finding.severity),
        )
        self.status_pill.set_status(finding.state.value.title(), palette.UNKNOWN)
        self.context_label.setText(
            f"{item.archive_name} \u203a {item.relative_path or 'Archive-level finding'}"
        )
        parts = finding.description.split("\n\n")
        for index, label in enumerate(self.paragraphs):
            label.setText(parts[index] if index < len(parts) else "—")
        evidence = [
            (key, value)
            for key, value in finding.evidence.items()
            if value not in (None, "", [], {})
        ]
        self.evidence_table.setRowCount(len(evidence))
        for row, (key, value) in enumerate(evidence):
            text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
            key_item = QTableWidgetItem(key.replace("_", " ").title())
            value_item = QTableWidgetItem(text if len(text) <= 180 else text[:177] + "…")
            value_item.setToolTip(text)
            self.evidence_table.setItem(row, 0, key_item)
            self.evidence_table.setItem(row, 1, value_item)
        self.evidence_table.resizeColumnsToContents()
        self.open_button.setEnabled(item.relative_path is not None)
        self.acknowledge_button.setEnabled(finding.state is not FindingState.ACKNOWLEDGED)
        self.ignore_button.setEnabled(finding.state is not FindingState.IGNORED)
        self.reopen_button.setEnabled(finding.state is not FindingState.OPEN)

    def _set_state(self, state: FindingState) -> None:
        if self.current is None or self.current.finding.id is None:
            return
        self.file_service.set_finding_state(self.current.finding.id, state)
        self.refresh()

    def _open_file_detail(self, index: QModelIndex) -> None:
        item = self.model.item_at(index.row())
        if item is not None and item.finding.file_record_id is not None:
            FileDetailDialog(
                self.file_service.file_detail(item.finding.file_record_id),
                self,
                preservation_service=self.preservation_service,
            ).exec()

    def _open_location(self) -> None:
        if self.current is None or self.current.finding.file_record_id is None:
            return
        detail = self.file_service.file_detail(self.current.finding.file_record_id)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(detail.absolute_path.parent)))


class FindingsScreen(QWidget):
    def __init__(
        self,
        findings_service: FindingsService,
        archive_service: ArchiveService,
        file_service: FileService,
        preservation_service: PreservationService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        heading = QLabel("Findings")
        heading.setProperty("heading", True)
        self.view = FindingsView(
            findings_service,
            archive_service,
            file_service,
            preservation_service=preservation_service,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(heading)
        layout.addWidget(self.view, 1)

    def refresh(self) -> None:
        self.view.refresh()
