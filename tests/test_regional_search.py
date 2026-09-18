"""Regional coverage regressions without live network dependencies."""
import hashlib
import unittest
from unittest.mock import Mock, patch

from jautomatic.models import AppSettings, DEFAULT_SOURCE_NAMES, JobPosting
from jautomatic.services.job_regions import location_matches
from jautomatic.services.job_scraper import SearchQuery, query_matches, posting_from_details
from jautomatic.services.regional_job_sources import regional_sources, JoobleUaeSource
from tests.support import WorkspaceTestCase


class RegionalSearchTests(unittest.TestCase):
    def test_regions_and_cities(self):
        for wanted, actual, expected in [
            ("Africa; UAE", "Nairobi, Kenya", True),
            ("Africa; UAE", "Dubai", True),
            ("Africa", "Accra, Ghana", True),
            ("Africa", "Berlin, Germany", False),
            ("South Africa", "Nairobi, Kenya", False),
            ("Dubai", "Abu Dhabi, UAE", False),
        ]:
            with self.subTest(wanted=wanted, actual=actual):
                self.assertEqual(location_matches(wanted, actual), expected)

    def test_logistics_related_titles(self):
        for title in ("Procurement Officer", "Supply Chain Manager", "Warehouse Supervisor",
                      "Freight Coordinator", "Transport Planner"):
            self.assertTrue(query_matches(title, ["logistics"]))
        self.assertFalse(query_matches("Software Engineer", ["logistics"]))

    def test_old_default_expands_but_custom_selection_survives(self):
        settings = AppSettings.from_dict({"enabled_sources": ["remotive", "arbeitnow", "remoteok"]})
        self.assertEqual(settings.enabled_sources, DEFAULT_SOURCE_NAMES)
        self.assertEqual(AppSettings.from_dict({"enabled_sources": ["sample"]}).enabled_sources,
                         ["sample"])

    def test_feed_filters_before_applying_limit(self):
        response = Mock(content=b'''<rss><channel>
          <item><title>Lawyer at Example</title><link>https://example.com/1</link></item>
          <item><title>Warehouse Manager at Example</title><link>https://example.com/2</link>
            <location>Nairobi</location><description>Manage inventory</description></item>
          <item><title>Logistics Officer</title><link>https://example.com/3</link>
            <expiryDate>2000-01-01</expiryDate></item>
        </channel></rss>''')
        with patch("jautomatic.services.regional_job_sources.requests.get", return_value=response):
            jobs = regional_sources()[0].fetch(SearchQuery(text="logistics", location="Africa; UAE",
                                                          limit_per_source=1))
        self.assertEqual([j.title for j in jobs], ["Warehouse Manager"])
        self.assertEqual(jobs[0].location, "Nairobi, Kenya")

    def test_jooble_combined_region_and_secret_redaction(self):
        import requests
        settings = AppSettings(jooble_uae_key="secret-key")
        with patch("jautomatic.services.regional_job_sources.requests.post",
                   side_effect=requests.ConnectionError("https://jooble.org/api/secret-key")):
            with self.assertRaises(requests.RequestException) as caught:
                JoobleUaeSource().fetch_with(SearchQuery(location="Africa; UAE"), settings)
        self.assertNotIn("secret-key", str(caught.exception))

    def test_manual_linkedin_details(self):
        job = posting_from_details("https://www.linkedin.com/jobs/view/123", "Logistics Officer",
                                   "Example", "Dubai", "Manage shipping and inventory", False)
        self.assertEqual(job.source, "linkedin")
        self.assertEqual(job.location, "Dubai")


class JobIdentityTests(WorkspaceTestCase):
    def test_query_ids_are_distinct_and_legacy_record_is_updated(self):
        first = JobPosting(title="First", url="https://example.com/job?id=1&utm_source=feed")
        second = JobPosting(title="Second", url="https://example.com/job?id=2")
        self.workspace.save_jobs([first])
        old_hash = hashlib.sha1(b"https://example.com/job").hexdigest()
        self.workspace._conn.execute("UPDATE jobs SET fingerprint=?", (old_hash,))
        self.workspace._conn.commit()
        refreshed = JobPosting(title="Updated", url="https://example.com/job?id=1&utm_source=other")
        self.assertEqual(self.workspace.save_jobs([refreshed, second]), 1)
        self.assertEqual(refreshed.job_id, first.job_id)
        self.assertEqual(len(self.workspace.jobs()), 2)
