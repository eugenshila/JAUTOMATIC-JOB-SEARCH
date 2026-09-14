# Verified job-source access

The assistant separates **a source preference** from **permission to query a source**. A checkbox in Find Jobs never authorizes scraping. Automated search only uses a user-supplied official API, approved partner feed, or permitted public RSS/XML/JSON endpoint.

## What is configured in the application

- The source catalog contains the official documentation/manual URLs and an access-policy note for each requested site.
- The generic connector accepts `Source name | URL` lines in **Find Jobs → Approved public RSS/XML or JSON feed URLs**.
- Plain URLs are still accepted, but are labelled `Public API / RSS feed`.
- No scraper, Apify actor, SERP endpoint, placeholder URL, or login-walled page has been added as an automated feed.
- The application opens an official manual job page when an automated route is unavailable; it does not bypass CAPTCHA, anti-bot controls, or access restrictions.

## Site-by-site findings

| Site | Verified official automated route | Configuration decision |
|---|---|---|
| LinkedIn | No open public read/search jobs API was verified. Official access is partner/integration controlled. [LinkedIn developer portal](https://developer.linkedin.com/) | Catalogued for manual browsing; no fake feed URL added. |
| Indeed | No open self-service read/search API was verified. Official integrations are partner/employer-side. [Indeed documentation](https://docs.indeed.com/) | Catalogued for manual browsing; no fake feed URL added. |
| Glassdoor | No open public jobs search API was verified. | Catalogued for manual browsing; no scraper endpoint added. |
| Google Jobs | Google for Jobs is a publisher/structured-data feature, not a general read API. [JobPosting documentation](https://developers.google.com/search/docs/appearance/structured-data/job-posting) | The Google jobs search page is manual-only; it is not put in the RSS/JSON feed box. |
| BrighterMonday | The reachable `/discover/feed` endpoint is an editorial career-advice feed, not a vacancy feed. | Deliberately excluded from automated defaults. Official jobs page is manual-only until a vacancy feed/API and permission are verified. |
| MyJobMag | MyJobMag publishes an official feeds page with summarized/detailed/aggregate feed options. [MyJobMag feeds](https://www.myjobmag.co.ke/feeds/) | The feeds page is recorded in the catalog. The actual copy-target URLs were not exposed by the inspected page, so no unverified URL is prefilled. |
| Fuzu | No verified official public vacancy API/feed was found during this review. | Manual-only until an official route is supplied. |
| Bayt | No verified official public vacancy API/feed was found during this review. | Manual-only until an official route is supplied. |
| GulfTalent | No verified official public vacancy API/feed was found during this review. | Manual-only until an official route is supplied. |
| Naukrigulf | No verified official public vacancy API/feed was found during this review. | Manual-only until an official route is supplied. |
| Adzuna | Official job-search API is available, but requires an application ID and application key. [Adzuna search](https://developer.adzuna.com/docs/search) | Not enabled without the user's credentials and review of the provider's terms/limits. Credentials must not be committed or placed in a URL. |

## Public ATS APIs that can be used per company

These are useful for employers whose career pages use the named ATS. They are **not global job-board searches**: each request requires a known company board/slug/identifier.

- **Greenhouse Job Board API:** `https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs` (public, read-only, per company). [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html)
- **Lever Postings API:** `https://api.lever.co/v0/postings/{company_slug}?mode=json` (public, per company). [Lever developer documentation](https://hire.lever.co/developer/documentation)
- **SmartRecruiters public postings:** `https://api.smartrecruiters.com/v1/companies/{company_id}/postings` (public only where the customer has enabled it, per company). [SmartRecruiters developer portal](https://dev.smartrecruiters.com/)

The current feed connector can consume a public JSON response from one of these endpoints after the user has confirmed the company board and the provider permits this use. The `{...}` values are intentionally not placed in the application as placeholders because a placeholder is not a valid feed.

## Why third-party job APIs are not defaults

Apify actors, SERP APIs, commercial job-data vendors, and scraper APIs may require paid accounts/tokens and may collect pages under terms that differ from the original site. They are not silently treated as official sources. A future provider connector must have explicit credentials, terms review, secure credential storage, and a clear user opt-in.
