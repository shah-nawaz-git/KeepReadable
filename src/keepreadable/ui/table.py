from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableView


def configure_table(table: QTableView, stretch_columns: Iterable[int] = ()) -> None:
    stretch = set(stretch_columns)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
    table.verticalHeader().setDefaultSectionSize(table.fontMetrics().height() + 12)
    header = table.horizontalHeader()
    header.setStretchLastSection(not stretch)
    for column in range(table.model().columnCount() if table.model() else 0):
        mode = (
            QHeaderView.ResizeMode.Stretch
            if column in stretch
            else QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(column, mode)
