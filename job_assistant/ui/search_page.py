from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QSpinBox, QVBoxLayout, QWidget, QComboBox

from job_assistant.config.settings import DEFAULT_JOB_TYPES, DEFAULT_LOCATIONS, DEFAULT_SOURCES, DEFAULT_SEARCH_FREQUENCY
from job_assistant.database.repository import Repository
from job_assistant.ui.widgets import Card, action_button, page_header, section_label


class SearchPage(QWidget):
    search_now = Signal()
    saved = Signal()

    def __init__(self, repository: Repository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.location_checks: dict[str, QCheckBox] = {}
        self.type_checks: dict[str, QCheckBox] = {}
        self.source_checks: dict[str, QCheckBox] = {}
        self._build()
        self.load_settings()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 26, 30, 24)
        title, subtitle = page_header("Find jobs", "Configure a focused search. Connectors will only query enabled, approved sources in later phases.")
        outer.addWidget(title)
        outer.addWidget(subtitle)
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(15)

        location_group = QGroupBox("Target markets")
        location_grid = QGridLayout(location_group)
        for index, label in enumerate(DEFAULT_LOCATIONS):
            check = QCheckBox(label)
            self.location_checks[label] = check
            location_grid.addWidget(check, index // 4, index % 4)
        layout.addWidget(location_group)

        types_group = QGroupBox("Job types and workplace")
        type_grid = QGridLayout(types_group)
        for index, label in enumerate(DEFAULT_JOB_TYPES):
            check = QCheckBox(label)
            self.type_checks[label] = check
            type_grid.addWidget(check, index // 4, index % 4)
        layout.addWidget(types_group)

        source_group = QGroupBox("Job sources")
        source_grid = QGridLayout(source_group)
        for index, label in enumerate(DEFAULT_SOURCES):
            check = QCheckBox(label)
            self.source_checks[label] = check
            source_grid.addWidget(check, index // 2, index % 2)
        layout.addWidget(source_group)

        form_row = QHBoxLayout()
        freq_column = QVBoxLayout()
        freq_column.addWidget(QLabel("Search frequency"))
        self.frequency = QComboBox()
        self.frequency.addItems(["On startup", "Every 2 hours", "Every 4 hours", "Every 6 hours", "Every 12 hours", "Once daily", "Manual search only"])
        freq_column.addWidget(self.frequency)
        form_row.addLayout(freq_column, 1)
        for label, attr in (("Prepare documents at", "prepare_threshold"), ("Priority application at", "priority_threshold"), ("Do not prepare below", "minimum_threshold")):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            spin = QSpinBox()
            spin.setRange(0, 100)
            spin.setSuffix("%")
            setattr(self, attr, spin)
            column.addWidget(spin)
            form_row.addLayout(column, 1)
        layout.addLayout(form_row)

        salary_row = QHBoxLayout()
        self.salary_min = QPlainTextEdit()
        self.salary_min.setPlaceholderText("Minimum salary")
        self.salary_min.setMaximumHeight(42)
        self.salary_max = QPlainTextEdit()
        self.salary_max.setPlaceholderText("Maximum salary")
        self.salary_max.setMaximumHeight(42)
        self.currency = QComboBox()
        self.currency.addItems(["USD", "KES", "AED", "QAR", "SAR", "BHD", "OMR", "GBP", "EUR"])
        salary_row.addWidget(QLabel("Salary preference"))
        salary_row.addWidget(self.salary_min)
        salary_row.addWidget(self.salary_max)
        salary_row.addWidget(self.currency)
        layout.addLayout(salary_row)

        layout.addWidget(QLabel("Approved public RSS/XML or JSON feed URLs (one per line)"))
        self.feed_urls = QPlainTextEdit()
        self.feed_urls.setPlaceholderText("LinkedIn | https://example.org/approved-linkedin-feed.xml\nIndeed | https://example.org/approved-indeed-feed.json")
        self.feed_urls.setMaximumHeight(80)
        layout.addWidget(self.feed_urls)
        feed_note = QLabel("A source name does not grant access by itself. Add only an official API, approved partner feed, or public RSS/XML/JSON endpoint that permits automated access. Otherwise use View Job for manual browsing. No login, CAPTCHA, or anti-bot controls are bypassed.")
        feed_note.setObjectName("muted")
        feed_note.setWordWrap(True)
        layout.addWidget(feed_note)

        layout.addWidget(QLabel("Target and transferable job titles (one per line; leave empty to derive from the profile)"))
        self.target_titles = QPlainTextEdit()
        self.target_titles.setPlaceholderText("Supply Chain Analyst\nOperations Coordinator\nInventory Controller")
        self.target_titles.setMaximumHeight(105)
        layout.addWidget(self.target_titles)
        outer.addWidget(card)

        buttons = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("success")
        buttons.addWidget(self.status)
        buttons.addStretch()
        save = action_button("Save search configuration")
        save.clicked.connect(self.save_settings)
        run = action_button("Search jobs now", True)
        run.clicked.connect(self._search)
        buttons.addWidget(save)
        buttons.addWidget(run)
        outer.addLayout(buttons)
        outer.addStretch()

    def load_settings(self) -> None:
        settings = self.repository.get_settings()
        self._set_checks(self.location_checks, settings.get("selected_locations", []))
        self._set_checks(self.type_checks, settings.get("selected_job_types", []))
        self._set_checks(self.source_checks, settings.get("selected_sources", DEFAULT_SOURCES))
        self.frequency.setCurrentText(settings.get("search_frequency", DEFAULT_SEARCH_FREQUENCY))
        self.prepare_threshold.setValue(int(settings.get("auto_prepare_threshold", 75)))
        self.priority_threshold.setValue(int(settings.get("priority_threshold", 85)))
        self.minimum_threshold.setValue(int(settings.get("minimum_match_threshold", 65)))
        self.salary_min.setPlainText(str(settings.get("salary_min", "")))
        self.salary_max.setPlainText(str(settings.get("salary_max", "")))
        self.currency.setCurrentText(settings.get("currency", "USD"))
        self.feed_urls.setPlainText("\n".join(settings.get("feed_urls", [])))
        self.target_titles.setPlainText("\n".join(settings.get("target_titles", [])))

    @staticmethod
    def _set_checks(checks: dict[str, QCheckBox], selected: list[str]) -> None:
        for label, check in checks.items():
            check.setChecked(label in selected)

    @staticmethod
    def _selected(checks: dict[str, QCheckBox]) -> list[str]:
        return [label for label, check in checks.items() if check.isChecked()]

    def config(self) -> dict:
        return {
            "selected_locations": self._selected(self.location_checks),
            "selected_job_types": self._selected(self.type_checks),
            "selected_sources": self._selected(self.source_checks),
            "search_frequency": self.frequency.currentText(),
            "auto_prepare_threshold": self.prepare_threshold.value(),
            "priority_threshold": self.priority_threshold.value(),
            "minimum_match_threshold": self.minimum_threshold.value(),
            "salary_min": self.salary_min.toPlainText().strip(),
            "salary_max": self.salary_max.toPlainText().strip(),
            "currency": self.currency.currentText(),
            "feed_urls": [line.strip() for line in self.feed_urls.toPlainText().splitlines() if line.strip()],
            "target_titles": [line.strip() for line in self.target_titles.toPlainText().splitlines() if line.strip()],
        }

    def save_settings(self) -> None:
        config = self.config()
        for key, value in config.items():
            self.repository.set_setting(key, value)
        self.status.setText("Search configuration saved locally.")
        self.saved.emit()

    def _search(self) -> None:
        self.save_settings()
        self.search_now.emit()
