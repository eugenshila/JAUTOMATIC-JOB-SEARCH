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

HIMALAYAS = {
    "totalCount": 2,
    "jobs": [
        {
            "title": "Machine Learning Engineer",
            "excerpt": "Build and deploy ML models for global payments.",
            "companyName": "Paystack Kenya",
            "companySlug": "paystack-kenya",
            "companyLogo": "",
            "employmentType": "Full Time",
            "minSalary": 45000,
            "maxSalary": 65000,
            "salaryPeriod": "annual",
            "seniority": ["Senior"],
            "currency": "USD",
            "locationRestrictions": ["Kenya"],
            "timezoneRestrictions": [3],
            "categories": ["Machine-Learning", "Python", "Payments"],
            "parentCategories": ["Engineering"],
            "description": "<p>Build and deploy <strong>ML models</strong> for global payments.</p>",
            "pubDate": 1789430400,
            "expiryDate": 1794739200,
            "applicationLink": "https://himalayas.app/companies/paystack-kenya/jobs/ml-engineer",
            "guid": "https://himalayas.app/companies/paystack-kenya/jobs/ml-engineer",
        },
        {
            "title": "Backend Engineer (Remote, UAE)",
            "excerpt": "Join our Dubai team remotely.",
            "companyName": "Dataloop",
            "companySlug": "dataloop",
            "companyLogo": "",
            "employmentType": "Full Time",
            "minSalary": 12000,
            "maxSalary": 15000,
            "salaryPeriod": "monthly",
            "seniority": ["Mid-level"],
            "currency": "AED",
            "locationRestrictions": [],
            "timezoneRestrictions": [4],
            "categories": ["Backend", "Go", "Kubernetes"],
            "parentCategories": ["Engineering"],
            "description": "<p>Join our Dubai team remotely.</p>",
            "pubDate": 1789344000,
            "expiryDate": 1794652800,
            "applicationLink": "https://himalayas.app/companies/dataloop/jobs/backend-engineer",
            "guid": "https://himalayas.app/companies/dataloop/jobs/backend-engineer",
        },
    ],
}

UAEAI = {
    "data": [
        {
            "slug": "emirates-senior-ai-engineer-dubai",
            "title": "Senior AI Engineer",
            "company": "Emirates",
            "emirate": "dubai",
            "role": "ml",
            "url": "https://ae.linkedin.com/jobs/view/senior-ai-engineer-emirates",
            "source": "linkedin",
            "posted_ts": 1789344000,
            "canonical": "https://artificial.ae/jobs/emirates-senior-ai-engineer-dubai/",
        },
        {
            "slug": "miral-data-scientist-abu-dhabi",
            "title": "Data Scientist – AI",
            "company": "Miral Destinations",
            "emirate": "abu dhabi",
            "role": "data",
            "url": "https://ae.linkedin.com/jobs/view/data-scientist-ai-miral",
            "source": "linkedin",
            "posted_ts": 1789257600,
            "canonical": "https://artificial.ae/jobs/miral-data-scientist-abu-dhabi/",
        },
    ],
    "meta": {"count": 2, "total": 772, "limit": 50, "offset": 0, "has_more": True},
}
