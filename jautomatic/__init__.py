"""JAUTOMATIC JOB SEARCH - a desktop job-application autopilot.

Package layout::

    jautomatic.models                      data model + SQLite/JSON workspace
    jautomatic.services.job_scraper        job-board integrations
    jautomatic.services.cv_generator        CV templates + docx/md/txt export
    jautomatic.services.cover_letter        cover-letter drafting
    jautomatic.services.email_drafter       application + follow-up e-mails
    jautomatic.services.application_pipeline  matching, preparation, tracking
    jautomatic.ui                           PySide6 desktop interface
"""
__version__ = "1.0.0"
APP_TITLE = "JAUTOMATIC JOB SEARCH"

__all__ = ["__version__", "APP_TITLE"]
