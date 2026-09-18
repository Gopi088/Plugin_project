"""Stage 5 engine: deterministic date extraction & normalization.

Rules:
  - Never invent dates. Unparseable text -> no mention (caller records AMBIGUOUS).
  - Original raw text is always preserved on the mention.
  - Precision is tracked: 'month' for month+year, 'year' for year-only.
    Year-only ranges expand to Jan..Dec; single year-only dates are NOT
    midpoint-guessed (unlike the legacy scripts) — the interval engine
    treats them as full-year coverage instead.
  - "Present / till date / current / now" end -> today's (year, month).
"""

import re
from datetime import date

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

MONTH_PAT = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
             r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
             r"Nov(?:ember)?|Dec(?:ember)?)\.?")
YEAR_PAT = r"((?:19|20)\d{2})"
PRESENT_PAT = r"(?:present|till\s+date|to\s+date|current|now|ongoing|till\s+now|tilldate)"
SEPARATOR_PAT = r"(?:\s*(?:\u2013|\u2014|-|–|—|to|till|until|through|/)\s*)"

MONTH_YEAR_RE = re.compile(MONTH_PAT + r"[\s.\-/]*?" + YEAR_PAT, re.IGNORECASE)
NUM_MY_RE = re.compile(r"(0?[1-9]|1[0-2])[\-/]((?:19|20)\d{2})")
NUM_YM_RE = re.compile(r"((?:19|20)\d{2})[\-/](0?[1-9]|1[0-2])")
YEAR_ONLY_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
PRESENT_RE = re.compile(PRESENT_PAT, re.IGNORECASE)


def _month_num(name):
    key = name.strip(".").lower()
    return MONTHS.get(key, MONTHS.get(key[:3]))


def parse_month_year(s):
    """Return (year, month) or None for a single month+year fragment."""
    m = MONTH_YEAR_RE.search(s or "")
    if m and m.group(2):
        mon = _month_num(m.group(1))
        if mon:
            return (int(m.group(2)), mon)
    m = NUM_MY_RE.search(s or "")
    if m:
        return (int(m.group(2)), int(m.group(1)))
    m = NUM_YM_RE.search(s or "")
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return None


def is_present(s):
    return bool(PRESENT_RE.search(s or ""))


def find_mentions(line, today=None):
    """Find date mentions in one line.

    Returns list of dicts: {raw, start, end, precision, is_range, is_present}.
    Year-only singles/ranges keep precision='year' with Jan..Dec expansion.
    Lines with no interpretable date return [] (never fabricated).
    """
    if today is None:
        today = date.today()
    text = line or ""
    out = []
    # 1) explicit ranges: <date-ish> sep <date-ish>
    date_bit = (r"(?:(?:" + MONTH_PAT + r"[\s.\-/]*?)?" + YEAR_PAT + r"|"
                + PRESENT_PAT + r"|(?:0?[1-9]|1[0-2])[\-/](?:19|20)\d{2})")
    pat = re.compile(r"(?P<a>" + date_bit + r")" + SEPARATOR_PAT +
                     r"(?P<b>" + PRESENT_PAT + r"|(?:" + date_bit + r"))",
                     re.IGNORECASE)
    consumed = []
    for m in pat.finditer(text):
        a, b = m.group("a"), m.group("b")
        consumed.append((m.start(), m.end()))
        sa = parse_month_year(a)
        ya = YEAR_ONLY_RE.search(a)
        if is_present(b):
            sb = (today.year, today.month)
            present = True
        else:
            sb = parse_month_year(b)
            yb = YEAR_ONLY_RE.search(b)
            present = False
            if sb is None and yb:
                sb = (int(yb.group(1)), 12)
                sa = sa or ((int(ya.group(1)), 1) if ya else None)
        if sa is None and ya:
            sa = (int(ya.group(1)), 1)
        if sa is None or sb is None:
            continue  # ambiguous half -> skip, do not guess
        if sa > sb:
            continue  # invalid (end before start) -> skip, flagged by caller
        raw = m.group(0).strip()
        # month evidence must not be a digit fragment of a year range
        # (e.g. the "3-2017" inside "2013-2017" is not a numeric date)
        has_month = bool(
            MONTH_YEAR_RE.search(raw)
            or re.search(r"(?<!\d)(?:0?[1-9]|1[0-2])[\-/](?:19|20)\d{2}(?!\d)", raw)
            or re.search(r"(?<!\d)(?:19|20)\d{2}[\-/](?:0?[1-9]|1[0-2])(?!\d)", raw))
        out.append({"raw": raw, "start": sa, "end": sb,
                    "precision": "month" if has_month else "year",
                    "is_range": True, "is_present": present})
    # 2) single dates outside consumed ranges
    for m in MONTH_YEAR_RE.finditer(text):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        mon = _month_num(m.group(1))
        if not mon or not m.group(2):
            continue
        y = int(m.group(2))
        out.append({"raw": m.group(0).strip(), "start": (y, mon), "end": (y, mon),
                    "precision": "month", "is_range": False, "is_present": False})
    for m in list(NUM_MY_RE.finditer(text)) + list(NUM_YM_RE.finditer(text)):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        parsed = parse_month_year(m.group(0))
        if parsed:
            out.append({"raw": m.group(0).strip(), "start": parsed, "end": parsed,
                        "precision": "month", "is_range": False, "is_present": False})
    # bare "Present" alone (e.g. end-date-only context) is not a standalone date.
    return out


def month_index(ym):
    return ym[0] * 12 + ym[1]


def months_between(a, b):
    """Whole months from a to b; negative = overlap."""
    return month_index(b) - month_index(a)


def fmt(ym):
    names = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
             7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
    return f"{names[ym[1]]} {ym[0]}"
