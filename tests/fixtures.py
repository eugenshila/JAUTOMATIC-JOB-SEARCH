"""Realistic, trimmed-down job-board payloads used by the scraper tests.

Shapes mirror the live endpoints (Remotive / Arbeitnow / RemoteOK / Adzuna) so
the parsers are exercised against production-like data without touching the
network.
"""
from __future__ import annotations

REMOTIVE = {
    "0-legal-notice": "© Remotive",
    "job-count": 2,
    "jobs": [
        {
            "id": 1900011,
            "url": "https://remotive.com/remote-jobs/software-dev/senior-python-engineer-1900011",
            "title": "Senior Python Engineer",
            "company_name": "Northwind Analytics",
            "category": "Software Development",
            "candidate_required_location": "Europe, UK",
            "salary": "$90,000 - $120,000",
            "publication_date": "2026-09-09T08:12:44",
            "tags": ["python", "fastapi", "postgresql", "aws"],
            "description": "<p>We are hiring a <strong>Senior Python Engineer</strong> to own our "
                           "data platform.</p><ul><li>FastAPI + PostgreSQL</li>"
                           "<li>Docker &amp; AWS</li></ul>",
        },
        {
            "id": 1900012,
            "url": "https://remotive.com/remote-jobs/design/product-designer-1900012",
            "title": "Product Designer",
            "company_name": "Bluebird Studio",
            "candidate_required_location": "Worldwide",
            "salary": "",
            "publication_date": "2026-09-01T10:00:00",
            "tags": ["figma", "design systems"],
            "description": "<p>Design beautiful product surfaces.</p>",
        },
    ],
}

ARBEITNOW = {
    "data": [
        {
            "slug": "backend-engineer-go-berlin",
            "company_name": "Kestrel Logistics",
            "title": "Backend Engineer (Go)",
            "description": "<p>Real-time shipment tracking. Go, gRPC, Kubernetes, PostgreSQL. "
                           "Remote-friendly within the EU.</p>",
            "remote": True,
            "url": "https://www.arbeitnow.com/jobs/companies/kestrel-logistics-backend-engineer-go",
            "tags": ["golang", "grpc", "kubernetes"],
            "job_types": ["full-time"],
            "location": "Berlin",
            "created_at": 1789000000,
        },
        {
            "slug": "accountant-munich",
            "company_name": "Meridian Retail",
            "title": "Accountant",
            "description": "<p>Monthly closing, SAP, German GAAP.</p>",
            "remote": False,
            "url": "https://www.arbeitnow.com/jobs/companies/meridian-retail-accountant",
            "tags": ["finance"],
            "job_types": ["full-time"],
            "location": "Munich",
            "created_at": 1788500000,
        },
    ],
}

REMOTEOK = [
    {"legal": "API terms of service"},
    {
        "id": "900001",
        "position": "Machine Learning Engineer, NLP",
        "company": "Lingua Labs",
        "description": "<p>Fine-tune transformers, own evaluation and serving.</p>",
        "location": "Worldwide",
        "tags": ["ml", "nlp", "pytorch"],
        "salary_min": 90000,
        "salary_max": 125000,
        "date": "2026-09-12T08:00:00+00:00",
        "url": "https://remoteok.com/remote-jobs/900001",
    },
    {"legal": ""},  # RemoteOK includes an empty-ish entry that must be skipped
]

ADZUNA = {
    "results": [
        {
            "id": "55001",
            "title": "Data Engineer",
            "company": {"display_name": "Helio Health"},
            "location": {"display_name": "Amsterdam, Netherlands"},
            "description": "Airflow, dbt, Snowflake pipelines. Hybrid role with 2 days in office.",
            "salary_min": 65000.0,
            "salary_max": 82000.0,
            "created": "2026-09-05T06:30:00Z",
            "redirect_url": "https://www.adzuna.co.uk/details/55001",
        }
    ]
}

REMOTIVE_PAYLOADS = {"remotive": REMOTIVE, "arbeitnow": ARBEITNOW, "remoteok": REMOTEOK}
