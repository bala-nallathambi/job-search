"""
Tailor the resume to one job.

Two modes:
- AI (Claude): rewrites emphasis and wording for the job, using only facts already on the resume.
- Keyword only (no AI, no network): reorders bullets and skills by how well they match the job
  description, and lists job keywords the resume does not mention yet.

Neither mode adds experience, skills, dates or numbers that are not on the resume.
The resume is written as simple Markdown: "# Name", "## SECTION", "### Entry", "- bullet", plain lines.
"""

from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5-5"
MODEL_CHOICES = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]

BULLET_CHARS = "●•▪◦‣∙·*-–"
DATE_RE = re.compile(
    r"\b(19|20)\d{2}\b|\bPresent\b|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}", re.I
)
STOPWORDS = set("""
a an and are as at be by for from has have in into is it its of on or our that the their this to we will with
you your who what when where how not but can all any more most other some such than then there these they
been being do does did using use used work working team teams role roles job jobs intern interns internship
internships summer 2026 2027 student students experience strong ability skills including include includes
etc per new well able across within help helping support supporting opportunity opportunities candidate
candidates preferred required requirements responsibilities qualifications must plus about also may
""".split())

# Terms a job may ask for; used to list "missing keywords" and to flag invented skills in AI output.
TECH_TERMS = [
    "C++", "C#", "C", "Go", "Golang", "Rust", "Java", "Python", "JavaScript", "TypeScript", "HTML", "CSS",
    "SQL", "NoSQL", "R", "MATLAB", "Kotlin", "Swift", "Scala", "Ruby", "PHP", "Bash", "Shell",
    "React", "Angular", "Vue", "Node", "Node.js", "Django", "Flask", "FastAPI", "Spring", "Express",
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Linux", "Git", "CI/CD", "REST", "REST API", "GraphQL",
    "JUnit", "pytest", "unit testing", "Agile", "Scrum", "pandas", "NumPy", "scikit-learn", "PyTorch",
    "TensorFlow", "machine learning", "deep learning", "statistics", "data analysis", "data structures",
    "algorithms", "object-oriented", "OCR", "web scraping", "BLAST", "SnapGene", "GenBank", "genomics",
    "sequencing", "DNA sequencing", "PCR", "wet lab", "biostatistics", "bioinformatics", "Arduino",
    "3D printing", "Excel", "Tableau", "Jupyter", "Google Colab", "Figma", "HPC",
]


# ---------------------------------------------------------------- resume text


def extract_resume_text(data: bytes, filename: str = "") -> str:
    name = filename.lower()
    if name.endswith(".pdf") or data[:4] == b"%PDF":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages).strip()
    if name.endswith(".docx"):
        import docx

        d = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in d.paragraphs).strip()
    return data.decode("utf-8", errors="replace").strip()


def find_local_resume(folder: Path) -> Path | None:
    if not folder.is_dir():
        return None
    files = sorted([*folder.glob("*.pdf"), *folder.glob("*.docx"), *folder.glob("*.txt"), *folder.glob("*.md")])
    return files[0] if files else None


def _is_heading(line: str) -> bool:
    s = line.strip()
    letters = re.sub(r"[^A-Za-z]", "", s)
    return (3 <= len(s) <= 40 and letters.isupper() and len(letters) >= 4 and ":" not in s
            and not DATE_RE.search(s))


def _is_bullet(line: str) -> bool:
    return bool(line.strip()) and line.strip()[0] in BULLET_CHARS


def _bullet_text(line: str) -> str:
    return line.strip().lstrip(BULLET_CHARS).strip()


def resume_to_markdown(text: str) -> str:
    """Turn plain resume text (from a PDF) into the simple Markdown format. Already-Markdown text is kept."""
    if re.search(r"^## ", text, re.M):
        return text.strip()
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: list[str] = []
    in_sections = False
    prev_bullet = False
    first = True
    for raw in lines:
        line = raw.strip()
        if not line:
            prev_bullet = False
            continue
        if first:
            out.append(f"# {line}")
            first = False
            continue
        if _is_heading(line):
            out.append("")
            out.append(f"## {line}")
            in_sections, prev_bullet = True, False
            continue
        if _is_bullet(line):
            out.append(f"- {_bullet_text(line)}")
            prev_bullet = True
            continue
        if prev_bullet and not DATE_RE.search(line):
            out[-1] = f"{out[-1]} {line}"  # wrapped bullet line from the PDF
            continue
        if in_sections and DATE_RE.search(line) and ":" not in line.split()[0]:
            out.append(f"### {line}")
        else:
            out.append(line)
        prev_bullet = False
    return "\n".join(out).strip()


def parse_markdown(md: str) -> list[dict]:
    """Split into blocks: header lines, then sections, each with entries holding lines and bullets."""
    sections: list[dict] = [{"heading": None, "entries": [{"title": None, "lines": [], "bullets": []}]}]
    for line in md.splitlines():
        s = line.rstrip()
        if s.startswith("## "):
            sections.append({"heading": s[3:].strip(), "entries": [{"title": None, "lines": [], "bullets": []}]})
        elif s.startswith("### "):
            sections[-1]["entries"].append({"title": s[4:].strip(), "lines": [], "bullets": []})
        elif s.startswith("- "):
            sections[-1]["entries"][-1]["bullets"].append(s[2:].strip())
        elif s.strip():
            sections[-1]["entries"][-1]["lines"].append(s)
    return sections


def render_markdown(sections: list[dict]) -> str:
    out: list[str] = []
    for sec in sections:
        if sec["heading"]:
            out += ["", f"## {sec['heading']}"]
        for e in sec["entries"]:
            if e["title"]:
                out.append(f"### {e['title']}")
            out += e["lines"]
            out += [f"- {b}" for b in e["bullets"]]
    return "\n".join(out).strip()


# ---------------------------------------------------------------- keyword matching


def _mentions(text: str, term: str) -> bool:
    t = term.lower()
    if len(t) <= 3 or not t.isalpha():
        return re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9+#])", text) is not None
    return t in text


def job_keywords(job_text: str, limit: int = 40) -> list[str]:
    """Tech terms the job mentions, plus its most frequent meaningful words."""
    low = job_text.lower()
    found = [t for t in TECH_TERMS if _mentions(low, t)]
    words = re.findall(r"[a-z][a-z+#.\-]{2,}", low)
    freq: dict[str, int] = {}
    for w in words:
        w = w.strip(".-")
        if w in STOPWORDS or len(w) < 4:
            continue
        freq[w] = freq.get(w, 0) + 1
    common = [w for w, c in sorted(freq.items(), key=lambda kv: -kv[1]) if c >= 2]
    seen = {f.lower() for f in found}
    return found + [w for w in common if w not in seen][: max(0, limit - len(found))]


def _relevance(text: str, keywords: list[str]) -> int:
    low = text.lower()
    return sum(3 if k in TECH_TERMS else 1 for k in keywords if _mentions(low, k))


def keyword_tailor(resume_md: str, job_title: str, job_text: str) -> dict:
    """Reorder (never add) resume content by relevance to the job. Returns the same shape as ai_tailor."""
    keywords = job_keywords(f"{job_title}\n{job_text}")
    sections = parse_markdown(resume_md)
    changes: list[str] = []
    for sec in sections:
        if not sec["heading"]:
            continue
        is_skills = "skill" in sec["heading"].lower()
        for e in sec["entries"]:
            if e["bullets"]:
                ranked = sorted(e["bullets"], key=lambda b: -_relevance(b, keywords))
                if ranked != e["bullets"]:
                    where = e["title"] or sec["heading"].title()
                    changes.append(f"Moved the most relevant bullet to the top under {where}.")
                    e["bullets"] = ranked
            if is_skills:
                new_bullets = []
                for b in e["bullets"]:
                    label, sep, items = b.partition(":")
                    if not sep:
                        new_bullets.append(b)
                        continue
                    parts = [p.strip() for p in items.split(",") if p.strip()]
                    ranked = sorted(parts, key=lambda p: 0 if _relevance(p, keywords) else 1)
                    if ranked != parts:
                        changes.append(f"Listed job-relevant {label.strip()} first.")
                    new_bullets.append(f"{label}: {', '.join(ranked)}")
                e["bullets"] = new_bullets
        # Put the most relevant entries (projects, experience) first within a section, keeping entry 0 lines.
        titled = [e for e in sec["entries"] if e["title"]]
        if len(titled) > 1 and not is_skills and "education" not in sec["heading"].lower():
            ranked = sorted(titled, key=lambda e: -_relevance(" ".join([e["title"], *e["lines"], *e["bullets"]]),
                                                               keywords))
            if ranked != titled:
                changes.append(f"Put the most relevant entry first in {sec['heading'].title()}.")
                sec["entries"] = [e for e in sec["entries"] if not e["title"]] + ranked
    low_resume = resume_md.lower()
    matched = [k for k in keywords if _mentions(low_resume, k)]
    missing = [k for k in keywords if k in TECH_TERMS and not _mentions(low_resume, k)]
    if not changes:
        changes.append("The resume order already fits this job; nothing was moved.")
    return dict(
        resume_markdown=render_markdown(sections),
        changes=changes,
        keywords_used=matched,
        missing_keywords=missing,
        warnings=[],
        method="keyword",
        model=None,
    )


# ---------------------------------------------------------------- AI tailoring

SYSTEM_PROMPT = """You tailor a student's resume to one job posting.

The resume you are given is the only source of facts. Your job is to change emphasis, order and wording,
never the facts:
- Do not add any employer, project, course, award, skill, tool, technology, number, metric or date that is
  not already on the resume. Do not upgrade a claim (for example "used" to "led", or adding a percentage).
- You may reorder sections, entries, bullets and skills so the most relevant come first; rephrase a bullet
  to use the job's words when the bullet already describes that thing; tighten wording; and drop or merge
  low-relevance bullets if the resume would otherwise run past one page.
- Keep every entry's name, title, organization, location and dates exactly as written.
- Keep contact details exactly as written.
- A job keyword the resume does not support goes in missing_keywords, never into the resume.

Write the resume in this Markdown format and nothing else:
# Full Name
contact line
## SECTION NAME
### Entry heading with dates as on the resume
plain line (role, degree, GPA and similar)
- bullet

In changes, list each change as one short sentence a student can check against the original."""

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "resume_markdown": {"type": "string"},
        "changes": {"type": "array", "items": {"type": "string"}},
        "keywords_used": {"type": "array", "items": {"type": "string"}},
        "missing_keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["resume_markdown", "changes", "keywords_used", "missing_keywords"],
    "additionalProperties": False,
}


class TailorError(Exception):
    pass


def load_dotenv(folder: Path) -> None:
    """Read KEY=VALUE lines from folder/.env into os.environ (without overriding what is already set)."""
    env = folder / ".env"
    if not env.is_file():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def api_key_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def invented_terms(original_md: str, tailored_md: str) -> list[str]:
    """Tech terms in the tailored resume that the original never mentions (a sign of invented skills)."""
    a, b = original_md.lower(), tailored_md.lower()
    return [t for t in TECH_TERMS if _mentions(b, t) and not _mentions(a, t)]


def ai_tailor(resume_md: str, company: str, job_title: str, job_text: str, model: str = DEFAULT_MODEL) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    user = (
        f"<resume>\n{resume_md}\n</resume>\n\n"
        f"<job>\nCompany: {company}\nTitle: {job_title}\n\n{job_text}\n</job>\n\n"
        "Tailor the resume to this job, following the rules."
    )
    kwargs = dict(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
    )
    try:
        if model in ("claude-opus-5-5", "claude-sonnet-5-5"):
            # Server-side fallback: if a safety classifier declines, the API retries on a fallback model.
            response = client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            response = client.messages.create(**kwargs)
    except anthropic.AuthenticationError as e:
        raise TailorError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in your .env file.") from e
    except anthropic.PermissionDeniedError as e:
        raise TailorError(f"This API key cannot use {model}.") from e
    except anthropic.NotFoundError as e:
        raise TailorError(f"Model {model} was not found for this API key.") from e
    except anthropic.RateLimitError as e:
        raise TailorError("Rate limited by the Anthropic API. Wait a minute and try again.") from e
    except anthropic.APIStatusError as e:
        raise TailorError(f"Anthropic API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise TailorError("Could not reach the Anthropic API. Check your internet connection.") from e

    if response.stop_reason == "refusal":
        raise TailorError("Claude declined this request. Try the keyword-only mode.")
    if response.stop_reason == "max_tokens":
        raise TailorError("The response was cut off. Try again, or shorten the job description.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise TailorError("Claude returned an unreadable response. Try again.") from e

    warnings = []
    extra = invented_terms(resume_md, data["resume_markdown"])
    if extra:
        warnings.append("These terms are in the tailored resume but not in your original. Remove them unless "
                        "they are true: " + ", ".join(extra))
    return dict(data, warnings=warnings, method="ai", model=response.model)


# ---------------------------------------------------------------- export


_PDF_REPLACEMENTS = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "•": "-", "●": "-",
                     "…": "...", " ": " "}


def _latin1(text: str) -> str:
    for a, b in _PDF_REPLACEMENTS.items():
        text = text.replace(a, b)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _strip_md(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


def to_docx(md: str) -> bytes:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    d = docx.Document()
    style = d.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    for sec in d.sections:
        sec.top_margin = sec.bottom_margin = sec.left_margin = sec.right_margin = Pt(40)
    first_line = True
    for line in md.splitlines():
        s = line.rstrip()
        if not s.strip():
            continue
        if s.startswith("# "):
            p = d.add_paragraph()
            r = p.add_run(_strip_md(s[2:]))
            r.bold, r.font.size = True, Pt(18)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            first_line = True
            continue
        if first_line and not s.startswith(("#", "- ")):
            p = d.add_paragraph(_strip_md(s))
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            continue
        first_line = False
        if s.startswith("## "):
            p = d.add_paragraph()
            r = p.add_run(_strip_md(s[3:]).upper())
            r.bold, r.font.size = True, Pt(12)
            p.paragraph_format.space_before = Pt(8)
        elif s.startswith("### "):
            p = d.add_paragraph()
            p.add_run(_strip_md(s[4:])).bold = True
            p.paragraph_format.space_after = Pt(0)
        elif s.startswith("- "):
            p = d.add_paragraph(_strip_md(s[2:]), style="List Bullet")
            p.paragraph_format.space_after = Pt(0)
        else:
            p = d.add_paragraph(_strip_md(s))
            p.paragraph_format.space_after = Pt(0)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def to_pdf(md: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(format="Letter")
    pdf.set_margins(15, 12, 15)
    pdf.set_auto_page_break(True, margin=12)
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin
    header = True
    for line in md.splitlines():
        s = _latin1(_strip_md(line.rstrip()))
        if not s.strip():
            continue
        pdf.set_x(pdf.l_margin)
        if s.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(width, 8, s[2:], align="C", new_x="LMARGIN", new_y="NEXT")
            header = True
        elif header and not s.startswith(("#", "- ")):
            pdf.set_font("Helvetica", "", 9.5)
            pdf.multi_cell(width, 4.5, s, align="C", new_x="LMARGIN", new_y="NEXT")
        elif s.startswith("## "):
            header = False
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(width, 6, s[3:].upper(), new_x="LMARGIN", new_y="NEXT")
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.l_margin + width, y)
            pdf.ln(1)
        elif s.startswith("### "):
            header = False
            pdf.set_font("Helvetica", "B", 10)
            pdf.multi_cell(width, 5, s[4:], new_x="LMARGIN", new_y="NEXT")
        elif s.startswith("- "):
            header = False
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(5, 4.8, "-")
            pdf.multi_cell(width - 5, 4.8, s[2:], new_x="LMARGIN", new_y="NEXT")
        else:
            header = False
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(width, 4.8, s, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
