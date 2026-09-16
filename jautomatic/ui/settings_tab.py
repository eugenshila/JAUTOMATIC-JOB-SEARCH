"""Settings tab: sources, search defaults, documents, autopilot, data & theme."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import APP_TITLE, __version__
from ..models import AppSettings
from ..services.cv_generator import template_label
from . import theme as th

FORMATS = [("Microsoft Word (.docx)", "docx"), ("Markdown (.md)", "md"), ("Plain text (.txt)", "txt")]


class SettingsTab(QWidget):
    page_title = "Settings"
    page_subtitle = "Sources, defaults, documents and where your data lives"

    def __init__(self, ctx) -> None:
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
        self.adzuna_country.addItems([
            "gb", "us", "de", "fr", "nl", "pl", "ca", "au", "in", "es",
            "it", "nz", "at", "ie", "be", "ch", "mx", "br", "sg", "id", "za",
        ])
        for widget in (self.adzuna_id, self.adzuna_key):
            widget.textChanged.connect(self._mark_dirty)
        self.adzuna_country.currentTextChanged.connect(self._mark_dirty)
        credentials.addRow("Adzuna app id", self.adzuna_id)
        credentials.addRow("Adzuna app key", self.adzuna_key)
        credentials.addRow("Adzuna country", self.adzuna_country)
        sources.add_layout(credentials)
        sources.add(th.label("Adzuna is optional — Remotive, Arbeitnow, RemoteOK, Himalayas "
                             "and UAE AI jobs need no key. Register free at "
                             "developer.adzuna.com.", "small", wrap=True))
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
        self.min_match_score = QSpinBox()
        self.min_match_score.setRange(0, 100)
        self.min_match_score.setSuffix(" / 100")
        self.min_match_score.setToolTip("Results below this match score are hidden "
                                        "from the search table (0 = off)")
        self.remote_only = QCheckBox("Remote postings only")
        self.exclude_keywords = QLineEdit()
        self.exclude_keywords.setPlaceholderText("unpaid, commission only, crypto, doordash")
        for widget in (self.results_per_source, self.timeout, self.min_salary,
                       self.min_match_score):
            widget.valueChanged.connect(self._mark_dirty)
        self.remote_only.toggled.connect(self._mark_dirty)
        self.exclude_keywords.textChanged.connect(self._mark_dirty)
        form.addRow("Results per source", self.results_per_source)
        form.addRow("Request timeout", self.timeout)
        form.addRow("Minimum salary", self.min_salary)
        form.addRow("Minimum match score", self.min_match_score)
        form.addRow("", self.remote_only)
        form.addRow("Exclude keywords", self.exclude_keywords)
        search.add_layout(form)
        left.addWidget(search)

        # documents ------------------------------------------------------ #
        documents = th.Card("Documents", "What gets generated for each application")
        form = QFormLayout()
        form.setSpacing(8)
        self.cv_template = QComboBox()
        self._fill_templates()
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
        template_row = QHBoxLayout()
        template_row.setSpacing(6)
        template_row.addWidget(th.button("Preview the selected template", "default", "",
                                         self._preview_template))
        template_row.addWidget(th.button("New custom template", "default",
                                         "Write an annotated starter .md into the templates "
                                         "folder and open it in your editor",
                                         self._new_template))
        template_row.addWidget(th.button("Templates folder", "ghost",
                                         "Drop your own .md templates here",
                                         self._open_templates_dir))
        template_row.addWidget(th.button("Reload", "ghost",
                                         "Re-scan the templates folder", self._reload_templates))
        template_row.addStretch(1)
        documents.add_layout(template_row)
        self.template_status = th.label("", "small", wrap=True)
        documents.add(self.template_status)
        left.addWidget(documents)

        # AI writing (optional, local-only) ------------------------------- #
        ai = th.Card("AI writing (optional)", "Local AI cover letters — nothing leaves "
                     "your machine")
        form = QFormLayout()
        form.setSpacing(8)
        self.llm_provider = QComboBox()
        self.llm_provider.addItem("Off — deterministic template", "none")
        self.llm_provider.addItem("Local AI (Ollama)", "ollama")
        self.llm_model = QLineEdit()
        self.llm_model.setPlaceholderText("llama3.2")
        self.llm_base_url = QLineEdit()
        self.llm_base_url.setPlaceholderText("http://localhost:11434")
        self.llm_provider.currentIndexChanged.connect(self._mark_dirty)
        self.llm_model.textChanged.connect(self._mark_dirty)
        self.llm_base_url.textChanged.connect(self._mark_dirty)
        form.addRow("Writer", self.llm_provider)
        form.addRow("Model", self.llm_model)
        form.addRow("Ollama server", self.llm_base_url)
        ai.add_layout(form)
        row_ai = QHBoxLayout()
        row_ai.addWidget(th.button("Test connection", "default", "", self._test_llm))
        row_ai.addStretch(1)
        ai.add_layout(row_ai)
        ai.add(th.label("Requires the free Ollama app (ollama.com) running locally. The "
                        "tone follows your profile tone. If Ollama is off or slow, the "
                        "deterministic template is used instead.", "small", wrap=True))
        left.addWidget(ai)
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
        self.follow_up_repeat = QSpinBox()
        self.follow_up_repeat.setRange(1, 90)
        self.follow_up_repeat.setSuffix(" days")
        self.follow_up_nudges = QSpinBox()
        self.follow_up_nudges.setRange(1, 10)
        self.follow_up_nudges.setPrefix("max ")
        self.auto_clear_days = QSpinBox()
        self.auto_clear_days.setRange(0, 90)
        self.auto_clear_days.setSpecialValueText("off")
        self.auto_clear_days.setSuffix(" days")
        self.auto_clear_days.setToolTip(
            "Applications that are still discovered/shortlisted (never prepared or sent) "
            "are archived automatically once they have been tracked for this long. "
            "0 = off. Runs on startup and each background refresh.")
        self.autopilot.toggled.connect(self._mark_dirty)
        self.autopilot_min_score.valueChanged.connect(self._mark_dirty)
        self.autopilot_max.valueChanged.connect(self._mark_dirty)
        self.follow_up_days.valueChanged.connect(self._mark_dirty)
        self.follow_up_repeat.valueChanged.connect(self._mark_dirty)
        self.follow_up_nudges.valueChanged.connect(self._mark_dirty)
        self.auto_clear_days.valueChanged.connect(self._mark_dirty)
        form.addRow("", self.autopilot)
        form.addRow("Score threshold", self.autopilot_min_score)
        form.addRow("Max per run", self.autopilot_max)
        form.addRow("First follow-up after", self.follow_up_days)
        form.addRow("Between follow-ups", self.follow_up_repeat)
        form.addRow("Follow-ups (ladder)", self.follow_up_nudges)
        form.addRow("Auto-clear untouched after", self.auto_clear_days)
        autopilot.add_layout(form)
        autopilot.add(th.label(
            "Follow-ups escalate: each draft is more direct, and once the ladder is spent "
            "the application stops being “due” — mark it interview/offer/rejected to stop "
            "them sooner.", "small", wrap=True))
        autopilot.add(th.label(
            "Untouched = discovered/shortlisted and never prepared or sent. Cleared "
            "applications are archived (out of the active queue) — the database and "
            "history are kept, and you can filter them back in.", "small", wrap=True))
        right.addWidget(autopilot)

        # background refresh & notifications ---------------------------- #
        refresh_card = th.Card("Background refresh",
                               "Re-scrape the enabled boards on a timer; new roles pop up "
                               "in a desktop notification")
        form = QFormLayout()
        form.setSpacing(8)
        self.auto_refresh = QCheckBox("Refresh job boards in the background")
        self.auto_refresh.setToolTip("Runs even while the window is minimized; the Search "
                                     "tab keeps the latest results")
        self.auto_refresh_minutes = QSpinBox()
        self.auto_refresh_minutes.setRange(5, 720)
        self.auto_refresh_minutes.setSingleStep(5)
        self.auto_refresh_minutes.setSuffix(" min")
        self.notify_new = QCheckBox("Notify me when refresh finds fresh roles")
        self.auto_refresh.toggled.connect(self._mark_dirty)
        self.auto_refresh_minutes.valueChanged.connect(self._mark_dirty)
        self.notify_new.toggled.connect(self._mark_dirty)
        form.addRow("", self.auto_refresh)
        form.addRow("Every", self.auto_refresh_minutes)
        form.addRow("", self.notify_new)
        refresh_card.add_layout(form)
        refresh_card.add(th.label("It only re-scrapes boards you already enabled and never "
                                  "auto-applies for anything. Fresh postings are announced in "
                                  "a tray notification and shown in the Search tab.",
                                  "small", wrap=True))
        right.addWidget(refresh_card)

        # appearance ----------------------------------------------------- #
        appearance = th.Card("Appearance")
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Midnight (dark)", "midnight")
        self.theme_combo.addItem("Black & Green (dark)", "blackgreen")
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
            "A local-first job-search autopilot: it pulls postings from public job boards, "
            "scores them against your profile, then writes a tailored CV, cover letter "
            "and e-mail draft for every application you choose — no accounts, no cloud, "
            "no data leaves your machine. Untouched applications are archived automatically.",
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
        self.min_match_score.setValue(settings.min_match_score)
        self.remote_only.setChecked(settings.remote_only)
        self.exclude_keywords.setText(settings.exclude_keywords)
        self._fill_templates(keep=settings.cv_template)
        index = self.export_format.findData(settings.export_format)
        self.export_format.setCurrentIndex(max(0, index))
        self.with_cover_letter.setChecked(settings.include_cover_letter)
        self.with_email.setChecked(settings.include_email_draft)
        self.autopilot.setChecked(settings.autopilot)
        self.autopilot_min_score.setValue(settings.autopilot_min_score)
        self.autopilot_max.setValue(settings.autopilot_max_per_run)
        self.follow_up_days.setValue(settings.follow_up_days)
        self.follow_up_repeat.setValue(settings.follow_up_repeat_days)
        self.follow_up_nudges.setValue(settings.follow_up_max_nudges)
        self.auto_clear_days.setValue(settings.auto_clear_days)
        self.auto_refresh.setChecked(settings.auto_refresh_enabled)
        self.auto_refresh_minutes.setValue(settings.auto_refresh_minutes)
        self.notify_new.setChecked(settings.notify_new_matches)
        index = self.llm_provider.findData(settings.llm_provider if
                                           settings.llm_provider in ("none", "ollama") else "none")
        self.llm_provider.setCurrentIndex(max(0, index))
        self.llm_model.setText(settings.llm_model)
        self.llm_base_url.setText(settings.llm_base_url)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(settings.theme)))
        self.theme_combo.blockSignals(False)
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
        settings.min_match_score = self.min_match_score.value()
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
        settings.follow_up_repeat_days = self.follow_up_repeat.value()
        settings.follow_up_max_nudges = self.follow_up_nudges.value()
        settings.auto_clear_days = self.auto_clear_days.value()
        settings.auto_refresh_enabled = self.auto_refresh.isChecked()
        settings.auto_refresh_minutes = self.auto_refresh_minutes.value()
        settings.notify_new_matches = self.notify_new.isChecked()
        settings.llm_provider = self.llm_provider.currentData() or "none"
        settings.llm_model = self.llm_model.text().strip() or "llama3.2"
        settings.llm_base_url = self.llm_base_url.text().strip() or "http://localhost:11434"
        return settings

    # ------------------------------------------------------------ actions #
    def save(self) -> None:
        settings = self.collect()
        self.ctx.save_settings(settings)
        self.status_line.setText("Saved.")
        self.ctx.notify("Settings saved.", "success")
        self.ctx.refresh_all()
        self.ctx.update_meta()

    def _test_llm(self) -> None:
        base = self.llm_base_url.text().strip() or "http://localhost:11434"

        def work():
            from ..services.cover_letter import ollama_ping

            return ollama_ping(base)

        def done(version) -> None:
            self.ctx.notify(f"Ollama {version} is reachable at {base}.", "success")

        def failed(message: str) -> None:
            self.ctx.notify(f"Ollama test failed — {message}", "error")

        self.ctx.run_task("Testing the Ollama connection", work, done, failed)

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

    # ---------------------------------------------------------- templates #
    def _fill_templates(self, keep: str | None = None) -> None:
        """Built-ins + valid custom files; broken custom files are reported, not listed."""
        generator = self.ctx.pipeline.cv_generator
        wanted = keep if keep is not None else (self.cv_template.currentData() or "modern")
        self.cv_template.blockSignals(True)
        self.cv_template.clear()
        for name, label in generator.available_templates():
            self.cv_template.addItem(label, name)
        index = self.cv_template.findData(wanted)
        self.cv_template.setCurrentIndex(max(0, index))
        self.cv_template.blockSignals(False)
        custom = generator.registry.list()
        broken = [t for t in custom if not t.ok]
        good = [t for t in custom if t.ok]
        bits = []
        if good:
            bits.append(f"{len(good)} custom template(s) in {generator.registry.directory}")
        else:
            bits.append(f"No custom templates yet — drop .md files into "
                        f"{generator.registry.directory} or press “New custom template”.")
        for item in broken:
            bits.append(f"⚠ {item.path.name}: {item.error}")
        if index < 0 and wanted:
            bits.append(f"⚠ Saved template “{wanted}” is unavailable; “modern” will be used.")
        if hasattr(self, "template_status"):
            self.template_status.setText("\n".join(bits))

    def _reload_templates(self) -> None:
        self._fill_templates()
        self.ctx.notify("Templates reloaded.", "info")

    def _open_templates_dir(self) -> None:
        directory = self.ctx.pipeline.cv_generator.registry.ensure_directory()
        if directory is not None:
            th.open_in_file_manager(directory)

    def _new_template(self) -> None:
        registry = self.ctx.pipeline.cv_generator.registry
        try:
            path = registry.create_starter()
        except OSError as exc:
            self.ctx.notify(f"Could not write the template: {exc}", "error")
            return
        self._fill_templates(keep=f"custom:{path.name}")
        self._mark_dirty()
        self.ctx.notify(f"Created {path.name} — edit it, then Save settings to use it.",
                        "success")
        th.open_path(path)

    def _preview_template(self) -> None:
        template = self.cv_template.currentData() or "modern"
        profile = self.ctx.profile

        def work():
            return self.ctx.pipeline.cv_generator.generate(profile, None, template, None,
                                                           self.export_format.currentData())

        def done(document) -> None:
            if document.warning:
                self.ctx.notify(document.warning, "warning")
            self.ctx.open_preview(f"CV template · {template_label(document.template)}",
                                  document.text, None)

        self.ctx.run_task("Rendering template preview", work, done)

    def _export_csv(self) -> None:
        def done(path) -> None:
            self.ctx.notify(f"Exported {path}", "success")

        self.ctx.run_task("Exporting tracker CSV",
                          lambda: self.ctx.pipeline.export_tracker_csv(self.ctx.profile), done)

    def _export_calendar(self) -> None:
        def done(path) -> None:
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


__all__ = ["FORMATS", "SettingsTab"]
