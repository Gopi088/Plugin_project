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
    exp = section(text, [r"PROFESSIONAL EXPERIENCE", r"WORK EXPERIENCE", r"EMPLOYMENT HISTORY", r"WORK HISTORY", r"EMPLOYMENT", r"\bEXPERIENCE\b", r"CAREER HISTORY", r"CAREER TIMELINE", r"CAREER OVERVIEW", r"CAREER JOURNEY", r"CAREER", r"POSITIONS HELD", r"PROFESSIONAL BACKGROUND", r"CHRONOLOGICAL WORK HISTORY", r"CHRONOLOGICAL EXPERIENCE"],
                  [r"KEY PROJECTS", r"\bPROJECTS\b", r"EDUCATION", r"SKILLS", r"CERTIFICATION"])
    if not exp:
        return []
        # Fallback: scan lines of text directly, excluding Education and Skills sections
        lines_all = (text or "").split("\n")
        in_skip = False
        exp_lines = []
        for ln in lines_all:
            s = ln.strip()
            if re.match(r"(?i)^(?:education|academic|qualification|skills|technical skills|certifications?)\b", s) and len(s.split()) <= 6:
                in_skip = True
                continue
            if in_skip and re.match(r"(?i)^(?:projects?|awards?|summary|personal projects)\b", s) and len(s.split()) <= 6:
                in_skip = False
            if not in_skip:
                exp_lines.append(ln)
        lines = [ln.strip() for ln in exp_lines if ln.strip()]
    else:
        lines = [ln.strip() for ln in exp.split("\n") if ln.strip()]
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
            inline_role = line[:idx].strip(" :–—|,") if idx > 0 else line[idx + len(raw):].strip(" :–—|,")
            if inline_role and len(inline_role) > 2:
                # date on the same line as role: "Senior Engineer ... Jan 2022 - Present"
                # or "Company | Title | 05/2025 - Present" -> split on "|"
                # or "Company as Role"
                role = inline_role
                company = ""
                m_as = re.match(r'(?i)^(.+?)\s+as\s+(?:an?\s+)?(.+)$', inline_role.strip(' :–—|,'))
                if m_as:
                    company = m_as.group(1).split(',')[0].strip(' :–—|,')
                    role = m_as.group(2).strip(' :–—|,')
                elif "|" in inline_role:
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
    numbered_pat = re.compile(r"^\s*(?:PROJECT|POC)\s*[-#]?\s*\d+(?:\s*[:\-–.]?\s*(.*))?$", re.IGNORECASE)
    numbered = []
    cur = None
    for ln in (text or "").split("\n"):
        s = ln.strip()
        m = numbered_pat.match(s)
        if m:
            if cur:
                numbered.append(cur)
            name_val = (m.group(1) or "").strip(" #:.-")
            cur = {"name": name_val or s, "duration": "", "client": "", "role": "", "details": []}
        elif cur is not None:
            m_dur = re.match(r"^(?:duration|period|tenure)\s*[:\-]\s*(.+)$", s, re.IGNORECASE)
            m_client = re.match(r"^(?:client(?:\s*name)?)\s*[:\-]\s*(.+)$", s, re.IGNORECASE)
            m_role = re.match(r"^(?:role|position|designation|project role)\s*[:\-]\s*(.+)$", s, re.IGNORECASE)
            m_title = re.match(r"^(?:title|project title|project name)\s*[:\-]\s*(.+)$", s, re.IGNORECASE)
            if m_dur and not cur.get("duration"):
                cur["duration"] = m_dur.group(1).strip()
            elif m_client and not cur.get("client"):
                cur["client"] = m_client.group(1).strip()
            elif m_role and not cur.get("role"):
                cur["role"] = m_role.group(1).strip()
            elif m_title and (not cur.get("name") or cur["name"].isdigit() or cur["name"].startswith("POC") or cur["name"].startswith("Project")):
                cur["name"] = m_title.group(1).strip()
            elif s.startswith("•"):
                cur["details"].append(s.lstrip("• ").strip())
            elif re.match(r"^(EDUCATION|DECLARATION|CERTIFICATION|REFERENCES)\s*:?\s*$", s, re.IGNORECASE):
                break
            elif cur.get("details") and s and not s.startswith(("Roles & Responsibilities", "Details:")):
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


def analyze_resume_timeline(text, today=None, *, raw_bytes=b"", filename="resume.txt"):
    """Compatibility output backed by the same twelve stages as the API."""
    from backend.pipeline_context import PipelineContext
    from backend.pipeline import runner
    ctx = PipelineContext("cli", filename, raw_text=text, raw_bytes=raw_bytes)
    if today is not None:
        ctx.meta["today"] = today
    runner.run(ctx)
    dto = ctx.recruiter_output
    jobs, education = [], []
    for event in ctx.events:
        row = {"title": event.title, "company": event.org,
               "start": _month(event.start), "end": _month(event.end),
               "raw": event.date_label, "precision": event.precision,
               "status": event.status, "source": event.source}
        row["duration_months"] = (months_between(row["start"], row["end"]) + 1
            if row["start"] and row["end"] and event.precision == "month" and event.status == "CONFIRMED" else None)
        if event.type in ("EMPLOYMENT", "INTERNSHIP"):
            jobs.append(row)
        elif event.type == "EDUCATION":
            education.append({**row, "label": event.title})
    # A course end is evidence of an education date, not proof of graduation.
    grad_gap = None
    job_gaps, activity_gaps = [], []
    for gap in ctx.gaps:
        if gap.state != "POTENTIAL_GAP":
            continue
        bounds = (dto.get("gaps") or [])
        evidence = next((g.get("evidence_details", []) for g in bounds if g["id"] == gap.id), [])
        row = {"gap_months": gap.months, "start": _month(gap.start),
               "end": _month(gap.end), "evidence": evidence}
        before = ctx.events_by_id().get(gap.evidence.get("event_before"))
        after = ctx.events_by_id().get(gap.evidence.get("event_after"))
        activity_gaps.append(row)
        if before.type == 'EDUCATION' and after.type in ('EMPLOYMENT', 'INTERNSHIP'):
            grad_gap = gap.months
        elif before.type in ('EMPLOYMENT', 'INTERNSHIP') and after.type in ('EMPLOYMENT', 'INTERNSHIP'):
            job_gaps.append(row)
    return {"period_analysis": dto.get("period_analysis", {}), "activity_gaps": activity_gaps,
            "graduation": None, "education_entries": education, "jobs": jobs,
            "graduation_to_first_job_months": grad_gap, "job_gaps": job_gaps,
            "total_experience_months": (len({year * 12 + month for e in ctx.events
                if e.type in ("EMPLOYMENT", "INTERNSHIP") and e.start and e.end
                for year, month in _covered_months(e.start, e.end)})
                if all(j["duration_months"] is not None for j in jobs) else None),
            "total_gap_months": sum(g.months for g in ctx.gaps if g.state == "POTENTIAL_GAP"),
            "projects": {"items": [e.to_dict() for e in ctx.events if e.type == "PROJECT"]},
            "warnings": ["Insufficient evidence to assess unrepresented periods."]
                if any(g.state == "INSUFFICIENT_EVIDENCE" for g in ctx.gaps) else [],
            "timeline": dto}


def _month(value):
    return f"{value[0]:04d}-{value[1]:02d}" if value else ""


def _covered_months(start, end):
    for index in range(start[0]*12+start[1]-1, end[0]*12+end[1]):
        year, zero_month = divmod(index, 12)
        yield year, zero_month+1
