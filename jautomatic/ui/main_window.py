"""Main window: sidebar navigation, background worker plumbing, app state."""
from __future__ import annotations

import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QRectF, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy, QStackedWidget, QStatusBar, QSystemTrayIcon, QVBoxLayout, QWidget

from .. import APP_TITLE, __version__
from ..models import AppSettings, Profile, Workspace
from ..services.application_pipeline import ApplicationPipeline
from . import theme as th
from .analytics_tab import AnalyticsTab
from .applications_tab import ApplicationsTab
from .dashboard_tab import DashboardTab
from .interview_prep_dialog import InterviewPrepDialog
from .job_search_tab import JobSearchTab
from .learning_tab import LearningTab
from .profile_tab import ProfileTab
from .settings_tab import SettingsTab
from .tasks_tab import TasksTab

NAV_ITEMS = [
    ("dashboard", "Dashboard", "Overview of your search"),
    ("profile", "Profile", "Who you are, what you want"),
    ("learning", "Skills Improvement & Learning", "Find free courses and track certificates"),
    ("search", "Job search", "Find and score openings"),
    ("tasks", "Tasks", "Microtasks & gigs with a minimum-pay filter"),
    ("applications", "Applications", "Prepare applications before sending"),
    ("sent", "Sent", "Sent applications, follow-ups and interview preparation"),
    ("archive", "Archive", "Regrets, archived applications and permanent deletion"),
    ("insights", "Insights", "Trends, response times, market demand"),
    ("settings", "Settings", "Sources, documents, data"),
]


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn, *args, cancel: threading.Event | None = None, **kwargs) -> None:
        super().__init__()
        self.fn, self.args, self.kwargs, self.cancel = fn, args, kwargs, cancel
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            return
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:
            self.signals.failed.emit("".join(traceback.format_exception_only(type(exc), exc)).strip())
        else:
            self.signals.finished.emit(result)


class MainWindow(QMainWindow):
    def __init__(self, data_dir: str | Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = Workspace(data_dir)
        self.settings: AppSettings = self.workspace.load_settings()
        if data_dir is not None:
            self.settings.data_dir = str(self.workspace.root)
            self.workspace.save_settings(self.settings)
        self.profile: Profile = self.workspace.load_profile()
        self.pipeline = ApplicationPipeline(self.workspace, self.settings)
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(max(2, min(8, self.pool.maxThreadCount())))
        self._busy = 0
        self._closing = False
        self._active_key = "dashboard"
        self._header_actions: dict[str, list[QWidget]] = {}
        self._previews: list[QWidget] = []
        self._workers: set[Worker] = set()
        self._background_notes: list[str] = []
        self._tray: QSystemTrayIcon | None = None
        self.cancel_event = threading.Event()
        app = QApplication.instance()
        if app is not None:
            th.apply_theme(app, self.settings.theme or th.DEFAULT_THEME)
        self.setWindowTitle(f"{APP_TITLE} {__version__}")
        self.resize(1440, 900)
        self.setMinimumSize(1024, 680)
        self._build_ui()
        self._wire_shortcuts()
        self._restore_geometry()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.background_refresh)
        self._apply_auto_refresh()
        self.go_to("dashboard")
        self._setup_tray()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self._build_sidebar())
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 16, 18, 10)
        right_layout.addWidget(self._build_header())
        self.stack = QStackedWidget()
        self.tabs = {
            "dashboard": DashboardTab(self),
            "profile": ProfileTab(self),
            "learning": LearningTab(self),
            "search": JobSearchTab(self),
            "tasks": TasksTab(self),
            "applications": ApplicationsTab(self),
            "sent": ApplicationsTab(self, "sent"),
            "archive": ApplicationsTab(self, "archive"),
            "insights": AnalyticsTab(self),
            "settings": SettingsTab(self),
        }
        for key, _, _ in NAV_ITEMS:
            self.stack.addWidget(self._index_of(self.tabs[key], key))
        right_layout.addWidget(self.stack, 1)
        root_layout.addWidget(right, 1)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.status_label = QLabel("Ready")
        self.status_meta = QLabel("")
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.status_meta)

    def _index_of(self, widget: QWidget, key: str) -> QWidget:
        widget.setProperty("nav_key", key)
        return widget

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(224)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        brand = QLabel("JAUTOMATIC")
        brand.setObjectName("SidebarTitle")
        layout.addWidget(brand)
        subtitle = QLabel("JOB SEARCH AUTOPILOT")
        subtitle.setObjectName("SidebarSubtitle")
        layout.addWidget(subtitle)
        layout.addSpacing(18)
        self.nav_buttons = {}
        for key, text, tooltip in NAV_ITEMS:
            button = QPushButton(f"  {th.GLYPHS.get(key, '•')}   {text}")
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _=False, k=key: self.go_to(k))
            layout.addWidget(button)
            self.nav_buttons[key] = button
        layout.addStretch(1)
        self.sidebar_stats = QLabel("")
        layout.addWidget(self.sidebar_stats)
        return sidebar

    def _build_header(self) -> QWidget:
        header = QWidget()
        row = QHBoxLayout(header)
        self.page_titles = {}
        for key, text, tooltip in NAV_ITEMS:
            box = th.title_label(text, tooltip)
            box.setVisible(False)
            self.page_titles[key] = box
            row.addWidget(box)
        row.addStretch(1)
        self.header_actions = QHBoxLayout()
        row.addLayout(self.header_actions)
        self.toast = th.Toast()
        return header

    def _wire_shortcuts(self) -> None:
        for index, (key, _, _) in enumerate(NAV_ITEMS, start=1):
            QShortcut(QKeySequence(f"Ctrl+{index}"), self).activated.connect(lambda k=key: self.go_to(k))
        QShortcut(QKeySequence("F5"), self).activated.connect(self.refresh_current_tab)
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self.close)

    def go_to(self, key: str) -> None:
        self._active_key = key
        for index, (nav_key, _, _) in enumerate(NAV_ITEMS):
            selected = nav_key == key
            self.nav_buttons[nav_key].setChecked(selected)
            self.page_titles[nav_key].setVisible(selected)
            if selected:
                self.stack.setCurrentIndex(index)
        self.update_meta()

    def refresh_current_tab(self) -> None:
        self.go_to(self.stack.currentWidget().property("nav_key") or "dashboard")

    def run_task(self, description, fn, on_done=None, on_error=None, *args, **kwargs):
        if self._closing:
            return None
        worker = Worker(fn, *args, cancel=self.cancel_event, **kwargs)
        self._workers.add(worker)
        self._busy += 1
        self.status_label.setText(f"{description}…")
        worker.signals.finished.connect(lambda result: self._finish_worker(worker, result, on_done))
        worker.signals.failed.connect(lambda message: self._fail_worker(worker, message, on_error))
        self.pool.start(worker)
        return worker

    def _finish_worker(self, worker, result, callback):
        self._workers.discard(worker)
        self._busy = max(0, self._busy - 1)
        if callback:
            callback(result)
        self.update_meta()

    def _fail_worker(self, worker, message, callback):
        self._workers.discard(worker)
        self._busy = max(0, self._busy - 1)
        self.notify(message, "error")
        if callback:
            callback(message)
        self.update_meta()

    def notify(self, message, level="info"):
        self.toast.show_message(message, level)
        self.status_label.setText(message)

    def update_meta(self):
        if self._closing:
            return
        stats = self.workspace.stats()
        self.status_meta.setText(f"{self.profile.display_name} · {stats['jobs']} jobs · {stats['applications']} tracked")
        self.sidebar_stats.setText(f"{stats['jobs']} postings · {stats['applications']} tracked")

    def reload_profile(self):
        self.profile = self.workspace.load_profile()
        return self.profile

    def save_profile(self, profile):
        self.profile = profile
        self.workspace.save_profile(profile)
        self.update_meta()

    def save_settings(self, settings):
        self.settings = settings
        self.workspace.save_settings(settings)
        self.pipeline.settings = settings
        self._apply_auto_refresh()

    def _apply_auto_refresh(self):
        if not hasattr(self, "_refresh_timer"):
            return
        self._refresh_timer.stop()
        if self._closing or not self.settings.auto_refresh_enabled:
            return
        self._refresh_timer.setInterval(max(1, self.settings.auto_refresh_minutes) * 60000)
        self._refresh_timer.start()

    def _setup_tray(self):
        return

    def background_refresh(self):
        return

    def _update_header_actions(self):
        for key, widgets in self._header_actions.items():
            for widget in widgets:
                widget.setVisible(key == self._active_key)

    def add_header_action(self, key, widget):
        widget.setVisible(key == self._active_key)
        self.header_actions.addWidget(widget)
        self._header_actions.setdefault(key, []).append(widget)
        return widget

    def open_preview(self, title, markdown, path=None):
        dialog = th.MarkdownPreviewDialog(title, markdown, path, self)
        dialog.show()
        return dialog

    def open_interview_prep(self, row):
        return InterviewPrepDialog(self, row, self)

    def _restore_geometry(self):
        blob = self.settings.window_geometry
        if blob:
            self.restoreGeometry(QByteArray.fromBase64(blob.encode("ascii", "ignore")))

    def closeEvent(self, event):
        self._closing = True
        self.cancel_event.set()
        self.pool.clear()
        self.pool.waitForDone()
        self.workspace.close()
        super().closeEvent(event)
