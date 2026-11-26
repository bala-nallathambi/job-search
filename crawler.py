"""
Fetch internship postings from sources that publish them openly.

Only public, machine-readable feeds are used:
- The SimplifyJobs internship list on GitHub (a JSON file in a public repo).
- Greenhouse job boards (boards-api.greenhouse.io, the public Job Board API).
- Lever job boards (api.lever.co/v0/postings, the public Postings API).

Handshake, LinkedIn, Indeed and similar sites need a login or forbid automated access in their
terms, so they are not crawled. Use the saved-search links and CSV import for those.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

USER_AGENT = "internship-tracker/1.0 (personal job search tool)"
TIMEOUT = 30

SIMPLIFY_DEFAULT_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
)
INTERN_TITLE = re.compile(r"\b(intern|interns|internship|co-?op|summer student|student researcher)\b", re.I)


class CrawlError(Exception):
    """A source could not be fetched or parsed."""


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise CrawlError(f"HTTP {e.code} from {urllib.parse.urlparse(url).netloc}") from e
    except urllib.error.URLError as e:
        raise CrawlError(f"Could not reach {urllib.parse.urlparse(url).netloc}: {e.reason}") from e
    except TimeoutError as e:
        raise CrawlError(f"Timed out after {TIMEOUT}s reaching {urllib.parse.urlparse(url).netloc}") from e
    except (ValueError, UnicodeDecodeError) as e:
        raise CrawlError("The response was not valid JSON") from e


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


def _degree_note(degrees: list[str]) -> str:
    # Mention graduate degrees only when undergraduates are not eligible, so scoring can penalize those.
    if not degrees or any("bachelor" in d.lower() for d in degrees):
        return "Open to undergraduates." if degrees else ""
    return f"Degrees: {', '.join(degrees)} only."


def parse_simplify(data, term: str = "Summer 2027") -> list[dict]:
    if not isinstance(data, list):
        raise CrawlError("Unexpected format for the SimplifyJobs list")
    out = []
    for item in data:
        if not isinstance(item, dict) or not item.get("active") or not item.get("is_visible", True):
            continue
        terms = item.get("terms") or []
        if term and term not in terms:
            continue
        url = item.get("url")
        if not url or not item.get("company_name") or not item.get("title"):
            continue
        locations = item.get("locations") or []
        desc_bits = [
            f"Category: {item.get('category')}" if item.get("category") else "",
            f"Terms: {', '.join(terms)}" if terms else "",
            _degree_note(item.get("degrees") or []),
            f"Sponsorship: {item.get('sponsorship')}" if item.get("sponsorship") else "",
            "Internship listing from the SimplifyJobs GitHub list.",
        ]
        out.append(dict(
            company=item["company_name"],
            title=item["title"],
            location="; ".join(locations[:3]) + (" ..." if len(locations) > 3 else ""),
            link=url,
            description=" ".join(b for b in desc_bits if b),
            date_posted=_date_from_epoch(item.get("date_posted")),
        ))
    return out


def parse_greenhouse(data, company: str) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise CrawlError("Unexpected format from Greenhouse")
    out = []
    for job in data["jobs"]:
        title = job.get("title") or ""
        if not INTERN_TITLE.search(title) or not job.get("absolute_url"):
            continue
        out.append(dict(
            company=company,
            title=title,
            location=(job.get("location") or {}).get("name"),
            link=job["absolute_url"],
            description=_strip_html(job.get("content"))[:5000],
            date_posted=_date_from_iso(job.get("first_published") or job.get("updated_at")),
        ))
    return out


def parse_lever(data, company: str) -> list[dict]:
    if not isinstance(data, list):
        raise CrawlError("Unexpected format from Lever")
    out = []
    for job in data:
        title = job.get("text") or ""
        url = job.get("hostedUrl")
        if not INTERN_TITLE.search(title) or not url:
            continue
        cats = job.get("categories") or {}
        out.append(dict(
            company=company,
            title=title,
            location=cats.get("location"),
            link=url,
            description=(job.get("descriptionPlain") or _strip_html(job.get("description")))[:5000],
            date_posted=_date_from_epoch(job.get("createdAt"), millis=True),
        ))
    return out


def crawl_source(kind: str, target: str, name: str | None = None, term: str = "Summer 2027") -> list[dict]:
    """Return normalized postings for one source. Raises CrawlError on failure."""
    target = (target or "").strip()
    if kind == "simplify":
        return parse_simplify(fetch_json(target or SIMPLIFY_DEFAULT_URL), term)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", target):
        raise CrawlError(f"'{target}' is not a valid board name (letters, digits, - and _ only)")
    company = name or target
    if kind == "greenhouse":
        return parse_greenhouse(
            fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{target}/jobs?content=true"), company)
    if kind == "lever":
        return parse_lever(fetch_json(f"https://api.lever.co/v0/postings/{target}?mode=json"), company)
    raise CrawlError(f"Unknown source type '{kind}'")
