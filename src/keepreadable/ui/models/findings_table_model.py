from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from keepreadable.application.findings_service import FindingDisplay

_INVALID_INDEX = QModelIndex()


class FindingsTableModel(QAbstractTableModel):
    headers = ("Severity", "Finding", "Archive", "Path", "Status")

    def __init__(self) -> None:
        super().__init__()
        self.items: list[FindingDisplay] = []

    def set_items(self, items: list[FindingDisplay]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX) -> int:
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _INVALID_INDEX) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        item = self.items[index.row()]
        finding = item.finding
        return (
            finding.severity.value.title(),
            finding.title,
            item.archive_name,
            item.relative_path or "—",
            finding.state.value.title(),
        )[index.column()]

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def item_at(self, row: int) -> FindingDisplay | None:
        return self.items[row] if 0 <= row < len(self.items) else None
