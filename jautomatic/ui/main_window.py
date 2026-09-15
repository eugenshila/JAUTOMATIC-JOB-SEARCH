"""Main window: sidebar navigation, background worker plumbing, app state.

The window doubles as the application context object that every tab receives as
``ctx``.  Tabs use it to reach the workspace/pipeline and to run slow work
(scraping, document generation) off the GUI thread:

    ctx.run_task("Searching job boards…", lambda: pipeline.search(query),
                 on_done=self._show_results)
"""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QSizePolicy, QStackedWidget, QStatusBar, QVBoxLayout,
                               QWidget)

from .. import APP_TITLE, __version__
from ..models import AppSettings, Profile, Workspace
from ..services.application_pipeline import ApplicationPipeline
from . import theme as th
from .applications_tab import ApplicationsTab
from .dashboard_tab import DashboardTab
from .job_search_tab import JobSearchTab
from .profile_tab import ProfileTab
from .settings_tab import SettingsTab

NAV_ITEMS = [
    ("dashboard", "Dashboard", "Overview of your search"),
    ("profile", "Profile", "Who you are, what you want"),
    ("search", "Job search", "Find and score openings"),
    ("applications", "Applications", "Materials, tracking, follow-ups"),
    ("settings", "Settings", "Sources, documents, data"),
]


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    """Runs ``fn`` on the thread pool and reports back on the GUI thread."""

    def __init__(self, fn, *args, **kwargs) -> None:  # noqa: ANN001, ANN003
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:  # noqa: D102
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - reported to the UI, never fatal
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.signals.failed.emit(detail)
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
        self._qt_settings = QSettings("JAUTOMATIC", "job-search")

        self.setWindowTitle(f"{APP_TITLE} {__version__}")
        self.resize(1440, 900)
        self.setMinimumSize(1024, 680)
        self._build_ui()
        self._wire_shortcuts()
        self._restore_geometry()
        self.go_to("dashboard")

    # ------------------------------------------------------------------ UI #
    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_sidebar())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 16, 18, 10)
        right_layout.setSpacing(12)
        right_layout.addWidget(self._build_header())

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tabs = {
            "dashboard": DashboardTab(self),
            "profile": ProfileTab(self),
            "search": JobSearchTab(self),
            "applications": ApplicationsTab(self),
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
        self.status_meta.setObjectName("Small")
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
        layout.setSpacing(6)

        brand = QLabel("JAUTOMATIC")
        brand.setObjectName("SidebarTitle")
        sub = QLabel("JOB SEARCH AUTOPILOT")
        sub.setObjectName("SidebarSubtitle")
        layout.addWidget(brand)
        layout.addWidget(sub)
        layout.addSpacing(18)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text, tooltip in NAV_ITEMS:
            button = QPushButton(f"  {th.GLYPHS.get(key, '•')}   {text}")
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _=False, k=key: self.go_to(k))
            layout.addWidget(button)
            self.nav_buttons[key] = button

        layout.addStretch(1)
        self.sidebar_stats = QLabel("")
        self.sidebar_stats.setObjectName("SidebarFooter")
        self.sidebar_stats.setWordWrap(True)
        layout.addWidget(self.sidebar_stats)
        version = QLabel(f"v{__version__}")
        version.setObjectName("SidebarFooter")
        layout.addWidget(version)
        return sidebar

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QVBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.page_titles: dict[str, QWidget] = {}
        for key, text, tooltip in NAV_ITEMS:
            box = th.title_label(text, tooltip)
            box.setVisible(False)
            self.page_titles[key] = box
            row.addWidget(box)
        row.addStretch(1)
        self.header_actions = QHBoxLayout()
        self.header_actions.setSpacing(8)
        row.addLayout(self.header_actions)
        layout.addLayout(row)
        self.toast = th.Toast()
        layout.addWidget(self.toast)
        return header

    def _wire_shortcuts(self) -> None:
        for index, (key, _, _) in enumerate(NAV_ITEMS, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.activated.connect(lambda k=key: self.go_to(k))
        QShortcut(QKeySequence("F5"), self).activated.connect(self.refresh_current_tab)
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self.close)

    # ------------------------------------------------------------ context #
    @property
    def busy(self) -> bool:
        return self._busy > 0

    def go_to(self, key: str) -> None:
        self._active_key = key
        self._update_header_actions()
        for index, (nav_key, _, _) in enumerate(NAV_ITEMS):
            if nav_key == key:
                self.stack.setCurrentIndex(index)
                self.nav_buttons[nav_key].setChecked(True)
                self.page_titles[nav_key].setVisible(True)
            else:
                self.nav_buttons[nav_key].setChecked(False)
                self.page_titles[nav_key].setVisible(False)
        tab = self.tabs.get(key)
        if tab is not None and hasattr(tab, "refresh"):
            try:
                tab.refresh()
            except Exception as exc:  # noqa: BLE001 - never let refresh kill the UI
                self.notify(f"Could not refresh the {key} view: {exc}", "warning")
        self.update_meta()

    def refresh_current_tab(self) -> None:
        key = self.stack.currentWidget().property("nav_key") or "dashboard"
        self.go_to(key)

    def refresh_all(self) -> None:
        for tab in self.tabs.values():
            if hasattr(tab, "refresh"):
                try:
                    tab.refresh()
                except Exception as exc:  # noqa: BLE001
                    self.notify(f"Refresh problem: {exc}", "warning")
        self.update_meta()

    def run_task(self, description: str, fn, on_done=None, on_error=None, *args,
                 **kwargs) -> Worker:  # noqa: ANN001, ANN003, ANN201
        """Run ``fn`` in the background; callbacks fire on the GUI thread.

        The worker is kept in ``self._workers`` for the duration of the task: PySide6
        does not keep a Python reference to a ``QRunnable`` handed to ``QThreadPool``,
        so a worker nobody points at is garbage collected before it ever runs.
        """
        worker = Worker(fn, *args, **kwargs)
        self._workers.add(worker)
        self._busy += 1
        self.set_status(f"{description}…")
        self.setCursor(Qt.BusyCursor)

        def forget() -> None:
            self._workers.discard(worker)

        def finish(result) -> None:  # noqa: ANN001
            forget()
            self._task_finished()
            if on_done is not None:
                try:
                    on_done(result)
                except Exception as exc:  # noqa: BLE001
                    self.notify(f"Something went wrong handling the result: {exc}", "error")

        def fail(message: str) -> None:
            forget()
            self._task_finished()
            self.notify(message, "error")
            if on_error is not None:
                on_error(message)

        worker.signals.finished.connect(finish)
        worker.signals.failed.connect(fail)
        self.pool.start(worker)
        return worker

    def _task_finished(self) -> None:
        self._busy = max(0, self._busy - 1)
        if not self._closing:
            self.unsetCursor()
            if self._busy == 0:
                self.set_status("Ready")
        self.update_meta()

    def set_status(self, text: str) -> None:
        if not self._closing:
            self.status_label.setText(text)

    def notify(self, message: str, level: str = "info") -> None:
        if self._closing:
            return
        self.toast.show_message(message, level)
        if level in ("error", "warning"):
            self.set_status(message)

    def confirm(self, title: str, message: str, danger: bool = False) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(QMessageBox.Warning if danger else QMessageBox.Question)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    def update_meta(self) -> None:
        stats = self.workspace.stats()
        busy = " · working…" if self._busy else ""
        self.status_meta.setText(
            f"{self.profile.display_name} · profile {self.profile.completeness()}% · "
            f"{stats['jobs']} jobs · {stats['applications']} tracked · "
            f"{stats['materials_ready']} ready · {stats['sent']} sent{busy}")
        self.sidebar_stats.setText(
            f"{stats['jobs']} postings · {stats['applications']} tracked\n"
            f"{stats['sent']} sent · {stats['interviews']} interviews")

    # ------------------------------------------------------------- state  #
    def reload_profile(self) -> Profile:
        self.profile = self.workspace.load_profile()
        return self.profile

    def save_profile(self, profile: Profile) -> None:
        self.profile = profile
        self.workspace.save_profile(profile)
        self.update_meta()

    def save_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        self.workspace.save_settings(settings)
        self.pipeline.settings = settings
        self.pipeline.scraper.settings = settings

    def apply_theme(self, name: str) -> None:
        app = QApplication.instance()
        if app is not None:
            theme = th.apply_theme(app, name)
            self.refresh_all()
            self.notify(f"Switched to the {theme.name} theme.", "success")

    def add_header_action(self, key: str, widget: QWidget) -> QWidget:
        """Register a primary action that is only visible while ``key`` is active."""
        widget.setVisible(key == self._active_key)
        self.header_actions.addWidget(widget)
        self._header_actions.setdefault(key, []).append(widget)
        return widget

    def _update_header_actions(self) -> None:
        for key, widgets in self._header_actions.items():
            for widget in widgets:
                widget.setVisible(key == self._active_key)

    def open_preview(self, title: str, markdown: str,
                     path: str | Path | None = None) -> th.MarkdownPreviewDialog:
        """Show a generated document in a (non-modal) preview window.

        Non-modal on purpose: the window keeps working while a document is on
        screen, and scripts/tests can inspect the dialog without blocking.
        """
        dialog = th.MarkdownPreviewDialog(title, markdown, path, self)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        self._previews.append(dialog)
        dialog.destroyed.connect(lambda *_, d=dialog: self._forget_preview(d))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _forget_preview(self, dialog: QWidget) -> None:
        if dialog in self._previews:
            self._previews.remove(dialog)

    # -------------------------------------------------------- lifecycle   #
    def _restore_geometry(self) -> None:
        geometry = self._qt_settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        theme_name = self.settings.theme or th.DEFAULT_THEME
        app = QApplication.instance()
        if app is not None:
            th.apply_theme(app, theme_name)

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        self._qt_settings.setValue("geometry", self.saveGeometry())
        self._closing = True
        self.pool.waitForDone(800)
        self._workers.clear()
        self.workspace.close()
        super().closeEvent(event)


__all__ = ["MainWindow", "Worker", "WorkerSignals", "NAV_ITEMS"]
