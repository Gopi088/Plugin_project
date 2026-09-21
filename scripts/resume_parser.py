import os
import re

import pdfplumber

try:
    import spacy
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _MODEL_PATH = os.path.join(BASE_DIR, "model")
    try:
        nlp = spacy.load(_MODEL_PATH)
    except Exception:
        try:
            nlp = spacy.load("en_core_web_sm")
        except Exception:
            nlp = spacy.blank("en")
except Exception:
    nlp = None

try:
    from scripts.timeline import (
        find_ranges,
        section as timeline_section,
        extract_jobs as timeline_jobs,
        extract_projects as timeline_projects,
        extract_education as timeline_education,
    )
except ImportError:
    try:
        from timeline import (
            find_ranges,
            section as timeline_section,
            extract_jobs as timeline_jobs,
            extract_projects as timeline_projects,
            extract_education as timeline_education,
        )
    except ImportError:
        find_ranges = None
        timeline_section = None
        timeline_jobs = None
        timeline_projects = None
        timeline_education = None

email_regex = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
linkedin_regex = r"(linkedin\.com/in/[A-Za-z0-9_\-]+)"
github_regex = r"(github\.com/[A-Za-z0-9_\-]+)"

def _load_skills():
    """Shared skill vocabulary (backend/data/skills.json); falls back to built-in."""
    import json as _json
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(base, "backend", "data", "skills.json"), encoding="utf-8") as fh:
            return [s.lower() for s in _json.load(fh)]
    except Exception:
        return [
            "python", "java", "javascript", "sql",
            "aws", "docker", "kubernetes",
            "react", "redux", "typescript",
            "spring", "spring boot", "microservices",
            "mongodb", "mysql", "postgresql", "redis",
            "langchain", "rag", "llm", "embeddings",
            "kafka", "hadoop", "spark", "airflow",
            "fastapi", "django", "flask",
            "node.js", "express.js", "angular", "hibernate",
            "rest", "rest api", "rest apis", "html", "css",
            "git", "maven", "junit", "sonar", "jira",
        ]


VALID_SKILLS = _load_skills()

HEADER_SKIP = {
    "detailed info", "professional summary", "professional experience",
    "summary", "objective", "contact", "contact info", "personal details",
    "skills", "technical skills", "key projects", "projects", "education",
    "experience", "work experience", "curriculum vitae", "resume", "profile",
}

MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def _norm(text):
    """Fix pdfplumber ligature corruption (\\x00 = fi/ti/ft) + bullets/dashes."""
    if not text:
        return text
    # explicit fi/ft ligatures first, remainder are ti
    text = text.replace("So\x00ware", "Software").replace("so\x00ware", "software")
    text = text.replace("Pro\x00cient", "Proficient").replace("pro\x00ciency", "proficiency")
    text = text.replace("con\x00g", "config").replace("Con\x00g", "Config")
    text = re.sub(r"(?<![A-Za-z])\x00x(?![A-Za-z])", "fix", text)
    text = text.replace("\x00", "ti")
    text = text.replace("\u2022", "•").replace("\uf0b7", "•").replace("\uf0a7", "•")
    text = text.replace("", "•")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return text


def _exp_section(text):
    """Prefer explicit PROFESSIONAL/WORK EXPERIENCE header; ignore
    body-copy lines like 'Exp Total Years Experience: 5.7'."""
    lines = text.split("\n")
    start = None
    for i, ln in enumerate(lines):
        s = ln.strip().strip(":").strip()
        low = s.lower()
        if re.fullmatch(r"(professional experience|work experience|employment history)", low):
            start = i
            break
    if start is None:
        for i, ln in enumerate(lines):
            s = ln.strip().strip(":").strip()
            low = s.lower()
            if low in ("professional experience", "work experience", "experience"):
                start = i
                break
    if start is None:
        for i, ln in enumerate(lines):
            s = ln.strip()
            if re.match(r"^(professional experience|work experience)\s*:?\s*$", s, re.IGNORECASE):
                start = i
                break
    if start is None:
        return timeline_section(
            text,
            [r"PROFESSIONAL EXPERIENCE", r"WORK EXPERIENCE", r"EMPLOYMENT"],
            [r"KEY PROJECTS", r"\bPROJECTS\b", r"EDUCATION", r"CERTIFICATION"],
        ) if timeline_section else ""
    buf = []
    for ln in lines[start + 1:]:
        s = ln.strip().strip(":").strip()
        if re.match(r"^(key projects|projects|project profile|education|certification|declaration|references|technical skills|skills)\s*:?\s*$", s, re.IGNORECASE):
            break
        buf.append(ln)
    return "\n".join(buf)


def _fmt_ym(ym):
    try:
        y, m = int(ym[:4]), int(ym[5:7])
        return f"{MONTH_NAMES.get(m, '')} {y}"
    except Exception:
        return ym


# -------------------------
# TEXT EXTRACTION
# -------------------------

def extract_text_from_pdf(file_path):
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text:
                text += page_text + "\n"
    return text


def extract_text_from_docx(file_path):
    from docx import Document
    doc = Document(file_path)
    return "\n".join([p.text for p in doc.paragraphs])


def extract_text_any(file_path):
    if file_path.lower().endswith(".pdf"):
        return extract_text_from_pdf(file_path)
    if file_path.lower().endswith(".docx"):
        return extract_text_from_docx(file_path)
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        return f.read()


# -------------------------
# CLEAN TEXT
# -------------------------

def clean_text(text):
    # normalise bullets / dashes / pdf ligature artefacts
    text = _norm(text)
    text = re.sub(r'(\w)-\s+(\w)', r'\1\2', text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# -------------------------
# NAME
# -------------------------

def extract_name(raw_text, doc=None):
    raw_text = _norm(raw_text)
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

    for line in lines[:6]:
        low = line.lower()
        if "@" in line or "gmail" in low or "linkedin" in low or "github" in low:
            continue
        if re.search(r"(19|20)\d{2}|present|years|experience|engineer|developer|mob|phone|gmail|india", low):
            # might still be "Gopal Prasad K - Java Full Stack Engineer"
            # -> take left part before - / | /
            if any(sep in line for sep in ["–", "-", "|", "—"]):
                left = re.split(r"[–—\-|]", line)[0].strip()
                parts = left.split()
                if 2 <= len(parts) <= 4 and re.match(r"^[A-Za-z .]+$", left):
                    return left.upper()
            continue
        # strip role suffix: "Gopal Prasad K – Java Full Stack Engineer"
        cand = re.split(r"[–—\-|]", line)[0].strip()
        if cand.lower() in HEADER_SKIP:
            continue
        parts = cand.split()
        if 2 <= len(parts) <= 4 and re.match(r"^[A-Za-z .]+$", cand):
            return cand.upper()

    # fallback: spaCy NAME entity from top of doc
    if doc is not None:
        for ent in doc.ents:
            if ent.label_ == "NAME" and len(ent.text.split()) >= 2:
                return ent.text.strip().upper()
    return None


# -------------------------
# CONTACT
# -------------------------

def extract_email(text):
    m = re.findall(email_regex, text)
    return m[0] if m else None


def extract_phone(text):
    # candidates like (+91)- 6200776432, +91 98XXXXXXXX, 098XXX XXXXX
    pat = re.compile(r"\+?\(?\d{2,5}\)?[\s\-]*\d{5}[\s\-]*\d{5}|\b\d{10}\b")
    for m in pat.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        # strip leading country code
        if len(digits) > 10:
            digits = digits[-10:]
        if len(digits) == 10 and digits[0] in "6789":
            return digits
    # fallback: any 10-digit run not part of a year range
    for m in re.finditer(r"\d{10,12}", re.sub(r"\D", " ", text).replace("  ", " ")):
        d = m.group(0)
        if len(d) >= 10:
            d = d[-10:]
            if d[0] in "6789":
                return d
    return None


def extract_links(text):
    links = []
    links += re.findall(linkedin_regex, text, flags=re.IGNORECASE)
    links += re.findall(github_regex, text, flags=re.IGNORECASE)
    return links


# -------------------------
# SUMMARY (line-anchored, not substring)
# -------------------------

def extract_summary(text):
    lines = text.split("\n")
    start_idx, end_idx = None, None
    start_pat = re.compile(r"^(objective|summary|professional summary|profile|about me)\s*:?\s*$", re.IGNORECASE)
    end_pat = re.compile(r"^(skills|technical skills|skills description|professional experience|work experience|experience|education|projects|key projects)\s*:?\s*$", re.IGNORECASE)
    for i, ln in enumerate(lines):
        s = ln.strip().strip(":").strip()
        if start_idx is None and start_pat.match(s):
            start_idx = i + 1
        elif start_idx is not None and end_pat.match(s):
            end_idx = i
            break
    if start_idx is not None:
        buf = lines[start_idx:end_idx] if end_idx else lines[start_idx:start_idx + 15]
        buf = [l.strip("• ").strip() for l in buf if l.strip()]
        return " ".join(buf)[:800]
    return ""


# -------------------------
# SKILLS
# -------------------------

def extract_skills(doc, text):
    skills = set()
    low = text.lower()
    if doc is not None:
        for ent in doc.ents:
            if ent.label_ == "SKILL" and ent.text.lower() in VALID_SKILLS:
                skills.add(ent.text.lower().title() if ent.text.lower() != "node.js" else "Node.js")
    for skill in VALID_SKILLS:
        if re.search(r"(?<![a-z0-9+#])" + re.escape(skill) + r"(?![a-z0-9+#])", low):
            disp = skill.title()
            if skill == "node.js":
                disp = "Node.js"
            elif skill == "rest apis":
                disp = "Rest Apis"
            skills.add(disp)
    return sorted(skills)


# -------------------------
# EXPERIENCE
# -------------------------

def _inline_split_role_company(prefix):
    """'Software Developer EPAM Systems India Pvt Ltd.' -> role/company split."""
    m = re.search(r"\b(Pvt\.?\s*Ltd\.?|Pvt Ltd|Ltd|Inc\.?|LLP|Technologies|Solutions|Systems|Services|Consulting|Digital|Labs|Group|Bank|Infotech)\b.*$", prefix, re.IGNORECASE)
    if m:
        # company = from first capitalised phrase before hint... simplest:
        # role = leading title words (Developer/Engineer/...) boundary
        title_pat = re.compile(
            r"^(.*?)(Software\s+\w+|Senior\s+\w+.*|Junior\s+.*|.*Engineer|.*Developer|.*Analyst|.*Manager|.*Consultant|.*Architect|.*Lead|.*Tester)\s+(.+)$",
            re.IGNORECASE,
        )
        tm = title_pat.match(prefix.strip())
        if tm:
            return tm.group(2).strip(), tm.group(3).strip()
        # fallback: first 2-3 words = role
        parts = prefix.strip().split()
        return " ".join(parts[:2]), " ".join(parts[2:])
    parts = prefix.strip().split()
    if len(parts) > 4:
        return " ".join(parts[:2]), " ".join(parts[2:])
    return prefix.strip(), ""


def extract_experience(raw_text):
    raw_text = _norm(raw_text)
    # Preferred: deterministic timeline extractor (handles till/to/Present, etc.)
    if timeline_jobs is not None:
        try:
            jobs = timeline_jobs(raw_text)
            out = []
            for j in jobs:
                out.append({
                    "role": j.get("title", ""),
                    "company": j.get("company", ""),
                    "duration": f"{_fmt_ym(j['start'])} - {_fmt_ym(j['end'])}" if j.get("start") else "",
                    "details": j.get("details", []),
                })
            if out:
                return out
        except Exception:
            pass

    # Fallback regex (supports till/to/- with full month names)
    experience = []
    text = raw_text
    sec = _exp_section(text)
    if not sec:
        m = re.search(r"(PROFESSIONAL EXPERIENCE|EXPERIENCE)(.*?)(KEY PROJECTS|PROJECTS|EDUCATION|$)",
                      text, re.IGNORECASE | re.DOTALL)
        sec = m.group(2) if m else ""
    if not sec:
        return experience

    date_pat = re.compile(
        r"(?P<start>(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)?\.?\s*\d{4}|\d{1,2}[/-]\d{4})"
        r"\s*(?:-|–|—|to|till|until|through)\s*"
        r"(?P<end>Present|till\s+date|to\s+date|current|now|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)?\.?\s*\d{4}|\d{1,2}[/-]\d{4})",
        re.IGNORECASE,
    )
    lines = [l.strip() for l in sec.split("\n") if l.strip()]
    current_job = None
    for i, line in enumerate(lines):
        if re.fullmatch(r"(PROFESSIONAL EXPERIENCE|WORK EXPERIENCE|EXPERIENCE)", line, re.IGNORECASE):
            continue
        dm = date_pat.search(line)
        if dm:
            if current_job:
                experience.append(current_job)
            prefix = line[:dm.start()].strip(" -–—,|")
            duration = dm.group(0).strip()
            role, company = _inline_split_role_company(prefix)
            if not company and i + 1 < len(lines) and not lines[i + 1].startswith("•") \
                    and not date_pat.search(lines[i + 1]):
                company = lines[i + 1].strip(" -–—,|")
            current_job = {"role": role, "company": company, "duration": duration, "details": []}
        elif line.startswith("•"):
            if current_job:
                current_job["details"].append(line.replace("•", "").strip())
        elif current_job and current_job.get("details"):
            current_job["details"][-1] += " " + line
    if current_job:
        experience.append(current_job)
    return experience


# -------------------------
# PROJECTS
# -------------------------

def extract_projects(raw_text):
    raw_text = _norm(raw_text)
    # Preferred: timeline extractor + explicit PROJECT #N headers
    numbered_pat = re.compile(r"^\s*PROJECT\s*#?\s*\d+\s*[:\-–.]?\s*(.+?)\s*$", re.IGNORECASE)
    lines_all = [l.rstrip() for l in raw_text.split("\n")]
    numbered = []
    cur = None
    for ln in lines_all:
        s = ln.strip()
        m = numbered_pat.match(s)
        if m:
            if cur:
                numbered.append(cur)
            cur = {"name": m.group(1).strip(" #:.-"), "details": []}
        elif cur is not None:
            if s.startswith("•"):
                cur["details"].append(s.lstrip("• ").strip())
            elif re.match(r"^(EDUCATION|DECLARATION|CERTIFICATION|REFERENCES)\s*:?\s*$", s, re.IGNORECASE):
                break
            elif cur.get("details"):
                if s:
                    cur["details"][-1] += " " + s
    if cur:
        numbered.append(cur)
    if len(numbered) >= 1:
        return numbered

    if timeline_projects is not None:
        try:
            res = timeline_projects(raw_text)
            if res.get("items"):
                return res["items"]
        except Exception:
            pass
    return []


# -------------------------
# EDUCATION
# -------------------------

def extract_education(text):
    text = _norm(text)
    if timeline_education is not None:
        try:
            entries = timeline_education(text)
            out = []
            for e in entries:
                label = e.get("label", "").lstrip("• ").strip()
                ym = re.findall(r"(19|20)\d{2}", label)
                year = e.get("end", "")[:4] or (ym[-1] if ym else "")
                parts = re.split(r"[-–—]", label)
                inst = parts[-1].strip() if len(parts) > 1 else ""
                out.append({
                    "degree": label,
                    "institution": inst,
                    "year": year,
                })
            if out:
                return out
        except Exception:
            pass
    # fallback: degree line + year in EDUCATION section
    sec = timeline_section(text, [r"EDUCATION", r"ACADEMIC", r"QUALIFICATION"],
                           [r"PROFESSIONAL EXPERIENCE", r"WORK EXPERIENCE", r"EXPERIENCE",
                            r"KEY PROJECTS", r"PROJECTS", r"SKILLS", r"CERTIFICATION"]) if timeline_section else ""
    if not sec and "bachelor" in text.lower():
        return [{"degree": "Bachelor of Technology", "institution": "", "year": ""}]
    out = []
    for line in [l.strip(" •\u2022-\t") for l in (sec or "").split("\n") if l.strip()]:
        if re.search(r"bachelor|b\.?\s*tech|b\.?\s*e\.?|master|m\.?\s*tech|mca|mba|bca|diploma|ph\.?\s*d", line, re.IGNORECASE):
            ym = re.findall(r"(19|20)\d{2}", line)
            # institution: text after last dash
            parts = re.split(r"[-–—]", line)
            inst = parts[-1].strip() if len(parts) > 1 else ""
            out.append({"degree": line[:120].lstrip("• ").strip(), "institution": inst[:120], "year": ym[-1] if ym else ""})
    return out


# -------------------------
# MAIN
# -------------------------

def parse_resume(file_path):
    raw_text = extract_text_any(file_path)
    text = clean_text(raw_text)

    doc = nlp(text[:1000000]) if nlp is not None else None

    profile = {
        "name": extract_name(raw_text, doc),
        "email": extract_email(text),
        "phone": extract_phone(text),
        "summary": extract_summary(text),
        "skills": extract_skills(doc, text),
        "experience": extract_experience(raw_text),
        "education": extract_education(raw_text),
        "projects": extract_projects(raw_text),
        "certifications": [],
        "links": extract_links(text),
    }
    return profile
