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

- **Dashboard**: totals, response rate, pipeline by status and source, deadlines in the next 21 days,
  follow-ups due, and applications sitting in "Applied" for 3+ weeks.
- **Relevant jobs**: a separate dashboard for job postings you have collected (added by hand or imported
  from CSV). Each posting is scored 0-100 against your resume: internship, target role (SWE, bioinformatics,
  research, data), Summer 2027, open to sophomores, and resume skills mentioned. Senior, PhD, new-grad and
  expired postings are scored down. Filter by score, status, source and deadline, then pick postings to add
  to Applications, save or dismiss.
- **Add application**: company, role, track, source site, link, status, priority, dates, deadline,
  next action, recruiter contact, pay and notes.
- **Applications**: filter and search, edit any cell inline, then press **Save changes**. Status changes are logged.
- **Contacts**: recruiters, alumni, professors, with follow-up dates.
- **Job sites**: one-click searches (LinkedIn, Indeed, Handshake, Wellfound, Google Jobs) with presets for
  SWE, bioinformatics, research and sophomore programs, plus a list of recommended sites.
- **Resume keyword match**: paste a job description to see which of your skills it mentions and what it asks
  for that is not on your resume.
- **Import / export**: import applications (try `sample_import.csv`) or job postings (try
  `sample_postings.csv`) from CSV, export to CSV, and back up the database.

## Database

Everything lives in one SQLite file, `data/jobsearch.db`, created on first run. Tables:

- `applications`: jobs you are tracking or have applied to.
- `status_history`: every status change on an application.
- `contacts`: recruiters, alumni, professors.
- `postings`: job postings you have found, with their relevance score, matched skills, the reasons for the
  score, a status (New, Saved, Dismissed, Added to applications) and a link to the application made from it.

You can open it with any SQLite tool, for example `sqlite3 data/jobsearch.db`.

## Notes

- Handshake and most job sites require sign-in, so the app does not scrape them. Copy postings in by hand,
  or paste rows into a spreadsheet and import as CSV.
- To back up, copy `data/jobsearch.db`.
- To customize statuses, sources, skills or search presets, edit the lists at the top of `app.py`. To tune
  relevance, edit `RESUME_SKILLS`, `TARGET_ROLE_TERMS`, `EARLY_CAREER_TERMS` and `MISMATCH_TERMS`, then press
  **Rescore all postings** on the Relevant jobs page.
