"""Application e-mail drafting.

Produces a ready-to-send message (subject + body) with a *specific* subject
line, a short body that references the posting, and a list of attachments that
were generated alongside it.  Also renders polite follow-up e-mails, which the
reminder system offers once a follow-up date comes due.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..models import (
    JobPosting,
    Profile,
    human_join,
    pretty_term,
    slugify,
    unique_document_path,
)
from .cover_letter import MatchContext, approved_cover_letter
from .cv_generator import GeneratedDocument, document_suffix, export

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


@dataclass
class EmailDraft:
    subject: str = ""
    body: str = ""
    recipient: str = ""
    attachments: list[str] = field(default_factory=list)
    tone: str = "professional"

    @property
    def text(self) -> str:
        """Plain-text version of the message, including its attachment list."""
        head = ""
        if self.recipient:
            head += f"To: {self.recipient}\n"
        if self.subject:
            head += f"Subject: {self.subject}\n"
        body = self.body
        if self.attachments:
            body += "\n\nAttachments: " + ", ".join(self.attachments)
        return f"{head}\n{body}".strip() + "\n"

    def to_markdown(self) -> str:
        lines = []
        if self.recipient:
            lines.append(f"**To:** {self.recipient}")
        lines.append(f"**Subject:** {self.subject}")
        lines.append("")
        lines.append(self.body)
        if self.attachments:
            lines.append("")
            lines.append("**Attachments:** " + ", ".join(self.attachments))
        return "\n".join(lines).strip() + "\n"


NOISE_DOMAINS = {"example.com", "example.org", "sentry.io", "localhost"}


def guess_recipient(job: JobPosting) -> str:
    """Look for a contact address in the posting; blank means "apply via form"."""
    for text in (job.description, job.url):
        for match in EMAIL_RE.finditer(text or ""):
            address = match.group(0)
            local, _, domain = address.lower().partition("@")
            if domain in NOISE_DOMAINS or "noreply" in local or "no-reply" in local:
                continue
            return address
    return ""


def build_subject(profile: Profile, job: JobPosting) -> str:
    role = job.title.strip() or "the advertised role"
    company = job.company.strip()
    base = f"Application: {role}" + (f" — {company}" if company else "")
    if profile.full_name.strip():
        return f"{base} ({profile.full_name.strip()})"
    return base


def _opening(tone: str, job: JobPosting, profile: Profile) -> str:
    name = profile.full_name.strip() or "I"
    if tone == "enthusiastic":
        return (f"I was genuinely excited to see the {job.title} opening at {job.company} — "
                f"it reads like a role written for my background, so here is my application.")
    if tone == "friendly":
        return (f"Quick note to put my hat in the ring for the {job.title} role at "
                f"{job.company} — details and attachments below.")
    if tone == "concise":
        return (f"Please consider my application for the {job.title} role at {job.company}.")
    return (f"I would like to apply for the {job.title} position at {job.company}."
            if name == "I" else
            f"My name is {name} and I would like to apply for the {job.title} position at "
            f"{job.company}.")


def _evidence_sentence(profile: Profile, job: JobPosting, match: MatchContext | None) -> str:
    highlights = list((match.matched_keywords if match else []) or [])[:3]
    if not highlights:
        highlights = [t for t in job.tags[:3]]
    skills = (human_join([pretty_term(h) for h in highlights])
              if highlights else "the requirements in your posting")
    years = ""
    if profile.experience:
        entry = profile.experience[0]
        years = f" Most recently I was {entry.title or 'in a senior role'}"
        if entry.company:
            years += f" at {entry.company}"
        years += "."
    return (f"My background lines up with {skills}.{years} "
            f"The attached CV has the full detail; the cover letter explains the fit.")


def _closing_line(tone: str) -> str:
    if tone == "concise":
        return "Thank you for your consideration."
    if tone == "friendly":
        return "Happy to jump on a call whenever it suits your team — thanks for reading."
    return "Thank you for your time and consideration; I look forward to hearing from you."


def render_email(profile: Profile, job: JobPosting, match: MatchContext | None = None,
                 tone: str | None = None, attachments: list[str] | None = None) -> EmailDraft:
    tone = (tone or profile.tone or "professional").lower()
    recipient = guess_recipient(job)
    approved = approved_cover_letter(profile, job)
    if approved:
        return EmailDraft(
            subject=build_subject(profile, job), body=approved.rstrip("\n"),
            recipient=recipient,
            attachments=[Path(a).name for a in (attachments or []) if a], tone=tone)
    greeting_name = job.company.strip() or "Hiring Team"

    body_parts = [
        f"Dear {greeting_name} Hiring Team,",
        _opening(tone, job, profile),
        _evidence_sentence(profile, job, match),
    ]
    if tone != "concise":
        body_parts.append(
            f"Why {job.company}: the posting mentions "
            + (human_join([pretty_term(t) for t in job.tags[:3]]) if job.tags
               else "problems I have solved before")
            + ", which is exactly the work I want to keep doing.")
    if job.url:
        body_parts.append(f"I found the role here: {job.url}")
    body_parts.append(_closing_line(tone))
    signature = profile.signature_block().strip() or profile.display_name
    body_parts.append(f"Best regards,\n{signature}")

    draft = EmailDraft(
        subject=build_subject(profile, job),
        body="\n\n".join(p.strip() for p in body_parts if p.strip()),
        recipient=recipient,
        attachments=[Path(a).name for a in (attachments or []) if a],
        tone=tone)
    return draft


# Each rung of the escalating follow-up ladder: a subject template and the body
# paragraphs that make that particular nudge feel like a step forward rather
# than a copy of the last one.  ``level`` is how many nudges already went out.
FOLLOW_UP_SUBJECTS = [
    lambda role, name: (f"Following up: {role} application"
                        + (f" ({name})" if name else "")),              # first nudge
    lambda role, name: (f"Still interested: {role}"
                        + (f" ({name})" if name else "")),              # second nudge
    lambda role, name: (f"One last check on {role}"
                        + (f" ({name})" if name else "")),              # third+
]


def _follow_up_body(profile: Profile, job: JobPosting, days_since_sent: int,
                    stage: str, level: int, final: bool) -> str:
    greeting = f"Dear {job.company.strip() or 'Hiring Team'} Hiring Team,"
    role, company = job.title, job.company
    if level == 0:
        body = [
            greeting,
            f"I applied for the {role} role {days_since_sent} days ago and wanted to check in "
            f"on where things stand. I remain very interested in the position.",
            "If it helps, I am happy to provide additional work samples, references or a short "
            "technical conversation at your convenience.",
            "Thanks for your time — I appreciate any update you can share.",
        ]
    elif level == 1:
        body = [
            greeting,
            f"I wrote to you a little while ago about the {role} role at {company} and haven't "
            f"heard back, so I wanted to make sure my application didn't slip through the cracks.",
            "I am as interested now as on day one — happy to supply anything at all that would "
            "help you decide, from samples of my work to a quick call with the team.",
            "Either way, a two-line update would be genuinely appreciated.",
        ]
    else:
        body = [
            greeting,
            f"This is my last follow-up about the {role} position at {company} — I don't want "
            f"to keep nudging your inbox, only to close the loop on my application.",
            "If the role has been filled or is no longer moving forward, a one-line note to "
            "that effect is more than enough. If it is still open, I'd be glad to have that "
            "conversation any time.",
            "Thank you for your help either way.",
        ]
    if stage == "interview":
        body.insert(2, "Thank you again for the interview — I enjoyed the conversation and it "
                       "only increased my interest in the team.")
    body.append(f"Best regards,\n{profile.signature_block().strip() or profile.display_name}")
    return "\n\n".join(body)


def render_follow_up(profile: Profile, job: JobPosting, days_since_sent: int = 7,
                     stage: str = "sent", level: int = 0,
                     max_nudges: int = 0) -> EmailDraft:
    """Polite nudge used by the follow-up reminders; ``level`` picks the tone.

    ``level`` is the number of nudges already sent for this application: 0 is the
    gentle first check-in, 1 a firmer "did it slip through the cracks?", 2+ the
    final "closing the loop" message (unless ``max_nudges`` says 2 is not final).
    """
    role = job.title.strip() or "the advertised role"
    name = profile.full_name.strip()
    subject = FOLLOW_UP_SUBJECTS[min(level, len(FOLLOW_UP_SUBJECTS) - 1)](role, name)
    final = bool(max_nudges) and level >= max_nudges - 1
    return EmailDraft(subject=subject,
                      body=_follow_up_body(profile, job, days_since_sent, stage, level, final),
                      recipient=guess_recipient(job), attachments=[], tone="professional")


class EmailDrafter:
    """Renders + persists e-mail drafts next to the other documents."""

    def generate(self, profile: Profile, job: JobPosting, match: MatchContext | None = None,
                 tone: str | None = None, attachments: list[str] | None = None,
                 output_dir: Path | None = None, fmt: str = "docx", *,
                 reuse: str | Path | None = None) -> GeneratedDocument:
        draft = render_email(profile, job, match, tone, attachments)
        document = GeneratedDocument(
            kind="email", text=draft.to_markdown(), template=draft.tone,
            used_keywords=list((match.matched_keywords if match else []) or [])[:10])
        if output_dir is not None:
            stem = (f"Email_{slugify(profile.display_name, 24)}_{slugify(job.company, 18)}_"
                    f"{slugify(job.title, 20)}")
            key = f"email|{profile.display_name}|{job.company}|{job.title}"
            path = unique_document_path(output_dir, stem, document_suffix(fmt),
                                        key=key, reuse=reuse)
            document.path = export(draft.to_markdown(), path, fmt,
                                   title=draft.subject)
        return document

    def follow_up(self, profile: Profile, job: JobPosting, days_since_sent: int = 7,
                  stage: str = "sent", output_dir: Path | None = None,
                  fmt: str = "docx", *, level: int = 0,
                  max_nudges: int = 0) -> GeneratedDocument:
        draft = render_follow_up(profile, job, days_since_sent, stage, level, max_nudges)
        document = GeneratedDocument(kind="follow_up", text=draft.to_markdown(),
                                     template=f"follow-up-email-{level}")
        if output_dir is not None:
            step = level + 1
            stem = (f"FollowUp{step}_{slugify(profile.display_name, 20)}_{slugify(job.company, 16)}_"
                    f"{date.today().isoformat()}")
            key = (f"follow_up|{level}|{profile.display_name}|{job.company}|{job.title}"
                   f"|{date.today().isoformat()}")
            path = unique_document_path(output_dir, stem, document_suffix(fmt), key=key)
            document.path = export(draft.to_markdown(), path, fmt,
                                   title=draft.subject)
        return document


__all__ = [
    "FOLLOW_UP_SUBJECTS",
    "EmailDraft",
    "EmailDrafter",
    "build_subject",
    "guess_recipient",
    "render_email",
    "render_follow_up",
]
