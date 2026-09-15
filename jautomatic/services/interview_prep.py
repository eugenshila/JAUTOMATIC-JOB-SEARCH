"""Interview preparation: a per-application notes sheet and question bank.

Everything is deterministic and offline, in the spirit of the other
generators: the question bank is *derived* from the posting (its tags, title
and text), the match analysis (what you cover, what you don't) and your own
profile (achievements become STAR prompts).  Nothing is invented — a question
about Kubernetes only appears when the posting or your profile mentions it.

Data model (stored as JSON on the application row):

    {
      "notes": "free text — company research, interviewer names, logistics",
      "questions": [
        {"id": "q-3f2a", "category": "technical", "question": "…",
         "hint": "why it is likely to come up", "answer": "your prepared answer",
         "starred": false, "source": "generated" | "custom"}
      ],
      "generated_at": "2026-09-15 10:00:00"
    }

The service also renders the whole sheet to Markdown so it can be exported
next to the CV / cover letter (``PREP_<you>_<company>_<role>.md``).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..models import (Application, JobPosting, Profile, human_join, now_iso, pretty_term,
                      slugify, specific_keywords, tokenize, unique_document_path)

CATEGORIES = ("opening", "technical", "behavioural", "gap", "role", "ask")
CATEGORY_LABELS = {
    "opening": "Opening & motivation",
    "technical": "Technical — from the posting",
    "behavioural": "Behavioural — your achievements (STAR)",
    "gap": "Gaps — skills the posting names that your profile does not",
    "role": "Role, team & logistics",
    "ask": "Questions to ask them",
}
SOURCE_GENERATED = "generated"
SOURCE_CUSTOM = "custom"


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
@dataclass
class PrepQuestion:
    question: str
    category: str = "technical"
    hint: str = ""
    answer: str = ""
    starred: bool = False
    source: str = SOURCE_GENERATED
    id: str = ""

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            self.category = "technical"
        if not self.id:
            self.id = question_id(self.question, self.category)

    @property
    def answered(self) -> bool:
        return bool(self.answer.strip())

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    def to_dict(self) -> dict:
        return {"id": self.id, "category": self.category, "question": self.question,
                "hint": self.hint, "answer": self.answer, "starred": self.starred,
                "source": self.source}

    @classmethod
    def from_dict(cls, data: dict) -> "PrepQuestion":
        data = data or {}
        return cls(question=str(data.get("question") or "").strip(),
                   category=str(data.get("category") or "technical"),
                   hint=str(data.get("hint") or ""), answer=str(data.get("answer") or ""),
                   starred=bool(data.get("starred")),
                   source=str(data.get("source") or SOURCE_GENERATED),
                   id=str(data.get("id") or ""))


@dataclass
class InterviewPrep:
    notes: str = ""
    questions: list[PrepQuestion] = field(default_factory=list)
    generated_at: str = ""

    # -- derived ----------------------------------------------------------- #
    @property
    def is_empty(self) -> bool:
        return not self.notes.strip() and not self.questions

    @property
    def answered_count(self) -> int:
        return sum(1 for q in self.questions if q.answered)

    @property
    def progress_text(self) -> str:
        if not self.questions:
            return "no questions yet"
        return f"{self.answered_count}/{len(self.questions)} answered"

    def by_category(self) -> list[tuple[str, list[PrepQuestion]]]:
        groups: list[tuple[str, list[PrepQuestion]]] = []
        for category in CATEGORIES:
            items = [q for q in self.questions if q.category == category]
            if items:
                groups.append((category, items))
        return groups

    def find(self, question_id: str) -> PrepQuestion | None:
        for question in self.questions:
            if question.id == question_id:
                return question
        return None

    # -- mutation ---------------------------------------------------------- #
    def add_question(self, question: str, category: str = "technical",
                     hint: str = "", source: str = SOURCE_CUSTOM) -> PrepQuestion:
        text = " ".join(question.split())
        if not text:
            raise ValueError("The question text is empty.")
        existing = self.find(question_id(text, category))
        if existing:
            return existing
        item = PrepQuestion(question=text, category=category, hint=hint, source=source)
        self.questions.append(item)
        return item

    def remove_question(self, question_id_: str) -> bool:
        before = len(self.questions)
        self.questions = [q for q in self.questions if q.id != question_id_]
        return len(self.questions) < before

    def merge_generated(self, generated: list[PrepQuestion]) -> int:
        """Add generated questions that are not there yet; keep answers. Returns #added."""
        known = {q.id for q in self.questions}
        added = 0
        for question in generated:
            if question.id in known:
                continue
            self.questions.append(question)
            known.add(question.id)
            added += 1
        self.generated_at = now_iso()
        return added

    # -- serialisation ----------------------------------------------------- #
    def to_dict(self) -> dict:
        return {"notes": self.notes, "questions": [q.to_dict() for q in self.questions],
                "generated_at": self.generated_at}

    @classmethod
    def from_dict(cls, data: dict | None) -> "InterviewPrep":
        data = data or {}
        questions = [PrepQuestion.from_dict(q) for q in (data.get("questions") or [])
                     if isinstance(q, dict)]
        return cls(notes=str(data.get("notes") or ""),
                   questions=[q for q in questions if q.question],
                   generated_at=str(data.get("generated_at") or ""))


def question_id(question: str, category: str) -> str:
    """Stable id so regenerating never duplicates a question you already answered."""
    key = f"{category}|{' '.join(question.lower().split())}"
    return "q-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


# --------------------------------------------------------------------------- #
# generation
# --------------------------------------------------------------------------- #
def _match_lists(match) -> tuple[list[str], list[str]]:  # noqa: ANN001
    matched = list(getattr(match, "matched_keywords", []) or []) if match is not None else []
    missing = list(getattr(match, "missing_keywords", []) or []) if match is not None else []
    return matched, missing


def _posting_tags(job: JobPosting) -> list[str]:
    block = set(tokenize(job.company))
    tags = [t for t in job.tags if t and t.strip()]
    return specific_keywords(tags, extra_block=block, limit=8, min_length=2)


def _profile_skills_in_posting(profile: Profile, job: JobPosting, matched: list[str]) -> list[str]:
    hay = f"{job.title} {job.description} {' '.join(job.tags)}".lower()
    ordered: list[str] = []
    for skill in profile.skills:
        low = skill.strip().lower()
        if low and (low in hay or low in [m.lower() for m in matched]):
            ordered.append(low)
    return ordered


def _achievement_bullets(profile: Profile) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for entry in profile.experience:
        for bullet in entry.as_bullets():
            out.append((bullet, entry.company or entry.title))
    return out


def _has_number(text: str) -> bool:
    return bool(re.search(r"\d", text))


def _mentions(job: JobPosting, *needles: str) -> bool:
    hay = f"{job.title} {job.description} {' '.join(job.tags)}".lower()
    return any(n in hay for n in needles)


def generate_questions(profile: Profile, job: JobPosting, match=None) -> list[PrepQuestion]:  # noqa: ANN001
    """Build the question bank for one posting from what we actually know."""
    matched, missing = _match_lists(match)
    questions: list[PrepQuestion] = []

    def add(category: str, question: str, hint: str = "") -> None:
        item = PrepQuestion(question=question, category=category, hint=hint)
        if all(q.id != item.id for q in questions):
            questions.append(item)

    company = job.company or "the company"
    title = job.title or "this role"

    # -- opening ----------------------------------------------------------- #
    add("opening", "Tell me about yourself.",
        "60–90 seconds: current role → the two achievements most relevant to "
        f"{title} → why {company} now. Use your CV headline as the spine.")
    add("opening", f"Why {company}, and why this {title} role?",
        "Quote something specific from the posting — product, team, stack — and "
        "connect it to what you want next.")
    if profile.desired_titles and not any(
            t.lower() in title.lower() or title.lower() in t.lower() for t in profile.desired_titles):
        add("opening", f"Your target roles are {human_join(profile.desired_titles[:3])}; "
                       f"how does {title} fit that plan?",
            "The title is outside your stated targets — have a one-line bridge ready.")
    if job.remote:
        add("opening", "How do you stay effective and visible in a remote team?",
            "The posting is remote-friendly; talk about async writing, overlap hours, demos.")
    if job.location and profile.location and job.location.lower() not in profile.location.lower() \
            and not job.remote:
        add("opening", f"The role is based in {job.location}. What is your situation regarding "
                       "location or relocation?",
            "Your profile says " + (profile.location or "another location")
            + (" and you are open to relocating." if profile.willing_to_relocate
               else " — settle this before the first call."))

    # -- technical: the posting's own tags, strongest first --------------- #
    tags = _posting_tags(job)
    covered = _profile_skills_in_posting(profile, job, matched)
    known_phrasings = (
        "Walk me through the most complex thing you have built with {t}.",
        "What do people commonly get wrong with {t}, and how do you avoid it?",
        "How would you explain your approach to {t} to a new team member?",
        "Tell me about a production problem involving {t} and how you debugged it.",
        "Where does {t} fit in a system you designed, and what would you swap it for today?",
        "How do you test and monitor code that relies on {t}?",
    )
    known_hints = (
        "Tagged in the posting and present in your profile — pick one concrete system, "
        "the trade-offs, what you would do differently.",
        "Depth check: a specific pitfall + the practice you use to avoid it beats a list.",
        "Tests whether you can teach: structure it as principles, then one example.",
        "Have the timeline: symptom → hypothesis → tooling → fix → what prevented a repeat.",
        "Architecture-level answer: why it was chosen, its limits, honest alternatives.",
        "Name the test layers and the metrics/alerts you would actually look at.",
    )
    slot = 0
    gaps: list[str] = []
    for tag in tags:
        pretty = pretty_term(tag)
        if tag.lower() in covered:
            add("technical", known_phrasings[slot % len(known_phrasings)].format(t=pretty),
                known_hints[slot % len(known_hints)])
            slot += 1
        else:
            gaps.append(tag)
    for keyword in matched[:6]:
        if keyword.lower() in [t.lower() for t in tags]:
            continue
        pretty = pretty_term(keyword)
        add("technical", f"The posting mentions {pretty}. Where have you used it, and at what scale?",
            "Appears in the posting text and in your profile — have a specific example ready.")
    if _mentions(job, "design", "architecture", "scal", "distributed", "platform"):
        add("technical", "Sketch the architecture of a system you owned end-to-end. Where "
                         "were the bottlenecks and how did you find them?",
            "The posting talks about design/scale/platform work — expect a whiteboard-style "
            "question; rehearse it out loud.")
    if _mentions(job, "test", "quality", "ci", "reliab", "sre", "on-call", "incident"):
        add("technical", "How do you decide what to test, and how do you keep production "
                         "reliable? Describe an incident you handled.",
            "Posting mentions testing/reliability — bring one real incident with a timeline.")
    if _mentions(job, "lead", "mentor", "senior", "staff", "principal", "manage", "head of"):
        add("technical", "How do you review code and mentor less experienced engineers "
                         "without becoming the bottleneck?",
            "Seniority signals in the posting — they will probe how you multiply others.")

    # -- behavioural: your achievements as STAR prompts ------------------- #
    bullets = _achievement_bullets(profile)
    ranked = sorted(bullets, key=lambda pair: (not _has_number(pair[0]), -len(pair[0])))
    for bullet, where in ranked[:4]:
        short = bullet.rstrip(".")
        if len(short) > 90:
            short = short[:87].rstrip() + "…"
        add("behavioural", f"Your CV says: “{short}” ({where}). Take me through it.",
            "STAR: Situation (1 sentence), Task, Actions *you* took, Result with the number. "
            "Follow-up they will ask: what went wrong / what you would change.")
    add("behavioural", "Tell me about a time you disagreed with a decision. What did you do?",
        "Pick one where you disagreed, committed, and the outcome taught you something.")
    add("behavioural", "Describe a project that failed or slipped. What was your part in it?",
        "Own it. Interviewers reward candour with a concrete lesson far more than a "
        "disguised success story.")

    # -- gaps: the employer's own tags that your profile does not cover --- #
    # (free-text keywords are deliberately ignored here: "night", "shift" or
    # "incident" are not skills, and guessing makes the sheet noisy)
    gap_phrasings = (
        "How much hands-on experience do you have with {t}?",
        "We rely on {t}. How would you get productive with it in your first weeks?",
        "What is the closest thing to {t} you have worked with?",
    )
    for index, tag in enumerate(gaps[:5]):
        pretty = pretty_term(tag)
        add("gap", gap_phrasings[index % len(gap_phrasings)].format(t=pretty),
            "Tagged in the posting but not in your profile — be honest, name the nearest "
            "equivalent you know and a concrete ramp-up plan (or add it to your profile if "
            "you simply forgot to list it).")
    if not gaps and missing:
        add("gap", "Is there anything in the job description you have not done before?",
            "Your profile covers every tag the posting lists; the free text still mentions "
            f"{human_join([pretty_term(m) for m in missing[:3]])} — decide in advance how "
            "you frame those.")

    # -- role & logistics ------------------------------------------------- #
    if job.salary_min or job.salary_max:
        add("role", "What are your salary expectations?",
            f"The posting advertises {job.salary_text}"
            + (f"; your floor is {profile.salary_floor:,} {profile.currency}."
               if profile.salary_floor else ".")
            + " Give a range anchored on the band, not a single number.")
    else:
        add("role", "What are your salary expectations?",
            "No band advertised" + (f" — your floor is {profile.salary_floor:,} "
                                    f"{profile.currency}. " if profile.salary_floor else ". ")
            + "Ask for their range first; if pushed, give a range, not a number.")
    add("role", "When could you start, and what does your notice period look like?",
        "Have the exact date; mention holidays already booked.")
    add("role", "Where do you see yourself in two to three years?",
        "Tie it to the growth this role offers rather than a job title.")

    # -- questions to ask them ------------------------------------------- #
    add("ask", "What does success look like in the first 90 days for this role?",
        "Shows you think in outcomes; the answer tells you how clear the role really is.")
    add("ask", "How does the team decide what to build next, and who owns that decision?",
        "Reveals product/engineering dynamics and how much autonomy you would have.")
    if tags:
        add("ask", f"How is {pretty_term(tags[0])} used here today, and what would you change "
                   "about the current setup?",
            "Their headline tag — the answer tells you the real state of the stack.")
    if job.remote:
        add("ask", "How does the team work across time zones — meetings, async decisions, "
                   "on-site meet-ups?", "Remote role: find out before you find out the hard way.")
    add("ask", "What is the interview process from here, and when will I hear back?",
        "Always ask — it also gives you the date for your follow-up e-mail.")
    add("ask", "Why is the position open — growth, or did someone leave?",
        "Politely asked, this is one of the most informative questions there is.")
    return questions


# --------------------------------------------------------------------------- #
# rendering / export
# --------------------------------------------------------------------------- #
def render_prep_markdown(prep: InterviewPrep, profile: Profile, job: JobPosting,
                         application: Application | None = None) -> str:
    lines: list[str] = []
    add = lines.append
    add(f"# Interview prep — {job.title or 'role'} at {job.company or 'company'}")
    meta = [f"candidate: {profile.display_name}"]
    if application is not None and application.interview_at:
        meta.append(f"interview: {application.interview_at}")
    if job.location or job.remote:
        meta.append("location: " + (job.display_location or "remote"))
    if job.salary_text:
        meta.append(f"advertised: {job.salary_text}")
    if job.url:
        meta.append(f"posting: {job.url}")
    add("*" + " · ".join(meta) + "*")
    if prep.questions:
        add(f"\n**Progress:** {prep.progress_text}"
            + (f" · generated {prep.generated_at[:10]}" if prep.generated_at else ""))
    if prep.notes.strip():
        add("\n## Notes")
        add(prep.notes.strip())
    for category, items in prep.by_category():
        add(f"\n## {CATEGORY_LABELS[category]}")
        for question in items:
            star = "★ " if question.starred else ""
            add(f"\n### {star}{question.question}")
            if question.hint:
                add(f"*{question.hint}*")
            if question.answer.strip():
                add("")
                add(question.answer.strip())
            else:
                add("\n_(no answer prepared yet)_")
    if not prep.questions and not prep.notes.strip():
        add("\n_(nothing prepared yet — generate a question bank or add notes)_")
    return "\n".join(lines).strip() + "\n"


def export_prep(prep: InterviewPrep, profile: Profile, job: JobPosting, output_dir: Path,
                application: Application | None = None, fmt: str = "md") -> Path:
    """Write the sheet next to the other documents (Markdown by default)."""
    from .cv_generator import document_suffix, export  # local import: avoids a cycle at load

    fmt = (fmt or "md").lower()
    stem = (f"PREP_{slugify(profile.display_name, 30)}_{slugify(job.company, 20)}"
            f"_{slugify(job.title, 24)}")
    key = f"prep|{profile.display_name}|{job.company}|{job.title}"
    reuse = (application.prep_path or None) if application is not None else None
    path = unique_document_path(output_dir, stem, document_suffix(fmt), key=key, reuse=reuse)
    return export(render_prep_markdown(prep, profile, job, application), path, fmt,
                  title=f"Interview prep – {job.title} @ {job.company}")


__all__ = ["CATEGORIES", "CATEGORY_LABELS", "InterviewPrep", "PrepQuestion", "export_prep",
           "generate_questions", "question_id", "render_prep_markdown"]
