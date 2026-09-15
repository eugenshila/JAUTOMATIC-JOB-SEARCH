"""Profile tab: the single source of truth for everything the generators use."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QScrollArea,
                               QSpinBox, QVBoxLayout, QWidget)

from ..models import SAMPLE_PROFILE, EducationEntry, ExperienceEntry, Profile
from ..services.cover_letter import TONE_LABELS, TONES
from ..services.cv_generator import TEMPLATE_LABELS
from . import theme as th

class ExperienceDialog(QDialog):
    """Add/edit one work-experience entry (bullets separated by new lines)."""

    def __init__(self, entry: ExperienceEntry | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit experience" if entry else "Add experience")
        self.resize(560, 520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)
        entry = entry or ExperienceEntry()
        self.title = QLineEdit(entry.title)
        self.company = QLineEdit(entry.company)
        self.location = QLineEdit(entry.location)
        self.start = QLineEdit(entry.start)
        self.start.setPlaceholderText("2021-04 or 2021")
        self.end = QLineEdit(entry.end)
        self.end.setPlaceholderText("leave empty for “present”")
        self.summary = QPlainTextEdit(entry.summary)
        self.summary.setFixedHeight(70)
        self.bullets = QPlainTextEdit("\n".join(entry.highlights))
        self.bullets.setPlaceholderText("One achievement per line, e.g.\n"
                                        "Cut p95 latency 62% by adding query caching")
        form.addRow("Job title", self.title)
        form.addRow("Company", self.company)
        form.addRow("Location", self.location)
        form.addRow("Start", self.start)
        form.addRow("End", self.end)
        form.addRow("Summary", self.summary)
        form.addRow("Highlights", self.bullets)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_entry(self) -> ExperienceEntry:
        bullets = [line.strip(" -•\t") for line in self.bullets.toPlainText().splitlines()
                   if line.strip()]
        return ExperienceEntry(title=self.title.text().strip(), company=self.company.text().strip(),
                               location=self.location.text().strip(), start=self.start.text().strip(),
                               end=self.end.text().strip(), summary=self.summary.toPlainText().strip(),
                               highlights=bullets)


class EducationDialog(QDialog):
    def __init__(self, entry: EducationEntry | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit education" if entry else "Add education")
        self.resize(520, 320)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        entry = entry or EducationEntry()
        self.degree = QLineEdit(entry.degree)
        self.school = QLineEdit(entry.school)
        self.location = QLineEdit(entry.location)
        self.start = QLineEdit(entry.start)
        self.end = QLineEdit(entry.end)
        self.details = QPlainTextEdit(entry.details)
        self.details.setFixedHeight(80)
        form.addRow("Degree", self.degree)
        form.addRow("School", self.school)
        form.addRow("Location", self.location)
        form.addRow("Start", self.start)
        form.addRow("End", self.end)
        form.addRow("Details", self.details)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_entry(self) -> EducationEntry:
        return EducationEntry(degree=self.degree.text().strip(), school=self.school.text().strip(),
                              location=self.location.text().strip(), start=self.start.text().strip(),
                              end=self.end.text().strip(),
                              details=self.details.toPlainText().strip())


class ProfileTab(QWidget):
    page_title = "Profile"
    page_subtitle = "Your data feeds the CV generator, the matcher and every letter"

    def __init__(self, ctx) -> None:  # noqa: ANN001 - MainWindow
        super().__init__()
        self.ctx = ctx
        self._dirty = False
        self._loading = False
        self.fields: dict[str, QWidget] = {}
        self._build_ui()
        self.load()

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

        grid = QHBoxLayout()
        grid.setSpacing(14)
        layout.addLayout(grid)

        left = QVBoxLayout()
        left.setSpacing(14)
        grid.addLayout(left, 3)
        right = QVBoxLayout()
        right.setSpacing(14)
        grid.addLayout(right, 2)

        # identity ------------------------------------------------------- #
        identity = th.Card("Identity", "Used in the CV header, letters and e-mail signatures")
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)
        for key, caption, placeholder in [
            ("full_name", "Full name", "Alex Doe"),
            ("headline", "Headline", "Senior Python Engineer · data platforms"),
            ("email", "E-mail", "alex@example.com"),
            ("phone", "Phone", "+49 30 1234 5678"),
            ("location", "Location", "Berlin, Germany"),
            ("links", "Links", "LinkedIn: … | GitHub: …"),
        ]:
            field = QLineEdit()
            field.setPlaceholderText(placeholder)
            field.textChanged.connect(self._mark_dirty)
            self.fields[key] = field
            form.addRow(caption, field)
        identity.add_layout(form)
        left.addWidget(identity)

        # summary -------------------------------------------------------- #
        summary_card = th.Card("Professional summary", "2-3 sentences; reused verbatim in CVs")
        self.summary = QPlainTextEdit()
        self.summary.setFixedHeight(110)
        self.summary.textChanged.connect(self._mark_dirty)
        summary_card.add(self.summary)
        left.addWidget(summary_card)

        # skills --------------------------------------------------------- #
        skills_card = th.Card("Skills & languages",
                              "Comma separated. The matcher checks each posting against these")
        self.skills = QLineEdit()
        self.skills.setPlaceholderText("python, fastapi, postgresql, docker, aws")
        self.skills.textChanged.connect(self._mark_dirty)
        self.skills.textChanged.connect(self._update_skill_preview)
        same_line = QHBoxLayout()
        same_line.addWidget(th.label("Skills", "muted"))
        same_line.addWidget(self.skills, 1)
        skills_card.add_layout(same_line)
        self.skill_preview = th.label("", "small", wrap=True)
        skills_card.add(self.skill_preview)
        self.languages = QLineEdit()
        self.languages.setPlaceholderText("English (C1), German (B2)")
        self.languages.textChanged.connect(self._mark_dirty)
        lang_row = QHBoxLayout()
        lang_row.addWidget(th.label("Languages", "muted"))
        lang_row.addWidget(self.languages, 1)
        skills_card.add_layout(lang_row)
        self.fields["skills"] = self.skills
        self.fields["languages"] = self.languages
        left.addWidget(skills_card)

        # experience ----------------------------------------------------- #
        experience_card = th.Card("Experience", "Newest first. Bullets become the CV's achievements")
        self.experience_list = QListWidget()
        self.experience_list.setMinimumHeight(150)
        experience_card.add(self.experience_list)
        row = QHBoxLayout()
        row.addWidget(th.button("Add role", "primary", "", self._add_experience))
        row.addWidget(th.button("Edit", "default", "", self._edit_experience))
        row.addWidget(th.button("Remove", "danger", "", self._remove_experience))
        row.addWidget(th.button("Move up", "ghost", "", lambda: self._move_experience(-1)))
        row.addWidget(th.button("Move down", "ghost", "", lambda: self._move_experience(1)))
        row.addStretch(1)
        experience_card.add_layout(row)
        left.addWidget(experience_card)

        # education ------------------------------------------------------ #
        education_card = th.Card("Education")
        self.education_list = QListWidget()
        self.education_list.setMinimumHeight(110)
        education_card.add(self.education_list)
        row = QHBoxLayout()
        row.addWidget(th.button("Add", "primary", "", self._add_education))
        row.addWidget(th.button("Edit", "default", "", self._edit_education))
        row.addWidget(th.button("Remove", "danger", "", self._remove_education))
        row.addStretch(1)
        education_card.add_layout(row)
        left.addWidget(education_card)
        left.addStretch(1)

        # preferences ---------------------------------------------------- #
        prefs = th.Card("Job preferences", "Drives ranking, filters and autopilot")
        prefs_form = QFormLayout()
        prefs_form.setSpacing(8)
        self.desired_titles = QLineEdit()
        self.desired_titles.setPlaceholderText("Python Engineer, Backend Engineer")
        self.desired_titles.textChanged.connect(self._mark_dirty)
        self.desired_locations = QLineEdit()
        self.desired_locations.setPlaceholderText("Berlin, Remote")
        self.desired_locations.textChanged.connect(self._mark_dirty)
        self.seniority = QComboBox()
        self.seniority.addItems(["", "junior", "mid", "senior", "lead", "principal"])
        self.seniority.currentIndexChanged.connect(self._mark_dirty)
        self.remote_only = QCheckBox("Only show remote postings")
        self.remote_only.toggled.connect(self._mark_dirty)
        self.relocate = QCheckBox("Open to relocation")
        self.relocate.toggled.connect(self._mark_dirty)
        self.salary_floor = QSpinBox()
        self.salary_floor.setRange(0, 2_000_000)
        self.salary_floor.setSingleStep(1000)
        self.salary_floor.setGroupSeparatorShown(True)
        self.salary_floor.setPrefix("min ")
        self.salary_floor.valueChanged.connect(self._mark_dirty)
        self.currency = QComboBox()
        self.currency.addItems(["USD", "EUR", "GBP", "PLN", "CHF", "SEK", "CAD", "AUD"])
        self.currency.currentIndexChanged.connect(self._mark_dirty)
        prefs_form.addRow("Target titles", self.desired_titles)
        prefs_form.addRow("Preferred locations", self.desired_locations)
        prefs_form.addRow("Seniority", self.seniority)
        prefs_form.addRow("", self.remote_only)
        prefs_form.addRow("", self.relocate)
        money_row = QHBoxLayout()
        money_row.addWidget(self.salary_floor)
        money_row.addWidget(self.currency)
        money_widget = QWidget()
        money_widget.setLayout(money_row)
        prefs_form.addRow("Salary floor", money_widget)
        prefs.add_layout(prefs_form)
        for widget in (self.desired_titles, self.desired_locations, self.salary_floor):
            self.fields[widget.objectName()] = widget
        right.addWidget(prefs)

        # letters -------------------------------------------------------- #
        letters = th.Card("Letter settings", "Tone, greeting and signature for cover letters")
        letter_form = QFormLayout()
        letter_form.setSpacing(8)
        self.tone = QComboBox()
        for tone in TONES:
            self.tone.addItem(TONE_LABELS[tone], tone)
        self.tone.currentIndexChanged.connect(self._mark_dirty)
        self.greeting = QLineEdit()
        self.greeting.setPlaceholderText("Dear Hiring Team,")
        self.greeting.textChanged.connect(self._mark_dirty)
        self.signature = QPlainTextEdit()
        self.signature.setFixedHeight(80)
        self.signature.setPlaceholderText("Name, title, e-mail, phone")
        self.signature.textChanged.connect(self._mark_dirty)
        letter_form.addRow("Tone", self.tone)
        letter_form.addRow("Greeting", self.greeting)
        letter_form.addRow("Signature", self.signature)
        letters.add_layout(letter_form)
        right.addWidget(letters)

        # completeness + actions ---------------------------------------- #
        readiness = th.Card("Readiness")
        self.completeness = QLabel("0%")
        self.completeness.setObjectName("H1")
        note = th.label("Complete profiles match better and need less manual editing.",
                        "muted", wrap=True)
        readiness.add(self.completeness)
        readiness.add(note)
        self.status_line = th.label("All changes saved.", "small")
        readiness.add(self.status_line)
        right.addWidget(readiness)

        actions = th.Card("Actions")
        self.save_button = th.button("Save profile", "primary", "Ctrl+S", self.save)
        self.save_button.setShortcut("Ctrl+S")
        actions.add(self.save_button)
        actions.add(th.button("Reload from disk", "default", "Discard unsaved edits", self.load))
        actions.add(th.button("Load example profile", "default",
                              "Fill every field with a realistic sample", self._load_sample))
        actions.add(th.button("Preview CV", "default", "Render a CV with the current settings",
                              self._preview_cv))
        actions.add(th.button("Export profile JSON", "ghost", "", self._export_json))
        actions.add(th.button("Import profile JSON", "ghost", "", self._import_json))
        right.addWidget(actions)
        right.addStretch(1)

        self.ctx.add_header_action("profile", self.save_button)

    # ------------------------------------------------------------ loading #
    def load(self) -> None:
        profile = self.ctx.reload_profile()
        self._loading = True
        self.fields["full_name"].setText(profile.full_name)
        self.fields["headline"].setText(profile.headline)
        self.fields["email"].setText(profile.email)
        self.fields["phone"].setText(profile.phone)
        self.fields["location"].setText(profile.location)
        self.fields["links"].setText(profile.links)
        self.summary.setPlainText(profile.summary)
        self.skills.setText(", ".join(profile.skills))
        self.languages.setText(profile.languages)
        self.desired_titles.setText(", ".join(profile.desired_titles))
        self.desired_locations.setText(", ".join(profile.desired_locations))
        self.seniority.setCurrentText(profile.seniority)
        self.remote_only.setChecked(profile.remote_only)
        self.relocate.setChecked(profile.willing_to_relocate)
        self.salary_floor.setValue(profile.salary_floor)
        self.currency.setCurrentText(profile.currency or "USD")
        index = self.tone.findData(profile.tone)
        self.tone.setCurrentIndex(index if index >= 0 else 0)
        self.greeting.setText(profile.greeting)
        self.signature.setPlainText(profile.signature)
        self._refresh_experience_list()
        self._refresh_education_list()
        self._update_skill_preview()
        self._dirty = False
        self._loading = False
        self._update_completeness()

    def refresh(self) -> None:
        """Called on tab switch: don't clobber unsaved edits."""
        if not self._dirty:
            self.load()
        else:
            self._update_completeness()
            self.status_line.setText("Unsaved changes — press Save profile.")

    # -------------------------------------------------------------- state #
    def _mark_dirty(self, *_: object) -> None:
        if self._loading:
            return
        self._dirty = True
        self.status_line.setText("Unsaved changes — press Save profile.")
        self._update_completeness()

    def collect(self) -> Profile:
        profile = self.ctx.profile
        profile.full_name = self.fields["full_name"].text().strip()
        profile.headline = self.fields["headline"].text().strip()
        profile.email = self.fields["email"].text().strip()
        profile.phone = self.fields["phone"].text().strip()
        profile.location = self.fields["location"].text().strip()
        profile.links = self.fields["links"].text().strip()
        profile.summary = self.summary.toPlainText().strip()
        profile.skills = [s.strip() for s in self.skills.text().split(",") if s.strip()]
        profile.languages = self.languages.text().strip()
        profile.desired_titles = [s.strip() for s in self.desired_titles.text().split(",")
                                  if s.strip()]
        profile.desired_locations = [s.strip() for s in self.desired_locations.text().split(",")
                                     if s.strip()]
        profile.seniority = self.seniority.currentText()
        profile.remote_only = self.remote_only.isChecked()
        profile.willing_to_relocate = self.relocate.isChecked()
        profile.salary_floor = self.salary_floor.value()
        profile.currency = self.currency.currentText()
        profile.tone = self.tone.currentData() or "professional"
        profile.greeting = self.greeting.text().strip() or "Dear Hiring Team,"
        profile.signature = self.signature.toPlainText().strip()
        return profile

    def _update_completeness(self) -> None:
        try:
            percent = self.collect().completeness()
        except Exception:  # noqa: BLE001 - fields may not exist yet
            percent = 0
        self.completeness.setText(f"{percent}%")

    def _update_skill_preview(self) -> None:
        skills = [s.strip() for s in self.skills.text().split(",") if s.strip()]
        if not skills:
            self.skill_preview.setText("No skills yet — five or more gives the matcher "
                                       "something to work with.")
            return
        self.skill_preview.setText(f"{len(skills)} skill(s): " + " · ".join(skills[:12])
                                   + (" …" if len(skills) > 12 else ""))

    # ---------------------------------------------------------- experience #
    def _refresh_experience_list(self) -> None:
        self.experience_list.clear()
        for entry in self.ctx.profile.experience:
            text = f"{entry.title or 'Role'} — {entry.company or 'Company'}  ({entry.period})"
            item = QListWidgetItem(text)
            item.setToolTip("\n".join(entry.as_bullets()[:6]))
            self.experience_list.addItem(item)

    def _refresh_education_list(self) -> None:
        self.education_list.clear()
        for entry in self.ctx.profile.education:
            label = " — ".join(p for p in (entry.degree, entry.school) if p) or "Education"
            self.education_list.addItem(QListWidgetItem(f"{label}  ({entry.period})"))

    def _add_experience(self) -> None:
        dialog = ExperienceDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.ctx.profile.experience.insert(0, dialog.result_entry())
            self._refresh_experience_list()
            self._mark_dirty()

    def _edit_experience(self) -> None:
        index = self.experience_list.currentRow()
        if index < 0:
            self.ctx.notify("Select a role to edit.", "warning")
            return
        dialog = ExperienceDialog(self.ctx.profile.experience[index], parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.ctx.profile.experience[index] = dialog.result_entry()
            self._refresh_experience_list()
            self._mark_dirty()

    def _remove_experience(self) -> None:
        index = self.experience_list.currentRow()
        if index < 0:
            return
        if self.ctx.confirm("Remove role", "Remove this role from your profile?"):
            del self.ctx.profile.experience[index]
            self._refresh_experience_list()
            self._mark_dirty()

    def _move_experience(self, delta: int) -> None:
        index = self.experience_list.currentRow()
        target = index + delta
        entries = self.ctx.profile.experience
        if index < 0 or not 0 <= target < len(entries):
            return
        entries[index], entries[target] = entries[target], entries[index]
        self._refresh_experience_list()
        self.experience_list.setCurrentRow(target)
        self._mark_dirty()

    def _add_education(self) -> None:
        dialog = EducationDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.ctx.profile.education.append(dialog.result_entry())
            self._refresh_education_list()
            self._mark_dirty()

    def _edit_education(self) -> None:
        index = self.education_list.currentRow()
        if index < 0:
            self.ctx.notify("Select an entry to edit.", "warning")
            return
        dialog = EducationDialog(self.ctx.profile.education[index], parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.ctx.profile.education[index] = dialog.result_entry()
            self._refresh_education_list()
            self._mark_dirty()

    def _remove_education(self) -> None:
        index = self.education_list.currentRow()
        if index < 0:
            return
        del self.ctx.profile.education[index]
        self._refresh_education_list()
        self._mark_dirty()

    # ------------------------------------------------------------ actions #
    def save(self) -> None:
        profile = self.collect()
        self.ctx.save_profile(profile)
        self._dirty = False
        self.status_line.setText("Saved.")
        self.ctx.notify("Profile saved.", "success")
        self._update_completeness()
        self.ctx._update_meta()

    def _load_sample(self) -> None:
        if not self.ctx.confirm("Load example profile",
                                "Replace the current profile with a realistic sample?"):
            return
        profile = Profile.from_dict(SAMPLE_PROFILE)
        self.ctx.save_profile(profile)
        self.load()
        self.ctx.refresh_all()
        self.ctx.notify("Example profile loaded — edit it to make it yours.", "success")

    def _preview_cv(self) -> None:
        if self._dirty:
            self.save()
        template = self.ctx.settings.cv_template
        profile = self.ctx.profile

        def work():  # noqa: ANN202
            generator = self.ctx.pipeline.cv_generator
            return generator.generate(profile, None, template, None, self.ctx.settings.export_format)

        def done(document) -> None:  # noqa: ANN001
            self.ctx.open_preview(f"CV preview · {TEMPLATE_LABELS.get(template, template)}",
                                  document.text, None)

        self.ctx.run_task("Rendering CV preview", work, done)

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export profile", "profile.json",
                                              "JSON files (*.json)")
        if not path:
            return
        if self._dirty:
            self.save()
        Path(path).write_text(json.dumps(self.ctx.profile.to_dict(), indent=2), encoding="utf-8")
        self.ctx.notify(f"Profile exported to {path}", "success")

    def _import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import profile", "", "JSON files (*.json)")
        if not path:
            return
        try:
            profile = Profile.from_dict(json.loads(Path(path).read_text("utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            self.ctx.notify(f"Could not read that file: {exc}", "error")
            return
        self.ctx.save_profile(profile)
        self.load()
        self.ctx.refresh_all()
        self.ctx.notify("Profile imported.", "success")


__all__ = ["ProfileTab", "ExperienceDialog", "EducationDialog", "SAMPLE_PROFILE"]
