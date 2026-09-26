from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from keepreadable.ui.theme import palette


class PillDelegate(QStyledItemDelegate):
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "Unknown")
        lowered = text.casefold()
        colour = palette.UNKNOWN
        if "healthy" in lowered or "passed" in lowered or "info" in lowered:
            colour = palette.HEALTHY
        elif "review" in lowered or "warning" in lowered or "medium" in lowered:
            colour = palette.REVIEW
        elif "unreadable" in lowered or "failed" in lowered or "high" in lowered:
            colour = palette.UNREADABLE
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor("#E3ECFD"))
        radius = 4.0
        centre_y = option.rect.center().y()
        painter.setBrush(QColor(colour))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(
            QRectF(option.rect.left() + 8, centre_y - radius, radius * 2, radius * 2)
        )
        painter.setPen(QColor(palette.TEXT))
        text_rect = option.rect.adjusted(24, 0, -6, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        size = super().sizeHint(option, index)
        size.setWidth(size.width() + 24)
        return size
