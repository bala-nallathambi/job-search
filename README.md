# Summer 2027 Internship Tracker

A local Streamlit app for managing an internship search. Everything is stored on your computer in
`data/jobsearch.db` (SQLite). Nothing is uploaded anywhere.

## Run it (macOS)

The app uses [uv](https://docs.astral.sh/uv/) to manage Python and dependencies. Install it once:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then, from the project folder:

```bash
cd ~/jobsearch
uv sync
uv run streamlit run app.py
```

`uv sync` creates `.venv` and installs the exact versions pinned in `uv.lock`. Your browser opens at
http://localhost:8501. Next time, you only need:

```bash
cd ~/jobsearch && uv run streamlit run app.py
```

To add a dependency, run `uv add <package>` (this updates `pyproject.toml` and `uv.lock`).

## Pages

- **Dashboard**: one place for what to do next.
  - **Crawl and refresh** pulls new internship postings from public feeds (see below), skips links already
    saved, scores them, and reports how many were added per source. A source that fails is reported and the
    others still update.
  - **Apply next** lists recent postings you have not applied to yet, together with jobs you are tracking as
    Interested. Filter by relevance, how recently it was posted and keywords. Sort by newest, deadline or best
    match. Pick rows to mark them applied, track them as Interested, or dismiss them.
  - Below that: application totals, response rate, pipeline by status and source, deadlines in the next 21
    days, follow-ups due, and applications sitting in "Applied" for 3+ weeks.
- **Job postings**: every posting you have collected (crawled, added by hand or imported from CSV), each scored
  0-100 against your resume: internship, target role (SWE, bioinformatics, research, data), Summer 2027, open
  to sophomores, and resume skills mentioned. Senior, PhD, new-grad and expired postings are scored down. This
  page also manages the crawl sources.
- **Add application**: company, role, track, source site, link, status, priority, dates, deadline,
  next action, recruiter contact, pay and notes.
- **Applications**: filter and search, edit any cell inline, then press **Save changes**. Status changes are logged.
- **Contacts**: recruiters, alumni, professors, with follow-up dates.
- **Job sites**: one-click searches (LinkedIn, Indeed, Handshake, Wellfound, Google Jobs) with presets for
  SWE, bioinformatics, research and sophomore programs, plus a list of recommended sites.
- **Tailor resume**: make a version of your resume for one job. Open it with the **Tailor resume** button on
  Apply next, Job postings or Applications. See "Tailoring your resume" below.
- **Resume keyword match**: paste a job description to see which of your skills it mentions and what it asks
  for that is not on your resume.
- **Import / export**: import applications (try `sample_import.csv`) or job postings (try
  `sample_postings.csv`) from CSV, export to CSV, and back up the database.

## Crawl and refresh

Only sources that publish postings openly are crawled:

- **SimplifyJobs internship list on GitHub** (on by default). The app reads the list's public JSON file and
  keeps active postings for Summer 2027. To follow another list in the same format, add a "GitHub list"
  source with its raw JSON URL.
- **Greenhouse boards**: add a source with the company's board name, the part after
  `job-boards.greenhouse.io/` in its careers page address (for example `stripe`).
- **Lever boards**: add a source with the name after `jobs.lever.co/`.

For Greenhouse and Lever, only titles that mention intern, internship or co-op are kept. Crawled postings from
the GitHub list have no job description, so they are scored on title, category and term only. Expect scores
around 40-60, and paste a description in to get a sharper score.

Handshake, LinkedIn, Indeed and similar sites need a login or forbid automated access in their terms, so the
app does not crawl them. Use the saved searches on **Job sites**, and add postings from those sites by hand or
by CSV import.

## Tailoring your resume

1. On the **Tailor resume** page, open **Your resume** and load it: put your resume PDF in a `resume/` folder
   next to `app.py` and press **Load it**, or upload the file. Check the text it pulled out and fix anything,
   then press **Save resume text**. This is done once.
2. Pick a job and paste its full job description. Crawled jobs only have a title, so open the posting and copy
   the description in. It is saved with the posting, and the posting's relevance score is updated.
3. Choose a method and press **Tailor my resume**:
   - **AI (Claude)** rewrites emphasis and wording for the job. It may reorder, rephrase and trim, but it is
     told never to add experience, skills, tools, numbers or dates that are not on your resume. If the result
     mentions a technology your original resume does not, the app warns you. Your resume and the job
     description are sent to the Anthropic API.
   - **Keyword only (no AI)** works offline. It moves the bullets, entries and skills that match the job to
     the top, and lists job keywords your resume does not mention yet.
4. Read the result and the list of changes, edit it, then **Save this version** (kept per job) and download it
   as .docx, PDF or Markdown.

To use AI mode, create a file named `.env` next to `app.py` with your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is in `.gitignore`, so the key is never committed. The default model is `claude-opus-5-5`. You can pick
`claude-sonnet-5-5` or `claude-haiku-5-5` on the page for a cheaper run.

Your resume file (`resume/`) and the database that stores your resume text and tailored versions (`data/`)
are both in `.gitignore`.

## Database

Everything lives in one SQLite file, `data/jobsearch.db`, created on first run. Tables:

- `applications`: jobs you are tracking or have applied to.
- `status_history`: every status change on an application.
- `contacts`: recruiters, alumni, professors.
- `postings`: job postings you have found, with their relevance score, matched skills, the reasons for the
  score, a status (New, Saved, Dismissed, Added to applications), where it came from (`origin`) and a link to
  the application made from it.
- `crawl_sources`: the feeds that Crawl and refresh reads, with the result of the last run.
- `profile`: your resume text, used for tailoring.
- `tailored_resumes`: each saved tailored version, with the job description, method, list of changes and
  missing keywords, linked to its posting or application.

You can open it with any SQLite tool, for example `sqlite3 data/jobsearch.db`.

## Notes

- Handshake and most job sites require sign-in, so the app does not crawl them. Copy postings in by hand,
  or paste rows into a spreadsheet and import as CSV.
- To back up, copy `data/jobsearch.db`.
- To customize statuses, sources, skills or search presets, edit the lists at the top of `app.py`. To tune
  relevance, edit `RESUME_SKILLS`, `TARGET_ROLE_TERMS`, `EARLY_CAREER_TERMS` and `MISMATCH_TERMS`, then press
  **Rescore all postings** on the Relevant jobs page.
