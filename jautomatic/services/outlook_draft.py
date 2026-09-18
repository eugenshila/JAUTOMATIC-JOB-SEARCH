"""Open an unsent application message with its documents attached."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
from email.message import EmailMessage
from email.policy import SMTP

from .email_drafter import EmailDraft


def write_message(draft: EmailDraft, attachments: list[Path], destination: Path) -> Path:
    """Create a portable MIME draft, deliberately leaving all recipients blank."""
    message = EmailMessage(policy=SMTP)
    message["Subject"] = " ".join(draft.subject.splitlines())
    message["X-Unsent"] = "1"
    message.set_content(draft.body)
    for path in attachments:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Attachment is missing: {path.name}")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        main, sub = content_type.split("/", 1)
        message.add_attachment(path.read_bytes(), maintype=main, subtype=sub, filename=path.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(message.as_bytes())
    return destination


def new_outlook_path() -> Path | None:
    """Find Windows' stable app-execution alias, independent of Store version."""
    if sys.platform != "win32" or not os.environ.get("LOCALAPPDATA"):
        return None
    path = Path(os.environ["LOCALAPPDATA"]) / "Microsoft/WindowsApps/olk.exe"
    return path if path.is_file() else None


def classic_outlook_available() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID"):
            return True
    except OSError:
        return False


_COM_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
try {
    $payload = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([Console]::In.ReadToEnd())) | ConvertFrom-Json
    $outlook = New-Object -ComObject Outlook.Application
    $mail = $outlook.CreateItem(0)
    $mail.Subject = $payload.subject
    $mail.Body = $payload.body
    foreach ($path in $payload.attachments) { $null = $mail.Attachments.Add($path) }
    $mail.Save()
    $mail.Display($false)
    exit 0
} catch {
    [Console]::Error.WriteLine('Outlook could not open the draft. Open classic Outlook and configure your mail account, then try again.')
    exit 1
}
'''


def open_message(draft: EmailDraft, attachments: list[Path], message_path: Path) -> str:
    """Display only. Never send or assign To/Cc/Bcc, even if a job contains an address."""
    if sys.platform != "win32":
        raise RuntimeError(f"Outlook opening requires Windows. Your draft is saved at {message_path}")
    new_outlook = new_outlook_path()
    if new_outlook:
        # Launch the configured Windows app explicitly, without changing associations
        # or attempting classic Outlook COM activation first.
        os.startfile(str(new_outlook), "open",
                     subprocess.list2cmdline([str(message_path.resolve(strict=True))]))
        return "new"
    if not classic_outlook_available():
        os.startfile(str(message_path.resolve()))
        return "eml"
    payload = {"subject": " ".join(draft.subject.splitlines()), "body": draft.body,
               "attachments": [str(Path(p).resolve(strict=True)) for p in attachments]}
    encoded = base64.b64encode(_COM_SCRIPT.encode("utf-16-le")).decode("ascii")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
            input=base64.b64encode(json.dumps(payload).encode("utf-8")),
            capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Outlook took too long. Check Outlook for an open draft before trying again.") from exc
    if result.returncode:
        raise RuntimeError("Outlook could not open the draft. Open classic Outlook and configure your "
                           f"mail account, then try again. A backup draft is saved at {message_path}")
    return "classic"
