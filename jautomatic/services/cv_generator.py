"""CV generation.

Templates are pure functions ``(profile, job, match) -> str`` that render a
Markdown-ish document.  Markdown is the canonical in-memory format; exporters
turn it into ``.md`` / ``.txt`` / ``.docx`` (and the app shows it in a rich
text preview).

Six templates ship by default:

* ``modern``     – tone-first, keyword-highlighted skills line (good default)
* ``classic``    – traditional reverse-chronological, corporate friendly
* ``compact``    – one page, minimal, for very senior candidates
* ``functional`` – skills-first; groups evidence by the employer's keywords
  (career changers, gaps, or when the stack matters more than the timeline)
* ``executive``  – leadership brief: headline achievements first, then roles
* ``technical``  – engineering layout with a "stack" line per role and a
  keyword-coverage block that mirrors the posting

On top of those, **user-supplied templates** are plain ``.md`` files in
``<data dir>/templates`` (see :class:`TemplateRegistry`).  They are rendered
with the small, safe template language in :mod:`.template_engine` and show up
in Settings next to the built-ins as ``custom:<file name>``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..models import (JobPosting, Profile, slugify, specific_keywords, tokenize,
                      unique_document_path)
from . import template_engine

TEMPLATES = ("modern", "classic", "compact", "functional", "executive", "technical")
TEMPLATE_LABELS = {
    "modern": "Modern (impact-focused)",
    "classic": "Classic (traditional ATS)",
    "compact": "Compact (one page)",
    "functional": "Functional (skills-first)",
    "executive": "Executive (leadership brief)",
    "technical": "Technical (stack per role)",
}
CUSTOM_PREFIX = "custom:"
CUSTOM_SUFFIXES = (".md", ".txt", ".markdown")


@dataclass
class GeneratedDocument:
    """A rendered artefact: text plus where it was written (if anywhere)."""
    kind: str                 # cv | cover_letter | email
    text: str
    path: Path | None = None
    template: str = ""
    used_keywords: list[str] = None  # type: ignore[assignment]
    warning: str = ""             # e.g. a custom template that failed and fell back

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


def _entry_stack(entry, job: JobPosting | None, profile: Profile) -> list[str]:  # noqa: ANN001
    """Technologies evidenced by one role: profile skills / posting tags found in its text."""
    text = " ".join([entry.title, entry.summary, " ".join(entry.highlights)]).lower()
    found = re.findall(r"[a-z0-9+#.]+", text)
    known = [s for s in profile.skills if s.strip()]
    if job:
        known += [t for t in job.tags if t.lower() not in {k.lower() for k in known}]
    stack: list[str] = []
    for skill in known:
        needle = skill.strip().lower()
        if not needle:
            continue
        if needle in found or needle in text:
            if needle not in [s.lower() for s in stack]:
                stack.append(skill.strip())
    return stack


def _all_bullets(profile: Profile) -> list[tuple[str, object]]:
    """Every achievement bullet in the profile, paired with its role."""
    out: list[tuple[str, object]] = []
    for entry in profile.experience:
        for bullet in entry.as_bullets():
            out.append((bullet, entry))
    return out


def _impact_bullets(profile: Profile, job: JobPosting | None, limit: int) -> list[str]:
    """Bullets with numbers first (they read as outcomes), then keyword hits."""
    wanted = {k.lower() for k in (job.tags if job else [])}

    def weight(bullet: str) -> tuple[int, int]:
        numbers = len(re.findall(r"\d+(?:[.,]\d+)?%?|\b\d+x\b", bullet))
        hits = len(wanted & set(re.findall(r"[a-z0-9+#.]+", bullet.lower())))
        return (-min(numbers, 2), -hits)

    bullets = [b for b, _ in _all_bullets(profile)]
    return sorted(bullets, key=weight)[:limit]


def render_functional(profile: Profile, job: JobPosting | None = None, match=None) -> str:  # noqa: ANN001
    """Skills-first: evidence grouped by competency, timeline kept short."""
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
        add("\n## Summary")
        add(summary)

    # competency groups: the posting's tags (or the top skills) each get the
    # bullets that evidence them; leftover bullets go under "Further highlights"
    groups: list[str] = []
    if job and job.tags:
        groups = [t for t in job.tags if t.strip()][:5]
    for skill in profile.skills:
        if len(groups) >= 5:
            break
        if skill.strip() and skill.lower() not in [g.lower() for g in groups]:
            groups.append(skill.strip())
    used: set[str] = set()
    if groups:
        add("\n## Areas of expertise")
        for group in groups:
            evidence = [b for b, _ in _all_bullets(profile)
                        if group.lower() in b.lower() and b not in used][:3]
            if not evidence:
                continue
            add(f"\n### {group[:1].upper()}{group[1:]}")
            for bullet in evidence:
                used.add(bullet)
                add(f"- {bullet}")
        rest = [b for b, _ in _all_bullets(profile) if b not in used][:4]
        if rest:
            add("\n### Further highlights")
            for bullet in rest:
                add(f"- {bullet}")

    skills = _skill_line(profile, job, match)
    if skills:
        add("\n## Skills")
        add(skills)

    if profile.experience:
        add("\n## Career history")
        for entry in profile.experience:
            head = " — ".join(p for p in (entry.title, entry.company) if p) or "Role"
            period = entry.period if (entry.start or entry.end) else ""
            add(f"- **{head}**" + (f" ({period})" if period else "")
                + (f", {entry.location}" if entry.location else ""))

    if profile.education:
        add("\n## Education")
        for entry in profile.education:
            head = " — ".join(p for p in (entry.degree, entry.school) if p)
            add(f"- {head or 'Education'}" + (f" ({entry.period})" if entry.period else ""))
    if profile.languages.strip():
        add(f"\n**Languages:** {profile.languages.strip()}")
    return "\n".join(lines).strip() + "\n"


def render_executive(profile: Profile, job: JobPosting | None = None, match=None) -> str:  # noqa: ANN001
    """Leadership brief: headline achievements first, then roles with scope."""
    lines: list[str] = []
    add = lines.append

    add(f"# {profile.display_name}")
    subtitle = " · ".join(p for p in (profile.headline.strip(), profile.location.strip()) if p)
    if subtitle:
        add(f"### {subtitle}")
    contact = " | ".join(p for p in (profile.email, profile.phone) if p.strip())
    if contact:
        add(contact)
    if profile.links.strip():
        add(profile.links.strip())

    summary = _tailored_summary(profile, job)
    if summary:
        add("\n## Executive summary")
        add(summary)

    highlights = _impact_bullets(profile, job, 5)
    if highlights:
        add("\n## Selected achievements")
        for bullet in highlights:
            add(f"- {bullet}")

    if profile.experience:
        add("\n## Leadership experience")
        for entry in profile.experience:
            add(f"\n### {entry.title or 'Role'}"
                + (f", {entry.company}" if entry.company else ""))
            meta = " · ".join(p for p in (entry.period if (entry.start or entry.end) else "",
                                          entry.location) if p)
            if meta:
                add(f"*{meta}*")
            if entry.summary.strip() and entry.highlights:
                add(entry.summary.strip())
            for bullet in _bullets(entry, job, 3):
                if bullet not in highlights:
                    add(f"- {bullet}")

    skills = _skill_line(profile, job, match)
    if skills:
        add("\n## Expertise")
        add(skills)

    if profile.education:
        add("\n## Education")
        for entry in profile.education:
            head = ", ".join(p for p in (entry.degree, entry.school) if p)
            add(f"- {head or 'Education'}" + (f" ({entry.period})" if entry.period else ""))
    if profile.languages.strip():
        add(f"\n**Languages:** {profile.languages.strip()}")
    return "\n".join(lines).strip() + "\n"


def render_technical(profile: Profile, job: JobPosting | None = None, match=None) -> str:  # noqa: ANN001
    """Engineering layout: stack per role + a keyword-coverage block for the posting."""
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

    add("\n## Technical skills")
    skills = [s.strip() for s in profile.skills if s.strip()]
    if job:
        wanted = [t.lower() for t in job.tags if t.strip()]
        primary = [s for s in skills if s.lower() in wanted]
        secondary = [s for s in skills if s.lower() not in wanted]
        if match is not None and match.matched_keywords:
            block = {t for t in tokenize(job.title) + tokenize(job.company)}
            extras = specific_keywords(
                [k for k in match.matched_keywords if k.lower() not in {s.lower() for s in skills}],
                extra_block=block, limit=6)
            primary += extras
        if primary:
            add(f"- **Relevant to this role:** {', '.join(primary)}")
        if secondary:
            add(f"- **Also:** {', '.join(secondary[:20])}")
        if match is not None and match.missing_keywords:
            # only real technologies the posting *tagged*; no free-text noise
            tagged = [t for t in match.missing_keywords if t.lower() in wanted
                      and "." not in t and "@" not in t]
            gaps = specific_keywords(tagged, limit=6)
            if gaps:
                add(f"- *Posting also asks for:* {', '.join(gaps)}")
    elif skills:
        add(", ".join(skills[:26]))
    if profile.languages.strip():
        add(f"- **Languages:** {profile.languages.strip()}")

    if profile.experience:
        add("\n## Experience")
        for entry in profile.experience:
            add(f"\n### {entry.title or 'Role'}"
                + (f" — {entry.company}" if entry.company else ""))
            meta = " | ".join(p for p in (entry.period if (entry.start or entry.end) else "",
                                          entry.location) if p)
            if meta:
                add(f"*{meta}*")
            stack = _entry_stack(entry, job, profile)
            if stack:
                add(f"**Stack:** {', '.join(stack[:10])}")
            for bullet in _bullets(entry, job, 5):
                add(f"- {bullet}")

    if profile.education:
        add("\n## Education")
        for entry in profile.education:
            head = " — ".join(p for p in (entry.degree, entry.school) if p)
            add(f"- **{head or 'Education'}**"
                + (f" ({entry.period})" if entry.period else "")
                + (f" — {entry.details.strip()}" if entry.details.strip() else ""))

    if job:
        add("\n---")
        add(f"*Prepared for **{job.title}** at **{job.company}** · {date.today().isoformat()}*")
    return "\n".join(lines).strip() + "\n"


RENDERERS = {"modern": render_modern, "classic": render_classic, "compact": render_compact,
             "functional": render_functional, "executive": render_executive,
             "technical": render_technical}


# --------------------------------------------------------------------------- #
# user-supplied templates
# --------------------------------------------------------------------------- #
def template_context(profile: Profile, job: JobPosting | None = None, match=None) -> dict:  # noqa: ANN001
    """The variables a custom template can read (see ``docs/cv-templates.md``)."""
    experience = []
    for entry in profile.experience:
        experience.append({
            "title": entry.title, "company": entry.company, "location": entry.location,
            "start": entry.start, "end": entry.end or "present",
            "period": entry.period if (entry.start or entry.end) else "",
            "summary": entry.summary, "bullets": _bullets(entry, job, 8),
            "stack": _entry_stack(entry, job, profile),
        })
    education = []
    for entry in profile.education:
        education.append({
            "degree": entry.degree, "school": entry.school, "location": entry.location,
            "start": entry.start, "end": entry.end, "period": entry.period,
            "details": entry.details,
        })
    context = {
        "name": profile.display_name,
        "headline": profile.headline.strip(),
        "email": profile.email, "phone": profile.phone, "location": profile.location,
        "links": profile.links.strip(),
        "contact": _contact_line(profile).replace("\n", " · "),
        "summary": profile.summary.strip(),
        "tailored_summary": _tailored_summary(profile, job),
        "skills": [s.strip() for s in profile.skills if s.strip()],
        "skills_line": _skill_line(profile, job, match),
        "languages": profile.languages.strip(),
        "experience": experience,
        "education": education,
        "highlights": _impact_bullets(profile, job, 5),
        "desired_titles": list(profile.desired_titles),
        "seniority": profile.seniority,
        "today": date.today().isoformat(),
        "job": None,
        "match": None,
    }
    if job is not None:
        context["job"] = {
            "title": job.title, "company": job.company, "location": job.location,
            "remote": job.remote, "salary": job.salary_text, "url": job.url,
            "tags": list(job.tags), "source": job.source,
        }
    if match is not None:
        context["match"] = {
            "score": getattr(match, "score", 0),
            "matched_keywords": list(getattr(match, "matched_keywords", []) or []),
            "missing_keywords": list(getattr(match, "missing_keywords", []) or []),
            "reasons": list(getattr(match, "reasons", []) or []),
        }
    return context


STARTER_TEMPLATE = """{# JAUTOMATIC custom CV template — edit freely, the app re-reads it on every render.
   Placeholders: {{ name }} {{ headline }} {{ contact }} {{ tailored_summary }}
   {{ skills_line }} {{ languages }} {{ today }}; loops over experience / education /
   highlights / skills; {{ job.title }} {{ job.company }} {{ match.score }} when tailoring.
   Tags on a line of their own leave no blank line behind. Full reference: docs/cv-templates.md #}
# {{ name }}
{% if headline %}
### {{ headline }}
{% endif %}
{{ contact }}

## Profile
{{ tailored_summary }}

## Skills
{{ skills_line }}
{% if languages %}

**Languages:** {{ languages }}
{% endif %}

## Experience
{% for role in experience %}

### {{ role.title }}{% if role.company %} — {{ role.company }}{% endif %}
*{{ role.period }}{% if role.location %} | {{ role.location }}{% endif %}*
{% for bullet in role.bullets %}
- {{ bullet }}
{% endfor %}
{% endfor %}

## Education
{% for school in education %}
- **{{ school.degree }}** — {{ school.school }}{% if school.period %} ({{ school.period }}){% endif %}
{% endfor %}
{% if job %}

---
*Tailored for **{{ job.title }}** at **{{ job.company }}** · {{ today }}*
{% endif %}
"""


def is_custom_template(template: str) -> bool:
    return bool(template) and template.startswith(CUSTOM_PREFIX)


def custom_template_label(template: str) -> str:
    """``custom:my-cv.md`` -> ``My cv (custom)``."""
    stem = Path(template[len(CUSTOM_PREFIX):]).stem.replace("-", " ").replace("_", " ")
    return f"{stem[:1].upper()}{stem[1:]} (custom)" if stem else "Custom template"


def template_label(template: str) -> str:
    if is_custom_template(template):
        return custom_template_label(template)
    return TEMPLATE_LABELS.get(template, template)


@dataclass
class CustomTemplate:
    name: str            # ``custom:<file name>``
    path: Path
    error: str | None = None

    @property
    def label(self) -> str:
        return custom_template_label(self.name)

    @property
    def ok(self) -> bool:
        return self.error is None


class TemplateRegistry:
    """Discovers ``*.md`` templates in ``directory`` and renders them safely."""

    def __init__(self, directory: str | Path | None) -> None:
        self.directory = Path(directory) if directory else None

    def ensure_directory(self) -> Path | None:
        if self.directory is None:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        return self.directory

    def path_for(self, template: str) -> Path | None:
        if self.directory is None or not is_custom_template(template):
            return None
        filename = template[len(CUSTOM_PREFIX):]
        if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
            return None
        return self.directory / filename

    def list(self) -> list[CustomTemplate]:
        if self.directory is None or not self.directory.is_dir():
            return []
        out: list[CustomTemplate] = []
        for path in sorted(self.directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in CUSTOM_SUFFIXES  \
                    or path.name.startswith("."):
                continue
            try:
                error = template_engine.validate(path.read_text("utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                error = f"cannot read: {exc}"
            out.append(CustomTemplate(name=f"{CUSTOM_PREFIX}{path.name}", path=path, error=error))
        return out

    def names(self) -> list[str]:
        return [t.name for t in self.list() if t.ok]

    def exists(self, template: str) -> bool:
        path = self.path_for(template)
        return bool(path and path.is_file())

    def source(self, template: str) -> str:
        path = self.path_for(template)
        if not path or not path.is_file():
            raise FileNotFoundError(f"custom template not found: {template}")
        return path.read_text("utf-8")

    def render(self, template: str, profile: Profile, job: JobPosting | None = None,
               match=None) -> str:  # noqa: ANN001
        """Render a custom template; raises ``TemplateError``/``FileNotFoundError``."""
        return template_engine.render(self.source(template), template_context(profile, job, match))

    def create_starter(self, filename: str = "my-template.md") -> Path:
        """Write the annotated starter template (never overwrites) and return its path."""
        directory = self.ensure_directory()
        if directory is None:
            raise RuntimeError("no template directory configured")
        filename = Path(filename).name or "my-template.md"
        if Path(filename).suffix.lower() not in CUSTOM_SUFFIXES:
            filename += ".md"
        target = directory / filename
        counter = 2
        while target.exists():
            target = directory / f"{Path(filename).stem}-{counter}{Path(filename).suffix}"
            counter += 1
        target.write_text(STARTER_TEMPLATE, encoding="utf-8")
        return target


def render_markdown(profile: Profile, job: JobPosting | None = None, template: str = "modern",
                    match=None, registry: TemplateRegistry | None = None) -> str:  # noqa: ANN001
    """Render ``template`` (built-in name or ``custom:<file>``) to Markdown.

    Unknown built-ins fall back to ``modern``; so does a custom template whose
    file went missing or no longer parses - a CV is always produced, and the
    caller can surface the problem via :meth:`CVGenerator.generate`'s
    ``GeneratedDocument.warning``.
    """
    if is_custom_template(template) and registry is not None:
        try:
            return registry.render(template, profile, job, match)
        except (template_engine.TemplateError, FileNotFoundError, OSError, UnicodeDecodeError):
            return render_modern(profile, job, match)
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


def document_suffix(fmt: str) -> str:
    """Canonical file suffix for an export format (mirrors ``export``'s mapping)."""
    fmt = (fmt or "docx").lower()
    if fmt in ("md", "markdown"):
        return ".md"
    if fmt in ("txt", "text"):
        return ".txt"
    return ".docx"


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
    """Renders a CV for a profile (+ optional target job) and stores it.

    ``templates_dir`` (normally ``<data dir>/templates``) enables user-supplied
    templates; without it only the built-ins are available.
    """

    def __init__(self, templates_dir: str | Path | None = None) -> None:
        self.registry = TemplateRegistry(templates_dir)

    # -- template catalogue ------------------------------------------------ #
    def available_templates(self) -> list[tuple[str, str]]:
        """``(name, label)`` pairs: built-ins first, then valid custom files."""
        out = [(name, TEMPLATE_LABELS[name]) for name in TEMPLATES]
        out += [(t.name, t.label) for t in self.registry.list() if t.ok]
        return out

    def resolve_template(self, template: str) -> tuple[str, str]:
        """Return ``(effective template, warning)`` — falls back to ``modern``."""
        if template in TEMPLATES:
            return template, ""
        if is_custom_template(template):
            if not self.registry.exists(template):
                return "modern", (f"Custom template “{template[len(CUSTOM_PREFIX):]}” was not "
                                  f"found in {self.registry.directory} — used “modern” instead.")
            try:
                error = template_engine.validate(self.registry.source(template))
            except (OSError, UnicodeDecodeError) as exc:
                error = str(exc)
            if error:
                return "modern", (f"Custom template “{template[len(CUSTOM_PREFIX):]}” has an "
                                  f"error ({error}) — used “modern” instead.")
            return template, ""
        return "modern", ""

    # -- rendering --------------------------------------------------------- #
    def generate(self, profile: Profile, job: JobPosting | None = None, template: str = "modern",
                 output_dir: Path | None = None, fmt: str = "docx",
                 match=None, *, reuse: str | Path | None = None) -> GeneratedDocument:  # noqa: ANN001
        template, warning = self.resolve_template(template or "modern")
        markdown = render_markdown(profile, job, template, match, registry=self.registry)
        used = [k for k in (job.tags if job else []) if k]
        document = GeneratedDocument(kind="cv", text=markdown, template=template,
                                     used_keywords=used[:10], warning=warning)
        if output_dir is not None:
            stem = f"CV_{slugify(profile.display_name, 30)}"
            key = f"cv|{profile.display_name}"
            if job:
                stem += f"_{slugify(job.company, 20)}_{slugify(job.title, 24)}"
                key += f"|{job.company}|{job.title}"
            path = unique_document_path(output_dir, stem, document_suffix(fmt),
                                        key=key, reuse=reuse)
            document.path = export(markdown, path, fmt,
                                   title=f"CV – {profile.display_name}")
        return document
