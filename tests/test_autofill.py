"""Autofill engine: parsing, taxonomy matching, answer resolution, fill plans.

The ATS fixtures under ``tests/fixtures/forms/`` are realistic, trimmed-down
captures of public application-form shapes (Greenhouse / Lever / Workday /
generic HTML5).  They keep this whole suite offline — the browser hand-off in
``jautomatic/services/autofill_browser.py`` is deliberately the only untested
seam.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from jautomatic.models import SAMPLE_PROFILE, Application
from jautomatic.services.autofill import (
    FormField, ProfileAnswers, match_field, parse_html, plan_for_html,
    _norm, _has_token,
)

FIXTURES = Path(__file__).parent / "fixtures" / "forms"


def sample_profile():
    from jautomatic.models import Profile
    return Profile.from_dict(SAMPLE_PROFILE)


def form(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


def sample_answers(**overrides):
    return ProfileAnswers.from_profile(sample_profile(), overrides=overrides or None)


def field(**overrides) -> FormField:
    base = dict(index=0, tag="input", kind="text")
    base.update(overrides)
    return FormField(**base)


def with_application(cv_name="cv.docx", email_text="Dear Hiring Team, hire me."):
    """An Application whose generated pack actually exists on disk."""
    tmp = tempfile.mkdtemp()
    cv = Path(tmp) / cv_name
    cv.write_bytes(b"PK\x03\x04 fake docx")
    email = Path(tmp) / "email.txt"
    email.write_text(email_text, encoding="utf-8")
    return Application(cv_path=str(cv), email_path=str(email))


class NormalizationTests(unittest.TestCase):
    def test_accents_and_punctuation_fold_away(self):
        self.assertEqual(_norm("Résumé/CV"), "resume cv")
        self.assertEqual(_norm("E-mail"), "e mail")
        self.assertEqual(_norm("  First   Name  "), "first name")

    def test_tokens_match_on_word_boundaries(self):
        self.assertTrue(_has_token("candidate first name", "first name"))
        self.assertFalse(_has_token("username", "name"), "‘name’ must not match ‘username’")
        self.assertFalse(_has_token("links", "link"))
        self.assertFalse(_has_token("emailing someone", "email"))


class MatchingTests(unittest.TestCase):
    def test_first_and_last_name_are_not_ambiguous(self):
        # regression: a bare “Name” used to be a *strong* full_name token, which
        # made “First Name” / “Last Name” fields ambiguous
        self.assertEqual(match_field(field(label="First Name")).canonical, "first_name")
        self.assertEqual(match_field(field(label="Last Name")).canonical, "last_name")
        self.assertGreaterEqual(match_field(field(label="Last Name")).score, 0.5)

    def test_name_only_signal_matches_first_name(self):
        greenhouse = field(name="candidate[first_name]")
        self.assertEqual(match_field(greenhouse).canonical, "first_name")

    def test_company_name_is_company_not_full_name(self):
        match = match_field(field(label="Company name"))
        self.assertEqual(match.canonical, "current_company")

    def test_autocomplete_and_type_signals(self):
        self.assertEqual(match_field(field(kind="email", autocomplete="email")).canonical,
                         "email")
        self.assertEqual(match_field(field(kind="tel", name="contact-phone")).canonical,
                         "phone")
        self.assertEqual(match_field(field(kind="email", name="contact")).canonical,
                         "email", "type=email alone should still match")

    def test_placeholder_matches_link_fields(self):
        match = match_field(field(kind="url", placeholder="LinkedIn"))
        self.assertEqual(match.canonical, "linkedin_url")
        self.assertGreaterEqual(match.score, 0.5)

    def test_accented_resume_label(self):
        match = match_field(field(kind="file", label="Résumé File"))
        self.assertEqual(match.canonical, "resume_file")

    def test_boolean_keys_only_match_choice_controls(self):
        text = field(label="Are you legally authorized to work in Germany?")
        self.assertEqual(match_field(text).canonical, "work_authorization")
        plain = field(label="Authorization letter")
        self.assertNotEqual(match_field(plain).canonical, "work_authorization")


class ParserTests(unittest.TestCase):
    def test_greenhouse_shape(self):
        fields = parse_html(form("greenhouse"))
        self.assertEqual(len(fields), 11)
        by_name = {f.name: f for f in fields}
        self.assertEqual(by_name["candidate[first_name]"].label, "First Name")
        self.assertEqual(by_name["candidate[first_name]"].label_source, "for")
        self.assertTrue(by_name["candidate[first_name]"].required)

        select = by_name["question[1900011]"]
        self.assertEqual(select.kind, "select")
        self.assertEqual([o.value for o in select.options],
                         ["", "linkedin", "company_website", "referral", "job_board"])
        self.assertEqual(select.options[1].label, "LinkedIn")

        radios = by_name["question[1900013]"]
        self.assertEqual(radios.kind, "radio")
        self.assertEqual([o.value for o in radios.options], ["yes", "no"])
        self.assertEqual(radios.label,
                         "Are you legally authorized to work in the United States?")
        self.assertEqual([o.label for o in radios.options], ["Yes", "No"])

        resume = by_name["file"]
        self.assertEqual((resume.kind, resume.label), ("file", "Resume/CV"))
        # submit buttons / hidden inputs are never parsed as fillable controls
        self.assertNotIn("commit", by_name)

    def test_lever_shape(self):
        fields = parse_html(form("lever"))
        by_name = {f.name: f for f in fields}
        self.assertEqual(by_name["name"].label, "Name")
        self.assertEqual(by_name["name"].label_source, "wrap")
        # regression: a consumed wrapped label must not leak onto the next field
        url_inputs = [f for f in fields if f.name == "urls[]"]
        self.assertEqual(len(url_inputs), 4)
        self.assertNotIn("Organization", url_inputs[0].label)
        self.assertEqual([f.placeholder for f in url_inputs],
                         ["LinkedIn", "GitHub", "Portfolio", "Other"])
        # wrapped labels with the text *after* the input are back-patched on close
        self.assertIn("Additional information", by_name["cards[additional]"].label)

    def test_workday_shape(self):
        fields = parse_html(form("workday"))
        by_id = {f.id: f for f in fields}
        self.assertEqual(by_id["wd-input-4"].kind, "tel")
        self.assertEqual(by_id["wd-file-1"].label, "Résumé File")
        self.assertEqual(by_id["wd-date-1"].kind, "date")
        country = by_id["wd-select-1"]
        self.assertEqual(country.kind, "select")
        self.assertEqual(len(country.options), 5)

    def test_generic_shape(self):
        fields = parse_html(form("generic"))
        by_name = {f.name: f for f in fields}
        self.assertEqual(by_name["applicant_name"].autocomplete, "name")
        self.assertEqual(by_name["password"].kind, "password")
        radios = by_name["relocate"]
        self.assertEqual(radios.kind, "radio")
        self.assertEqual(radios.label, "Are you willing to relocate for this role?")
        self.assertEqual([o.label for o in radios.options], ["Yes", "No"])

    def test_submit_and_hidden_never_parsed(self):
        for name in ("greenhouse", "lever", "workday", "generic"):
            for f in parse_html(form(name)):
                self.assertNotIn(f.kind, ("submit", "button", "hidden", "image", "reset"),
                                 f"{name}: {f.name or f.id} parsed as a control")


class AnswerTests(unittest.TestCase):
    def test_identity_and_links(self):
        answers = sample_answers()
        self.assertEqual(answers.get("first_name"), "Alex")
        self.assertEqual(answers.get("last_name"), "Doe")
        self.assertEqual(answers.get("email"), "alex.doe@example.com")
        # URLs keep their path (regression: they were split on “/” once)
        self.assertEqual(answers.get("linkedin_url"), "https://linkedin.com/in/alexdoe")
        self.assertEqual(answers.get("github_url"), "https://github.com/alexdoe")

    def test_years_of_experience_is_deterministic_per_date(self):
        answers = ProfileAnswers.from_profile(sample_profile(),
                                              today=date(2026, 9, 15))
        self.assertEqual(answers.get("years_experience"), "8")
        again = ProfileAnswers.from_profile(sample_profile(),
                                            today=date(2026, 9, 15))
        self.assertEqual(again.get("years_experience"), "8")

    def test_salary_uses_profile_floor(self):
        self.assertEqual(sample_answers().get("salary_expectation"), "80,000 USD")

    def test_negative_booleans_are_not_answered(self):
        # a silent False default is not something we type on your behalf
        self.assertIsNone(sample_answers().get("willing_to_relocate"))
        self.assertIsNone(sample_answers().get("requires_sponsorship"))

    def test_overrides_canonical_and_question_text(self):
        answers = sample_answers(**{"work authorization": "Yes",
                                    "how did you hear": "LinkedIn"})
        self.assertEqual(answers.get("work_authorization"), "Yes")
        self.assertEqual(answers.get("how_did_you_hear"), "LinkedIn")

    def test_application_pack_provides_files_and_suggestion(self):
        application = with_application()
        answers = ProfileAnswers.from_profile(sample_profile(), application=application)
        self.assertTrue(Path(answers.get("resume_file")).exists())
        self.assertIn("hire me", answers.suggestions["why_company"])


class PlanTests(unittest.TestCase):
    def test_greenhouse_plan(self):
        plan = plan_for_html(form("greenhouse"), sample_profile(),
                             overrides={"work authorization": "Yes",
                                        "how did you hear": "LinkedIn"})
        values = {a.canonical: a.value for a in plan.filled}
        self.assertEqual(values["first_name"], "Alex")
        self.assertEqual(values["last_name"], "Doe")
        self.assertEqual(values["email"], "alex.doe@example.com")
        self.assertEqual(values["how_did_you_hear"], "linkedin")   # option value
        self.assertEqual(values["work_authorization"], "yes")      # option value
        self.assertEqual(values["years_experience"], "8")
        # EEO questions are none of our business — left alone
        self.assertTrue(all("voluntary" not in a.label for a in plan.filled))

    def test_resume_fills_only_when_pack_file_exists(self):
        plan = plan_for_html(form("greenhouse"), sample_profile())
        resume = [a for a in plan.to_review if a.canonical == "resume_file"]
        self.assertEqual(len(resume), 1)

        application = with_application()
        plan = plan_for_html(form("greenhouse"), sample_profile(),
                             application=application)
        resume = [a for a in plan.filled if a.canonical == "resume_file"]
        self.assertEqual(len(resume), 1)
        self.assertTrue(Path(resume[0].value).exists())

    def test_question_text_override_fills_unmatched_select(self):
        plan = plan_for_html(form("greenhouse"), sample_profile(),
                             overrides={"how did you hear about this job": "A friend"})
        heard = [a for a in plan.actions if "hear" in a.label.lower()][0]
        self.assertEqual((heard.status, heard.value), ("fill", "referral"))

    def test_number_and_date_coercion(self):
        plan = plan_for_html(form("workday"), sample_profile(),
                             overrides={"work authorization": "Yes"})
        values = {a.canonical: a.value for a in plan.filled}
        self.assertEqual(values["salary_expectation"], "80000")   # digits only
        # the Lever salary field is plain text and keeps the formatted value
        lever = plan_for_html(form("lever"), sample_profile())
        lever_values = {a.canonical: a.value for a in lever.filled}
        self.assertEqual(lever_values["salary_expectation"], "80,000 USD")

    def test_lone_name_field_is_promoted_to_full_name(self):
        plan = plan_for_html(form("lever"), sample_profile())
        filled = {a.canonical: a.value for a in plan.filled}
        self.assertEqual(filled.get("full_name"), "Alex Doe")

    def test_password_is_never_filled(self):
        for name in ("greenhouse", "lever", "workday", "generic"):
            plan = plan_for_html(form(name), sample_profile())
            for action in plan.actions:
                self.assertNotIn("password", (action.canonical or "").lower())
                self.assertNotIn("password", action.value.lower() if action.value else "")
        generic = plan_for_html(form("generic"), sample_profile())
        passwords = [a for a in generic.actions if "password" in a.label.lower()]
        self.assertEqual([a.status for a in passwords], ["skip"])

    def test_plan_is_deterministic(self):
        first = plan_for_html(form("greenhouse"), sample_profile(),
                              overrides={"work authorization": "Yes"})
        second = plan_for_html(form("greenhouse"), sample_profile(),
                               overrides={"work authorization": "Yes"})
        self.assertEqual(first.to_json(), second.to_json())

    def test_empty_profile_produces_no_fills_and_no_crash(self):
        from jautomatic.models import Profile
        for name in ("greenhouse", "lever", "workday", "generic"):
            plan = plan_for_html(form(name), Profile())
            self.assertEqual(plan.filled, [], name)
            self.assertTrue(plan.actions, name)

    def test_every_action_is_fill_review_or_skip(self):
        # the planner structurally cannot produce a submit: every action is one
        # of the three states, and only *fill* actions ever carry a value
        for name in ("greenhouse", "lever", "workday", "generic"):
            plan = plan_for_html(form(name), sample_profile())
            for action in plan.actions:
                self.assertIn(action.status, ("fill", "review", "skip"))
                if action.status != "fill":
                    self.assertEqual(action.value, "")


if __name__ == "__main__":
    unittest.main()
