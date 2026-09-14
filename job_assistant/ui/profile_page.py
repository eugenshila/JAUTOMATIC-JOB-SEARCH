from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget, QLineEdit

from job_assistant.config.settings import AppPaths
from job_assistant.database.repository import Repository
from job_assistant.services.cv_service import store_master_cv, suggest_profile_from_text
from job_assistant.services.profile_service import form_from_profile, profile_from_form
from job_assistant.ui.widgets import Card, action_button, page_header, section_label


class ProfilePage(QWidget):
    saved = Signal()

    def __init__(self, repository: Repository, paths: AppPaths, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.paths = paths
        self.fields: dict[str, QLineEdit | QPlainTextEdit] = {}
        self._build()
        self.load_profile()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 26, 30, 24)
        title, subtitle = page_header("Master CV & profile", "Keep one source of truth. Every future tailored CV will be generated as a separate version.")
        outer.addWidget(title)
        outer.addWidget(subtitle)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 14, 12, 20)
        layout.setSpacing(16)

        upload_card = Card()
        upload_layout = QVBoxLayout(upload_card)
        upload_layout.setContentsMargins(20, 18, 20, 18)
        top = QHBoxLayout()
        copy = QVBoxLayout()
        copy.addWidget(section_label("Master CV document"))
        self.cv_status = QLabel("No Master CV uploaded yet. Accepted formats: PDF, DOCX, DOC.")
        self.cv_status.setObjectName("muted")
        self.cv_status.setWordWrap(True)
        copy.addWidget(self.cv_status)
        top.addLayout(copy, 1)
        upload = action_button("Upload Master CV", True)
        upload.clicked.connect(self.upload_cv)
        top.addWidget(upload)
        upload_layout.addLayout(top)
        self.extracted_preview = QPlainTextEdit()
        self.extracted_preview.setReadOnly(True)
        self.extracted_preview.setPlaceholderText("Extracted text will appear here after upload. Review the structured fields below before saving.")
        self.extracted_preview.setMaximumHeight(130)
        upload_layout.addWidget(self.extracted_preview)
        layout.addWidget(upload_card)

        contact_card = Card()
        contact_layout = QVBoxLayout(contact_card)
        contact_layout.setContentsMargins(20, 18, 20, 18)
        contact_layout.addWidget(section_label("Contact and positioning"))
        contact_grid = QGridLayout()
        contact_grid.setHorizontalSpacing(14)
        contact_grid.setVerticalSpacing(8)
        self._add_line(contact_grid, "Full name", "full_name", 0, 0)
        self._add_line(contact_grid, "Email", "email", 0, 1)
        self._add_line(contact_grid, "Phone", "phone", 1, 0)
        self._add_line(contact_grid, "Professional headline", "headline", 1, 1)
        contact_layout.addLayout(contact_grid)
        layout.addWidget(contact_card)

        details_card = Card()
        details_layout = QVBoxLayout(details_card)
        details_layout.setContentsMargins(20, 18, 20, 18)
        details_layout.addWidget(section_label("Structured professional profile"))
        details = QGridLayout()
        details.setHorizontalSpacing(14)
        details.setVerticalSpacing(12)
        self._add_text(details, "Professional summary", "summary", 0, 0, height=100)
        self._add_text(details, "Professional experience", "experience", 0, 1, height=130)
        self._add_text(details, "Education", "education", 1, 0, height=90)
        self._add_text(details, "Qualifications", "qualifications", 1, 1, height=90)
        self._add_text(details, "Certifications", "certifications", 2, 0, height=90)
        self._add_text(details, "Achievements", "achievements", 2, 1, height=90)
        self._add_text(details, "Management experience", "management_experience", 3, 0, height=90)
        self._add_text(details, "Years of experience", "years_experience", 3, 1, height=55)
        details_layout.addLayout(details)
        layout.addWidget(details_card)

        skills_card = Card()
        skills_layout = QVBoxLayout(skills_card)
        skills_layout.setContentsMargins(20, 18, 20, 18)
        skills_layout.addWidget(section_label("Skills, titles and preferences"))
        skills = QGridLayout()
        skills.setHorizontalSpacing(14)
        skills.setVerticalSpacing(12)
        self._add_text(skills, "Technical skills (one per line)", "technical_skills", 0, 0, height=90)
        self._add_text(skills, "Software skills (one per line)", "software_skills", 0, 1, height=90)
        self._add_text(skills, "Industry experience (one per line)", "industry_experience", 1, 0, height=80)
        self._add_text(skills, "Job titles (one per line)", "job_titles", 1, 1, height=80)
        self._add_text(skills, "Preferred locations (one per line)", "preferred_locations", 2, 0, height=80)
        self._add_text(skills, "Languages (one per line)", "languages", 2, 1, height=80)
        self._add_text(skills, "Relocation willingness", "relocation_willingness", 3, 0, height=70)
        skills_layout.addLayout(skills)
        layout.addWidget(skills_card)

        buttons = QHBoxLayout()
        buttons.addStretch()
        save = action_button("Save profile", True)
        save.clicked.connect(self.save_profile)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    def _add_line(self, grid: QGridLayout, label: str, key: str, row: int, col: int) -> None:
        wrapper = QVBoxLayout()
        wrapper.setSpacing(5)
        label_widget = QLabel(label)
        label_widget.setObjectName("muted")
        editor = QLineEdit()
        editor.setPlaceholderText(label)
        self.fields[key] = editor
        wrapper.addWidget(label_widget)
        wrapper.addWidget(editor)
        grid.addLayout(wrapper, row, col)

    def _add_text(self, grid: QGridLayout, label: str, key: str, row: int, col: int, *, height: int) -> None:
        wrapper = QVBoxLayout()
        wrapper.setSpacing(5)
        label_widget = QLabel(label)
        label_widget.setObjectName("muted")
        editor = QPlainTextEdit()
        editor.setPlaceholderText(label)
        editor.setMinimumHeight(height)
        self.fields[key] = editor
        wrapper.addWidget(label_widget)
        wrapper.addWidget(editor)
        grid.addLayout(wrapper, row, col)

    def upload_cv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select Master CV", "", "CV files (*.pdf *.docx *.doc)")
        if not path:
            return
        try:
            stored, text = store_master_cv(path, self.paths.master_cv_dir)
            self.repository.add_master_cv(path, stored, text)
            self.extracted_preview.setPlainText(text or "No text could be extracted from this legacy DOC file. You can still keep the original safely stored.")
            hints = suggest_profile_from_text(text)
            for key, value in hints.items():
                editor = self.fields.get(key)
                if editor and not _get_editor(editor).strip():
                    _set_editor(editor, value)
            self.cv_status.setText(f"Master CV stored safely as {stored.name}. Review the fields and save your profile.")
            self.cv_status.setObjectName("success")
            self.cv_status.style().polish(self.cv_status)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "CV upload failed", str(exc))

    def load_profile(self) -> None:
        values = form_from_profile(self.repository.get_profile())
        for key, editor in self.fields.items():
            _set_editor(editor, values.get(key, ""))
        cv = self.repository.latest_master_cv()
        if cv:
            self.cv_status.setText(f"Master CV: {Path(cv['stored_path']).name} · uploaded {cv['created_at']}")
            self.extracted_preview.setPlainText(cv["extracted_text"] or "No extractable text stored for this file.")

    def save_profile(self) -> None:
        values = {key: _get_editor(editor) for key, editor in self.fields.items()}
        self.repository.save_profile(profile_from_form(values))
        self.cv_status.setText("Profile saved locally. No factual CV content was changed.")
        self.cv_status.setObjectName("success")
        self.cv_status.style().polish(self.cv_status)
        self.saved.emit()


def _get_editor(editor: QLineEdit | QPlainTextEdit) -> str:
    return editor.text() if isinstance(editor, QLineEdit) else editor.toPlainText()


def _set_editor(editor: QLineEdit | QPlainTextEdit, value: str) -> None:
    if isinstance(editor, QLineEdit):
        editor.setText(value)
    else:
        editor.setPlainText(value)
