from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from job_assistant.database.repository import Repository
from job_assistant.ui.widgets import Card, StatCard, action_button, page_header, section_label


class DashboardPage(QWidget):
    navigate = Signal(str)
    search_now = Signal()

    def __init__(self, repository: Repository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.stat_cards: dict[str, StatCard] = {}
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(20)
        title, subtitle = page_header("Good morning", "Your private workspace for focused, high-quality job applications.")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        stats = QGridLayout()
        stats.setHorizontalSpacing(12)
        stats.setVerticalSpacing(12)
        definitions = [
            ("jobs_found", "Jobs found today", "New opportunities"),
            ("excellent", "Excellent matches", "90% and above"),
            ("strong", "Strong matches", "80–89% fit"),
            ("prepared", "Applications ready", "Waiting for review"),
            ("submitted", "Applications submitted", "Tracked locally"),
            ("interviews", "Interviews", "Upcoming & completed"),
            ("offers", "Offers", "Keep the momentum"),
            ("rejected", "Rejected", "Learn from outcomes"),
        ]
        for index, (key, label, hint) in enumerate(definitions):
            card = StatCard(label, "0", hint)
            self.stat_cards[key] = card
            stats.addWidget(card, index // 4, index % 4)
        layout.addLayout(stats)

        action_card = Card()
        action_layout = QHBoxLayout(action_card)
        action_layout.setContentsMargins(20, 18, 20, 18)
        copy = QVBoxLayout()
        copy.addWidget(section_label("Build your candidate foundation"))
        message = QLabel("Upload your Master CV and set search preferences before connecting job sources.")
        message.setObjectName("muted")
        message.setWordWrap(True)
        copy.addWidget(message)
        action_layout.addLayout(copy, 1)
        upload = action_button("Upload Master CV", True)
        upload.clicked.connect(lambda: self.navigate.emit("profile"))
        configure = action_button("Configure search")
        configure.clicked.connect(lambda: self.navigate.emit("search"))
        search = action_button("Search jobs now")
        search.clicked.connect(self.search_now)
        action_layout.addWidget(upload)
        action_layout.addWidget(configure)
        action_layout.addWidget(search)
        layout.addWidget(action_card)

        activity = Card()
        activity_layout = QVBoxLayout(activity)
        activity_layout.setContentsMargins(20, 18, 20, 18)
        activity_layout.addWidget(section_label("Quality-first workflow"))
        for number, text in (("01", "Keep one factual Master CV — generated CVs will always be separate."),
                             ("02", "Review match explanations and missing mandatory requirements before applying."),
                             ("03", "Applications are never submitted automatically by this first phase.")):
            row = QHBoxLayout()
            n = QLabel(number)
            n.setObjectName("cardHint")
            n.setFixedWidth(32)
            detail = QLabel(text)
            detail.setObjectName("muted")
            row.addWidget(n)
            row.addWidget(detail)
            activity_layout.addLayout(row)
        layout.addWidget(activity)
        layout.addStretch()

    def refresh(self) -> None:
        counts = self.repository.dashboard_counts()
        for key, card in self.stat_cards.items():
            card.value_widget.setText(str(counts.get(key, 0)))
