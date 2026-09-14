from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from job_assistant.database.repository import Repository
from job_assistant.services.email_launcher import open_email_application
from job_assistant.ui.widgets import action_button, page_header


class ApplicationQueuePage(QWidget):
    def __init__(self, repository: Repository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.rows: list[Any] = []
        self.table = QTableWidget()
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        title, subtitle = page_header("Application queue", "Documents are prepared locally, but nothing is submitted without your review and approval.")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Company", "Position", "Location", "Match", "Status", "Application route"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.status = QLabel("Select a prepared application to continue.")
        self.status.setObjectName("muted")
        actions.addWidget(self.status)
        actions.addStretch()
        folder = action_button("Open documents folder")
        folder.clicked.connect(self.open_folder)
        email = action_button("Open email application", True)
        email.clicked.connect(self.open_email)
        view = action_button("View job")
        view.clicked.connect(self.view_job)
        actions.addWidget(view)
        actions.addWidget(folder)
        actions.addWidget(email)
        layout.addLayout(actions)

    def refresh(self) -> None:
        self.rows = self.repository.list_applications()
        self.table.setRowCount(len(self.rows))
        for row_index, row in enumerate(self.rows):
            values = [row["company"] or "Unknown company", row["job_title"], row["location"], f"{row['match_score']:.0f}%", row["status"], row["application_method"] or "website"]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))
        self.status.setText(f"{len(self.rows)} application(s) waiting in the local queue.")

    def _selected(self):
        selection = self.table.selectionModel().selectedRows()
        return self.rows[selection[0].row()] if selection else None

    def open_folder(self) -> None:
        row = self._selected()
        if not row:
            return
        path = Path(row["cv_path"] or "")
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        else:
            QMessageBox.information(self, "Documents unavailable", "Documents have not been generated for this application yet.")

    def open_email(self) -> None:
        row = self._selected()
        if not row:
            return
        job = dict(row)
        opened, detail = open_email_application(job, candidate_name=self.repository.get_profile().full_name or "Candidate", attachment_paths=[row["cv_path"], row["cover_letter_path"]])
        if not opened:
            QMessageBox.warning(self, "Email application", detail)
        else:
            QMessageBox.information(self, "Email application opened", f"A compose window for {detail} should now be open. Attach the generated CV and cover letter from the folder that was opened. Nothing was sent.")

    def view_job(self) -> None:
        row = self._selected()
        if row and row["job_url"]:
            QDesktopServices.openUrl(QUrl(row["job_url"]))
