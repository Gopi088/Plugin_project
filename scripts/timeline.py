"""Deterministic career-timeline extractor for resumes.

Owns all gap arithmetic (month resolution). The spaCy model in
``model_timeline/`` (see scripts/train_timeline.py) only *assists* entity
spotting; every date/gap number below is computed here with regex, so it is
never hallucinated.

Public entry point: analyze_resume_timeline(text) -> dict (schema in
TIMELINE_REQUIREMENTS.md section 3).
"""

import re
from datetime import date

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

PRESENT_WORDS = r"(?:present|till\s+date|todate|to\s+date|current|now|ongoing)"

MONTH_PAT = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
YEAR_PAT = r"((?:19|20)\d{2})"

# single date: "Feb 2025" | "05/2025" | "05-2025" | "June-2025" | "2016" | "Present"
SINGLE_DATE_PAT = re.compile(
    r"(?P<month>" + MONTH_PAT + r")[\s.\-/]*?(?P<year>" + YEAR_PAT + r")"
    r"|(?P<mnum>(?:0?[1-9]|1[0-2]))[\-/](?P<ynum>" + YEAR_PAT + r")"
    r"|(?P<ynum2>" + YEAR_PAT + r")[\-/](?P<mnum2>(?:0?[1-9]|1[0-2]))"
    r"|(?P<yearonly>" + YEAR_PAT + r")"
    r"|(?P<present>" + PRESENT_WORDS + r")",
    re.IGNORECASE,
)

SEPARATOR_PAT = r"(?:\s*(?:\u2013|\u2014|-|–|—|to|till|until|through|/|,)\s*)"

DEGREE_PAT = re.compile(
    r"(B\.?\s*E\.?|B\.?\s*Tech(?:nology)?|Bachelor(?:'s)?[^,\n]{0,60}|"
    r"M\.?\s*Tech(?:nology)?|Master(?:'s)?[^,\n]{0,60}|\bMCA\b|\bMBA\b|"
    r"\bBCA\b|Diploma|Ph\.?\s*D\.?|Doctorate|"
    r"B\.?\s*Sc\.?|M\.?\s*Sc\.?|B\.?\s*Com\.?|INTER(?:MEDIATE)?|\bSSC\b|\bHSC\b)",
    re.IGNORECASE,
)

CLAIMED_PROJECT_PAT = re.compile(
    r"(?:worked\s+on|handled|delivered|executed|completed|involved\s+in)\s+"
    r"(?P<n>\d+)\+?\s+(?:\w+\s+){0,3}projects?",
    re.IGNORECASE,
)
CLAIMED_PROJECT_PAT2 = re.compile(
    r"(?P<n>\d+)\+?\s+projects?\s+(?:worked|handled|delivered|done|completed)",
    re.IGNORECASE,
)
NAV_PAT = re.compile(
    r"leetcode|hackerrank|codechef|github\.com|linkedin|transformed\s+by|"
    r"references|declaration|^https?://|www\.",
    re.IGNORECASE,
)


def _month_index(year, month):
    return year * 12 + month


def parse_single(s, today=None):
    """Parse one date fragment -> (year, month) or None. Year-only => month=6 (mid-year)."""
    if today is None:
        today = date.today()
    m = SINGLE_DATE_PAT.search(s or "")
    if not m:
        return None
    if m.group("present"):
        return (today.year, today.month)
    if m.group("month") and m.group("year"):
        mon = MONTHS[m.group("month").strip(".").lower()[:3] if len(m.group("month")) > 3 else m.group("month").strip(".").lower()]
        # normalise key: full names -> first 3 letters
        key = m.group("month").strip(".").lower()
        mon = MONTHS.get(key, MONTHS.get(key[:3]))
        return (int(m.group("year")), mon)
    if m.group("mnum"):
        return (int(m.group("ynum")), int(m.group("mnum")))
    if m.group("ynum2"):
        return (int(m.group("ynum2")), int(m.group("mnum2")))
    if m.group("yearonly"):
        return (int(m.group("yearonly")), 6)
    return None


def find_ranges(line, today=None):
    """Find (start, end, raw) date ranges in a line; falls back to single dates."""
    if today is None:
        today = date.today()
    text = (line or "").replace("\u2013", "-").replace("\u2014", "-")
    ranges = []
    # explicit range: <date> sep <date>
    pat = re.compile(
        r"(?P<a>(?:" + MONTH_PAT + r"[\s.\-/]*?)?" + YEAR_PAT + r"|" + PRESENT_WORDS + r"|(?:0?[1-9]|1[0-2])[\-/](?:19|20)\d{2})"
        + SEPARATOR_PAT
        + r"(?P<b>" + PRESENT_WORDS + r"|(?:" + MONTH_PAT + r"[\s.\-/]*?)?" + YEAR_PAT + r"|(?:0?[1-9]|1[0-2])[\-/](?:19|20)\d{2})",
        re.IGNORECASE,
    )
    for m in pat.finditer(text):
        a = parse_single(m.group("a"), today)
        b = parse_single(m.group("b"), today)
        if a and b:
            # guard: "17-09-2025" style document dates are single dates, not ranges;
            # if both sides are bare years with same value skip
            ranges.append((a, b, m.group(0).strip()))
    if not ranges:
        singles = []
        for m in SINGLE_DATE_PAT.finditer(text):
            s = parse_single(m.group(0), today)
            if s:
                singles.append((s, m.start(), m.end(), m.group(0).strip()))
        for s, _, _, raw in singles:
            ranges.append((s, s, raw))
        # "2019-06 - 2021-01": two singles joined by a separator = one range
        if len(singles) >= 2 and re.search(
                r"–|—|-|\bto\b|\btill\b|/", text, re.IGNORECASE):
            raw = text[singles[0][1]:singles[-1][2]].strip()
            ranges = [(singles[0][0], singles[-1][0], raw)]
    return ranges


def _norm_text(text):
    if not text:
        return text
    text = text.replace("So\x00ware", "Software").replace("so\x00ware", "software")
    text = text.replace("Pro\x00cient", "Proficient").replace("pro\x00ciency", "proficiency")
    text = text.replace("con\x00g", "config").replace("Con\x00g", "Config")
    import re as _re
    text = _re.sub(r"(?<![A-Za-z])\x00x(?![A-Za-z])", "fix", text)
    text = text.replace("\x00", "ti")
    text = text.replace("•", "•").replace("\u2022", "•").replace("\uf0b7", "•").replace("\uf0a7", "•").replace("", "•")
    return text


def section(text, start_words, stop_words):
    text = _norm_text(text)
    # Line-anchored section search: avoids matching "experience" inside body copy
    # (e.g. "8+ years of experience in ..."). A header line must contain a start
    # phrase and be short (<10 words) or fully uppercase.
    # First pass: explicit multi-word headers only (PROFESSIONAL/WORK EXPERIENCE).
    lines = (text or "").split("\n")
    explicit = [w for w in start_words if " " in w.strip(" \\b")]
    for pass_no in (0, 1):
        buf, inside = [], False
        for ln in lines:
            s = ln.strip()
            if not inside:
                cands = explicit if pass_no == 0 and explicit else start_words
                hit = False
                for w in cands:
                    rx = re.compile(r"^.*?(?:" + w + r").*$", re.IGNORECASE)
                    if not rx.match(s):
                        continue
                    # skip body-copy lines: contain digits (5.7, 5+ years) unless
                    # they are explicit PROFESSIONAL/WORK headers
                    low = s.lower()
                    if re.search(r"\d", s) and "professional" not in low and "work" not in low and "employment" not in low:
                        continue
                    if len(s.split()) <= 8 or s.isupper() or low.startswith("professional") or low.startswith("work"):
                        hit = True
                        break
                if hit:
                    inside = True
                continue
            if any(re.compile(r"^.*?(?:" + w + r").*$", re.IGNORECASE).match(s) and (len(s.split()) <= 8 or s.isupper()) for w in stop_words):
                break
            buf.append(ln)
        if buf:
            return "\n".join(buf)
    # fallback: old behaviour
    m = re.search(
        r"(" + "|".join(start_words) + r")(.*?)(?:" + "|".join(stop_words) + r"|$)",
        text or "",
        re.IGNORECASE | re.DOTALL,
    )
    return m.group(2) if m else ""


def extract_education(text, today=None):
    edu = section(text, [r"EDUCATION", r"ACADEMIC", r"QUALIFICATION"],
                  [r"PROFESSIONAL EXPERIENCE", r"WORK EXPERIENCE", r"EXPERIENCE",
                   r"KEY PROJECTS", r"PROJECTS", r"SKILLS", r"TECHNICAL SKILLS", r"CERTIFICATION"])
    if not edu:
        return []
    entries = []
    for line in [ln.strip(" •\u2022-\t") for ln in edu.split("\n") if ln.strip()]:
        deg = DEGREE_PAT.search(line)
        ranges = find_ranges(line, today)
        for (a, b, raw) in ranges:
            # a range inside education: graduation = end; single year = that year
            entries.append({
                "label": deg.group(0).strip() if deg else line[:60],
                "start": f"{a[0]:04d}-{a[1]:02d}",
                "end": f"{b[0]:04d}-{b[1]:02d}",
                "raw": raw,
            })
        if not ranges and deg:
            # degree with no date (e.g. fresher "B.Tech ... | 9.55 CGPA"):
            # keep label so callers know education exists; no date -> no gap math
            entries.append({"label": line[:120], "start": "", "end": "", "raw": ""})
    return entries


def extract_jobs(text, today=None):
    exp = section(text, [r"PROFESSIONAL EXPERIENCE", r"WORK EXPERIENCE", r"EMPLOYMENT", r"\bEXPERIENCE\b"],
                  [r"KEY PROJECTS", r"\bPROJECTS\b", r"EDUCATION", r"SKILLS", r"CERTIFICATION"])
    if not exp:
        return []
    jobs = []
    lines = [ln.strip() for ln in exp.split("\n") if ln.strip()]
    current = None
    pending = []  # non-bullet, non-date header lines since last job (role/company candidates)
    COMPANY_HINT = re.compile(
        r"Pvt|Ltd|Inc|LLP|Technolog|Solutions|Systems|Services|Consulting|Digital|"
        r"Engineering|Labs|Group|Bank|Infotech|Client\s*:|Company\s*:|Organization\s*:",
        re.IGNORECASE)
    for i, line in enumerate(lines):
        if re.fullmatch(r"(PROFESSIONAL EXPERIENCE|WORK EXPERIENCE|EXPERIENCE)", line, re.IGNORECASE):
            continue
        has_date = bool(re.search(r"(19|20)\d{2}|present|till\s+date|current", line, re.IGNORECASE))
        ranges = find_ranges(line, today) if has_date else []
        # drop bare-year false positives like "(2000 TPS)", "20K+ requests/day":
        # a job date must carry a month, a range separator, or a present-word
        ranges = [r for r in ranges if re.search(
            r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|/|\u2013|\u2014|-|–|—|\bto\b|\btill\b|present|current|now",
            r[2], re.IGNORECASE)]
        if ranges and len(line) > 2:
            if current:
                jobs.append(current)
            (a, b, raw) = ranges[0]
            norm_line = line.replace("\u2013", "-").replace("\u2014", "-")
            norm_raw = raw.replace("\u2013", "-").replace("\u2014", "-")
            idx = norm_line.lower().find(norm_raw.lower()[:10])
            inline_role = line[:idx].strip(" -–—|,") if idx > 0 else ""
            if inline_role and len(inline_role) > 2:
                # date on the same line as role: "Senior Engineer ... Jan 2022 - Present"
                # or "Company | Title | 05/2025 - Present" -> split on "|"
                role = inline_role
                company = ""
                if "|" in inline_role:
                    parts = [p.strip() for p in inline_role.split("|") if p.strip()]
                    if len(parts) >= 2:
                        company, role = parts[0], " | ".join(parts[1:])
                    else:
                        role = parts[0]
                else:
                    # "Software Developer EPAM Systems India Pvt Ltd." -> split on company hint
                    cm = re.search(r"\b(Pvt\.?\s*Ltd\.?|Pvt Ltd|Ltd\.?|Inc\.?|LLP|Technologies|Technology|Solutions|Systems|Services|Consulting|Digital|Labs|Group|Bank|Infotech)\b.*$", inline_role, re.IGNORECASE)
                    if cm:
                        # role = leading job-title phrase, company = rest
                        tm = re.match(r"^(.*?(?:Engineer|Developer|Analyst|Manager|Consultant|Architect|Tester|Lead|Administrator|Specialist|Owner|Head))\s+(.+)$", inline_role.strip(), re.IGNORECASE)
                        if tm:
                            role, company = tm.group(1).strip(), tm.group(2).strip()
                        else:
                            parts = inline_role.strip().split()
                            role, company = " ".join(parts[:2]), " ".join(parts[2:])
                    else:
                        for nxt in lines[i + 1:i + 3]:
                            if nxt.startswith("•") or re.search(r"(19|20)\d{2}|present", nxt, re.IGNORECASE):
                                break
                            if len(nxt) > 2:
                                company = nxt.strip(" -–—|,")
                                break
            else:
                # date on its own line: role/company are the pending header lines above it
                company = next((p for p in reversed(pending) if COMPANY_HINT.search(p)), "")
                role_cands = [p for p in pending if p != company]
                role = role_cands[-1] if role_cands else ""
                if not role and pending:
                    role = pending[-1]
            current = {
                "title": re.sub(r"\s+", " ", role).strip(" -–—|,")[:120],
                "company": company[:120],
                "start": f"{a[0]:04d}-{a[1]:02d}",
                "end": f"{b[0]:04d}-{b[1]:02d}",
                "_s": a, "_e": b,
            }
            pending = []
        elif line.startswith("•") and current:
            current.setdefault("details", []).append(line.lstrip("• ").strip())
            pending = []
        elif current and current.get("details") and not has_date:
            current["details"][-1] += " " + line
        elif not line.startswith("•") and not has_date and len(line.split()) <= 14:
            # candidate header line (role or company); keep last few
            pending.append(line.strip(" -–—|,"))
            pending = pending[-4:]
        elif has_date and not ranges:
            pending = []
    if current:
        jobs.append(current)
    # chronological order (oldest first) for gap math
    jobs.sort(key=lambda j: (_month_index(*j["_s"])))
    for j in jobs:
        j["duration_months"] = _month_index(*j["_e"]) - _month_index(*j["_s"])
        j.pop("_s", None)
        j.pop("_e", None)
    return jobs


def extract_projects(text):
    text = _norm_text(text)
    # First: explicit PROJECT #N headers anywhere in the doc (most reliable).
    numbered_pat = re.compile(r"^\s*PROJECT\s*#?\s*\d+\s*[:\-–.]?\s*(.+?)\s*$", re.IGNORECASE)
    numbered = []
    cur = None
    for ln in (text or "").split("\n"):
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
            elif cur.get("details") and s:
                cur["details"][-1] += " " + s
    if cur:
        numbered.append(cur)
    if numbered:
        claimed = 0
        for pat in (CLAIMED_PROJECT_PAT, CLAIMED_PROJECT_PAT2):
            for mm in pat.finditer(text or ""):
                try:
                    claimed = max(claimed, int(mm.group("n")))
                except ValueError:
                    pass
        return {"claimed": claimed, "described": len(numbered),
                "unexplained": max(0, claimed - len(numbered)),
                "items": numbered, "numbered_headers": len(numbered)}
    proj_sec = section(text, [r"KEY PROJECTS", r"PROJECT PROFILE", r"PROJECTS PROFILE"],
                       [r"EDUCATION", r"CERTIFICATION", r"DECLARATION", r"REFERENCES"])
    # last resort: generic PROJECTS header (may match body copy — require header-like line)
    if not proj_sec:
        proj_sec = section(text, [r"\bPROJECTS\b"],
                           [r"EDUCATION", r"CERTIFICATION", r"DECLARATION", r"REFERENCES"])
    described = []
    if proj_sec:
        cur = None
        for line in [ln.strip() for ln in proj_sec.split("\n") if ln.strip()]:
            if line.upper() in ("KEY PROJECTS", "PROJECTS", "PROJECT PROFILE"):
                continue
            if NAV_PAT.search(line):
                if cur:
                    described.append(cur)
                    cur = None
                continue
            is_bullet = line.startswith("•")
            looks_header = (not is_bullet and len(line.split()) <= 8
                            and line[0].isupper() and not line.endswith(".")
                            and not re.search(r"(19|20)\d{2}", line))
            if looks_header:
                if cur:
                    described.append(cur)
                cur = {"name": line.strip("#:0123456789. "), "details": []}
            elif is_bullet and cur:
                cur["details"].append(line.lstrip("• ").strip())
            elif cur and cur["details"]:
                cur["details"][-1] += " " + line
            elif cur is None and is_bullet:
                cur = {"name": "Untitled project", "details": [line.lstrip("• ").strip()]}
        if cur:
            described.append(cur)
    claimed = 0
    for pat in (CLAIMED_PROJECT_PAT, CLAIMED_PROJECT_PAT2):
        for m in pat.finditer(text or ""):
            try:
                claimed = max(claimed, int(m.group("n")))
            except ValueError:
                pass
    # "Project name:" / "#1 Project" headers also count as described evidence
    numbered = re.findall(r"(?:project\s*(?:name)?\s*[:#]|#\d+\s*project)", text or "", re.IGNORECASE)
    return {
        "claimed": claimed,
        "described": len(described),
        "unexplained": max(0, claimed - len(described)),
        "items": described,
        "numbered_headers": len(numbered),
    }


def months_between(a, b):
    """a, b = 'YYYY-MM' strings -> b - a in months."""
    ay, am = int(a[:4]), int(a[5:7])
    by, bm = int(b[:4]), int(b[5:7])
    return (by * 12 + bm) - (ay * 12 + am)


def analyze_resume_timeline(text, today=None):
    text = _norm_text(text)
    if today is None:
        today = date.today()
    edu = extract_education(text, today)
    jobs = extract_jobs(text, today)
    projects = extract_projects(text)

    graduation = None
    dated = [e for e in edu if e.get("end")]
    if dated:
        # latest education end = graduation
        g = max(dated, key=lambda e: e["end"])
        graduation = {"label": g["label"], "date": g["end"],
                      "year": int(g["end"][:4]), "month": int(g["end"][5:7])}

    grad_gap = None
    if graduation and jobs:
        first = min(jobs, key=lambda j: j["start"])
        grad_gap = months_between(graduation["date"], first["start"])

    gaps, warnings = [], []
    ordered = sorted(jobs, key=lambda j: j["start"])
    for prev, nxt in zip(ordered, ordered[1:]):
        gap = months_between(prev["end"], nxt["start"])
        gaps.append({"from": f"{prev['title']} @ {prev['company']}"[:80],
                     "to": f"{nxt['title']} @ {nxt['company']}"[:80],
                     "gap_months": gap})
        if gap > 3:
            warnings.append(f"GAP: {gap} months between '{prev['company']}' and '{nxt['company']}'")
        elif gap < 0:
            warnings.append(f"OVERLAP: {abs(gap)} months between '{prev['company']}' and '{nxt['company']}'")
    if grad_gap is not None and grad_gap > 6:
        warnings.append(f"GAP: {grad_gap} months between graduation ({graduation['date']}) and first job")
    if projects["unexplained"] > 0:
        warnings.append(f"UNEXPLAINED_PROJECTS: claimed {projects['claimed']}, described {projects['described']}")

    total_exp = sum(j["duration_months"] for j in jobs)
    total_gap = sum(g["gap_months"] for g in gaps if g["gap_months"] > 0) + (grad_gap if grad_gap and grad_gap > 0 else 0)

    return {
        "graduation": graduation,
        "education_entries": edu,
        "jobs": jobs,
        "graduation_to_first_job_months": grad_gap,
        "job_gaps": gaps,
        "total_experience_months": total_exp,
        "total_gap_months": total_gap,
        "projects": projects,
        "warnings": warnings,
    }
