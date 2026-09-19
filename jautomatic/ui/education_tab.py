"""Education & skills development tab.

Tracks learning progress in profile.extra so the feature is backward-compatible
with existing profile.json files and needs no SQLite schema migration.
"""
from __future__ import annotations

import shutil
from collections import Counter
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..models import pretty_term
from . import theme as th


COURSE_CATALOG = [
    {
        "id": "ibm-data-analytics",
        "title": "Data & Analytics learning path",
        "provider": "IBM SkillsBuild",
        "skills": ["data analysis", "excel", "data quality", "visualization", "problem solving"],
        "url": "https://skillsbuild.org/learning-catalog",
        "credential": "Free digital credentials available",
        "verified_free": True,
        "note": "Use the Data & Analytics category and choose modules that match your job gaps.",
    },
    {
        "id": "ibm-ai",
        "title": "Artificial Intelligence learning path",
        "provider": "IBM SkillsBuild",
        "skills": ["artificial intelligence", "ai", "generative ai", "prompting", "ai ethics"],
        "url": "https://skillsbuild.org/learning-catalog",
        "credential": "Free digital credentials available",
        "verified_free": True,
        "note": "Useful for AI-enabled analyst, virtual assistant and operations roles.",
    },
    {
        "id": "ibm-professional",
        "title": "Business & Professional Skills",
        "provider": "IBM SkillsBuild",
        "skills": ["customer service", "communication", "problem solving", "career skills"],
        "url": "https://skillsbuild.org/learning-catalog",
        "credential": "Free digital credentials available",
        "verified_free": True,
        "note": "Use this path to strengthen transferable skills requested across many roles.",
    },
    {
        "id": "hp-business-email",
        "title": "Business Email",
        "provider": "HP LIFE",
        "skills": ["business communication", "email", "customer service", "virtual assistant"],
        "url": "https://www.life-global.org/",
        "credential": "Free Certificate of Completion",
        "verified_free": True,
        "note": "Practical professional communication training.",
    },
    {
        "id": "hp-critical-ai",
        "title": "Critical Thinking in the AI Era",
        "provider": "HP LIFE",
        "skills": ["artificial intelligence", "ai", "critical thinking", "fact checking"],
        "url": "https://www.life-global.org/",
        "credential": "Free Certificate of Completion",
        "verified_free": True,
        "note": "Strengthens judgement and verification skills when using AI tools.",
    },
    {
        "id": "hp-agile",
        "title": "Agile Project Management",
        "provider": "HP LIFE",
        "skills": ["agile", "scrum", "kanban", "project management"],
        "url": "https://www.life-global.org/",
        "credential": "Free Certificate of Completion",
        "verified_free": True,
        "note": "Useful for operations, analyst and coordination roles.",
    },
    {
        "id": "ms-power-bi",
        "title": "Power BI learning paths",
        "provider": "Microsoft Learn",
        "skills": ["power bi", "powerbi", "dax", "data visualization", "data analysis"],
        "url": "https://learn.microsoft.com/training/powerplatform/power-bi/",
        "credential": "Training is free; certification exam is separate",
        "verified_free": False,
        "note": "Recommended when Power BI appears in job requirements. Do not treat the paid PL-300 exam as a free certificate.",
    },
]


class EducationTab(QWidget):
    page_title = "Education"
    page_subtitle = "Build job-ready skills, track free learning and keep certificates with your profile"

    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx
        self._ranked: list[tuple[dict, int, list[str]]] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.recommended_stat = th.StatCard("Recommended", "0", "Courses tied to current job gaps", "accent")
        self.progress_stat = th.StatCard("In progress", "0", "Courses currently underway", "info")
        self.completed_stat = th.StatCard("Completed", "0", "Finished learning records", "success")
        self.cert_stat = th.StatCard("Certificates", "0", "Certificates stored in JAUTOMATIC", "warning")
        for card in (self.recommended_stat, self.progress_stat, self.completed_stat, self.cert_stat):
            stats.addWidget(card)
        layout.addLayout(stats)

        filter_card = th.Card(
            "Skills development",
            "Recommendations are ranked from missing keywords in your tracked applications. "
            "Free-credential status is shown separately so paid exams are never presented as free."
        )
        row = QHBoxLayout()
        row.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter courses or skills: Power BI, AI, customer service…")
        self.search.textChanged.connect(self._fill_table)
        row.addWidget(self.search, 1)
        row.addWidget(th.button("Refresh recommendations", "primary", "", self.refresh))
        filter_card.add_layout(row)
        self.gap_line = th.label("", "muted", wrap=True)
        filter_card.add(self.gap_line)
        layout.addWidget(filter_card)

        body = QHBoxLayout()
        body.setSpacing(12)
        layout.addLayout(body, 1)

        courses = th.Card("Recommended courses", "Highest relevance appears first")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Course", "Provider", "Skills", "Credential", "Priority", "Status"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.table.doubleClicked.connect(self._open_selected)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        for col in (1, 3, 4, 5):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        courses.add(self.table)

        course_actions = QHBoxLayout()
        course_actions.addWidget(th.button("Open course", "primary", "", self._open_selected))
        course_actions.addWidget(th.button("Start", "default", "", self._mark_in_progress))
        course_actions.addWidget(th.button("Complete", "default", "", self._mark_completed))
        course_actions.addStretch(1)
        courses.add_layout(course_actions)
        body.addWidget(courses, 3)

        detail = th.Card("Learning record")
        self.detail_title = th.label("Select a course", "title", wrap=True)
        self.detail_meta = th.label("", "small", wrap=True)
        self.priority_bar = QProgressBar()
        self.priority_bar.setRange(0, 100)
        self.priority_bar.setValue(0)
        self.priority_bar.setFormat("Priority %p%")
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(True)
        self.detail.setMinimumWidth(340)
        self.certificate_line = th.label("No certificate stored.", "muted", wrap=True)
        detail.add(self.detail_title)
        detail.add(self.detail_meta)
        detail.add(self.priority_bar)
        detail.add(self.detail)
        detail.add(self.certificate_line)
        detail.add(th.button("Attach certificate", "primary", "",
                             self._attach_certificate))
        detail.add(th.button("Add course skills to profile", "default", "",
                             self._add_skills_to_profile))
        detail.add(th.button("Reset course progress", "danger", "",
                             self._reset_progress))
        body.addWidget(detail, 2)

        self.ctx.add_header_action(
            "education",
            th.button("Refresh recommendations", "primary", "", self.refresh),
        )

    # --------------------------------------------------------------- data #
    def _store(self) -> dict:
        extra = self.ctx.profile.extra
        store = extra.get("education_progress")
        if not isinstance(store, dict):
            store = {}
            extra["education_progress"] = store
        return store

    def _record(self, course_id: str) -> dict:
        store = self._store()
        record = store.get(course_id)
        if not isinstance(record, dict):
            record = {"status": "Not started", "certificate_path": "", "completed_on": ""}
            store[course_id] = record
        return record

    def _save(self) -> None:
        self.ctx.save_profile(self.ctx.profile)

    def _gap_counts(self) -> Counter:
        counts: Counter = Counter()
        try:
            rows = self.ctx.pipeline.tracker(self.ctx.profile)
        except Exception:
            rows = []
        for row in rows:
            if not row.application.status_enum.is_active:
                continue
            for skill in row.match.missing_keywords:
                key = str(skill).strip().lower()
                if key:
                    counts[key] += 1
        return counts

    def _rank_courses(self) -> None:
        gaps = self._gap_counts()
        profile_skills = self.ctx.profile.skill_set
        ranked: list[tuple[dict, int, list[str]]] = []

        for course in COURSE_CATALOG:
            skills = [s.lower() for s in course["skills"]]
            hits: list[str] = []
            score = 0
            for skill in skills:
                exact = gaps.get(skill, 0)
                fuzzy = sum(count for gap, count in gaps.items()
                            if skill in gap or gap in skill)
                weight = max(exact, fuzzy)
                if weight:
                    hits.append(skill)
                    score += min(24, 8 * weight)

            # Give useful baseline weight to courses that expand the user's
            # current field even before enough applications have been tracked.
            if any(skill in {"power bi", "powerbi", "data analysis", "artificial intelligence",
                             "ai", "customer service", "project management", "agile"}
                   for skill in skills):
                score += 12
            if any(skill in profile_skills for skill in skills):
                score += 5
            if course.get("verified_free"):
                score += 8
            score = min(100, score)
            ranked.append((course, score, hits))

        ranked.sort(key=lambda item: (-item[1], item[0]["provider"], item[0]["title"]))
        self._ranked = ranked

        if gaps:
            top = [f"{pretty_term(k)} ({v})" for k, v in gaps.most_common(8)]
            self.gap_line.setText("Most common missing job keywords: " + " · ".join(top))
        else:
            self.gap_line.setText(
                "No tracked-job skill gaps yet. Recommendations use your existing profile focus "
                "until you import or track more jobs."
            )

    # --------------------------------------------------------------- view #
    def refresh(self) -> None:
        self._rank_courses()
        self._fill_table()
        store = self._store()
        records = [r for r in store.values() if isinstance(r, dict)]
        in_progress = sum(1 for r in records if r.get("status") == "In progress")
        completed = sum(1 for r in records if r.get("status") == "Completed")
        certificates = sum(1 for r in records if r.get("certificate_path"))
        recommended = sum(1 for _, score, _ in self._ranked if score >= 20)
        self.recommended_stat.set_value(str(recommended))
        self.progress_stat.set_value(str(in_progress))
        self.completed_stat.set_value(str(completed))
        self.cert_stat.set_value(str(certificates))

    def _fill_table(self) -> None:
        if not hasattr(self, "table"):
            return
        query = self.search.text().strip().lower() if hasattr(self, "search") else ""
        rows = []
        for course, score, hits in self._ranked:
            hay = " ".join([
                course["title"], course["provider"], " ".join(course["skills"]),
                course["credential"],
            ]).lower()
            if query and query not in hay:
                continue
            rows.append((course, score, hits))

        self.table.setRowCount(len(rows))
        for row_index, (course, score, hits) in enumerate(rows):
            record = self._record(course["id"])
            values = [
                course["title"],
                course["provider"],
                ", ".join(course["skills"][:4]),
                course["credential"],
                str(score),
                record.get("status") or "Not started",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.UserRole, course["id"])
                if col == 4:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, col, item)
        if rows:
            self.table.selectRow(0)
        else:
            self.detail_title.setText("No matching courses")
            self.detail.setPlainText("Try a broader filter.")

    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        course_id = item.data(Qt.UserRole) if item else None
        for course, score, hits in self._ranked:
            if course["id"] == course_id:
                return course, score, hits
        return None

    def _show_selected(self) -> None:
        selected = self._selected()
        if not selected:
            return
        course, score, hits = selected
        record = self._record(course["id"])
        self.detail_title.setText(course["title"])
        self.detail_meta.setText(
            f'{course["provider"]} · {course["credential"]} · '
            f'{record.get("status") or "Not started"}'
        )
        self.priority_bar.setValue(score)
        gap_text = ", ".join(pretty_term(s) for s in hits) if hits else "No direct tracked-job gap yet"
        self.detail.setHtml(
            f"<b>Skills:</b> {', '.join(course['skills'])}<br><br>"
            f"<b>Why it is recommended:</b> {gap_text}<br><br>"
            f"<b>Notes:</b> {course['note']}"
        )
        path = record.get("certificate_path") or ""
        self.certificate_line.setText(
            f"Certificate: {path}" if path else "No certificate stored."
        )

    # ------------------------------------------------------------- actions #
    def _open_selected(self) -> None:
        selected = self._selected()
        if not selected:
            self.ctx.notify("Select a course first.", "warning")
            return
        th.open_in_browser(selected[0]["url"])

    def _mark_in_progress(self) -> None:
        self._set_status("In progress")

    def _mark_completed(self) -> None:
        self._set_status("Completed")

    def _set_status(self, status: str) -> None:
        selected = self._selected()
        if not selected:
            self.ctx.notify("Select a course first.", "warning")
            return
        course = selected[0]
        record = self._record(course["id"])
        record["status"] = status
        record["completed_on"] = date.today().isoformat() if status == "Completed" else ""
        self._save()
        self.refresh()
        self.ctx.notify(f'{course["title"]}: {status}.', "success")

    def _attach_certificate(self) -> None:
        selected = self._selected()
        if not selected:
            self.ctx.notify("Select a course first.", "warning")
            return
        course = selected[0]
        source, _ = QFileDialog.getOpenFileName(
            self,
            "Attach certificate",
            "",
            "Certificates (*.pdf *.png *.jpg *.jpeg *.docx);;All files (*)",
        )
        if not source:
            return
        source_path = Path(source)
        target_dir = Path(self.ctx.workspace.root) / "certificates"
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f'{course["id"]}-{source_path.name}'
        target = target_dir / safe_name
        if source_path.resolve() != target.resolve():
            shutil.copy2(source_path, target)
        record = self._record(course["id"])
        record["certificate_path"] = str(target)
        record["status"] = "Completed"
        record["completed_on"] = record.get("completed_on") or date.today().isoformat()
        self._save()
        self.refresh()
        self.ctx.notify("Certificate copied into your JAUTOMATIC workspace.", "success")

    def _add_skills_to_profile(self) -> None:
        selected = self._selected()
        if not selected:
            self.ctx.notify("Select a course first.", "warning")
            return
        course = selected[0]
        record = self._record(course["id"])
        if record.get("status") != "Completed":
            self.ctx.notify("Mark the course completed before adding its skills to your profile.",
                            "warning")
            return
        existing = {s.lower() for s in self.ctx.profile.skills}
        added = []
        for skill in course["skills"]:
            if skill.lower() not in existing:
                self.ctx.profile.skills.append(skill)
                existing.add(skill.lower())
                added.append(skill)
        self._save()
        if added:
            self.ctx.pipeline.refresh_scores(self.ctx.profile)
            self.ctx.notify("Added to profile: " + ", ".join(added), "success")
        else:
            self.ctx.notify("Those skills are already in your profile.", "info")

    def _reset_progress(self) -> None:
        selected = self._selected()
        if not selected:
            return
        course = selected[0]
        if not self.ctx.confirm(
            "Reset course progress",
            f'Reset progress for {course["title"]}? The stored certificate link will also be cleared.',
            danger=True,
        ):
            return
        self._store().pop(course["id"], None)
        self._save()
        self.refresh()
        self.ctx.notify("Course progress reset.", "info")
