"""Skills Improvement & Learning tab."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QComboBox, QTextBrowser,
    QVBoxLayout, QWidget,
)

from ..learning import CATEGORIES, LearningCourse, LearningStore, STATUSES
from ..services.learning_search import CourseResult, search_courses


class LearningTab(QWidget):
    page_title = "Skills Improvement & Learning"
    page_subtitle = "Find free learning resources, track progress, and attach certificates"

    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx
        self.store = LearningStore(ctx.workspace.root)
        self.results: list[CourseResult] = []
        self._build_ui()
        self._refresh_saved()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.category = QComboBox(); self.category.addItems(CATEGORIES)
        self.query = QLineEdit(); self.query.setPlaceholderText("Optional topic or keyword")
        form.addRow("Category", self.category); form.addRow("Search", self.query)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        search = QPushButton("Search free courses"); search.clicked.connect(self.search)
        save = QPushButton("Save selected course"); save.clicked.connect(self.save_selected)
        buttons.addWidget(search); buttons.addWidget(save); layout.addLayout(buttons)
        self.results_list = QListWidget(); layout.addWidget(QLabel("Search results")); layout.addWidget(self.results_list, 2)
        saved_row = QHBoxLayout()
        self.saved_list = QListWidget(); saved_row.addWidget(self.saved_list, 2)
        controls = QVBoxLayout()
        self.status = QComboBox(); self.status.addItems(STATUSES)
        mark = QPushButton("Update status"); mark.clicked.connect(self.update_status)
        cert = QPushButton("Attach certificate"); cert.clicked.connect(self.attach_certificate)
        open_link = QPushButton("Open course link"); open_link.clicked.connect(self.open_link)
        controls.addWidget(QLabel("Selected saved course")); controls.addWidget(self.status)
        controls.addWidget(mark); controls.addWidget(cert); controls.addWidget(open_link); controls.addStretch()
        saved_row.addLayout(controls, 1); layout.addWidget(QLabel("My learning")); layout.addLayout(saved_row, 2)
        self.message = QTextBrowser(); self.message.setMaximumHeight(90); layout.addWidget(self.message)

    def search(self) -> None:
        try:
            self.message.setPlainText("Searching trusted course indexes…")
            self.results = search_courses(self.category.currentText(), self.query.text().strip())
            self.results_list.clear()
            for course in self.results:
                item = QListWidgetItem(f"{course.title} — {course.certificate_status}")
                item.setData(32, course); self.results_list.addItem(item)
            self.message.setPlainText(f"Found {len(self.results)} candidate course(s). Always verify the provider's final price and certificate terms.")
        except Exception as exc:  # noqa: BLE001 - surface network failures in the UI
            self.message.setPlainText(f"Search failed: {exc}")

    def save_selected(self) -> None:
        item = self.results_list.currentItem()
        if not item: return
        result: CourseResult = item.data(32)
        try:
            self.store.add(LearningCourse(title=result.title, provider=result.provider, url=result.url,
                                          category=result.category, description=result.description,
                                          level=result.level, duration=result.duration,
                                          certificate_status=result.certificate_status))
            self._refresh_saved(); self.message.setPlainText("Course saved.")
        except ValueError as exc: self.message.setPlainText(str(exc))

    def _refresh_saved(self) -> None:
        self.saved_list.clear()
        for course in self.store.courses:
            item = QListWidgetItem(f"[{course.status}] {course.title} — {course.category}")
            item.setData(32, course); self.saved_list.addItem(item)

    def _selected(self) -> LearningCourse | None:
        item = self.saved_list.currentItem()
        return item.data(32) if item else None

    def _sync_profile(self) -> None:
        profile = self.ctx.reload_profile()
        existing = {skill.strip().casefold() for skill in profile.skills if skill.strip()}
        changed = False
        for course in self.store.completed_courses():
            skill = course.title.strip()
            if skill and skill.casefold() not in existing:
                profile.skills.append(skill)
                existing.add(skill.casefold())
                changed = True
        if changed:
            self.ctx.save_profile(profile)

    def update_status(self) -> None:
        course = self._selected()
        if not course: return
        course.status = self.status.currentText()
        if course.completed: course.mark_completed(course.completed_on or None)
        self.store.update(course); self._sync_profile(); self._refresh_saved()
        self.message.setPlainText("Completed learning has been added to your profile skills.")

    def attach_certificate(self) -> None:
        course = self._selected()
        if not course: return
        path, _ = QFileDialog.getOpenFileName(self, "Attach certificate", "", "Certificates (*.pdf *.jpg *.jpeg *.png)")
        if not path: return
        try:
            self.store.attach_certificate(course.id, path); self._sync_profile(); self._refresh_saved()
            self.message.setPlainText("Certificate saved, course marked completed, and profile updated.")
        except (OSError, ValueError, KeyError) as exc: QMessageBox.warning(self, "Certificate", str(exc))

    def open_link(self) -> None:
        course = self._selected()
        if course: QDesktopServices.openUrl(QUrl(course.url))
