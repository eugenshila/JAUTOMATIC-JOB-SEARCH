"""Additional CV templates, the mini template language and user-supplied templates."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jautomatic.models import SAMPLE_PROFILE, Profile
from jautomatic.services import template_engine
from jautomatic.services.application_pipeline import match_job
from jautomatic.services.cv_generator import (CUSTOM_PREFIX, STARTER_TEMPLATE, TEMPLATE_LABELS,
                                              TEMPLATES, CVGenerator, TemplateRegistry,
                                              document_suffix, markdown_to_html, render_markdown,
                                              template_context, template_label)
from tests.test_documents import job, profile


class NewBuiltinTemplateTests(unittest.TestCase):
    def test_templates_are_registered_with_labels(self):
        self.assertEqual(TEMPLATES, ("modern", "classic", "compact", "functional", "executive",
                                     "technical", "portfolio"))
        for name in TEMPLATES:
            self.assertIn(name, TEMPLATE_LABELS)
            self.assertTrue(render_markdown(profile(), job(), name).strip(), name)

    def test_functional_groups_evidence_by_posting_tag(self):
        text = render_markdown(profile(), job(), "functional", match_job(profile(), job()))
        self.assertIn("## Areas of expertise", text)
        self.assertIn("### Python", text)                     # posting tag -> heading
        self.assertIn("## Career history", text)              # timeline kept, but short
        self.assertNotIn("### Senior Backend Engineer", text)  # no per-role sections

    def test_executive_leads_with_quantified_achievements(self):
        text = render_markdown(profile(), job(), "executive")
        head, _, _ = text.partition("## Leadership experience")
        self.assertIn("## Selected achievements", head)
        self.assertIn("62%", head)          # numbers float to the top
        self.assertIn("40M", head)

    def test_technical_splits_relevant_and_other_skills_and_lists_stack(self):
        text = render_markdown(profile(), job(), "technical", match_job(profile(), job()))
        self.assertIn("**Relevant to this role:** python, fastapi, postgresql, aws", text)
        self.assertIn("**Also:**", text)
        self.assertIn("**Stack:** python, fastapi, postgresql", text)

    def test_technical_without_job_lists_plain_skills(self):
        text = render_markdown(profile(), None, "technical")
        self.assertIn("## Technical skills", text)
        self.assertNotIn("Relevant to this role", text)
        self.assertNotIn("Prepared for", text)

    def test_templates_cope_with_an_empty_profile(self):
        for name in TEMPLATES:
            text = render_markdown(Profile(), None, name)
            self.assertIn("unnamed candidate", text.lower(), name)


class TemplateEngineTests(unittest.TestCase):
    def test_placeholders_dotted_lookups_and_missing_values(self):
        out = template_engine.render("{{ name }} / {{ job.title }} / {{ nope }} / {{ list.1 }}",
                                     {"name": "A", "job": {"title": "T"}, "list": ["x", "y"]})
        self.assertEqual(out, "A / T /  / y\n")

    def test_for_if_else_and_loop_variables(self):
        source = ("{% for item in items %}{{ loop.index }}:{{ item }}"
                  "{% if loop.last %}.{% else %},{% endif %}{% endfor %}")
        self.assertEqual(template_engine.render(source, {"items": ["a", "b"]}), "1:a,2:b.\n")

    def test_if_not_and_truthiness(self):
        source = "{% if not job %}generic{% endif %}{% if skills %}S{% endif %}"
        self.assertEqual(template_engine.render(source, {"job": None, "skills": []}), "generic\n")
        self.assertEqual(template_engine.render(source, {"job": {"t": 1}, "skills": ["x"]}), "S\n")

    def test_block_tags_on_their_own_line_leave_no_blank_lines(self):
        source = "# H\n{% for b in bullets %}\n- {{ b }}\n{% endfor %}\nEnd\n"
        self.assertEqual(template_engine.render(source, {"bullets": ["one", "two"]}),
                         "# H\n- one\n- two\nEnd\n")

    def test_indented_block_tags_are_stripped_too(self):
        source = "{% for b in bullets %}\n    {% if b %}\n- {{ b }}\n    {% endif %}\n{% endfor %}"
        self.assertEqual(template_engine.render(source, {"bullets": ["x"]}), "- x\n")

    def test_comments_vanish(self):
        self.assertEqual(template_engine.render("a{# gone #}b", {}), "ab\n")

    def test_lists_render_comma_joined(self):
        self.assertEqual(template_engine.render("{{ skills }}", {"skills": ["a", "b"]}), "a, b\n")

    def test_structural_errors_are_reported_with_line_numbers(self):
        cases = {
            "x\n{% for a in b %}": "line 2: {% for %} is never closed",
            "{% endif %}": "without a matching {% if %}",
            "{% if a %}\n{% endfor %}": "line 2: {% endfor %} closes a {% if %} opened on line 1",
            "{% frobnicate %}": "unknown tag",
            "{{ a|upper }}": "bad placeholder",
            "{% if a %}{% else %}{% else %}{% endif %}": "second {% else %}",
            "{% for x %}": "bad loop",
        }
        for source, fragment in cases.items():
            error = template_engine.validate(source)
            self.assertIsNotNone(error, source)
            self.assertIn(fragment, error, source)
        self.assertIsNone(template_engine.validate("{% if a %}{% for b in c %}{% endfor %}{% endif %}"))

    def test_lookup_never_calls_or_exposes_private_attributes(self):
        class Thing:
            public = "ok"
            _secret = "no"

            def method(self):
                return "called"

        self.assertEqual(template_engine.lookup({"t": Thing()}, "t.public"), "ok")
        self.assertIsNone(template_engine.lookup({"t": Thing()}, "t._secret"))
        self.assertIsNone(template_engine.lookup({"t": Thing()}, "t.method"))
        self.assertIsNone(template_engine.lookup({"t": Thing()}, "t.__class__"))


class TemplateContextTests(unittest.TestCase):
    def test_context_exposes_documented_variables(self):
        context = template_context(profile(), job(), match_job(profile(), job()))
        for key in ("name", "headline", "contact", "summary", "tailored_summary", "skills",
                    "skills_line", "languages", "experience", "education", "highlights",
                    "today", "job", "match"):
            self.assertIn(key, context)
        self.assertEqual(context["job"]["company"], "Northwind Analytics")
        self.assertGreater(context["match"]["score"], 0)
        role = context["experience"][0]
        for key in ("title", "company", "period", "bullets", "stack"):
            self.assertIn(key, role)
        self.assertIn("python", role["stack"])

    def test_context_without_job_has_none_for_job_and_match(self):
        context = template_context(profile(), None)
        self.assertIsNone(context["job"])
        self.assertIsNone(context["match"])
        self.assertEqual(context["tailored_summary"], profile().summary)

    def test_starter_template_renders_cleanly_with_and_without_job(self):
        self.assertIsNone(template_engine.validate(STARTER_TEMPLATE))
        with_job = template_engine.render(STARTER_TEMPLATE, template_context(profile(), job()))
        self.assertIn("# Alex Doe", with_job)
        self.assertIn("- Owned the ingestion platform", with_job)
        self.assertIn("Tailored for **Senior Python Engineer**", with_job)
        self.assertNotIn("\n\n\n", with_job)
        without = template_engine.render(STARTER_TEMPLATE, template_context(profile(), None))
        self.assertNotIn("Tailored for", without)


class CustomTemplateRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="jautomatic-templates-")
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.registry = TemplateRegistry(self.dir)

    def test_lists_only_template_files_and_flags_broken_ones(self):
        (self.dir / "good.md").write_text("# {{ name }}", "utf-8")
        (self.dir / "bad.md").write_text("{% for x in y %}", "utf-8")
        (self.dir / "notes.pdf").write_bytes(b"%PDF")
        (self.dir / ".hidden.md").write_text("x", "utf-8")
        found = {t.name: t for t in self.registry.list()}
        self.assertEqual(set(found), {"custom:good.md", "custom:bad.md"})
        self.assertTrue(found["custom:good.md"].ok)
        self.assertFalse(found["custom:bad.md"].ok)
        self.assertIn("never closed", found["custom:bad.md"].error)
        self.assertEqual(self.registry.names(), ["custom:good.md"])

    def test_labels(self):
        self.assertEqual(template_label("custom:my-cv_v2.md"), "My cv v2 (custom)")
        self.assertEqual(template_label("classic"), TEMPLATE_LABELS["classic"])

    def test_path_traversal_is_refused(self):
        self.assertIsNone(self.registry.path_for("custom:../../etc/passwd"))
        self.assertIsNone(self.registry.path_for("custom:..\\x.md"))
        self.assertIsNone(self.registry.path_for("custom:.hidden.md"))
        self.assertIsNone(self.registry.path_for("modern"))
        self.assertFalse(self.registry.exists("custom:../x.md"))

    def test_create_starter_never_overwrites(self):
        first = self.registry.create_starter("mine.md")
        second = self.registry.create_starter("mine.md")
        self.assertEqual(first.name, "mine.md")
        self.assertEqual(second.name, "mine-2.md")
        self.assertEqual(first.read_text("utf-8"), STARTER_TEMPLATE)
        self.assertEqual(self.registry.create_starter("weird").suffix, ".md")

    def test_generator_renders_custom_template_and_reports_it(self):
        (self.dir / "mine.md").write_text("# CUSTOM {{ name }} for {{ job.company }}", "utf-8")
        generator = CVGenerator(self.dir)
        names = [name for name, _ in generator.available_templates()]
        self.assertEqual(names[:len(TEMPLATES)], list(TEMPLATES))
        self.assertIn("custom:mine.md", names)
        document = generator.generate(profile(), job(), "custom:mine.md")
        self.assertEqual(document.text.strip(), "# CUSTOM Alex Doe for Northwind Analytics")
        self.assertEqual(document.template, "custom:mine.md")
        self.assertEqual(document.warning, "")

    def test_missing_or_broken_custom_template_falls_back_to_modern_with_warning(self):
        generator = CVGenerator(self.dir)
        missing = generator.generate(profile(), job(), "custom:nope.md")
        self.assertEqual(missing.template, "modern")
        self.assertIn("was not found", missing.warning)
        self.assertEqual(missing.text, render_markdown(profile(), job(), "modern"))

        (self.dir / "bad.md").write_text("{% endif %}", "utf-8")
        broken = generator.generate(profile(), job(), "custom:bad.md")
        self.assertEqual(broken.template, "modern")
        self.assertIn("has an error", broken.warning)

    def test_generator_without_directory_only_offers_builtins(self):
        generator = CVGenerator()
        self.assertEqual([n for n, _ in generator.available_templates()], list(TEMPLATES))
        self.assertEqual(generator.generate(profile(), job(), CUSTOM_PREFIX + "x.md").template,
                         "modern")

    def test_custom_template_exports_to_every_format(self):
        (self.dir / "mine.md").write_text("# {{ name }}\n- {{ headline }}", "utf-8")
        generator = CVGenerator(self.dir)
        for fmt, suffix in (("docx", ".docx"), ("md", ".md"), ("txt", ".txt"), ("pdf", ".pdf")):
            with tempfile.TemporaryDirectory() as out:
                document = generator.generate(profile(), job(), "custom:mine.md", Path(out), fmt)
                self.assertEqual(document.path.suffix, suffix)
                self.assertGreater(document.path.stat().st_size, 20)

    def test_document_suffix_handles_pdf(self):
        self.assertEqual(document_suffix("pdf"), ".pdf")
        self.assertEqual(document_suffix("PDF"), ".pdf")
        self.assertEqual(document_suffix(""), ".docx")

    def test_markdown_to_html_marks_headings_bullets_and_inline(self):
        body = markdown_to_html("# Lead\n\n- one **bold**\n- two\n\n---\n\nplain *text*")
        self.assertIn("<h1>Lead</h1>", body)
        self.assertIn("<ul><li>one <b>bold</b></li><li>two</li></ul>", body)
        self.assertIn("<hr/>", body)
        self.assertIn("plain <i>text</i>", body)


class SampleProfileTemplateSmokeTest(unittest.TestCase):
    def test_all_templates_mention_every_employer(self):
        sample = Profile.from_dict(SAMPLE_PROFILE)
        for name in TEMPLATES:
            text = render_markdown(sample, job(), name, match_job(sample, job()))
            for entry in sample.experience:
                self.assertIn(entry.company, text, f"{name} lost {entry.company}")


if __name__ == "__main__":
    unittest.main()
