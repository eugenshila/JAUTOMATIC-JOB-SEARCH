from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from job_assistant.database.repository import Repository
from job_assistant.services.search_service import SearchOrchestrator, SearchSummary


class SearchWorker(QThread):
    completed = Signal(object)

    def __init__(self, repository: Repository, applications_dir: str, config: dict, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.applications_dir = applications_dir
        self.config = config

    def run(self) -> None:
        summary = SearchOrchestrator(self.repository, self.applications_dir).run(self.config)
        self.completed.emit(summary)
