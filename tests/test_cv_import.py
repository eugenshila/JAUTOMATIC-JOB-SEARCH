"""CV import: docx / txt / md files map onto a Profile draft."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from jautomatic.services.cv_import import extract_cv_text, parse_cv
from tests.support import WorkspaceTestCase

TXT_CV = """Alex Doe
Senior Python Engineer · data platforms
Berlin, Germany
alex.doe@example.com
+49 30 1234 5678
LinkedIn: linkedin.com/in/alexdoe | GitHub: github.com/alexdoe

Professional summary
Backend engineer with 8 years of experience building data platforms. I design
scalable ETL pipelines and lead teams that ship.

Skills
Python, FastAPI, PostgreSQL, Docker, AWS

Experience
Senior Backend Engineer — DataWorks GmbH | Berlin
Mar 2021 – Present
- Built a real-time event pipeline handling 2M events/min
- Cut processing costs 40% by moving to spot workloads

Python Engineer — Cloudly Inc | Remote
Jan 2018 – Feb 2021
Implemented microservices in Python and Django.

Education
MSc Computer Science — TU Berlin
Oct 2014 – Apr 2017

Bachelor of Science in Mathematics — University of Bonn
2011 - 2014

Languages
English (C1), German (B2)
"""

MD_CV = """# Alex Doe

Senior Python Engineer · data platforms

Berlin, Germany
alex.doe@example.com
+49 30 1234 5678

## Professional summary

Backend engineer with 8 years of experience building data platforms.

## Skills

- Python
- FastAPI
- PostgreSQL
- Docker
- AWS

## Experience

## Senior Backend Engineer — DataWorks GmbH | Berlin

Mar 2021 – Present
- Built a real-time event pipeline handling 2M events/min

## Education

## MSc Computer Science — TU Berlin

Oct 2014 – Apr 2017

## Languages

English (C1), German (B2)
"""


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


class CvImportTests(unittest.TestCase):
    def test_txt_full_parse(self):
        tmp = _tmp()
        try:
            path = tmp / "cv.txt"
            path.write_text(TXT_CV, encoding="utf-8")
            profile = parse_cv(path)
            self.assertEqual(profile.full_name, "Alex Doe")
            self.assertIn("data platforms", profile.headline)
            self.assertEqual(profile.email, "alex.doe@example.com")
            self.assertEqual(profile.phone, "+49 30 1234 5678")
            self.assertEqual(profile.location, "Berlin, Germany")
            self.assertIn("linkedin.com/in/alexdoe", profile.links)
            self.assertIn("github.com/alexdoe", profile.links)
            self.assertIn("ETL", profile.summary)
            self.assertEqual(profile.seniority, "senior")
            for skill in ("Python", "FastAPI", "PostgreSQL", "Docker", "AWS"):
                self.assertIn(skill, profile.skills)
            self.assertIn("German (B2)", profile.languages)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_experience_and_education(self):
        tmp = _tmp()
        try:
            path = tmp / "cv.txt"
            path.write_text(TXT_CV, encoding="utf-8")
            profile = parse_cv(path)
            self.assertEqual(len(profile.experience), 2)
            first, second = profile.experience
            self.assertEqual(first.title, "Senior Backend Engineer")
            self.assertEqual(first.company, "DataWorks GmbH")
            self.assertEqual(first.location, "Berlin")
            self.assertEqual((first.start, first.end), ("Mar 2021", "present"))
            self.assertTrue(any("event pipeline" in bullet
                                for bullet in first.highlights))
            self.assertEqual(second.title, "Python Engineer")
            self.assertEqual(second.end, "Feb 2021")
            self.assertIn("microservices", second.summary)
            self.assertEqual(len(profile.education), 2)
            self.assertIn("MSc", profile.education[0].degree)
            self.assertEqual(profile.education[0].school, "TU Berlin")
            self.assertEqual(profile.education[1].school, "University of Bonn")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_markdown_parse(self):
        tmp = _tmp()
        try:
            path = tmp / "cv.md"
            path.write_text(MD_CV, encoding="utf-8")
            profile = parse_cv(path)
            self.assertEqual(profile.full_name, "Alex Doe")
            self.assertEqual(profile.email, "alex.doe@example.com")
            self.assertIn("Python", profile.skills)
            self.assertEqual(len(profile.experience), 1)
            self.assertEqual(profile.experience[0].company, "DataWorks GmbH")
            self.assertEqual(profile.education[0].degree, "MSc Computer Science")
            self.assertIn("German (B2)", profile.languages)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_docx_parse(self):
        tmp = _tmp()
        try:
            from docx import Document

            path = tmp / "cv.docx"
            document = Document()
            for line in TXT_CV.splitlines():
                document.add_paragraph(line)
            document.save(str(path))
            profile = parse_cv(path)
            self.assertEqual(profile.full_name, "Alex Doe")
            self.assertEqual(profile.email, "alex.doe@example.com")
            self.assertIn("PostgreSQL", profile.skills)
            self.assertEqual(len(profile.experience), 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_reject_unsupported_and_empty(self):
        tmp = _tmp()
        try:
            pdf = tmp / "cv.pdf"
            pdf.write_text("%PDF-1.4 fake", encoding="utf-8")
            with self.assertRaises(ValueError):
                extract_cv_text(pdf)
            with self.assertRaises(ValueError):
                parse_cv(pdf)
            empty = tmp / "empty.txt"
            empty.write_text("   \n\n  ", encoding="utf-8")
            with self.assertRaises(ValueError):
                parse_cv(empty)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_minimal_cv_keeps_scalars_and_no_guesses(self):
        tmp = _tmp()
        try:
            path = tmp / "minimal.md"
            path.write_text("# Jane Roe\n\nData Scientist\nRemote\njane@ex.com\n\n"
                            "**Skills**\nPython, SQL, Spark\n", encoding="utf-8")
            profile = parse_cv(path)
            self.assertEqual(profile.full_name, "Jane Roe")
            self.assertEqual(profile.headline, "Data Scientist")
            self.assertEqual(profile.email, "jane@ex.com")
            self.assertIn("SQL", profile.skills)
            self.assertEqual(profile.experience, [])
            self.assertEqual(profile.education, [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_heading_cv_recovers_summary_skills_and_languages(self):
        text = """John Smith
Data Analyst
Addis Ababa, Ethiopia
john@example.com

More than five years turning messy spreadsheets into clear dashboards for
finance teams. Comfortable with SQL and Python.

Technologies: Python (Advanced), SQL; Databases: PostgreSQL, MySQL | CI/CD

Full Stack Developer
Addis Ababa, Ethiopia
Mar 2021 - Present
- Built live KPI dashboards for finance

Languages: English (C1), French (B2)
"""
        tmp = _tmp()
        try:
            path = tmp / "no_heading.txt"
            path.write_text(text, encoding="utf-8")
            profile = parse_cv(path)
            self.assertEqual(profile.full_name, "John Smith")
            self.assertIn("five years", profile.summary.lower())
            self.assertIn("Python", profile.skills)
            self.assertIn("SQL", profile.skills)
            self.assertIn("PostgreSQL", profile.skills)
            self.assertIn("MySQL", profile.skills)
            self.assertNotIn("Databases", profile.skills)
            self.assertIn("English", profile.languages)
            self.assertIn("French", profile.languages)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_inline_label_summary_is_stripped(self):
        tmp = _tmp()
        try:
            path = tmp / "inline_summary.md"
            path.write_text("# Ben Cole\n\nben@ex.com\n\n"
                            "Professional summary: Backend engineer with 8 years "
                            "building data platforms.\n\n"
                            "Skills: Python, SQL\n", encoding="utf-8")
            profile = parse_cv(path)
            self.assertTrue(profile.summary.startswith("Backend engineer"))
            self.assertNotIn("professional summary", profile.summary.lower())
            self.assertIn("Python", profile.skills)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_experience_single_dates_and_undated_trailing_role(self):
        text = """Data Analyst | Techno Corp | Berlin
2020 - 2021
- Cleaned survey data

Junior Analyst
2018 - 2019
- Maintained weekly reports

Intern
- Assisted the reporting team
"""
        tmp = _tmp()
        try:
            path = tmp / "roles.txt"
            path.write_text(f"# Pat Roe\n\npat@ex.com\n\nExperience\n\n{text}",
                            encoding="utf-8")
            profile = parse_cv(path)
            self.assertEqual(len(profile.experience), 3)
            analyst, junior, intern = profile.experience
            self.assertEqual(analyst.title, "Data Analyst")
            self.assertEqual(analyst.company, "Techno Corp")
            self.assertEqual(analyst.location, "Berlin")
            self.assertIn("reports", " ".join(junior.highlights).lower())
            self.assertEqual(intern.title, "Intern")
            self.assertTrue(any("reporting team" in bullet.lower()
                                for bullet in intern.highlights))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_dense_experience_splits_into_multiple_positions(self):
        text = ("Senior Data Scientist | Alpha Ltd | London | 2021 - Present\n"
                "- Built churn models\n"
                "Data Scientist | Beta Corp | 2019 - 2021\n"
                "- Maintained dashboards\n"
                "Junior Analyst | Gamma | 2017 - 2019\n"
                "- Cleaned raw datasets\n")
        tmp = _tmp()
        try:
            path = tmp / "dense.txt"
            path.write_text(f"# Kim Lee\n\nkim@ex.com\n\nExperience\n\n{text}",
                            encoding="utf-8")
            profile = parse_cv(path)
            self.assertEqual(len(profile.experience), 3)
            senior, scientist, analyst = profile.experience
            self.assertEqual(senior.title, "Senior Data Scientist")
            self.assertEqual(senior.company, "Alpha Ltd")
            self.assertEqual(senior.location, "London")
            self.assertEqual((senior.start, senior.end), ("2021", "present"))
            self.assertEqual(scientist.company, "Beta Corp")
            self.assertEqual((scientist.start, scientist.end), ("2019", "2021"))
            self.assertEqual(analyst.company, "Gamma")
            self.assertEqual(analyst.start, "2017")
            self.assertTrue(any("churn" in b for b in senior.highlights))
            self.assertTrue(any("dashboards" in b for b in scientist.highlights))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_key_skills_and_areas_of_expertise_headings_are_imported(self):
        tmp = _tmp()
        try:
            path = tmp / "key_skills.txt"
            path.write_text("# Pat Roe\n\npat@ex.com\n\nKEY SKILLS\nPython, SQL, Tableau\n\n"
                            "AREAS OF EXPERTISE\nETL, Forecasting\n", encoding="utf-8")
            profile = parse_cv(path)
            skills = {s.lower(): s for s in profile.skills}
            for name in ("python", "sql", "tableau", "etl", "forecasting"):
                self.assertIn(name, skills)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_skill_section_from_bullets(self):
        tmp = _tmp()
        try:
            path = tmp / "skills_bullets.txt"
            path.write_text("# Sam Poe\n\nsam@ex.com\n\nTechnical Skills\n"
                            "- Python (Advanced)\n- Docker\n- AWS\n", encoding="utf-8")
            profile = parse_cv(path)
            skills = {s.lower(): s for s in profile.skills}
            self.assertIn("python", skills)
            self.assertIn("docker", skills)
            self.assertIn("aws", skills)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_operator_cv_with_company_role_headers_and_skill_lists(self):
        text = """Omar Hassan
LOGISTICS | OPERATIONS
Nairobi, Kenya | +254 700 123 456 | omar@example.com
linkedin.com/in/omarhassan | Open to relocation: UAE / GCC

PROFESSIONAL PROFILE
Logistics professional with 10+ years of experience in inbound/outbound logistics.
CORE COMPETENCIES
Supply Chain Operations • Logistics Coordination • Inbound & Outbound Operations • WMS/ERP
PROFESSIONAL EXPERIENCE
Spare Parts Logistics Coordinator | DHL
Sep 2010 - Apr 2018 | Nairobi, Kenya
- Coordinated inbound and outbound spare-parts logistics for HP and IBM.
Data Entry Clerk | DHL Express
Sep 2008 - Sep 2010 | Nairobi, Kenya
- Captured and validated shipment data.
EARLIER EXPERIENCE
DHL - IT Support | Apr 2008 - Dec 2008 | Nairobi • User administration and network monitoring.
EDUCATION & PROFESSIONAL DEVELOPMENT
Diploma in Computer Networking | Kenya Christian Technical Institute | 2000 - 2002
DIGITAL SKILLS
Microsoft Excel • Relational databases & SQL knowledge • Microsoft Office
LANGUAGES & MOBILITY
English - Professional Working Proficiency | Swahili - Professional Working Proficiency |
Based in Nairobi, Kenya | Open to UAE/GCC and international relocation
"""
        tmp = _tmp()
        try:
            path = tmp / "operator.txt"
            path.write_text(text, encoding="utf-8")
            profile = parse_cv(path)
            self.assertEqual(profile.location, "Nairobi, Kenya")
            self.assertEqual(len(profile.experience), 3)
            coordinator, clerk, it = profile.experience
            self.assertEqual(coordinator.title, "Spare Parts Logistics Coordinator")
            self.assertEqual(coordinator.company, "DHL")
            self.assertEqual(coordinator.location, "Nairobi, Kenya")
            self.assertEqual((coordinator.start, coordinator.end), ("Sep 2010", "Apr 2018"))
            self.assertEqual(clerk.title, "Data Entry Clerk")
            self.assertEqual(clerk.company, "DHL Express")
            self.assertEqual(it.title, "IT Support")
            self.assertEqual(it.company, "DHL")
            self.assertTrue(any("network monitoring" in b for b in it.highlights))
            skills = {s.lower(): s for s in profile.skills}
            self.assertIn("wms/erp", skills)
            self.assertIn("inbound & outbound operations", skills)
            self.assertIn("microsoft excel", skills)
            self.assertIn("relational databases & sql knowledge", skills)
            self.assertIn("English", profile.languages)
            self.assertIn("Swahili", profile.languages)
            self.assertNotIn("Kenya", profile.languages)
            self.assertTrue(profile.willing_to_relocate)
            self.assertEqual(profile.education[0].degree, "Diploma in Computer Networking")
            self.assertEqual(profile.education[0].school, "Kenya Christian Technical Institute")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_level_suffix_and_parenthetical_stripped_from_skills(self):
        tmp = _tmp()
        try:
            path = tmp / "levels.txt"
            path.write_text("# Pat Brown\n\npat@ex.com\n\nSkills\n"
                            "Python (Advanced), SQL - Intermediate; Proficient in "
                            "FastAPI; Databases: PostgreSQL\n", encoding="utf-8")
            profile = parse_cv(path)
            skills = {s.lower(): s for s in profile.skills}
            self.assertEqual(skills.get("python"), "Python")
            self.assertEqual(skills.get("sql"), "SQL")
            self.assertEqual(skills.get("fastapi"), "FastAPI")
            self.assertEqual(skills.get("postgresql"), "PostgreSQL")
            self.assertNotIn("Proficient", profile.skills)
            self.assertNotIn("Databases", profile.skills)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CvImportWorkspaceTests(WorkspaceTestCase):
    """Import result persists and round-trips through the workspace."""

    def test_workspace_save_round_trip(self):
        tmp = _tmp()
        try:
            path = tmp / "cv.txt"
            path.write_text(TXT_CV, encoding="utf-8")
            profile = parse_cv(path)
            self.workspace.save_profile(profile)
            loaded = self.workspace.load_profile()
            self.assertEqual(loaded.full_name, "Alex Doe")
            self.assertEqual(loaded.email, "alex.doe@example.com")
            self.assertEqual(len(loaded.experience), 2)
            self.assertEqual(len(loaded.education), 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()