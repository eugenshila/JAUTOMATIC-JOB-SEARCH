"""RFC 5545 (iCalendar) export: interviews and follow-ups as calendar events.

Everything is generated offline from the tracker - no network involved - and the
resulting ``.ics`` file imports into Google Calendar, Outlook, Apple Calendar or
anything else that speaks iCalendar.

Design notes:

* UIDs are stable (``<application_id>-<kind>@jautomatic``), so re-importing an
  updated export refreshes events instead of duplicating them.
* Follow-ups are all-day events; interviews are timed when the user stored a
  time ("2026-09-22 14:30") and all-day otherwise.
* Lines are folded at 75 octets without splitting multi-byte UTF-8, text is
  escaped per RFC 5545 §3.3.11 and the file uses CRLF line endings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .. import APP_TITLE, __version__
from ..models import ApplicationStatus, parse_date

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a circular import
    from .application_pipeline import TrackedApplication

PRODID = f"-//{APP_TITLE}//Job Search Autopilot {__version__}//EN"
CALENDAR_NAME = "JAUTOMATIC job search"
UID_DOMAIN = "jautomatic"
MAX_LINE_OCTETS = 75                      # RFC 5545 §3.1
INTERVIEW_DEFAULT_MINUTES = 60            # assumed length when no end time is known

_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}")


# --------------------------------------------------------------------------- #
# parsing / escaping
# --------------------------------------------------------------------------- #
def parse_when(value: str | None) -> date | datetime | None:
    """Parse a user-entered interview date or date/time.

    Accepts "2026-09-22" (all-day) and "2026-09-22 14:30[:00]" / the ISO "T"
    variant (timed).  Returns ``None`` for anything else.
    """
    text = (value or "").strip()
    if not text:
        return None
    if _DATETIME_RE.match(text):
        try:
            return datetime.fromisoformat(text.replace(" ", "T", 1))
        except ValueError:
            return None
    return parse_date(text)


def escape_text(value: str) -> str:
    """Escape TEXT property values per RFC 5545 §3.3.11."""
    return (str(value).replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\n")
            .replace("\n", "\\n"))


def fold_line(line: str) -> str:
    """Fold one content line at 75 octets (RFC 5545 §3.1).

    Continuation lines start with a single space, which counts towards the
    limit; multi-byte UTF-8 sequences are never split across the fold.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= MAX_LINE_OCTETS:
        return line
    parts: list[str] = []
    limit = MAX_LINE_OCTETS
    while encoded:
        cut = min(limit, len(encoded))
        while cut < len(encoded) and (encoded[cut] & 0xC0) == 0x80:
            cut -= 1                      # back up to the start of the code point
        parts.append(encoded[:cut].decode("utf-8"))
        encoded = encoded[cut:]
        limit = MAX_LINE_OCTETS - 1       # leading space on continuation lines
    return "\r\n ".join(parts)


def unfold(text: str) -> str:
    """Inverse of :func:`fold_line` for the whole document (RFC 5545 §3.1)."""
    return text.replace("\r\n ", "").replace("\r\n\t", "")


# --------------------------------------------------------------------------- #
# events
# --------------------------------------------------------------------------- #
@dataclass
class CalendarEvent:
    """One VEVENT. ``start``/``end`` as ``date`` -> all-day, ``datetime`` -> timed."""
    uid: str
    summary: str
    start: date | datetime
    end: date | datetime | None = None
    description: str = ""
    location: str = ""
    url: str = ""

    @property
    def is_all_day(self) -> bool:
        return not isinstance(self.start, datetime)

    @property
    def sort_key(self) -> datetime:
        if isinstance(self.start, datetime):
            return self.start.replace(tzinfo=None)
        return datetime.combine(self.start, datetime.min.time())


def _format_value(value: date | datetime, all_day: bool) -> str:
    if all_day:
        day = value.date() if isinstance(value, datetime) else value
        return day.strftime("%Y%m%d")
    moment = value if isinstance(value, datetime) else datetime.combine(value, datetime.min.time())
    return moment.strftime("%Y%m%dT%H%M%S")


def event_lines(event: CalendarEvent, dtstamp: str) -> list[str]:
    """Render one VEVENT as unfolded content lines."""
    lines = ["BEGIN:VEVENT", f"UID:{event.uid}", f"DTSTAMP:{dtstamp}"]
    if event.is_all_day:
        end = event.end or (event.start + timedelta(days=1))
        lines.append(f"DTSTART;VALUE=DATE:{_format_value(event.start, True)}")
        lines.append(f"DTEND;VALUE=DATE:{_format_value(end, True)}")
    else:
        end = event.end or (event.start + timedelta(minutes=INTERVIEW_DEFAULT_MINUTES))
        lines.append(f"DTSTART:{_format_value(event.start, False)}")
        lines.append(f"DTEND:{_format_value(end, False)}")
    lines.append(f"SUMMARY:{escape_text(event.summary)}")
    if event.description:
        lines.append(f"DESCRIPTION:{escape_text(event.description)}")
    if event.location:
        lines.append(f"LOCATION:{escape_text(event.location)}")
    if event.url:
        lines.append(f"URL:{event.url.strip()}")
    lines.append("END:VEVENT")
    return lines


def build_calendar(events: list[CalendarEvent], calname: str = CALENDAR_NAME,
                   dtstamp: datetime | None = None) -> str:
    """Serialize events into a complete VCALENDAR document (CRLF endings)."""
    stamp = (dtstamp or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    ordered = sorted(events, key=lambda event: (event.sort_key, event.summary, event.uid))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_text(calname)}",
    ]
    for event in ordered:
        lines.extend(event_lines(event, stamp))
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_line(line) for line in lines) + "\r\n"


# --------------------------------------------------------------------------- #
# tracker -> events
# --------------------------------------------------------------------------- #
def _follow_up_event(row: TrackedApplication) -> CalendarEvent | None:
    app = row.application
    due = parse_date(app.follow_up_at)
    if due is None or not app.status_enum.is_active:
        return None
    details = [f"Status: {app.status_enum.label}"]
    if app.sent_at:
        details.append(f"Sent: {app.sent_at[:10]}")
    details.append("Draft the follow-up e-mail from the Applications tab.")
    return CalendarEvent(
        uid=f"{app.application_id}-follow-up@{UID_DOMAIN}",
        summary=f"Follow up: {row.title} @ {row.company}",
        start=due,
        description="\n".join(details),
        url=row.job.url)


def _interview_event(row: TrackedApplication) -> CalendarEvent | None:
    app = row.application
    when = parse_when(app.interview_at)
    if when is None:
        if app.status_enum is not ApplicationStatus.INTERVIEW:
            return None
        fallback = app.interview_fallback_date()
        if fallback is None:
            return None
        when = fallback
    details = [f"Status: {app.status_enum.label}"]
    if row.job.location:
        details.append(f"Where: {row.job.display_location}")
    details.append("Good luck — bring questions about the team, the stack and next steps.")
    return CalendarEvent(
        uid=f"{app.application_id}-interview@{UID_DOMAIN}",
        summary=f"Interview: {row.title} @ {row.company}",
        start=when,
        description="\n".join(details),
        location=row.job.display_location,
        url=row.job.url)


def events_for(rows: list[TrackedApplication], include_follow_ups: bool = True,
               include_interviews: bool = True) -> list[CalendarEvent]:
    """Derive calendar events from tracker rows (follow-ups + interviews)."""
    events: list[CalendarEvent] = []
    for row in rows:
        if include_follow_ups:
            event = _follow_up_event(row)
            if event is not None:
                events.append(event)
        if include_interviews:
            event = _interview_event(row)
            if event is not None:
                events.append(event)
    return events


__all__ = [
    "CALENDAR_NAME",
    "INTERVIEW_DEFAULT_MINUTES",
    "PRODID",
    "UID_DOMAIN",
    "CalendarEvent",
    "build_calendar",
    "escape_text",
    "events_for",
    "fold_line",
    "parse_when",
    "unfold",
]
