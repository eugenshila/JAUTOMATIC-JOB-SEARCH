from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from job_assistant.config.settings import APP_NAME, AppPaths
from job_assistant.database.repository import Repository
from job_assistant.ui.dashboard_page import DashboardPage
from job_assistant.ui.placeholder_page import PlaceholderPage
from job_assistant.ui.profile_page import ProfilePage
from job_assistant.ui.search_page import SearchPage
from job_assistant.ui.settings_page import SettingsPage
from job_assistant.ui.theme import DARK_STYLESHEET, LIGHT_STYLESHEET


class MainWindow(QMainWindow):
    def __init__(self, repository: Repository, paths: AppPaths):
        super().__init__()
        self.repository = repository
        self.paths = paths
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1120, 720)
        self.resize(1320, 840)
        self._nav_buttons: dict[str, QPushButton] = {}
        self.pages: dict[str, QWidget] = {}
        self._build_ui()
        self.apply_theme(self.repository.get_setting("appearance", "Dark"))
        self.show_page("dashboard")

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(228)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(15, 22, 15, 18)
        sidebar_layout.setSpacing(4)
        brand = QLabel("AI Job Assistant")
        brand.setObjectName("brand")
        brand_sub = QLabel("Private career workspace")
        brand_sub.setObjectName("brandSub")
        sidebar_layout.addWidget(brand)
        sidebar_layout.addWidget(brand_sub)
        sidebar_layout.addSpacing(24)

        groups = [
            ("WORKSPACE", [("dashboard", "Dashboard"), ("search", "Find Jobs"), ("matches", "Job Matches"), ("queue", "Application Queue")]),
            ("APPLICATIONS", [("applications", "Applications"), ("profile", "CV Builder"), ("letters", "Cover Letters")]),
            ("INSIGHTS", [("interviews", "Interviews"), ("recruiters", "Recruiters"), ("analytics", "Analytics")]),
        ]
        for group_name, entries in groups:
            group = QLabel(group_name)
            group.setObjectName("brandSub")
            sidebar_layout.addWidget(group)
            for key, text in entries:
                button = QPushButton(text)
                button.setObjectName("navButton")
                button.setProperty("nav_key", key)
                button.clicked.connect(lambda checked=False, page=key: self.show_page(page))
                self._nav_buttons[key] = button
                sidebar_layout.addWidget(button)
            sidebar_layout.addSpacing(10)
        sidebar_layout.addStretch()
        settings_button = QPushButton("Settings")
        settings_button.setObjectName("navButton")
        settings_button.clicked.connect(lambda: self.show_page("settings"))
        self._nav_buttons["settings"] = settings_button
        sidebar_layout.addWidget(settings_button)
        main_layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)
        status_bar = QFrame()
        status_bar.setObjectName("statusBar")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(18, 7, 18, 7)
        self.status_label = QLabel("Local database ready")
        self.status_label.setObjectName("statusText")
        self.privacy_label = QLabel("●  Private local workspace")
        self.privacy_label.setObjectName("statusText")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.privacy_label)
        content_layout.addWidget(status_bar)
        main_layout.addWidget(content, 1)

        self.dashboard = DashboardPage(self.repository)
        self.dashboard.navigate.connect(self.show_page)
        self.dashboard.search_now.connect(self.search_now)
        self._add_page("dashboard", self.dashboard)

        # First-development-phase pages are concrete; later pages are explicit placeholders.
        self.profile = ProfilePage(self.repository, self.paths)
        self.profile.saved.connect(self.dashboard.refresh)
        self._add_page("profile", self.profile)
        self.search = SearchPage(self.repository)
        self.search.search_now.connect(self.search_now)
        self._add_page("search", self.search)
        self.settings = SettingsPage(self.repository, self.paths)
        self.settings.theme_changed.connect(self.apply_theme)
        self._add_page("settings", self.settings)
        for key, title, description in [
            ("matches", "Job Matches", "Review ranked opportunities with transparent score explanations."),
            ("queue", "Application Queue", "Approve, edit, or reject prepared application documents."),
            ("applications", "Applications", "Track every application from discovery through outcome."),
            ("letters", "Cover Letters", "Create truthful, vacancy-specific cover letters."),
            ("interviews", "Interviews", "Keep interview dates, notes, and follow-up reminders in one place."),
            ("recruiters", "Recruiters", "Organize recruiter contacts and communication notes."),
            ("analytics", "Analytics", "Learn which roles, locations, and documents produce interviews."),
        ]:
            self._add_page(key, PlaceholderPage(title, description))

    def _add_page(self, key: str, page: QWidget) -> None:
        self.pages[key] = page
        self.stack.addWidget(page)

    def show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if not page:
            return
        self.stack.setCurrentWidget(page)
        for name, button in self._nav_buttons.items():
            button.setProperty("active", name == key)
            button.style().unpolish(button)
            button.style().polish(button)
        self.set_status(f"Viewing {button_text(self._nav_buttons.get(key))}")

    def search_now(self) -> None:
        QMessageBox.information(self, "Search workflow", "Job connectors are intentionally not enabled in Phase 1. Your search configuration is saved and ready for the retrieval engine in the next phase.")
        self.set_status("Search request recorded — connectors will be enabled in Phase 3")

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def apply_theme(self, appearance: str) -> None:
        self.setStyleSheet(LIGHT_STYLESHEET if appearance == "Light" else DARK_STYLESHEET)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.accept()


def button_text(button: QPushButton | None) -> str:
    return button.text() if button else "Workspace"
