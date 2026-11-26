"""
Fetch internship postings from sources that publish them openly.

Only public, machine-readable feeds are used:
- GitHub internship lists: JSON files (SimplifyJobs format) or Markdown tables in a public README.
- Job board APIs that are public by design: The Muse, Remotive, RemoteOK, USAJobs (free key).
- Company job boards on Greenhouse, Lever and Ashby, through their public posting APIs.

Handshake, LinkedIn, Indeed, Internships.com and similar sites need a login or forbid automated
access in their terms, so they are not crawled. NOT_CRAWLED lists them with links to search by hand.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

USER_AGENT = "internship-tracker/1.0 (personal job search tool)"
TIMEOUT = 20

SIMPLIFY_DEFAULT_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
)
INTERN_TITLE = re.compile(r"\b(intern|interns|internship|internships|co-?op|summer student|student researcher)\b",
                          re.I)

KINDS = {
    "simplify": "GitHub list (JSON)",
    "github_readme": "GitHub list (README table)",
    "themuse": "The Muse API",
    "remotive": "Remotive API",
    "remoteok": "RemoteOK API",
    "usajobs": "USAJobs API",
    "greenhouse": "Greenhouse board",
    "lever": "Lever board",
    "ashby": "Ashby board",
}
CATEGORY = {
    "simplify": "GitHub lists", "github_readme": "GitHub lists",
    "themuse": "Job board APIs", "remotive": "Job board APIs", "remoteok": "Job board APIs",
    "usajobs": "Job board APIs",
    "greenhouse": "Company boards", "lever": "Company boards", "ashby": "Company boards",
}

# Sources added to a new database. `on` means enabled by default; only sources confirmed to respond
# when this list was written are on. Use "Check sources" in the app to test and turn on the rest.
PRESETS = [
    # key, kind, name, target, term, on
    ("simplify-summer-2027", "simplify", "SimplifyJobs Summer 2027 internships", SIMPLIFY_DEFAULT_URL,
     "Summer 2027", True),
    ("vanshb03-summer-2027", "simplify", "vanshb03 Summer 2027 internships",
     "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json",
     "Summer", True),
    ("speedyapply-2027-swe", "github_readme", "SpeedyApply 2027 SWE college jobs",
     "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/README.md", "", True),
    ("simplify-offseason", "simplify", "SimplifyJobs off-season (Fall 2026 - Spring 2027)", SIMPLIFY_DEFAULT_URL,
     "Fall 2026, Winter 2027, Spring 2027", False),
    ("themuse-internships", "themuse", "The Muse internships", "Internship", "", False),
    ("remotive-intern", "remotive", "Remotive remote internships", "intern", "", False),
    ("remoteok-intern", "remoteok", "RemoteOK remote internships", "", "", False),
    ("usajobs-students", "usajobs", "USAJobs student internships (needs free API key)", "intern", "", False),
    *[(f"gh-{t}", "greenhouse", n, t, "", False) for t, n in [
        ("stripe", "Stripe"), ("databricks", "Databricks"), ("robinhood", "Robinhood"), ("figma", "Figma"),
        ("discord", "Discord"), ("cloudflare", "Cloudflare"), ("duolingo", "Duolingo"), ("roblox", "Roblox"),
        ("airbnb", "Airbnb"), ("pinterest", "Pinterest"), ("asana", "Asana"), ("gitlab", "GitLab"),
        ("twilio", "Twilio"), ("datadog", "Datadog"), ("verkada", "Verkada"), ("anduril", "Anduril"),
    ]],
    *[(f"lever-{t}", "lever", n, t, "", False) for t, n in [
        ("palantir", "Palantir"), ("plaid", "Plaid"), ("spotify", "Spotify"),
    ]],
    *[(f"ashby-{t}", "ashby", n, t, "", False) for t, n in [
        ("notion", "Notion"), ("ramp", "Ramp"), ("linear", "Linear"), ("openai", "OpenAI"),
    ]],
]

# Presets that "Check sources" tests but leaves for you to turn on.
OPT_IN_PRESETS = {"simplify-offseason"}

# Sites that need a login or forbid crawling: shown in the app with a link instead.
NOT_CRAWLED = [
    ("Handshake", "https://app.joinhandshake.com/stu/postings?query=intern",
     "Login required (UMD account). Copy postings in or import a CSV."),
    ("LinkedIn Jobs", "https://www.linkedin.com/jobs/search/?keywords=intern%20summer%202027&f_E=1",
     "Terms of service forbid automated access."),
    ("Indeed", "https://www.indeed.com/jobs?q=intern+summer+2027", "Terms of service forbid automated access."),
    ("Internships.com", "https://www.internships.com/", "No public feed or API."),
    ("Glassdoor", "https://www.glassdoor.com/Job/intern-jobs-SRCH_KO0,6.htm",
     "Login required; terms forbid automated access."),
    ("Wellfound", "https://wellfound.com/jobs?query=intern", "Login required; no public API."),
    ("WayUp", "https://www.wayup.com/s/internships/", "No public API."),
    ("RippleMatch", "https://ripplematch.com/", "Login required."),
    ("Simplify.jobs website", "https://simplify.jobs/jobs?experience=Internship",
     "Use the SimplifyJobs GitHub list above instead (same postings)."),
]


class CrawlError(Exception):
    """A source could not be fetched or parsed."""


def _host(url: str) -> str:
    return urllib.parse.urlparse(url).netloc


def fetch(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        hint = " (board name not found)" if e.code == 404 else ""
        raise CrawlError(f"HTTP {e.code} from {_host(url)}{hint}") from e
    except urllib.error.URLError as e:
        raise CrawlError(f"Could not reach {_host(url)}: {e.reason}") from e
    except TimeoutError as e:
        raise CrawlError(f"Timed out after {TIMEOUT}s reaching {_host(url)}") from e


def fetch_json(url: str, headers: dict | None = None):
    data = fetch(url, {"Accept": "application/json", **(headers or {})})
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise CrawlError(f"{_host(url)} did not return valid JSON") from e


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _date_from_epoch(value, millis: bool = False) -> str | None:
    try:
        ts = float(value) / (1000 if millis else 1)
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _date_from_iso(value) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _posting(company, title, link, location=None, description="", date_posted=None, deadline=None, pay=None):
    return dict(company=company, title=title, link=link, location=location, description=description,
                date_posted=date_posted, deadline=deadline, pay=pay)


# ---------------------------------------------------------------- GitHub lists


def _degree_note(degrees: list[str]) -> str:
    # Mention graduate degrees only when undergraduates are not eligible, so scoring can penalize those.
    if not degrees or any("bachelor" in d.lower() for d in degrees):
        return "Open to undergraduates." if degrees else ""
    return f"Degrees: {', '.join(degrees)} only."


def _term_matches(item: dict, terms_wanted: list[str]) -> bool:
    if not terms_wanted:
        return True
    terms = item.get("terms") or []
    season = item.get("season") or ""
    for want in terms_wanted:
        if want in terms:
            return True
        # Lists that give only a season ("Summer") are per-year repos, so match the season word alone.
        if season and want.split()[0].lower() in season.lower():
            return True
    return False


def parse_simplify(data, term: str = "Summer 2027") -> list[dict]:
    if not isinstance(data, list):
        raise CrawlError("Unexpected format for a GitHub JSON list")
    wanted = [t.strip() for t in (term or "").split(",") if t.strip()]
    out = []
    for item in data:
        if not isinstance(item, dict) or not item.get("active") or not item.get("is_visible", True):
            continue
        if not _term_matches(item, wanted):
            continue
        url = item.get("url")
        if not url or not item.get("company_name") or not item.get("title"):
            continue
        terms = item.get("terms") or ([item["season"]] if item.get("season") else [])
        locations = item.get("locations") or []
        desc_bits = [
            f"Category: {item.get('category')}" if item.get("category") else "",
            f"Terms: {', '.join(terms)}" if terms else "",
            _degree_note(item.get("degrees") or []),
            f"Sponsorship: {item.get('sponsorship')}" if item.get("sponsorship") else "",
            "Internship listing from a GitHub internship list.",
        ]
        out.append(_posting(
            item["company_name"], item["title"], url,
            location="; ".join(locations[:3]) + (" ..." if len(locations) > 3 else ""),
            description=" ".join(b for b in desc_bits if b),
            date_posted=_date_from_epoch(item.get("date_posted")),
        ))
    return out


def _cell_text(cell: str) -> str:
    return _strip_html(re.sub(r"\*\*|__", "", cell)).strip()


def _cell_link(cell: str) -> str | None:
    m = re.search(r'href="([^"]+)"', cell) or re.search(r"\]\((https?://[^)\s]+)\)", cell)
    return html.unescape(m.group(1)) if m else None


def _age_to_date(age: str) -> str | None:
    m = re.fullmatch(r"\s*(\d+)\s*(d|mo|w|h)\s*", age or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    days = {"h": 0, "d": n, "w": 7 * n, "mo": 30 * n}[unit]
    return (date.today() - timedelta(days=days)).isoformat()


def parse_readme_tables(text: str) -> list[dict]:
    """Parse Markdown tables with Company / Position (or Role) / Location / ... / link columns."""
    out, header, last_company = [], None, ""
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        low = [_cell_text(c).lower() for c in cells]
        if "company" in low and any(k in low for k in ("position", "role", "title")):
            header = low
            continue
        if header is None or set("".join(cells)) <= set("-: "):
            continue
        row = dict(zip(header, cells))
        title = _cell_text(row.get("position") or row.get("role") or row.get("title") or "")
        company = _cell_text(row.get("company", ""))
        if company in ("↳", ""):
            company = last_company
        last_company = company
        link = None
        for k in ("posting", "application", "apply", "link", "application/link"):
            if row.get(k):
                link = _cell_link(row[k])
                if link:
                    break
        if not link:
            link = _cell_link(row.get("position") or row.get("role") or "")
        if not (company and title and link) or "🔒" in "".join(cells):
            continue
        desc = "Listing from a GitHub internship list."
        if row.get("salary"):
            desc += f" Pay: {_cell_text(row['salary'])}."
        out.append(_posting(company, title, link, location=_cell_text(row.get("location", "")), description=desc,
                            date_posted=_age_to_date(_cell_text(row.get("age", "") or row.get("date posted", ""))),
                            pay=_cell_text(row.get("salary", "")) or None))
    if not out:
        raise CrawlError("No job tables found in that README")
    return out


# ---------------------------------------------------------------- job board APIs


def parse_themuse(pages: list) -> list[dict]:
    out = []
    for data in pages:
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise CrawlError("Unexpected format from The Muse")
        for job in data["results"]:
            link = (job.get("refs") or {}).get("landing_page")
            if not link or not job.get("name"):
                continue
            out.append(_posting(
                (job.get("company") or {}).get("name") or "Unknown", job["name"], link,
                location="; ".join(loc.get("name", "") for loc in (job.get("locations") or [])[:3]),
                description=_strip_html(job.get("contents"))[:5000] + " Internship.",
                date_posted=_date_from_iso(job.get("publication_date")),
            ))
    return out


def parse_remotive(data) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise CrawlError("Unexpected format from Remotive")
    return [_posting(j.get("company_name") or "Unknown", j["title"], j["url"],
                     location=j.get("candidate_required_location") or "Remote",
                     description=_strip_html(j.get("description"))[:5000],
                     date_posted=_date_from_iso(j.get("publication_date")), pay=j.get("salary") or None)
            for j in data["jobs"] if j.get("url") and INTERN_TITLE.search(j.get("title") or "")]


def parse_remoteok(data) -> list[dict]:
    if not isinstance(data, list):
        raise CrawlError("Unexpected format from RemoteOK")
    out = []
    for j in data:
        if not isinstance(j, dict) or not j.get("position") or not j.get("url"):
            continue  # the first element is RemoteOK's legal notice
        if not INTERN_TITLE.search(j["position"]):
            continue
        out.append(_posting(j.get("company") or "Unknown", j["position"], j["url"],
                            location=j.get("location") or "Remote",
                            description=_strip_html(j.get("description"))[:5000],
                            date_posted=_date_from_iso(j.get("date"))))
    return out


def parse_usajobs(data) -> list[dict]:
    try:
        items = data["SearchResult"]["SearchResultItems"]
    except (KeyError, TypeError) as e:
        raise CrawlError("Unexpected format from USAJobs") from e
    out = []
    for it in items:
        d = it.get("MatchedObjectDescriptor") or {}
        if not d.get("PositionURI") or not d.get("PositionTitle"):
            continue
        summary = ((d.get("UserArea") or {}).get("Details") or {}).get("JobSummary") or ""
        out.append(_posting(d.get("OrganizationName") or d.get("DepartmentName") or "US Government",
                            d["PositionTitle"], d["PositionURI"], location=d.get("PositionLocationDisplay"),
                            description=_strip_html(summary)[:5000] + " Student internship.",
                            date_posted=_date_from_iso(d.get("PublicationStartDate")),
                            deadline=_date_from_iso(d.get("ApplicationCloseDate"))))
    return out


# ---------------------------------------------------------------- company boards


def parse_greenhouse(data, company: str) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise CrawlError("Unexpected format from Greenhouse")
    return [_posting(company, j["title"], j["absolute_url"], location=(j.get("location") or {}).get("name"),
                     description=_strip_html(j.get("content"))[:5000],
                     date_posted=_date_from_iso(j.get("first_published") or j.get("updated_at")))
            for j in data["jobs"] if j.get("absolute_url") and INTERN_TITLE.search(j.get("title") or "")]


def parse_lever(data, company: str) -> list[dict]:
    if not isinstance(data, list):
        raise CrawlError("Unexpected format from Lever")
    return [_posting(company, j["text"], j["hostedUrl"], location=(j.get("categories") or {}).get("location"),
                     description=(j.get("descriptionPlain") or _strip_html(j.get("description")))[:5000],
                     date_posted=_date_from_epoch(j.get("createdAt"), millis=True))
            for j in data if j.get("hostedUrl") and INTERN_TITLE.search(j.get("text") or "")]


def parse_ashby(data, company: str) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise CrawlError("Unexpected format from Ashby")
    return [_posting(company, j["title"], j.get("jobUrl") or j.get("applyUrl"), location=j.get("location"),
                     description=(j.get("descriptionPlain") or _strip_html(j.get("descriptionHtml")))[:5000],
                     date_posted=_date_from_iso(j.get("publishedAt")))
            for j in data["jobs"]
            if (j.get("jobUrl") or j.get("applyUrl")) and j.get("isListed", True)
            and INTERN_TITLE.search(j.get("title") or "")]


# ---------------------------------------------------------------- entry point


def _board(target: str) -> str:
    target = (target or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", target):
        raise CrawlError(f"'{target}' is not a valid board name (letters, digits, - and _ only)")
    return urllib.parse.quote(target)


def crawl_source(kind: str, target: str, name: str | None = None, term: str = "Summer 2027") -> list[dict]:
    """Return normalized postings for one source. Raises CrawlError on failure."""
    target = (target or "").strip()
    company = name or target
    if kind == "simplify":
        return parse_simplify(fetch_json(target or SIMPLIFY_DEFAULT_URL), term)
    if kind == "github_readme":
        if not target.startswith("https://"):
            raise CrawlError("Give the raw README URL (https://raw.githubusercontent.com/...)")
        return parse_readme_tables(fetch(target).decode("utf-8", errors="replace"))
    if kind == "themuse":
        level = urllib.parse.quote(target or "Internship")
        pages = [fetch_json(f"https://www.themuse.com/api/public/jobs?level={level}&page={p}") for p in range(5)]
        return parse_themuse(pages)
    if kind == "remotive":
        q = urllib.parse.quote(target or "intern")
        return parse_remotive(fetch_json(f"https://remotive.com/api/remote-jobs?search={q}"))
    if kind == "remoteok":
        return parse_remoteok(fetch_json("https://remoteok.com/api"))
    if kind == "usajobs":
        key, email = os.environ.get("USAJOBS_API_KEY"), os.environ.get("USAJOBS_EMAIL")
        if not key or not email:
            raise CrawlError("Add USAJOBS_API_KEY and USAJOBS_EMAIL to your .env file (free key from "
                             "developer.usajobs.gov)")
        q = urllib.parse.quote(target or "intern")
        return parse_usajobs(fetch_json(
            f"https://data.usajobs.gov/api/search?Keyword={q}&HiringPath=student&ResultsPerPage=250",
            {"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key}))
    if kind == "greenhouse":
        return parse_greenhouse(
            fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{_board(target)}/jobs?content=true"), company)
    if kind == "lever":
        return parse_lever(fetch_json(f"https://api.lever.co/v0/postings/{_board(target)}?mode=json"), company)
    if kind == "ashby":
        return parse_ashby(fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{_board(target)}"), company)
    raise CrawlError(f"Unknown source type '{kind}'")
