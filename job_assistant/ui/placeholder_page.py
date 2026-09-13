from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from job_assistant.ui.widgets import Card, page_header, section_label


class PlaceholderPage(QWidget):
    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        title_label, subtitle = page_header(title, description)
        layout.addWidget(title_label)
        layout.addWidget(subtitle)
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.addWidget(section_label("Planned module"))
        body = QLabel("This workspace is included in the architecture and will be enabled in a later development phase. Your local data model is ready for it.")
        body.setWordWrap(True)
        body.setObjectName("muted")
        card_layout.addWidget(body)
        layout.addWidget(card)
        layout.addStretch()
