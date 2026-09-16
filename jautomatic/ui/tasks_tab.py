"""Tasks tab: microtask / gig search with an explicit minimum-pay (USD) filter.

Live microtask portals (Remotasks, Clickworker, Outlier, Appen…) hide task lists
behind sign-in and have no public API, so this tab searches an offline demo gig
feed and lets you track gigs you paste in from anywhere (the same link importer
the job search uses).  The "$X min" control filters results to tasks whose
advertised per-task pay is at least X USD - off by default, $10 already set.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..models import JobPosting
from ..services.application_pipeline import MatchResult, match_job, min_pay_ok
from ..services.job_scraper import JobScraper, SearchQuery, default_task_sources
from . import theme as th
from .job_search_tab import COLUMNS


class TasksTab(QWidget):
    page_title = "Tasks"
    page_subtitle = "Remote microtasks and gigs, filtered by minimum USD pay"

    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx
        self.outcome = None
        self.ranked: list[tuple[JobPosting, MatchResult]] = []
        self._build_ui()
        self.load_defaults()

    # ------------------------------------------------------------------ UI #
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        query_card = th.Card("Search tasks",
                             "Offline demo gig feed + track any task you paste as a link")
        row_one = QHBoxLayout()
        row_one.setSpacing(8)
        self.query = QLineEdit()
        self.query.setPlaceholderText("data labeling, transcription, content moderation…")
        self.query.returnPressed.connect(lambda: self.start_search())
        self.min_pay = QSpinBox()
        self.min_pay.setRange(0, 1000)
        self.min_pay.setSingleStep(1)
        self.min_pay.setPrefix("$")
        self.min_pay.setSuffix(" min pay")
        self.min_pay.setToolTip("Hide tasks whose posted per-task pay is below this USD "
                                "amount (0 shows everything)")
        self.min_pay.valueChanged.connect(self._on_min_pay_changed)
        self.limit = QSpinBox()
        self.limit.setRange(5, 100)
        self.limit.setPrefix("max ")
        self.limit.setSuffix(" results")
        row_one.addWidget(th.label("What kind of task?", "muted"))
        row_one.addWidget(self.query, 1)
        row_one.addWidget(self.min_pay)
        row_one.addWidget(self.limit)
        query_card.add_layout(row_one)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.search_button = th.button("Search tasks", "primary", "Fetch fresh task listings",
                                       lambda: self.start_search())
        buttons.addWidget(self.search_button)
        buttons.addWidget(th.button("Import all results", "default",
                                    "Add every current task to the tracker",
                                    self.import_all))
        buttons.addStretch(1)
        query_card.add_layout(buttons)

        self.progress = QProgressBar()
        self.progress.setObjectName("Busy")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        self.progress.setVisible(False)
        self.result_summary = th.label("No task search yet — try a query or paste a task link.",
                                       "muted", wrap=True)
        query_card.add(self.progress)
        query_card.add(self.result_summary)

        url_row_sep = th.hline()
        query_card.add(url_row_sep)
        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "Or paste an individual gig / task URL from anywhere to track it…")
        self.url_input.returnPressed.connect(self.track_url)
        self.import_url_button = th.button("Track from URL", "primary",
                                           "Read the pasted link and add it to your tracker",
                                           self.track_url)
        url_row.addWidget(self.url_input, 1)
        url_row.addWidget(self.import_url_button)
        query_card.add_layout(url_row)
        layout.addWidget(query_card)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        table_card = th.Card("Task results", "Ranked by match against your profile")
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.table.doubleClicked.connect(self._prepare_selected)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (0, 2, 3, 4, 5, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        table_card.add(self.table)
        table_actions = QHBoxLayout()
        table_actions.addWidget(th.button("Prepare materials", "primary",
                                          "Generate CV + letter + e-mail for the selection",
                                          self._prepare_selected))
        table_actions.addWidget(th.button("Track selected", "default",
                                          "Add the selected task to your tracker",
                                          self._track_selected))
        table_actions.addWidget(th.button("Clear", "default",
                                          "Archive a task you can't do (kept in the "
                                          "database/history)", self._clear_selected))
        table_actions.addWidget(th.button("Open task", "ghost", "", self._open_selected))
        table_actions.addStretch(1)
        table_card.add_layout(table_actions)
        splitter.addWidget(table_card)

        detail_card = th.Card("Details")
        self.detail_title = th.label("Select a task", "title", wrap=True)
        self.detail_meta = th.label("", "small", wrap=True)
        self.score_bar = th.ScoreBar(0)
        self.score_bar.setVisible(False)
        self.match_summary = th.label("", "muted", wrap=True)
        self.tags_line = th.label("", "small", wrap=True)
        self.description = QTextBrowser()
        self.description.setOpenExternalLinks(True)
        detail_card.add(self.detail_title)
        detail_card.add(self.detail_meta)
        detail_card.add(self.score_bar)
        detail_card.add(self.match_summary)
        detail_card.add(self.tags_line)
        detail_card.add(self.description)
        detail_card.add(th.button("Prepare materials", "primary",
                                  "Generate the CV, cover letter and e-mail for this task",
                                  self._prepare_selected))
        detail_actions = QHBoxLayout()
        detail_actions.setSpacing(6)
        detail_actions.addWidget(th.button("Open task", "default", "", self._open_selected))
        detail_actions.addWidget(th.button("Copy link", "ghost", "", self._copy_link))
        detail_actions.addStretch(1)
        detail_card.add_layout(detail_actions)
        detail_card.setMinimumWidth(380)
        splitter.addWidget(detail_card)
        splitter.setSizes([860, 430])

        self.ctx.add_header_action("tasks", th.button("Search tasks", "primary", "",
                                                      lambda: self.start_search()))

    # ---------------------------------------------------------- defaults   #
    def load_defaults(self) -> None:
        settings = self.ctx.settings
        self.limit.setValue(settings.results_per_source)
        self.min_pay.setValue(settings.min_pay_usd)
        if not self.query.text().strip():
            default = settings.last_search_query or (self.ctx.profile.desired_titles[0]
                                                     if self.ctx.profile.desired_titles else "")
            self.query.setText(default or "data labeling")

    def refresh(self) -> None:
        self.load_defaults()
        self._mark_tracked()
        if not self.ranked:
            self._show_tracked()

    def _show_tracked(self) -> None:
        """Populate the task table from tracked task-feed postings (no live search yet)."""
        from ..services.job_scraper import TaskSource
        rows = [row for row in self.ctx.pipeline.tracker(self.ctx.profile)
                if row.status.is_active and row.job.source == TaskSource.name]
        rows = rows[:400]
        if not rows:
            return
        self.ranked = [(row.job, row.match) for row in rows]
        self._fill_table()
        self.result_summary.setText(
            f"Showing {len(rows)} tracked task(s) from your queue — run a search for "
            f"fresh listings.{self._filter_note()}")

    def _on_min_pay_changed(self, value: int) -> None:
        self.ctx.settings.min_pay_usd = value
        self.ctx.save_settings(self.ctx.settings)
        if not self.ranked:
            self.result_summary.setText(
                f"Pay filter: tasks advertised below ${value} USD are hidden — run a search."
                if value else "Pay filter off — every task is shown. Run a search.")
            return
        self._fill_table()
        self.result_summary.setText(f"Filtered to tasks paying ≥ ${value} USD."
                                    f"{self._filter_note()}")

    def _filter_note(self) -> str:
        floor = self.min_pay.value()
        if floor <= 0 or not self.ranked:
            return ""
        shown = sum(1 for job, _ in self.ranked if min_pay_ok(job, floor))
        return f" Showing {shown} of {len(self.ranked)} ranked tasks."

    def _visible_rows(self) -> list[tuple[int, JobPosting, MatchResult]]:
        floor = self.min_pay.value()
        rows = [(index, job, match) for index, (job, match) in enumerate(self.ranked)
                if floor <= 0 or min_pay_ok(job, floor)]
        return rows[:400]

    # ------------------------------------------------------------ search  #
    def start_search(self) -> None:
        query_text = self.query.text().strip()
        if not query_text:
            query_text = (self.ctx.profile.desired_titles[0]
                          if self.ctx.profile.desired_titles else "data labeling")
            self.query.setText(query_text)
        self.ctx.settings.last_search_query = query_text
        self.ctx.save_settings(self.ctx.settings)

        self.progress.setVisible(True)
        self.search_button.setEnabled(False)
        self.result_summary.setText("Searching the task feed…")

        query = SearchQuery(text=query_text, remote_only=True,
                            limit_per_source=self.limit.value(), sources=["tasks"],
                            exclude_keywords=self.ctx.settings.excluded_keyword_list)

        def work():
            scraper = JobScraper(self.ctx.settings, sources=default_task_sources())
            cancel = self.ctx.cancel_event.is_set
            outcome = scraper.search(query, should_cancel=cancel)
            if cancel():
                return outcome, []  # closing: skip the import against the workspace
            floor = self.min_pay.value()
            keep = [job for job in outcome.jobs if min_pay_ok(job, floor)]
            return outcome, self.ctx.pipeline.import_jobs(keep)

        def done(result):
            self.progress.setVisible(False)
            self.search_button.setEnabled(True)
            outcome, created = result
            self.outcome = outcome
            self.ranked = [(job, match_job(self.ctx.profile, job, self.ctx.settings))
                           for job in outcome.jobs]
            self._fill_table()
            message = outcome.summary() + f" · {len(created)} new in tracker" + self._filter_note()
            self.result_summary.setText(message)
            self.ctx.notify(message, "warning" if outcome.errors else "success")
            self.ctx.update_meta()
            if hasattr(self.ctx.tabs.get("dashboard"), "refresh"):
                self.ctx.tabs["dashboard"].refresh()

        def failed(_message: str) -> None:
            self.progress.setVisible(False)
            self.search_button.setEnabled(True)

        self.ctx.run_task("Searching task feed", work, done, failed)

    def import_all(self) -> None:
        if not self.ranked:
            self.ctx.notify("Nothing to import yet — run a task search first.", "warning")
            return
        rows = self._visible_rows()
        if not rows:
            self.ctx.notify("No task meets the current minimum pay filter.", "warning")
            return
        jobs = [job for _index, job, _match in rows]
        created = self.ctx.pipeline.import_jobs(jobs)
        self._mark_tracked()
        self.ctx.notify(f"Imported {len(jobs)} task(s); {len(created)} new in the tracker.",
                        "success")
        if hasattr(self.ctx.tabs.get("dashboard"), "refresh"):
            self.ctx.tabs["dashboard"].refresh()

    def track_url(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            self.ctx.notify("Paste a task URL first.", "warning")
            return
        self.import_url_button.setEnabled(False)

        def work():
            try:
                return self.ctx.pipeline.import_from_url(url)
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(f"no readable task text on that page ({exc.__class__.__name__})"
                                 ) from exc

        def done(result):
            self.import_url_button.setEnabled(True)
            _application, created = result
            message = ("Tracked the pasted link." if created else "That link is already in "
                        "your tracker.")
            self.ctx.notify(message, "success" if created else "info")
            self.url_input.clear()
            if hasattr(self.ctx.tabs.get("dashboard"), "refresh"):
                self.ctx.tabs["dashboard"].refresh()
            if hasattr(self.ctx.tabs.get("applications"), "refresh"):
                self.ctx.tabs["applications"].refresh()

        def failed(message: str) -> None:
            self.import_url_button.setEnabled(True)
            self.ctx.notify(f"Could not read that link — {message}", "error")

        self.ctx.run_task("Reading the pasted link", work, done, failed)

    # ------------------------------------------------------------- table  #
    def _fill_table(self) -> None:
        rows = self._visible_rows()
        self.table.setRowCount(len(rows))
        tracked = {app.job_id for app in self.ctx.workspace.applications()}
        for index, (rank_index, job, match) in enumerate(rows):
            is_tracked = job.job_id in tracked
            match_item = QTableWidgetItem(f"{match.score}")
            match_item.setTextAlignment(Qt.AlignCenter)
            match_item.setForeground(QColor(th.ScoreBar.score_color(match.score)))
            match_item.setToolTip(" · ".join(match.reasons) or "no reasons recorded")
            match_item.setData(Qt.UserRole, rank_index)
            self.table.setItem(index, 0, match_item)
            title_item = QTableWidgetItem(f"✔  {job.title}" if is_tracked else job.title)
            if is_tracked:
                title_item.setToolTip("Already in your tracker")
            self.table.setItem(index, 1, title_item)
            self.table.setItem(index, 2, QTableWidgetItem(job.company))
            self.table.setItem(index, 3, QTableWidgetItem(job.short_location))
            salary_item = QTableWidgetItem(job.salary_short)
            salary_item.setToolTip(job.salary_text)
            self.table.setItem(index, 4, salary_item)
            self.table.setItem(index, 5, QTableWidgetItem(job.posted_text))
            self.table.setItem(index, 6, QTableWidgetItem(job.source))
        self.table.resizeRowsToContents()
        if rows:
            self.table.selectRow(0)

    def _mark_tracked(self) -> None:
        tracked = {app.job_id for app in self.ctx.workspace.applications()}
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            job = self._job_for_row(row)
            if job is None:
                continue
            is_tracked = job.job_id in tracked
            title_item = QTableWidgetItem(f"✔  {job.title}" if is_tracked else job.title)
            if is_tracked:
                title_item.setToolTip("Already in your tracker")
            self.table.setItem(row, 1, title_item)

    def _job_for_row(self, row: int) -> JobPosting | None:
        item = self.table.item(row, 0)
        if item is None:
            return None
        index = item.data(Qt.UserRole)
        if isinstance(index, int) and 0 <= index < len(self.ranked):
            return self.ranked[index][0]
        return None

    def _match_for_row(self, row: int) -> MatchResult | None:
        item = self.table.item(row, 0)
        if item is None:
            return None
        index = item.data(Qt.UserRole)
        if isinstance(index, int) and 0 <= index < len(self.ranked):
            return self.ranked[index][1]
        return None

    def _selected_task(self) -> tuple[JobPosting, MatchResult] | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        job, match = self._job_for_row(rows[0].row()), self._match_for_row(rows[0].row())
        return (job, match) if job else None

    def _show_selected(self) -> None:
        selected = self._selected_task()
        if not selected:
            return
        job, match = selected
        self.detail_title.setText(f"{job.title} · {job.company}")
        self.detail_meta.setText(
            f"{job.display_location} · {job.salary_text} · posted {job.posted_text} · "
            f"via {job.source}")
        self.score_bar.setVisible(True)
        self.score_bar.set_score(match.score)
        self.match_summary.setText(f"Match {match.score}/100 ({match.grade}) — "
                                   + "; ".join(match.reasons[:3]))
        self.tags_line.setText("Tags: " + (", ".join(job.tags) if job.tags else "none"))
        body = job.description or "This task has no description text."
        if job.url:
            body += f"<p><a href='{job.url}'>Open the original posting</a></p>"
        self.description.setHtml(f"<p>{body.replace(chr(10), '<br>')}</p>")

    # ------------------------------------------------------------ actions #
    def _prepare_selected(self) -> None:
        selected = self._selected_task()
        if not selected:
            self.ctx.notify("Select a task first.", "warning")
            return
        job, _match = selected
        profile = self.ctx.profile

        def work():
            cancel = self.ctx.cancel_event.is_set
            application = self.ctx.pipeline.ensure_application(job)
            if cancel():
                return []
            return [self.ctx.pipeline.prepare(application, profile)]

        def done(materials):
            self._mark_tracked()
            self.ctx.notify(f"Materials generated for {len(materials)} task(s).", "success")
            if hasattr(self.ctx.tabs.get("dashboard"), "refresh"):
                self.ctx.tabs["dashboard"].refresh()
            if hasattr(self.ctx.tabs.get("applications"), "refresh"):
                self.ctx.tabs["applications"].refresh()
            if materials and materials[0].cv and materials[0].cv.text:
                first = materials[0]
                self.ctx.open_preview(f"CV · {first.job.title}", first.cv.text, first.cv.path)

        self.ctx.run_task("Generating materials", work, done)

    def _track_selected(self) -> None:
        selected = self._selected_task()
        if not selected:
            self.ctx.notify("Select a task first.", "warning")
            return
        job, _match = selected
        self.ctx.pipeline.ensure_application(job)
        self._mark_tracked()
        self.ctx.notify(f"Tracked {job.title}.", "success")
        if hasattr(self.ctx.tabs.get("dashboard"), "refresh"):
            self.ctx.tabs["dashboard"].refresh()

    def _clear_selected(self) -> None:
        selected = self._selected_task()
        if not selected:
            self.ctx.notify("Select a task first.", "warning")
            return
        job, _match = selected
        application = self.ctx.pipeline.ensure_application(job)
        self.ctx.pipeline.clear_application(application)
        self._mark_tracked()
        self.ctx.notify(f"Cleared {job.title} from the queue.", "success")
        if hasattr(self.ctx.tabs.get("dashboard"), "refresh"):
            self.ctx.tabs["dashboard"].refresh()
        if hasattr(self.ctx.tabs.get("applications"), "refresh"):
            self.ctx.tabs["applications"].refresh()

    def _open_selected(self) -> None:
        selected = self._selected_task()
        if not selected:
            self.ctx.notify("Select a task first.", "warning")
            return
        url = selected[0].url
        if url:
            th.open_in_browser(url)
        else:
            self.ctx.notify("This task has no URL attached.", "warning")

    def _copy_link(self) -> None:
        selected = self._selected_task()
        if not selected:
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(selected[0].url)
        self.ctx.notify("Task URL copied to the clipboard.", "info")


__all__ = ["TasksTab"]