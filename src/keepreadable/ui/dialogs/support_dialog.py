from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from keepreadable.validators.registry import SUPPORT_MATRIX


class SupportDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("What KeepReadable checks")
        self.resize(620, 480)
        layout = QVBoxLayout(self)
        heading = QLabel("What KeepReadable checks")
        heading.setProperty("heading", True)
        layout.addWidget(heading)
        intro = QLabel(
            "Deep support reads structure and content with a format-aware validator. "
            "Structural support checks package structure. Identify-only support records "
            "the detected format without a deep readability check."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        families: dict[str, list[str]] = {}
        for support in SUPPORT_MATRIX:
            families.setdefault(support.tier.value, []).append(support.family)
        for tier, names in families.items():
            label = QLabel(f"{tier.replace('_', ' ').title()}: {', '.join(names)}")
            label.setWordWrap(True)
            layout.addWidget(label)
        tier_three = QLabel(
            "Other identified formats use Tier 3 identify-only support. This does not "
            "make a readability claim about those files."
        )
        tier_three.setWordWrap(True)
        layout.addWidget(tier_three)
        layout.addStretch()
        close = QPushButton("Close")
        close.setAccessibleName("Close support information")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
