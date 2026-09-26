from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from keepreadable.application.file_service import FileService
from keepreadable.domain.enums import HealthState
from keepreadable.domain.file_record import FileRecord
from keepreadable.ui.formatting import format_bytes, label_for

_INVALID_INDEX = QModelIndex()


class FilesTableModel(QAbstractTableModel):
    headers = ("Path", "Size", "Modified", "Health", "Format")

    def __init__(self, service: FileService, archive_id: int, page_size: int = 200) -> None:
        super().__init__()
        self.service = service
        self.archive_id = archive_id
        self.page_size = page_size
        self.records: list[FileRecord] = []
        self.health: HealthState | None = None
        self.search: str | None = None
        self.exhausted = False

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX) -> int:
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        record = self.records[index.row()]
        values = (
            record.relative_path,
            format_bytes(record.size),
            datetime.fromtimestamp(record.mtime_ns / 1_000_000_000).strftime("%Y-%m-%d %H:%M"),
            label_for(record.last_health) if record.last_health else "Unknown",
            record.last_format
            or (
                record.relative_path.rsplit(".", 1)[-1].upper()
                if "." in record.relative_path
                else "—"
            ),
        )
        return values[index.column()]

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def canFetchMore(self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX) -> bool:
        return not parent.isValid() and not self.exhausted

    def fetchMore(self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX) -> None:
        if parent.isValid() or self.exhausted:
            return
        batch = self.service.list_files(
            self.archive_id,
            len(self.records),
            self.page_size,
            health=self.health,
            search=self.search,
        )
        if not batch:
            self.exhausted = True
            return
        first = len(self.records)
        self.beginInsertRows(_INVALID_INDEX, first, first + len(batch) - 1)
        self.records.extend(batch)
        self.endInsertRows()
        if len(batch) < self.page_size:
            self.exhausted = True

    def set_filters(self, health: HealthState | None, search: str | None) -> None:
        self.beginResetModel()
        self.health = health
        self.search = search or None
        self.records.clear()
        self.exhausted = False
        self.endResetModel()
        self.fetchMore()

    def record_at(self, row: int) -> FileRecord | None:
        return self.records[row] if 0 <= row < len(self.records) else None
