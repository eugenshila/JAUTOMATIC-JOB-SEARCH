"""Bring a job read in the user's browser into the local tracker."""
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QPlainTextEdit, QVBoxLayout,
)
from ..services.job_scraper import posting_from_details


class ManualJobDialog(QDialog):
    def __init__(self, url="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paste job details — LinkedIn or another website")
        self.resize(700, 600)
        self.job = None
        layout = QVBoxLayout(self)
        help_text = QLabel("Copy the posting from your browser. The job link and full description "
                           "are saved for matching and application materials.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        form = QFormLayout()
        self.url, self.title, self.company, self.location = (QLineEdit() for _ in range(4))
        self.url.setText(url)
        for label, widget in (("Job URL", self.url), ("Job title", self.title),
                              ("Employer", self.company), ("Location", self.location)):
            form.addRow(label, widget)
        self.remote = QCheckBox("The posting says this role is remote")
        form.addRow(self.remote)
        layout.addLayout(form)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("Paste the job description and requirements here…")
        layout.addWidget(self.description, 1)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        try:
            self.job = posting_from_details(self.url.text(), self.title.text(), self.company.text(),
                                            self.location.text(), self.description.toPlainText(),
                                            self.remote.isChecked())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()
