"""Job search tab: query builders, ranked results, one-click material prep."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QHeaderView, QLineEdit,
                               QProgressBar, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from ..models import JobPosting
from ..services.application_pipeline import MatchResult, match_job
from . import theme as th

COLUMNS = ["Match", "Role", "Company", "Location", "Salary", "Posted", "Source"]


class JobSearchTab(QWidget):
    page_title = "Job search"
    page_subtitle = "Pull postings from every enabled board, then prepare applications"

    def __init__(self, ctx) -> None:  # noqa: ANN001 - MainWindow
        super().__init__()
        self.ctx = ctx
        self.outcome = None
        self.ranked: list[tuple[JobPosting, MatchResult]] = []
        self.source_boxes: dict[str, QCheckBox] = {}
        self._build_ui()
        self.load_defaults()

    # ------------------------------------------------------------------ UI #
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        query_card = th.Card("Search", "Leave the query empty to use the first target title "
                                       "from your profile")
        row_one = QHBoxLayout()
        row_one.setSpacing(8)
        self.query = QLineEdit()
        self.query.setPlaceholderText("python engineer, data engineer, product manager…")
        self.query.returnPressed.connect(lambda: self.start_search(False))
        self.location = QLineEdit()
        self.location.setPlaceholderText("Location (optional)")
        self.location.setMaximumWidth(220)
        self.remote_only = QCheckBox("Remote only")
        row_one.addWidget(th.label("Query", "muted"))
        row_one.addWidget(self.query, 1)
        row_one.addWidget(self.location)
        row_one.addWidget(self.remote_only)
        query_card.add_layout(row_one)

        row_two = QHBoxLayout()
        row_two.setSpacing(10)
        self.per_source = QSpinBox()
        self.per_source.setRange(5, 100)
        self.per_source.setPrefix("max ")
        self.per_source.setSuffix(" per source")
        self.min_salary = QSpinBox()
        self.min_salary.setRange(0, 2_000_000)
        self.min_salary.setSingleStep(1000)
        self.min_salary.setGroupSeparatorShown(True)
        self.min_salary.setPrefix("min salary ")
        row_two.addWidget(self.per_source)
        row_two.addWidget(self.min_salary)
        row_two.addWidget(th.label("Sources:", "muted"))
        for name, source in self.ctx.pipeline.scraper.sources.items():
            box = QCheckBox(source.label)
            box.setToolTip(source.description + (f"\n{source.homepage}" if source.homepage else ""))
            self.source_boxes[name] = box
            row_two.addWidget(box)
        row_two.addStretch(1)
        query_card.add_layout(row_two)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.search_button = th.button("Search job boards", "primary", "Fetch fresh postings",
                                       lambda: self.start_search(False))
        buttons.addWidget(self.search_button)
        self.search_import_button = th.button("Search & import", "default",
                                              "Search and add the results to your tracker",
                                              lambda: self.start_search(True))
        buttons.addWidget(self.search_import_button)
        buttons.addWidget(th.button("Import demo data", "ghost",
                                    "Add offline sample postings (no network needed)",
                                    self.import_demo))
        buttons.addWidget(th.button("Import all results", "default",
                                    "Add every current result to the tracker", self.import_all))
        buttons.addStretch(1)
        query_card.add_layout(buttons)

        self.progress = QProgressBar()
        self.progress.setObjectName("Busy")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        self.progress.setVisible(False)
        self.result_summary = th.label("No search yet — try a query or the demo data.", "muted",
                                       wrap=True)
        query_card.add(self.progress)
        query_card.add(self.result_summary)
        layout.addWidget(query_card)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        table_card = th.Card("Results", "Ranked by match score against your profile")
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.table.doubleClicked.connect(self._prepare_selected)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)          # role widens first
        for column in (0, 2, 3, 4, 5, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        table_card.add(self.table)
        table_actions = QHBoxLayout()
        table_actions.addWidget(th.button("Prepare materials", "primary",
                                          "Generate CV + letter + e-mail for the selection",
                                          self._prepare_selected))
        table_actions.addWidget(th.button("Prepare top 3", "default",
                                          "Generate materials for the three best matches",
                                          lambda: self._prepare_top(3)))
        table_actions.addWidget(th.button("Shortlist", "default", "Mark as shortlisted",
                                          self._shortlist_selected))
        table_actions.addWidget(th.button("Open posting", "ghost", "", self._open_selected))
        table_actions.addStretch(1)
        table_card.add_layout(table_actions)
        splitter.addWidget(table_card)

        detail_card = th.Card("Details")
        self.detail_title = th.label("Select a posting", "title", wrap=True)
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
                                  "Generate the CV, cover letter and e-mail for this posting",
                                  self._prepare_selected))
        detail_actions = QHBoxLayout()
        detail_actions.setSpacing(6)
        detail_actions.addWidget(th.button("Open posting", "default", "", self._open_selected))
        detail_actions.addWidget(th.button("Copy link", "ghost", "", self._copy_link))
        detail_actions.addStretch(1)
        detail_card.add_layout(detail_actions)
        detail_card.setMinimumWidth(380)
        splitter.addWidget(detail_card)
        splitter.setSizes([860, 430])

        self.ctx.add_header_action("search", th.button("Search job boards", "primary", "",
                                             lambda: self.start_search(False)))

    # ---------------------------------------------------------- defaults   #
    def load_defaults(self) -> None:
        settings = self.ctx.settings
        profile = self.ctx.profile
        self.per_source.setValue(settings.results_per_source)
        self.min_salary.setValue(settings.min_salary)
        self.remote_only.setChecked(settings.remote_only)
        enabled = set(settings.enabled_sources)
        for name, box in self.source_boxes.items():
            box.setChecked(name in enabled)
        if not self.query.text().strip():
            default = settings.last_search_query or (profile.desired_titles[0]
                                                     if profile.desired_titles else "")
            self.query.setText(default)
        if not self.location.text().strip() and profile.desired_locations:
            self.location.setText(profile.desired_locations[0])

    def refresh(self) -> None:
        self.load_defaults()
        self._mark_tracked()

    # ------------------------------------------------------------ search  #
    def start_search(self, import_results: bool) -> None:
        query_text = self.query.text().strip()
        if not query_text:
            profile = self.ctx.profile
            query_text = (profile.desired_titles[0] if profile.desired_titles else "python")
            self.query.setText(query_text)
        sources = [name for name, box in self.source_boxes.items() if box.isChecked()]
        if not sources:
            sources = ["sample"]
            self.ctx.notify("No source selected — using the offline demo source.", "warning")

        self.ctx.settings.last_search_query = query_text
        self.ctx.save_settings(self.ctx.settings)

        self.progress.setVisible(True)
        self.search_button.setEnabled(False)
        self.search_import_button.setEnabled(False)
        self.result_summary.setText("Contacting job boards…")

        query = self.ctx.pipeline.build_query(
            query_text, self.location.text().strip(), sources=sources,
            remote_only=self.remote_only.isChecked(), min_salary=self.min_salary.value(),
            limit_per_source=self.per_source.value())

        def work():  # noqa: ANN202
            cancel = self.ctx.cancel_event.is_set
            outcome = self.ctx.pipeline.scraper.search(query, should_cancel=cancel)
            if cancel():
                return outcome, []  # closing: skip the import against the workspace
            return outcome, self.ctx.pipeline.import_jobs(outcome.jobs)

        def done(result) -> None:  # noqa: ANN001
            self.progress.setVisible(False)
            self.search_button.setEnabled(True)
            self.search_import_button.setEnabled(True)
            outcome, created = result
            self.outcome = outcome
            self.ranked = [(job, match_job(self.ctx.profile, job, self.ctx.settings))
                           for job in outcome.jobs]
            self._fill_table()
            message = outcome.summary() + f" · {len(created)} new in tracker"
            self.result_summary.setText(message)
            level = "warning" if outcome.errors else "success"
            if not outcome.jobs:
                level = "warning"
            self.ctx.notify(message, level)
            self.ctx.update_meta()
            for tab in ("dashboard", "applications"):
                if hasattr(self.ctx.tabs.get(tab), "refresh"):
                    self.ctx.tabs[tab].refresh()

        def failed(_message: str) -> None:
            self.progress.setVisible(False)
            self.search_button.setEnabled(True)
            self.search_import_button.setEnabled(True)

        self.ctx.run_task("Searching job boards", work, done, failed)

    def import_demo(self) -> None:
        query = self.query.text().strip() or "python"

        def work():  # noqa: ANN202
            return self.ctx.pipeline.search_and_import(query, sources=["sample"],
                                                       limit_per_source=self.per_source.value())

        def done(result) -> None:  # noqa: ANN001
            outcome, created = result
            self.outcome = outcome
            self.ranked = [(job, match_job(self.ctx.profile, job, self.ctx.settings))
                           for job in outcome.jobs]
            self._fill_table()
            self.result_summary.setText(f"Demo data: {len(outcome.jobs)} posting(s), "
                                        f"{len(created)} new in tracker.")
            self.ctx.notify("Demo postings imported.", "success")
            self.ctx.tabs["dashboard"].refresh()

        self.ctx.run_task("Importing demo postings", work, done)

    def import_all(self) -> None:
        if not self.ranked:
            self.ctx.notify("Nothing to import yet — run a search first.", "warning")
            return
        jobs = [job for job, _ in self.ranked]
        created = self.ctx.pipeline.import_jobs(jobs)
        self._mark_tracked()
        self.ctx.notify(f"Imported {len(jobs)} posting(s); {len(created)} new in the tracker.",
                        "success")
        self.ctx.tabs["dashboard"].refresh()

    # ------------------------------------------------------------- table  #
    def _fill_table(self) -> None:
        rows = self.ranked[:400]
        self.table.setRowCount(len(rows))
        tracked = {app.job_id for app in self.ctx.workspace.applications()}
        for index, (job, match) in enumerate(rows):
            is_tracked = job.job_id in tracked
            match_item = QTableWidgetItem(f"{match.score}")
            match_item.setTextAlignment(Qt.AlignCenter)
            match_item.setForeground(QColor(th.ScoreBar.score_color(match.score)))
            match_item.setToolTip(" · ".join(match.reasons) or "no reasons recorded")
            match_item.setData(Qt.UserRole, index)
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
            if self.table.item(row, 0) is None:
                continue
            job = self._job_for_row(row)
            if job is None:
                continue
            is_tracked = job.job_id in tracked
            item = QTableWidgetItem(f"✔  {job.title}" if is_tracked else job.title)
            if is_tracked:
                item.setToolTip("Already in your tracker")
            self.table.setItem(row, 1, item)

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

    def _selected_job(self) -> tuple[JobPosting, MatchResult] | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        row = rows[0].row()
        job, match = self._job_for_row(row), self._match_for_row(row)
        return (job, match) if job else None

    def _show_selected(self) -> None:
        selected = self._selected_job()
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
        body = job.description or "This posting has no description text."
        if job.url:
            body += f"<p><a href='{job.url}'>Open the original posting</a></p>"
        self.description.setHtml(f"<p>{body.replace(chr(10), '<br>')}</p>")

    # ------------------------------------------------------------ actions #
    def _prepare_selected(self) -> None:
        selected = self._selected_job()
        if not selected:
            self.ctx.notify("Select a posting first.", "warning")
            return
        job, _match = selected
        self._prepare_jobs([job])

    def _prepare_top(self, count: int) -> None:
        if not self.ranked:
            self.ctx.notify("Run a search first.", "warning")
            return
        candidates = [job for job, match in self.ranked
                      if match.score >= self.ctx.settings.autopilot_min_score][:count]
        if not candidates:
            candidates = [job for job, _ in self.ranked[:count]]
        self._prepare_jobs(candidates)

    def _prepare_jobs(self, jobs: list[JobPosting]) -> None:
        profile = self.ctx.profile

        def work():  # noqa: ANN202
            cancel = self.ctx.cancel_event.is_set
            results = []
            for job in jobs:
                if cancel():
                    break  # closing: hand back the partial batch
                application = self.ctx.pipeline.ensure_application(job)
                results.append(self.ctx.pipeline.prepare(application, profile))
            return results

        def done(materials) -> None:  # noqa: ANN001
            self._mark_tracked()
            self.ctx.notify(f"Materials generated for {len(materials)} posting(s).", "success")
            self.ctx.tabs["dashboard"].refresh()
            self.ctx.tabs["applications"].refresh()
            self.ctx.go_to("applications")
            if materials and materials[0].cv and materials[0].cv.text:
                first = materials[0]
                self.ctx.open_preview(f"CV · {first.job.title}", first.cv.text, first.cv.path)

        self.ctx.run_task(f"Generating materials for {len(jobs)} posting(s)", work, done)

    def _shortlist_selected(self) -> None:
        selected = self._selected_job()
        if not selected:
            self.ctx.notify("Select a posting first.", "warning")
            return
        job, _match = selected
        application = self.ctx.pipeline.ensure_application(job)
        from ..models import ApplicationStatus
        self.ctx.pipeline.set_status(application, ApplicationStatus.SHORTLISTED,
                                     "shortlisted from search results")
        self._mark_tracked()
        self.ctx.notify(f"Shortlisted {job.title} at {job.company}.", "success")

    def _open_selected(self) -> None:
        selected = self._selected_job()
        if not selected:
            self.ctx.notify("Select a posting first.", "warning")
            return
        job, _match = selected
        if job.url:
            th.open_in_browser(job.url)
        else:
            self.ctx.notify("This posting has no URL attached.", "warning")

    def _copy_link(self) -> None:
        selected = self._selected_job()
        if not selected:
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(selected[0].url)
        self.ctx.notify("Posting URL copied to the clipboard.", "info")


__all__ = ["JobSearchTab", "COLUMNS"]
