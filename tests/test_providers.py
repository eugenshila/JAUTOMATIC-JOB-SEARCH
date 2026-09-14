"""Provider parsing tests against trimmed real API payloads."""

import pytest

from conftest import FakeClient, load_fixture

from jauto.providers import (
    AshbyProvider,
    GreenhouseProvider,
    LeverProvider,
    SmartRecruitersProvider,
    WorkableProvider,
    build_providers,
    detect_from_url,
)


def test_greenhouse_fetch_and_detail(fake_client):
    fake_client.add(
        "GET",
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        load_fixture("greenhouse_jobs"),
    )
    fake_client.add(
        "GET",
        lambda u, p, d: "/jobs/900001" in u,
        load_fixture("greenhouse_job_900001"),
    )
    provider = GreenhouseProvider(fake_client)
    jobs = provider.fetch_jobs("acme")
    assert len(jobs) == 3
    job = jobs[0]
    assert job.title == "Software Engineer, Backend"
    assert job.company == "Acme Corp"
    assert job.provider_job_id == "900001"
    assert job.remote is True
    assert job.url == "https://job-boards.greenhouse.io/acme/jobs/900001"
    assert job.published_at is not None

    detailed = provider.get_job_detail(job)
    assert "Python" in detailed.description_text
    assert detailed.salary_min == 800000.0
    assert detailed.salary_max == 1200000.0
    assert detailed.currency == "USD"


def test_greenhouse_application_spec(fake_client):
    fake_client.add(
        "GET",
        lambda u, p, d: "/jobs/900001" in u,
        load_fixture("greenhouse_job_900001"),
    )
    provider = GreenhouseProvider(fake_client)
    from jauto.models import Job

    spec = provider.get_application_spec(
        Job(provider="greenhouse", provider_board="acme", provider_job_id="900001",
            company="Acme", title="x")
    )
    assert spec is not None
    names = {q.name for q in spec.questions}
    assert {"first_name", "last_name", "email", "resume", "question_5555"} <= names
    select = next(q for q in spec.questions if q.name == "question_3333")
    assert select.type == "single_select"
    assert select.options == [(1, "Yes"), (0, "No")]
    assert select.required is True
    assert spec.requires_gdpr_consent is False  # fixture has consent flags false


def test_greenhouse_gdpr_flag(fake_client):
    fake_client.add(
        "GET",
        lambda u, p, d: "/jobs/900003" in u,
        load_fixture("greenhouse_job_900003"),
    )
    provider = GreenhouseProvider(fake_client)
    from jauto.models import Job

    spec = provider.get_application_spec(
        Job(provider="greenhouse", provider_board="acme", provider_job_id="900003",
            company="Acme", title="x")
    )
    assert spec.requires_gdpr_consent is True


def test_lever_fetch(fake_client):
    fake_client.add(
        "GET", "https://api.lever.co/v0/postings/leverdemo",
        load_fixture("lever_postings"),
    )
    provider = LeverProvider(fake_client, apply_key="k")
    jobs = provider.fetch_jobs("leverdemo")
    assert len(jobs) == 2
    engineer = jobs[0]
    assert engineer.title == "Software Engineer"
    assert engineer.company == "Leverdemo"
    assert engineer.remote is True
    assert engineer.published_at == "2025-10-09T08:53:20Z"
    assert "Requirements" in engineer.description_text
    assert "Python" in engineer.description_text
    assert engineer.apply_url.endswith("/apply")


def test_lever_apply_requires_key(fake_client):
    without_key = LeverProvider(fake_client)
    assert without_key.apply_supported is False
    with_key = LeverProvider(fake_client, apply_key="secret")
    assert with_key.apply_supported is True


def test_ashby_fetch(fake_client):
    fake_client.add(
        "GET", "https://api.ashbyhq.com/posting-api/job-board/ashby",
        load_fixture("ashby_jobs"),
    )
    provider = AshbyProvider(fake_client)
    jobs = provider.fetch_jobs("ashby")
    assert len(jobs) == 2
    engineer = jobs[0]
    assert engineer.title == "Software Engineer, Platform"
    assert engineer.company == "Ashby"
    assert engineer.remote is True
    assert engineer.apply_url.endswith("/application")
    assert "Python" in engineer.description_text


def test_smartrecruiters_fetch(fake_client):
    fake_client.add(
        "GET",
        lambda u, p, d: "smartrecruiters.com/v1/companies/Visa/postings" in u,
        load_fixture("smartrecruiters_postings"),
    )
    provider = SmartRecruitersProvider(fake_client)
    jobs = provider.fetch_jobs("Visa")
    assert len(jobs) == 2
    engineer = jobs[0]
    assert engineer.title == "Software Engineer"
    assert engineer.company == "Example Ltd"
    assert engineer.location == "Nairobi, Kenya"
    assert engineer.url == "https://careers.smartrecruiters.com/Visa/SR-001"
    assert engineer.remote is False


def test_workable_fetch(fake_client):
    fake_client.add(
        "GET",
        "https://apply.workable.com/api/v1/widget/accounts/example",
        load_fixture("workable_jobs"),
    )
    provider = WorkableProvider(fake_client)
    jobs = provider.fetch_jobs("example")
    assert len(jobs) == 2
    engineer = jobs[0]
    assert engineer.company == "Example Co"
    assert engineer.title == "Backend Engineer"
    assert engineer.remote is True
    assert "Docker" in engineer.description_text


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://boards.greenhouse.io/acme", ("greenhouse", "acme")),
        ("https://job-boards.greenhouse.io/acme/jobs/12345", ("greenhouse", "acme")),
        ("https://jobs.lever.co/acme/abc-123", ("lever", "acme")),
        ("https://jobs.ashbyhq.com/acme/xyz", ("ashby", "acme")),
        ("https://careers.smartrecruiters.com/Visa", ("smartrecruiters", "Visa")),
        ("https://acme.workable.com/j/ABC123", ("workable", "acme")),
        ("https://apply.workable.com/acme/j/ABC123", ("workable", "acme")),
    ],
)
def test_detect_from_url(url, expected):
    assert detect_from_url(url) == expected


def test_detect_from_url_unknown():
    assert detect_from_url("https://example.com/careers") is None
    assert detect_from_url("") is None


def test_build_providers_registry(fake_client):
    providers = build_providers(fake_client, lever_apply_key="x")
    assert set(providers) == {"greenhouse", "lever", "ashby", "smartrecruiters", "workable"}
    assert providers["greenhouse"].apply_supported is True
    assert providers["ashby"].apply_supported is False
