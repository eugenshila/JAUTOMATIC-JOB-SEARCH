"""Interview prep window: notes + question bank for one application.

Opened from the Applications tab.  Left: the questions grouped by category
(with answered/starred markers); right: the selected question's hint and your
answer, plus the free-text notes sheet.  Everything is saved on the
application row via ``pipeline.save_interview_prep`` — there is no separate
file until you press *Export sheet*.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..services.application_pipeline import TrackedApplication
from ..services.interview_prep import (
    CATEGORIES,
    CATEGORY_LABELS,
    InterviewPrep,
    PrepQuestion,
)
from . import theme as th


class InterviewPrepDialog(QDialog):
    def __init__(self, ctx, row: TrackedApplication, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.row = row
        self.application_id = row.application.application_id
        self.prep: InterviewPrep = ctx.pipeline.interview_prep(row.application)
        self._current: PrepQuestion | None = None
        self._dirty = False
        self.setWindowTitle(f"Interview prep · {row.title} @ {row.company}")
        self.resize(1040, 700)
        self._build_ui()
        self._fill_tree()
        self.notes.setPlainText(self.prep.notes)

    # ------------------------------------------------------------------ UI #
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel(f"{self.row.title} · {self.row.company}")
        title.setObjectName("PageTitle")
        head.addWidget(title, 1)
        self.progress = th.label("", "small")
        head.addWidget(self.progress)
        layout.addLayout(head)
        bits = [self.row.job.display_location, self.row.job.salary_text,
                f"match {self.row.score}/100"]
        if self.row.application.interview_at:
            bits.append(f"interview {self.row.application.interview_at}")
        layout.addWidget(th.label(" · ".join(b for b in bits if b), "muted", wrap=True))

        actions = QHBoxLayout()
        actions.setSpacing(6)
        actions.addWidget(th.button("Generate question bank", "primary",
                                    "Derive questions from the posting, the match analysis and "
                                    "your achievements. Re-running adds new questions and keeps "
                                    "your answers.", self._generate))
        actions.addWidget(th.button("Export sheet (.md)", "default",
                                    "Write the notes + questions next to your CV and letter",
                                    self._export))
        actions.addWidget(th.button("Preview", "ghost", "", self._preview))
        actions.addStretch(1)
        actions.addWidget(th.button("Save", "default", "Store notes and answers", self.save))
        actions.addWidget(th.button("Close", "ghost", "", self.close))
        layout.addLayout(actions)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        # left: question tree + add row
        left = th.Card("Question bank", "★ = starred · ✓ = answered")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setIndentation(14)
        self.tree.itemSelectionChanged.connect(self._show_selected)
        self.tree.setMinimumWidth(380)
        left.add(self.tree)
        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self.new_category = QComboBox()
        for category in CATEGORIES:
            self.new_category.addItem(CATEGORY_LABELS[category], category)
        self.new_question = QLineEdit()
        self.new_question.setPlaceholderText("Add your own question…")
        self.new_question.returnPressed.connect(self._add_question)
        add_row.addWidget(self.new_category)
        add_row.addWidget(self.new_question, 1)
        add_row.addWidget(th.button("Add", "default", "", self._add_question))
        left.add_layout(add_row)
        splitter.addWidget(left)

        # right: selected question + notes
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        self.question_card = th.Card("Question")
        self.question_text = th.label("Select a question on the left.", "title", wrap=True)
        self.question_hint = th.label("", "muted", wrap=True)
        self.answer = QPlainTextEdit()
        self.answer.setPlaceholderText("Your prepared answer — bullet points are fine. "
                                       "For STAR questions: Situation, Task, Action, Result.")
        self.answer.textChanged.connect(self._answer_edited)
        self.question_card.add(self.question_text)
        self.question_card.add(self.question_hint)
        self.question_card.add(self.answer)
        q_actions = QHBoxLayout()
        q_actions.setSpacing(6)
        self.star_button = th.button("★ Star", "ghost", "Mark as a must-rehearse question",
                                     self._toggle_star)
        q_actions.addWidget(self.star_button)
        q_actions.addWidget(th.button("Remove question", "danger", "", self._remove_question))
        q_actions.addStretch(1)
        self.question_card.add_layout(q_actions)
        right_layout.addWidget(self.question_card, 3)

        notes_card = th.Card("Notes", "Company research, interviewer names, logistics, "
                                      "salary talk, take-home deadlines")
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Interviewers · what the team builds · recent news · "
                                      "questions they asked last round · what to wear/bring…")
        self.notes.textChanged.connect(self._mark_dirty)
        notes_card.add(self.notes)
        right_layout.addWidget(notes_card, 2)
        splitter.addWidget(right)
        splitter.setSizes([420, 620])

        self.status_line = th.label("", "small")
        layout.addWidget(self.status_line)

    # ------------------------------------------------------------- state #
    def _fill_tree(self, select_id: str | None = None) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)
        select_item: QTreeWidgetItem | None = None
        for category, items in self.prep.by_category():
            answered = sum(1 for q in items if q.answered)
            parent = QTreeWidgetItem([f"{CATEGORY_LABELS[category]}  ({answered}/{len(items)})"])
            parent.setFont(0, bold)
            parent.setFlags(parent.flags() & ~Qt.ItemIsSelectable)
            self.tree.addTopLevelItem(parent)
            for question in items:
                marks = ("★ " if question.starred else "") + ("✓ " if question.answered else "")
                child = QTreeWidgetItem([f"{marks}{question.question}"])
                child.setData(0, Qt.UserRole, question.id)
                child.setToolTip(0, question.hint or question.question)
                if question.source == "custom":
                    child.setForeground(0, QColor(th.current_theme()["accent"]))
                parent.addChild(child)
                if select_id and question.id == select_id:
                    select_item = child
            parent.setExpanded(True)
        self.tree.blockSignals(False)
        self.progress.setText(self.prep.progress_text)
        if select_item is not None:
            self.tree.setCurrentItem(select_item)
        elif self._current is None and self.prep.questions:
            first = self.tree.topLevelItem(0)
            if first is not None and first.childCount():
                self.tree.setCurrentItem(first.child(0))
        if not self.prep.questions:
            self._show_question(None)

    def _selected_question(self) -> PrepQuestion | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        question_id = item.data(0, Qt.UserRole)
        return self.prep.find(question_id) if question_id else None

    def _show_selected(self) -> None:
        self._show_question(self._selected_question())

    def _show_question(self, question: PrepQuestion | None) -> None:
        self._current = question
        self.answer.blockSignals(True)
        if question is None:
            self.question_text.setText("Select a question on the left — or generate the bank."
                                       if not self.prep.questions
                                       else "Select a question on the left.")
            self.question_hint.setText("")
            self.answer.setPlainText("")
            self.answer.setEnabled(False)
            self.star_button.setEnabled(False)
        else:
            self.question_text.setText(question.question)
            self.question_hint.setText(question.hint)
            self.answer.setPlainText(question.answer)
            self.answer.setEnabled(True)
            self.star_button.setEnabled(True)
            self.star_button.setText("★ Unstar" if question.starred else "★ Star")
        self.answer.blockSignals(False)

    def _answer_edited(self) -> None:
        if self._current is None:
            return
        was_answered = self._current.answered
        self._current.answer = self.answer.toPlainText()
        self._mark_dirty()
        if was_answered != self._current.answered:
            self._fill_tree(select_id=self._current.id)

    def _mark_dirty(self, *_: object) -> None:
        self._dirty = True
        self.status_line.setText("Unsaved changes — press Save (also saved on close).")

    # ------------------------------------------------------------ actions #
    def _generate(self) -> None:
        self._sync_notes()
        self.ctx.pipeline.save_interview_prep(self.application_id, self.prep)

        def work():
            return self.ctx.pipeline.generate_interview_prep(self.application_id, self.ctx.profile)

        def done(result) -> None:
            prep, added = result
            self.prep = prep
            self._dirty = False
            self._fill_tree(select_id=self._current.id if self._current else None)
            self.status_line.setText(f"Question bank updated: {added} new question(s), "
                                     f"{len(prep.questions)} total.")
            self.ctx.notify(f"{added} new question(s) for {self.row.title}.", "success")
            self.ctx.tabs["sent"].refresh()

        self.ctx.run_task("Generating interview questions", work, done)

    def _add_question(self) -> None:
        text = self.new_question.text().strip()
        if not text:
            return
        category = self.new_category.currentData() or "technical"
        question = self.prep.add_question(text, category)
        self.new_question.clear()
        self._mark_dirty()
        self._fill_tree(select_id=question.id)

    def _remove_question(self) -> None:
        if self._current is None:
            return
        if self._current.answered and not self.ctx.confirm(
                "Remove question", "This question has an answer. Remove it anyway?", danger=True):
            return
        self.prep.remove_question(self._current.id)
        self._current = None
        self._mark_dirty()
        self._fill_tree()

    def _toggle_star(self) -> None:
        if self._current is None:
            return
        self._current.starred = not self._current.starred
        self._mark_dirty()
        self._fill_tree(select_id=self._current.id)

    def _sync_notes(self) -> None:
        self.prep.notes = self.notes.toPlainText()

    def save(self, *, quiet: bool = False) -> None:
        self._sync_notes()
        self.ctx.pipeline.save_interview_prep(self.application_id, self.prep,
                                             note=f"saved ({self.prep.progress_text})")
        self._dirty = False
        self.status_line.setText("Saved.")
        if not quiet:
            self.ctx.notify("Interview prep saved.", "success")
        self.ctx.tabs["sent"].refresh()

    def _export(self) -> None:
        self.save(quiet=True)

        def done(path) -> None:
            self.status_line.setText(f"Exported {path}")
            self.ctx.notify(f"Prep sheet exported to {path.name}", "success")
            th.open_path(path)

        self.ctx.run_task("Exporting interview prep",
                          lambda: self.ctx.pipeline.export_interview_prep(self.application_id,
                                                                          self.ctx.profile), done)

    def _preview(self) -> None:
        from ..services.interview_prep import render_prep_markdown

        self._sync_notes()
        application = self.ctx.workspace.get_application(self.application_id) or self.row.application
        markdown = render_prep_markdown(self.prep, self.ctx.profile, self.row.job, application)
        self.ctx.open_preview(f"Interview prep · {self.row.title}", markdown, None)

    # ----------------------------------------------------------- lifecycle #
    def closeEvent(self, event) -> None:
        if self._dirty and not getattr(self.ctx, "_closing", False):
            self.save(quiet=True)
        super().closeEvent(event)


__all__ = ["InterviewPrepDialog"]
