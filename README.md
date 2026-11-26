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
- **Add application**: company, role, track, source site, link, status, priority, dates, deadline,
  next action, recruiter contact, pay and notes.
- **Applications**: filter and search, edit any cell inline, then press **Save changes**. Status changes are logged.
- **Contacts**: recruiters, alumni, professors, with follow-up dates.
- **Job sites**: one-click searches (LinkedIn, Indeed, Handshake, Wellfound, Google Jobs) with presets for
  SWE, bioinformatics, research and sophomore programs, plus a list of recommended sites.
- **Resume keyword match**: paste a job description to see which of your skills it mentions and what it asks
  for that is not on your resume.
- **Import / export**: import a CSV (try `sample_import.csv`), export to CSV, and back up the database.

## Notes

- Handshake and most job sites require sign-in, so the app does not scrape them. Copy postings in by hand,
  or paste rows into a spreadsheet and import as CSV.
- To back up, copy `data/jobsearch.db`.
- To customize statuses, sources, skills or search presets, edit the lists at the top of `app.py`.
