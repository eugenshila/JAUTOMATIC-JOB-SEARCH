"""Shared fixtures: offline HTTP fake, config factory, fixture loader."""

from __future__ import annotations

import json
import os

import pytest
import yaml

from jauto.config import ApplyConfig, Config, MatchingConfig, NetworkConfig, Profile

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name: str):
    if not name.endswith(".json"):
        name = name + ".json"
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text or (json.dumps(json_data) if json_data is not None else "")

    def json(self):
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json


class FakeClient:
    """Offline stand-in for jauto.net.Client.

    Routes are (method, matcher, response) where matcher is
    callable(url, params, data) -> bool, or an exact URL string.
    """

    def __init__(self, *args, **kwargs):
        self.routes = []
        self.requests = []

    def add(self, method: str, matcher, response) -> None:
        if not callable(matcher):
            exact = matcher
            matcher = (lambda u, p, d, _e=exact: u == _e)
        self.routes.append((method, matcher, response))

    def _match(self, method: str, url: str, params=None, data=None):
        self.requests.append(
            {"method": method, "url": url, "params": params, "data": data}
        )
        for route_method, matcher, response in self.routes:
            if route_method != method:
                continue
            if matcher(url, params or {}, data or {}):
                return response
        raise AssertionError(f"no fake route for {method} {url} params={params}")

    # -- jauto.net.Client API ------------------------------------------
    def get_json(self, url, params=None):
        response = self._match("GET", url, params=params)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, FakeResponse):
            return response.json()
        return response

    def post_multipart(self, url, data=None, files=None):
        response = self._match("POST", url, data={"form": data, "files": files})
        if isinstance(response, Exception):
            raise response
        if isinstance(response, FakeResponse):
            return response
        return FakeResponse(200, response)

    def post_urlencoded(self, url, data=None):
        response = self._match("POST", url, data=data)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, FakeResponse):
            return response
        return FakeResponse(200, response)

    @property
    def timeout(self):
        return 5


@pytest.fixture
def fake_client():
    return FakeClient()


def make_config(tmp_path, **overrides) -> Config:
    """Config tuned to the fixture payloads (board 'acme' on greenhouse)."""
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake resume for tests")
    cover = tmp_path / "cover_letter_template.txt"
    cover.write_text(
        "Dear {company} team,\n\nI'd love to join as {title}.\n\n— {name}\n",
        encoding="utf-8",
    )
    config = Config(
        sources=overrides.pop("sources", {"greenhouse": ["acme"]}),
        profile=Profile(
            first_name="Jane",
            last_name="Doe",
            email="jane.doe@example.com",
            phone="+254700000000",
            location="Nairobi, Kenya",
            resume_path="resume.pdf",
            resume_text_path="",
            cover_letter_template="cover_letter_template.txt",
            links={
                "linkedin": "https://www.linkedin.com/in/janedoe",
                "github": "https://github.com/janedoe",
            },
        ),
        matching=MatchingConfig(
            titles=["software engineer", "backend engineer"],
            skills=["python", "aws", "docker"],
            exclude_titles=["senior", "manager", "lead"],
            company_blacklist=[],
            locations=["remote", "nairobi", "kenya"],
            remote_only=False,
            threshold=50.0,
        ),
        apply=ApplyConfig(
            min_score=60.0,
            max_per_run=10,
            daily_limit=15,
            submit_delay=0.0,
            answers={"legally authorized": "Yes"},
        ),
        network=NetworkConfig(request_delay=0.0, contact_email="jane@example.com"),
        db_path="jauto.db",
        base_dir=str(tmp_path),
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def write_config_file(tmp_path) -> str:
    """Write a config.yaml matching make_config() for CLI-level tests."""
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake resume for tests")
    cover = tmp_path / "cover_letter_template.txt"
    cover.write_text(
        "Dear {company} team,\n\nI'd love to join as {title}.\n\n— {name}\n",
        encoding="utf-8",
    )
    data = {
        "sources": {"greenhouse": ["acme"]},
        "profile": {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.doe@example.com",
            "phone": "+254700000000",
            "location": "Nairobi, Kenya",
            "resume_path": "resume.pdf",
            "cover_letter_template": "cover_letter_template.txt",
            "links": {
                "linkedin": "https://www.linkedin.com/in/janedoe",
                "github": "https://github.com/janedoe",
            },
        },
        "matching": {
            "titles": ["software engineer", "backend engineer"],
            "skills": ["python", "aws", "docker"],
            "exclude_titles": ["senior", "manager", "lead"],
            "locations": ["remote", "nairobi", "kenya"],
            "threshold": 50,
        },
        "apply": {
            "min_score": 60,
            "max_per_run": 10,
            "daily_limit": 15,
            "submit_delay": 0,
            "answers": {"legally authorized": "Yes"},
        },
        "network": {"request_delay": 0, "contact_email": "jane@example.com"},
        "db_path": "jauto.db",
    }
    path = tmp_path / "config.yaml"
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
    return str(path)


def route_greenhouse(client: FakeClient) -> None:
    """Wire the standard greenhouse/acme routes used by CLI + pipeline tests."""
    client.add("GET", "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
               load_fixture("greenhouse_jobs"))
    detail_1 = load_fixture("greenhouse_job_900001")
    detail_3 = load_fixture("greenhouse_job_900003")

    def detail_900001(url, params, data):
        return "/jobs/900001" in url

    def detail_900003(url, params, data):
        return "/jobs/900003" in url

    client.add("GET", detail_900001, detail_1)
    client.add("GET", detail_900003, detail_3)
    client.add(
        "POST",
        lambda u, p, d: "/jobs/900001" in u,
        FakeResponse(200, {"status": "ok"}),
    )
    client.add(
        "POST",
        lambda u, p, d: "/jobs/900003" in u,
        FakeResponse(200, {"status": "ok"}),
    )
