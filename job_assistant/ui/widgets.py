from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")


class StatCard(Card):
    def __init__(self, label: str, value: str = "0", hint: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(4)
        label_widget = QLabel(label.upper())
        label_widget.setObjectName("cardLabel")
        value_widget = QLabel(value)
        value_widget.setObjectName("cardValue")
        hint_widget = QLabel(hint)
        hint_widget.setObjectName("cardHint")
        layout.addWidget(label_widget)
        layout.addWidget(value_widget)
        layout.addWidget(hint_widget)
        self.value_widget = value_widget
        self.hint_widget = hint_widget


def page_header(title: str, subtitle: str) -> tuple[QLabel, QLabel]:
    title_label = QLabel(title)
    title_label.setObjectName("pageTitle")
    subtitle_label = QLabel(subtitle)
    subtitle_label.setObjectName("pageSubtitle")
    subtitle_label.setWordWrap(True)
    return title_label, subtitle_label


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def action_button(text: str, primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("primary" if primary else "secondary")
    button.setCursor(Qt.PointingHandCursor)
    return button
