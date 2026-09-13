"""Master CV file handling and conservative profile prefill."""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}


def extract_text(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages).strip()
        except Exception as exc:  # noqa: BLE001 - shown as a useful UI error by caller
            raise ValueError(f"Could not read this PDF: {exc}") from exc
    if suffix == ".docx":
        try:
            from docx import Document
            return "\n".join(paragraph.text for paragraph in Document(str(path)).paragraphs).strip()
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Could not read this Word document: {exc}") from exc
    if suffix == ".doc":
        # Legacy .doc is retained as an accepted upload type, but parsing it
        # requires Microsoft Word or a separate converter. Never invent text.
        return ""
    raise ValueError("Choose a PDF, DOCX, or DOC file.")


def _first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else ""


def suggest_profile_from_text(text: str) -> dict[str, str]:
    """Extract only high-confidence contact hints; the user remains in control."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    email = _first_match(r"([\w.+-]+@[\w.-]+\.[A-Za-z]{2,})", text)
    phone = _first_match(r"(\+?[\d][\d ()-]{7,}[\d])", text)
    name = ""
    for line in lines[:8]:
        if "@" not in line and not re.search(r"\d", line) and 2 <= len(line.split()) <= 5:
            name = line
            break
    return {"full_name": name, "email": email, "phone": phone, "summary": text[:4000]}


def store_master_cv(source: str | Path, master_cv_dir: str | Path) -> tuple[Path, str]:
    source = Path(source)
    if source.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Choose a PDF, DOCX, or DOC file.")
    master_cv_dir = Path(master_cv_dir)
    # Parse first so a corrupt PDF is never copied into the user's MasterCV folder.
    extracted_text = extract_text(source)
    master_cv_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = master_cv_dir / f"Master_CV_{timestamp}{source.suffix.lower()}"
    shutil.copy2(source, destination)
    return destination, extracted_text
