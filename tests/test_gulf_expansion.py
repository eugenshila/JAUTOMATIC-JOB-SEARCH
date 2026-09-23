"""The 1.5 expansion: Jobicy, Working Nomads, company career boards, Gulf coverage."""
from __future__ import annotations

import re
import unittest
from unittest import mock

import requests

from jautomatic.models import (AppSettings, DEFAULT_SOURCE_NAMES, GULF_PRESET_SOURCE_NAMES,
                               SOURCE_NAMES_V2, JobPosting)
from jautomatic.services.company_boards import (BoardError, CompanyBoardsSource,
                                                DEFAULT_COMPANY_BOARDS, board_display,
                                                normalise_boards, parse_board_spec)
from jautomatic.services import job_scraper
from jautomatic.services.job_scraper import (JobScraper, JobicySource, SearchQuery,
                                             WorkingNomadsSource, jobicy_geo)
from jautomatic.services.job_regions import CITY_COUNTRIES, gulf_codes, location_matches
from jautomatic.services.regional_job_sources import (BROWSER_SITES, JoobleSource,
                                                      JoobleUaeSource, browser_boards,
                                                      browser_hint, browser_regions,
                                                      jooble_gulf_sources, jooble_key,
                                                      regional_search_url,
                                                      regional_sources)

from .fixtures import ASHBY, GREENHOUSE_CAREEM, JOBICY, LEVER_KITOPI, WORKINGNOMADS


class GulfGeographyTests(unittest.TestCase):
    def test_gulf_states_are_recognised(self):
        for wanted, actual in (("Gulf; UAE", "Dubai, UAE"),
                               ("Gulf", "Riyadh, Saudi Arabia"),
                               ("Saudi Arabia", "Doha, Qatar")):
            if wanted == "Saudi Arabia":
                self.assertFalse(location_matches(wanted, actual))
            else:
                self.assertTrue(location_matches(wanted, actual), (wanted, actual))
        self.assertTrue(location_matches("Qatar", "Doha"))
        self.assertTrue(location_matches("Gulf", "Manama, Bahrain"))
        self.assertFalse(location_matches("Gulf; UAE", "Berlin, Germany"))

    def test_gulf_cities_map_to_countries(self):
        for city, code in (("riyadh", "SA"), ("doha", "QA"), ("muscat", "OM"), ("manama", "BH")):
            self.assertEqual(CITY_COUNTRIES[city], code)

    def test_gulf_codes_helper(self):
        self.assertEqual(gulf_codes("Gulf; UAE"), {"AE", "SA", "QA", "KW", "OM", "BH"})
        self.assertEqual(gulf_codes("Dubai"), {"AE"})
        self.assertEqual(gulf_codes("Kenya"), set())

    def test_mena_and_middle_east_regions_exist(self):
        self.assertTrue(location_matches("Middle East", "Abu Dhabi, UAE"))
        self.assertTrue(location_matches("MENA", "Casablanca, Morocco"))


class JobicyTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(job_scraper, "_request_json", return_value=JOBICY)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_parses_jobs_with_monthly_salary_annualised(self):
        jobs = JobicySource().fetch(SearchQuery(text="logistics", limit_per_source=10))
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.title, "Staff Product Manager")
        self.assertEqual((job.salary_min, job.salary_max), (4000 * 12, 5000 * 12))
        self.assertEqual(job.currency, "AED")
        self.assertTrue(job.remote)
        self.assertIn("United Arab Emirates", job.location)

    def test_worldwide_roles_use_the_remote_location(self):
        jobs = JobicySource().fetch(SearchQuery(text="react", limit_per_source=10))
        self.assertEqual(jobs[0].location, "Remote (Worldwide)")
        self.assertEqual((jobs[0].salary_min, jobs[0].salary_max), (90000, 120000))

    def test_uae_location_sends_a_geo_filter(self):
        with mock.patch.object(job_scraper, "_request_json", return_value=JOBICY) as request:
            JobicySource().fetch(SearchQuery(location="UAE", limit_per_source=10))
        params = request.call_args[1].get("params") or request.call_args[0][2]
        self.assertEqual(params.get("geo"), "united-arab-emirates")

    def test_gulf_region_does_not_filter_to_one_country(self):
        # Jobicy has no slug for the Gulf as a whole: no geo filter, then the shared
        # location filter keeps worldwide roles the search asked for.
        with mock.patch.object(job_scraper, "_request_json", return_value=JOBICY) as request:
            jobs = JobicySource().fetch(SearchQuery(location="Gulf; UAE", limit_per_source=10))
        params = request.call_args[1].get("params") or request.call_args[0][2]
        self.assertNotIn("geo", params)
        self.assertTrue(jobs)

    def test_geo_helper_resolves_single_countries(self):
        self.assertEqual(jobicy_geo("Kenya"), "")
        self.assertEqual(jobicy_geo("Dubai"), "united-arab-emirates")
        self.assertEqual(jobicy_geo("Germany"), "germany")
        self.assertEqual(jobicy_geo("Africa; UAE"), "")
        self.assertEqual(jobicy_geo("Gulf"), "")


class WorkingNomadsTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(job_scraper, "_request_json", return_value=WORKINGNOMADS)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_parses_jobs_and_salary(self):
        jobs = WorkingNomadsSource().fetch(SearchQuery(text="logistics", limit_per_source=10))
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.title, "Remote Logistics Coordinator")
        self.assertEqual(job.company, "Kestrel Logistics")
        self.assertEqual((job.salary_min, job.salary_max), (60000, 75000))
        self.assertEqual(job.currency, "USD")
        self.assertTrue(job.remote)
        self.assertIn("logistics", job.tags)


class BoardSpecTests(unittest.TestCase):
    def test_accepts_provider_slugs_urls_and_bare_slugs(self):
        for spec, expected in (("greenhouse:careem", ("greenhouse", "careem")),
                               ("jobs.lever.co/kitopi", ("lever", "kitopi")),
                               ("https://jobs.lever.co/kitopi", ("lever", "kitopi")),
                               ("boards.greenhouse.io/careem", ("greenhouse", "careem")),
                               ("jobs.ashbyhq.com/flexport", ("ashby", "flexport")),
                               ("https://api.ashbyhq.com/posting-api/job-board/flexport",
                                ("ashby", "flexport")),
                               ("flexport", ("greenhouse", "flexport"))):
            with self.subTest(spec=spec):
                self.assertEqual(parse_board_spec(spec), expected)

    def test_normalises_and_dedupes(self):
        boards = normalise_boards(["https://boards.greenhouse.io/careem/",
                                   "greenhouse:careem", " JOBS.LEVER.CO/Kitopi ",
                                   "workday:acme"])
        self.assertEqual(boards, ["greenhouse:careem", "lever:kitopi"])

    def test_rejects_unknown_hosts_and_providers(self):
        for spec in ("jobs.workday.com/acme", "example.com/jobs", "greenhouse:", ""):
            with self.subTest(spec=spec), self.assertRaises(BoardError):
                parse_board_spec(spec)

    def test_workday_gets_a_clear_message(self):
        with self.assertRaises(BoardError) as caught:
            parse_board_spec("https://acme.wd3.myworkdayjobs.com/careers")
        self.assertIn("Workday", str(caught.exception))

    def test_display_label(self):
        self.assertEqual(board_display("greenhouse:careem"), "Careem (Greenhouse)")
        self.assertEqual(board_display("jobs.lever.co/kitopi"), "Kitopi (Lever)")


class CompanyBoardsTests(unittest.TestCase):
    def _settings(self, boards=None) -> AppSettings:
        settings = AppSettings()
        settings.enabled_sources = ["company_boards"]
        settings.company_boards = list(boards or DEFAULT_COMPANY_BOARDS)
        return settings

    def test_default_boards_are_valid_and_capped(self):
        parsed = CompanyBoardsSource.boards(self._settings())
        self.assertEqual([f"{provider}:{slug}" for provider, slug in parsed],
                         normalise_boards(DEFAULT_COMPANY_BOARDS))
        with mock.patch("jautomatic.services.company_boards.MAX_BOARDS_PER_SEARCH", 2):
            self.assertEqual(len(CompanyBoardsSource.boards(
                self._settings(["greenhouse:careem", "lever:kitopi", "ashby:flexport"]))), 2)

    def test_greenhouse_parsing(self):
        with mock.patch("jautomatic.services.company_boards._get_json",
                        side_effect=[GREENHOUSE_CAREEM, GREENHOUSE_CAREEM]):
            jobs = CompanyBoardsSource().fetch_with(SearchQuery(text="logistics",
                                                                limit_per_source=10),
                                                    self._settings(["greenhouse:careem"]))
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.company, "Careem")
        self.assertEqual(job.title, "Logistics Manager, Dubai")
        self.assertEqual(job.location, "Dubai, UAE")
        self.assertIn("greenhouse.io/careem/jobs/6301", job.url)

    def test_greenhouse_monthly_salary_is_annualised(self):
        with mock.patch("jautomatic.services.company_boards._get_json",
                        side_effect=[GREENHOUSE_CAREEM, GREENHOUSE_CAREEM]):
            jobs = CompanyBoardsSource().fetch_with(SearchQuery(text="data scientist",
                                                                limit_per_source=10),
                                                    self._settings(["greenhouse:careem"]))
        self.assertEqual((jobs[0].salary_min, jobs[0].salary_max), (30000 * 12, 45000 * 12))
        self.assertEqual(jobs[0].currency, "AED")

    def test_lever_parsing_and_remote(self):
        with mock.patch("jautomatic.services.company_boards._get_json",
                        return_value=LEVER_KITOPI):
            jobs = CompanyBoardsSource().fetch_with(SearchQuery(text="engineer",
                                                                limit_per_source=10),
                                                    self._settings(["lever:kitopi"]))
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual((job.salary_min, job.salary_max, job.currency), (90000, 120000, "USD"))
        self.assertTrue(job.remote)

    def test_ashby_parsing_and_unlisted_skip(self):
        with mock.patch("jautomatic.services.company_boards._get_json", return_value=ASHBY):
            jobs = CompanyBoardsSource().fetch_with(SearchQuery(text="", limit_per_source=10),
                                                    self._settings(["ashby:flexport"]))
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual((job.salary_min, job.salary_max, job.currency), (180000, 240000, "SAR"))
        self.assertEqual(job.location, "Riyadh, Saudi Arabia")

    def test_gulf_location_filters_other_countries(self):
        with mock.patch("jautomatic.services.company_boards._get_json", return_value=ASHBY):
            jobs = CompanyBoardsSource().fetch_with(SearchQuery(text="", location="UAE",
                                                                limit_per_source=10),
                                                    self._settings(["ashby:flexport"]))
        self.assertEqual(jobs, [])

    def test_a_dead_board_is_skipped_inside_the_source(self):
        def fake(url, timeout, params=None):  # noqa: ANN001
            if "greenhouse" in url:
                raise requests.ConnectionError("blocked")
            return LEVER_KITOPI

        with mock.patch("jautomatic.services.company_boards._get_json",
                        side_effect=lambda url, timeout, params=None: fake(url, timeout, params)):
            jobs = CompanyBoardsSource().fetch_with(SearchQuery(text="", limit_per_source=10),
                                                    self._settings(["greenhouse:careem",
                                                                    "lever:kitopi"]))
        self.assertEqual(sorted(job.title for job in jobs),
                         ["Backend Engineer", "Warehouse Operations Lead"])

    def test_all_boards_failing_names_the_dead_boards(self):
        with mock.patch("jautomatic.services.company_boards._get_json",
                        side_effect=requests.ConnectionError("blocked")):
            with self.assertRaises(requests.RequestException) as caught:
                CompanyBoardsSource().fetch_with(SearchQuery(text="", limit_per_source=10),
                                                 self._settings(["greenhouse:careem",
                                                                 "lever:kitopi"]))
        message = str(caught.exception)
        self.assertIn("no company board responded", message)
        self.assertIn("careem unreachable", message)
        self.assertIn("kitopi unreachable", message)

    def test_a_dead_board_does_not_break_the_rest(self):
        settings = self._settings(["greenhouse:careem", "lever:kitopi"])
        with mock.patch("jautomatic.services.company_boards._get_json",
                        side_effect=lambda url, timeout, params=None: (
                            (_ for _ in ()).throw(requests.ConnectionError("blocked"))
                            if "greenhouse" in url else LEVER_KITOPI)):
            outcome = JobScraper(settings).search(
                SearchQuery(text="engineer", sources=["company_boards"], limit_per_source=10))
        self.assertEqual([job.title for job in outcome.jobs], ["Backend Engineer"])
        self.assertEqual(outcome.results_ok_count, 1)

    def test_search_via_the_shared_scraper_merges_boards(self):
        settings = self._settings(["lever:kitopi", "ashby:flexport"])
        payloads = {"lever": LEVER_KITOPI, "ashby": ASHBY}
        with mock.patch("jautomatic.services.company_boards._get_json",
                        side_effect=lambda url, timeout, params=None:
                            next(payload for key, payload in payloads.items() if key in url)):
            outcome = JobScraper(settings).search(
                SearchQuery(text="", sources=["company_boards"], limit_per_source=10))
        self.assertEqual(len(outcome.jobs), 3)
        self.assertFalse(outcome.errors)


class JoobleGulfTests(unittest.TestCase):
    def _settings(self, **keys) -> AppSettings:
        settings = AppSettings()
        settings.jooble_keys = dict(keys)
        return settings

    def test_each_country_is_its_own_source(self):
        sources = {source.name: source for source in jooble_gulf_sources()}
        self.assertEqual(set(sources), {"jooble_sa", "jooble_qa", "jooble_kw", "jooble_bh"})
        sa = sources["jooble_sa"]
        self.assertEqual(sa.country, "Saudi Arabia")
        self.assertIn("sa.jooble.org", sa.homepage)
        self.assertTrue(sa.needs_credentials)

    def test_legacy_uae_source_keeps_its_name(self):
        source = JoobleUaeSource()
        self.assertEqual(source.name, "jooble_uae")
        self.assertEqual(source.code, "ae")

    def test_key_lookup_per_country(self):
        settings = self._settings(sa="riyadh-key")
        self.assertEqual(jooble_key(settings, "sa"), "riyadh-key")
        self.assertEqual(jooble_key(settings, "ae"), "")
        legacy = AppSettings()
        legacy.jooble_uae_key = "old-uae-key"
        self.assertEqual(jooble_key(legacy, "ae"), "old-uae-key")

    def test_key_lookup_per_country(self):
        settings = self._settings(sa="riyadh-key")
        self.assertEqual(jooble_key(settings, "sa"), "riyadh-key")
        self.assertEqual(jooble_key(settings, "ae"), "")
        legacy = AppSettings()
        legacy.jooble_uae_key = "old-uae-key"
        self.assertEqual(jooble_key(legacy, "ae"), "old-uae-key")

    def test_unconfigured_country_is_skipped(self):
        source = JoobleSource("qa")
        settings = self._settings(sa="riyadh-key")
        self.assertFalse(source.is_configured(settings))
        with self.assertRaises(ValueError):
            source.fetch(SearchQuery())

    def test_requests_go_to_the_right_country_site(self):
        source = JoobleSource("sa")
        posted = {}

        def fake_post(url, json=None, **kwargs):  # noqa: ANN001
            posted["url"], posted["json"] = url, json
            response = mock.Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = {"jobs": []}
            return response

        with mock.patch("jautomatic.services.regional_job_sources.requests.post",
                        side_effect=fake_post):
            source.fetch_with(SearchQuery(text="driver", location="Gulf"),
                              self._settings(sa="riyadh-key"))
        self.assertIn("https://sa.jooble.org/api/riyadh-key", posted["url"])
        self.assertEqual(posted["json"]["location"], "Saudi Arabia")

    def test_gulf_search_reaches_every_gulf_jooble(self):
        settings = self._settings(sa="key-sa", qa="key-qa", kw="key-kw", bh="key-bh")
        reached = []

        def fake_post(url, json=None, **kwargs):  # noqa: ANN001
            reached.append(url)
            response = mock.Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = {"jobs": []}
            return response

        sources = [JoobleUaeSource(), *jooble_gulf_sources()]
        with mock.patch("jautomatic.services.regional_job_sources.requests.post",
                        side_effect=fake_post):
            for source in sources:
                if source.is_configured(settings):
                    source.fetch_with(SearchQuery(text="driver", location="Gulf",
                                                  limit_per_source=5), settings)
        self.assertEqual(len(reached), 4)
        for url, code in zip(reached, ("sa", "qa", "kw", "bh")):
            self.assertIn(f"jooble.org/api/key-{code}", url)


class BrowserCatalogTests(unittest.TestCase):
    def test_catalog_covers_the_gulf_and_africa(self):
        boards = browser_boards()
        for expected in ("LinkedIn", "Bayt", "GulfTalent", "NaukriGulf", "foundit Gulf",
                         "Indeed", "Dubizzle", "Qatar Living", "BrighterMonday", "Jobberman"):
            self.assertIn(expected, boards)
        self.assertEqual(browser_regions("Bayt"),
                         ["UAE", "Saudi Arabia", "Qatar", "Kuwait", "Oman", "Bahrain"])
        self.assertIn("Dubai", browser_regions("NaukriGulf"))
        self.assertIn("Ghana", browser_regions("Jobberman"))

    def test_region_list_follows_the_board(self):
        self.assertEqual(browser_regions("Nope"), [])
        self.assertEqual(browser_hint("Bayt"), BROWSER_SITES["Bayt"].hint)

    def test_gulf_urls(self):
        for board, region, url in (
                ("Bayt", "Saudi Arabia", "https://www.bayt.com/en/saudi-arabia/jobs/driver-jobs/"),
                ("GulfTalent", "Qatar", "https://www.gulftalent.com/qatar/jobs?keywords=driver"),
                ("NaukriGulf", "Dubai", "https://www.naukrigulf.com/driver-jobs-in-dubai"),
                ("NaukriGulf", "Bahrain", "https://www.naukrigulf.com/driver-jobs-in-bahrain"),
                ("foundit Gulf", "Riyadh", "https://www.founditgulf.com/search/driver-jobs-in-riyadh"),
                ("Indeed", "Kuwait", "https://kw.indeed.com/jobs?q=driver"),
                ("Indeed", "Oman", "https://om.indeed.com/jobs?q=driver"),
                ("Dubizzle", "Abu Dhabi", "https://abudhabi.dubizzle.com/jobs/search/?keywords=driver"),
                ("Qatar Living", "Qatar", "https://www.qatarliving.com/jobs?keys=driver")):
            with self.subTest(board=board, region=region):
                self.assertEqual(regional_search_url(board, "driver", region=region), url)

    def test_africa_urls_unchanged(self):
        self.assertEqual(regional_search_url("BrighterMonday", "driver", region="Kenya"),
                         "https://www.brightermonday.co.ke/jobs?q=driver")
        self.assertEqual(regional_search_url("BrighterMonday", "driver", region="Tanzania"),
                         "https://www.brightermonday.co.tz/jobs?q=driver")
        self.assertEqual(regional_search_url("Jobberman", "driver", region="Ghana"),
                         "https://www.jobberman.com.gh/jobs?q=driver")
        self.assertIn("location=Africa", regional_search_url("LinkedIn", "driver", region="Africa"))
        self.assertIn("location=United+Arab+Emirates",
                      regional_search_url("LinkedIn", "driver", region="UAE"))

    def test_legacy_combined_labels_still_resolve(self):
        self.assertEqual(regional_search_url("Bayt UAE", "driver"),
                         "https://www.bayt.com/en/uae/jobs/driver-jobs/")
        self.assertEqual(regional_search_url("GulfTalent UAE", "driver"),
                         "https://www.gulftalent.com/uae/jobs?keywords=driver")
        self.assertEqual(regional_search_url("BrighterMonday Kenya", "driver"),
                         "https://www.brightermonday.co.ke/jobs?q=driver")
        self.assertEqual(regional_search_url("Jobberman Nigeria", "driver"),
                         "https://www.jobberman.com/jobs?q=driver")

    def test_unknown_board_raises(self):
        with self.assertRaises(ValueError):
            regional_search_url("Nope", "driver")


class SettingsMigrationTests(unittest.TestCase):
    def test_v2_default_expands_with_the_new_boards(self):
        settings = AppSettings.from_dict({"enabled_sources": SOURCE_NAMES_V2})
        self.assertEqual(settings.enabled_sources, DEFAULT_SOURCE_NAMES)
        self.assertIn("jobicy", settings.enabled_sources)
        self.assertIn("company_boards", settings.enabled_sources)

    def test_v1_default_expands_too(self):
        settings = AppSettings.from_dict({"enabled_sources": ["remotive", "arbeitnow",
                                                             "remoteok"]})
        self.assertEqual(settings.enabled_sources, DEFAULT_SOURCE_NAMES)

    def test_custom_selection_is_preserved(self):
        settings = AppSettings.from_dict({"enabled_sources": ["sample", "jooble_sa"]})
        self.assertEqual(settings.enabled_sources, ["sample", "jooble_sa"])

    def test_uae_key_moves_into_the_country_map(self):
        settings = AppSettings.from_dict({"jooble_uae_key": "legacy"})
        self.assertEqual(settings.jooble_keys.get("ae"), "legacy")
        self.assertEqual(settings.jooble_uae_key, "")

    def test_gulf_keys_round_trip(self):
        settings = AppSettings.from_dict({"jooble_keys": {"sa": "a", "qa": "b", "xx": ""}})
        self.assertEqual(settings.jooble_keys, {"sa": "a", "qa": "b"})
        exported = settings.to_dict()
        self.assertEqual(AppSettings.from_dict(exported).jooble_keys, {"sa": "a", "qa": "b"})

    def test_company_boards_round_trip_and_defaults(self):
        settings = AppSettings()
        self.assertEqual(settings.company_boards, [])     # empty = the built-in list
        stored = AppSettings.from_dict({"company_boards":
                                        ["greenhouse:careem", "  ", "greenhouse:careem"]})
        self.assertEqual(stored.company_boards, ["greenhouse:careem"])

    def test_gulf_preset_sources_exist_and_are_key_free(self):
        scraper_sources = {"jobicy", "workingnomads", "company_boards", "uae_ai",
                           "remotive", "arbeitnow", "remoteok", "himalayas"}
        self.assertEqual(set(GULF_PRESET_SOURCE_NAMES), scraper_sources)


class DefaultCatalogTests(unittest.TestCase):
    def test_every_default_source_is_registered(self):
        from jautomatic.services.job_scraper import default_sources
        names = [source.name for source in default_sources()]
        self.assertEqual(len(names), len(set(names)))
        for expected in ("remotive", "arbeitnow", "remoteok", "himalayas", "jobicy",
                         "workingnomads", "uae_ai", "company_boards", "myjobmag_ke",
                         "jobweb_ke", "jooble_uae", "jooble_sa", "jooble_qa", "jooble_kw",
                         "jooble_bh", "adzuna", "sample"):
            self.assertIn(expected, names)

    def test_regional_feed_sources_are_unchanged(self):
        names = [source.name for source in regional_sources()]
        self.assertEqual(names, ["myjobmag_ke", "myjobmag_ng", "myjobmag_za",
                                 "jobweb_ke", "jobweb_ug", "jobweb_tz"])

    def test_source_labels_are_known(self):
        from jautomatic.models import source_label
        self.assertEqual(source_label("jooble_sa"), "Jooble Saudi Arabia")
        self.assertEqual(source_label("company_boards"), "the company's career page")
        # Anything unlabelled still falls back to a readable title.
        self.assertEqual(source_label("weird_source"), "Weird Source")


class GulfPresetSearchTests(unittest.TestCase):
    def test_gulf_preset_search_reaches_the_new_sources(self):
        """A Gulf search fans out over the key-free Gulf sources and filters locations."""
        settings = AppSettings(enabled_sources=list(GULF_PRESET_SOURCE_NAMES))
        payloads = {
            "himalayas.app": {"jobs": []},
            "jobicy.com": JOBICY,
            "workingnomads.com": WORKINGNOMADS,
            "artificial.ae": {"data": []},
            "remotive.com": {"jobs": []},
            "arbeitnow.com": {"data": []},
            "remoteok.com": [],
        }

        def fake(url, timeout, params=None):  # noqa: ANN001
            for suffix, payload in payloads.items():
                if suffix in url:
                    return payload
            raise AssertionError(f"unexpected url {url}")

        with mock.patch.object(job_scraper, "_request_json", side_effect=fake), \
                mock.patch("jautomatic.services.company_boards._get_json",
                           side_effect=lambda url, timeout, params=None: GREENHOUSE_CAREEM):
            outcome = JobScraper(settings).search(
                SearchQuery(text="logistics", location="Gulf; UAE", limit_per_source=10))
        ok = {result.source for result in outcome.results if result.ok}
        self.assertIn("jobicy", ok)
        self.assertIn("workingnomads", ok)
        self.assertIn("company_boards", ok)
        self.assertFalse(outcome.used_fallback)
        titles = [job.title for job in outcome.jobs]
        self.assertIn("Staff Product Manager", titles)          # Jobicy, UAE geo
        self.assertIn("Logistics Manager, Dubai", titles)       # Greenhouse, Dubai


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
