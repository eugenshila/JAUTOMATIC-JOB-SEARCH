"""Open a user-approved email application without sending anything."""
from __future__ import annotations

import re
import webbrowser
from pathlib import Path
from urllib.parse import quote
from typing import Any

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def find_application_email(job: dict[str, Any]) -> str:
    explicit = str(job.get("application_email") or "").strip()
    if explicit and EMAIL_RE.fullmatch(explicit):
        return explicit
    match = EMAIL_RE.search(str(job.get("description") or ""))
    return match.group(0) if match else ""


def open_email_application(job: dict[str, Any], *, candidate_name: str, cover_letter_text: str = "", attachment_paths: list[str] | None = None) -> tuple[bool, str]:
    """Open the default mail client compose screen.

    Standard mailto links cannot reliably attach files across Outlook, Mail, and
    browser mail clients. The generated document folder is therefore opened too
    so the user can attach the truthful CV and cover letter manually.
    """
    email = find_application_email(job)
    if not email:
        return False, "No application email address was found in the job record or description."
    title = str(job.get("title") or "job application")
    subject = f"Application for {title} - {candidate_name}".strip(" -")
    body = cover_letter_text or f"Dear Hiring Manager,\n\nPlease find my application for the {title} position attached.\n\nKind regards,\n{candidate_name}"
    url = f"mailto:{email}?{quote('subject')}={quote(subject)}&{quote('body')}={quote(body)}"
    opened = webbrowser.open(url)
    if attachment_paths:
        existing = [str(Path(path)) for path in attachment_paths if Path(path).exists()]
        if existing:
            _open_document_folder(Path(existing[0]).parent)
    return bool(opened), email


def _open_document_folder(folder: Path) -> None:
    try:
        import os
        if hasattr(os, "startfile"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        else:
            webbrowser.open(folder.as_uri())
    except OSError:
        pass
