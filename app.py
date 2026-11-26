"""
Summer 2027 Internship Tracker
Run with:  streamlit run app.py
All data stays on your machine in data/jobsearch.db (SQLite).
"""

from __future__ import annotations

import re
import sqlite3
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "jobsearch.db"

STATUSES = [
    "Interested",
    "Applied",
    "OA / Assessment",
    "Interviewing",
    "Offer",
    "Accepted",
    "Rejected",
    "Withdrawn",
    "Ghosted",
]
ACTIVE_STATUSES = ["Interested", "Applied", "OA / Assessment", "Interviewing", "Offer"]
PRIORITIES = ["High", "Medium", "Low"]
SOURCES = [
    "Handshake",
    "Internships.com",
    "LinkedIn",
    "Indeed",
    "Simplify",
    "GitHub list (SimplifyJobs)",
    "Wellfound",
    "WayUp",
    "RippleMatch",
    "Company careers page",
    "NSF REU",
    "NIH / government",
    "UMD career fair",
    "Referral",
    "Other",
]
ROLE_TRACKS = [
    "Software Engineering",
    "Bioinformatics / Comp Bio",
    "Research (REU / lab)",
    "Data / ML",
    "Web / Frontend",
    "Sophomore program (Explore/STEP-style)",
    "Other",
]

# Pulled from the resume (CS & Biology, UMD, Class of 2029).
RESUME_SKILLS = [
    "Java", "Python", "JavaScript", "HTML", "CSS", "REST API", "OCR", "web scraping",
    "Git", "JUnit", "MATLAB", "BLAST", "SnapGene", "bioinformatics", "DNA sequencing",
    "GenBank", "Google Colab", "IntelliJ", "Eclipse", "VS Code", "Arduino", "circuitry",
    "soldering", "3D printing", "FreeCAD", "data analysis", "database", "frontend",
    "responsive design", "leadership", "customer service", "writing",
]

SEARCH_KEYWORDS = {
    "Software Engineering": "software engineering intern summer 2027",
    "Sophomore programs": "sophomore software engineering internship 2027",
    "Bioinformatics": "bioinformatics intern summer 2027",
    "Computational biology": "computational biology internship 2027",
    "Research / REU": "undergraduate research internship biology computer science 2027",
    "Data / ML": "data science intern summer 2027",
    "Web / Frontend": "frontend web developer intern summer 2027",
}

# ---------------------------------------------------------------- database


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                track TEXT,
                location TEXT,
                source TEXT,
                link TEXT,
                status TEXT DEFAULT 'Interested',
                priority TEXT DEFAULT 'Medium',
                date_found TEXT,
                date_applied TEXT,
                deadline TEXT,
                next_action TEXT,
                next_action_date TEXT,
                contact_name TEXT,
                contact_email TEXT,
                pay TEXT,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                company TEXT,
                title TEXT,
                email TEXT,
                linkedin TEXT,
                how_met TEXT,
                last_contacted TEXT,
                follow_up_date TEXT,
                notes TEXT
            );
            CREATE TABLE IF NOT EXISTS status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id INTEGER,
                status TEXT,
                changed_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


APP_COLUMNS = [
    "company", "role", "track", "location", "source", "link", "status", "priority",
    "date_found", "date_applied", "deadline", "next_action", "next_action_date",
    "contact_name", "contact_email", "pay", "notes",
]
CONTACT_COLUMNS = [
    "name", "company", "title", "email", "linkedin", "how_met",
    "last_contacted", "follow_up_date", "notes",
]
DATE_COLUMNS = ["date_found", "date_applied", "deadline", "next_action_date",
                "last_contacted", "follow_up_date"]


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if value is pd.NaT:
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def insert_application(record: dict) -> int:
    values = [_clean(record.get(c)) for c in APP_COLUMNS]
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO applications ({', '.join(APP_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(APP_COLUMNS))})",
            values,
        )
        app_id = cur.lastrowid
        conn.execute(
            "INSERT INTO status_history (app_id, status) VALUES (?, ?)",
            (app_id, record.get("status") or "Interested"),
        )
    return app_id


def update_application(app_id: int, record: dict) -> None:
    with get_conn() as conn:
        old = conn.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()
        sets = ", ".join(f"{c}=?" for c in APP_COLUMNS)
        conn.execute(
            f"UPDATE applications SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [_clean(record.get(c)) for c in APP_COLUMNS] + [app_id],
        )
        if old and old["status"] != record.get("status"):
            conn.execute(
                "INSERT INTO status_history (app_id, status) VALUES (?, ?)",
                (app_id, record.get("status")),
            )


def delete_rows(table: str, ids: list[int]) -> None:
    if not ids:
        return
    with get_conn() as conn:
        conn.executemany(f"DELETE FROM {table} WHERE id=?", [(i,) for i in ids])
        if table == "applications":
            conn.executemany("DELETE FROM status_history WHERE app_id=?", [(i,) for i in ids])


def load_df(table: str) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(f"SELECT * FROM {table} ORDER BY id DESC", conn)
    for col in DATE_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    return df


def insert_contact(record: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            f"INSERT INTO contacts ({', '.join(CONTACT_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(CONTACT_COLUMNS))})",
            [_clean(record.get(c)) for c in CONTACT_COLUMNS],
        )


def update_contact(contact_id: int, record: dict) -> None:
    with get_conn() as conn:
        sets = ", ".join(f"{c}=?" for c in CONTACT_COLUMNS)
        conn.execute(
            f"UPDATE contacts SET {sets} WHERE id=?",
            [_clean(record.get(c)) for c in CONTACT_COLUMNS] + [contact_id],
        )


# ---------------------------------------------------------------- helpers


def days_until(d) -> int | None:
    if d is None or pd.isna(d):
        return None
    return (d - date.today()).days


def search_links(query: str, location: str = "") -> dict[str, str]:
    q = urllib.parse.quote_plus(query)
    loc = urllib.parse.quote_plus(location)
    return {
        "LinkedIn (internship filter)": f"https://www.linkedin.com/jobs/search/?keywords={q}&location={loc}&f_E=1",
        "Indeed": f"https://www.indeed.com/jobs?q={q}&l={loc}",
        "Handshake (sign in first)": f"https://app.joinhandshake.com/stu/postings?query={q}",
        "Internships.com": f"https://www.internships.com/",
        "Simplify": "https://simplify.jobs/jobs?experience=Internship",
        "Wellfound (startups)": f"https://wellfound.com/jobs?query={q}",
        "Google Jobs": f"https://www.google.com/search?q={q}+{loc}&ibp=htl;jobs",
        "WayUp": "https://www.wayup.com/s/internships/",
    }


def link_column_config() -> dict:
    return {
        "link": st.column_config.LinkColumn("Link", display_text="open"),
        "status": st.column_config.SelectboxColumn("Status", options=STATUSES),
        "priority": st.column_config.SelectboxColumn("Priority", options=PRIORITIES),
        "source": st.column_config.SelectboxColumn("Source", options=SOURCES),
        "track": st.column_config.SelectboxColumn("Track", options=ROLE_TRACKS),
        "date_found": st.column_config.DateColumn("Found"),
        "date_applied": st.column_config.DateColumn("Applied"),
        "deadline": st.column_config.DateColumn("Deadline"),
        "next_action_date": st.column_config.DateColumn("Next action date"),
        "id": st.column_config.NumberColumn("ID", disabled=True),
    }


# ---------------------------------------------------------------- pages


def page_dashboard() -> None:
    st.title("Summer 2027 Internship Dashboard")
    df = load_df("applications")
    if df.empty:
        st.info("No applications yet. Add one from **Add application**, or import a CSV.")
        return

    today = date.today()
    applied_like = df["status"].isin(
        ["Applied", "OA / Assessment", "Interviewing", "Offer", "Accepted", "Rejected", "Ghosted"]
    )
    responded = df["status"].isin(["OA / Assessment", "Interviewing", "Offer", "Accepted", "Rejected"])
    week_ago = today - timedelta(days=7)
    applied_this_week = df["date_applied"].apply(lambda d: d is not None and not pd.isna(d) and d >= week_ago).sum()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Tracked", len(df))
    c2.metric("Applied", int(applied_like.sum()))
    c3.metric("Applied (last 7 days)", int(applied_this_week))
    c4.metric("Interviewing", int((df["status"] == "Interviewing").sum()))
    rate = f"{(responded.sum() / applied_like.sum() * 100):.0f}%" if applied_like.sum() else "n/a"
    c5.metric("Response rate", rate)

    left, right = st.columns(2)
    with left:
        st.subheader("Pipeline")
        counts = df["status"].value_counts().reindex(STATUSES, fill_value=0)
        st.bar_chart(counts.rename("Applications"), horizontal=True)
    with right:
        st.subheader("By source")
        st.bar_chart(df["source"].fillna("Unknown").value_counts().rename("Applications"), horizontal=True)

    st.subheader("Deadlines in the next 21 days")
    upcoming = df[df["status"].isin(["Interested"]) | df["status"].isin(ACTIVE_STATUSES)].copy()
    upcoming["days_left"] = upcoming["deadline"].apply(days_until)
    upcoming = upcoming[upcoming["days_left"].notna() & (upcoming["days_left"] >= 0) & (upcoming["days_left"] <= 21)]
    if upcoming.empty:
        st.caption("Nothing due in the next three weeks.")
    else:
        st.dataframe(
            upcoming.sort_values("days_left")[["company", "role", "status", "deadline", "days_left", "link"]],
            hide_index=True,
            column_config=link_column_config(),
            width="stretch",
        )

    st.subheader("Follow-ups and next actions")
    todo = df[df["next_action_date"].notna() & df["status"].isin(ACTIVE_STATUSES)].copy()
    todo["days_left"] = todo["next_action_date"].apply(days_until)
    todo = todo[todo["days_left"] <= 7]
    stale = df[(df["status"] == "Applied") & df["date_applied"].apply(
        lambda d: d is not None and not pd.isna(d) and (today - d).days >= 21)]
    if todo.empty and stale.empty:
        st.caption("No follow-ups due this week.")
    if not todo.empty:
        st.dataframe(
            todo.sort_values("days_left")[["company", "role", "next_action", "next_action_date", "days_left"]],
            hide_index=True, width="stretch",
        )
    if not stale.empty:
        st.warning(
            f"{len(stale)} application(s) have been in **Applied** for 3+ weeks. "
            "Consider a polite follow-up or marking them Ghosted."
        )
        st.dataframe(stale[["company", "role", "date_applied", "contact_name", "contact_email"]],
                     hide_index=True, width="stretch")

    overdue = df[df["status"] == "Interested"].copy()
    overdue["days_left"] = overdue["deadline"].apply(days_until)
    overdue = overdue[overdue["days_left"].notna() & (overdue["days_left"] < 0)]
    if not overdue.empty:
        st.error(f"{len(overdue)} saved posting(s) passed their deadline without an application.")


def application_form(defaults: dict | None = None, key: str = "new") -> dict | None:
    d = defaults or {}

    def idx(options, value, fallback=0):
        return options.index(value) if value in options else fallback

    with st.form(f"app_form_{key}", clear_on_submit=(key == "new")):
        c1, c2 = st.columns(2)
        company = c1.text_input("Company *", d.get("company") or "")
        role = c2.text_input("Role / title *", d.get("role") or "")
        c1, c2, c3 = st.columns(3)
        track = c1.selectbox("Track", ROLE_TRACKS, index=idx(ROLE_TRACKS, d.get("track")))
        source = c2.selectbox("Source site", SOURCES, index=idx(SOURCES, d.get("source")))
        location = c3.text_input("Location", d.get("location") or "")
        link = st.text_input("Posting link", d.get("link") or "")
        c1, c2, c3 = st.columns(3)
        status = c1.selectbox("Status", STATUSES, index=idx(STATUSES, d.get("status")))
        priority = c2.selectbox("Priority", PRIORITIES, index=idx(PRIORITIES, d.get("priority"), 1))
        pay = c3.text_input("Pay (if listed)", d.get("pay") or "")

        def date_val(name, default=None):
            v = d.get(name)
            return v if v is not None and not pd.isna(v) else default

        c1, c2, c3 = st.columns(3)
        date_found = c1.date_input("Date found", date_val("date_found", date.today()))
        date_applied = c2.date_input("Date applied", date_val("date_applied"), help="Leave blank if not applied yet")
        deadline = c3.date_input("Deadline", date_val("deadline"))
        c1, c2 = st.columns([2, 1])
        next_action = c1.text_input("Next action", d.get("next_action") or "",
                                    placeholder="e.g. finish OA, email recruiter, prep behavioral")
        next_action_date = c2.date_input("Next action date", date_val("next_action_date"))
        c1, c2 = st.columns(2)
        contact_name = c1.text_input("Contact / recruiter", d.get("contact_name") or "")
        contact_email = c2.text_input("Contact email", d.get("contact_email") or "")
        notes = st.text_area("Notes", d.get("notes") or "", height=100)
        submitted = st.form_submit_button("Save", type="primary")

    if submitted:
        if not company.strip() or not role.strip():
            st.error("Company and role are required.")
            return None
        if status == "Applied" and date_applied is None:
            date_applied = date.today()
        return dict(
            company=company, role=role, track=track, location=location, source=source,
            link=link, status=status, priority=priority, date_found=date_found,
            date_applied=date_applied, deadline=deadline, next_action=next_action,
            next_action_date=next_action_date, contact_name=contact_name,
            contact_email=contact_email, pay=pay, notes=notes,
        )
    return None


def page_add() -> None:
    st.title("Add application")
    st.caption("Copy the details from Handshake, Internships.com or any other site. Fields marked * are required.")
    record = application_form()
    if record:
        insert_application(record)
        st.success(f"Saved {record['company']} - {record['role']}.")


def page_applications() -> None:
    st.title("Applications")
    df = load_df("applications")
    if df.empty:
        st.info("No applications yet.")
        return

    with st.expander("Filters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        status_f = c1.multiselect("Status", STATUSES)
        source_f = c2.multiselect("Source", sorted(df["source"].dropna().unique()))
        track_f = c3.multiselect("Track", sorted(df["track"].dropna().unique()))
        text_f = c4.text_input("Search company / role / notes")
    view = df.copy()
    if status_f:
        view = view[view["status"].isin(status_f)]
    if source_f:
        view = view[view["source"].isin(source_f)]
    if track_f:
        view = view[view["track"].isin(track_f)]
    if text_f:
        mask = (
            view["company"].fillna("").str.contains(text_f, case=False)
            | view["role"].fillna("").str.contains(text_f, case=False)
            | view["notes"].fillna("").str.contains(text_f, case=False)
        )
        view = view[mask]

    st.caption(f"Showing {len(view)} of {len(df)}. Edit cells directly, then press **Save changes**.")
    cols = ["id"] + APP_COLUMNS
    edited = st.data_editor(
        view[cols],
        hide_index=True,
        width="stretch",
        column_config=link_column_config(),
        disabled=["id"],
        key="app_editor",
        num_rows="fixed",
    )
    c1, c2 = st.columns([1, 3])
    if c1.button("Save changes", type="primary"):
        original = view[cols].set_index("id")
        changed = 0
        for _, row in edited.iterrows():
            rid = int(row["id"])
            before = original.loc[rid]
            if any(_clean(before[c]) != _clean(row[c]) for c in APP_COLUMNS):
                update_application(rid, row.to_dict())
                changed += 1
        st.success(f"Updated {changed} row(s).")
        st.rerun()

    with st.expander("Delete applications"):
        labels = {f"#{r.id} {r.company} - {r.role}": int(r.id) for r in view.itertuples()}
        to_delete = st.multiselect("Select to delete", list(labels))
        if st.button("Delete selected", disabled=not to_delete):
            delete_rows("applications", [labels[x] for x in to_delete])
            st.success(f"Deleted {len(to_delete)}.")
            st.rerun()


def page_contacts() -> None:
    st.title("Contacts and networking")
    st.caption("Recruiters, alumni, professors, career fair contacts. Networking often beats cold applying.")
    with st.expander("Add contact", expanded=False):
        with st.form("contact_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Name *")
            company = c2.text_input("Company / lab")
            title = c3.text_input("Title")
            c1, c2, c3 = st.columns(3)
            email = c1.text_input("Email")
            linkedin = c2.text_input("LinkedIn URL")
            how_met = c3.text_input("How you met", placeholder="career fair, alum, professor...")
            c1, c2 = st.columns(2)
            last = c1.date_input("Last contacted", None)
            follow = c2.date_input("Follow up on", None)
            notes = st.text_area("Notes")
            if st.form_submit_button("Save contact", type="primary"):
                if name.strip():
                    insert_contact(dict(name=name, company=company, title=title, email=email,
                                        linkedin=linkedin, how_met=how_met, last_contacted=last,
                                        follow_up_date=follow, notes=notes))
                    st.success("Saved.")
                else:
                    st.error("Name is required.")

    df = load_df("contacts")
    if df.empty:
        st.info("No contacts yet.")
        return
    cols = ["id"] + CONTACT_COLUMNS
    edited = st.data_editor(
        df[cols], hide_index=True, width="stretch", disabled=["id"], key="contact_editor",
        column_config={
            "linkedin": st.column_config.LinkColumn("LinkedIn", display_text="profile"),
            "last_contacted": st.column_config.DateColumn("Last contacted"),
            "follow_up_date": st.column_config.DateColumn("Follow up"),
        },
    )
    c1, c2 = st.columns([1, 3])
    if c1.button("Save contact changes", type="primary"):
        for _, row in edited.iterrows():
            update_contact(int(row["id"]), row.to_dict())
        st.success("Saved.")
        st.rerun()
    with st.expander("Delete contacts"):
        labels = {f"#{r.id} {r.name} ({r.company or ''})": int(r.id) for r in df.itertuples()}
        to_delete = st.multiselect("Select to delete", list(labels), key="del_contacts")
        if st.button("Delete selected contacts", disabled=not to_delete):
            delete_rows("contacts", [labels[x] for x in to_delete])
            st.rerun()


SITES = [
    # (name, url, why)
    ("Handshake", "https://app.joinhandshake.com/stu/postings",
     "Your primary site. Sign in with UMD (Careers4Terps). Employers here are recruiting UMD students specifically."),
    ("Internships.com", "https://www.internships.com/",
     "Your other primary site. Broad listings, many smaller companies."),
    ("SimplifyJobs Summer 2027 list (GitHub)", "https://github.com/SimplifyJobs/Summer2027-Internships",
     "Community-maintained list of tech internships, updated daily. Watch the repo for new postings. "
     "If the link 404s, check github.com/SimplifyJobs for the current year's repo."),
    ("Simplify", "https://simplify.jobs/",
     "Job board plus a browser extension that autofills applications and tracks them."),
    ("LinkedIn Jobs", "https://www.linkedin.com/jobs/",
     "Use the Experience level = Internship filter and set job alerts."),
    ("Indeed", "https://www.indeed.com/",
     "Largest general board. Good for local / non-tech-hub roles."),
    ("Wellfound (AngelList)", "https://wellfound.com/",
     "Startups. Often more open to sophomores and less competitive than big tech."),
    ("WayUp", "https://www.wayup.com/",
     "Early-career and internship focused, many diversity programs."),
    ("RippleMatch", "https://ripplematch.com/",
     "Matches you to employers based on your profile; recruiters reach out to you."),
    ("NSF REU sites", "https://www.nsf.gov/crssprgm/reu/reu_search.jsp",
     "Paid summer research at universities. Great fit for CS + Biology (bioinformatics, comp bio). "
     "Deadlines are usually Jan-Mar."),
    ("NIH Summer Internship Program (SIP)", "https://www.training.nih.gov/research-training/pb/sip/",
     "Biomedical / bioinformatics research at NIH in Bethesda, close to UMD. Applications usually open in winter."),
    ("USAJobs Pathways (students)", "https://www.usajobs.gov/",
     "Federal internships (NIST, NIH, NASA Goddard are all near College Park)."),
    ("UMD University Career Center", "https://careers.umd.edu/",
     "Career fairs, resume reviews, mock interviews."),
    ("Levels.fyi internships", "https://www.levels.fyi/internships/",
     "See which companies hire interns and what they pay."),
]

SOPHOMORE_TIPS = """
**Programs aimed at first- and second-year students** (check each company's careers page to confirm the
program is running for 2027, since these change year to year):

- Google STEP-style programs, Microsoft Explore-style programs, Meta University, Capital One,
  JPMorgan Chase (you already won JPMC GenerationTech), Goldman Sachs, Bloomberg, Amazon Propel / Future Engineer,
  and many banks' sophomore technology programs.
- Search "sophomore internship 2027", "freshman sophomore software", "early insight" and "discovery program".

**Fit for your resume (CS + Biology):**

- Software engineering intern: Java, Python, JavaScript, JUnit, Git, REST APIs, web projects.
- Bioinformatics / computational biology intern: BLAST, SnapGene, GenBank work at Waksman, Python.
- Research (REU, NIH SIP, UMD labs): your Waksman Summer Scholar experience is a strong starting point.
  Emailing UMD professors directly about summer research is very effective.

**Timing:** Big-tech Summer 2027 postings open from roughly July to October 2026 and many fill early.
Research programs and government roles usually close January to March 2027. Keep applying through spring.
"""


def page_sites() -> None:
    st.title("Job sites and search links")
    st.subheader("Quick search")
    c1, c2, c3 = st.columns([2, 2, 1])
    preset = c1.selectbox("Preset search", list(SEARCH_KEYWORDS))
    query = c2.text_input("Keywords", SEARCH_KEYWORDS[preset])
    location = c3.text_input("Location", "")
    links = search_links(query, location)
    cols = st.columns(4)
    for i, (name, url) in enumerate(links.items()):
        cols[i % 4].link_button(name, url, width="stretch")

    st.subheader("Recommended sites")
    for name, url, why in SITES:
        st.markdown(f"**[{name}]({url})**: {why}")

    st.subheader("Tips for a sophomore")
    st.markdown(SOPHOMORE_TIPS)


def page_keyword_match() -> None:
    st.title("Resume keyword match")
    st.caption("Paste a job description to see which of your resume skills it mentions and what it asks for that you might add.")
    extra = st.text_input("Extra skills to count as yours (comma separated)", "")
    skills = RESUME_SKILLS + [s.strip() for s in extra.split(",") if s.strip()]
    jd = st.text_area("Job description", height=250)
    common_terms = [
        "C++", "C#", "Golang", "Rust", "SQL", "React", "Node", "TypeScript", "AWS", "Docker", "Linux",
        "Kubernetes", "machine learning", "pandas", "NumPy", "statistics", "data structures",
        "algorithms", "object-oriented", "Agile", "REST", "API", "cloud", "Spring", "Django", "Flask",
        "genomics", "sequencing", "PCR", "wet lab", "biostatistics", "Bash", "unit testing",
    ]
    if jd.strip():
        low = jd.lower()

        def found(term):
            t = term.lower()
            if len(t) <= 3:
                return re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z+#])", low) is not None
            return t in low

        have = [s for s in skills if found(s)]
        missing = [t for t in common_terms if found(t) and not any(t.lower() == s.lower() for s in skills)]
        c1, c2 = st.columns(2)
        c1.metric("Your skills mentioned", len(have))
        c2.metric("Asked for, not on resume", len(missing))
        c1.write(", ".join(have) or "None found")
        c2.write(", ".join(missing) or "None found")
        st.caption("Only list a skill on your resume if you can talk about it in an interview.")


def page_import_export() -> None:
    st.title("Import / export")
    st.subheader("Export")
    apps = load_df("applications")
    contacts = load_df("contacts")
    c1, c2 = st.columns(2)
    c1.download_button("Download applications CSV", apps.to_csv(index=False), "applications.csv", "text/csv",
                       disabled=apps.empty)
    c2.download_button("Download contacts CSV", contacts.to_csv(index=False), "contacts.csv", "text/csv",
                       disabled=contacts.empty)

    st.subheader("Import applications from CSV")
    st.caption(
        "Columns are matched by name (case-insensitive). Required: company, role. Optional: "
        + ", ".join(APP_COLUMNS[2:])
        + ". Common aliases like 'Company Name', 'Title', 'Position', 'URL', 'Apply By' also work."
    )
    aliases = {
        "company name": "company", "employer": "company", "organization": "company",
        "title": "role", "position": "role", "job title": "role",
        "url": "link", "apply link": "link", "posting url": "link", "application link": "link",
        "apply by": "deadline", "due date": "deadline", "expiration date": "deadline",
        "applied": "date_applied", "date applied": "date_applied",
        "site": "source", "board": "source",
    }
    up = st.file_uploader("CSV file", type=["csv"])
    default_source = st.selectbox("Source to use when the CSV has none", SOURCES)
    if up is not None:
        raw = pd.read_csv(up)
        rename = {}
        for c in raw.columns:
            key = c.strip().lower()
            if key in APP_COLUMNS:
                rename[c] = key
            elif key.replace(" ", "_") in APP_COLUMNS:
                rename[c] = key.replace(" ", "_")
            elif key in aliases:
                rename[c] = aliases[key]
        df = raw.rename(columns=rename)
        df = df.loc[:, ~df.columns.duplicated()]
        if "company" not in df.columns or "role" not in df.columns:
            st.error(f"Could not find company and role columns. Found: {list(raw.columns)}")
            return
        st.dataframe(df.head(20), width="stretch")
        skip_dupes = st.checkbox("Skip rows already tracked (same company + role)", value=True)
        if st.button(f"Import {len(df)} rows", type="primary"):
            existing = set(zip(apps["company"].str.lower(), apps["role"].str.lower())) if not apps.empty else set()
            added = 0
            for rec in df.to_dict("records"):
                if not _clean(rec.get("company")) or not _clean(rec.get("role")):
                    continue
                if skip_dupes and (str(rec["company"]).lower(), str(rec["role"]).lower()) in existing:
                    continue
                rec.setdefault("source", default_source)
                if not _clean(rec.get("source")):
                    rec["source"] = default_source
                if not _clean(rec.get("status")):
                    rec["status"] = "Interested"
                for dc in ("date_found", "date_applied", "deadline", "next_action_date"):
                    if _clean(rec.get(dc)):
                        parsed = pd.to_datetime(rec[dc], errors="coerce")
                        rec[dc] = None if pd.isna(parsed) else parsed.date()
                rec.setdefault("date_found", date.today())
                insert_application(rec)
                added += 1
            st.success(f"Imported {added} application(s).")

    st.subheader("Backup")
    st.caption(f"Your database file is `{DB_PATH}`. Copy it somewhere safe (or into cloud storage) to back up everything.")


# ---------------------------------------------------------------- main


def main() -> None:
    st.set_page_config(page_title="Internship Tracker 2027", page_icon=":briefcase:", layout="wide")
    init_db()
    pages = {
        "Dashboard": page_dashboard,
        "Add application": page_add,
        "Applications": page_applications,
        "Contacts": page_contacts,
        "Job sites": page_sites,
        "Resume keyword match": page_keyword_match,
        "Import / export": page_import_export,
    }
    with st.sidebar:
        st.header("Internship Tracker")
        st.caption("Summer 2027 · CS & Biology")
        choice = st.radio("Go to", list(pages), label_visibility="collapsed")
        st.divider()
        st.link_button("Handshake", "https://app.joinhandshake.com/stu/postings", width="stretch")
        st.link_button("Internships.com", "https://www.internships.com/", width="stretch")
        st.link_button("Summer 2027 GitHub list", "https://github.com/SimplifyJobs/Summer2027-Internships",
                       width="stretch")
    pages[choice]()


if __name__ == "__main__":
    main()
