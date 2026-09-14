from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from job_assistant.database.repository import Repository
from job_assistant.ui.widgets import Card, StatCard, action_button, page_header, section_label


class DashboardPage(QWidget):
    """Career command center: live local counts plus next-step readiness."""

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
        layout.setSpacing(16)
        title, subtitle = page_header("Job Search Dashboard", "Track opportunities, application preparation, and interview progress from one private workspace.")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        brief = Card()
        brief_layout = QVBoxLayout(brief)
        brief_layout.setContentsMargins(18, 13, 18, 13)
        brief_layout.setSpacing(4)
        brief_layout.addWidget(section_label("TODAY'S OPPORTUNITY BRIEF"))
        self.brief_label = QLabel("")
        self.brief_label.setObjectName("muted")
        self.brief_label.setWordWrap(True)
        brief_layout.addWidget(self.brief_label)
        layout.addWidget(brief)

        stats = QGridLayout()
        stats.setHorizontalSpacing(10)
        stats.setVerticalSpacing(10)
        definitions = [
            ("jobs_found", "Jobs found", "Today"),
            ("excellent", "Excellent", "90%+ match"),
            ("strong", "Strong", "80–89% match"),
            ("prepared", "Ready", "Documents prepared"),
            ("submitted", "Applied", "Submitted"),
            ("interviews", "Interviews", "Active pipeline"),
            ("offers", "Offers", "Positive outcomes"),
            ("rejected", "Rejected", "Tracked outcomes"),
        ]
        for index, (key, label, hint) in enumerate(definitions):
            card = StatCard(label, "0", hint)
            self.stat_cards[key] = card
            stats.addWidget(card, index // 4, index % 4)
        layout.addLayout(stats)

        lower = QGridLayout()
        lower.setHorizontalSpacing(12)
        lower.setVerticalSpacing(12)
        profile_card = Card()
        profile_layout = QVBoxLayout(profile_card)
        profile_layout.setContentsMargins(18, 15, 18, 15)
        profile_layout.addWidget(section_label("COMPLETE YOUR CANDIDATE PROFILE"))
        self.profile_status = QLabel("")
        self.profile_status.setObjectName("muted")
        self.profile_status.setWordWrap(True)
        profile_layout.addWidget(self.profile_status)
        profile_action = action_button("Open Candidate Profile", True)
        profile_action.clicked.connect(lambda: self.navigate.emit("profile"))
        profile_layout.addWidget(profile_action, 0)
        lower.addWidget(profile_card, 0, 0)

        readiness_card = Card()
        readiness_layout = QVBoxLayout(readiness_card)
        readiness_layout.setContentsMargins(18, 15, 18, 15)
        readiness_layout.addWidget(section_label("SYSTEM READINESS"))
        self.readiness = QLabel("")
        self.readiness.setObjectName("muted")
        self.readiness.setWordWrap(True)
        readiness_layout.addWidget(self.readiness)
        lower.addWidget(readiness_card, 0, 1)

        workflow_card = Card()
        workflow_layout = QVBoxLayout(workflow_card)
        workflow_layout.setContentsMargins(18, 15, 18, 15)
        workflow_layout.addWidget(section_label("APPLICATION WORKFLOW"))
        self.workflow_status = QLabel("")
        self.workflow_status.setObjectName("muted")
        self.workflow_status.setWordWrap(True)
        workflow_layout.addWidget(self.workflow_status)
        workflow_action = action_button("Open application queue")
        workflow_action.clicked.connect(lambda: self.navigate.emit("queue"))
        workflow_layout.addWidget(workflow_action, 0)
        lower.addWidget(workflow_card, 0, 2)
        layout.addLayout(lower)

        actions = QHBoxLayout()
        actions.addStretch()
        configure = action_button("Find Jobs / Sources")
        configure.clicked.connect(lambda: self.navigate.emit("search"))
        search = action_button("Search Jobs Now", True)
        search.clicked.connect(self.search_now)
        actions.addWidget(configure)
        actions.addWidget(search)
        layout.addLayout(actions)
        layout.addStretch()

    def refresh(self) -> None:
        counts = self.repository.dashboard_counts()
        for key, card in self.stat_cards.items():
            value = counts.get(key, 0)
            if key == "average_score":
                card.value_widget.setText(f"{float(value):.0f}%")
            else:
                card.value_widget.setText(str(value))

        locations = self.repository.get_setting("selected_locations", [])
        sources = self.repository.get_setting("selected_sources", [])
        self.brief_label.setText(
            f"{counts.get('jobs_found', 0)} new jobs  •  {counts.get('excellent', 0)} excellent  •  "
            f"{counts.get('strong', 0)} strong  •  {counts.get('prepared', 0)} ready for review  •  "
            f"{counts.get('total_applications', 0)} tracked applications  •  {counts.get('needs_attention', 0)} need attention  •  "
            f"{len(locations)} target markets  •  {len(sources)} source preferences"
        )

        profile = self.repository.get_profile()
        cv = self.repository.latest_master_cv()
        profile_ready = bool(profile.full_name and (profile.email or profile.phone))
        if profile_ready and cv:
            self.profile_status.setText("Your Master CV and contact profile are ready for job matching and truthful document tailoring.")
        elif cv:
            self.profile_status.setText("Master CV uploaded. Complete your name and contact details so applications can be prepared correctly.")
        else:
            self.profile_status.setText("Upload your Master CV and complete the structured profile before searching.")

        self.readiness.setText(
            "✓ Candidate database available\n"
            f"{'✓' if cv else '○'} Master CV and CV text extraction\n"
            "✓ Explainable match engine enabled\n"
            f"{'✓' if self.repository.get_setting('feed_urls', []) else '○'} Approved job feeds configured"
        )
        self.workflow_status.setText(
            f"{counts.get('prepared', 0)} ready  •  {counts.get('needs_attention', 0)} need review\n"
            f"{counts.get('interviews', 0)} interviews  •  {counts.get('email_applications', 0)} email routes\n"
            f"{counts.get('offers', 0)} offers  •  {counts.get('average_score', 0)}% average match  •  Analytics stay local"
        )
