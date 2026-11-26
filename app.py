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

import crawler

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
    conn.execute("PRAGMA foreign_keys = ON")
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
            -- Job postings you have found but not necessarily applied to yet.
            CREATE TABLE IF NOT EXISTS postings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                title TEXT NOT NULL,
                location TEXT,
                source TEXT,
                link TEXT,
                description TEXT,
                date_posted TEXT,
                date_found TEXT,
                deadline TEXT,
                pay TEXT,
                relevance INTEGER DEFAULT 0,
                matched_skills TEXT,
                reasons TEXT,
                status TEXT DEFAULT 'New',
                application_id INTEGER REFERENCES applications(id) ON DELETE SET NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_postings_relevance ON postings(relevance DESC);
            CREATE INDEX IF NOT EXISTS idx_postings_status ON postings(status);
            CREATE INDEX IF NOT EXISTS idx_postings_deadline ON postings(deadline);
            CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
            CREATE INDEX IF NOT EXISTS idx_applications_deadline ON applications(deadline);
            CREATE INDEX IF NOT EXISTS idx_status_history_app ON status_history(app_id);
            CREATE INDEX IF NOT EXISTS idx_postings_link ON postings(link);
            -- Public job feeds that "Crawl and refresh" pulls from.
            CREATE TABLE IF NOT EXISTS crawl_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,            -- simplify | greenhouse | lever
                name TEXT NOT NULL,
                target TEXT,                   -- JSON URL (simplify) or board name (greenhouse / lever)
                enabled INTEGER DEFAULT 1,
                last_run TEXT,
                last_status TEXT,
                last_added INTEGER
            );
            """
        )
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(postings)")}
        if "origin" not in cols:
            conn.execute("ALTER TABLE postings ADD COLUMN origin TEXT DEFAULT 'manual'")
        if conn.execute("SELECT COUNT(*) FROM crawl_sources").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO crawl_sources (kind, name, target) VALUES (?, ?, ?)",
                [("simplify", "SimplifyJobs Summer 2027 list (GitHub)", crawler.SIMPLIFY_DEFAULT_URL)],
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
POSTING_COLUMNS = [
    "company", "title", "location", "source", "link", "description",
    "date_posted", "date_found", "deadline", "pay",
]
POSTING_STATUSES = ["New", "Saved", "Dismissed", "Added to applications"]
DATE_COLUMNS = ["date_found", "date_applied", "deadline", "next_action_date",
                "last_contacted", "follow_up_date", "date_posted"]


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


# ---------------------------------------------------------------- job postings + relevance


# Terms that make a posting a fit for a CS + Biology sophomore targeting Summer 2027.
TARGET_ROLE_TERMS = {
    "software": 15, "developer": 12, "engineering": 8, "bioinformatics": 20,
    "computational biology": 20, "comp bio": 15, "genomics": 12, "research": 10,
    "reu": 15, "data": 8, "machine learning": 8, "web": 6, "frontend": 8, "full stack": 8,
}
EARLY_CAREER_TERMS = [
    "sophomore", "freshman", "first-year", "first year", "second-year", "second year",
    "underclassmen", "early insight", "discovery program", "explore", "step intern",
    "class of 2029", "rising sophomore", "rising junior",
]
MISMATCH_TERMS = {
    "senior": 25, "staff engineer": 25, "phd": 20, "ph.d": 20, "master's": 15, "masters": 15,
    "graduate student": 15, "new grad": 20, "full-time": 15, "full time": 15,
    "5+ years": 25, "3+ years": 20, "class of 2026": 20, "class of 2027": 10,
}


def _mentions(text: str, term: str) -> bool:
    t = term.lower()
    if len(t) <= 4:
        return re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z+#])", text) is not None
    return t in text


def score_posting(title: str | None, description: str | None, deadline=None,
                  skills: list[str] | None = None) -> tuple[int, list[str], list[str]]:
    """Return (score 0-100, matched resume skills, reasons)."""
    skills = skills or RESUME_SKILLS
    title_l = (title or "").lower()
    text = f"{title_l}\n{(description or '').lower()}"
    score, reasons = 0, []

    if _mentions(title_l, "intern") or "internship" in text or "co-op" in text:
        score += 15
        reasons.append("internship")
    role_pts = 0
    for term, pts in TARGET_ROLE_TERMS.items():
        if _mentions(title_l, term):
            role_pts += pts
        elif _mentions(text, term):
            role_pts += pts // 3
    if role_pts:
        score += min(role_pts, 25)
        reasons.append("target role")
    if "2027" in text:
        score += 15
        reasons.append("Summer 2027")
    if any(_mentions(text, t) for t in EARLY_CAREER_TERMS):
        score += 15
        reasons.append("open to sophomores")

    matched = [s for s in skills if _mentions(text, s)]
    if matched:
        score += min(len(matched) * 5, 30)
        reasons.append(f"{len(matched)} resume skill(s)")

    penalty = 0
    for term, pts in MISMATCH_TERMS.items():
        if _mentions(text, term):
            penalty += pts
            reasons.append(f"mentions '{term}'")
    score -= min(penalty, 50)

    d = deadline
    if isinstance(d, str):
        d = pd.to_datetime(d, errors="coerce")
        d = None if pd.isna(d) else d.date()
    if d is not None and not pd.isna(d) and d < date.today():
        score -= 30
        reasons.append("deadline passed")

    return max(0, min(100, score)), matched, reasons


def _posting_values(record: dict) -> tuple[list, int, str, str]:
    values = [_clean(record.get(c)) for c in POSTING_COLUMNS]
    rec = dict(zip(POSTING_COLUMNS, values))
    score, matched, reasons = score_posting(rec["title"], rec["description"], rec["deadline"])
    return values, score, ", ".join(matched), "; ".join(reasons)


def insert_posting(record: dict, conn: sqlite3.Connection | None = None) -> int:
    values, score, matched, reasons = _posting_values(record)
    sql = (f"INSERT INTO postings ({', '.join(POSTING_COLUMNS)}, relevance, matched_skills, reasons, status, "
           f"origin) VALUES ({', '.join('?' * (len(POSTING_COLUMNS) + 5))})")
    params = values + [score, matched, reasons, _clean(record.get("status")) or "New",
                       _clean(record.get("origin")) or "manual"]
    if conn is not None:
        return conn.execute(sql, params).lastrowid
    with get_conn() as c:
        return c.execute(sql, params).lastrowid


CRAWL_KINDS = {"simplify": "GitHub list (SimplifyJobs format)", "greenhouse": "Greenhouse board",
               "lever": "Lever board"}


def run_crawl(term: str = "Summer 2027") -> list[dict]:
    """Fetch every enabled source, add postings with new links, and return a per-source summary."""
    with get_conn() as conn:
        sources = conn.execute("SELECT * FROM crawl_sources WHERE enabled=1 ORDER BY id").fetchall()
        known = {r[0] for r in conn.execute("SELECT link FROM postings WHERE link IS NOT NULL")}
    summary = []
    for src in sources:
        row = dict(source=src["name"], found=0, added=0, error=None)
        try:
            items = crawler.crawl_source(src["kind"], src["target"], src["name"], term)
            row["found"] = len(items)
            with get_conn() as conn:
                for item in items:
                    if item["link"] in known:
                        continue
                    known.add(item["link"])
                    item.update(source="Company careers page" if src["kind"] != "simplify"
                                else "GitHub list (SimplifyJobs)",
                                date_found=date.today(), origin=f"crawl:{src['name']}")
                    insert_posting(item, conn)
                    row["added"] += 1
            status = f"OK: {row['found']} found, {row['added']} new"
        except crawler.CrawlError as e:
            row["error"] = str(e)
            status = f"Failed: {e}"
        except Exception as e:  # keep one bad source from stopping the rest
            row["error"] = f"{type(e).__name__}: {e}"
            status = f"Failed: {row['error']}"
        with get_conn() as conn:
            conn.execute("UPDATE crawl_sources SET last_run=?, last_status=?, last_added=? WHERE id=?",
                         (datetime.now().isoformat(timespec="minutes"), status, row["added"], src["id"]))
        summary.append(row)
    return summary


def update_posting(posting_id: int, record: dict) -> None:
    values, score, matched, reasons = _posting_values(record)
    sets = ", ".join(f"{c}=?" for c in POSTING_COLUMNS)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE postings SET {sets}, relevance=?, matched_skills=?, reasons=?, status=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            values + [score, matched, reasons, _clean(record.get("status")) or "New", posting_id],
        )


def set_posting_status(ids: list[int], status: str) -> None:
    with get_conn() as conn:
        conn.executemany("UPDATE postings SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         [(status, i) for i in ids])


def rescore_all_postings() -> int:
    df = load_df("postings")
    for rec in df.to_dict("records"):
        update_posting(int(rec["id"]), rec)
    return len(df)


def posting_to_application(posting_id: int, status: str = "Interested") -> int | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM postings WHERE id=?", (posting_id,)).fetchone()
    if row is None:
        return None
    if row["application_id"]:
        if status != "Interested":
            mark_applied([row["application_id"]])
        return row["application_id"]
    text = f"{row['title']} {row['description'] or ''}".lower()
    track = next((t for k, t in [
        ("bioinformatics", "Bioinformatics / Comp Bio"), ("computational biology", "Bioinformatics / Comp Bio"),
        ("reu", "Research (REU / lab)"), ("research", "Research (REU / lab)"),
        ("sophomore", "Sophomore program (Explore/STEP-style)"), ("data", "Data / ML"),
        ("machine learning", "Data / ML"), ("frontend", "Web / Frontend"), ("web", "Web / Frontend"),
        ("software", "Software Engineering"),
    ] if _mentions(text, k)), "Other")
    app_id = insert_application(dict(
        company=row["company"], role=row["title"], track=track, location=row["location"],
        source=row["source"], link=row["link"], status=status,
        date_applied=date.today() if status == "Applied" else None,
        priority="High" if (row["relevance"] or 0) >= 70 else "Medium",
        date_found=row["date_found"] or date.today(), deadline=row["deadline"], pay=row["pay"],
        notes=f"From job postings (relevance {row['relevance']}). {row['reasons'] or ''}".strip(),
    ))
    with get_conn() as conn:
        conn.execute("UPDATE postings SET status='Added to applications', application_id=?, "
                     "updated_at=CURRENT_TIMESTAMP WHERE id=?", (app_id, posting_id))
    return app_id


def mark_applied(app_ids: list[int]) -> None:
    with get_conn() as conn:
        for aid in app_ids:
            conn.execute("UPDATE applications SET status='Applied', date_applied=COALESCE(date_applied, ?), "
                         "updated_at=CURRENT_TIMESTAMP WHERE id=?", (date.today().isoformat(), aid))
            conn.execute("INSERT INTO status_history (app_id, status) VALUES (?, 'Applied')", (aid,))


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


def render_crawl_controls(key: str) -> None:
    with get_conn() as conn:
        last = conn.execute("SELECT MAX(last_run) FROM crawl_sources WHERE enabled=1").fetchone()[0]
        n_sources = conn.execute("SELECT COUNT(*) FROM crawl_sources WHERE enabled=1").fetchone()[0]
    c1, c2 = st.columns([1, 3])
    clicked = c1.button("Crawl and refresh", type="primary", key=f"crawl_{key}", disabled=not n_sources,
                        help="Pulls new postings from the public feeds listed under Job postings > Crawl sources.")
    c2.caption(
        f"{n_sources} source(s) enabled. Last crawl: {last or 'never'}. Only public feeds are crawled "
        "(the SimplifyJobs GitHub list, Greenhouse and Lever boards). Handshake, LinkedIn and Indeed need a "
        "login or forbid crawling, so use **Job sites** and CSV import for those."
    )
    if clicked:
        with st.spinner("Fetching postings..."):
            summary = run_crawl()
        added = sum(r["added"] for r in summary)
        failed = [r for r in summary if r["error"]]
        msg = f"Added {added} new posting(s) from {len(summary) - len(failed)} source(s)."
        (st.warning if failed else st.success)(msg)
        for r in summary:
            if r["error"]:
                st.caption(f"{r['source']}: could not refresh ({r['error']}). Other sources were still updated.")
            else:
                st.caption(f"{r['source']}: {r['found']} matching posting(s), {r['added']} new.")


def apply_next_frame() -> pd.DataFrame:
    """Postings you have not applied to yet, plus applications still at Interested."""
    posts = load_df("postings")
    posts = posts[posts["status"].isin(["New", "Saved"]) & posts["application_id"].isna()] if not posts.empty else posts
    apps = load_df("applications")
    apps = apps[apps["status"] == "Interested"] if not apps.empty else apps
    rows = []
    for r in posts.to_dict("records"):
        rows.append(dict(key=f"p{r['id']}", kind="Posting" if r["status"] == "New" else "Saved posting",
                         company=r["company"], role=r["title"], relevance=r["relevance"], location=r["location"],
                         posted=r["date_posted"] if r["date_posted"] is not None and not pd.isna(r["date_posted"])
                         else r["date_found"], deadline=r["deadline"], why=r["reasons"], link=r["link"]))
    for r in apps.to_dict("records"):
        rows.append(dict(key=f"a{r['id']}", kind="Tracked, not applied", company=r["company"], role=r["role"],
                         relevance=None, location=r["location"], posted=r["date_found"], deadline=r["deadline"],
                         why=r["notes"], link=r["link"]))
    df = pd.DataFrame(rows, columns=["key", "kind", "company", "role", "relevance", "location", "posted",
                                     "deadline", "why", "link"])
    df["days_left"] = df["deadline"].apply(days_until)
    return df[df["days_left"].isna() | (df["days_left"] >= 0)]


def render_apply_next() -> None:
    st.subheader("Apply next")
    st.caption("Recent postings that fit your resume and that you have not applied to yet, together with jobs "
               "you are tracking as Interested.")
    df = apply_next_frame()
    if df.empty:
        st.info("Nothing waiting. Press **Crawl and refresh**, or add postings from **Job postings**.")
        return
    c1, c2, c3, c4 = st.columns(4)
    min_score = c1.slider("Minimum relevance", 0, 100, 45, step=5, key="an_score")
    posted_within = c2.selectbox("Posted", ["Any time", "Last 7 days", "Last 14 days", "Last 30 days"],
                                 index=2, key="an_posted")
    order = c3.selectbox("Sort by", ["Newest", "Deadline soonest", "Best match"], key="an_sort")
    text_f = c4.text_input("Search company / role", key="an_text")

    view = df[df["relevance"].isna() | (df["relevance"] >= min_score)].copy()
    if posted_within != "Any time":
        cutoff = date.today() - timedelta(days=int(posted_within.split()[1]))
        view = view[view["posted"].apply(lambda d: d is None or pd.isna(d) or d >= cutoff)
                    | (view["kind"] == "Tracked, not applied")]
    if text_f:
        view = view[view["company"].fillna("").str.contains(text_f, case=False, regex=False)
                    | view["role"].fillna("").str.contains(text_f, case=False, regex=False)]
    sort = {"Newest": (["posted", "relevance"], [False, False]),
            "Deadline soonest": (["deadline", "relevance"], [True, False]),
            "Best match": (["relevance", "posted"], [False, False])}[order]
    view = view.sort_values(sort[0], ascending=sort[1], na_position="last")

    m1, m2, m3 = st.columns(3)
    m1.metric("To apply", len(view))
    m2.metric("Strong match (70+)", int((view["relevance"].fillna(0) >= 70).sum()))
    m3.metric("Due in 14 days", int((view["days_left"].notna() & (view["days_left"] <= 14)).sum()))
    if view.empty:
        st.caption("Nothing matches these filters. Try a lower minimum relevance or a longer posted window.")
        return

    limit = 100
    if len(view) > limit:
        st.caption(f"Showing the top {limit} of {len(view)}. Narrow the filters to see others.")
    view = view.head(limit)
    view.insert(0, "select", False)
    shown = ["select", "kind", "relevance", "company", "role", "location", "posted", "deadline", "days_left",
             "why", "link", "key"]
    picked = st.data_editor(
        view[shown], hide_index=True, width="stretch", key="apply_next_editor",
        disabled=[c for c in shown if c != "select"],
        column_config={
            "select": st.column_config.CheckboxColumn("Pick"),
            "kind": st.column_config.TextColumn("Type"),
            "relevance": st.column_config.ProgressColumn("Relevance", min_value=0, max_value=100, format="%d"),
            "posted": st.column_config.DateColumn("Posted"),
            "deadline": st.column_config.DateColumn("Deadline"),
            "days_left": st.column_config.NumberColumn("Days left"),
            "link": st.column_config.LinkColumn("Link", display_text="apply"),
            "key": None,
        },
    )
    keys = list(picked.loc[picked["select"], "key"])
    post_ids = [int(k[1:]) for k in keys if k.startswith("p")]
    app_ids = [int(k[1:]) for k in keys if k.startswith("a")]
    c1, c2, c3 = st.columns(3)
    if c1.button(f"Mark {len(keys)} applied", type="primary", disabled=not keys):
        for pid in post_ids:
            posting_to_application(pid, status="Applied")
        mark_applied(app_ids)
        st.success(f"Marked {len(keys)} as Applied. They now appear under Applications.")
        st.rerun()
    if c2.button("Track as Interested", disabled=not post_ids,
                 help="Copies the picked postings into Applications without marking them applied."):
        for pid in post_ids:
            posting_to_application(pid)
        st.rerun()
    if c3.button("Dismiss", disabled=not post_ids, help="Hides the picked postings. Tracked jobs are not affected."):
        set_posting_status(post_ids, "Dismissed")
        st.rerun()


def page_dashboard() -> None:
    st.title("Summer 2027 Internship Dashboard")
    render_crawl_controls("dash")
    render_apply_next()
    st.divider()
    st.subheader("Applications")
    df = load_df("applications")
    if df.empty:
        st.info("No applications yet. Mark a posting above as applied, add one from **Add application**, "
                "or import a CSV.")
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


def render_crawl_sources() -> None:
    st.caption(
        "Public feeds that **Crawl and refresh** reads. For a company's own board, find its Greenhouse or Lever "
        "name in the careers page address: job-boards.greenhouse.io/**name** or jobs.lever.co/**name**. "
        "Only titles that mention intern, internship or co-op are kept."
    )
    with get_conn() as conn:
        src = pd.read_sql_query("SELECT * FROM crawl_sources ORDER BY id", conn)
    src["enabled"] = src["enabled"].astype(bool)
    edited = st.data_editor(
        src[["id", "enabled", "name", "kind", "target", "last_run", "last_status"]], hide_index=True,
        width="stretch", key="sources_editor", disabled=["id", "kind", "last_run", "last_status"],
        column_config={"id": None, "enabled": st.column_config.CheckboxColumn("On"),
                       "kind": st.column_config.TextColumn("Type"),
                       "target": st.column_config.TextColumn("Feed URL / board name")},
    )
    c1, c2 = st.columns([1, 3])
    if c1.button("Save sources"):
        with get_conn() as conn:
            for r in edited.to_dict("records"):
                conn.execute("UPDATE crawl_sources SET enabled=?, name=?, target=? WHERE id=?",
                             (int(bool(r["enabled"])), r["name"], r["target"], int(r["id"])))
        st.rerun()
    with st.form("add_source", clear_on_submit=True):
        c1, c2, c3 = st.columns([1, 1, 2])
        kind = c1.selectbox("Type", list(CRAWL_KINDS), format_func=CRAWL_KINDS.get)
        name = c2.text_input("Company / label *")
        target = c3.text_input("Board name or JSON URL *", placeholder="e.g. stripe")
        if st.form_submit_button("Add source"):
            if name.strip() and target.strip():
                with get_conn() as conn:
                    conn.execute("INSERT INTO crawl_sources (kind, name, target) VALUES (?, ?, ?)",
                                 (kind, name.strip(), target.strip()))
                st.rerun()
            else:
                st.error("Label and board name are required.")
    removable = {f"{r.name} ({r.kind})": int(r.id) for r in src.itertuples()}
    gone = st.multiselect("Remove sources", list(removable), key="rm_sources")
    if st.button("Remove selected sources", disabled=not gone):
        delete_rows("crawl_sources", [removable[g] for g in gone])
        st.rerun()


def page_relevant_jobs() -> None:
    st.title("Job postings")
    render_crawl_controls("postings")
    with st.expander("Crawl sources", expanded=False):
        render_crawl_sources()
    st.caption(
        "Job postings you have collected, scored 0-100 against your resume: internship, target role "
        "(SWE, bioinformatics, research, data), Summer 2027, open to sophomores, and resume skills. "
        "Senior, PhD, new-grad or expired postings are scored down."
    )

    with st.expander("Add a posting", expanded=False):
        with st.form("posting_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            company = c1.text_input("Company *")
            title = c2.text_input("Job title *")
            c1, c2, c3 = st.columns(3)
            source = c1.selectbox("Source site", SOURCES)
            location = c2.text_input("Location")
            pay = c3.text_input("Pay (if listed)")
            link = st.text_input("Posting link")
            c1, c2 = st.columns(2)
            date_posted = c1.date_input("Date posted", None)
            deadline = c2.date_input("Deadline", None)
            description = st.text_area("Job description (paste it for a better score)", height=150)
            if st.form_submit_button("Save posting", type="primary"):
                if company.strip() and title.strip():
                    pid = insert_posting(dict(company=company, title=title, source=source, location=location,
                                              pay=pay, link=link, date_posted=date_posted, deadline=deadline,
                                              description=description, date_found=date.today()))
                    with get_conn() as conn:
                        score = conn.execute("SELECT relevance FROM postings WHERE id=?", (pid,)).fetchone()[0]
                    st.success(f"Saved {company} - {title} (relevance {score}).")
                else:
                    st.error("Company and job title are required.")

    df = load_df("postings")
    if df.empty:
        st.info("No postings yet. Add one above, or import a CSV of postings from **Import / export** "
                "(try `sample_postings.csv`).")
        return

    with st.expander("Filters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        min_score = c1.slider("Minimum relevance", 0, 100, 40, step=5)
        status_f = c2.multiselect("Status", POSTING_STATUSES, default=["New", "Saved"])
        source_f = c3.multiselect("Source", sorted(df["source"].dropna().unique()))
        within = c4.selectbox("Deadline", ["Any", "Next 7 days", "Next 14 days", "Next 30 days", "Next 90 days"])
        c1, c2 = st.columns([3, 1])
        text_f = c1.text_input("Search company / title / description")
        hide_past = c2.checkbox("Hide past deadlines", value=True)

    view = df[df["relevance"].fillna(0) >= min_score].copy()
    if status_f:
        view = view[view["status"].isin(status_f)]
    if source_f:
        view = view[view["source"].isin(source_f)]
    view["days_left"] = view["deadline"].apply(days_until)
    if hide_past:
        view = view[view["days_left"].isna() | (view["days_left"] >= 0)]
    if within != "Any":
        n = int(within.split()[1])
        view = view[view["days_left"].notna() & (view["days_left"] <= n)]
    if text_f:
        mask = pd.Series(False, index=view.index)
        for col in ("company", "title", "description"):
            mask |= view[col].fillna("").str.contains(text_f, case=False, regex=False)
        view = view[mask]
    view = view.sort_values(["relevance", "deadline"], ascending=[False, True], na_position="last")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Relevant postings", len(view))
    c2.metric("Strong match (70+)", int((view["relevance"] >= 70).sum()))
    c3.metric("Due in 14 days", int((view["days_left"].notna() & (view["days_left"] <= 14)).sum()))
    c4.metric("All postings", len(df))

    if view.empty:
        st.caption("No postings match these filters. Try lowering the minimum relevance.")
        return

    if len(view) > 200:
        st.caption(f"Showing the top 200 of {len(view)}. Narrow the filters to see others.")
        view = view.head(200)
    view.insert(0, "select", False)
    shown = ["select", "id", "relevance", "company", "title", "location", "source", "deadline",
             "days_left", "matched_skills", "reasons", "status", "link"]
    picked = st.data_editor(
        view[shown], hide_index=True, width="stretch", key="postings_editor",
        disabled=[c for c in shown if c != "select"],
        column_config={
            "select": st.column_config.CheckboxColumn("Pick"),
            "id": st.column_config.NumberColumn("ID"),
            "relevance": st.column_config.ProgressColumn("Relevance", min_value=0, max_value=100, format="%d"),
            "deadline": st.column_config.DateColumn("Deadline"),
            "days_left": st.column_config.NumberColumn("Days left"),
            "matched_skills": st.column_config.TextColumn("Your skills"),
            "reasons": st.column_config.TextColumn("Why"),
            "link": st.column_config.LinkColumn("Link", display_text="open"),
        },
    )
    ids = [int(i) for i in picked.loc[picked["select"], "id"]]
    c1, c2, c3, c4 = st.columns(4)
    if c1.button(f"Add {len(ids)} to Applications", type="primary", disabled=not ids):
        for pid in ids:
            posting_to_application(pid)
        st.success(f"Added {len(ids)} posting(s) to Applications as Interested.")
        st.rerun()
    if c2.button("Mark saved", disabled=not ids):
        set_posting_status(ids, "Saved")
        st.rerun()
    if c3.button("Dismiss", disabled=not ids):
        set_posting_status(ids, "Dismissed")
        st.rerun()
    if c4.button("Delete", disabled=not ids):
        delete_rows("postings", ids)
        st.rerun()

    with st.expander("Rescore"):
        st.caption("Scores are saved when a posting is added. Rescore after editing RESUME_SKILLS or the "
                   "scoring terms at the top of app.py, or as deadlines pass.")
        if st.button("Rescore all postings"):
            st.success(f"Rescored {rescore_all_postings()} posting(s).")
            st.rerun()


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

    st.subheader("Import job postings from CSV")
    st.caption(
        "Postings go to **Job postings** and the Dashboard, where they are scored against your resume. Required: company, "
        "title. Optional: " + ", ".join(POSTING_COLUMNS[2:]) + ". Aliases like 'Company Name', 'Role', "
        "'Position', 'URL', 'Apply By', 'Job Description' also work. Try `sample_postings.csv`."
    )
    posting_aliases = {
        "company name": "company", "employer": "company", "organization": "company",
        "role": "title", "position": "title", "job title": "title",
        "url": "link", "apply link": "link", "posting url": "link", "application link": "link",
        "apply by": "deadline", "due date": "deadline", "expiration date": "deadline",
        "job description": "description", "details": "description", "summary": "description",
        "posted": "date_posted", "date posted": "date_posted", "salary": "pay",
        "site": "source", "board": "source",
    }
    up2 = st.file_uploader("Postings CSV file", type=["csv"], key="postings_csv")
    default_source2 = st.selectbox("Source to use when the CSV has none", SOURCES, key="postings_source")
    if up2 is not None:
        raw = pd.read_csv(up2)
        rename = {}
        for c in raw.columns:
            key = c.strip().lower()
            if key in POSTING_COLUMNS:
                rename[c] = key
            elif key.replace(" ", "_") in POSTING_COLUMNS:
                rename[c] = key.replace(" ", "_")
            elif key in posting_aliases:
                rename[c] = posting_aliases[key]
        df = raw.rename(columns=rename)
        df = df.loc[:, ~df.columns.duplicated()]
        if "company" not in df.columns or "title" not in df.columns:
            st.error(f"Could not find company and title columns. Found: {list(raw.columns)}")
        else:
            st.dataframe(df.head(20), width="stretch")
            if st.button(f"Import {len(df)} postings", type="primary"):
                existing_p = load_df("postings")
                seen = (set(zip(existing_p["company"].str.lower(), existing_p["title"].str.lower()))
                        if not existing_p.empty else set())
                added = 0
                for rec in df.to_dict("records"):
                    if not _clean(rec.get("company")) or not _clean(rec.get("title")):
                        continue
                    k = (str(rec["company"]).strip().lower(), str(rec["title"]).strip().lower())
                    if k in seen:
                        continue
                    seen.add(k)
                    if not _clean(rec.get("source")):
                        rec["source"] = default_source2
                    for dc in ("date_posted", "date_found", "deadline"):
                        if _clean(rec.get(dc)):
                            parsed = pd.to_datetime(rec[dc], errors="coerce")
                            rec[dc] = None if pd.isna(parsed) else parsed.date()
                    if not _clean(rec.get("date_found")):
                        rec["date_found"] = date.today()
                    insert_posting(rec)
                    added += 1
                st.success(f"Imported {added} posting(s). Open **Dashboard** or **Job postings** to see them ranked.")

    postings = load_df("postings")
    st.download_button("Download job postings CSV", postings.to_csv(index=False), "postings.csv", "text/csv",
                       disabled=postings.empty)

    st.subheader("Backup")
    st.caption(f"Your database file is `{DB_PATH}`. Copy it somewhere safe (or into cloud storage) to back up everything.")


# ---------------------------------------------------------------- main


def main() -> None:
    st.set_page_config(page_title="Internship Tracker 2027", page_icon=":briefcase:", layout="wide")
    init_db()
    pages = {
        "Dashboard": page_dashboard,
        "Job postings": page_relevant_jobs,
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
