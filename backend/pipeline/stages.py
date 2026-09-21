"""The 12-stage processing pipeline.

Every stage: ``run(ctx) -> StageResult`` with defined input/output/status/
evidence/confidence/error handling (see STAGE_SPECS). Deterministic logic
decides wherever the answer is unambiguous; ML (ml_assist) only supplies
hints. Nothing is ever invented: ambiguous cases stay AMBIGUOUS/UNRESOLVED.
"""

import re
from datetime import date

from .. import datamodel as M
from .. import dates as D
from .. import intervals as I
from .. import evidence as EV
from .. import ml_assist
from ..cues import load as _load_cues

_CUES = _load_cues()


def _rx(fragments):
    return re.compile("|".join(f"(?:{f})" for f in fragments), re.IGNORECASE)


COMPANY_HINT = _rx(_CUES["company_suffixes_regex"])
TITLE_CUE = _rx(_CUES["title_words_regex"])
DEGREE_CUE = _rx(_CUES["degree_words_regex"])
NAV_PAT = _rx(_CUES["nav_terms_regex"])
PROJECT_FIELD_PATS = list(_CUES["project_field_labels_regex"])
INTERNSHIP_WORDS = [w.lower() for w in _CUES.get("internship_words", ["intern"])]
INTERNSHIP_RE = re.compile(r"\b(?:" + "|".join(
    re.escape(w) for w in INTERNSHIP_WORDS) + r")\b", re.IGNORECASE)
_STRIP_CAPS = _CUES.get("strip_leading_caps", {"enabled": True, "min_length": 3})
PROJECT_HEAD = re.compile(r"^\s*PROJECT\s*#?\s*\d+\s*[:\-–.]?\s*(.+?)\s*$", re.IGNORECASE)

SECTION_KINDS = tuple(
    (kind, tuple(names)) for kind, names in _CUES["section_headers"].items()
)


def _strip_leading_caps(text):
    if not _STRIP_CAPS.get("enabled", True):
        return text or ""
    n = int(_STRIP_CAPS.get("min_length", 3))
    return re.sub(rf"^([A-Z]{{{n},}}[\s,]+)+", "", (text or "").strip())


# ---------------------------------------------------------------- helpers

def _sr(stage, **kw):
    return M.StageResult(stage, **kw)


def _norm(text):
    if not text:
        return text
    text = text.replace("So\x00ware", "Software").replace("so\x00ware", "software")
    text = text.replace("Pro\x00cient", "Proficient").replace("pro\x00ciency", "proficiency")
    text = text.replace("con\x00g", "config").replace("Con\x00g", "Config")
    text = re.sub(r"(?<![A-Za-z])\x00x(?![A-Za-z])", "fix", text)
    text = text.replace("\x00", "ti")
    for b in ("\u2022", "\uf0b7", "\uf0a7", ""):
        text = text.replace(b, "•")
    return text


def _is_header_line(s):
    t = s.strip().strip(":").strip()
    if not t or len(t.split()) > 8:
        return None
    low = t.lower()
    for kind, names in SECTION_KINDS:
        if low in [n.lower() for n in names]:
            if re.search(r"\d", t) and kind == "EXPERIENCE" and "professional" not in low and "work" not in low:
                continue  # e.g. "Exp Total Years Experience: 5.7" is not a header
            return kind
    return None


# ---------------------------------------------------------------- stage 1

def s01_document_processing(ctx):
    """Input: raw bytes/text + filename. Output: clean text, pages, doc facts."""
    text, pages, warnings, errors = "", 1, [], []
    name = (ctx.filename or "").split("?", 1)[0].split("#", 1)[0].lower()
    try:
        if ctx.raw_bytes and (name.endswith(".pdf") or ctx.raw_bytes.startswith(b"%PDF-")):
            import pdfplumber
            import io
            pages_list = []
            with pdfplumber.open(io.BytesIO(ctx.raw_bytes)) as pdf:
                pages = len(pdf.pages)
                for p in pdf.pages:
                    pages_list.append(p.extract_text() or "")
            text = "\n".join(pages_list)
        elif ctx.raw_bytes and (name.endswith(".docx") or ctx.raw_bytes.startswith(b"PK\x03\x04")):
            from docx import Document
            import io
            doc = Document(io.BytesIO(ctx.raw_bytes))
            parts = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
            text = "\n".join(t for t in parts if t.strip())
        elif ctx.raw_bytes and name.endswith(".txt"):
            text = ctx.raw_bytes.decode("utf-8-sig")
        elif ctx.raw_text:
            text = ctx.raw_text
        else:
            errors.append("no content provided")
    except Exception as exc:  # malformed documents must not crash the pipeline
        errors.append(f"extraction failed: {type(exc).__name__}")
    text = _norm(text or "")
    ctx.raw_text = text
    ctx.meta["pages"] = pages
    if not text.strip():
        status = "FAILED"
        errors.append("empty document")
        reasons = ["DOC_EMPTY"]
        conf = 0.0
    elif len(re.findall(r"[A-Za-z]{3,}", text)) < 20:
        status = "PARTIAL"
        warnings.append("very little extractable text; scanned image PDF may need OCR")
        reasons = ["DOC_SCANNED_OCR_NEEDED"]
        conf = 0.3
    else:
        status = "SUCCESS"
        reasons = []
        conf = 0.95
    ctx.meta["char_count"] = len(text)
    return _sr("document_processing", status=status, confidence=conf,
               errors=errors, warnings=warnings,
               output={"pages": pages, "chars": len(text), "reasons": reasons},
               evidence={"filename": ctx.filename})


# ---------------------------------------------------------------- stage 2

def _join_wrapped_lines(lines):
    """Join date ranges split across line breaks ('August 2022 to' + 'till now').

    Conservative: join only when a line ends with a range separator, or when
    the next line starts with a range-continuation and this line has a year.
    """
    end_sep = re.compile(r"(to|till|until|through|-|–|—|/)\s*$", re.IGNORECASE)
    next_cont = re.compile(r"^(till|until|through|to|present|now|current)\b", re.IGNORECASE)
    has_year = re.compile(r"(19|20)\d{2}")
    out = []
    i = 0
    while i < len(lines):
        cur = lines[i].rstrip()
        nxt = lines[i + 1].lstrip() if i + 1 < len(lines) else ""
        if nxt and (end_sep.search(cur) or
                    (has_year.search(cur) and next_cont.match(nxt))):
            out.append(cur + " " + nxt)
            i += 2
        else:
            out.append(lines[i])
            i += 1
    return out


def s02_text_representation(ctx):
    """Input: clean text. Output: ordered TextBlocks (page/position/format)."""
    if not ctx.raw_text.strip():
        return _sr("text_representation", status="FAILED", confidence=0.0,
                   errors=["no text to represent"])
    lines = [ln for ln in ctx.raw_text.split("\n")]
    # crude page split: source had no page map in text mode; keep page=1
    # (submit path with bytes could map pages; extension-text path is page-less)
    lines = _join_wrapped_lines(lines)
    blocks, order = [], 0
    for ln in lines:
        s = ln.rstrip()
        if not s.strip():
            continue
        order += 1
        bold = s.isupper() and len(s.split()) <= 8
        blocks.append(M.TextBlock(f"b{order}", 1, order, s.strip(), bold=bold))
    ctx.blocks = blocks
    if not blocks:
        return _sr("text_representation", status="FAILED", confidence=0.0,
                   errors=["no text blocks"])
    return _sr("text_representation", status="SUCCESS", confidence=0.95,
               output={"blocks": len(blocks)})


# ---------------------------------------------------------------- stage 3

def s03_section_detection(ctx):
    """Input: blocks. Output: sections with confidence + reason."""
    if not ctx.blocks:
        return _sr("section_detection", status="SKIPPED", confidence=0.0,
                   errors=["no blocks"])
    bounds = []  # (index, kind, header_text)
    for i, b in enumerate(ctx.blocks):
        kind = _is_header_line(b.text)
        if kind:
            bounds.append((i, kind, b.text.strip()))
    sections = []
    ml_hints = ml_assist.section_hints(ctx.raw_text)
    for n, (idx, kind, header) in enumerate(bounds):
        nxt = bounds[n + 1][0] if n + 1 < len(bounds) else len(ctx.blocks)
        bids = [b.id for b in ctx.blocks[idx + 1:nxt]]
        sections.append(M.Section(f"s{n}", kind, header, bids, 0.9, "SECTION_HEADER_MATCH"))
    # ML hint only fills kinds missed by headers (recorded, discounted).
    if ml_hints and not any(s.kind == "EXPERIENCE" for s in sections):
        if any(lab in ("COMPANY", "JOB_TITLE", "JOB_DATE") for _, _, lab in ml_hints):
            bids = [b.id for b in ctx.blocks]
            sections.append(M.Section("sML", "EXPERIENCE", "inferred", bids, 0.5, "SECTION_ML_HINT"))
    ctx.sections = sections
    ctx.meta["ml_version"] = ml_assist.version()
    if not sections:
        return _sr("section_detection", status="PARTIAL", confidence=0.2,
                   warnings=["no section headers found"],
                   output={"sections": []}, evidence={"reason": "SECTION_MISSING"})
    kinds = sorted({s.kind for s in sections})
    return _sr("section_detection", status="SUCCESS", confidence=0.85,
               output={"sections": [s.to_dict() for s in sections], "kinds": kinds})


# ---------------------------------------------------------------- stage 4

def _looks_like_entry_start(line):
    s = line.strip()
    if PROJECT_HEAD.match(s):
        return True
    ms = D.find_mentions(s)
    if any(m["is_range"] for m in ms):
        return True
    if s.startswith("•") or not s:
        return False
    # company-only line ("BIRLASOFT LTD, BENGALURU") belongs with the role
    # line that follows — keep as pending, do not start an entry alone.
    # (Degree cues like BE also match city names, so only title/date counts.)
    if COMPANY_HINT.search(s) and not TITLE_CUE.search(s) \
            and not any(m["is_range"] for m in ms):
        return False
    words = s.split()
    if len(words) <= 12 and (COMPANY_HINT.search(s) or TITLE_CUE.search(s)
                             or DEGREE_CUE.search(s) or s.isupper()):
        return True
    return False


def _segment_section(sec_id, sec_kind, header_text, bids, by_id, entries, warnings):
    """Segment one section's blocks into entries. Returns leftover (bid, line)
    pairs that belong to an inferred PROJECTS section (EXPERIENCE only)."""
    cur_lines, cur_bids, pending, pending_ids = [], [], [], []
    leftover = []

    def flush():
        if cur_lines:
            eid = f"e{len(entries)}"
            entries.append(M.Entry(eid, sec_id, " ".join(cur_lines),
                                   list(cur_bids), len(entries)))

    for bid in bids:
        b = by_id.get(bid)
        if b is None:
            continue
        line = b.text.strip()
        if not line or line.strip(":").upper() == header_text.strip(":").upper():
            continue
        # A numbered project inside EXPERIENCE starts inferred PROJECTS content:
        # never let project metadata become employment entries.
        if sec_kind == "EXPERIENCE" and (PROJECT_HEAD.match(line) or leftover):
            if cur_lines:
                flush()
                cur_lines, cur_bids = [], []
            leftover.append((bid, line))
            continue
        if NAV_PAT.search(line):
            if cur_lines:
                flush()
                cur_lines, cur_bids = [], []
            continue
        if _looks_like_entry_start(line):
            # project metadata ("Period: Dec-23 to Nov-24") continues the
            # current project; it must not start a pseudo-job entry.
            if sec_kind == "PROJECTS" and re.match(
                    r"(?i)^\s*(period|duration|timeline|tenure)\s*:", line):
                if cur_lines:
                    cur_lines[-1] += " " + line
                    cur_bids.append(bid)
                else:
                    pending.append(line)
                    pending_ids.append(bid)
                continue
            # If current entry has content but NO dates yet, and this line
            # provides the date, attach to current entry instead of splitting.
            if cur_lines and any(m["is_range"] for m in D.find_mentions(line)) and not any(D.find_mentions(cl) for cl in cur_lines):
                cur_lines[-1] += " " + line
                cur_bids.append(bid)
                continue
            if cur_lines:
                flush()
            cur_lines = pending + [line]
            cur_bids = pending_ids + [bid]
            pending, pending_ids = [], []
            continue
        if line.startswith("•") and cur_lines:
            cur_lines.append(line)
            cur_bids.append(bid)
            continue
        if cur_lines:
            # a dateless company-only line after a dated entry belongs to the
            # NEXT entry (adjacent layout) — flush and hold as pending.
            if (COMPANY_HINT.search(line) and not TITLE_CUE.search(line)
                    and not D.find_mentions(line)
                    and any(D.find_mentions(cl) for cl in cur_lines)):
                flush()
                cur_lines, cur_bids = [], []
                pending, pending_ids = [line], [bid]
                continue
            cur_lines[-1] += " " + line
            cur_bids.append(bid)
            continue
        pending.append(line)
        pending_ids.append(bid)
    if cur_lines:
        flush()
    elif pending:
        eid = f"e{len(entries)}"
        entries.append(M.Entry(eid, sec_id, " ".join(pending), list(pending_ids), len(entries)))
        warnings.append(f"section {sec_kind}: entry without dated header preserved as-is")
    return leftover


def s04_entry_segmentation(ctx):
    """Input: sections+blocks. Output: entries preserving text + location."""
    if not ctx.sections:
        return _sr("entry_segmentation", status="SKIPPED", confidence=0.0,
                   errors=["no sections"])
    by_id = {b.id: b for b in ctx.blocks}
    entries, warnings = [], []
    inferred = []  # (bid, line) pairs for a synthetic PROJECTS section
    for sec in ctx.sections:
        if sec.kind not in ("EXPERIENCE", "EDUCATION", "PROJECTS"):
            continue
        rest = _segment_section(sec.id, sec.kind, sec.header_text,
                                sec.block_ids, by_id, entries, warnings)
        inferred.extend(rest)
    if inferred:
        proj_sec = M.Section("s-inf", "PROJECTS", "inferred projects",
                             [bid for bid, _ in inferred], 0.6, "SECTION_INFERRED")
        ctx.sections.append(proj_sec)
        warnings.append(f"{len(inferred)} lines moved to inferred PROJECTS section")
        _segment_section(proj_sec.id, "PROJECTS", proj_sec.header_text,
                         proj_sec.block_ids, by_id, entries, warnings)
    ctx.entries = entries
    if not entries:
        return _sr("entry_segmentation", status="PARTIAL", confidence=0.3,
                   warnings=["no entries segmented"] + warnings,
                   output={"entries": 0})
    return _sr("entry_segmentation", status="SUCCESS", confidence=0.8,
               warnings=warnings, output={"entries": len(entries)})


# ---------------------------------------------------------------- stage 5

def s05_date_extraction(ctx):
    """Input: entries+blocks. Output: DateMentions (raw preserved, precision kept)."""
    if not ctx.entries and not ctx.blocks:
        return _sr("date_extraction", status="SKIPPED", confidence=0.0,
                   errors=["nothing to scan"])
    mentions, invalid = [], []
    today = date.today()
    # scan every block so no date is silently dropped; link to entry when possible
    for b in ctx.blocks:
        for m in D.find_mentions(b.text, today):
            ent = ctx.entry_of_block(b.id)
            mid = f"m{len(mentions)}"
            precision = m["precision"]
            s, e = m["start"], m["end"]
            if precision == "year":
                s, e = (s[0], 1), (e[0], 12)
            mentions.append(M.DateMention(mid, b.id, ent.id if ent else None,
                                          m["raw"], 0, 0, precision, s, e,
                                          m["is_range"], m["is_present"]))
    ctx.mentions = mentions
    if not mentions:
        return _sr("date_extraction", status="PARTIAL", confidence=0.3,
                   warnings=["no dates found"],
                   output={"mentions": 0}, evidence={"reason": "INSUFFICIENT_DATES"})
    return _sr("date_extraction", status="SUCCESS", confidence=0.9,
               output={"mentions": len(mentions),
                       "ranges": sum(1 for m in mentions if m.is_range)})


# ---------------------------------------------------------------- stage 6

def s06_date_association(ctx):
    """Input: entries+mentions. Output: CONFIRMED/AMBIGUOUS/UNRESOLVED assocs."""
    if not ctx.entries:
        return _sr("date_association", status="SKIPPED", confidence=0.0,
                   errors=["no entries"])
    by_entry = {}
    for m in ctx.mentions:
        if m.entry_id:
            by_entry.setdefault(m.entry_id, []).append(m)
    assocs, warnings = [], []
    for e in ctx.entries:
        ms = sorted(by_entry.get(e.id, []),
                    key=lambda m: (m.block_id, D.month_index(m.start) if m.start else 0, m.char_start))
        ranges = [m for m in ms if m.is_range]
        if len(ranges) == 1:
            r = ("ASSOC_SAME_LINE" if any(ranges[0].block_id == b for b in e.block_ids) else "ASSOC_PROXIMITY")
            assocs.append(M.DateAssoc(f"a{len(assocs)}", e.id, ranges[0].id, "CONFIRMED", 0.9, r))
        elif len(ranges) > 1:
            assocs.append(M.DateAssoc(f"a{len(assocs)}", e.id, ranges[0].id, "AMBIGUOUS", 0.6, "ASSOC_AMBIGUOUS_MULTI"))
            warnings.append(f"entry {e.id}: {len(ranges)} ranges; first kept, rest preserved in evidence")
            for r_ in ranges[1:]:
                assocs.append(M.DateAssoc(f"a{len(assocs)}", e.id, r_.id, "AMBIGUOUS", 0.5, "ASSOC_AMBIGUOUS_MULTI"))
        else:
            singles = sorted([m for m in ms if not m.is_range and m.precision == "month"],
                             key=lambda m: (D.month_index(m.start) if m.start else 0, m.char_start))
            if len(singles) >= 2:
                # span interpretation, explicitly ambiguous — never silent
                a0 = M.DateAssoc(f"a{len(assocs)}", e.id, singles[0].id, "AMBIGUOUS", 0.55, "ASSOC_AMBIGUOUS_MULTI")
                a0.span_end_id = singles[-1].id  # ad-hoc span pointer (serialized below)
                assocs.append(a0)
                warnings.append(f"entry {e.id}: singles spanned {singles[0].raw}..{singles[-1].raw} (ambiguous)")
            else:
                assocs.append(M.DateAssoc(f"a{len(assocs)}", e.id, None, "UNRESOLVED", 0.3, "ASSOC_UNRESOLVED_NO_DATE"))
    # serialize ad-hoc span pointers into reason payload
    for a in assocs:
        if hasattr(a, "span_end_id"):
            a.reason += f":{a.span_end_id}"
            delattr(a, "span_end_id")
    ctx.assocs = assocs
    n_unres = sum(1 for a in assocs if a.status == "UNRESOLVED")
    status = "PARTIAL" if n_unres else "SUCCESS"
    return _sr("date_association", status=status,
               confidence=0.8 if not n_unres else 0.6,
               warnings=warnings,
               output={"assocs": len(assocs), "unresolved": n_unres})


# ---------------------------------------------------------------- stage 7

def _clean_org(org):
    org = re.sub(r"^[\[\(\-–—\s|]+", "", (org or "").strip())
    org = re.split(r"\s+[—|]\s+|\s+\|\s+", org, maxsplit=1)[0]
    org = re.sub(r"[\]\)\s|.,;:-]+$", "", org.strip())
    org = re.sub(r"\s+", " ", org).strip()
    return org[:120]


def _org_from_line(line):
    """Company fragment around the company-hint match (brackets stripped)."""
    s = re.sub(r"[\[\]()]", " ", line or "")
    m = COMPANY_HINT.search(s)
    if not m:
        return ""
    before = [s.rfind(sep, 0, m.start()) for sep in (",", "|", "—", "(", "[")]
    start = max(before)
    after = [s.find(sep, m.end()) for sep in (",", "|", ")", "]")]
    after = [a for a in after if a >= 0]
    end = min(after) if after else len(s)
    return _clean_org(s[start + 1:end])


def _split_title_org(text):
    # NOTE: leading-caps stripping applies to titles only (never orgs),
    # so "QUESS CORP PVT LTD, BENGALURU" keeps its company half intact.
    text = (text or "").lstrip("▪•·‐-–—| ")
    # "Title, Company, Date..." or "Company | Title | Date" first
    for sep in ("|", ","):
        if sep in text:
            parts = [p.strip(" -–—") for p in text.split(sep) if p.strip(" -–—")]
            orgs = [p for p in parts if COMPANY_HINT.search(p)]
            if orgs:
                org = _clean_org(orgs[0])
                rest = [p for p in parts if p != orgs[0] and not D.find_mentions(p)]
                title = next((p for p in rest if TITLE_CUE.search(p)), "")
                if not title and rest and len(rest[0].split()) > 2:
                    title = rest[0]  # multi-word fallback only; lone cities dropped
                title = _strip_leading_caps(title)
                return title.strip(" -–—[]|,"), org
    # "Developer in Capgemini[, Bangalore]" pattern (no Pvt/Ltd cue)
    m = re.search(r"\bin\s+([A-Z][A-Za-z&]*)(?:\s*,\s*[A-Z][A-Za-z&., ]*)?\s*$",
                  text.strip())
    if m and TITLE_CUE.search(text[:m.start()]):
        return _strip_leading_caps(
            text[:m.start()]).strip(" -–—,|[]▪•"), _clean_org(m.group(1))
    m = COMPANY_HINT.search(text)
    if m:
        tm = re.match(r"^(.*?(?:Engineer|Developer|Analyst|Manager|Consultant|Architect|"
                      r"Tester|Lead|Administrator|Specialist|Owner|Head|Intern|Associate|"
                      r"Designer|Scientist))\s+(.+)$", text.strip(), re.IGNORECASE)
        if tm:
            return _strip_leading_caps(tm.group(1)).strip(" -–—[]|,"), _clean_org(tm.group(2))
        idx = text.lower().find(m.group(0).lower())
        return _strip_leading_caps(text[:idx]).strip(" -–—,|[]▪•"), _clean_org(text[idx:])
    return _strip_leading_caps(text).strip(" -–—[]|,▪•"), ""


def s07_event_classification(ctx):
    """Input: entries+assocs. Output: typed Events (employment/education/...)."""
    if not ctx.entries:
        return _sr("event_classification", status="SKIPPED", confidence=0.0,
                   errors=["no entries"])
    sec_kind = {s.id: s.kind for s in ctx.sections}
    sec_conf = {s.id: s.confidence for s in ctx.sections}
    assoc_by_entry = {}
    for a in ctx.assocs:
        assoc_by_entry.setdefault(a.entry_id, []).append(a)
    events, warnings = [], []
    for pos, e in enumerate(ctx.entries):
        kind = sec_kind.get(e.section_id, "OTHER")
        low = e.text.lower()
        if INTERNSHIP_RE.search(e.text) and kind == "EXPERIENCE":
            etype, reason = "INTERNSHIP", "EVENT_INTERNSHIP_CUES"
        elif kind == "EDUCATION":
            etype, reason = "EDUCATION", "EVENT_EDUCATION_CUES"
        elif kind == "PROJECTS":
            etype, reason = "PROJECT", "EVENT_PROJECT_CUES"
        elif kind == "EXPERIENCE":
            etype, reason = "EMPLOYMENT", "EVENT_EMPLOYMENT_CUES"
        else:
            etype, reason = "OTHER", "EVENT_UNCLASSIFIED"
        blocks_by_id = ctx.blocks_by_id()
        first_line = (blocks_by_id[e.block_ids[0]].text if e.block_ids
                      and e.block_ids[0] in blocks_by_id
                      else e.text.split("•")[0])[:200]
        # date span from best assoc (resolved first so dates never leak into titles)
        aa = assoc_by_entry.get(e.id, [])
        confirmed = [a for a in aa if a.status == "CONFIRMED"]
        ambig = [a for a in aa if a.status == "AMBIGUOUS"]
        by_mid = {m.id: m for m in ctx.mentions}
        best_mention = None
        if confirmed and confirmed[0].mention_id in by_mid:
            best_mention = by_mid[confirmed[0].mention_id]
        elif ambig and ambig[0].mention_id in by_mid:
            best_mention = by_mid[ambig[0].mention_id]
        # title comes from the role line (first block with a title cue or date),
        # company from the first company-hint block anywhere in the entry.
        role_line, company_line, role_found = first_line, "", False
        for bid in e.block_ids:
            t = (blocks_by_id[bid].text if bid in blocks_by_id else "")
            if not company_line and COMPANY_HINT.search(t):
                company_line = t
            if not role_found and (TITLE_CUE.search(t) or D.find_mentions(t)):
                role_line, role_found = t, True
        role_line = role_line[:200]
        if best_mention is not None:
            role_line = role_line.replace(best_mention.raw, " ", 1)
            role_line = re.sub(r"\s+", " ", role_line).strip(" -–—,|[]")
            role_line = re.sub(r"\b(in|to|till|until|from|at)\s*$", "", role_line,
                               flags=re.IGNORECASE).strip(" -–—,|")
        title, org = _split_title_org(role_line)
        if not org and company_line:
            org = _org_from_line(company_line)
        if etype == "PROJECT":
            # prefer explicit cues over the first line for project names;
            # project orgs come only from an explicit Client cue (never guessed).
            for pat in PROJECT_FIELD_PATS:
                pm = re.search(pat, e.text, re.IGNORECASE)
                if pm:
                    val = re.split(r"\s*(?:Role|Period|Duration|Environment|Team Size|"
                                   r"Description|Timeline|Tenure)\s*:",
                                   pm.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
                    title = val.split("\n")[0].strip(" -–—:")[:120]
                    break
            org = ""
            cm = re.search(r"Client\s*(?:Name)?\s*:\s*(.+?)(?:\s+Role\s*:|\s*$)",
                           e.text, re.IGNORECASE)
            if cm:
                org = _clean_org(cm.group(1)[:120])
            # skip the generic company-line scan for projects below
            _skip_company_scan = True
        else:
            _skip_company_scan = False
        if not org and not _skip_company_scan and len(e.block_ids) > 1:
            for bid in e.block_ids[1:3]:
                b2 = blocks_by_id.get(bid)
                if b2 and (COMPANY_HINT.search(b2.text) or " in " in b2.text.lower()):
                    org = _org_from_line(b2.text) or _split_title_org(b2.text[:160])[1]
                    if org:
                        break
        if not org and not _skip_company_scan:
            # company line sometimes follows the role line (role, then org);
            # borrow it from the next same-section entry only.
            for nxt in ctx.entries[pos + 1:pos + 2]:
                if nxt.section_id != e.section_id:
                    break
                nb = blocks_by_id.get(nxt.block_ids[0] if nxt.block_ids else "")
                if nb and COMPANY_HINT.search(nb.text):
                    cand = _org_from_line(nb.text)
                    if cand:
                        org = cand
                        warnings.append(f"event from {e.id}: org taken from following entry")
                        break
        status, span, precision, conf = "UNRESOLVED", None, "month", 0.3
        aids = [a.id for a in aa]
        if best_mention is not None:
            m_ = best_mention
            span, precision = (m_.start, m_.end), m_.precision
            if ambig and ambig[0].reason and ":" in ambig[0].reason:
                end_mid = ambig[0].reason.split(":")[-1]
                if end_mid in by_mid:
                    span = (m_.start, by_mid[end_mid].end)
            if confirmed and confirmed[0].mention_id in by_mid:
                status = "CONFIRMED"
                conf = EV.event_confidence("CONFIRMED", precision, sec_conf.get(e.section_id, 1.0))
            else:
                status = "AMBIGUOUS"
                conf = EV.event_confidence("AMBIGUOUS", precision, sec_conf.get(e.section_id, 1.0))
                warnings.append(f"event from {e.id} is ambiguous")
        else:
            ctx.unresolved.append(e.id)
        if span is None:
            # unresolved events are kept (NEVER silently discarded) without dates
            ev = M.Event(f"v{len(events)}", e.id, aids, etype, title, org,
                         None, None, precision, "UNRESOLVED", conf, [reason])
        else:
            ev = M.Event(f"v{len(events)}", e.id, aids, etype, title, org,
                         span[0], span[1], precision, status, conf, [reason])
        events.append(ev)
    ctx.events = events
    return _sr("event_classification", status="SUCCESS", confidence=0.8,
               warnings=warnings, output={"events": len(events),
                                          "unresolved": len(ctx.unresolved)})


# ---------------------------------------------------------------- stage 8

def s08_timeline_reconciliation(ctx):
    """Input: events. Output: chronological timeline; overlaps kept, never errors."""
    dated = [e for e in ctx.events if e.start and e.end]
    dated.sort(key=lambda e: D.month_index(e.start))
    warnings = []
    for a, b in zip(dated, dated[1:]):
        if D.month_index(b.start) <= D.month_index(a.end):
            warnings.append(f"overlap preserved: '{a.title}' overlaps '{b.title}'")
    for e in ctx.events:
        if e.status == "AMBIGUOUS":
            warnings.append(f"conflicting/ambiguous date kept for '{e.title}'")
    ctx.meta["timeline_order"] = [e.id for e in dated]
    status = "SUCCESS"
    if not dated:
        status = "PARTIAL"
        warnings.append("no dated events to order")
    return _sr("timeline_reconciliation", status=status, confidence=0.85,
               warnings=warnings,
               output={"dated_events": len(dated),
                       "order": ctx.meta["timeline_order"],
                       "unresolved_events": len(ctx.unresolved)},
               evidence={"reasons": ["OVERLAP_PRESERVED", "CONFLICT_PRESERVED"]})


# ---------------------------------------------------------------- stage 9

def s09_coverage_analysis(ctx):
    """Input: dated events. Output: unioned coverage intervals + totals."""
    dated = [e for e in ctx.events if e.start and e.end]
    if not dated:
        return _sr("coverage_analysis", status="PARTIAL", confidence=0.3,
                   warnings=["no intervals to cover"],
                   output={"coverage": [], "total_months": 0})
    ivs = [I.normalize_interval(e.start, e.end, e.precision) for e in dated]
    unioned = I.union(ivs)
    total = I.total_months(unioned)
    ctx.coverage = unioned
    ctx.total_months = total
    return _sr("coverage_analysis", status="SUCCESS", confidence=0.9,
               output={"coverage": [{"start": list(s), "end": list(e)} for s, e in unioned],
                       "total_months": total})


# ---------------------------------------------------------------- stage 10

def s10_gap_detection(ctx):
    """Input: dated events + coverage. Output: gaps with states.

    A gap means ONLY 'no activity clearly represented here' — the system
    never claims unemployment (enforced: the token never appears).
    """
    dated = [e for e in ctx.events if e.start and e.end]
    dated.sort(key=lambda e: D.month_index(e.start))
    gaps = []
    if len(dated) < 2:
        g = M.Gap("g0", None, None, 0, "INSUFFICIENT_EVIDENCE", 0.4,
                  ["INSUFFICIENT_DATES"],
                  {"note": "fewer than two dated events; no gap inference possible"})
        gaps = [g]
    else:
        max_end = dated[0].end
        last_event = dated[0]
        for b in dated[1:]:
            gm = D.months_between(max_end, b.start)
            if gm > 0:
                g = M.Gap(f"g{len(gaps)}", list(max_end), list(b.start), gm, "POTENTIAL_GAP",
                          0.0, ["GAP_NO_COVERAGE"],  # confidence filled in stage 11
                          {"event_before": last_event.id, "event_after": b.id})
                gaps.append(g)
            if D.month_index(b.end) > D.month_index(max_end):
                max_end = b.end
                last_event = b
        if not gaps:
            g = M.Gap("g0", None, None, 0, "NO_GAP_DETECTED", 0.9, [],
                      {"note": "continuous representation across dated events"})
            gaps = [g]
    for g in gaps:
        assert "unemploy" not in (g.state + " ".join(g.reasons)).lower()
    ctx.gaps = gaps
    states = sorted({g.state for g in gaps})
    return _sr("gap_detection", status="SUCCESS", confidence=0.85,
               output={"gaps": [g.to_dict() for g in gaps], "states": states})


# ---------------------------------------------------------------- stage 11

def s11_confidence_evidence(ctx):
    """Input: gaps+events+entries+assocs+mentions+blocks. Output: confidences + lineage."""
    by_ev, by_en = ctx.events_by_id(), ctx.entries_by_id()
    by_a, by_m, by_b = ctx.assocs_by_id(), ctx.mentions_by_id(), ctx.blocks_by_id()
    for g in ctx.gaps:
        if g.state != "POTENTIAL_GAP":
            continue
        cb = by_ev.get(g.evidence.get("event_before"))
        ca = by_ev.get(g.evidence.get("event_after"))
        g.confidence = EV.gap_confidence(cb.confidence if cb else None,
                                         ca.confidence if ca else None, True)
        ctx.lineage[g.id] = EV.lineage(g, by_ev, by_en, by_a, by_m, by_b, ctx.doc_id)
    return _sr("confidence_evidence", status="SUCCESS", confidence=0.9,
               output={"gaps_scored": sum(1 for g in ctx.gaps if g.state == "POTENTIAL_GAP"),
                       "lineage_built": len(ctx.lineage)})


# ---------------------------------------------------------------- stage 12

def s12_recruiter_output(ctx):
    """Input: everything. Output: extension-facing DTO (timeline, gaps, evidence)."""
    dated = [e for e in ctx.events if e.start and e.end]
    dto_events = [{
        "id": e.id, "type": e.type, "title": e.title, "org": e.org,
        "start": f"{e.start[0]:04d}-{e.start[1]:02d}" if e.start else None,
        "end": f"{e.end[0]:04d}-{e.end[1]:02d}" if e.end else None,
        "precision": e.precision, "status": e.status,
        "confidence": e.confidence, "reasons": e.reasons} for e in dated]
    dto_gaps = []
    for g in ctx.gaps:
        d = g.to_dict()
        if g.start and g.end:
            d["start_label"] = f"{g.start[0]:04d}-{g.start[1]:02d}"
            d["end_label"] = f"{g.end[0]:04d}-{g.end[1]:02d}"
        # attach short evidence quotes for the browser UI
        chain = ctx.lineage.get(g.id, {})
        quotes = []
        for link in chain.get("links", []):
            q = link.get("entry_quote", "")
            if q:
                quotes.append(q[:300])
        d["evidence_quotes"] = quotes
        dto_gaps.append(d)
    overall = _overall_status(ctx)
    dto = {
        "doc_id": ctx.doc_id,
        "filename": ctx.filename,
        "candidate_name": _guess_candidate_name(ctx),
        "status": overall,
        "timeline": dto_events,
        "unresolved_events": [
            {"id": e.id, "type": e.type, "title": e.title, "org": e.org,
             "entry_text": by_en_text(ctx, e.entry_id)}
            for e in ctx.events if not (e.start and e.end)],
        "gaps": dto_gaps,
        "total_represented_months": ctx.total_months,
        "stages": {k: {"status": v.status, "confidence": v.confidence}
                   for k, v in ctx.stage_results.items()},
        "model_versions": dict(ctx.model_versions),
        "disclaimer": ("Potential gaps mark periods with no clearly represented "
                       "activity in the resume. They are not evidence of unemployment. "
                       "The recruiter makes the final decision."),
    }
    ctx.recruiter_output = dto
    return _sr("recruiter_output", status="SUCCESS", confidence=0.95,
               output={"events": len(dto_events), "gaps": len(dto_gaps)})


def by_en_text(ctx, entry_id):
    e = ctx.entries_by_id().get(entry_id)
    return (e.text[:300] if e else "")


def _guess_candidate_name(ctx):
    """Heuristic display name only (first content line); never used in logic."""
    skip = {"detailed info", "professional summary", "summary", "objective",
            "contact", "resume", "curriculum vitae", "profile"}
    for ln in (ctx.raw_text or "").split("\n")[:8]:
        s = ln.strip()
        if not s or "@" in s or "linkedin" in s.lower() or "github" in s.lower():
            continue
        if re.search(r"(19|20)\d{2}|present|years|experience|engineer|developer|mob|phone|india", s.lower()):
            m = re.split(r"[–—\-|]", s)[0].strip()
            parts = m.split()
            if 2 <= len(parts) <= 4 and re.match(r"^[A-Za-z .]+$", m):
                return m.title()
            continue
        cand = re.split(r"[–—\-|]", s)[0].strip()
        if cand.lower() in skip:
            continue
        if 2 <= len(cand.split()) <= 4 and re.match(r"^[A-Za-z .]+$", cand):
            return cand.title()
    return ""


def _overall_status(ctx):
    vals = [r.status for r in ctx.stage_results.values()]
    if "FAILED" in vals[:2]:
        return "FAILED"
    if "FAILED" in vals or "PARTIAL" in vals:
        return "PARTIAL"
    if vals and all(v == "SUCCESS" for v in vals):
        return "SUCCESS"
    return "PARTIAL"


STAGE_FUNCS = (
    s01_document_processing, s02_text_representation, s03_section_detection,
    s04_entry_segmentation, s05_date_extraction, s06_date_association,
    s07_event_classification, s08_timeline_reconciliation, s09_coverage_analysis,
    s10_gap_detection, s11_confidence_evidence, s12_recruiter_output,
)


STAGE_SPECS = {fn.__name__[4:]: {
    "input": doc, "output": out, "statuses": M.STAGE_STATUSES}
    for fn, (doc, out) in zip(STAGE_FUNCS, [
        ("raw bytes/text + filename", "clean text, pages, doc facts"),
        ("clean text", "ordered TextBlocks"),
        ("blocks", "sections + confidence"),
        ("sections + blocks", "entries with text + location"),
        ("entries + blocks", "date mentions (raw + precision)"),
        ("entries + mentions", "confirmed/ambiguous/unresolved assocs"),
        ("entries + assocs", "typed events"),
        ("events", "chronological timeline, overlaps kept"),
        ("dated events", "unioned coverage + totals"),
        ("dated events + coverage", "gaps (never 'unemployed')"),
        ("gaps + chain artifacts", "confidences + lineage"),
        ("all artifacts", "extension-facing DTO"),
    ])}
