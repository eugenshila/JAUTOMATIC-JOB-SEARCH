"""Job-source parsing, filtering, de-duplication and failure handling."""
from __future__ import annotations

import unittest
from unittest import mock

import requests

from jautomatic.models import AppSettings, JobPosting
from jautomatic.services import job_scraper
from jautomatic.services.job_scraper import (
    AdzunaSource,
    ArbeitnowSource,
    ArtificialAeSource,
    HimalayasSource,
    JobScraper,
    RemoteOkSource,
    RemotiveSource,
    SampleSource,
    SearchQuery,
    TaskSource,
    default_task_sources,
    linkedin_search_url,
    looks_remote,
    parse_salary,
    posting_from_url,
)

from .fixtures import ADZUNA, ARBEITNOW, HIMALAYAS, REMOTEOK, REMOTIVE, UAEAI


class SalaryParsingTests(unittest.TestCase):
    def test_dollar_range(self):
        self.assertEqual(parse_salary("$90,000 - $120,000"), (90000, 120000, "USD"))

    def test_euro_suffix_and_k_shorthand(self):
        self.assertEqual(parse_salary("€70k – 90k"), (70000, 90000, "EUR"))

    def test_currency_code(self):
        low, high, currency = parse_salary("85000 - 105000 GBP per annum")
        self.assertEqual((low, high), (85000, 105000))
        self.assertEqual(currency, "GBP")

    def test_reversed_band_is_normalised(self):
        self.assertEqual(parse_salary("EUR 95000 - 75000"), (75000, 95000, "EUR"))

    def test_no_salary_text(self):
        self.assertEqual(parse_salary("Competitive salary, great team"), (0, 0, ""))

    def test_strips_html_before_parsing(self):
        self.assertEqual(parse_salary("<p>Pay: <b>$120,000 - $150,000</b></p>"),
                         (120000, 150000, "USD"))


class RemoteDetectionTests(unittest.TestCase):
    def test_detects_remote_variants(self):
        for text in ("Remote (EU)", "work from home", "Distributed team", "Fully Remote"):
            self.assertTrue(looks_remote(text), text)

    def test_ignores_onsite(self):
        self.assertFalse(looks_remote("Amsterdam, Netherlands (on-site)"))


class RemotiveTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(job_scraper, "_request_json", return_value=REMOTIVE)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_parses_jobs(self):
        jobs = RemotiveSource().fetch(SearchQuery(text="python", limit_per_source=10))
        self.assertEqual(len(jobs), 2)
        job = jobs[0]
        self.assertEqual(job.title, "Senior Python Engineer")
        self.assertEqual(job.company, "Northwind Analytics")
        self.assertTrue(job.remote)
        self.assertEqual(job.salary_min, 90000)
        self.assertEqual(job.currency, "USD")
        self.assertIn("data platform", job.description)
        self.assertNotIn("<p>", job.description)
        self.assertEqual(job.tags[:2], ["python", "fastapi"])

    def test_request_uses_search_parameter(self):
        with mock.patch.object(job_scraper, "_request_json", return_value=REMOTIVE) as request:
            RemotiveSource().fetch(SearchQuery(text="python", limit_per_source=7))
        args, kwargs = request.call_args
        params = kwargs.get("params") or args[2]
        self.assertEqual(args[0], "https://remotive.com/api/remote-jobs")
        self.assertEqual(params["search"], "python")
        self.assertEqual(params["limit"], 7)


class ArbeitnowTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(job_scraper, "_request_json", return_value=ARBEITNOW)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_parses_and_infers_remote(self):
        jobs = ArbeitnowSource().fetch(SearchQuery(text="go backend", limit_per_source=5))
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.company, "Kestrel Logistics")
        self.assertTrue(job.remote)
        self.assertEqual(job.location, "Berlin")

    def test_term_filtering_drops_non_matches(self):
        jobs = ArbeitnowSource().fetch(SearchQuery(text="accountant", limit_per_source=5))
        self.assertEqual([j.title for j in jobs], ["Accountant"])


class RemoteOkTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(job_scraper, "_request_json", return_value=REMOTEOK)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_skips_metadata_entries(self):
        jobs = RemoteOkSource().fetch(SearchQuery(text="machine learning", limit_per_source=5))
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.title, "Machine Learning Engineer, NLP")
        self.assertEqual((job.salary_min, job.salary_max), (90000, 125000))
        self.assertEqual(job.currency, "USD")

    def test_unrelated_query_returns_nothing(self):
        self.assertEqual(RemoteOkSource().fetch(SearchQuery(text="welding")), [])


class AdzunaTests(unittest.TestCase):
    def test_requires_credentials(self):
        settings = AppSettings()
        self.assertFalse(AdzunaSource().is_configured(settings))
        settings.adzuna_app_id, settings.adzuna_app_key = "id", "key"
        self.assertTrue(AdzunaSource().is_configured(settings))

    def test_parses_payload(self):
        settings = AppSettings(adzuna_app_id="id", adzuna_app_key="key", adzuna_country="gb")
        source = AdzunaSource()
        with mock.patch.object(job_scraper, "_request_json", return_value=ADZUNA) as request:
            jobs = source.fetch_with(SearchQuery(text="data engineer", limit_per_source=10),
                                     settings)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.company, "Helio Health")
        self.assertEqual(job.location, "Amsterdam, Netherlands")
        self.assertEqual((job.salary_min, job.salary_max), (65000, 82000))
        self.assertIn("/gb/", request.call_args[0][0])


class HimalayasTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(job_scraper, "_request_json", return_value=HIMALAYAS)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_parses_jobs(self):
        jobs = HimalayasSource().fetch(SearchQuery(text="engineer", limit_per_source=10))
        self.assertEqual(len(jobs), 2)
        job = jobs[0]
        self.assertEqual(job.title, "Machine Learning Engineer")
        self.assertEqual(job.company, "Paystack Kenya")
        self.assertTrue(job.remote)
        self.assertEqual(job.currency, "USD")
        self.assertIn("Kenya", job.location)

    def test_monthly_salary_annualised(self):
        jobs = HimalayasSource().fetch(SearchQuery(limit_per_source=10))
        uae_job = next(j for j in jobs if "Dataloop" in (j.company or ""))
        self.assertEqual(uae_job.salary_min, 12000 * 12)
        self.assertEqual(uae_job.salary_max, 15000 * 12)
        self.assertEqual(uae_job.currency, "AED")

    def test_kenya_country_filter(self):
        with mock.patch.object(job_scraper, "_request_json", return_value=HIMALAYAS) as req:
            HimalayasSource().fetch(SearchQuery(text="engineer", location="Kenya",
                                                limit_per_source=10))
        params = req.call_args[1].get("params") or req.call_args[0][2]
        self.assertEqual(params.get("country"), "KE")

    def test_unrestricted_when_no_location(self):
        with mock.patch.object(job_scraper, "_request_json", return_value=HIMALAYAS) as req:
            HimalayasSource().fetch(SearchQuery(text="engineer", limit_per_source=10))
        params = req.call_args[1].get("params") or req.call_args[0][2]
        self.assertNotIn("country", params)


class ArtificialAeTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(job_scraper, "_request_json", return_value=UAEAI)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_parses_jobs(self):
        jobs = ArtificialAeSource().fetch(SearchQuery(limit_per_source=10))
        self.assertEqual(len(jobs), 2)
        job = jobs[0]
        self.assertEqual(job.title, "Senior AI Engineer")
        self.assertEqual(job.company, "Emirates")
        self.assertTrue(job.remote is False)
        self.assertIn("Dubai", job.location)
        self.assertEqual(job.currency, "")
        self.assertIn("artificial.ae", job.url)

    def test_remote_emirate(self):
        payload = dict(UAEAI)
        payload["data"] = [{**UAEAI["data"][0], "emirate": "remote"}]
        with mock.patch.object(job_scraper, "_request_json", return_value=payload):
            jobs = ArtificialAeSource().fetch(SearchQuery(limit_per_source=10))
        self.assertTrue(jobs[0].remote)
        self.assertEqual(jobs[0].location, "Remote (UAE)")

    def test_emirate_filter(self):
        with mock.patch.object(job_scraper, "_request_json", return_value=UAEAI) as req:
            ArtificialAeSource().fetch(SearchQuery(location="Abu Dhabi",
                                                   limit_per_source=10))
        params = req.call_args[1].get("params") or req.call_args[0][2]
        self.assertEqual(params.get("emirate"), "abu dhabi")

    def test_uae_no_key_required(self):
        self.assertFalse(ArtificialAeSource().needs_credentials)
        self.assertTrue(ArtificialAeSource().is_configured(AppSettings()))


class OrchestratorTests(unittest.TestCase):
    def _scraper(self, settings: AppSettings | None = None) -> JobScraper:
        return JobScraper(settings or AppSettings(), sources=[
            RemotiveSource(), ArbeitnowSource(), RemoteOkSource(), SampleSource()])

    def test_merges_sources_and_dedupes(self):
        duplicate = dict(REMOTIVE["jobs"][0])
        payload = {"jobs": [REMOTIVE["jobs"][0], REMOTIVE["jobs"][0], duplicate]}

        def fake(url, timeout, params=None):  # noqa: ANN001
            if "remotive" in url:
                return payload
            if "arbeitnow" in url:
                return ARBEITNOW
            return REMOTEOK

        with mock.patch.object(job_scraper, "_request_json", side_effect=fake):
            outcome = self._scraper().search(
                SearchQuery(text="python", sources=["remotive", "arbeitnow", "remoteok"],
                            limit_per_source=10))
        titles = [job.title for job in outcome.jobs]
        self.assertEqual(titles.count("Senior Python Engineer"), 1)
        self.assertTrue(outcome.results_ok_count == 3)

    def test_filters_and_reports_drops(self):
        with mock.patch.object(job_scraper, "_request_json", return_value=REMOTIVE) as _:
            outcome = self._scraper().search(SearchQuery(
                text="python", sources=["remotive"], limit_per_source=10,
                exclude_keywords=["designer"]))
        self.assertEqual([j.title for j in outcome.jobs], ["Senior Python Engineer"])
        self.assertEqual(outcome.filtered_out, 1)

    def test_remote_only_filter(self):
        with mock.patch.object(job_scraper, "_request_json", return_value=ARBEITNOW):
            outcome = self._scraper().search(SearchQuery(
                text="", sources=["arbeitnow"], limit_per_source=10, remote_only=True))
        self.assertTrue(all(job.remote for job in outcome.jobs))
        self.assertEqual(len(outcome.jobs), 1)

    def test_min_salary_filter_keeps_undisclosed(self):
        with mock.patch.object(job_scraper, "_request_json", return_value=REMOTIVE):
            outcome = self._scraper().search(SearchQuery(
                text="", sources=["remotive"], limit_per_source=10, min_salary=100000))
        titles = [j.title for j in outcome.jobs]
        self.assertIn("Senior Python Engineer", titles)   # pays up to 120k
        self.assertIn("Product Designer", titles)         # no band disclosed -> kept

    def test_source_failure_is_reported_not_raised(self):
        error = requests.exceptions.SSLError("TLS handshake failed")
        with mock.patch.object(job_scraper, "_request_json", side_effect=error):
            outcome = self._scraper().search(SearchQuery(text="python", sources=["remotive"]))
        # the failure is surfaced as text, never as an exception ...
        self.assertEqual(outcome.results_ok_count, 0)
        self.assertIn("TLS", outcome.errors[0])
        # ... and the demo source keeps the app usable, clearly flagged
        self.assertTrue(outcome.used_fallback)
        self.assertTrue(all(job.source == "sample" for job in outcome.jobs))

    def test_cancel_before_the_first_result_returns_empty_and_skips_fallback(self):
        def fake(url, timeout, params=None):  # noqa: ANN001
            return REMOTIVE

        with mock.patch.object(job_scraper, "_request_json", side_effect=fake):
            outcome = self._scraper().search(
                SearchQuery(text="python", sources=["remotive", "arbeitnow"],
                            limit_per_source=10),
                should_cancel=lambda: True)
        self.assertEqual(outcome.jobs, [])       # nothing consumed after the cancel flag
        self.assertEqual(outcome.results, [])
        self.assertFalse(outcome.used_fallback)  # a closing app must not "recover" into demo data

    def test_cancel_after_the_first_source_keeps_the_partial_result(self):
        arrivals = iter([False, True, True])

        with mock.patch.object(job_scraper, "_request_json", return_value=REMOTIVE):
            outcome = self._scraper().search(
                SearchQuery(text="python", sources=["remotive", "arbeitnow"],
                            limit_per_source=10),
                should_cancel=lambda: next(arrivals, True))
        self.assertEqual(len(outcome.results), 1)          # first source landed, then stop
        self.assertEqual(outcome.jobs[0].source, "remotive")

    def test_no_fallback_when_a_source_responded(self):
        def fake(url, timeout, params=None):  # noqa: ANN001, ARG001
            if "remotive" in url:
                return REMOTIVE
            raise requests.exceptions.ConnectionError("blocked")

        with mock.patch.object(job_scraper, "_request_json", side_effect=fake):
            outcome = self._scraper().search(
                SearchQuery(text="python", sources=["remotive", "arbeitnow"]))
        self.assertFalse(outcome.used_fallback)
        self.assertEqual(outcome.results_ok_count, 1)
        self.assertTrue(all(job.source == "remotive" for job in outcome.jobs))

    def test_offline_fallback_produces_demo_data(self):
        error = requests.exceptions.ConnectionError("no route to host")
        with mock.patch.object(job_scraper, "_request_json", side_effect=error):
            outcome = self._scraper().search(SearchQuery(text="python", sources=["remotive"]))
        self.assertTrue(outcome.used_fallback)
        self.assertTrue(outcome.jobs)
        self.assertIn("demo posting", outcome.summary())

    def test_sample_source_respects_query(self):
        jobs = SampleSource().fetch(SearchQuery(text="product manager", limit_per_source=10))
        self.assertEqual([j.title for j in jobs], ["Product Manager, Platform"])
        self.assertTrue(all(isinstance(j, JobPosting) for j in jobs))

    def test_query_words_are_split_and_filler_dropped(self):
        self.assertEqual(SearchQuery(text="Senior Python Engineer, remote").terms,
                         ["python", "engineer"])
        self.assertEqual(SearchQuery(text="data engineer").terms, ["data", "engineer"])
        jobs = SampleSource().fetch(SearchQuery(text="frontend react", limit_per_source=5))
        self.assertEqual([j.title for j in jobs], ["Frontend Engineer (React)"])

    def test_multi_word_query_matches_any_word_as_fallback(self):
        with mock.patch.object(job_scraper, "_request_json", return_value=ARBEITNOW):
            outcome = self._scraper().search(SearchQuery(
                text="accountant nursing", sources=["arbeitnow"], limit_per_source=5))
        self.assertEqual([j.title for j in outcome.jobs], ["Accountant"])

    def test_sources_are_queried_concurrently(self):
        calls: list[str] = []

        def fake(url, timeout, params=None):  # noqa: ANN001, ARG001
            calls.append(url)
            return REMOTIVE if "remotive" in url else ARBEITNOW

        with mock.patch.object(job_scraper, "_request_json", side_effect=fake):
            outcome = self._scraper().search(
                SearchQuery(text="python", sources=["remotive", "arbeitnow"]))
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(outcome.results), 2)
        self.assertLess(outcome.elapsed, 5)


class PostingFromUrlTests(unittest.TestCase):
    PAGE = """
    <html><head>
      <title>Senior Python Engineer - Northwind Analytics | Greenhouse</title>
      <meta property="og:title" content="Senior Python Engineer">
      <meta property="og:site_name" content="Northwind Analytics">
      <meta property="og:description"
            content="Own the data platform. Pay: $90,000 - $120,000. Remote (EU) welcome.">
    </head><body></body></html>
    """

    def _fetch(self, text: str, url: str = "https://boards.greenhouse.io/northwind/jobs/123"):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.text = text
        with mock.patch.object(job_scraper.requests, "get", return_value=response) as get:
            job = posting_from_url(url)
            return job, get

    def test_extracts_fields_and_parses_salary(self):
        job, get = self._fetch(self.PAGE)
        self.assertEqual(job.title, "Senior Python Engineer")
        self.assertEqual(job.company, "Northwind Analytics")
        self.assertEqual(job.source, "manual")
        self.assertEqual(job.url, "https://boards.greenhouse.io/northwind/jobs/123")
        self.assertEqual((job.salary_min, job.salary_max), (90000, 120000))
        self.assertTrue(job.remote)
        self.assertTrue(job.tags)
        self.assertIn("/boards.greenhouse.io/", get.call_args[0][0])

    def test_falls_back_to_title_and_domain(self):
        job, _ = self._fetch("<html><head><title>Backend Engineer (Go)</title></head></html>",
                             "https://kestrel.io/jobs/1")
        self.assertEqual(job.title, "Backend Engineer (Go)")
        self.assertEqual(job.company, "Kestrel")          # kestrel.io -> "Kestrel"
        self.assertEqual(job.url, "https://kestrel.io/jobs/1")

    def test_json_ld_description_is_used_when_meta_is_missing(self):
        html = ('<html><head>'
                '<script type="application/ld+json">'
                '{"@type":"JobPosting","title":"Data Engineer",'
                '"description":"Write SQL against Snowflake. Salary \u20ac60k - \u20ac75k."}'
                '</script></head></html>')
        job, _ = self._fetch(html)
        self.assertIn("Snowflake", job.description)
        self.assertEqual((job.salary_min, job.salary_max), (60000, 75000))

    def test_scheme_is_added_when_missing(self):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.text = self.PAGE
        with mock.patch.object(job_scraper.requests, "get", return_value=response) as get:
            job = posting_from_url("boards.lever.co/northwind/jobs/9")
        self.assertTrue(job.url.startswith("https://"))

    def test_invalid_url_raises_value_error(self):
        with self.assertRaises(ValueError):
            posting_from_url("ftp://example.com/jobs/1")

    def test_empty_url_raises(self):
        with self.assertRaises(ValueError):
            posting_from_url("   ")

    def test_network_errors_propagate_as_request_exceptions(self):
        with mock.patch.object(job_scraper.requests, "get",
                               side_effect=requests.exceptions.Timeout("too slow")):
            with self.assertRaises(requests.exceptions.RequestException):
                posting_from_url("https://example.com/jobs/1")

    def test_linkedin_url_is_labeled_linkedin(self):
        page = """
        <html><head>
          <title>Senior Python Engineer - Northwind Analytics | LinkedIn</title>
          <meta property="og:title" content="Senior Python Engineer - Northwind Analytics | LinkedIn">
          <meta property="og:site_name" content="Northwind Analytics">
        </head><body></body></html>
        """
        job, _ = self._fetch(page, "https://www.linkedin.com/jobs/view/1234567")
        self.assertEqual(job.source, "linkedin")
        self.assertEqual(job.title, "Senior Python Engineer")
        self.assertEqual(job.url, "https://www.linkedin.com/jobs/view/1234567")


class LinkedInHandoffTests(unittest.TestCase):
    def _url(self, **overrides) -> str:
        kwargs = {"query_text": "Python Engineer", "location": "Berlin, Germany", **overrides}
        return linkedin_search_url(**kwargs)

    def test_builds_guest_search_url_with_easy_apply_by_default(self):
        url = self._url()
        self.assertTrue(url.startswith("https://www.linkedin.com/jobs/search/?"))
        self.assertIn("keywords=Python+Engineer", url)
        self.assertIn("f_AL=true", url)

    def test_easy_apply_can_be_yurned_off(self):
        self.assertNotIn("f_AL", self._url(easy_apply_only=False))

    def test_remote_filter_adds_f_wt(self):
        self.assertIn("f_WT=2", self._url(remote_only=True))

    def test_location_is_encoded(self):
        self.assertIn("location=Berlin%2C+Germany", self._url())

    def test_is_exported(self):
        self.assertIn("linkedin_search_url", job_scraper.__all__)


class ScraperPublicApiTests(unittest.TestCase):
    def test_posting_from_url_is_exported(self):
        self.assertIn("posting_from_url", job_scraper.__all__)


class TaskSourceTests(unittest.TestCase):
    def test_fetch_returns_usd_priced_remote_tasks(self):
        jobs = TaskSource().fetch(SearchQuery(text="audio", limit_per_source=25))
        self.assertEqual(jobs[0].title, "Audio transcription - English audio")
        self.assertTrue(all(job.currency.upper() == "USD" for job in jobs))
        self.assertTrue(all(job.remote for job in jobs))
        self.assertTrue(all((job.salary_min or 0) > 0 for job in jobs))
        self.assertEqual(jobs[0].source, "tasks")

    def test_fetch_respects_limit(self):
        jobs = TaskSource().fetch(SearchQuery(text="", limit_per_source=4))
        self.assertEqual(len(jobs), 4)

    def test_query_terms_filter_the_feed(self):
        matching = TaskSource().fetch(SearchQuery(text="translation", limit_per_source=25))
        self.assertTrue(any("translation" in (job.title + job.description).lower()
                            for job in matching))
        empty = TaskSource().fetch(SearchQuery(text="", limit_per_source=0))
        self.assertEqual(empty, [])

    def test_scraper_search_via_tasks_source(self):
        settings = AppSettings()
        settings.enabled_sources = []          # search must use the explicit source list
        scraper = JobScraper(settings, sources=default_task_sources())
        outcome = scraper.search(SearchQuery(text="labeling", limit_per_source=10,
                                             sources=["tasks"]))
        self.assertFalse(outcome.errors)
        self.assertTrue(outcome.jobs)
        self.assertEqual(outcome.jobs[0].source, "tasks")
        self.assertTrue(all(job.currency.upper() == "USD" for job in outcome.jobs))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
