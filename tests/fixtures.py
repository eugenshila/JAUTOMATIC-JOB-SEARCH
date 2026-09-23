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


JOBICY = {
    "apiVersion": "2.2.16",
    "jobCount": 2,
    "jobs": [
        {
            "id": 153918,
            "url": "https://jobicy.com/jobs/153918-staff-product-manager",
            "jobTitle": "Staff Product Manager",
            "companyName": "Wheel",
            "jobIndustry": ["Product & Operations"],
            "jobType": ["Full-Time"],
            "jobGeo": "United Arab Emirates",
            "jobLevel": "Director",
            "jobExcerpt": "Own the roadmap for patient experience.",
            "jobDescription": "<p>Own the roadmap. Logistics for a virtual care platform.</p>",
            "pubDate": "2026-09-20T12:00:00+00:00",
            "salaryMin": 4000,
            "salaryMax": 5000,
            "salaryCurrency": "AED",
            "salaryPeriod": "monthly",
        },
        {
            "id": 153919,
            "url": "https://jobicy.com/jobs/153919-frontend-engineer",
            "jobTitle": "Frontend Engineer",
            "companyName": "Bluebird",
            "jobIndustry": ["Design"],
            "jobType": ["Full-Time"],
            "jobGeo": "Anywhere",
            "jobLevel": "Senior",
            "jobExcerpt": "React surfaces for a design system.",
            "jobDescription": "<p>Build React interfaces.</p>",
            "pubDate": "2026-09-18T09:00:00+00:00",
            "salaryMin": 90000,
            "salaryMax": 120000,
            "salaryCurrency": "USD",
            "salaryPeriod": "yearly",
        },
    ],
}

WORKINGNOMADS = [
    {
        "url": "https://www.workingnomads.com/job/go/1880339/",
        "title": "Remote Logistics Coordinator",
        "description": "Coordinate freight for a distributed team. Salary: $60,000 - $75,000.",
        "company_name": "Kestrel Logistics",
        "category_name": "Operations",
        "tags": "logistics,freight,coordination",
        "location": "Anywhere in the world",
        "pub_date": "2026-09-21T02:36:00-04:00",
    },
    {
        "url": "https://www.workingnomads.com/job/go/1879612/",
        "title": "Content Reviewer",
        "description": "Rate search results for relevance and quality.",
        "company_name": "TELUS Digital",
        "category_name": "Other",
        "tags": "review,search",
        "location": "United States",
        "pub_date": "2026-09-20T10:00:00-04:00",
    },
]

GREENHOUSE_CAREEM = {
    "name": "Careem",
    "jobs": [
        {
            "id": 6301,
            "title": "Logistics Manager, Dubai",
            "absolute_url": "https://job-boards.greenhouse.io/careem/jobs/6301",
            "location": {"name": "Dubai, UAE"},
            "departments": [{"name": "Operations"}],
            "content": "<p>Own bus and delivery logistics for the Dubai market.</p>",
            "updated_at": "2026-09-19T10:00:00+02:00",
        },
        {
            "id": 6302,
            "title": "Data Scientist",
            "absolute_url": "https://job-boards.greenhouse.io/careem/jobs/6302",
            "location": {"name": "Remote (EMEA)"},
            "departments": [{"name": "Data"}],
            "content": "<p>Model pricing and ETA. Salary: AED 30,000 - 45,000 monthly.</p>",
            "updated_at": "2026-09-18T08:00:00+02:00",
        },
    ],
}

LEVER_KITOPI = [
    {
        "id": "f47ac10b",
        "text": "Warehouse Operations Lead",
        "hostedUrl": "https://jobs.lever.co/kitopi/f47ac10b",
        "applyUrl": "https://jobs.lever.co/kitopi/f47ac10b/apply",
        "createdAt": 1789300000000,
        "country": "AE",
        "workplaceType": "onsite",
        "categories": {"location": "Dubai, UAE", "team": "Operations",
                       "department": "Supply Chain"},
        "descriptionPlain": "Run cloud-kitchen warehouse operations. Pay AED 25,000 - 35,000.",
    },
    {
        "id": "8c1420de",
        "text": "Backend Engineer",
        "hostedUrl": "https://jobs.lever.co/kitopi/8c1420de",
        "applyUrl": "https://jobs.lever.co/kitopi/8c1420de/apply",
        "createdAt": 1789200000000,
        "country": "AE",
        "workplaceType": "remote",
        "categories": {"location": "Remote", "team": "Engineering"},
        "descriptionPlain": "Build order-flow services. Salary: $90,000 - $120,000.",
        "salaryRange": {"min": 90000, "max": 120000, "currency": "USD"},
    },
]

ASHBY = {
    "apiVersion": "1",
    "jobs": [
        {
            "title": "Freight Pricing Analyst",
            "location": "Riyadh, Saudi Arabia",
            "department": "Operations",
            "team": "Pricing",
            "isListed": True,
            "isRemote": False,
            "workplaceType": "OnSite",
            "descriptionPlain": "Price lanes across the Gulf corridor.",
            "publishedAt": "2026-09-15T08:00:00.000+00:00",
            "employmentType": "FullTime",
            "address": {"postalAddress": {"addressLocality": "Riyadh",
                                          "addressCountry": "Saudi Arabia"}},
            "jobUrl": "https://jobs.ashbyhq.com/flexport/freight-pricing-analyst",
            "applyUrl": "https://jobs.ashbyhq.com/flexport/freight-pricing-analyst/apply",
            "compensation": {
                "summaryComponents": [
                    {"compensationType": "Salary", "interval": "1 YEAR",
                     "currencyCode": "SAR", "minValue": 180000, "maxValue": 240000},
                ],
            },
        },
        {
            "title": "Unlisted Confidential Role",
            "location": "Dubai",
            "isListed": False,
            "isRemote": False,
            "workplaceType": "OnSite",
            "descriptionPlain": "Direct-link only.",
            "jobUrl": "https://jobs.ashbyhq.com/flexport/confidential",
        },
    ],
}
