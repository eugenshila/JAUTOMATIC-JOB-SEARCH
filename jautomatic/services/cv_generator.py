"""CV generation.

Templates are pure functions ``(profile, job, match) -> str`` that render a
Markdown-ish document.  Markdown is the canonical in-memory format; exporters
turn it into ``.md`` / ``.txt`` / ``.docx`` (and the app shows it in a rich
text preview).

Three templates ship by default:

* ``modern``  – tone-first, keyword-highlighted skills line (good default)
* ``classic`` – traditional reverse-chronological, corporate friendly
* ``compact`` – one page, minimal, for very senior candidates
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..models import JobPosting, Profile, slugify, specific_keywords, tokenize

TEMPLATES = ("modern", "classic", "compact")
TEMPLATE_LABELS = {
    "modern": "Modern (impact-focused)",
    "classic": "Classic (traditional ATS)",
    "compact": "Compact (one page)",
}


@dataclass
class GeneratedDocument:
    """A rendered artefact: text plus where it was written (if anywhere)."""
    kind: str                 # cv | cover_letter | email
    text: str
    path: Path | None = None
    template: str = ""
    used_keywords: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.used_keywords is None:
            self.used_keywords = []

    @property
    def filename(self) -> str:
        return self.path.name if self.path else ""

    @property
    def word_count(self) -> int:
        return len(re.findall(r"\S+", self.text))


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _rule(char: str = "=") -> str:
    return char * 3


def _contact_line(profile: Profile) -> str:
    bits = [profile.location, profile.email, profile.phone]
    line = " | ".join(b for b in bits if b.strip())
    if profile.links.strip():
        line = f"{line}\n{profile.links.strip()}" if line else profile.links.strip()
    return line


def _skill_line(profile: Profile, job: JobPosting | None, match=None) -> str:  # noqa: ANN001
    """Skills first, then the posting keywords the profile genuinely covers."""
    skills = [s.strip() for s in profile.skills if s.strip()]
    if job:
        known = {s.lower() for s in skills}
        if match is not None and match.matched_keywords:
            candidates = [k for k in match.matched_keywords if k.lower() not in known]
        else:
            candidates = [k for k in job.tags if k.lower() not in known]
        # never advertise "senior"/"engineer"/"data" as if they were technologies
        block = {t for t in tokenize(job.title) + tokenize(job.company)}
        skills += specific_keywords(candidates, extra_block=block, limit=6)
    return ", ".join(skills[:26])


def _bullets(entry, job: JobPosting | None, limit: int) -> list[str]:  # noqa: ANN001
    """Take the user's bullets; if the job asks for something we can evidence, show it first."""
    bullets = entry.as_bullets()
    if job and bullets:
        wanted = {k.lower() for k in (job.tags or [])}
        bullets = sorted(bullets, key=lambda b: -len(wanted & set(re.findall(r"[a-z0-9+#.]+",
                                                                           b.lower()))))
    return bullets[:limit]


def _tailored_summary(profile: Profile, job: JobPosting | None) -> str:
    summary = profile.summary.strip()
    if not job:
        return summary
    focus = ", ".join(job.tags[:3]) if job.tags else (job.title or "this role")
    target = f"Targeting the {job.title} role at {job.company}".strip()
    if target.endswith("at"):
        target = target[:-2].strip()
    if summary:
        return f"{summary}\n\n{target} — focus on {focus}."
    return (f"{profile.headline or 'Experienced professional'} targeting the "
            f"{job.title} role at {job.company}, with hands-on strength in {focus}.")


# --------------------------------------------------------------------------- #
# templates
# --------------------------------------------------------------------------- #
def render_modern(profile: Profile, job: JobPosting | None = None, match=None) -> str:  # noqa: ANN001
    lines: list[str] = []
    add = lines.append

    add(f"# {profile.display_name}")
    if profile.headline.strip():
        add(f"### {profile.headline.strip()}")
    contact = _contact_line(profile)
    if contact:
        add(contact)

    summary = _tailored_summary(profile, job)
    if summary:
        add("\n## Profile")
        add(summary)

    skills = _skill_line(profile, job, match)
    if skills:
        add("\n## Core skills")
        add(skills)
    if profile.languages.strip():
        add(f"\n**Languages:** {profile.languages.strip()}")

    if profile.experience:
        add("\n## Experience")
        for entry in profile.experience:
            add(f"\n### {entry.title or 'Role'}"
                + (f" — {entry.company}" if entry.company else ""))
            meta = " | ".join(p for p in (entry.period if (entry.start or entry.end) else "",
                                          entry.location) if p)
            if meta:
                add(f"*{meta}*")
            for bullet in _bullets(entry, job, 5):
                add(f"- {bullet}")

    if profile.education:
        add("\n## Education")
        for entry in profile.education:
            head = " — ".join(p for p in (entry.degree, entry.school) if p)
            add(f"- **{head or 'Education'}**"
                + (f" ({entry.period})" if entry.period else "")
                + (f"\n  {entry.details.strip()}" if entry.details.strip() else ""))

    if job:
        add("\n---")
        add(f"*Tailored for **{job.title}** at **{job.company}**"
            + (f" · {job.location}" if job.location else "") + f" · {date.today().isoformat()}*")
    return "\n".join(lines).strip() + "\n"


def render_classic(profile: Profile, job: JobPosting | None = None, match=None) -> str:  # noqa: ANN001
    lines: list[str] = []
    add = lines.append

    add(profile.display_name.upper())
    if profile.headline.strip():
        add(profile.headline.strip())
    contact = _contact_line(profile)
    if contact:
        add(contact)
    add("\n" + "=" * 64)

    if profile.summary.strip():
        add("PROFESSIONAL SUMMARY")
        add(_tailored_summary(profile, job))

    skills = _skill_line(profile, job, match)
    if skills:
        add("\nKEY SKILLS")
        add(skills)

    if profile.experience:
        add("\nPROFESSIONAL EXPERIENCE")
        for entry in profile.experience:
            add("")
            add(f"{entry.title or 'Role'}" + (f", {entry.company}" if entry.company else ""))
            meta = " | ".join(p for p in (entry.period if (entry.start or entry.end) else "",
                                          entry.location) if p)
            if meta:
                add(meta)
            for bullet in _bullets(entry, job, 6):
                add(f"  * {bullet}")

    if profile.education:
        add("\nEDUCATION")
        for entry in profile.education:
            add(f"  * {entry.degree or 'Degree'}"
                + (f", {entry.school}" if entry.school else "")
                + (f" ({entry.period})" if entry.period else ""))

    if profile.languages.strip():
        add(f"\nLANGUAGES\n{profile.languages.strip()}")
    if profile.links.strip():
        add(f"\nLINKS\n{profile.links.strip()}")
    return "\n".join(lines).strip() + "\n"


def render_compact(profile: Profile, job: JobPosting | None = None, match=None) -> str:  # noqa: ANN001
    lines: list[str] = []
    add = lines.append

    head = profile.display_name
    if profile.headline.strip():
        head += f" — {profile.headline.strip()}"
    add(f"**{head}**")
    contact = _contact_line(profile).replace("\n", " · ")
    if contact:
        add(contact)

    summary = _tailored_summary(profile, job).replace("\n\n", " ")
    if summary:
        add(f"\n{summary}")

    skills = _skill_line(profile, job, match)
    if skills:
        add(f"\n**Skills:** {skills}")

    if profile.experience:
        add("\n**Experience**")
        for entry in profile.experience:
            head = f"- **{entry.title or 'Role'}"
            if entry.company:
                head += f" @ {entry.company}"
            head += "**"
            if entry.period:
                head += f" ({entry.period})"
            add(head)
            for bullet in _bullets(entry, job, 3):
                add(f"    - {bullet}")

    if profile.education:
        add("\n**Education:** " + "; ".join(
            " , ".join(p for p in (e.degree, e.school) if p) + (f" ({e.period})" if e.period else "")
            for e in profile.education))
    if profile.languages.strip():
        add(f"**Languages:** {profile.languages.strip()}")
    return "\n".join(lines).strip() + "\n"


RENDERERS = {"modern": render_modern, "classic": render_classic, "compact": render_compact}


def render_markdown(profile: Profile, job: JobPosting | None = None, template: str = "modern",
                    match=None) -> str:  # noqa: ANN001
    return RENDERERS.get(template, render_modern)(profile, job, match)


# --------------------------------------------------------------------------- #
# exporters
# --------------------------------------------------------------------------- #
def to_plain_text(markdown: str) -> str:
    text = re.sub(r"(?m)^#{1,6}\s*", "", markdown)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?m)^\s*---\s*$", "-" * 40, text)
    return text.strip() + "\n"


def to_docx(markdown: str, path: Path, title: str = "") -> Path:
    """Minimal Markdown -> .docx converter (headings, bullets, bold)."""
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError:  # pragma: no cover - dependency hint
        raise RuntimeError("python-docx is required for .docx export "
                           "(pip install -r requirements.txt)") from None

    document = Document()
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    if title:
        document.core_properties.title = title

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            document.add_paragraph()
            continue
        if line.strip() in ("---", "***"):
            document.add_paragraph("_" * 40)
            continue
        heading = re.match(r"^(#{1,6})\s*(.*)$", line)
        if heading:
            level = min(len(heading.group(1)), 4)
            document.add_heading(_strip_inline(heading.group(2)), level=level)
            continue
        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        if bullet:
            _add_rich(document.add_paragraph(style="List Bullet"), bullet.group(1))
            continue
        _add_rich(document.add_paragraph(), line)

    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    return path


def _strip_inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)


def _add_rich(paragraph, text: str) -> None:  # noqa: ANN001
    """Render ``**bold**`` runs inside a paragraph."""
    for part in re.split(r"(\*\*.+?\*\*)", _strip_inline_keep_bold(text)):
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            paragraph.add_run(part[2:-2]).bold = True
        elif part:
            paragraph.add_run(part)


def _strip_inline_keep_bold(text: str) -> str:
    return re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)


def export(markdown: str, path: Path, fmt: str = "docx", title: str = "") -> Path:
    """Write ``markdown`` to ``path`` honouring ``fmt`` (docx|md|txt|markdown)."""
    fmt = (fmt or "docx").lower()
    path = Path(path)
    if fmt in ("md", "markdown"):
        path = path.with_suffix(".md")
        path.write_text(markdown, encoding="utf-8")
    elif fmt in ("txt", "text"):
        path = path.with_suffix(".txt")
        path.write_text(to_plain_text(markdown), encoding="utf-8")
    else:
        path = path.with_suffix(".docx")
        to_docx(markdown, path, title=title)
    return path


# --------------------------------------------------------------------------- #
# service
# --------------------------------------------------------------------------- #
class CVGenerator:
    """Renders a CV for a profile (+ optional target job) and stores it."""

    def generate(self, profile: Profile, job: JobPosting | None = None, template: str = "modern",
                 output_dir: Path | None = None, fmt: str = "docx",
                 match=None) -> GeneratedDocument:  # noqa: ANN001
        template = template if template in TEMPLATES else "modern"
        markdown = render_markdown(profile, job, template, match)
        used = [k for k in (job.tags if job else []) if k]
        document = GeneratedDocument(kind="cv", text=markdown, template=template,
                                     used_keywords=used[:10])
        if output_dir is not None:
            stem = f"CV_{slugify(profile.display_name, 30)}"
            if job:
                stem += f"_{slugify(job.company, 20)}_{slugify(job.title, 24)}"
            document.path = export(markdown, Path(output_dir) / f"{stem}.{fmt}",
                                   fmt, title=f"CV – {profile.display_name}")
        return document
