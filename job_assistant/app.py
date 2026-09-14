"""Application entry point for the AI Job Application Assistant."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from job_assistant.config.settings import APP_NAME, AppPaths
from job_assistant.database.repository import Repository
from job_assistant.ui.main_window import MainWindow
from job_assistant.utils.logging import configure_logging


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("JAUTOMATIC")
    paths = AppPaths.default()
    paths.ensure()
    logger = configure_logging(paths.logs_dir)
    logger.info("Application started")
    repository = Repository(paths.database)
    window = MainWindow(repository, paths)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
