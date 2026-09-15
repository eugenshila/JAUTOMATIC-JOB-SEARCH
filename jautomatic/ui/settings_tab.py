"""Settings tab: sources, search defaults, documents, autopilot, data & theme."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLineEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from .. import APP_TITLE, __version__
from ..models import AppSettings
from ..services.cv_generator import TEMPLATE_LABELS, TEMPLATES
from . import theme as th

FORMATS = [("Microsoft Word (.docx)", "docx"), ("Markdown (.md)", "md"), ("Plain text (.txt)", "txt")]


class SettingsTab(QWidget):
    page_title = "Settings"
    page_subtitle = "Sources, defaults, documents and where your data lives"

    def __init__(self, ctx) -> None:  # noqa: ANN001 - MainWindow
        super().__init__()
        self.ctx = ctx
        self.source_boxes: dict[str, QCheckBox] = {}
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

        columns = QHBoxLayout()
        columns.setSpacing(14)
        layout.addLayout(columns)
        left = QVBoxLayout()
        left.setSpacing(14)
        columns.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(14)
        columns.addLayout(right, 1)

        # sources -------------------------------------------------------- #
        sources = th.Card("Job sources", "Enabled boards are queried in parallel")
        for name, source in self.ctx.pipeline.scraper.sources.items():
            box = QCheckBox(f"{source.label} — {source.description}")
            box.setToolTip(source.homepage)
            box.toggled.connect(self._mark_dirty)
            self.source_boxes[name] = box
            sources.add(box)
        credentials = QFormLayout()
        credentials.setSpacing(8)
        self.adzuna_id = QLineEdit()
        self.adzuna_id.setPlaceholderText("Adzuna app id")
        self.adzuna_key = QLineEdit()
        self.adzuna_key.setPlaceholderText("Adzuna app key")
        self.adzuna_country = QComboBox()
        self.adzuna_country.setEditable(True)
        self.adzuna_country.addItems(["gb", "us", "de", "fr", "nl", "pl", "ca", "au", "in", "es"])
        for widget in (self.adzuna_id, self.adzuna_key):
            widget.textChanged.connect(self._mark_dirty)
        self.adzuna_country.currentTextChanged.connect(self._mark_dirty)
        credentials.addRow("Adzuna app id", self.adzuna_id)
        credentials.addRow("Adzuna app key", self.adzuna_key)
        credentials.addRow("Adzuna country", self.adzuna_country)
        sources.add_layout(credentials)
        sources.add(th.label("Adzuna is optional — the other three boards need no key at all. "
                             "Register free at developer.adzuna.com.", "small", wrap=True))
        left.addWidget(sources)

        # search defaults ------------------------------------------------ #
        search = th.Card("Search defaults")
        form = QFormLayout()
        form.setSpacing(8)
        self.results_per_source = QSpinBox()
        self.results_per_source.setRange(5, 100)
        self.timeout = QSpinBox()
        self.timeout.setRange(5, 60)
        self.timeout.setSuffix(" s")
        self.min_salary = QSpinBox()
        self.min_salary.setRange(0, 2_000_000)
        self.min_salary.setSingleStep(1000)
        self.min_salary.setGroupSeparatorShown(True)
        self.remote_only = QCheckBox("Remote postings only")
        self.exclude_keywords = QLineEdit()
        self.exclude_keywords.setPlaceholderText("unpaid, commission only, crypto, doordash")
        for widget in (self.results_per_source, self.timeout, self.min_salary):
            widget.valueChanged.connect(self._mark_dirty)
        self.remote_only.toggled.connect(self._mark_dirty)
        self.exclude_keywords.textChanged.connect(self._mark_dirty)
        form.addRow("Results per source", self.results_per_source)
        form.addRow("Request timeout", self.timeout)
        form.addRow("Minimum salary", self.min_salary)
        form.addRow("", self.remote_only)
        form.addRow("Exclude keywords", self.exclude_keywords)
        search.add_layout(form)
        left.addWidget(search)

        # documents ------------------------------------------------------ #
        documents = th.Card("Documents", "What gets generated for each application")
        form = QFormLayout()
        form.setSpacing(8)
        self.cv_template = QComboBox()
        for template in TEMPLATES:
            self.cv_template.addItem(TEMPLATE_LABELS[template], template)
        self.export_format = QComboBox()
        for caption, value in FORMATS:
            self.export_format.addItem(caption, value)
        self.with_cover_letter = QCheckBox("Generate a cover letter")
        self.with_email = QCheckBox("Generate an application e-mail draft")
        for widget in (self.cv_template, self.export_format):
            widget.currentIndexChanged.connect(self._mark_dirty)
        for widget in (self.with_cover_letter, self.with_email):
            widget.toggled.connect(self._mark_dirty)
        form.addRow("CV template", self.cv_template)
        form.addRow("Export format", self.export_format)
        form.addRow("", self.with_cover_letter)
        form.addRow("", self.with_email)
        documents.add_layout(form)
        documents.add(th.button("Preview the selected template", "default", "",
                                self._preview_template))
        left.addWidget(documents)
        left.addStretch(1)

        # autopilot ------------------------------------------------------ #
        autopilot = th.Card("Autopilot", "Hands-off preparation of your best matches")
        form = QFormLayout()
        form.setSpacing(8)
        self.autopilot = QCheckBox("Enable autopilot")
        self.autopilot.setToolTip("Runs after an import and from the Dashboard/Applications tabs")
        self.autopilot_min_score = QSpinBox()
        self.autopilot_min_score.setRange(0, 100)
        self.autopilot_min_score.setSuffix(" / 100")
        self.autopilot_max = QSpinBox()
        self.autopilot_max.setRange(1, 50)
        self.follow_up_days = QSpinBox()
        self.follow_up_days.setRange(1, 90)
        self.follow_up_days.setSuffix(" days")
        self.autopilot.toggled.connect(self._mark_dirty)
        self.autopilot_min_score.valueChanged.connect(self._mark_dirty)
        self.autopilot_max.valueChanged.connect(self._mark_dirty)
        self.follow_up_days.valueChanged.connect(self._mark_dirty)
        form.addRow("", self.autopilot)
        form.addRow("Score threshold", self.autopilot_min_score)
        form.addRow("Max per run", self.autopilot_max)
        form.addRow("Follow-up after", self.follow_up_days)
        autopilot.add_layout(form)
        right.addWidget(autopilot)

        # appearance ----------------------------------------------------- #
        appearance = th.Card("Appearance")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Midnight (dark)", "midnight")
        self.theme_combo.addItem("Daylight (light)", "daylight")
        self.theme_combo.currentIndexChanged.connect(self._apply_theme)
        appearance.add(self.theme_combo)
        right.addWidget(appearance)

        # data ----------------------------------------------------------- #
        data = th.Card("Data", "Everything is plain files you can back up or move")
        self.data_dir = QLineEdit()
        self.data_dir.setReadOnly(True)
        self.data_dir.setText(str(self.ctx.workspace.root))
        data.add(self.data_dir)
        data.add(th.label("profile.json · settings.json · jautomatic.sqlite3 · documents/ · "
                          "exports/", "small", wrap=True))
        row = QHBoxLayout()
        row.addWidget(th.button("Open data folder", "default", "",
                                lambda: th.open_in_file_manager(self.ctx.workspace.root)))
        row.addWidget(th.button("Open documents", "default", "",
                                lambda: th.open_in_file_manager(self.ctx.workspace.documents_dir)))
        row.addWidget(th.button("Backup data folder…", "default", "Copy everything to a folder",
                                self._backup))
        data.add_layout(row)
        row_two = QHBoxLayout()
        row_two.addWidget(th.button("Export tracker CSV", "ghost", "", self._export_csv))
        row_two.addWidget(th.button("Export calendar (.ics)", "ghost",
                                    "Interviews + follow-ups as an iCalendar file",
                                    self._export_calendar))
        row_two.addWidget(th.button("Clear job cache", "danger",
                                    "Delete stored postings and tracker entries", self._clear))
        data.add_layout(row_two)
        right.addWidget(data)

        # about ---------------------------------------------------------- #
        about = th.Card("About")
        about.add(th.label(f"{APP_TITLE} {__version__}", "title"))
        about.add(th.label(
            "A local-first job-search autopilot: it pulls postings from public job boards, scores "
            "them against your profile, then writes a tailored CV, cover letter and e-mail draft "
            "for every application you choose — no accounts, no cloud, no data leaves your machine.",
            "muted", wrap=True))
        about.add(th.label("Job data: Remotive · Arbeitnow · RemoteOK · Adzuna. "
                           "Documents: python-docx. Interface: PySide6.", "small", wrap=True))
        right.addWidget(about)
        right.addStretch(1)

        # footer --------------------------------------------------------- #
        footer = th.Card("")
        row_three = QHBoxLayout()
        self.save_button = th.button("Save settings", "primary", "Ctrl+S", self.save)
        row_three.addWidget(self.save_button)
        row_three.addWidget(th.button("Reload", "default", "Discard unsaved changes", self.load))
        row_three.addWidget(th.button("Restore defaults", "ghost", "",
                                      self._restore_defaults))
        row_three.addStretch(1)
        self.status_line = th.label("All changes saved.", "small")
        row_three.addWidget(self.status_line)
        footer.add_layout(row_three)
        layout.addWidget(footer)
        layout.addStretch(1)
        self.ctx.add_header_action("settings", self.save_button)

    # ------------------------------------------------------------ loading #
    def load(self) -> None:
        settings = self.ctx.settings
        enabled = set(settings.enabled_sources)
        for name, box in self.source_boxes.items():
            box.setChecked(name in enabled)
        self.adzuna_id.setText(settings.adzuna_app_id)
        self.adzuna_key.setText(settings.adzuna_app_key)
        self.adzuna_country.setCurrentText(settings.adzuna_country)
        self.results_per_source.setValue(settings.results_per_source)
        self.timeout.setValue(settings.request_timeout)
        self.min_salary.setValue(settings.min_salary)
        self.remote_only.setChecked(settings.remote_only)
        self.exclude_keywords.setText(settings.exclude_keywords)
        index = self.cv_template.findData(settings.cv_template)
        self.cv_template.setCurrentIndex(max(0, index))
        index = self.export_format.findData(settings.export_format)
        self.export_format.setCurrentIndex(max(0, index))
        self.with_cover_letter.setChecked(settings.include_cover_letter)
        self.with_email.setChecked(settings.include_email_draft)
        self.autopilot.setChecked(settings.autopilot)
        self.autopilot_min_score.setValue(settings.autopilot_min_score)
        self.autopilot_max.setValue(settings.autopilot_max_per_run)
        self.follow_up_days.setValue(settings.follow_up_days)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(settings.theme)))
        self.status_line.setText("All changes saved.")

    def refresh(self) -> None:
        self.data_dir.setText(str(self.ctx.workspace.root))

    def _mark_dirty(self, *_: object) -> None:
        self.status_line.setText("Unsaved changes — press Save settings.")

    def collect(self) -> AppSettings:
        settings = self.ctx.settings
        settings.enabled_sources = [name for name, box in self.source_boxes.items()
                                    if box.isChecked()]
        settings.adzuna_app_id = self.adzuna_id.text().strip()
        settings.adzuna_app_key = self.adzuna_key.text().strip()
        settings.adzuna_country = self.adzuna_country.currentText().strip() or "gb"
        settings.results_per_source = self.results_per_source.value()
        settings.request_timeout = self.timeout.value()
        settings.min_salary = self.min_salary.value()
        settings.remote_only = self.remote_only.isChecked()
        settings.exclude_keywords = self.exclude_keywords.text().strip()
        settings.cv_template = self.cv_template.currentData() or "modern"
        settings.export_format = self.export_format.currentData() or "docx"
        settings.include_cover_letter = self.with_cover_letter.isChecked()
        settings.include_email_draft = self.with_email.isChecked()
        settings.autopilot = self.autopilot.isChecked()
        settings.autopilot_min_score = self.autopilot_min_score.value()
        settings.autopilot_max_per_run = self.autopilot_max.value()
        settings.follow_up_days = self.follow_up_days.value()
        return settings

    # ------------------------------------------------------------ actions #
    def save(self) -> None:
        settings = self.collect()
        self.ctx.save_settings(settings)
        self.status_line.setText("Saved.")
        self.ctx.notify("Settings saved.", "success")
        self.ctx.refresh_all()
        self.ctx.update_meta()

    def _apply_theme(self) -> None:
        name = self.theme_combo.currentData() or "midnight"
        settings = self.collect()
        settings.theme = name
        self.ctx.save_settings(settings)
        self.ctx.apply_theme(name)

    def _restore_defaults(self) -> None:
        if not self.ctx.confirm("Restore defaults",
                                "Reset every setting (profile and applications are kept)?"):
            return
        defaults = AppSettings(data_dir=str(self.ctx.workspace.root))
        self.ctx.save_settings(defaults)
        self.load()
        self.ctx.apply_theme(defaults.theme)
        self.ctx.notify("Settings restored to defaults.", "success")

    def _preview_template(self) -> None:
        template = self.cv_template.currentData() or "modern"
        profile = self.ctx.profile

        def work():  # noqa: ANN202
            return self.ctx.pipeline.cv_generator.generate(profile, None, template, None,
                                                           self.export_format.currentData())

        def done(document) -> None:  # noqa: ANN001
            self.ctx.open_preview(f"CV template · {TEMPLATE_LABELS.get(template, template)}",
                                  document.text, None)

        self.ctx.run_task("Rendering template preview", work, done)

    def _export_csv(self) -> None:
        def done(path) -> None:  # noqa: ANN001
            self.ctx.notify(f"Exported {path}", "success")

        self.ctx.run_task("Exporting tracker CSV",
                          lambda: self.ctx.pipeline.export_tracker_csv(self.ctx.profile), done)

    def _export_calendar(self) -> None:
        def done(path) -> None:  # noqa: ANN001
            self.ctx.notify(f"Calendar exported to {path}", "success")
            th.open_path(path)

        self.ctx.run_task("Exporting calendar (.ics)",
                          lambda: self.ctx.pipeline.export_calendar_ics(self.ctx.profile), done)

    def _backup(self) -> None:
        target = QFileDialog.getExistingDirectory(self, "Choose a folder for the backup")
        if not target:
            return
        destination = Path(target) / f"jautomatic-backup-{self.ctx.workspace.root.name}"
        try:
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(self.ctx.workspace.root, destination,
                            ignore=shutil.ignore_patterns("*.wal", "*.shm", "__pycache__"))
        except OSError as exc:
            self.ctx.notify(f"Backup failed: {exc}", "error")
            return
        self.ctx.notify(f"Backed up to {destination}", "success")
        th.open_in_file_manager(destination)

    def _clear(self) -> None:
        if not self.ctx.confirm("Clear job cache",
                                "Delete all stored postings and every tracked application? "
                                "Generated documents stay on disk.", danger=True):
            return
        self.ctx.workspace.clear_jobs()
        self.ctx.notify("Job cache and tracker cleared.", "info")
        self.ctx.refresh_all()


__all__ = ["SettingsTab", "FORMATS"]
