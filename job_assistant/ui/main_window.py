from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from job_assistant.config.settings import APP_NAME, AppPaths
from job_assistant.database.repository import Repository
from job_assistant.ui.application_queue_page import ApplicationQueuePage
from job_assistant.ui.dashboard_page import DashboardPage
from job_assistant.ui.placeholder_page import PlaceholderPage
from job_assistant.ui.profile_page import ProfilePage
from job_assistant.ui.search_page import SearchPage
from job_assistant.ui.search_worker import SearchWorker
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
        self.search_worker: SearchWorker | None = None
        self._build_ui()
        self.apply_theme(self.repository.get_setting("appearance", "Dark"))
        self.search_timer = QTimer(self)
        self.search_timer.timeout.connect(self.search_now)
        self._configure_search_timer(initial=True)
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
        self.search.saved.connect(self._configure_search_timer)
        self._add_page("search", self.search)
        self.queue = ApplicationQueuePage(self.repository)
        self._add_page("queue", self.queue)
        self.settings = SettingsPage(self.repository, self.paths)
        self.settings.theme_changed.connect(self.apply_theme)
        self.settings.settings_saved.connect(self._configure_search_timer)
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

    def _configure_search_timer(self, initial: bool = False) -> None:
        intervals = {
            "Every 2 hours": 2 * 60 * 60 * 1000,
            "Every 4 hours": 4 * 60 * 60 * 1000,
            "Every 6 hours": 6 * 60 * 60 * 1000,
            "Every 12 hours": 12 * 60 * 60 * 1000,
            "Once daily": 24 * 60 * 60 * 1000,
        }
        self.search_timer.stop()
        frequency = self.repository.get_setting("search_frequency", "Every 6 hours")
        if frequency in intervals:
            self.search_timer.start(intervals[frequency])
        if initial and self.repository.get_setting("search_on_startup", True) and self.repository.get_setting("feed_urls", []):
            QTimer.singleShot(1500, self.search_now)

    def search_now(self) -> None:
        if self.search_worker and self.search_worker.isRunning():
            self.set_status("A job search is already running")
            return
        config = self.search.config()
        self.set_status("Searching configured public feeds…")
        self.search_worker = SearchWorker(self.repository, str(self.paths.applications_dir), config, self)
        self.search_worker.completed.connect(self._search_finished)
        self.search_worker.start()

    def _search_finished(self, summary: object) -> None:
        self.dashboard.refresh()
        self.queue.refresh()
        self.search_worker = None
        jobs = getattr(summary, "jobs_found", 0)
        prepared = getattr(summary, "applications_prepared", 0)
        errors = getattr(summary, "errors", [])
        message = f"Search complete. {jobs} jobs found; {prepared} application(s) prepared for review."
        if errors:
            message += "\n\n" + "\n".join(errors[:3])
        self.set_status(message.replace("\n", " "))
        if errors and jobs == 0:
            self.show_page("search")
            self.search.focus_feed_urls()
            guidance = (
                "No approved job-feed URL is configured. Selecting LinkedIn, Indeed, or another source only records your preference; it does not grant access to that website.\n\n"
                "Add a permitted RSS/XML/JSON endpoint in the feed box, for example:\n"
                "LinkedIn | https://your-approved-feed.example/jobs.xml\n\n"
                "Use an official API or approved feed supplied by the provider. For sites without one, open and apply through the official job page manually."
            )
            QMessageBox.warning(self, "Search setup required", guidance)
        elif errors:
            QMessageBox.warning(self, "Job search completed with warnings", message)
        else:
            QMessageBox.information(self, "Job search complete", message)

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def apply_theme(self, appearance: str) -> None:
        self.setStyleSheet(LIGHT_STYLESHEET if appearance == "Light" else DARK_STYLESHEET)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.accept()


def button_text(button: QPushButton | None) -> str:
    return button.text() if button else "Workspace"
