"""Applications tab: the tracker - statuses, documents, notes, follow-ups."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..models import ApplicationStatus
from ..services.application_pipeline import TrackedApplication
from . import theme as th

COLUMNS = ["Status", "Score", "Role", "Company", "Follow-up", "Interview", "Docs", "Prep"]
VIEW_STATUSES = {
    "applications": (ApplicationStatus.DISCOVERED, ApplicationStatus.PROPOSED,
                     ApplicationStatus.SHORTLISTED, ApplicationStatus.MATERIALS_READY),
    "sent": (ApplicationStatus.SENT, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER),
    "archive": (ApplicationStatus.REJECTED, ApplicationStatus.ARCHIVED),
}


class ApplicationsTab(QWidget):
    page_title = "Applications"
    page_subtitle = ("Every tracked posting — qualified and below-bar proposals — "
                     "its documents and the next action")

    def __init__(self, ctx, view: str = "applications") -> None:
        super().__init__()
        self.ctx = ctx
        self.view = view
        self.statuses = VIEW_STATUSES[view]
        self.page_title, self.page_subtitle = {
            "applications": ("Applications", "Prepare applications, then mark them Sent once you apply"),
            "sent": ("Sent", "Follow up on applications and prepare for interviews; mark regrets to archive them"),
            "archive": ("Archive", "Regrets and archived applications — restore a status or delete permanently"),
        }[view]
        self.rows: list[TrackedApplication] = []
        self._checked_ids: set[str] = set()
        self._build_ui()

    # ------------------------------------------------------------------ UI #
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        filters = th.Card("Filters", "Filter applications in this tab")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter by title, company or notes…")
        self.search_box.textChanged.connect(self.refresh)
        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", None)
        for status in self.statuses:
            self.status_filter.addItem(status.label, status.value)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        self.min_score = QSpinBox()
        self.min_score.setRange(0, 100)
        self.min_score.setPrefix("min score ")
        self.min_score.valueChanged.connect(self.refresh)
        self.due_only = QCheckBox("Follow-ups due only")
        self.due_only.toggled.connect(self.refresh)
        row.addWidget(self.search_box, 1)
        row.addWidget(self.status_filter)
        row.addWidget(self.min_score)
        row.addWidget(self.due_only)
        self.due_only.setVisible(self.view == "sent")
        filters.add_layout(row)

        actions = QHBoxLayout()
        actions.addWidget(th.button("Recompute match scores", "default",
                                    "Re-score every tracked posting against the current profile",
                                    self._recompute))
        actions.addWidget(th.button("Autopilot: prepare top matches", "default",
                                    "Generate materials for the best untouched matches",
                                    self._autopilot))
        actions.addWidget(th.button("Export CSV", "ghost", "", self._export))
        actions.addWidget(th.button("Export calendar (.ics)", "ghost",
                                    "Interviews and follow-ups for Google/Outlook/Apple Calendar",
                                    self._export_calendar))
        actions.addWidget(th.button("Preview auto-clear", "ghost",
                                    "Dry run: show which untouched applications the next "
                                    "sweep would archive (nothing is changed)", self._preview_auto_clear))
        actions.addStretch(1)
        self.count_label = th.label("", "small")
        actions.addWidget(self.count_label)
        filters.add_layout(actions)
        # Preparation and auto-clear belong to the unsent queue.
        for index in (0, 1, 4):
            actions.itemAt(index).widget().setVisible(self.view == "applications")
        layout.addWidget(filters)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        table_card = th.Card("Tracked applications")
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        for column in (4, 5, 7):
            self.table.setColumnHidden(column, self.view == "applications")
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.table.itemChanged.connect(self._check_changed)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(70)     # floor so columns never squash to illegibility
        header.setSectionResizeMode(2, QHeaderView.Stretch)          # role breathes
        for column in (0, 1, 3, 4, 5, 6, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(3, 170)
        self.table.setColumnWidth(4, 110)
        self.table.setColumnWidth(5, 110)
        self.table.setMinimumWidth(430)
        bulk = QHBoxLayout()
        self.select_all_button = th.button("Select all", "ghost",
            "Select and tick every application currently shown", self._select_all)
        self.archive_selected_button = th.button("Archive selected", "default",
            "Move selected applications to Archive", lambda: self._archive_queue(False))
        self.archive_all_button = th.button("Archive all shown", "default",
            "Move every application matching the current filters to Archive",
            lambda: self._archive_queue(True))
        for button in (self.select_all_button, self.archive_selected_button, self.archive_all_button):
            bulk.addWidget(button)
            button.setVisible(self.view == "applications")
        self.delete_selected_button = th.button("Delete selected", "danger",
            "Permanently remove selected applications from the tracker", self._delete_selected)
        bulk.addWidget(self.delete_selected_button)
        self.delete_selected_button.setVisible(self.view in ("applications", "archive"))
        self.select_all_button.setVisible(self.view in ("applications", "archive"))
        bulk.addStretch(1)
        self.add_matches_button = th.button("Add matching saved jobs", "default",
            "Review saved postings against your current profile and queue those meeting your match target",
            self._add_matching_jobs)
        self.add_matches_button.setVisible(self.view == "applications")
        bulk.addWidget(self.add_matches_button)
        table_card.add_layout(bulk)
        table_card.add(self.table)
        splitter.addWidget(table_card)

        detail_card = th.Card("Application")
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.detail_title = th.label("Select an application", "title", wrap=True)
        self.status_chip = th.StatusChip()
        self.status_chip.setVisible(False)
        title_row.addWidget(self.detail_title, 1)
        title_row.addWidget(self.status_chip, 0, Qt.AlignTop)
        self.detail_meta = th.label("", "small", wrap=True)
        status_row = QHBoxLayout()
        self.status_combo = QComboBox()
        for status in ApplicationStatus.ordered():
            self.status_combo.addItem("Regret" if status is ApplicationStatus.REJECTED
                                      else status.label, status.value)
        status_row.addWidget(th.label("Status", "muted"))
        status_row.addWidget(self.status_combo, 1)
        status_row.addWidget(th.button("Apply", "primary", "Update the status and log it",
                                       self._apply_status))
        interview_row = QHBoxLayout()
        self.interview_edit = QLineEdit()
        self.interview_edit.setPlaceholderText("e.g. 2026-09-22 14:30 — leave blank to clear")
        interview_row.addWidget(th.label("Interview", "muted"))
        interview_row.addWidget(self.interview_edit, 1)
        interview_row.addWidget(th.button("Save", "default",
                                          "Store the interview date/time (also lands in the "
                                          "calendar export)", self._save_interview))
        detail_card.add_layout(title_row)
        detail_card.add(self.detail_meta)
        detail_card.add_layout(status_row)
        interview_controls = QWidget()
        interview_controls.setLayout(interview_row)
        detail_card.add(interview_controls)
        interview_controls.setVisible(self.view == "sent")

        self.generate_button = th.button("Generate materials", "primary",
                                  "Write a tailored CV, cover letter and e-mail draft",
                                  self._prepare)
        detail_card.add(self.generate_button)
        self.generate_button.setVisible(self.view == "applications")
        self.outlook_button = th.button("Open Outlook draft", "primary",
            "Fill the email and attach your CV and cover letter; enter the recipient in Outlook",
            self._open_outlook_draft)
        self.outlook_button.setVisible(self.view == "applications")
        detail_card.add(self.outlook_button)
        documents = QHBoxLayout()
        documents.setSpacing(6)
        documents.addWidget(th.button("Open CV", "default", "", lambda: self._open_doc("cv")))
        documents.addWidget(th.button("Open letter", "default",
                                      "", lambda: self._open_doc("cover")))
        documents.addWidget(th.button("Open e-mail", "default", "", lambda: self._open_doc("email")))
        documents.addWidget(th.button("Open posting", "ghost", "", self._open_posting))
        documents.addStretch(1)
        detail_card.add_layout(documents)

        follow_up = QHBoxLayout()
        follow_up.setSpacing(6)
        follow_up.addWidget(th.button("Draft follow-up", "default",
                                      "Write a polite nudge e-mail", self._follow_up))
        follow_up.addWidget(th.button("Postpone 5 days", "ghost", "", self._postpone))
        follow_up.addWidget(th.button("Mark follow-up sent", "default",
                                      "Record a follow-up you have sent", self._follow_up_sent))
        follow_up.addStretch(1)
        follow_up_controls = QWidget()
        follow_up_controls.setLayout(follow_up)
        detail_card.add(follow_up_controls)
        follow_up_controls.setVisible(self.view == "sent")

        danger = QHBoxLayout()
        self.archive_button = th.button("Archive", "default",
                                   "Archive this application — it leaves the active queue "
                                   "but stays in the database/history", self._clear)
        danger.addWidget(self.archive_button)
        self.archive_button.setVisible(self.view != "archive")
        self.regret_button = th.button("Regret", "default",
                                       "Record a rejection and move this application to Archive",
                                       self._regret)
        danger.addWidget(self.regret_button)
        self.regret_button.setVisible(self.view == "sent")
        self.delete_button = th.button("Delete permanently", "danger", "Remove from the tracker",
                                       self._delete)
        danger.addWidget(self.delete_button)
        self.delete_button.setVisible(self.view == "archive")
        danger.addStretch(1)
        detail_card.add_layout(danger)

        notes_row = QHBoxLayout()
        notes_row.addWidget(th.label("Notes", "title"), 1)
        self.prep_label = th.label("", "small")
        notes_row.addWidget(self.prep_label)
        self.prep_button = th.button("Interview prep", "default",
                                      "Notes and a question bank derived from this posting "
                                      "and your profile", self._interview_prep)
        notes_row.addWidget(self.prep_button)
        self.prep_button.setVisible(self.view == "sent")
        detail_card.add_layout(notes_row)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Recruiter names, interview dates, salary talk, "
                                      "take-home deadlines…")
        self.notes.setFixedHeight(110)
        detail_card.add(self.notes)
        detail_card.add(th.button("Save notes", "default", "", self._save_notes))

        detail_card.add(th.label("History", "title"))
        self.history = QTextBrowser()
        self.history.setMinimumHeight(120)
        detail_card.add(self.history)
        detail_card.setMinimumWidth(470)
        splitter.addWidget(detail_card)
        splitter.setSizes([780, 500])

        if self.view == "applications":
            self.ctx.add_header_action(self.view, th.button("Generate materials", "primary", "",
                                                            self._prepare))
        elif self.view == "sent":
            self.ctx.add_header_action(self.view, th.button("Interview prep", "primary", "",
                                                            self._interview_prep))

    # ------------------------------------------------------------- refresh #
    def refresh(self) -> None:
        selected_id = self._selected_application_id()
        self.rows = self._filtered_rows()
        self.count_label.setText(f"{len(self.rows)} of "
                                 f"{len(self.ctx.workspace.applications())} application(s)")
        self._fill_table(selected_id)

    def _filtered_rows(self) -> list[TrackedApplication]:
        rows = self.ctx.pipeline.tracker(self.ctx.profile)
        text = self.search_box.text().strip().lower()
        status = self.status_filter.currentData()
        min_score = self.min_score.value()
        due_only = self.due_only.isChecked()
        filtered: list[TrackedApplication] = []
        for row in rows:
            if row.status not in self.statuses:
                continue
            if status and row.application.status != status:
                continue
            if row.score < min_score:
                continue
            if due_only and not row.application.follow_up_due:
                continue
            if text:
                prep_notes = str((row.application.prep or {}).get("notes") or "")
                haystack = " ".join([row.title, row.company, row.job.location,
                                     row.application.notes, prep_notes]).lower()
                if text not in haystack:
                    continue
            filtered.append(row)
        return filtered

    def _fill_table(self, selected_id: str | None) -> None:
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(len(self.rows))
        select_row = 0
        for index, row in enumerate(self.rows):
            app = row.application
            status_item = QTableWidgetItem(row.status.label)
            status_item.setData(Qt.UserRole, app.application_id)
            if self.view == "applications":
                status_item.setFlags(status_item.flags() | Qt.ItemIsUserCheckable)
                status_item.setCheckState(Qt.Checked if app.application_id in self._checked_ids
                                          else Qt.Unchecked)
            status_item.setForeground(QColor(row.status.color))
            score_item = QTableWidgetItem(str(row.score))
            score_item.setTextAlignment(Qt.AlignCenter)
            score_item.setForeground(QColor(th.ScoreBar.score_color(row.score)))
            self.table.setItem(index, 0, status_item)
            self.table.setItem(index, 1, score_item)
            self.table.setItem(index, 2, QTableWidgetItem(row.title))
            self.table.setItem(index, 3, QTableWidgetItem(row.company))
            follow = app.follow_up_at[:10] if app.follow_up_at else "—"
            if app.follow_up_due:
                follow += "  ⚠"
            follow_item = QTableWidgetItem(follow)
            follow_item.setToolTip(f"{app.rung_label(self.ctx.settings.follow_up_max_nudges)} "
                                   f"follow-up" if app.follow_up_at else "")
            self.table.setItem(index, 4, follow_item)
            self.table.setItem(index, 5, QTableWidgetItem(app.interview_at[:10] or "—"))
            documents = sum(1 for _, path in app.documents if path and Path(path).exists())
            self.table.setItem(index, 6, QTableWidgetItem(f"{documents}/3"))
            prep_item = QTableWidgetItem(
                f"{app.prep_answered_count}/{app.prep_question_count}"
                if app.prep_question_count else ("notes" if app.has_prep else "—"))
            prep_item.setTextAlignment(Qt.AlignCenter)
            prep_item.setToolTip("Interview prep: answered/total questions")
            self.table.setItem(index, 7, prep_item)
            if selected_id and app.application_id == selected_id:
                select_row = index
        self.table.resizeRowsToContents()
        self.table.blockSignals(False)
        if self.rows:
            self.table.selectRow(select_row)
            self._show_selected()
        else:
            self._clear_detail()

    def _selected_application_id(self) -> str | None:
        items = self.table.selectedItems()
        if not items:
            return None
        return self.table.item(items[0].row(), 0).data(Qt.UserRole)

    def _selected_row(self) -> TrackedApplication | None:
        application_id = self._selected_application_id()
        if not application_id:
            return None
        for row in self.rows:
            if row.application.application_id == application_id:
                return row
        return None

    def _clear_detail(self) -> None:
        self.status_chip.setVisible(False)
        self.detail_title.setText("No applications match the filters")
        self.detail_meta.setText("")
        self.prep_label.setText("")
        self.interview_edit.setText("")
        self.notes.setPlainText("")
        self.history.setHtml("")

    def _show_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            self._clear_detail()
            return
        app = row.application
        self.detail_title.setText(f"{row.title} · {row.company}")
        bits = [row.job.display_location, row.job.salary_text, f"match {row.score}/100",
                f"via {row.job.source}"]
        if app.sent_at:
            bits.append(f"sent {app.sent_at[:10]}")
        if app.follow_up_at:
            bits.append(f"follow-up {app.follow_up_at}")
        if app.interview_at:
            bits.append(f"interview {app.interview_at}")
        if app.follow_up_due:
            bits.append("FOLLOW-UP DUE")
        self.detail_meta.setText(" · ".join(b for b in bits if b))
        from ..services.cover_letter import select_cover_letter
        letter = select_cover_letter(self.ctx.profile, row.job)
        if letter:
            self.detail_meta.setText(self.detail_meta.text() +
                                     f"\nCover letter: {letter['name']} — {letter['reason']}")
        self.prep_label.setText(f"prep {app.prep_answered_count}/{app.prep_question_count}"
                                if app.prep_question_count else "")
        self.status_chip.setVisible(True)
        self.status_chip.set_status(row.status)
        index = self.status_combo.findData(app.status)
        self.status_combo.setCurrentIndex(max(0, index))
        if self.interview_edit.text() != app.interview_at:
            self.interview_edit.setText(app.interview_at)
        if self.notes.toPlainText() != app.notes:
            self.notes.setPlainText(app.notes)
        self._render_history(row)

    def _render_history(self, row: TrackedApplication) -> None:
        events = row.application.history[-40:]
        if not events:
            self.history.setHtml("<p><i>No history yet.</i></p>")
            return
        items = []
        for event in reversed(events):
            when = event.get("at", "")
            if event.get("event") == "status":
                text = (f"<b>{when}</b> — status {event.get('from')} → "
                        f"<b>{event.get('to')}</b>")
            else:
                text = f"<b>{when}</b> — {event.get('event')}: {event.get('note', '')}"
            items.append(f"<li>{text}</li>")
        self.history.setHtml("<ul>" + "".join(items) + "</ul>")

    # ------------------------------------------------------------ actions #
    def _current(self) -> TrackedApplication | None:
        row = self._selected_row()
        if row is None:
            self.ctx.notify("Select an application row first.", "warning")
        return row

    def _apply_status(self) -> None:
        row = self._current()
        if row is None:
            return
        status = ApplicationStatus(self.status_combo.currentData())
        self.ctx.pipeline.set_status(row.application, status,
                                    f"set from the tracker ({status.label})")
        self.ctx.notify(f"{row.title} → {status.label}", "success")
        self.ctx.refresh_all()

    def _regret(self) -> None:
        row = self._current()
        if row is None:
            return
        self.ctx.pipeline.set_status(row.application, ApplicationStatus.REJECTED,
                                    "regret received — moved to Archive")
        self.ctx.refresh_all()
        self.ctx.notify(f"{row.title} moved to Archive (regret).", "success")

    def _prepare(self) -> None:
        row = self._current()
        if row is None:
            return

        def work():
            return self.ctx.pipeline.prepare(row.application, self.ctx.profile)

        def done(materials) -> None:
            self.refresh()
            if materials.cv and materials.cv.warning:
                self.ctx.notify(materials.cv.warning, "warning")
            else:
                self.ctx.notify(f"Materials generated for {row.title}.", "success")
            self.ctx.tabs["dashboard"].refresh()
            if materials.cv and materials.cv.text:
                self.ctx.open_preview(f"CV · {row.title}", materials.cv.text, materials.cv.path)

        self.ctx.run_task(f"Generating materials for {row.title}", work, done)

    def _open_outlook_draft(self) -> None:
        row = self._current()
        if row is None or not self.outlook_button.isEnabled():
            return
        self.outlook_button.setEnabled(False)

        def work():
            return self.ctx.pipeline.open_outlook_draft(row.application, self.ctx.profile)

        def done(mode):
            self.outlook_button.setEnabled(True)
            self.refresh()
            self.ctx.refresh_all()
            message = "Outlook draft opened with CV and cover letter. Enter the recipient and send when ready."
            if mode == "new":
                message = ("Opened the prepared email in New Outlook with CV and cover letter. "
                           "If it opens read-only, use Forward to edit it. Enter the recipient and send when ready.")
            if mode == "eml":
                message = ("Email file opened with CV and cover letter. Choose Outlook if Windows asks. "
                           "If it opens read-only, use Forward to edit it. Enter the recipient and send when ready.")
            self.ctx.notify(message + " Moved to Sent automatically; delivery is not verified.", "success")

        def failed(message):
            self.outlook_button.setEnabled(True)

        self.ctx.run_task(f"Opening an Outlook draft for {row.title}", work, done, failed)

    def _open_doc(self, kind: str) -> None:
        row = self._current()
        if row is None:
            return
        app = row.application
        path = {"cv": app.cv_path, "cover": app.cover_letter_path,
                "email": app.email_path}.get(kind, "")
        if not path or not Path(path).exists():
            self.ctx.notify("That document does not exist yet — generate materials first.",
                            "warning")
            return
        th.open_path(path)

    def _interview_prep(self) -> None:
        row = self._current()
        if row is None:
            return
        self.ctx.open_interview_prep(row)

    def _follow_up(self) -> None:
        row = self._current()
        if row is None:
            return

        def done(result) -> None:
            path, text = result
            self.refresh()
            self.ctx.notify("Follow-up e-mail drafted.", "success")
            self.ctx.open_preview("Follow-up e-mail", text, path)

        self.ctx.run_task("Drafting follow-up e-mail",
                          lambda: self.ctx.pipeline.draft_follow_up(row.application), done)

    def _postpone(self) -> None:
        row = self._current()
        if row is None:
            return
        self.ctx.pipeline.postpone_follow_up(row.application, 5)
        self.refresh()
        self.ctx.notify("Follow-up postponed by 5 days.", "info")

    def _follow_up_sent(self) -> None:
        row = self._current()
        if row is None:
            return
        try:
            self.ctx.pipeline.mark_follow_up_sent(row.application)
        except ValueError as exc:
            self.ctx.notify(str(exc), "warning")
            return
        self.refresh()
        self.ctx.tabs["dashboard"].refresh()
        self.ctx.notify("Follow-up recorded as sent; reminders updated.", "success")

    def _open_posting(self) -> None:
        row = self._current()
        if row is None:
            return
        if row.job.url:
            th.open_in_browser(row.job.url)
        else:
            self.ctx.notify("No URL stored for this posting.", "warning")

    def _save_notes(self) -> None:
        row = self._current()
        if row is None:
            return
        self.ctx.pipeline.update_notes(row.application, self.notes.toPlainText().strip())
        self.ctx.notify("Notes saved.", "success")
        self.refresh()

    def _delete(self) -> None:
        row = self._current()
        if row is None or self.view != "archive" or not row.status.is_closed:
            return
        if not self.ctx.confirm("Delete permanently",
                                f"Remove “{row.title}” at {row.company} from the tracker "
                                "for good? Generated documents stay on disk.", danger=True):
            return
        for dialog in list(getattr(self.ctx, "_previews", [])):
            if getattr(dialog, "application_id", None) == row.application.application_id:
                dialog.close()
        self.ctx.workspace.delete_application(row.application.application_id)
        self.ctx.notify("Application removed.", "info")
        self.ctx.refresh_all()

    def _delete_selected(self) -> None:
        if self.view not in ("applications", "archive"):
            return
        ids = [self.table.item(index.row(), 0).data(Qt.UserRole)
               for index in self.table.selectionModel().selectedRows()]
        if not ids:
            self.ctx.notify("Select application rows to delete first.", "info")
            return
        if not self.ctx.confirm("Delete selected permanently",
                f"Permanently delete {len(ids)} selected application(s), including their "
                "notes and history? This cannot be undone. Generated documents stay on disk.",
                danger=True):
            return
        removed = 0
        for application_id in ids:
            record = self.ctx.workspace.get_application(application_id)
            if record is None or record.status_enum not in self.statuses:
                continue
            for dialog in list(getattr(self.ctx, "_previews", [])):
                if getattr(dialog, "application_id", None) == application_id:
                    dialog.close()
            self.ctx.workspace.delete_application(application_id)
            removed += 1
        self.ctx.refresh_all()
        self.ctx.notify(f"Deleted {removed} application(s).", "info")

    def _clear(self) -> None:
        row = self._current()
        if row is None:
            return
        if row.status in (ApplicationStatus.ARCHIVED,):
            self.ctx.notify("This application is already archived.", "info")
            return
        self.ctx.pipeline.clear_application(row.application)
        self.ctx.notify(f"{row.title} moved to Archive.", "success")
        self.ctx.refresh_all()

    def _select_all(self) -> None:
        self.table.selectAll()
        if self.view == "applications":
            for index in range(self.table.rowCount()):
                self.table.item(index, 0).setCheckState(Qt.Checked)

    def _check_changed(self, item) -> None:
        if item.column() != 0 or self.view != "applications":
            return
        application_id = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            self._checked_ids.add(application_id)
        else:
            self._checked_ids.discard(application_id)
        count = sum(row.application.application_id in self._checked_ids for row in self.rows)
        self.archive_selected_button.setText(f"Archive ticked ({count})" if count else "Archive selected")

    def _add_matching_jobs(self) -> None:
        def work():
            _, added = self.ctx.pipeline.import_qualified(
                self.ctx.workspace.jobs(), self.ctx.profile,
                threshold=self.ctx.settings.min_match_score)
            self.ctx.pipeline.refresh_scores(self.ctx.profile)
            return len(added)

        def done(count):
            self.ctx.refresh_all()
            self.ctx.notify(f"Added {count} matching saved job(s) to the queue. "
                            "Archived and sent applications keep their status.", "success")

        self.ctx.run_task("Reviewing saved jobs", work, done)

    def _archive_queue(self, all_shown: bool = False) -> None:
        """Archive a snapshot of visible queue IDs, never hidden or sent records."""
        if self.view != "applications":
            return
        if all_shown:
            ids = [row.application.application_id for row in self.rows]
        else:
            ids = [row.application.application_id for row in self.rows
                   if row.application.application_id in self._checked_ids]
            if not ids:
                ids = [self.table.item(index.row(), 0).data(Qt.UserRole)
                       for index in self.table.selectionModel().selectedRows()]
        if not ids:
            self.ctx.notify("No applications to archive. Select rows or adjust the filters.", "info")
            return
        scope = "shown" if all_shown else "selected"
        if not self.ctx.confirm("Archive applications",
                f"Move {len(ids)} {scope} application(s) to Archive? "
                "Notes, history and documents are kept. You can restore them from Archive."):
            return
        moved = 0
        for application_id in ids:
            record = self.ctx.workspace.get_application(application_id)
            if record is not None and record.status_enum in VIEW_STATUSES["applications"]:
                self.ctx.pipeline.clear_application(record)
                moved += 1
        self._checked_ids.difference_update(ids)
        self.archive_selected_button.setText("Archive selected")
        self.ctx.refresh_all()
        self.ctx.notify(f"Moved {moved} application(s) to Archive.", "success")

    def _preview_auto_clear(self) -> None:
        """Dry run: report (and optionally run) the auto-clear sweep."""
        settings = self.ctx.settings
        if settings.auto_clear_days <= 0:
            self.ctx.notify("Auto-clear is off (0 days) in Settings → Autopilot. Enable it "
                            "first, then preview what the sweep would archive.", "warning")
            return

        def work():
            pending = self.ctx.pipeline.pending_auto_clear(self.ctx.profile)
            rows = []
            for app in pending:
                job = self.ctx.workspace.get_job(app.job_id)
                rows.append((job.title if job else "?", job.company if job else "?"))
            return rows

        def done(rows) -> None:
            if not rows:
                self.ctx.notify(
                    f"Nothing to auto-clear: no untouched application is older than "
                    f"{settings.auto_clear_days} day(s).", "info")
                return
            days = settings.auto_clear_days
            names = ", ".join(f"“{t}” at {c}" for t, c in rows[:4])
            if len(rows) > 4:
                names += f" (+{len(rows) - 4} more)"
            if self.ctx.confirm(
                    f"Auto-clear preview — {len(rows)} would be archived",
                    f"{names}\n\nUntouched = discovered or shortlisted and never prepared or "
                    f"sent. These are {days} day(s) old and would be archived (kept in the "
                    f"database and history, not deleted) on the next sweep. Run it now?",
                    danger=True):
                self.ctx.run_task(
                    "Auto-clearing", lambda: self.ctx.pipeline.auto_clear_unacted(self.ctx.profile),
                    lambda moved: (self.refresh(),
                                   self.ctx.tabs["dashboard"].refresh(),
                                   self.ctx.update_meta(),
                                   self.ctx.notify(
                                       f"Archived {moved} untouched application(s).", "success")))

        self.ctx.run_task("Checking auto-clear", work, done)

    def _recompute(self) -> None:
        def done(updated) -> None:
            self.refresh()
            self.ctx.notify(f"Re-scored applications ({updated} score(s) changed).", "success")

        self.ctx.run_task("Recomputing match scores",
                          lambda: self.ctx.pipeline.refresh_scores(self.ctx.profile), done)

    def _autopilot(self) -> None:
        def done(materials) -> None:
            self.refresh()
            self.ctx.notify(f"Autopilot prepared {len(materials)} application(s).", "success")

        self.ctx.run_task("Autopilot preparing materials",
                          lambda: self.ctx.pipeline.autopilot(
                              self.ctx.profile,
                              should_cancel=self.ctx.cancel_event.is_set), done)

    def _save_interview(self) -> None:
        row = self._current()
        if row is None:
            return
        text = self.interview_edit.text().strip()
        try:
            self.ctx.pipeline.set_interview(row.application, text)
        except ValueError as exc:
            self.ctx.notify(str(exc), "warning")
            return
        self.ctx.notify(f"Interview for {row.title} saved." if text
                        else f"Interview date cleared for {row.title}.", "success")
        self.refresh()

    def _export(self) -> None:
        def done(path) -> None:
            self.ctx.notify(f"Exported {path}", "success")
            th.open_path(path)

        self.ctx.run_task("Exporting tracker CSV",
                          lambda: self.ctx.pipeline.export_tracker_csv(self.ctx.profile), done)

    def _export_calendar(self) -> None:
        def done(path) -> None:
            self.ctx.notify(f"Calendar exported to {path}", "success")
            th.open_path(path)

        self.ctx.run_task("Exporting calendar (.ics)",
                          lambda: self.ctx.pipeline.export_calendar_ics(self.ctx.profile), done)


__all__ = ["COLUMNS", "ApplicationsTab"]
