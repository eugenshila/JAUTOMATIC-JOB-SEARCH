"""Main window: sidebar navigation, background worker plumbing, app state.

The window doubles as the application context object that every tab receives as
``ctx``.  Tabs use it to reach the workspace/pipeline and to run slow work
(scraping, document generation) off the GUI thread:

    ctx.run_task("Searching job boards…", lambda: pipeline.search(query),
                 on_done=self._show_results)
"""
from __future__ import annotations

import threading
import traceback
from pathlib import Path

from PySide6.QtCore import (
    QByteArray,
    QObject,
    QRectF,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import APP_TITLE, __version__
from ..models import AppSettings, Profile, Workspace
from ..services.application_pipeline import ApplicationPipeline
from . import theme as th
from .analytics_tab import AnalyticsTab
from .applications_tab import ApplicationsTab
from .dashboard_tab import DashboardTab
from .interview_prep_dialog import InterviewPrepDialog
from .job_search_tab import JobSearchTab
from .profile_tab import ProfileTab
from .settings_tab import SettingsTab
from .tasks_tab import TasksTab

NAV_ITEMS = [
    ("dashboard", "Dashboard", "Overview of your search"),
    ("profile", "Profile", "Who you are, what you want"),
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
    """Runs ``fn`` on the thread pool and reports back on the GUI thread.

    ``cancel`` is the window's shutdown event: a worker that gets a CPU *after*
    closing began (queued behind busy threads) checks it first and returns
    without touching the fn it would have run — no half-started tasks against
    a closing workspace.  Workers already running are *not* interrupted from
    here; long loops poll the same event cooperatively instead.
    """

    def __init__(self, fn, *args, cancel: threading.Event | None = None,
                 **kwargs) -> None:
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.cancel = cancel
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            return  # refused: the app is closing (no signals — nobody is listening)
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
        # Audit trail for background notifications (also the test hook: the
        # tray is unavailable under offscreen, so alerts land here and in the
        # in-app toast instead).
        self._background_notes: list[str] = []
        self._tray: QSystemTrayIcon | None = None
        # Set once, in closeEvent: refuses new tasks, aborts queued workers and
        # tells long-running loops (search, batch prepare) to wind down early.
        self.cancel_event = threading.Event()

        # Apply the saved theme BEFORE the UI is built: tabs bake concrete
        # colors from current_theme() at construction time (stat cards, hlines,
        # empty-state icons), so the palette must already be active here or a
        # non-default theme silently keeps the default palette's accents.
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
        self._refresh_timer.setTimerType(Qt.CoarseTimer)
        self._refresh_timer.timeout.connect(self.background_refresh)
        self._apply_auto_refresh()
        self.go_to("dashboard")
        self._run_startup_maintenance()
        self._setup_tray()
        if self.workspace.recovery_notices:
            self.notify(" ".join(self.workspace.recovery_notices), "warning")

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
                 **kwargs) -> Worker | None:
        """Run ``fn`` in the background; callbacks fire on the GUI thread.

        The worker is kept in ``self._workers`` for the duration of the task: PySide6
        does not keep a Python reference to a ``QRunnable`` handed to ``QThreadPool``,
        so a worker nobody points at is garbage collected before it ever runs.

        Returns ``None`` (and starts nothing) once the window is closing — new
        work against a half-torn-down UI is refused, never queued.
        """
        if self._closing:
            return None
        worker = Worker(fn, *args, cancel=self.cancel_event, **kwargs)
        self._workers.add(worker)
        self._busy += 1
        self.set_status(f"{description}…")
        self.setCursor(Qt.BusyCursor)

        def forget() -> None:
            self._workers.discard(worker)

        def finish(result) -> None:
            forget()
            if self._closing:
                # Shutdown in progress: the workspace may already be closed and
                # the UI is mid-teardown — keep the books, touch nothing else.
                self._busy = max(0, self._busy - 1)
                return
            self._task_finished()
            if on_done is not None:
                try:
                    on_done(result)
                except Exception as exc:  # noqa: BLE001
                    self.notify(f"Something went wrong handling the result: {exc}", "error")

        def fail(message: str) -> None:
            forget()
            if self._closing:
                self._busy = max(0, self._busy - 1)
                return
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
        if self._closing:
            return  # no status/cursor/stats writes against a closing workspace
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
        if self._closing:
            return  # workspace may already be closed; stats would raise
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
        # The settings form rebuilds an AppSettings from its widgets, so it
        # would silently drop the window geometry — carry it over instead.
        settings.window_geometry = self.settings.window_geometry or settings.window_geometry
        if settings.last_search_job_ids is None:
            settings.last_search_job_ids = self.settings.last_search_job_ids
        self.settings = settings
        self.workspace.save_settings(settings)
        self.pipeline.settings = settings
        self.pipeline.scraper.settings = settings
        self._apply_auto_refresh()

    # ------------------------------------------- background refresh / tray  #
    def _apply_auto_refresh(self) -> None:
        timer = getattr(self, "_refresh_timer", None)
        if timer is None:
            return
        timer.stop()
        if self._closing or not self.settings.auto_refresh_enabled:
            return
        minutes = max(1, self.settings.auto_refresh_minutes)
        timer.setInterval(minutes * 60_000)
        timer.start()

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(self._tray_icon(), self)
        tray.setToolTip(f"{APP_TITLE} {__version__}")
        menu = QMenu(self)
        menu.addAction("Open JAUTOMATIC", self._show_from_tray)
        menu.addAction("Refresh job boards now", self.background_refresh)
        menu.addSeparator()
        menu.addAction("Quit", self.close)
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()
        self._tray = tray

    def _tray_icon(self) -> QIcon:
        palette = th.current_theme()
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(palette["accent"]))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
        painter.setPen(QColor(palette["bg"]))
        font = painter.font()
        font.setPixelSize(34)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, 64, 64), Qt.AlignCenter, "J")
        painter.end()
        return QIcon(pixmap)

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        if self._closing:
            return
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _run_startup_maintenance(self) -> None:
        """Archive untouched applications older than settings.auto_clear_days."""
        if self._closing:
            return
        try:
            cleared = self.pipeline.auto_clear_unacted(self.profile)
        except Exception as exc:  # noqa: BLE001 - housekeeping must never block startup
            self.notify(f"Auto-clear failed: {exc}", "warning")
            return
        if cleared:
            self.notify(f"Archived {cleared} untouched application(s) older than "
                        f"{self.settings.auto_clear_days} day(s).", "info")
        self.update_meta()

    def background_refresh(self) -> None:
        """Re-scrape the enabled boards without touching the tracker.

        Used by the auto-refresh timer and the tray action.  Runs in the
        background like any other task; never imports automatically, never
        generates documents — it only updates the Search tab's results and
        raises a desktop notification when genuinely fresh roles showed up.
        """
        if self._closing or self._busy:
            return
        profile = self.profile
        settings = self.settings
        query = settings.last_search_query or (
            profile.desired_titles[0] if profile.desired_titles else "python")
        location = settings.last_search_location
        if location is None:
            location = profile.desired_locations[0] if profile.desired_locations else ""
        job_query = self.pipeline.build_query(
            query, location, sources=settings.enabled_sources,
            remote_only=settings.remote_only, min_salary=settings.min_salary,
            limit_per_source=settings.results_per_source)

        def work():
            cleared = self.pipeline.auto_clear_unacted(profile)
            outcome = self.pipeline.scraper.search(job_query,
                                                   should_cancel=self.cancel_event.is_set)
            return outcome, cleared

        def done(result) -> None:
            outcome, cleared = result
            if cleared:
                self.notify(f"Auto-cleared {cleared} untouched application(s) older than "
                            f"{settings.auto_clear_days} day(s).", "info")
            search_tab = self.tabs.get("search")
            known = {job.fingerprint for job in self.workspace.jobs()}
            if search_tab is not None and hasattr(search_tab, "show_result_outcome"):
                search_tab.show_result_outcome(outcome)
            fresh = [job for job in outcome.jobs if job.fingerprint not in known]
            self._background_notes.append(
                f"{len(outcome.jobs)} posting(s), {len(fresh)} new, "
                f"{len(outcome.errors)} source error(s)")
            self.notify(f"Refresh: {len(outcome.jobs)} postings · "
                        f"{len(fresh)} new · {len(outcome.errors)} errors.",
                        "warning" if outcome.errors else "info")
            self.set_status(
                f"Background refresh: {len(outcome.jobs)} postings, "
                f"{len(fresh)} new since last time.")
            if fresh and settings.notify_new_matches:
                self._notify_background("New roles found",
                                        f"{len(fresh)} fresh posting(s) matched your search.")
            elif outcome.errors and settings.notify_new_matches:
                first = len(outcome.errors) == 1
                self._notify_background(
                    "Refresh had issues",
                    f"{len(outcome.errors)} source(s) did not answer"
                    + (f": {outcome.errors[0]}" if first else "."))
            if hasattr(self.tabs.get("dashboard"), "refresh"):
                self.tabs["dashboard"].refresh()

        self.run_task("Refreshing job boards", work, done)

    def _notify_background(self, title: str, message: str) -> None:
        self._background_notes.append(f"{title}: {message}")
        if self._tray is not None:
            self._tray.showMessage(title, message, QSystemTrayIcon.Information, 8000)

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

    def open_interview_prep(self, row) -> QWidget:
        """Open (or raise) the interview-prep window for one application."""
        for dialog in self._previews:
            if getattr(dialog, "application_id", None) == row.application.application_id:
                dialog.raise_()
                dialog.activateWindow()
                return dialog
        dialog = InterviewPrepDialog(self, row, self)
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
        blob = self.settings.window_geometry
        # Stored as base64 in settings.json next to everything else; a
        # corrupt/foreign value just means Qt declines to restore it.
        self._geometry_restored = bool(blob) and self.restoreGeometry(
            QByteArray.fromBase64(blob.encode("ascii", "ignore")))
        theme_name = self.settings.theme or th.DEFAULT_THEME
        app = QApplication.instance()
        if app is not None:
            th.apply_theme(app, theme_name)

    def _save_geometry(self) -> None:
        blob = bytes(self.saveGeometry().toBase64().data()).decode("ascii")
        self.settings.window_geometry = blob
        try:
            self.workspace.save_settings(self.settings)
        except OSError:
            pass  # window placement is cosmetic — never let it break a quit

    def closeEvent(self, event) -> None:
        self._refresh_timer.stop()
        if self._tray is not None:
            self._tray.hide()
            self._tray = None
        self._save_geometry()
        self._closing = True
        # Cooperative shutdown, no deadline: flag closing, drop queued work,
        # let running tasks wind down (they poll cancel_event between units of
        # work), then join the pool for as long as that actually takes.
        self.cancel_event.set()
        self.pool.clear()
        self.pool.waitForDone()
        for worker in self._workers:
            # Nothing is running anymore, but queued signal deliveries may still
            # fire during teardown (e.g. while preview dialogs keep the app
            # alive) — mute them so nobody touches the closed workspace.
            worker.signals.blockSignals(True)
        self._workers.clear()
        self.workspace.close()
        super().closeEvent(event)


__all__ = ["NAV_ITEMS", "MainWindow", "Worker", "WorkerSignals"]
