from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from keepreadable.domain.enums import FindingSeverity, HealthState
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
        severity = next(
            (value for value in FindingSeverity if value.value == lowered),
            None,
        )
        health = next(
            (value for value in HealthState if value.value == lowered),
            None,
        )
        if severity is not None:
            colour = palette.severity_colour(severity)
        elif health is not None:
            colour = palette.health_colour(health)
        elif "passed" in lowered:
            colour = palette.HEALTHY
        elif "warning" in lowered or "protected" in lowered:
            colour = palette.REVIEW
        elif "failed" in lowered:
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
