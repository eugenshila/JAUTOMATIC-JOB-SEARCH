# JAUTOMATIC-JOB-SEARCH (`jauto`)

An automatic job-search **and** job-application bot for ATS-backed career pages.
It tracks company boards on five major ATS platforms, scores every opening
against your profile, and can fill in and submit applications for you — with a
safety model that keeps you in control of what actually gets sent.

```
      ┌────────────┐   fetch    ┌─────────────┐   score   ┌──────────────┐
      │ ATS boards │ ─────────► │  SQLite DB  │ ◄──────── │    Matcher   │
      └────────────┘            └─────────────┘           └──────────────┘
       Greenhouse                   ▲    │                     ▲
       Lever                        │    │ apply               │ your profile
       Ashby                        │    ▼                     │ (config.yaml)
       SmartRecruiters          ┌──────────────┐               │
       Workable                 │   Applier    │ ──────────────┘
                                └──────────────┘
                                  dry-run first,
                                  submit only with --yes
```

## What it can do

| Provider | Fetch jobs | Score & track | Auto-apply |
|---|---|---|---|
| **Greenhouse** | ✅ | ✅ | ✅ full (custom questions, options, resume upload, cover letter) |
| **Lever** | ✅ | ✅ | ⚠️ experimental (name/email/phone/resume; needs an apply key) |
| **Ashby** | ✅ | ✅ | 🔗 link only (web flow) |
| **SmartRecruiters** | ✅ | ✅ | 🔗 link only (partner OAuth required) |
| **Workable** | ✅ | ✅ | 🔗 link only (web flow) |

All five providers use the **public JSON endpoints** that power the companies'
own career pages — no scraping of HTML, no browser automation, no accounts
required.

## Quick start

```bash
pip install -e .          # or: pipx install .

jauto init                # creates config.yaml + cover_letter_template.txt

# fill in your profile in config.yaml, then:
jauto add https://boards.greenhouse.io/twilio
jauto add https://jobs.lever.co/leverdemo
jauto add https://jobs.ashbyhq.com/ashby

jauto search              # fetch, score and list the best matches
jauto show 17             # full detail + score breakdown for a job
jauto apply 17            # PREVIEW the application (dry run, always safe)
jauto apply 17 --yes      # actually submit it
jauto apply --auto        # preview applications for every match above apply.min_score
jauto apply --auto --yes  # submit them (respects max_per_run / daily_limit)
jauto status              # pipeline overview + application history
```

## How matching works

Every job gets a 0–100 score from four weighted components (tunable in
`matching.weights`):

| Component | Default weight | Notes |
|---|---|---|
| `title` | 35 | best overlap between your `titles` phrases and the job title |
| `skills` | 35 | fraction of your `skills` found in the posting |
| `location` | 20 | remote handling + `locations` allow-list |
| `freshness` | 10 | full points ≤ 7 days old, linear decay to a floor at 35 days |

Hard rules (a job is **excluded** regardless of score):

- any `exclude_titles` term in the title (e.g. `senior`, `manager`)
- company in `company_blacklist`
- `remote_only: true` and the job is neither remote nor in `locations`

Jobs scoring ≥ `matching.threshold` are marked `matched`; the rest `skipped`.
Run `jauto show <ID>` on any job to see the full score breakdown.

## How auto-apply works (and stays safe)

1. `jauto apply <ID>` builds the application from the job's real form schema
   (Greenhouse exposes it via their API) and **previews every field** — nothing
   is sent without `--yes` (or `apply.auto_submit: true` for `jauto run`).
2. Answers are resolved in this order: standard profile fields → `apply.answers`
   (matched by question label) → `profile.links` (LinkedIn/GitHub questions) →
   `apply.eeo_answers` (EEO/demographic questions). Select questions are mapped
   to the matching option value.
3. **Required questions that can't be answered are never guessed.** The job is
   marked `needs_review` with a list of what's missing, and you apply to it by
   hand (`jauto show <ID>` prints the direct link).
4. Submissions are **never retried** (a retry could double-apply you), are
   spaced by `apply.submit_delay`, and are capped by `apply.max_per_run` and
   `apply.daily_limit`.
5. GDPR consent questions are only auto-answered if you set
   `apply.consent_gdpr: true` — and only if you actually consent.

### Custom question answers

Boards ask custom questions ("How many years of experience…", "Are you
authorized to work…"). Configure them once in `config.yaml`:

```yaml
apply:
  answers:
    "How many years of experience do you have?": "3"
    "Are you legally authorized to work": "Yes"
    "Will you now or in the future require sponsorship": "Yes"
```

Labels are matched case-insensitively by substring, so a short key like
`"legally authorized"` covers most phrasings.

## Running on a schedule

`jauto run` is the one-shot entry point: search every board, then auto-apply
**only if** `apply.auto_submit: true` (or `--yes` is passed).

```cron
# Every weekday at 08:30 — search + auto-apply (if auto_submit: true)
30 8 * * 1-5  cd /path/to/dir && jauto run >> jauto.log 2>&1
```

Keep `network.request_delay` ≥ 1s (the default) — these are the same endpoints
company career pages use, and politeness keeps them working for everyone.

## Configuration

See [`config.example.yaml`](config.example.yaml) for a fully annotated example.
Highlights:

| Section | Purpose |
|---|---|
| `sources` | boards to track, per provider (managed by `jauto add`) |
| `profile` | your identity, resume files, links, cover-letter template |
| `matching` | titles, skills, exclusions, locations, threshold, weights |
| `apply` | answer bank, limits, delays, consent settings |
| `network` | rate limiting, retries, User-Agent contact email |

Paths are resolved relative to the config file. `jauto check [--online]`
validates everything and can ping each board.

`config.yaml`, the database (`jauto.db`), your resume and cover letters are
**gitignored on purpose** — they're personal data. Only commit
`config.example.yaml`.

## Cover letters

`profile.cover_letter_template` is rendered per job with `{company}`, `{title}`,
`{location}`, `{name}`, `{skills}` placeholders and submitted wherever the form
accepts text (Greenhouse `cover_letter_text`), or attached as a file if you
configure `profile.cover_letter_path` instead.

## Extending with a new provider

1. Create `src/jauto/providers/<name>.py` implementing `fetch_jobs()` (see
   `ashby.py` for the smallest example, `greenhouse.py` for the full one with
   apply support).
2. Register it in `PROVIDER_CLASSES` and add its URL pattern to
   `detect_from_url()` in `src/jauto/providers/__init__.py`.
3. Add a fixture in `tests/fixtures/` and tests in `tests/test_providers.py`.

## Development

```bash
pip install -e ".[dev]"
pytest                  # 75 offline tests — no network needed
```

The test suite runs entirely offline against fixtures captured from the real
APIs, including an end-to-end CLI test that verifies applications POST exactly
once with the right form fields.

## Notes & disclaimer

- Job boards' terms of service may restrict automated submissions — you are
  responsible for how you use this tool against each board.
- Applications submitted for you are real. Use `--yes` deliberately, keep
  `daily_limit` sane, and review `needs_review` items by hand.
- Auto-applied applications are recorded in `jauto.db`; `jauto status` shows
  the history.
