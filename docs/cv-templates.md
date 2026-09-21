# CV templates

JAUTOMATIC renders every CV from a template into Markdown, then exports that to
`.docx` / `.pdf` / `.md` / `.txt`. You can pick one of the seven built-in templates or write
your own.

## Built-in templates

The **Portfolio (experience and business projects)** template presents your
profile, stated skills, selected projects, experience and education. It keeps
education completion details and does not add posting keywords as qualifications.
Select it in Settings → Documents. Project records live in `profile.json` under
`extra.projects`, with `name`, `period`, `highlights` (a list) and `url` fields.
Custom templates can also loop over `projects`.

In Profile → Letter settings, **Evidence paragraphs** lets you write the body
of your cover letter in first person. Separate paragraphs with blank lines.
The app adds the job title, employer, greeting, closing and signature. Empty
evidence uses the existing automatic drafting. These paragraphs are saved as
`extra.cover_letter_paragraphs`; opt-in local AI receives this evidence and
education status too. Review each letter for relevance before sending.

After changing your profile or template, regenerate application materials to
update existing documents. Previously generated files do not change on save.
Use profile JSON import/export to preserve projects reliably; Word import is
a best-effort extraction and should always be reviewed.

Word and PDF exports use Segoe UI, a clean Windows sans-serif font, with A4
pages, readable section headings, and consistent spacing. Cover letters use
a matching personal letterhead. Other platforms may substitute a local font.

Choose **Settings → Documents → Export format → PDF + editable Word** to save
both versions in the documents folder. The application tracker opens the PDF
and email drafts name the PDF attachment; the adjacent Word file remains editable.
Choose **PDF (.pdf)** to generate only the PDF. Save settings, then prepare or
regenerate the application's materials to apply the new format. Existing files
are not converted merely by changing the setting.

| Name | Best for | What is different |
|------|----------|-------------------|
| `modern` | most applications (default) | Profile → tailored skills line → experience with impact bullets |
| `classic` | conservative industries, strict ATS parsers | Upper-case section headings, plain text, no Markdown emphasis |
| `compact` | very senior candidates, one-page limits | Everything on one screen; 3 bullets per role |
| `functional` | career changers, gaps, skills-heavy roles | Evidence grouped under the posting's own keywords ("Areas of expertise"), timeline reduced to one line per role |
| `executive` | leadership roles | Quantified achievements first ("Selected achievements"), then roles with scope |
| `technical` | engineering roles | Skills split into *relevant to this role* / *also*; a **Stack** line per role derived from your bullets; a footer stating which posting it was prepared for |
| `portfolio` | operations and practical project experience | Stated skills and digital projects, then experience and education with completion details |

The original six read the same profile and tailor themselves to the posting the same way
(the matched keywords of the job move to the front, bullets that evidence a
posting tag sort first). Nothing is ever invented: a skill only appears if your
profile contains it.

Select the template under **Settings → Documents → CV template** and press
*Preview the selected template* to see it rendered with your own profile.

## User-supplied templates

Drop a `.md` (or `.txt` / `.markdown`) file into the `templates/` folder inside
your data directory:

```
%APPDATA%\JAUTOMATIC\templates\               Windows
~/.local/share/jautomatic-job-search/templates/   Linux / macOS
```

**Settings → Documents** has three helpers: *New custom template* writes an
annotated starter file and opens it in your editor, *Templates folder* opens
the directory, *Reload* re-scans it. Valid files appear in the template
drop-down as *`<file name>` (custom)*; broken ones are listed with the line
number of the problem instead. Custom templates are stored in `settings.json`
as `custom:<file name>`.

If a custom template disappears or stops parsing, the CV is still generated —
with the `modern` template — and the application's history gets a
*template fallback* entry saying why.

### Syntax

The template language is a small, safe subset of Jinja. Nothing in a template
can execute code, call functions or read files.

```
{{ name }}                         value (dotted lookups: {{ job.title }}, {{ role.bullets.0 }})
{% for role in experience %} … {% endfor %}      loop (nestable; loop.index / loop.first / loop.last)
{% if job %} … {% else %} … {% endif %}         condition ({% if not job %} works too)
{# comment #}                      dropped from the output
```

Missing values render as empty text; lists render comma-separated. A block tag
or comment that sits on a line of its own disappears together with its line
break (like Jinja's `trim_blocks` + `lstrip_blocks`), so loops don't leave
blank lines between bullets — put a blank line *inside* the loop when you want
one.

### Variables

| Variable | Type | Notes |
|----------|------|-------|
| `name`, `headline`, `email`, `phone`, `location`, `links` | text | straight from your profile |
| `contact` | text | location · email · phone · links on one line |
| `summary` | text | your summary as written |
| `tailored_summary` | text | summary + "Targeting the … role at …" when a job is known |
| `skills` | list | your skills |
| `skills_line` | text | skills + posting keywords you genuinely cover, comma-separated |
| `languages`, `seniority` | text | |
| `desired_titles` | list | |
| `highlights` | list | your five strongest bullets (numbers first, then posting-keyword hits) |
| `experience` | list | each item: `title`, `company`, `location`, `start`, `end`, `period`, `summary`, `bullets` (list, posting-relevant first), `stack` (list of technologies evidenced by that role) |
| `education` | list | each item: `degree`, `school`, `location`, `start`, `end`, `period`, `details` |
| `today` | text | ISO date |
| `job` | object or empty | `title`, `company`, `location`, `remote`, `salary`, `url`, `tags` (list), `source` — empty when previewing without a posting |
| `match` | object or empty | `score`, `matched_keywords`, `missing_keywords`, `reasons` |

### Example

```
# {{ name }}
{% if headline %}
### {{ headline }}
{% endif %}
{{ contact }}

## Profile
{{ tailored_summary }}

## Skills
{{ skills_line }}

## Experience
{% for role in experience %}

### {{ role.title }}{% if role.company %} — {{ role.company }}{% endif %}
*{{ role.period }}*
{% for bullet in role.bullets %}
- {{ bullet }}
{% endfor %}
{% endfor %}
{% if job %}

*Prepared for {{ job.title }} at {{ job.company }} · {{ today }}*
{% endif %}
```

Headings (`#`, `##`, `###`), bullets (`- `) and `**bold**` survive the `.docx`
export; other Markdown is written as plain text.
