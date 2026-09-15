"""Deterministic application-form autofill: profile → field aliases → fill plan.

This module is the *planning* half of assisted autofill.  It knows nothing about
browsers: it parses form HTML (stdlib only), matches every field against a
taxonomy of canonical application questions, resolves answers from the user's
profile / generated application pack, and emits a reviewable fill plan.

Two guarantees matter:

* **Deterministic** — the same (HTML, profile, overrides) always produce the
  exact same plan.  No randomness, no wall-clock reads inside planning.
* **Never submits** — the planner has no code path that produces a submit
  action.  Filling is the machine's job; reviewing and pressing *Send* stays
  with the human (that is the difference between this and the account-banning
  kind of automation).

The browser half lives in :mod:`jautomatic.services.autofill_browser` and is a
thin adapter that executes a plan field-by-field and stops.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

__all__ = [
    "FormField", "SelectOption", "FieldMatch", "FillAction", "FillPlan",
    "ProfileAnswers", "FIELD_SPECS", "parse_html", "build_plan", "plan_for_html",
]

# --------------------------------------------------------------------------- #
# canonical field taxonomy
# --------------------------------------------------------------------------- #
# ``strong`` / ``weak`` are normalised tokens (see _norm) matched against the
# signals a field carries: label, name/id, placeholder, aria-label, autocomplete.
# ``kinds`` restricts a spec to compatible control kinds.  ``boolean`` marks
# yes/no questions (selects, radios, checkboxes).
@dataclass(frozen=True)
class FieldSpec:
    key: str
    strong: tuple[str, ...] = ()
    weak: tuple[str, ...] = ()
    autocompletes: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ("text", "email", "tel", "url", "textarea",
                              "number", "date", "search")
    boolean: bool = False
    type_boost: str | None = None    # input type that strongly implies this key


def _spec(key, strong=(), weak=(), autocompletes=(), kinds=None, boolean=False,
          type_boost=None):
    return FieldSpec(key=key, strong=tuple(strong), weak=tuple(weak),
                     autocompletes=tuple(autocompletes),
                     kinds=tuple(kinds) if kinds else FieldSpec.__dataclass_fields__["kinds"].default,  # type: ignore[attr-defined]
                     boolean=boolean, type_boost=type_boost)


_TEXTY = ("text", "email", "tel", "url", "textarea", "number", "date", "search")
_CHOICEY = ("select", "radio", "checkbox")

FIELD_SPECS: dict[str, FieldSpec] = {s.key: s for s in [
    _spec("first_name",
          strong=("first name", "firstname", "given name", "fname", "forename"),
          autocompletes=("given-name",)),
    _spec("last_name",
          strong=("last name", "lastname", "surname", "family name", "lname"),
          autocompletes=("family-name",)),
    _spec("full_name", strong=("full name", "your name"),
          weak=("name", "applicant name", "candidate name"), autocompletes=("name",)),
    _spec("email", strong=("email", "e mail"), autocompletes=("email",),
          type_boost="email"),
    _spec("phone", strong=("phone", "mobile", "cell", "telephone"),
          weak=("tel",), autocompletes=("tel", "tel-national"), type_boost="tel"),
    _spec("location",
          strong=("location", "city", "where are you based", "where do you live",
                  "place of residence"),
          weak=("address",), autocompletes=("address-level2", "country-name")),
    _spec("linkedin_url", strong=("linkedin",)),
    _spec("github_url", strong=("github",)),
    _spec("portfolio_url",
          strong=("portfolio", "personal site", "personal website")),
    _spec("website", strong=("website", "home page"), weak=("url", "link"),
          type_boost="url"),
    _spec("resume_file", strong=("resume", "cv"), weak=("attachment",),
          kinds=("file",), type_boost="file"),
    _spec("cover_letter_file", strong=("cover letter", "motivation letter"),
          kinds=("file",)),
    _spec("cover_letter_text", strong=("cover letter", "motivation letter",
                                       "letter of motivation"),
          kinds=("textarea",)),
    _spec("why_company",
          strong=("why do you want", "why are you interested", "why would you like",
                  "why do you think", "why this company", "what attracts you"),
          kinds=("textarea",)),
    _spec("years_experience", strong=("years of experience", "how many years",
                                      "years experience", "years you have")),
    _spec("salary_expectation",
          strong=("salary expectation", "expected salary", "salary requirement",
                  "desired salary", "compensation expectation", "pay expectation",
                  "expected pay", "expected compensation", "expected annual salary",
                  "annual salary"),
          weak=("salary",)),
    _spec("notice_period", strong=("notice period",)),
    _spec("start_date",
          strong=("earliest start", "start date", "earliest available",
                  "available from", "when can you start", "earliest possible start",
                  "earliest date")),
    _spec("work_authorization",
          strong=("authorized to work", "authorised to work", "right to work",
                  "work permit", "eligible to work", "legally authorized",
                  "legally authorised", "employment eligibility"),
          kinds=_TEXTY + _CHOICEY, boolean=True),
    _spec("requires_sponsorship",
          strong=("sponsorship", "sponsor", "require visa", "need visa",
                  "visa sponsorship"),
          kinds=_TEXTY + _CHOICEY, boolean=True),
    _spec("willing_to_relocate",
          strong=("relocate", "relocation", "willing to move"),
          kinds=_TEXTY + _CHOICEY, boolean=True),
    _spec("remote_ok", strong=("open to remote", "work remotely", "remote work",
                               "willing to work remote"),
          kinds=_TEXTY + _CHOICEY, boolean=True),
    _spec("how_did_you_hear",
          strong=("how did you hear", "how did you find", "where did you find",
                  "how did you learn", "where did you hear", "referral source"),
          kinds=_TEXTY + _CHOICEY),
    _spec("referral", strong=("who referred", "were you referred", "referred by"),
          kinds=_TEXTY + _CHOICEY),
    _spec("current_company",
          strong=("current company", "current employer", "organization",
                  "organisation", "company you work for", "employer", "company")),
    _spec("current_title",
          strong=("current title", "current role", "job title", "your title",
                  "current position"),
          weak=("title",), autocompletes=("organization-title",)),
    _spec("headline", strong=("headline", "professional headline")),
    _spec("skills", strong=("skills",)),
    _spec("languages", strong=("languages", "language skills")),
    _spec("education", strong=("education", "highest degree", "degree"),
          weak=("university",)),
]}

_AUTOCOMPLETE_MAP = {token: spec.key for spec in FIELD_SPECS.values()
                     for token in spec.autocompletes}
_TYPE_BOOST_MAP = {spec.type_boost: spec.key for spec in FIELD_SPECS.values()
                   if spec.type_boost and spec.type_boost != "file"}
_BOOLEAN_KEYS = {spec.key for spec in FIELD_SPECS.values() if spec.boolean}
_FILE_KEYS = {spec.key for spec in FIELD_SPECS.values() if "file" in spec.kinds}

# input types we never record or touch
_IGNORED_INPUT_TYPES = {"hidden", "submit", "button", "reset", "image", "password",
                        "checkbox", "radio"}   # checkbox/radio handled separately


# --------------------------------------------------------------------------- #
# text normalisation + token matching
# --------------------------------------------------------------------------- #
def _norm(text: str) -> str:
    """Lower-case, accent-free, alphanumerics-and-spaces only."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


def _has_token(normalized: str, token: str) -> bool:
    """Whole-word token match on an already-normalised string."""
    if not normalized or not token:
        return False
    return f" {token} " in f" {normalized} "


def _contains(haystack: str, needle: str) -> bool:
    """Loose containment used for option coercion and override matching."""
    return bool(haystack and needle) and needle in haystack


# --------------------------------------------------------------------------- #
# form model + HTML parsing (stdlib html.parser)
# --------------------------------------------------------------------------- #
@dataclass
class SelectOption:
    value: str = ""
    label: str = ""
    selected: bool = False


@dataclass
class FormField:
    """One form control, in document order, with every signal we could glean."""
    index: int                      # document-order position among all controls
    tag: str                        # input | select | textarea
    kind: str                       # text | email | tel | url | textarea | number |
                                    # date | file | select | radio | checkbox
    name: str = ""
    id: str = ""
    label: str = ""                 # best label we found (for= / wrapping / legend)
    label_source: str = ""          # for | wrap | legend | nearby | placeholder
    placeholder: str = ""
    aria_label: str = ""
    autocomplete: str = ""
    required: bool = False
    options: list[SelectOption] = field(default_factory=list)  # select + radio
    form_id: str = ""

    @property
    def signals(self) -> list[tuple[str, str, float]]:
        """(source, text, weight) triples used for matching, best weight first."""
        out = [("label", self.label, 0.55), ("name", self.name, 0.5),
               ("id", self.id, 0.5), ("aria-label", self.aria_label, 0.45),
               ("placeholder", self.placeholder, 0.55), ("form", self.form_id, 0.2)]
        return [(src, text, weight) for src, text, weight in out if text]

    @property
    def display_name(self) -> str:
        return self.label or self.placeholder or self.name or self.id or f"#{self.index}"


class _FormHTMLParser(HTMLParser):
    """Collects form controls + labels.  Label strategies, best first:

    ``<label for=id>``, a ``<label>`` wrapping the control (whether the text
    comes before *or* after the control), a ``<fieldset>`` ``<legend>`` for
    grouped radios, then plain text seen just before the control (the weakest
    signal — pages without any labels at all).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: list[FormField] = []
        self._labels_by_for: dict[str, str] = {}
        self._open_labels: list[dict] = []   # {"for", "parts", "field_index", "radio"}
        self._legend_parts: list[str] = []
        self._in_legend = False
        self._legend_stack: list[str] = []   # legend text per open <fieldset>
        self._nearby_text: str = ""          # text accumulated since last control
        self._current_select: FormField | None = None
        self._option_text: list[str] = []
        self._radio_groups: dict[str, FormField] = {}
        self._radio_options_by_id: dict[str, tuple[str, int]] = {}
        self._form_id = ""
        self._suppress = 0                   # >0 inside head/script/style/noscript

    # -- capture pass ------------------------------------------------------ #
    def handle_starttag(self, tag, attrs):
        attr = {k: (v or "") for k, v in attrs}
        if tag in ("head", "script", "style", "noscript"):
            self._suppress += 1
        elif tag == "form":
            self._form_id = attr.get("id") or attr.get("name") or ""
        elif tag == "label":
            self._open_labels.append({"for": attr.get("for", ""), "parts": [],
                                      "field_index": None, "radio": None})
            self._nearby_text = ""
        elif tag == "legend":
            self._in_legend = True
        elif tag == "fieldset":
            self._legend_stack.append("")
        elif tag == "select":
            created = self._new_field(tag, "select", attr)
            self._current_select = created
            label, source = self._label_for(attr)
            if not label and created.aria_label:
                label, source = created.aria_label, "aria"
            created.label, created.label_source = label, source
        elif tag == "option" and self._current_select is not None:
            self._option_text = []
            value = attr.get("value", "")
            selected = attr.get("selected") is not None
            self._current_select.options.append(
                SelectOption(value=value, label="", selected=selected))
        elif tag in ("input", "textarea"):
            self._record_input(tag, attr)

    def handle_startendtag(self, tag, attrs):
        if tag in ("input", "textarea"):
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "label" and self._open_labels:
            self._close_label(self._open_labels.pop())
        elif tag == "legend":
            self._in_legend = False
            if self._legend_stack:
                self._legend_stack[-1] = _clean_label("".join(self._legend_parts))
            self._legend_parts = []
        elif tag == "option" and self._current_select is not None \
                and self._current_select.options:
            option = self._current_select.options[-1]
            option.label = _clean_label("".join(self._option_text)) or option.value
        elif tag == "select":
            self._current_select = None
        elif tag == "fieldset":
            if self._legend_stack:
                self._legend_stack.pop()
        elif tag in ("head", "script", "style", "noscript"):
            self._suppress = max(0, self._suppress - 1)

    def handle_data(self, data):
        if self._suppress:
            return
        if self._current_select is not None:
            if self._current_select.options:
                self._option_text.append(data)
            return
        if self._open_labels:
            self._open_labels[-1]["parts"].append(data)
        elif self._in_legend:
            self._legend_parts.append(data)
        elif data.strip():
            self._nearby_text = (self._nearby_text + " " + data.strip()).strip()

    # -- helpers ----------------------------------------------------------- #
    def _new_field(self, tag: str, kind: str, attr: dict) -> FormField:
        index = len(self.fields)
        new = FormField(index=index, tag=tag, kind=kind,
                        name=attr.get("name", ""), id=attr.get("id", ""),
                        placeholder=attr.get("placeholder", ""),
                        aria_label=attr.get("aria-label", ""),
                        autocomplete=attr.get("autocomplete", ""),
                        required=attr.get("required") is not None
                        or attr.get("aria-required") == "true",
                        form_id=self._form_id)
        self.fields.append(new)
        self._nearby_text = ""
        if self._open_labels:
            self._open_labels[-1]["field_index"] = index
        return new

    def _legend_text(self) -> str:
        return self._legend_stack[-1] if self._legend_stack else ""

    def _label_for(self, attr: dict) -> tuple[str, str]:
        """(label text, source) for the control being created.

        Empty string with source ``""`` means "pending" — a ``<label>`` wrap is
        open but its text has not arrived yet; the closing tag back-patches it.
        """
        if attr.get("id") and attr["id"] in self._labels_by_for:
            return self._labels_by_for[attr["id"]], "for"
        if self._open_labels:
            text = _clean_label("".join(self._open_labels[-1]["parts"]))
            return (text, "wrap") if text else ("", "")
        legend = self._legend_text()
        if legend:
            return legend, "legend"
        if self._nearby_text:
            return self._nearby_text, "nearby"
        return "", ""

    def _close_label(self, label: dict) -> None:
        text = _clean_label("".join(label["parts"]))
        if not text:
            return
        # a <label> tied to a radio input (wrapping it, or pointing at it with
        # for=) names the *option*, not the question
        claimed = None
        if label["radio"] is not None:
            claimed = label["radio"]
        elif label["for"] and label["for"] in self._radio_options_by_id:
            claimed = self._radio_options_by_id[label["for"]]
        if claimed is not None:
            group, option_index = claimed
            option = self._radio_groups[group].options[option_index]
            option.label = text or option.value
            return
        if label["for"]:
            self._labels_by_for.setdefault(label["for"], text)
            return
        if label["field_index"] is not None:           # input claimed this label
            target = self.fields[label["field_index"]]
            if not target.label or target.label_source in ("", "placeholder", "aria",
                                                           "nearby"):
                target.label, target.label_source = text, "wrap"
            return                                      # claimed — never leak
        self._nearby_text = text                       # label for a later control

    def _record_input(self, tag: str, attr: dict) -> None:
        input_type = (attr.get("type") or "text").lower()
        if tag == "input" and input_type == "password":
            self._new_field(tag, "password", attr)     # recorded, never filled
            return
        if tag == "input" and input_type in ("hidden", "submit", "button", "reset",
                                             "image"):
            return
        if input_type == "radio":
            self._record_radio(attr)
            return
        kind = "textarea" if tag == "textarea" else input_type
        if input_type == "checkbox":
            kind = "checkbox"
        label, source = self._label_for(attr)
        created = self._new_field(tag, kind, attr)
        if not label and created.placeholder:
            label, source = created.placeholder, "placeholder"
        elif not label and created.aria_label:
            label, source = created.aria_label, "aria"
        created.label, created.label_source = label, source

    def _record_radio(self, attr: dict) -> None:
        name = attr.get("name", "")
        group = self._radio_groups.get(name)
        if group is None:
            nearby = self._nearby_text
            group = self._new_field("input", "radio", attr)
            group.name, group.id, group.options = name, "", []
            self._radio_groups[name] = group
            legend = self._legend_text()
            if legend:
                group.label, group.label_source = legend, "legend"
            elif nearby:
                group.label, group.label_source = nearby, "nearby"
        option_label, source = self._label_for(attr)
        group.options.append(SelectOption(value=attr.get("value", ""),
                                          label=option_label if source in ("for", "wrap")
                                          else attr.get("value", ""),
                                          selected=attr.get("checked") is not None))
        if self._open_labels:                          # claim the wrapping label
            self._open_labels[-1]["radio"] = (name, len(group.options) - 1)
        if attr.get("id"):                             # …or a later for= label
            self._radio_options_by_id[attr["id"]] = (name, len(group.options) - 1)


def _clean_label(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_html(html: str) -> list[FormField]:
    """Parse form controls out of an HTML document (or fragment)."""
    parser = _FormHTMLParser()
    parser.feed(html)
    parser.close()
    # drop empty radio groups and password-less duplicates; keep document order
    fields = [f for f in parser.fields if not (f.kind == "radio" and not f.options)]
    for i, f in enumerate(fields):
        f.index = i
    return fields


# --------------------------------------------------------------------------- #
# answers resolved from the profile / application pack
# --------------------------------------------------------------------------- #
@dataclass
class ProfileAnswers:
    """Canonical key → value, with provenance.  Values are plain strings."""
    answers: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    question_overrides: dict[str, str] = field(default_factory=dict)  # norm(label) → value
    suggestions: dict[str, str] = field(default_factory=dict)         # review hints

    def get(self, key: str) -> str | None:
        return self.answers.get(key)

    @classmethod
    def from_profile(cls, profile, application=None, overrides: dict | None = None,
                     today: date | None = None) -> "ProfileAnswers":
        """Build the answer table.  Never invents: missing data stays missing
        (the plan flags those fields for the human)."""
        today = today or date.today()
        out = cls()

        def set_answer(key: str, value, source: str) -> None:
            if value is None:
                return
            text = str(value).strip()
            if text:
                out.answers[key] = text
                out.sources[key] = source

        # identity
        set_answer("full_name", profile.full_name, "profile")
        parts = (profile.full_name or "").split()
        if parts:
            set_answer("first_name", parts[0], "profile")
        if len(parts) > 1:
            set_answer("last_name", " ".join(parts[1:]), "profile")
        set_answer("email", profile.email, "profile")
        set_answer("phone", profile.phone, "profile")
        set_answer("location", profile.location, "profile")
        set_answer("headline", profile.headline, "profile")
        set_answer("current_title", profile.experience[0].title if profile.experience else None,
                   "profile")
        set_answer("current_company",
                   profile.experience[0].company if profile.experience else None, "profile")
        set_answer("skills", ", ".join(profile.skills) if profile.skills else None, "profile")
        set_answer("languages", profile.languages, "profile")
        set_answer("education",
                   _format_education(profile.education[0]) if profile.education else None,
                   "profile")

        # links string: "LinkedIn: … | GitHub: …"
        # links string: "LinkedIn: … | GitHub: …" — split on separators only,
        # never on the slashes inside the URLs themselves
        for segment in re.split(r"[|;\n]", profile.links or ""):
            if ":" not in segment:
                continue
            site, url = segment.split(":", 1)
            key = {"linkedin": "linkedin_url", "github": "github_url",
                   "portfolio": "portfolio_url", "website": "website",
                   "blog": "portfolio_url"}.get(_norm(site))
            if key:
                set_answer(key, _ensure_url(url.strip()), "profile")

        # derived
        set_answer("years_experience", _years_of_experience(profile.experience, today),
                   "derived")
        if profile.salary_floor:
            set_answer("salary_expectation", f"{profile.salary_floor:,} {profile.currency}",
                       "derived")

        # booleans — only when the profile states them positively; a silent
        # default of False is not an answer we are willing to type for you.
        if profile.willing_to_relocate:
            set_answer("willing_to_relocate", "Yes", "profile")
        if profile.remote_only:
            set_answer("remote_ok", "Yes", "profile")

        # application pack artefacts
        if application is not None:
            for key, path in (("resume_file", application.cv_path),
                              ("cover_letter_file", application.cover_letter_path)):
                if path:
                    out.answers[key] = path          # existence checked at plan time
                    out.sources[key] = "application"
            email_text = _read_text(application.email_path)
            if email_text:
                out.suggestions["cover_letter_text"] = email_text
                out.suggestions["why_company"] = email_text

        # overrides (profile.json → extra.autofill) — canonical keys win,
        # anything else becomes a question-text match
        for raw_key, value in (overrides or {}).items():
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            key = _norm(raw_key).replace(" ", "_")
            if key in FIELD_SPECS:
                out.answers[key] = text
                out.sources[key] = "override"
            else:
                out.question_overrides[_norm(str(raw_key))] = text
        return out


def _format_education(entry) -> str:
    parts = [p for p in (entry.degree, entry.school) if p]
    return " — ".join(parts) if parts else ""


def _ensure_url(url: str) -> str:
    url = url.strip()
    if url and "://" not in url:
        return f"https://{url}"
    return url


def _read_text(path: str | None) -> str:
    if not path:
        return ""
    try:
        target = Path(path)
        if target.exists() and target.suffix.lower() in (".txt", ".md", ""):
            return target.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        pass
    return ""


def _years_of_experience(experience, today: date) -> int | None:
    """Approximate total years across experience entries (whole years)."""
    total_days = 0
    for entry in experience:
        start = _parse_year_month(entry.start)
        end = _parse_year_month(entry.end) or (today.year, today.month)
        if not start:
            continue
        s = date(*start, 1) if start[1] else date(start[0], 1, 1)
        e = date(*end, 1) if end[1] else date(end[0], 12, 31)
        if e > s:
            total_days += (e - s).days
    if total_days <= 0:
        return None
    return int(total_days // 365.25)


def _parse_year_month(text: str):
    match = re.search(r"(\d{4})(?:[-/.](\d{1,2}))?", text or "")
    if not match:
        return None
    year, month = int(match.group(1)), match.group(2)
    month_int = max(1, min(12, int(month))) if month else None
    return (year, month_int) if year > 1900 else None


# --------------------------------------------------------------------------- #
# field matching (taxonomy lookup with confidence)
# --------------------------------------------------------------------------- #
@dataclass
class FieldMatch:
    canonical: str = ""
    score: float = 0.0
    runner_up: str = ""
    runner_up_score: float = 0.0
    reason: str = ""


def match_field(field: FormField) -> FieldMatch:
    """Score every compatible canonical key against the field's signals."""
    scores: dict[str, float] = {}
    reasons: dict[str, str] = {}

    for spec in FIELD_SPECS.values():
        if field.kind not in spec.kinds:
            continue
        best = 0.0
        reason = ""
        if field.autocomplete:
            key = _AUTOCOMPLETE_MAP.get(field.autocomplete.strip().lower())
            if key == spec.key:
                best, reason = max(best, 0.6), f"autocomplete={field.autocomplete}"
        for source, text, weight in field.signals:
            normalized = _norm(text)
            if not normalized:
                continue
            if any(_has_token(normalized, token) for token in spec.strong):
                if weight > best:
                    best, reason = weight, f"{source} “{text.strip()}”"
            elif any(_has_token(normalized, token) for token in spec.weak):
                if weight * 0.5 > best:
                    best, reason = weight * 0.5, f"{source} “{text.strip()}” (weak)"
        if field.kind in _TYPE_BOOST_MAP and _TYPE_BOOST_MAP[field.kind] == spec.key:
            if 0.4 > best:
                best, reason = max(best, 0.4), f"type={field.kind}"
        if field.kind == "file" and spec.key in _FILE_KEYS:
            if 0.3 > best:
                best = 0.3
                reason = "file input (unlabelled)"
        if best > 0:
            scores[spec.key] = min(best, 0.95)
            reasons[spec.key] = reason

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked:
        return FieldMatch(reason="no taxonomy match")
    (top_key, top_score), rest = ranked[0], ranked[1:]
    return FieldMatch(canonical=top_key, score=top_score,
                      runner_up=rest[0][0] if rest else "",
                      runner_up_score=rest[0][1] if rest else 0.0,
                      reason=reasons[top_key])


# --------------------------------------------------------------------------- #
# fill plan
# --------------------------------------------------------------------------- #
_FILL, _REVIEW, _SKIP = "fill", "review", "skip"
# confident matches need this much signal and this much distance to the runner-up
_CONFIDENT_SCORE = 0.5
_CONFIDENT_GAP = 0.15
# a bare “Name”-style weak match is promoted to full_name when no first/last
# fields exist anywhere in the form
_AMBIGUOUS_GAP = 0.12


@dataclass
class FillAction:
    index: int
    anchor: dict                 # {"tag","kind","name","id","index"} browser locator
    label: str
    canonical: str
    value: str = ""
    status: str = _SKIP          # fill | review | skip
    confidence: float = 0.0
    reason: str = ""
    suggestion: str = ""         # e.g. the generated e-mail draft, for pasting

    def to_dict(self) -> dict:
        return {"index": self.index, "label": self.label, "canonical": self.canonical,
                "value": self.value, "status": self.status,
                "confidence": round(self.confidence, 2), "reason": self.reason,
                "anchor": self.anchor}


@dataclass
class FillPlan:
    actions: list[FillAction] = field(default_factory=list)

    @property
    def filled(self) -> list[FillAction]:
        return [a for a in self.actions if a.status == _FILL]

    @property
    def to_review(self) -> list[FillAction]:
        return [a for a in self.actions if a.status == _REVIEW]

    @property
    def skipped(self) -> list[FillAction]:
        return [a for a in self.actions if a.status == _SKIP]

    def to_dict(self) -> dict:
        return {"summary": {"fill": len(self.filled), "review": len(self.to_review),
                            "skip": len(self.skipped)},
                "actions": [a.to_dict() for a in self.actions]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)

    def to_text(self) -> str:
        lines = []
        for action in self.actions:
            value = action.value
            if len(value) > 48:
                value = value[:45] + "…"
            lines.append(f"{action.status.upper():<6} "
                         f"{action.label[:34]:<34} "
                         f"{('<' + action.canonical + '>') if action.canonical else '—':<22} "
                         f"{value}")
            if action.reason:
                lines.append(f"       ↳ {action.reason}")
            if action.suggestion:
                hint = action.suggestion.replace("\n", " ¶ ")
                if len(hint) > 100:
                    hint = hint[:97] + "…"
                lines.append(f"       ✎ suggestion: {hint}")
        summary = (f"\n{len(self.filled)} to fill · {len(self.to_review)} need your "
                   f"input · {len(self.skipped)} left alone (nothing is ever submitted "
                   f"for you)")
        return "\n".join(lines) + summary


def _anchor(field: FormField) -> dict:
    return {"tag": field.tag, "kind": field.kind, "name": field.name,
            "id": field.id, "index": field.index}


def _question_override(field: FormField, answers: ProfileAnswers) -> str | None:
    normalized_label = _norm(field.label)
    for question, value in sorted(answers.question_overrides.items()):
        if question and (_contains(normalized_label, question) or _contains(question, normalized_label)):
            return value
    return None


def _coerce(field: FormField, value: str) -> tuple[str, str]:
    """Adapt an answer to the control kind.  Returns (value, note)."""
    if field.kind == "number":
        digits = re.sub(r"[^0-9.]", "", value)
        return digits, "numeric field — sent digits only"
    if field.kind == "date":
        match = re.search(r"(\d{4}-\d{2}-\d{2})", value)
        if match:
            return match.group(1), "date field — ISO format"
        return value, "date field — value not in YYYY-MM-DD form"
    return value, ""


def _pick_option(field: FormField, value: str) -> SelectOption | None:
    """Choose the option that best matches the answer (yes/no, contains)."""
    wanted = _norm(value)
    for option in field.options:
        if _norm(option.label) == wanted or _norm(option.value) == wanted:
            return option
    for option in field.options:
        if wanted and (_contains(_norm(option.label), wanted)
                       or _contains(_norm(option.value), wanted)):
            return option
    # yes/no fallback: boolean answers map onto the first yes-ish/no-ish option
    positive = wanted in ("yes", "true", "y")
    negative = wanted in ("no", "false", "n")
    if positive or negative:
        for option in field.options:
            label = _norm(option.label) or _norm(option.value)
            if positive and label.startswith("yes"):
                return option
            if negative and label.startswith("no"):
                return option
    return None


def build_plan(fields: list[FormField], answers: ProfileAnswers) -> FillPlan:
    """Deterministic plan: fill what the taxonomy resolved, flag the rest."""
    matches = [match_field(f) for f in fields]
    _promote_lone_full_name(fields, matches)

    plan = FillPlan()
    for form_field, match in zip(fields, matches):
        action = FillAction(index=form_field.index, anchor=_anchor(form_field),
                            label=form_field.display_name, canonical=match.canonical,
                            confidence=match.score)

        if form_field.kind == "password":
            action.status, action.reason = _SKIP, "password fields are never autofilled"
        elif not match.canonical:
            override = _question_override(form_field, answers)
            if override is not None:
                action.canonical, action.value = "(override)", override
                action.status, action.reason = _FILL, "matched a question override"
            else:
                action.status, action.reason = _SKIP, "not an application question"
        elif match.score < _CONFIDENT_SCORE:
            action.status = _REVIEW
            action.reason = (f"low confidence — maybe {match.canonical} "
                             f"({match.reason}); check before letting it type")
        elif (match.score - match.runner_up_score) < _AMBIGUOUS_GAP:
            action.status = _REVIEW
            action.reason = (f"ambiguous — best guess {match.canonical} "
                             f"({match.reason}), close runner-up {match.runner_up or 'none'}")
        else:
            value = answers.get(match.canonical) or _question_override(form_field, answers)
            if value is None:
                action.status = _REVIEW
                action.reason = f"no answer for “{match.canonical}” in your profile"
                action.suggestion = answers.suggestions.get(match.canonical, "")
            elif form_field.options:
                option = _pick_option(form_field, value)
                if option is None:
                    action.status, action.reason = _REVIEW, \
                        f"answer “{value}” matches none of the {len(form_field.options)} options"
                else:
                    action.value = option.value or option.label
                    action.status, action.reason = _FILL, \
                        f"{match.reason} → option “{option.label or option.value}”"
            elif form_field.kind == "file":
                if Path(value).exists():
                    action.value, action.status = value, _FILL
                    action.reason = f"{match.reason} → {Path(value).name}"
                else:
                    action.status, action.reason = _REVIEW, \
                        f"file from application pack not found: {value}"
            else:
                coerced, note = _coerce(form_field, value)
                action.value, action.status = coerced, _FILL
                action.reason = " → ".join(p for p in (match.reason, note) if p)
        plan.actions.append(action)
    return plan


def _promote_lone_full_name(fields: list[FormField], matches: list[FieldMatch]) -> None:
    """A single weak “Name”-style text field (no first/last fields anywhere)
    is almost certainly the full name — promote it to a confident match."""
    has_name_parts = any(m.canonical in ("first_name", "last_name") for m in matches)
    if has_name_parts:
        return
    candidates = [i for i, (f, m) in enumerate(zip(fields, matches))
                  if m.canonical == "full_name" and m.score < _CONFIDENT_SCORE
                  and f.kind in ("text", "search")]
    if len(candidates) == 1:
        i = candidates[0]
        matches[i] = FieldMatch(canonical="full_name", score=_CONFIDENT_SCORE,
                                runner_up=matches[i].runner_up,
                                runner_up_score=matches[i].runner_up_score - 0.01,
                                reason="only name field in the form")


def plan_for_html(html: str, profile, application=None, overrides: dict | None = None,
                  today: date | None = None) -> FillPlan:
    """Convenience: parse + resolve + plan in one call."""
    fields = parse_html(html)
    answers = ProfileAnswers.from_profile(profile, application=application,
                                          overrides=overrides, today=today)
    return build_plan(fields, answers)
