"""Job search tab: query builders, ranked results, one-click material prep."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..models import JobPosting
from ..services.application_pipeline import MatchResult, match_job
from . import theme as th

COLUMNS = ["Match", "Role", "Company", "Location", "Salary", "Posted", "Source", "Eligibility"]


class JobSearchTab(QWidget):
    page_title = "Job search"
    page_subtitle = "Pull postings from every enabled board, then prepare applications"

    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx
        self.outcome = None
        self.ranked: list[tuple[JobPosting, MatchResult]] = []
        self.source_boxes: dict[str, QCheckBox] = {}
        self._build_ui()
        self.load_defaults()

    # ------------------------------------------------------------------ UI #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(page_scroll)
        content = QWidget()
        content.setObjectName("SearchContent")
        page_scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        query_card = th.Card("Find your next opportunity",
                             "Search job boards. Compare your qualifications. Apply with confidence.")
        query_card.setObjectName("SearchHero")
        self.threshold_badge = th.label("70% MATCH TARGET")
        self.threshold_badge.setObjectName("MatchBadge")
        query_card.add_action(self.threshold_badge)
        row_one = QHBoxLayout()
        row_one.setSpacing(8)
        self.query = QLineEdit()
        self.query.setPlaceholderText("logistics, procurement, warehouse, supply chain…")
        self.query.returnPressed.connect(lambda: self.start_search(False))
        self.location = QLineEdit()
        self.location.setPlaceholderText("Africa; UAE; or a city")
        self.location.setToolTip("Use Africa, UAE, a country or a city. Separate destinations with semicolons.")
        self.location.setMaximumWidth(220)
        self.remote_only = QCheckBox("Remote only")
        row_one.addWidget(th.label("Query", "muted"))
        row_one.addWidget(self.query, 1)
        row_one.addWidget(self.location)
        row_one.addWidget(self.remote_only)
        self.search_button = th.button("Search jobs", "primary", "Fetch fresh postings",
                                       lambda: self.start_search(False))
        row_one.addWidget(self.search_button)
        query_card.add_layout(row_one)
        coverage = QHBoxLayout()
        coverage.addWidget(th.button("Africa + UAE logistics", "default",
                                     "Enable regional feeds and search local logistics roles",
                                     self.use_regional_search))
        coverage.addWidget(th.label("Logistics also matches supply chain, procurement, warehouse, "
                                    "freight and transport in fetched postings.", "small", wrap=True), 1)
        query_card.add_layout(coverage)

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
        self.min_match = QSpinBox()
        self.min_match.setRange(0, 100)
        self.min_match.setPrefix("Eligible at ")
        self.min_match.setSuffix("%")
        self.min_match.setToolTip("Profile match needed for automatic qualification. "
                                  "The default is 70%. Lower matches remain visible for review.")
        self.min_match.valueChanged.connect(self._on_min_match_changed)
        self.auto_track = QCheckBox("Auto-queue eligible jobs")
        self.auto_track.setToolTip("After a search, results at or above the qualification "
                                   "bar are added to your application queue automatically.")
        self.auto_track.toggled.connect(self._on_auto_track_changed)
        row_two.addWidget(self.min_match)
        self.eligible_only = QCheckBox("Eligible only")
        self.eligible_only.setToolTip("Show only jobs meeting your profile-match threshold.")
        self.eligible_only.toggled.connect(lambda _: self._fill_table())
        row_two.addWidget(self.eligible_only)
        row_two.addWidget(self.auto_track)
        row_two.addStretch(1)
        options_button = th.button("Search options", "ghost", "Sources, salary and import tools")
        options_button.setCheckable(True)
        row_two.addWidget(options_button)
        query_card.add_layout(row_two)

        self.search_options = QWidget()
        options = QVBoxLayout(self.search_options)
        options.setContentsMargins(0, 6, 0, 0)
        limits = QHBoxLayout()
        limits.addWidget(self.per_source)
        limits.addWidget(self.min_salary)
        limits.addStretch(1)
        options.addLayout(limits)
        sources_grid = QGridLayout()
        for index, (name, source) in enumerate(self.ctx.pipeline.scraper.sources.items()):
            box = QCheckBox(source.label)
            box.setToolTip(source.description + (f"\n{source.homepage}" if source.homepage else ""))
            self.source_boxes[name] = box
            sources_grid.addWidget(box, index // 4, index % 4)
        options.addLayout(sources_grid)

        buttons = QGridLayout()
        buttons.setSpacing(8)
        self.search_import_button = th.button("Search & import", "default",
                                              "Search and add the results to your tracker",
                                              lambda: self.start_search(True))
        buttons.addWidget(self.search_import_button, 0, 0)
        buttons.addWidget(th.button("Import demo data", "ghost",
                                    "Add offline sample postings (no network needed)",
                                    self.import_demo), 0, 1)
        buttons.addWidget(th.button("Import all results", "default",
                                    "Add every current result to the tracker", self.import_all), 0, 2)
        buttons.addWidget(th.button("LinkedIn (browser)", "ghost",
                                    "Open your query on linkedin.com — no public API, so "
                                    "the app hands the search to your browser; Easy Apply "
                                    "is applied as a built-in filter.",
                                    self.open_linkedin_search), 1, 0)
        options.addLayout(buttons)
        query_card.add(self.search_options)
        self.search_options.hide()
        options_button.toggled.connect(self.search_options.setVisible)

        self.progress = QProgressBar()
        self.progress.setObjectName("Busy")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        self.progress.setVisible(False)
        self.result_summary = th.label("No search yet — try a query or the demo data.", "muted",
                                       wrap=True)
        self.source_summary = th.label("", "small", wrap=True)
        query_card.add(self.progress)
        query_card.add(self.result_summary)
        query_card.add(self.source_summary)

        browser_row = QHBoxLayout()
        browser_row.addWidget(th.label("More websites", "muted"))
        self.browser_board = QComboBox()
        self.browser_board.addItems(["LinkedIn Africa", "LinkedIn UAE", "Bayt UAE", "GulfTalent UAE",
                                     "BrighterMonday Kenya", "BrighterMonday Uganda", "Jobberman Nigeria"])
        browser_row.addWidget(self.browser_board)
        browser_row.addWidget(th.button("Open website", "default", "Search in your own browser",
                                        self.open_regional_website))
        browser_row.addWidget(th.label("Browser results are imported using the tools below.",
                                       "small", wrap=True), 1)
        query_card.add_layout(browser_row)

        url_row_sep = th.hline()
        query_card.add(url_row_sep)
        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "Or paste a job URL from anywhere (Greenhouse, Workday, LinkedIn, a company site)…")
        self.url_input.returnPressed.connect(self.import_url)
        self.import_url_button = th.button(
            "Track from URL", "primary",
            "Read the pasted link and add it to your tracker", self.import_url)
        url_row.addWidget(self.url_input, 1)
        url_row.addWidget(self.import_url_button)
        url_row.addWidget(th.button("Paste job details", "default",
                                    "Copy a LinkedIn or other posting when URL import is unavailable",
                                    self.import_job_details))
        query_card.add_layout(url_row)
        layout.addWidget(query_card)

        splitter = self.results_splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        table_card = th.Card("Your job matches", "All results, ranked against your saved profile")
        self.result_counts = th.label("No results yet", "small", wrap=True)
        table_card.add(self.result_counts)
        self.empty_results = th.label("Your next opportunity starts with a search.\n"
                                      "Add your qualifications in Profile for accurate matches.",
                                      "muted", wrap=True)
        table_card.add(self.empty_results)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setMinimumSectionSize(46)
        self.table.setMinimumHeight(160)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.table.doubleClicked.connect(self._prepare_selected)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)          # role widens first
        header.setMinimumSectionSize(65)
        for column in (0, 2, 3, 4, 5, 6, 7):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.table.setColumnWidth(column, 100 if column != 7 else 135)
        # Keep the primary comparison readable; full location/pay/date are in Details.
        for column in (3, 4, 5):
            self.table.setColumnHidden(column, True)
        self.table.setColumnWidth(0, 72)
        self.table.setColumnWidth(2, 130)
        self.table.setColumnWidth(7, 110)
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
        secondary_actions = QHBoxLayout()
        secondary_actions.addWidget(th.button("Clear", "default",
                                          "Archive a posting you can't apply for "
                                          "(kept in the database/history)",
                                          self._clear_selected))
        secondary_actions.addWidget(th.button("Open posting", "ghost", "", self._open_selected))
        secondary_actions.addStretch(1)
        table_actions.addStretch(1)
        table_card.add_layout(table_actions)
        table_card.add_layout(secondary_actions)
        splitter.addWidget(table_card)

        detail_card = th.Card("Details")
        self.detail_title = th.label("Select a posting", "title", wrap=True)
        self.detail_meta = th.label("", "small", wrap=True)
        self.score_bar = th.ScoreBar(0)
        self.score_bar.setVisible(False)
        self.match_summary = th.label("", "muted", wrap=True)
        self.eligibility_label = th.label("", wrap=True)
        self.eligibility_label.setObjectName("MatchBadge")
        self.tags_line = th.label("", "small", wrap=True)
        self.description = QTextBrowser()
        self.description.setOpenExternalLinks(True)
        detail_card.add(self.detail_title)
        detail_card.add(self.detail_meta)
        detail_card.add(self.score_bar)
        detail_card.add(self.eligibility_label)
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
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QScrollArea.NoFrame)
        detail_scroll.setWidget(detail_card)
        detail_scroll.setMinimumWidth(280)
        detail_scroll.setMaximumWidth(440)
        self.detail_card = detail_scroll
        self.description.setMinimumHeight(140)
        splitter.addWidget(detail_scroll)
        splitter.setMinimumHeight(500)
        splitter.setSizes([860, 430])

        self.ctx.add_header_action("search", th.button("Search job boards", "primary", "",
                                             lambda: self.start_search(False)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        horizontal = self.width() >= 1050
        orientation = Qt.Horizontal if horizontal else Qt.Vertical
        if self.results_splitter.orientation() != orientation:
            self.results_splitter.setOrientation(orientation)
            self.detail_card.setMaximumWidth(440 if horizontal else 16777215)
            self.results_splitter.setSizes([650, 350] if horizontal else [300, 250])
        self.results_splitter.setMinimumHeight(500 if horizontal else 800)

    # ---------------------------------------------------------- defaults   #
    def load_defaults(self) -> None:
        settings = self.ctx.settings
        profile = self.ctx.profile
        self.per_source.setValue(settings.results_per_source)
        self.min_salary.setValue(settings.min_salary)
        self.min_match.blockSignals(True)
        self.auto_track.blockSignals(True)
        self.min_match.setValue(settings.min_match_score)
        self.auto_track.setChecked(settings.auto_track_qualified)
        self.min_match.blockSignals(False)
        self.auto_track.blockSignals(False)
        self.threshold_badge.setText(f"{self.min_match.value()}% MATCH TARGET")
        self.remote_only.setChecked(settings.remote_only)
        enabled = set(settings.enabled_sources)
        for name, box in self.source_boxes.items():
            box.setChecked(name in enabled)
        if not self.query.text().strip():
            default = settings.last_search_query or (profile.desired_titles[0]
                                                     if profile.desired_titles else "")
            self.query.setText(default)
        if not self.location.text().strip():
            if settings.last_search_location is not None:
                self.location.setText(settings.last_search_location)
            elif profile.desired_locations:
                self.location.setText(profile.desired_locations[0])

    def refresh(self) -> None:
        self.load_defaults()
        if not self.ranked:
            self._show_tracked()
        else:
            self.ranked = [(job, match_job(self.ctx.profile, job, self.ctx.settings))
                           for job, _ in self.ranked]
            self._fill_table()

    def _show_tracked(self) -> None:
        """Populate the results table from tracked applications (no live search yet)."""
        saved = self.ctx.settings.last_search_job_ids
        if saved is not None:
            jobs = [self.ctx.workspace.get_job(job_id) for job_id in saved]
            self.ranked = [(job, match_job(self.ctx.profile, job, self.ctx.settings))
                           for job in jobs if job is not None]
            self._fill_table()
            self.result_summary.setText("Your last search, rescored against your current profile. "
                                        "Search again for fresh postings." + self._filter_note())
            return
        rows = [row for row in self.ctx.pipeline.tracker(self.ctx.profile)
                if row.status.is_active]
        rows = rows[:400]
        if not rows:
            return
        self.ranked = [(row.job, row.match) for row in rows]
        self._fill_table()
        self.result_summary.setText(
            f"Showing {len(rows)} tracked posting(s) from your queue — run a search for "
            f"fresh postings.{self._filter_note()}")

    def _on_min_match_changed(self, value: int) -> None:
        self.ctx.settings.min_match_score = value
        self.ctx.save_settings(self.ctx.settings)
        self.threshold_badge.setText(f"{value}% MATCH TARGET")
        self._fill_table()

    def _on_auto_track_changed(self, checked: bool) -> None:
        self.ctx.settings.auto_track_qualified = checked
        self.ctx.save_settings(self.ctx.settings)

    def _filter_note(self) -> str:
        threshold = self.min_match.value()
        if threshold <= 0 or not self.ranked:
            return ""
        qualified = sum(1 for _, match in self.ranked if match.score >= threshold)
        return f" {qualified} of {len(self.ranked)} results meet the {threshold}% match target."

    def _visible_rows(self) -> list[tuple[int, JobPosting, MatchResult]]:
        threshold = self.min_match.value()
        filtered = enumerate(self.ranked)
        if self.eligible_only.isChecked() and threshold > 0:
            filtered = ((index, pair) for index, pair in filtered
                        if pair[1].score >= threshold)
        rows = [(index, job, match) for index, (job, match) in filtered]
        return rows[:400]

    def show_result_outcome(self, outcome) -> None:
        """Render a fetch's postings in the results table (manual or background)."""
        self._remember_results(outcome)
        self.outcome = outcome
        self.ranked = [(job, match_job(self.ctx.profile, job, self.ctx.settings))
                       for job in outcome.jobs]
        self._fill_table()
        self.result_summary.setText(outcome.summary() + self._filter_note())

    def _remember_results(self, outcome) -> None:
        # Saving a search is separate from adding applications to the queue.
        self.ctx.workspace.save_jobs(outcome.jobs)
        self.ctx.settings.last_search_job_ids = [job.job_id for job in outcome.jobs]
        self.ctx.save_settings(self.ctx.settings)

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
        self.ctx.settings.last_search_location = self.location.text().strip()
        self.ctx.settings.enabled_sources = sources
        self.ctx.settings.remote_only = self.remote_only.isChecked()
        self.ctx.save_settings(self.ctx.settings)

        self.progress.setVisible(True)
        self.search_button.setEnabled(False)
        self.search_import_button.setEnabled(False)
        self.result_summary.setText("Contacting job boards…")

        query = self.ctx.pipeline.build_query(
            query_text, self.location.text().strip(), sources=sources,
            remote_only=self.remote_only.isChecked(), min_salary=self.min_salary.value(),
            limit_per_source=self.per_source.value())
        # Snapshot UI values before crossing into the worker thread.
        profile = self.ctx.profile
        threshold = self.min_match.value()
        track = import_results or self.auto_track.isChecked()

        def work():
            cancel = self.ctx.cancel_event.is_set
            outcome = self.ctx.pipeline.scraper.search(query, should_cancel=cancel)
            if cancel():
                return outcome, [], [], []  # closing: skip the import against the workspace
            rows, created = self.ctx.pipeline.import_qualified(
                outcome.jobs, profile, threshold=threshold,
                track=track)
            proposed = []
            if track and threshold > 0:
                below = [job for job, match in rows if match.score < threshold]
                proposed = self.ctx.pipeline.import_review(below)
            return outcome, rows, created, proposed

        def done(result) -> None:
            self.progress.setVisible(False)
            self.search_button.setEnabled(True)
            self.search_import_button.setEnabled(True)
            outcome, rows, created, proposed = result
            self._remember_results(outcome)
            self.outcome = outcome
            self.ranked = rows
            self._fill_table()
            queued = (f" · {len(created)} new in your queue"
                      if track else "")
            review = f" · {len(proposed)} below the bar added for review" if proposed else ""
            message = outcome.summary() + queued + review
            self.source_summary.setText(outcome.source_summary())
            threshold = self.min_match.value()
            if outcome.jobs and threshold > 0:
                qualified = sum(1 for _, match in rows if match.score >= threshold)
                if qualified == 0:
                    message += (f" None reached the {threshold}% qualification bar. "
                                "You can review the lower matches here in Job Search.")
            if not outcome.jobs:
                message += (" Try Africa + UAE logistics, a wider location or another role title. "
                            "UAE in-app aggregation needs a UAE Jooble key in Settings; "
                            "LinkedIn, Bayt and GulfTalent are available under More websites.")
            skipped = _skipped_sources()
            if skipped:
                message += f" Skipped: {', '.join(skipped)} — add API keys in Settings to search them."
            message += self._filter_note()
            self.result_summary.setText(message)
            level = "warning" if outcome.errors else "success"
            if not outcome.jobs:
                level = "warning"
            self.ctx.notify(message, level)
            self.ctx.update_meta()
            for tab in ("dashboard", "applications"):
                if hasattr(self.ctx.tabs.get(tab), "refresh"):
                    self.ctx.tabs[tab].refresh()

        def _skipped_sources() -> tuple[str, ...]:
            labels: list[str] = []
            for name, box in self.source_boxes.items():
                if not box.isChecked():
                    continue
                source = self.ctx.pipeline.scraper.sources.get(name)
                if source and source.needs_credentials and not source.is_configured(
                        self.ctx.settings):
                    labels.append(source.label)
            return tuple(labels)

        def failed(_message: str) -> None:
            self.progress.setVisible(False)
            self.search_button.setEnabled(True)
            self.search_import_button.setEnabled(True)

        self.ctx.run_task("Searching job boards", work, done, failed)

    def import_demo(self) -> None:
        query = self.query.text().strip() or "python"

        def work():
            return self.ctx.pipeline.search_and_import(query, sources=["sample"],
                                                       limit_per_source=self.per_source.value())

        def done(result) -> None:
            outcome, created = result
            self._remember_results(outcome)
            self.outcome = outcome
            self.ranked = [(job, match_job(self.ctx.profile, job, self.ctx.settings))
                           for job in outcome.jobs]
            self._fill_table()
            self.result_summary.setText(f"Demo data: {len(outcome.jobs)} posting(s), "
                                            f"{len(created)} new in tracker."
                                            f"{self._filter_note()}")
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

    def import_url(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            self.ctx.notify("Paste a job posting URL first.", "warning")
            return
        self.import_url_button.setEnabled(False)

        def work():
            import requests

            from ..services.job_scraper import JobScraper
            try:
                return self.ctx.pipeline.import_from_url(url)
            except requests.exceptions.RequestException as exc:
                raise ValueError(JobScraper._friendly_error(exc)) from exc
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError(f"no readable job text on that page ({exc.__class__.__name__})"
                                 ) from exc

        def done(result) -> None:
            self.import_url_button.setEnabled(True)
            application, created = result
            job = self.ctx.workspace.get_job(application.job_id)
            if created:
                self.ctx.notify(f"Tracked “{job.title}” at {job.company} from the pasted link.",
                                "success")
            else:
                self.ctx.notify("That posting is already in your tracker.", "info")
            self.url_input.clear()
            if job:
                self.ranked = [(j, m) for j, m in self.ranked if j.job_id != job.job_id]
                self.ranked.append((job, match_job(self.ctx.profile, job, self.ctx.settings)))
                self.ctx.settings.last_search_job_ids = [j.job_id for j, _ in self.ranked]
                self.ctx.save_settings(self.ctx.settings)
                self._fill_table()
            self.ctx.tabs["dashboard"].refresh()
            self.ctx.tabs["applications"].refresh()

        def failed(message: str) -> None:
            self.import_url_button.setEnabled(True)
            self.ctx.notify(f"Could not read that link — {message}. Use Paste job details instead.", "warning")

        self.ctx.run_task("Reading the pasted link", work, done, failed)

    def use_regional_search(self) -> None:
        from ..models import DEFAULT_SOURCE_NAMES
        self.query.setText("logistics")
        self.location.setText("Africa; UAE")
        self.remote_only.setChecked(False)
        self.eligible_only.setChecked(False)
        for name, box in self.source_boxes.items():
            box.setChecked(name in DEFAULT_SOURCE_NAMES)
        self.ctx.settings.enabled_sources = list(DEFAULT_SOURCE_NAMES)
        self.ctx.settings.last_search_query = "logistics"
        self.ctx.settings.last_search_location = "Africa; UAE"
        self.ctx.settings.remote_only = False
        self.ctx.save_settings(self.ctx.settings)
        self.ctx.notify("Regional logistics sources selected. Click Search jobs. "
                        "Jooble UAE needs its own API key; More websites opens additional boards.", "info")

    def open_regional_website(self) -> None:
        from ..services.regional_job_sources import regional_search_url
        url = regional_search_url(self.browser_board.currentText(), self.query.text(),
                                  self.ctx.settings.linkedin_easy_apply, self.remote_only.isChecked())
        th.open_in_browser(url)

    def import_job_details(self) -> None:
        from .manual_job_dialog import ManualJobDialog
        dialog = ManualJobDialog(self.url_input.text(), self)
        if dialog.exec() != QDialog.Accepted or dialog.job is None:
            return
        job = dialog.job
        self.ctx.pipeline.ensure_application(job)
        self.ranked = [(j, m) for j, m in self.ranked if j.job_id != job.job_id]
        self.ranked.append((job, match_job(self.ctx.profile, job, self.ctx.settings)))
        self.ctx.settings.last_search_job_ids = [j.job_id for j, _ in self.ranked]
        self.ctx.save_settings(self.ctx.settings)
        self.url_input.clear()
        self._fill_table()
        self.ctx.tabs["applications"].refresh()
        self.ctx.tabs["dashboard"].refresh()
        self.ctx.notify(f"Tracked {job.title} from the copied job details.", "success")

    def open_linkedin_search(self) -> None:
        """Hand the current query off to LinkedIn's own job search in the browser."""
        from ..services.job_scraper import linkedin_search_url
        easy_apply = bool(getattr(self.ctx.settings, "linkedin_easy_apply", True))
        url = linkedin_search_url(
            self.query.text() or (self.ctx.profile.desired_titles[0]
                                  if self.ctx.profile.desired_titles else ""),
            self.location.text(), easy_apply_only=easy_apply, remote_only=self.remote_only.isChecked())
        if th.open_in_browser(url):
            self.ctx.notify("Opened LinkedIn in your browser — track jobs there by pasting "
                            "their URL into the box below.", "info")

    # ------------------------------------------------------------- table  #
    def _fill_table(self) -> None:
        self.ranked.sort(key=lambda pair: (-pair[1].score, pair[0].title.lower()))
        rows = self._visible_rows()
        threshold = self.min_match.value()
        qualified = sum(match.score >= threshold for _, match in self.ranked)
        self.result_counts.setText(
            f"{len(self.ranked)} FOUND   /   {qualified} ELIGIBLE   /   "
            f"{len(self.ranked) - qualified} TO REVIEW   /   {len(rows)} SHOWN")
        self.empty_results.setVisible(not rows)
        self.empty_results.setText(
            "No jobs meet your match target yet. Turn off 'Eligible only' to review all results."
            if self.ranked else "No postings to show yet. Search job boards or import demo data.")
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        tracked = {app.job_id for app in self.ctx.workspace.applications()}
        for index, (rank_index, job, match) in enumerate(rows):
            is_tracked = job.job_id in tracked
            match_item = QTableWidgetItem(f"{match.score}%")
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
            eligible = match.score >= threshold
            eligibility = QTableWidgetItem("Eligible" if eligible else "Below target")
            eligibility.setForeground(QColor(th.current_theme()["accent" if eligible else "muted"]))
            eligibility.setToolTip(f"{'Meets' if eligible else 'Below'} your {threshold}% profile-match target. "
                                   "Review the employer's requirements before applying.")
            self.table.setItem(index, 7, eligibility)
        self.table.resizeRowsToContents()
        self.table.blockSignals(False)
        if rows:
            self.table.selectRow(0)
        self._show_selected()

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
            self.detail_title.setText("Select a posting")
            self.detail_meta.clear()
            self.score_bar.hide()
            self.eligibility_label.clear()
            self.match_summary.clear()
            self.tags_line.clear()
            self.description.clear()
            return
        job, match = selected
        self.detail_title.setText(f"{job.title} · {job.company}")
        self.detail_meta.setText(
            f"{job.display_location} · {job.salary_text} · posted {job.posted_text} · "
            f"via {job.source}")
        self.score_bar.setVisible(True)
        self.score_bar.set_score(match.score)
        eligible = match.score >= self.min_match.value()
        self.eligibility_label.setText(
            f"{'Eligible' if eligible else 'Below target'} · {match.score}% profile match\n"
            f"Qualification target: {self.min_match.value()}%")
        self.match_summary.setText("\n".join(f"• {reason}" for reason in match.reasons))
        self.tags_line.setText(
            "Matched: " + (", ".join(match.matched_keywords) or "No matching keywords yet")
            + "\nGaps to review: " + (", ".join(match.missing_keywords) or "None detected")
            + "\nBased on your saved profile; employer requirements still need review.")
        body = job.description or "This posting has no description text."
        self.description.document().setDefaultStyleSheet(
            f"a {{ color: {th.current_theme()['accent']}; }}")
        if job.url:
            body += f"<p><a href='{escape(job.url, quote=True)}'>Open the original posting</a></p>"
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
                      if match.score >= self.min_match.value()][:count]
        if not candidates:
            self.ctx.notify("No jobs meet your match target yet. Review a posting individually.", "warning")
            return
        self._prepare_jobs(candidates)

    def _prepare_jobs(self, jobs: list[JobPosting]) -> None:
        profile = self.ctx.profile

        def work():
            cancel = self.ctx.cancel_event.is_set
            results = []
            for job in jobs:
                if cancel():
                    break  # closing: hand back the partial batch
                application = self.ctx.pipeline.ensure_application(job)
                results.append(self.ctx.pipeline.prepare(application, profile))
            return results

        def done(materials) -> None:
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

    def _clear_selected(self) -> None:
        selected = self._selected_job()
        if not selected:
            self.ctx.notify("Select a posting first.", "warning")
            return
        job, _match = selected
        application = self.ctx.pipeline.ensure_application(job)
        self.ctx.pipeline.clear_application(application)
        self._mark_tracked()
        self.ctx.notify(f"Cleared {job.title} at {job.company} from the queue.", "success")
        self.ctx.tabs["dashboard"].refresh()
        self.ctx.tabs["applications"].refresh()

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


__all__ = ["COLUMNS", "JobSearchTab"]
