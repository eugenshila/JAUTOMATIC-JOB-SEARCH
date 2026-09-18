"""Dashboard: at-a-glance numbers, top matches, follow-ups, next steps."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import ApplicationStatus
from ..services.application_pipeline import TrackedApplication
from . import theme as th


def next_steps(profile) -> list[str]:
    """Concrete, ordered suggestions that raise profile completeness."""
    steps: list[str] = []
    if not profile.full_name:
        steps.append("Add your name, e-mail and phone in the Profile tab.")
    if not profile.headline:
        steps.append("Write a one-line headline (e.g. “Senior Python Engineer · 6 yrs”).")
    if len(profile.skills) < 5:
        steps.append("List at least five skills — the matcher scores postings against them.")
    if not profile.summary:
        steps.append("Add a short professional summary; the CV uses it verbatim.")
    if not profile.experience:
        steps.append("Add your most recent role with 3-5 achievement bullets.")
    if not profile.education:
        steps.append("Add education or certifications.")
    if not profile.desired_titles:
        steps.append("Set the job titles you want so postings can be ranked by title fit.")
    if not profile.salary_floor:
        steps.append("Set a salary floor to flag postings that pay too little.")
    if not profile.links:
        steps.append("Add LinkedIn/GitHub links so recruiters can check your work.")
    if profile.tone not in ("professional", "friendly", "enthusiastic", "concise"):
        steps.append("Pick a letter tone in Profile → Letter settings.")
    return steps


class DashboardTab(QWidget):
    page_title = "Dashboard"
    page_subtitle = "Where your search stands right now"

    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx
        self.stat_cards: dict[str, th.StatCard] = {}
        self._build_ui()

    # ------------------------------------------------------------------ UI #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 6, 12)
        layout.setSpacing(14)

        # -- stat tiles ---------------------------------------------------- #
        tiles = QGridLayout()
        tiles.setSpacing(12)
        specs = [
            ("jobs", "Postings found", "info"),
            ("applications", "Tracked", "accent"),
            ("materials_ready", "Materials ready",
             ApplicationStatus.MATERIALS_READY.color),
            ("sent", "Applications sent", "success"),
            ("interviews", "Interviews", "warning"),
            ("follow_ups_due", "Follow-ups due", "danger"),
        ]
        for column, (key, caption, color) in enumerate(specs):
            card = th.StatCard(caption, "0", "", color)
            self.stat_cards[key] = card
            tiles.addWidget(card, 0, column)
            tiles.setColumnStretch(column, 1)
        layout.addLayout(tiles)

        # -- two column body ---------------------------------------------- #
        columns = QHBoxLayout()
        columns.setSpacing(14)
        layout.addLayout(columns, 1)

        left = QVBoxLayout()
        left.setSpacing(14)
        columns.addLayout(left, 3)

        self.matches_card = th.Card("Top matches",
                                   "Highest-scoring open postings that still need materials")
        self.matches_table = QTableWidget(0, 5)
        self.matches_table.setHorizontalHeaderLabels(["Score", "Role", "Company", "Location", "Status"])
        self.matches_table.verticalHeader().setVisible(False)
        self.matches_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.matches_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.matches_table.setAlternatingRowColors(True)
        self.matches_table.setMinimumHeight(210)
        self.matches_table.setMaximumHeight(320)
        header = self.matches_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.matches_card.add(self.matches_table)
        action_row = QHBoxLayout()
        self.prepare_button = th.button("Prepare materials", "primary", "", self._prepare_selected)
        action_row.addWidget(self.prepare_button)
        action_row.addWidget(th.button("Open applications tab", "ghost", "",
                                       lambda: self.ctx.go_to("applications")))
        action_row.addWidget(th.button("Open posting", "default", "", self._open_posting))
        action_row.addStretch(1)
        self.matches_card.add_layout(action_row)
        left.addWidget(self.matches_card)

        self.activity_card = th.Card("Recent activity", "Newest events from your application log")
        self.activity_list = QVBoxLayout()
        self.activity_list.setSpacing(6)
        self.activity_card.add_layout(self.activity_list)
        left.addWidget(self.activity_card)
        left.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(14)
        columns.addLayout(right, 2)

        self.readiness_card = th.Card("Profile readiness", "A complete profile means better matches")
        self.completeness = QProgressBar()
        self.completeness.setRange(0, 100)
        self.readiness_card.add(self.completeness)
        self.steps_list = QVBoxLayout()
        self.steps_list.setSpacing(5)
        self.readiness_card.add_layout(self.steps_list)
        right.addWidget(self.readiness_card)

        self.follow_card = th.Card("Follow-ups", "Applications that are due for a nudge")
        self.follow_list = QVBoxLayout()
        self.follow_list.setSpacing(8)
        self.follow_card.add_layout(self.follow_list)
        right.addWidget(self.follow_card)

        self.quick_card = th.Card("Quick actions")
        for text, tip, handler, role in [
            ("Run search & import", "Search every enabled source with your last query",
             self._quick_search, "primary"),
            ("Import demo data", "Add offline sample postings (works without a network)",
             self._import_demo, "default"),
            ("Autopilot: prepare top matches", "Generate CVs for the best matches above the "
             "autopilot threshold", self._run_autopilot, "default"),
            ("Export tracker to CSV", "Applications + status + documents", self._export_csv, "default"),
            ("Export calendar (.ics)", "Interviews + follow-ups for Google/Outlook/Apple Calendar",
             self._export_calendar, "default"),
            ("Open data folder", "Profile, settings, documents, database", self._open_data_dir, "ghost"),
        ]:
            widget = th.button(text, role, tip, handler)
            self.quick_card.add(widget)
        right.addWidget(self.quick_card)
        right.addStretch(1)

        self.ctx.add_header_action("dashboard", th.button("Run search & import", "primary",
                                             "Fetch fresh postings from every enabled source",
                                             self._quick_search))

    # ------------------------------------------------------------- refresh #
    def refresh(self) -> None:
        stats = self.ctx.pipeline.dashboard_stats(self.ctx.profile)
        for key, card in self.stat_cards.items():
            card.set_value(str(stats.get(key, 0)))
        self.stat_cards["applications"].set_value(
            str(stats["applications"]), f"{stats['response_rate']}% response rate")
        self.stat_cards["sent"].set_value(str(stats["sent"]),
                                          f"{stats['interview_rate']}% interview rate")

        self._refresh_readiness()
        self._refresh_matches(stats.get("top_matches", []))
        self._refresh_follow_ups()
        self._refresh_activity()

    def _refresh_readiness(self) -> None:
        profile = self.ctx.profile
        percent = profile.completeness()
        self.completeness.setValue(percent)
        self.completeness.setFormat(f"{percent}% complete")
        th.clear_layout(self.steps_list)
        steps = next_steps(profile)
        if not steps:
            th.clear_layout(self.steps_list)
            self.steps_list.addWidget(th.label(
                "Nothing missing — your profile is ready to send.", "muted", wrap=True))
            return
        for step in steps[:6]:
            row = QHBoxLayout()
            bullet = QLabel("•")
            bullet.setObjectName("Muted")
            text = th.label(step, "muted", wrap=True)
            row.addWidget(bullet)
            row.addWidget(text, 1)
            container = QWidget()
            container.setLayout(row)
            self.steps_list.addWidget(container)
        if len(steps) > 6:
            self.steps_list.addWidget(th.label(f"+ {len(steps) - 6} more suggestion(s)", "small"))

    def _refresh_matches(self, rows: list[TrackedApplication]) -> None:
        if not rows:
            rows = [r for r in self.ctx.pipeline.tracker(self.ctx.profile)
                    if r.status.is_active][:5]
        self.matches_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            score_item = QTableWidgetItem(f"{row.score}")
            score_item.setData(Qt.UserRole, row.application.application_id)
            score_item.setTextAlignment(Qt.AlignCenter)
            self.matches_table.setItem(index, 0, score_item)
            self.matches_table.setItem(index, 1, QTableWidgetItem(row.title))
            self.matches_table.setItem(index, 2, QTableWidgetItem(row.company))
            self.matches_table.setItem(index, 3, QTableWidgetItem(row.job.short_location))
            status_item = QTableWidgetItem(row.status.label)
            status_item.setForeground(Qt.GlobalColor.gray)
            self.matches_table.setItem(index, 4, status_item)
        self.matches_table.resizeRowsToContents()
        self.prepare_button.setEnabled(bool(rows))

    def _refresh_follow_ups(self) -> None:
        th.clear_layout(self.follow_list)
        due = self.ctx.pipeline.follow_ups_due(self.ctx.profile)
        if not due:
            self.follow_list.addWidget(th.label(
                "Nothing due. Applications you mark as sent get a follow-up date automatically.",
                "muted", wrap=True))
            return
        for row in due[:5]:
            container = QWidget()
            box = QVBoxLayout(container)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(4)
            head = th.label(f"{row.title} · {row.company}", "title", wrap=True)
            when = row.application.follow_up_at or date.today().isoformat()
            days = row.application.days_since_sent
            rung = row.application.rung_label(self.ctx.settings.follow_up_max_nudges)
            meta = f"{rung} follow-up {when}" + (f" · sent {days} days ago" if days is not None else "")
            box.addWidget(head)
            box.addWidget(th.label(meta, "small"))
            buttons = QHBoxLayout()
            buttons.addWidget(th.button("Draft e-mail", "primary", "Create a polite follow-up",
                                        lambda _=False, r=row: self._draft_follow_up(r)))
            buttons.addWidget(th.button("Postpone 5 days", "ghost", "",
                                        lambda _=False, r=row: self._postpone(r)))
            buttons.addWidget(th.button("Mark sent", "default", "Record a follow-up you sent",
                                        lambda _=False, r=row: self._follow_up_sent(r)))
            buttons.addStretch(1)
            box.addLayout(buttons)
            self.follow_list.addWidget(container)

    def _refresh_activity(self) -> None:
        th.clear_layout(self.activity_list)
        events: list[tuple[str, str, str]] = []
        for row in self.ctx.pipeline.tracker(self.ctx.profile):
            for event in row.application.history[-4:]:
                events.append((event.get("at", ""), row.title, self._describe(event)))
        events.sort(reverse=True)
        if not events:
            self.activity_list.addWidget(th.label(
                "No activity yet — run a search to fill your pipeline.", "muted", wrap=True))
            return
        for when, title, description in events[:7]:
            line = QLabel(f"<b>{title}</b> — {description} <span style='opacity:.6'>· {when}</span>")
            line.setWordWrap(True)
            self.activity_list.addWidget(line)

    @staticmethod
    def _describe(event: dict) -> str:
        kind = event.get("event", "event")
        if kind == "status":
            return f"status {event.get('from')} → {event.get('to')}"
        return event.get("note") or kind

    # ------------------------------------------------------------ actions #
    def _selected_row(self) -> TrackedApplication | None:
        items = self.matches_table.selectedItems()
        if not items:
            return None
        application_id = self.matches_table.item(items[0].row(), 0).data(Qt.UserRole)
        for row in self.ctx.pipeline.tracker(self.ctx.profile):
            if row.application.application_id == application_id:
                return row
        return None

    def _prepare_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            self.ctx.notify("Pick a posting from the Top matches table first.", "warning")
            return
        self._prepare(row)

    def _prepare(self, row: TrackedApplication) -> None:
        def work():
            return self.ctx.pipeline.prepare(row.application, self.ctx.profile)

        def done(materials) -> None:
            self.ctx.notify(f"Materials ready for {row.title} at {row.company}.", "success")
            self.ctx.refresh_all()
            if materials.cv and materials.cv.text:
                self.ctx.open_preview(f"CV · {row.title}", materials.cv.text,
                                      materials.cv.path)

        self.ctx.run_task(f"Generating materials for {row.title}", work, done)

    def _open_posting(self) -> None:
        row = self._selected_row()
        if row and row.job.url:
            th.open_in_browser(row.job.url)
        else:
            self.ctx.notify("This posting has no URL attached.", "warning")

    def _draft_follow_up(self, row: TrackedApplication) -> None:
        def done(result) -> None:
            path, text = result
            self.ctx.notify("Follow-up e-mail drafted.", "success")
            self.ctx.open_preview("Follow-up e-mail", text, path)

        self.ctx.run_task("Drafting follow-up e-mail",
                          lambda: self.ctx.pipeline.draft_follow_up(row.application), done)

    def _postpone(self, row: TrackedApplication) -> None:
        self.ctx.pipeline.postpone_follow_up(row.application, 5)
        self.ctx.notify(f"Follow-up for {row.title} moved out by 5 days.", "info")
        self.refresh()

    def _follow_up_sent(self, row: TrackedApplication) -> None:
        try:
            self.ctx.pipeline.mark_follow_up_sent(row.application)
        except ValueError as exc:
            self.ctx.notify(str(exc), "warning")
            return
        self.refresh()
        self.ctx.tabs["applications"].refresh()
        self.ctx.notify("Follow-up recorded as sent; reminders updated.", "success")

    def _quick_search(self) -> None:
        self.ctx.go_to("search")
        tab = self.ctx.tabs["search"]
        tab.start_search(import_results=True)

    def _import_demo(self) -> None:
        def work():
            outcome = self.ctx.pipeline.search(
                self.ctx.settings.last_search_query or "python", include_sample=True,
                sources=["sample"])
            created = self.ctx.pipeline.import_jobs(outcome.jobs)
            return outcome, created

        def done(result) -> None:
            outcome, created = result
            self.ctx.notify(f"Imported {len(created)} demo posting(s); "
                            f"{len(outcome.jobs)} matched your filters.", "success")
            self.ctx.refresh_all()

        self.ctx.run_task("Importing demo postings", work, done)

    def _run_autopilot(self) -> None:
        def done(materials) -> None:
            if not materials:
                self.ctx.notify("Autopilot found nothing above the score threshold "
                                "(or everything is already prepared).", "info")
            else:
                self.ctx.notify(f"Autopilot prepared {len(materials)} application(s).", "success")
            self.ctx.refresh_all()

        self.ctx.run_task("Autopilot preparing materials",
                          lambda: self.ctx.pipeline.autopilot(
                              self.ctx.profile,
                              should_cancel=self.ctx.cancel_event.is_set), done)

    def _export_csv(self) -> None:
        def done(path) -> None:
            self.ctx.notify(f"Tracker exported to {path}", "success")
            th.open_path(path)

        self.ctx.run_task("Exporting tracker CSV",
                          lambda: self.ctx.pipeline.export_tracker_csv(self.ctx.profile), done)

    def _export_calendar(self) -> None:
        def done(path) -> None:
            self.ctx.notify(f"Calendar exported to {path}", "success")
            th.open_path(path)

        self.ctx.run_task("Exporting calendar (.ics)",
                          lambda: self.ctx.pipeline.export_calendar_ics(self.ctx.profile), done)

    def _open_data_dir(self) -> None:
        if not th.open_in_file_manager(self.ctx.workspace.root):
            self.ctx.notify(f"Data folder: {self.ctx.workspace.root}", "info")


__all__ = ["DashboardTab", "next_steps"]
