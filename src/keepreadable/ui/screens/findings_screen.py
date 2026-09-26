from collections.abc import Iterable
from enum import StrEnum

from PySide6.QtCore import QModelIndex, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from keepreadable.application.archive_service import ArchiveService
from keepreadable.application.file_service import FileService
from keepreadable.application.findings_service import FindingDisplay, FindingsService
from keepreadable.domain.enums import FindingCategory, FindingSeverity, FindingState
from keepreadable.ui.models.findings_table_model import FindingsTableModel
from keepreadable.ui.widgets.empty_state import EmptyState


class FindingsView(QWidget):
    def __init__(
        self,
        findings_service: FindingsService,
        archive_service: ArchiveService,
        file_service: FileService,
        archive_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.findings_service = findings_service
        self.archive_service = archive_service
        self.file_service = file_service
        self.archive_id = archive_id
        self.current: FindingDisplay | None = None
        self.severity_filter = self._enum_combo("All severities", list(FindingSeverity))
        self.category_filter = self._enum_combo("All categories", list(FindingCategory))
        self.state_filter = self._enum_combo("All statuses", list(FindingState))
        self.archive_filter = QComboBox()
        self.archive_filter.addItem("All archives", None)
        for archive in archive_service.list_archives():
            self.archive_filter.addItem(archive.name, archive.id)
        if archive_id is not None:
            index = self.archive_filter.findData(archive_id)
            self.archive_filter.setCurrentIndex(max(0, index))
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
        self.model = FindingsTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Findings")
        self.table.setModel(self.model)
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        self.empty = EmptyState(
            "No findings",
            "Current findings that need review will appear here after an audit.",
        )
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addWidget(self.table)
        table_layout.addWidget(self.empty)
        self.detail_title = QLabel("Select a finding")
        self.detail_title.setProperty("subheading", True)
        self.detail_context = QLabel("")
        self.detail_context.setWordWrap(True)
        self.paragraphs = [QLabel("") for _ in range(4)]
        headings = (
            "What was observed",
            "Why it matters",
            "What KeepReadable knows",
            "What you can do",
        )
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_context)
        for heading, label in zip(headings, self.paragraphs, strict=True):
            title = QLabel(heading)
            title.setStyleSheet("font-weight: 600")
            label.setWordWrap(True)
            detail_layout.addWidget(title)
            detail_layout.addWidget(label)
        self.evidence_form = QFormLayout()
        detail_layout.addLayout(self.evidence_form)
        buttons = QHBoxLayout()
        for text, state in (
            ("Acknowledge", FindingState.ACKNOWLEDGED),
            ("Ignore", FindingState.IGNORED),
            ("Reopen", FindingState.OPEN),
        ):
            button = QPushButton(text)
            button.setAccessibleName(text)
            button.clicked.connect(lambda _checked=False, value=state: self._set_state(value))
            buttons.addWidget(button)
        self.open_button = QPushButton("Open file location")
        self.open_button.setAccessibleName("Open file location")
        self.open_button.clicked.connect(self._open_location)
        buttons.addWidget(self.open_button)
        detail_layout.addLayout(buttons)
        detail_layout.addStretch()
        splitter = QSplitter()
        splitter.addWidget(table_container)
        splitter.addWidget(detail)
        splitter.setSizes([650, 400])
        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addWidget(splitter)
        self.refresh()

    @staticmethod
    def _enum_combo(label: str, values: Iterable[StrEnum]) -> QComboBox:
        combo = QComboBox()
        combo.addItem(label, None)
        for value in values:
            combo.addItem(value.value.replace("_", " ").title(), value)
        return combo

    def refresh(self) -> None:
        archive_id = self.archive_id or self.archive_filter.currentData()
        severity_value = self.severity_filter.currentData()
        category_value = self.category_filter.currentData()
        state_value = self.state_filter.currentData()
        items = self.findings_service.list_findings(
            archive_id=archive_id,
            severity=(FindingSeverity(severity_value) if severity_value is not None else None),
            category=(FindingCategory(category_value) if category_value is not None else None),
            state=FindingState(state_value) if state_value is not None else None,
            limit=1000,
        )
        self.model.set_items(items)
        self.table.setVisible(bool(items))
        self.empty.setVisible(not items)
        self.table.resizeColumnsToContents()

    def _selected(self, current: QModelIndex, _previous: QModelIndex) -> None:
        row = current.row()
        item = self.model.item_at(row)
        if item is None:
            return
        self.current = item
        finding = item.finding
        self.detail_title.setText(finding.title)
        self.detail_context.setText(
            f"{finding.severity.value.title()} · {item.archive_name} · "
            f"{item.relative_path or 'Archive-level finding'}"
        )
        parts = finding.description.split("\n\n")
        for index, label in enumerate(self.paragraphs):
            label.setText(parts[index] if index < len(parts) else "—")
        while self.evidence_form.rowCount():
            self.evidence_form.removeRow(0)
        for key, value in finding.evidence.items():
            label = QLabel(str(value))
            label.setWordWrap(True)
            self.evidence_form.addRow(key.replace("_", " ").title(), label)
        self.open_button.setEnabled(item.relative_path is not None)

    def _set_state(self, state: FindingState) -> None:
        if self.current is None or self.current.finding.id is None:
            return
        self.file_service.set_finding_state(self.current.finding.id, state)
        self.refresh()

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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        heading = QLabel("Findings")
        heading.setProperty("heading", True)
        self.view = FindingsView(findings_service, archive_service, file_service)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(self.view)

    def refresh(self) -> None:
        self.view.refresh()
