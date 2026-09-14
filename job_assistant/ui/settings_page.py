from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from job_assistant.config.settings import APP_NAME, AppPaths, DEFAULT_SEARCH_FREQUENCY
from job_assistant.database.repository import Repository
from job_assistant.ui.widgets import Card, action_button, page_header, section_label


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    settings_saved = Signal()

    def __init__(self, repository: Repository, paths: AppPaths, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.paths = paths
        self._build()
        self.load_settings()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        title, subtitle = page_header("Settings", "Control how the assistant behaves. Sensitive application answers and credentials are not guessed or written to logs.")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        general = Card()
        general_layout = QVBoxLayout(general)
        general_layout.setContentsMargins(20, 18, 20, 18)
        general_layout.addWidget(section_label("General"))
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(14)
        self.appearance = QComboBox()
        self.appearance.addItems(["Dark", "Light"])
        form.addRow("Appearance", self.appearance)
        self.startup = QCheckBox("Start Job Assistant when Windows starts")
        self.startup.setToolTip("Phase 12 will register this preference with Windows Task Scheduler.")
        form.addRow("Startup", self.startup)
        self.minimized = QCheckBox("Start minimized in the Windows system tray")
        form.addRow("Window", self.minimized)
        self.search_on_startup = QCheckBox("Run a search when the application starts")
        form.addRow("Search", self.search_on_startup)
        self.auto_apply = QCheckBox("Auto Apply (disabled by default)")
        self.auto_apply.setToolTip("Automatic submission is only permitted for approved flows with truthful answers and no CAPTCHA or security-control bypass.")
        form.addRow("Applications", self.auto_apply)
        general_layout.addLayout(form)
        apply_note = QLabel("The assistant prepares documents and opens permitted job pages or email compose windows. It does not submit applications automatically in this build.")
        apply_note.setObjectName("warning")
        apply_note.setWordWrap(True)
        general_layout.addWidget(apply_note)
        note = QLabel("Startup integration is intentionally stored as a preference in Phase 1; Task Scheduler registration is added in the Windows automation phase.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        general_layout.addWidget(note)
        layout.addWidget(general)

        data = Card()
        data_layout = QVBoxLayout(data)
        data_layout.setContentsMargins(20, 18, 20, 18)
        data_layout.addWidget(section_label("Local data and privacy"))
        location = QLabel(str(self.paths.data_dir))
        location.setObjectName("muted")
        location.setWordWrap(True)
        data_layout.addWidget(QLabel("Application data directory"))
        data_layout.addWidget(location)
        privacy = QLabel("Your SQLite database, Master CV, generated documents, and logs stay in this local directory. Keep it backed up securely. API credentials will use Windows Credential Manager in a later phase.")
        privacy.setObjectName("muted")
        privacy.setWordWrap(True)
        data_layout.addWidget(privacy)
        layout.addWidget(data)

        buttons = QHBoxLayout()
        buttons.addStretch()
        restore = action_button("Restore defaults")
        restore.clicked.connect(self.restore_defaults)
        save = action_button("Save settings", True)
        save.clicked.connect(self.save_settings)
        buttons.addWidget(restore)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        layout.addStretch()

    def load_settings(self) -> None:
        settings = self.repository.get_settings()
        self.appearance.setCurrentText(settings.get("appearance", "Dark"))
        self.startup.setChecked(bool(settings.get("start_with_windows", False)))
        self.minimized.setChecked(bool(settings.get("start_minimized", True)))
        self.search_on_startup.setChecked(bool(settings.get("search_on_startup", True)))
        self.auto_apply.setChecked(bool(settings.get("auto_apply", False)))

    def save_settings(self) -> None:
        self.repository.set_setting("appearance", self.appearance.currentText())
        self.repository.set_setting("start_with_windows", self.startup.isChecked())
        self.repository.set_setting("start_minimized", self.minimized.isChecked())
        self.repository.set_setting("search_on_startup", self.search_on_startup.isChecked())
        self.repository.set_setting("auto_apply", self.auto_apply.isChecked())
        self.theme_changed.emit(self.appearance.currentText())
        self.settings_saved.emit()
        QMessageBox.information(self, "Settings saved", "Settings have been saved to your local database.")

    def restore_defaults(self) -> None:
        self.appearance.setCurrentText("Dark")
        self.startup.setChecked(False)
        self.minimized.setChecked(True)
        self.search_on_startup.setChecked(True)
        self.auto_apply.setChecked(False)
