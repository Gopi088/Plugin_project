"""The 12-stage processing pipeline.

Every stage: ``run(ctx) -> StageResult`` with defined input/output/status/
evidence/confidence/error handling (see STAGE_SPECS). Deterministic logic
decides wherever the answer is unambiguous; ML (ml_assist) only supplies
hints. Nothing is ever invented: ambiguous cases stay AMBIGUOUS/UNRESOLVED.
"""

import calendar
import re
import hashlib
import json
from datetime import date

from .. import datamodel as M
from .. import dates as D
from .. import intervals as I
from .. import evidence as EV
from .. import ml_assist
from .. import source as SRC
from ..cues import load as _load_cues

_CUES = _load_cues()


def _rx(fragments):
    return re.compile("|".join(f"(?<!\\w)(?:{f})(?!\\w)" for f in fragments), re.IGNORECASE)


COMPANY_HINT = _rx(_CUES["company_suffixes_regex"])
TITLE_CUE = _rx(_CUES["title_words_regex"])
DEGREE_CUE = _rx(_CUES["degree_words_regex"])
NAV_PAT = _rx(_CUES["nav_terms_regex"])
PROJECT_FIELD_PATS = list(_CUES["project_field_labels_regex"])
INTERNSHIP_WORDS = [w.lower() for w in _CUES.get("internship_words", ["intern"])]
INTERNSHIP_RE = re.compile(r"\b(?:" + "|".join(
    re.escape(w) for w in INTERNSHIP_WORDS) + r")\b", re.IGNORECASE)
_STRIP_CAPS = _CUES.get("strip_leading_caps", {"enabled": True, "min_length": 3})
PROJECT_HEAD = re.compile(r"^\s*PROJECT\s*[-#]?\s*\d+\s*[:\-–.]?\s*(.+?)\s*$", re.IGNORECASE)
BULLET_PREFIXES = ("•", "●", "■", "▪", "·", "○", "◆", "◇", "➢", "", "✔", "►", "▸", "✓", "★", "*", "–", "—", "-")

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
    for b in ("\u2022", "\uf0b7", "\uf0a7", "", "●", "■", "▪", "·", "○", "◆", "◇", "➢", "", "✔", "►", "▸", "✓", "★"):
        text = text.replace(b, "•")
    return text


def _is_header_line(s):
    t = s.strip().strip("#* ").strip(":").strip()
    t = re.sub(r"^\d+[.)]?\s+", "", t)
    if not t or len(t.split()) > 8:
        return None
    if re.match(r"(?i)^(?:key\s+result\s+areas?|responsibilities|key\s+responsibilities|roles?\s*(?:and|&)\s*responsibilities|duties|tools|technologies|environment)\b", t):
        return None
    low = t.lower()
    if re.fullmatch(r"open[ -]source\s+(?:projects?|contributions?)", low):
        return "PROJECTS"
    for kind, names in SECTION_KINDS:
        if low in [n.lower() for n in names]:
            if re.search(r"\d", t) and kind == "EXPERIENCE" and "professional" not in low and "work" not in low:
                continue  # e.g. "Exp Total Years Experience: 5.7" is not a header
            return kind
    if re.match(r"(?i)^(?:key\s+|notable\s+|major\s+|client\s+|academic\s+|personal\s+)?projects?(?:\s*(?:and|&|\/)\s*(?:pocs?|research))?(?:\s*(?:profile|details|handled|experience|undertaken|summary))?\s*:?\s*$", t):
        return "PROJECTS"
    if re.match(r"(?i)^(?:projects?\s*(?:&|and)\s*research|research\s*(?:&|and)\s*projects?)\s*:?$", t):
        return "PROJECTS"
    if not re.search(r"\d", t) and not DESCRIPTION.match(t):
        if re.match(r"(?i)^(?:professional|work|career|employment|corporate|industry|relevant|chronological)?\s*(?:history|background|timeline|chronology|record|engagements|profile|path|journey|positions(?:\s+held)?)\s*:?$", t) and 1 < len(t.split()) <= 6:
            return "EXPERIENCE"
        # NOTE: single generic words like "Details:" must NOT become EDUCATION;
        # they are project sub-labels (e.g. "Details:" under a POC/Project).
        # Explicit single-word headers (EDUCATION, ACADEMIC, ...) are already
        # handled by the SECTION_KINDS exact match above.
        if re.match(r"(?i)^(?:academic|educational|education)?\s*(?:qualifications?|background|history|credentials|education)\s*:?$", t) and 1 < len(t.split()) <= 6:
            return "EDUCATION"
    return None


# ---------------------------------------------------------------- stage 1

def s01_document_processing(ctx):
    """Input: raw bytes/text + filename. Output: clean text, pages, doc facts."""
    import subprocess
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
                    lines = SRC.pdf_lines(p, _norm)
                    page_text = "\n".join(line['text'] for line in lines) if lines else (p.extract_text() or "")
                    if not page_text.strip():
                        ctx.meta["reading_incomplete"] = True
                        try:
                            from ..ocr import extract_page
                            lines = extract_page(ctx.raw_bytes, p.page_number, _norm)
                            page_text = "\n".join(line['text'] for line in lines)
                            if page_text.strip():
                                ctx.meta.setdefault("ocr_pages", []).append(p.page_number)
                                warnings.append(f"page {p.page_number}: OCR-derived text needs verification")
                        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                            warnings.append(f"page {p.page_number}: {exc}")
                    pages_list.append(page_text)
                    ctx.meta.setdefault("source_lines", []).extend(lines)
            text = "\n".join(pages_list)
        elif ctx.raw_bytes and (name.endswith(".docx") or ctx.raw_bytes.startswith(b"PK\x03\x04")):
            from docx import Document
            import io
            try:
                doc = Document(io.BytesIO(ctx.raw_bytes))
            except KeyError:
                from ..documents import recover_docx_body
                text = recover_docx_body(ctx.raw_bytes)
                ctx.meta["reading_incomplete"] = True
                warnings.append("DOCX has broken package relationships; original body text recovered, verify against original")
            else:
                parts = []
                for block in doc.iter_inner_content():
                    if hasattr(block, "text"):
                        parts.append(block.text)
                    else:
                        for row in block.rows:
                            parts.append(" | ".join(c.text.strip() for c in row.cells))
                text = "\n".join(t for t in parts if t.strip())
        elif ctx.raw_bytes and name.endswith(".doc"):
            import shutil
            executable = shutil.which('antiword')
            if not executable:
                raise RuntimeError('Legacy DOC requires antiword')
            result = subprocess.run([executable, '-'], input=ctx.raw_bytes, capture_output=True, timeout=60)
            if result.returncode:
                raise RuntimeError('antiword could not read this legacy DOC document')
            text = result.stdout.decode('utf-8')
        elif ctx.raw_bytes and name.endswith(".txt"):
            text = ctx.raw_bytes.decode("utf-8-sig")
        elif ctx.raw_bytes and (name.endswith(".txt") or name.endswith(".json")):
            try:
                decoded = ctx.raw_bytes.decode("utf-8-sig")
                if name.endswith(".json"):
                    jdata = json.loads(decoded)
                    text = jdata["text"] if isinstance(jdata, dict) and "text" in jdata else decoded
                else:
                    text = decoded
            except Exception:
                text = ctx.raw_bytes.decode("utf-8-sig", errors="ignore")
        elif ctx.raw_text:
            text = ctx.raw_text
        else:
            errors.append("no content provided")
    except ModuleNotFoundError as exc:
        import sys
        errors.append(f"missing Python dependency {exc.name!r}; interpreter: {sys.executable}. Install requirements.txt with the project venv/bin/python.")
    except Exception as exc:  # malformed documents must not crash the pipeline
        errors.append(f"extraction failed: {type(exc).__name__}")
    ctx.meta["original_text"] = text or ""
    text = _norm(text or "")
    ctx.raw_text = text
    ctx.meta["pages"] = pages
    if not text.strip():
        status = "FAILED"
        errors.append("empty document")
        reasons = ["DOC_EMPTY"]
        conf = 0.0
    elif ctx.meta.get("reading_incomplete") or len(re.findall(r"[A-Za-z]{3,}", text)) < 20:
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
    source_lines = ctx.meta.get("source_lines")
    if source_lines is None:
        source_lines, offset = [], 0
        for line in ctx.meta.get("original_text", ctx.raw_text).split("\n"):
            source_lines.append(SRC.normalized_line(line, [None] * len(line), _norm, 1, offset=offset))
            offset += len(line) + 1
    blocks, order = [], 0
    i = 0
    while i < len(source_lines):
        line = source_lines[i]
        text = line['text']
        parts = [{'start': 0, 'end': len(text), 'line': line}]
        # Keep both original anchors when joining a wrapped date range.
        if i + 1 < len(source_lines) and source_lines[i + 1]['page'] == line['page']:
            nxt = source_lines[i + 1]
            joined = _join_wrapped_lines([text, nxt['text']])
            if len(joined) == 1:
                parts.append({'start': len(text) + 1, 'end': len(joined[0]), 'line': nxt})
                text = joined[0]
                i += 1
        i += 1
        if not text.strip():
            continue
        order += 1
        block = M.TextBlock(f"b{order}", line['page'], order, text,
                            bold=bool(line.get("bold")) or (text.isupper() and len(text.split()) <= 8))
        block.source_parts = parts
        blocks.append(block)
    ctx.blocks = blocks
    if not blocks:
        return _sr("text_representation", status="FAILED", confidence=0.0,
                   errors=["no text blocks"])
    return _sr("text_representation", status="SUCCESS", confidence=0.95,
               output={"blocks": len(blocks)})


# ---------------------------------------------------------------- stage 3

def _looks_like_job_start(blocks, i):
    b = blocks[i]
    text = b.text.strip()
    if not text or len(text.split()) > 25:
        return False
    if text.startswith(BULLET_PREFIXES) and not any(m['is_range'] for m in D.find_mentions(text)):
        return False
    clean = text.lstrip("•●■▪·○◆◇➢✔►▸✓★-*–— ")
    if DESCRIPTION.match(clean) or DOB_OR_PERSONAL_RE.search(text):
        return False
    if DEGREE_CUE.search(text) or re.search(r'\b(?:bachelor|master|b\.?\s*tech|m\.?\s*tech|diploma|ph\.?d|degree|university|college|school|cgpa)\b', text, re.I):
        return False
    if PROJECT_HEAD.match(clean) or re.match(r"(?i)^\s*(?:project|poc)\b", clean):
        return False
    if re.match(r"(?i)^\s*(?:key\s+result\s+areas?|responsibilities|key\s+responsibilities|roles?\s*(?:and|&)\s*responsibilities|duties|tools|technologies|environment|client(?:\s*name)?|project\s+role|role|duration|period|tenure|timeline)\b", clean):
        return False
    if re.match(r"(?i)^\s*(?:microsoft mvp|certified|hackathon|published author|ieee|patent|paper|conference)\b", clean):
        return False

    has_date_range = any(m['is_range'] for m in D.find_mentions(text))
    prev_has_date = False
    if not has_date_range and i > 0:
        prev_t = blocks[i - 1].text.strip()
        prev_has_date = any(m['is_range'] for m in D.find_mentions(prev_t)) and not DEGREE_CUE.search(prev_t)
    adj_has_date = False
    if not has_date_range and not prev_has_date and i + 1 < len(blocks):
        next_t = blocks[i + 1].text.strip()
        adj_has_date = any(m['is_range'] for m in D.find_mentions(next_t)) and not DEGREE_CUE.search(next_t)

    has_title = bool(TITLE_CUE.search(text))
    has_comp = bool(COMPANY_HINT.search(text))
    has_emp_syntax = bool(re.search(r"(?i)\b(?:as\s+(?:an?\s+)?\w+|at\s+[A-Z]|\bworked\b|\bworking\b|\bemployed\b|intern\b)", text))
    has_label = bool(re.match(r"(?i)^\s*(?:company|employer|organization|position|designation|job title)\s*[:]", text))

    if has_date_range or prev_has_date:
        return has_title or has_comp or has_emp_syntax or has_label or (text[0].isupper() and len(text.split()) <= 15)
    elif adj_has_date:
        return has_title or has_comp or has_label
    return False


def _looks_like_edu_start(blocks, i):
    b = blocks[i]
    text = b.text.strip()
    if not text or len(text.split()) > 30:
        return False
    clean = text.lstrip("•●■▪·○◆◇➢✔►▸✓★-*–— ")
    if DESCRIPTION.match(clean) or DOB_OR_PERSONAL_RE.search(text):
        return False
    has_degree = bool(DEGREE_CUE.search(text) or re.search(r'\b(?:bachelor|master|b\.?\s*tech|m\.?\s*tech|diploma|ph\.?d|bca|mca|b\.?sc|m\.?sc|b\.?e\.?)\b', text, re.I))
    if not has_degree:
        return False
    has_date = bool(D.find_mentions(text))
    has_inst = bool(re.search(r'(?i)\b(?:university|college|institute|school|board|academy)\b', text))
    return has_date or has_inst


def s03_section_detection(ctx):
    """Input: blocks. Output: sections with confidence + reason."""
    if not ctx.blocks:
        return _sr("section_detection", status="SKIPPED", confidence=0.0,
                   errors=["no blocks"])
    bounds = []  # (index, kind, header_text, is_implicit)
    for i, b in enumerate(ctx.blocks):
        kind = _is_header_line(b.text)
        if (kind == "PROJECTS" and b.text.strip().casefold() == "project" and i
                and D.find_mentions(ctx.blocks[i - 1].text)
                and TITLE_CUE.search(ctx.blocks[i - 1].text)):
            # A wrapped job title ending in "... in AML / Project" is not a section.
            continue
        if kind:
            bounds.append((i, kind, b.text.strip(), False))

    # Discover implicit EXPERIENCE sections: any block starting a job entry outside EXPERIENCE.
    # A job-looking line inside another explicit section (e.g. SKILLS) is treated
    # as a skill bullet ONLY when isolated. A repeated employment pattern
    # (>=2 job starts in the same non-EXPERIENCE section range) is strong
    # evidence of a heading-less experience region (e.g. M Lipsa) and must NOT
    # be suppressed.
    job_starts = [i for i in range(len(ctx.blocks)) if _looks_like_job_start(ctx.blocks, i)]
    job_start_set = set(job_starts)
    for j_idx in job_starts:
        in_explicit_experience = False
        containing_range = None
        for n, (b_idx, k, h, is_imp) in enumerate(bounds):
            nxt = bounds[n + 1][0] if n + 1 < len(bounds) else len(ctx.blocks)
            if b_idx <= j_idx < nxt:
                containing_range = (b_idx, nxt, k)
                if k == "EXPERIENCE":
                    in_explicit_experience = True
                break
        if in_explicit_experience:
            continue
        if containing_range is not None:
            start, end, kind = containing_range
            if kind == "PROJECTS":
                # Roles and date ranges in explicit project sections stay projects.
                continue
            if kind in ("SKILLS", "PROJECTS", "OTHER", "PERSONAL", "SUMMARY"):
                peers = sum(1 for j in job_start_set if start <= j < end)
                # Check if this job start has a date on current or previous line
                blk = ctx.blocks[j_idx]
                has_date_here = any(m['is_range'] for m in D.find_mentions(blk.text))
                has_date_prev = False
                if j_idx > 0:
                    prev_blk = ctx.blocks[j_idx - 1]
                    has_date_prev = any(m['is_range'] for m in D.find_mentions(prev_blk.text))
                if peers < 2 and not (has_date_here or has_date_prev):
                    # Isolated job-looking line inside a non-experience section:
                    # treat as skill bullet / project line, not a new section.
                    continue
        bounds.append((j_idx, "EXPERIENCE", ctx.blocks[j_idx].text.strip(), True))
        bounds.sort(key=lambda x: x[0])

    # Discover implicit EDUCATION sections if not already inside EDUCATION
    edu_starts = [i for i in range(len(ctx.blocks)) if _looks_like_edu_start(ctx.blocks, i)]
    for e_idx in edu_starts:
        sec_kind = None
        for n, (b_idx, k, h, is_imp) in enumerate(bounds):
            nxt = bounds[n + 1][0] if n + 1 < len(bounds) else len(ctx.blocks)
            if b_idx <= e_idx < nxt:
                sec_kind = k
                break
        if sec_kind not in ("EDUCATION", "PROJECTS"):
            bounds.append((e_idx, "EDUCATION", ctx.blocks[e_idx].text.strip(), True))
            bounds.sort(key=lambda x: x[0])

    sections = []
    for n, (idx, kind, header, is_implicit) in enumerate(bounds):
        nxt = bounds[n + 1][0] if n + 1 < len(bounds) else len(ctx.blocks)
        start_idx = idx if is_implicit else idx + 1
        # For implicit EXPERIENCE sections, include preceding date line if present
        if is_implicit and kind == "EXPERIENCE" and start_idx > 0:
            prev_block = ctx.blocks[start_idx - 1]
            if any(m['is_range'] for m in D.find_mentions(prev_block.text)):
                start_idx -= 1
        bids = [b.id for b in ctx.blocks[start_idx:nxt]]
        sec = M.Section(f"s{n}", kind, header, bids, 0.9 if not is_implicit else 0.85,
                        "SECTION_HEADER_MATCH" if not is_implicit else "IMPLICIT_SECTION_DETECTED")
        sec.is_implicit = is_implicit
        sections.append(sec)
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

DESCRIPTION = re.compile(
    r"(?i)^(?:organized|organised|organizing|conducted|conduct|facilitated|authored|collaborated|participated|"
    r"lead (?:triage|calls?|meetings?|multiple|requirements?|workshops)|built|designed|developed|implemented|"
    r"managed|led|worked with|worked on|holding|having|used|using|responsible|acted|leveraged|analyzed|"
    r"configured|deployed|expertise|lead the|delivered|enabled|introduced|automated|provided|maintained|"
    r"utilized|created|creating|supported|supporting|performed|performing|prepared|preparing|assisted|assisting|"
    r"ensured|ensuring|defined|defining|executed|executing|tested|testing|reviewed|reviewing|resolved|resolving|"
    r"integrated|integrating|streamlined|streamlining|spearheaded|spearheading|generated|generating|contributed|"
    r"contributing|focused|focusing|engineered|engineering|programmed|programming|coded|coding|migrated|migrating|"
    r"handled|handling|monitored|monitoring|improved|improving|optimized|optimizing|established|establishing|"
    r"troubleshot|troubleshooting|the |i |we |to |and |with |for )\b"
)


def _header_candidate(line, kind):
    raw = line.strip()
    if not raw or raw.startswith(("#", "-", "=")) or len(raw.split()) > 18:
        return False
    if raw[0].islower():
        return False
    if kind != "EDUCATION" and raw.startswith(BULLET_PREFIXES) and not any(m['is_range'] for m in D.find_mentions(raw)):
        return False
    s = raw.lstrip("•●■▪·○◆◇➢✔►▸✓★-*–— ")
    if not s or _is_header_line(s) or DESCRIPTION.match(s):
        return False
    if re.match(r"(?i)^\s*(client|responsibilities|tools|technologies|environment|role|project role|period|duration|timeline|tenure|title|project title|project name)\b", s):
        return False
    if kind == "EDUCATION":
        return bool(DEGREE_CUE.search(s))
    if kind == "PROJECTS":
        # Generic sub-labels (Details:, Roles & Responsibilities, Approach:, Outcome:)
        # are project content, never new-project headers.
        if re.match(r"(?i)^\s*(?:details|roles?\s*(?:&|and)?\s*responsibilities|approach|outcome|objective)\b", s):
            return False
        return bool(PROJECT_HEAD.match(s) or re.match(r"(?i)^\s*(?:project|poc)(?:[-#]?\s*\d+|[\s:]|$)", s))
    if re.match(r"(?i)^(?:company|organization|organisation|employer)\s*[:\-–—]", s):
        return True
    if re.match(r"(?i)^(?:position|designation|job title)\s*[:\-–—]", s):
        return True
    if re.match(r"(?i)^(?:worked|working|employed)\s+at\s+", s):
        return True
    has_range = any(m['is_range'] for m in D.find_mentions(s))
    title = TITLE_CUE.search(s)
    if title and len(s.split()) <= 18 and len(s[:title.start()].split()) <= 4:
        return True
    # Accept date lines starting with digits (e.g., "08/2024 – Present")
    return bool(has_range and (s[0].isupper() or s[0].isdigit()) and len(s.split()) <= 18)


def _looks_like_entry_start(line, sec_kind="EXPERIENCE"):
    raw = line.strip()
    if not raw or raw[0].islower():
        return False
    if sec_kind != "EDUCATION" and raw.startswith(BULLET_PREFIXES) and not any(m['is_range'] for m in D.find_mentions(raw)):
        return False
    if re.match(r"(?i)^\s*(period|duration|timeline|tenure|client|role|environment|technologies|tools|responsibilities|project role)\b", raw):
        return False
    # Company/Employer/Organization labels are field metadata, not new entries
    if re.match(r"(?i)^\s*(?:company|employer|organization|organisation)\s*[:\-–—]", raw):
        return False
    # Pure date lines (just a date range) are not entry starts
    if any(m['is_range'] for m in D.find_mentions(raw)) and len(raw.split()) <= 6:
        # Check if it's ONLY a date (no title/company keywords)
        if not (TITLE_CUE.search(raw) or COMPANY_HINT.search(raw) or re.search(r"(?i)\b(?:as|at|worked|working|employed|intern)\b", raw)):
            return False
    if sec_kind == "EXPERIENCE" and (PROJECT_HEAD.match(raw) or re.match(r"(?i)^\s*(?:project|poc)(?:[-#]?\s*\d+|[\s:]|$)", raw)):
        return False
    if sec_kind == "PROJECTS":
        if PROJECT_HEAD.match(raw) or re.match(r"(?i)^\s*(?:project|poc)(?:[-#]?\s*\d+|[\s:]|$)", raw):
            return True
    if sec_kind == 'EDUCATION':
        # Institution and graduation-date lines continue the degree entry.
        return bool(_header_candidate(line, sec_kind) and not re.match(r'(?i)^.*\b(?:university|college|institute|school)\b', line)
                    or re.match(r'(?i)^[•●■▪·○◆◇➢✔►▸✓★* -]*(?:bachelor|master|b\.?\s*tech|m\.?\s*tech|diploma|b\.?e\.?)\b', line))
    if any(m['is_range'] for m in D.find_mentions(line)) and len(line.split()) <= 18 and not DESCRIPTION.match(line.lstrip('•●■▪·○◆◇➢✔►▸✓★-*–— ')):
        return True
    return _header_candidate(line, sec_kind)


PROJECT_METADATA = re.compile(
    r"(?i)^(?:client(?:\s+name)?|role|position|designation|project role|"
    r"duration|period|tenure|timeline|title|project title|project name|"
    r"tools|technologies|environment|tech stack)\s*[:\-]"
)
PROJECT_SUBHEADING = re.compile(
    r"(?i)^(?:details|description|roles?\s*(?:&|and)?\s*responsibilities|"
    r"responsibilities|approach|outcome|objective|features|key features|"
    r"key result areas?|highlights|key contributions|project (?:description|overview)|"
    r"(?:\d+[.)]?\s*)?project information)\s*:?$"
)


def _project_title(text):
    """Remove presentation markup, keeping the literal title words."""
    return re.sub(r"^#{1,6}\s+", "", text.strip()).strip("* ")


def _explicit_project_heading(text):
    title = re.sub(r"^\d+[.)]\s*", "", _project_title(text))
    return not PROJECT_SUBHEADING.match(title) and bool(re.match(
        r"(?i)^(?:project|poc)(?:[-#:]?\s*\d+|[\s:]|$)", title))


def _project_bullet(text):
    raw = text.strip()
    if raw.startswith("**") and raw.endswith("**"):
        return False
    return raw.startswith(BULLET_PREFIXES) or bool(re.match(r"^\d+[.)]\s+", raw))


def _project_entry_starts(blocks):
    """Find titled blocks within a project section, independent of field labels.

    Explicit Project/POC identifiers remain supported. For unlabelled titles,
    require supporting bullets or a styled heading followed by prose. This
    works on extracted plain text, where original bold formatting may be lost.
    Body bullets, wrapped prose and metadata never create entries themselves.
    """
    starts = set()
    for index, block in enumerate(blocks):
        title = _project_title(block.text)
        if not title or _is_header_line(title):
            continue
        if _explicit_project_heading(title):
            starts.add(block.id)
            continue
        if (_project_bullet(block.text) or PROJECT_METADATA.match(title)
                or PROJECT_SUBHEADING.match(title) or DESCRIPTION.match(title)
                or len(title.split()) > 18 or title.rstrip("\uf020 ").endswith((".", ";"))
                or not any(c.isalpha() for c in title) or title[0].islower()):
            continue
        # A plain line wrapped from a bullet is still body text. Real PDF bold
        # or Markdown headings provide stronger evidence than capitalization.
        styled = block.bold or block.text.strip().startswith(("**", "#"))
        previous = blocks[index - 1].text.strip() if index else ""
        if (previous and not styled and not previous.endswith((".", ";", ":"))
                and not PROJECT_METADATA.match(previous)
                and not PROJECT_SUBHEADING.match(previous)
                and index + 1 < len(blocks)
                and not PROJECT_METADATA.match(blocks[index + 1].text.strip())):
            continue
        in_description = False
        for following in blocks[index + 1:]:
            text = following.text.strip()
            if PROJECT_METADATA.match(text):
                continue
            if PROJECT_SUBHEADING.match(text):
                in_description = True
                continue
            if _explicit_project_heading(text) or _is_header_line(text):
                break
            if _project_bullet(text):
                # Company headings followed by career-summary bullets group
                # projects; the employer name itself is not a project title.
                body = text.lstrip("•*- ")
                if (D.find_mentions(title) and COMPANY_HINT.search(title)
                        and re.match(r"(?i)^(?:worked|working)\s+(?:as|at)\b", body)):
                    break
                if text.lstrip("•*- ").strip("\uf020 "):
                    starts.add(block.id)
                break
            if (styled and not following.bold
                    and not text.startswith(("**", "#"))
                    and any(c.isalpha() for c in text)):
                # A visually marked heading may introduce prose instead of a
                # list. The paragraph is supporting content, not a field label.
                starts.add(block.id)
                break
            if not in_description:
                break
    return starts


def _segment_section(sec_id, sec_kind, header_text, bids, by_id, entries, warnings, is_implicit_experience=False):
    """Segment one section's blocks into entries preserving all child content."""
    cur_lines, cur_bids, pending, pending_ids = [], [], [], []
    project_starts = (_project_entry_starts([by_id[bid] for bid in bids if bid in by_id])
                      if sec_kind == "PROJECTS" else set())

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
        # For implicit experience sections, don't skip the header block (it's the first job)
        if not line or (not is_implicit_experience and line.strip(":").upper() == header_text.strip(":").upper()):
            continue
        if NAV_PAT.search(line):
            if cur_lines:
                flush()
                cur_lines, cur_bids = [], []
            continue
        if sec_kind == "PROJECTS":
            if bid in project_starts:
                flush()
                cur_lines, cur_bids = [line], [bid]
            elif cur_lines:
                cur_lines.append(line)
                cur_bids.append(bid)
            continue
        if _looks_like_entry_start(line, sec_kind):
            # project / tenure metadata continues current entry
            if re.match(r"(?i)^\s*(period|duration|timeline|tenure)\s*:", line):
                if cur_lines:
                    cur_lines[-1] += " " + line
                    cur_bids.append(bid)
                else:
                    pending.append(line)
                    pending_ids.append(bid)
                continue
            # If current entry has Company: and this line has Position: (or vice-versa),
            # combine into the same entry header
            if cur_lines:
                cl_text = " ".join(cur_lines)
                is_curr_company = bool(re.search(r"(?i)\b(?:company|employer|organization)\s*:", cl_text))
                is_curr_pos = bool(re.search(r"(?i)\b(?:position|designation|job title|role)\s*:", cl_text))
                is_line_company = bool(re.match(r"(?i)^\s*(?:company|employer|organization)\s*:", line))
                is_line_pos = bool(re.match(r"(?i)^\s*(?:position|designation|job title|role)\s*:", line))
                if (is_curr_company and is_line_pos and not is_curr_pos) or (is_curr_pos and is_line_company and not is_curr_company):
                    cur_lines.append(line)
                    cur_bids.append(bid)
                    continue
            # If current entry has content but NO dates yet, and this line
            # provides the date, attach to current entry instead of splitting.
            if cur_lines and any(m["is_range"] for m in D.find_mentions(line)) and not any(D.find_mentions(cl) for cl in cur_lines) and not TITLE_CUE.search(line):
                cur_lines[-1] += " " + line
                cur_bids.append(bid)
                continue
            # If current entry already has a date range, and this line is a new date range
            # WITHOUT a title (pure date line), flush current entry and put date in pending
            if cur_lines and any(m["is_range"] for m in D.find_mentions(line)) and not TITLE_CUE.search(line):
                has_curr_date = any(D.find_mentions(cl) for cl in cur_lines)
                if has_curr_date and not re.match(r"(?i)^\s*(period|duration|timeline|tenure)\s*[:\-]", line):
                    flush()
                    pending.append(line)
                    pending_ids.append(bid)
                    continue
            if cur_lines:
                flush()
            cur_lines = pending + [line]
            cur_bids = pending_ids + [bid]
            pending, pending_ids = [], []
            continue
        if (line.startswith("•") or line.startswith(BULLET_PREFIXES)) and cur_lines:
            cur_lines.append(line)
            cur_bids.append(bid)
            continue
        # Header candidates (date, company, position) that appear after a job
        # description belong to the NEXT job, not the current one.
        is_header_cand = _header_candidate(line, sec_kind)
        if is_header_cand and cur_lines:
            has_curr_date = any(D.find_mentions(cl) for cl in cur_lines)
            if has_curr_date:
                flush()
                pending.append(line)
                pending_ids.append(bid)
                continue
        if cur_lines:
            cur_lines[-1] += " " + line
            cur_bids.append(bid)
            continue
        if is_header_cand:
            pending.append(line)
            pending_ids.append(bid)
    if cur_lines:
        flush()
    elif pending:
        eid = f"e{len(entries)}"
        entries.append(M.Entry(eid, sec_id, " ".join(pending), list(pending_ids), len(entries)))
        warnings.append(f"section {sec_kind}: entry without dated header preserved as-is")


def s04_entry_segmentation(ctx):
    """Input: sections+blocks. Output: entries preserving text + location."""
    if not ctx.sections:
        return _sr("entry_segmentation", status="SKIPPED", confidence=0.0,
                   errors=["no sections"])
    by_id = {b.id: b for b in ctx.blocks}
    entries, warnings = [], []
    for sec in ctx.sections:
        if sec.kind not in ("EXPERIENCE", "EDUCATION", "PROJECTS"):
            continue
        # Check if this is an implicit experience section (header is a job entry)
        is_implicit_experience = (sec.kind == "EXPERIENCE" and
                                   sec.header_text in [b.text.strip() for b in ctx.blocks if b.id in sec.block_ids])
        # Check if this is an implicit section (header is a job/education entry)
        is_implicit = getattr(sec, "is_implicit", False) or (
            sec.kind in ("EXPERIENCE", "EDUCATION") and
            sec.header_text in [b.text.strip() for b in ctx.blocks if b.id in sec.block_ids]
        )
        _segment_section(sec.id, sec.kind, sec.header_text,
                         sec.block_ids, by_id, entries, warnings,
                         is_implicit_experience=is_implicit)
    ctx.entries = entries
    if not entries:
        return _sr("entry_segmentation", status="PARTIAL", confidence=0.3,
                   warnings=["no entries segmented"] + warnings,
                   output={"entries": 0})
    return _sr("entry_segmentation", status="SUCCESS", confidence=0.8,
               warnings=warnings, output={"entries": len(entries)})


# ---------------------------------------------------------------- stage 5

DOB_OR_PERSONAL_RE = re.compile(
    r"\b(date\s+of\s+birth|dob|born|birth\s*date|father(?:'?s)?\s+name|mother(?:'?s)?\s+name|nationality|passport|marital\s+status|declaration)\b",
    re.IGNORECASE,
)


def s05_date_extraction(ctx):
    """Input: entries+blocks. Output: DateMentions (raw preserved, precision kept)."""
    if not ctx.entries and not ctx.blocks:
        return _sr("date_extraction", status="SKIPPED", confidence=0.0,
                   errors=["nothing to scan"])
    mentions, invalid = [], []
    today = ctx.meta.get("today") or date.today()
    personal_bids = set()
    for sec in ctx.sections:
        if sec.kind == "PERSONAL":
            personal_bids.update(sec.block_ids)
    # scan every block so no date is silently dropped; link to entry when possible
    for b in ctx.blocks:
        # Ignore dates appearing on personal/DOB blocks to prevent false 20-30 year gaps
        if b.id in personal_bids or DOB_OR_PERSONAL_RE.search(b.text):
            continue
        for m in D.find_mentions(b.text, today):
            ent = ctx.entry_of_block(b.id)
            mid = f"m{len(mentions)}"
            precision = m["precision"]
            s, e = m["start"], m["end"]
            if precision == "year":
                s, e = (s[0], 1), (e[0], 12)
            mentions.append(M.DateMention(mid, b.id, ent.id if ent else None,
                                          m["raw"], m["char_start"], m["char_end"], precision, s, e,
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
    block_order = {b.id: b.order for b in ctx.blocks}
    for m in ctx.mentions:
        if m.entry_id:
            by_entry.setdefault(m.entry_id, []).append(m)
    assocs, warnings = [], []
    for e in ctx.entries:
        ms = sorted(by_entry.get(e.id, []),
                    key=lambda m: (block_order.get(m.block_id, 0), m.char_start))
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
            if len(ms) == 1:
                r = ("ASSOC_SAME_LINE" if any(ms[0].block_id == b for b in e.block_ids) else "ASSOC_PROXIMITY")
                assocs.append(M.DateAssoc(f"a{len(assocs)}", e.id, ms[0].id, "CONFIRMED", 0.85, r))
            elif len(ms) == 2 and ms[0].start and ms[1].end and ms[0].start <= ms[1].end:
                assocs.append(M.DateAssoc(f"a{len(assocs)}", e.id, ms[0].id, "CONFIRMED", 0.85, "ASSOC_DATE_PAIR"))
                assocs.append(M.DateAssoc(f"a{len(assocs)}", e.id, ms[1].id, "CONFIRMED", 0.85, "ASSOC_DATE_PAIR"))
            elif ms:
                for mention in ms:
                    assocs.append(M.DateAssoc(f"a{len(assocs)}", e.id, mention.id,
                                              "AMBIGUOUS", 0.3, "ASSOC_UNRESOLVED_NO_DATE"))
                warnings.append(f"entry {e.id}: dates found without an explicit range")
            else:
                assocs.append(M.DateAssoc(f"a{len(assocs)}", e.id, None, "UNRESOLVED", 0.3, "ASSOC_UNRESOLVED_NO_DATE"))
    ctx.assocs = assocs
    n_unres = sum(1 for a in assocs if a.status == "UNRESOLVED")
    sec_of_entry = {e.id: next((s.kind for s in ctx.sections if s.id == e.section_id), "") for e in ctx.entries}
    n_unres = sum(1 for a in assocs if a.status == "UNRESOLVED" and sec_of_entry.get(a.entry_id) == "EXPERIENCE")
    status = "PARTIAL" if n_unres else "SUCCESS"
    return _sr("date_association", status=status,
               confidence=0.8 if not n_unres else 0.6,
               warnings=warnings,
               output={"assocs": len(assocs), "unresolved": n_unres})


# ---------------------------------------------------------------- stage 7

def _clean_org(org):
    org = re.sub(r"^[\[\(\-–—\s|•*▪·]+", "", (org or "").strip())
    org = re.sub(r"^[:\[\(\-–—\s|•*▪·]+", "", (org or "").strip())
    org = re.split(r"\s+[—|]\s+|\s+\|\s+", org, maxsplit=1)[0]
    org = re.sub(r"[\]\)\s|.,;:-]+$", "", org.strip())
    org = re.sub(r"\s+", " ", org).strip()
    words = org.split()
    if len(words) > 7:
        return ""
    return org[:120]


def _is_bullet_or_description(text):
    s = (text or "").strip()
    if not s:
        return True
    if s[0] in "•-*▪·–—|" or re.match(r"^(\d+[\.\)]|[a-zA-Z][\.\)])\s+", s):
        return True
    if len(s.split()) > 15:
        return True
    return False


def _org_from_line(line):
    """Company fragment around the company-hint match (brackets stripped)."""
    if _is_bullet_or_description(line or ""):
        return ""
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
    parts = [p.strip(" -–—[]|,\t()") for p in re.split(r"\s+[–—\-]\s+|\s*[|,]\s*", text) if p.strip(" -–—[]|,\t()")]
    if len(parts) >= 2:
        title_idx = next((i for i, p in enumerate(parts) if TITLE_CUE.search(p) and not D.find_mentions(p)), None)
        if title_idx is not None:
            title = parts[title_idx]
            other_parts = [p for i, p in enumerate(parts) if i != title_idx and not D.find_mentions(p)]
            if other_parts:
                org_cand = next((p for p in other_parts if COMPANY_HINT.search(p)), other_parts[0])
                return _strip_leading_caps(title).strip(" -–—[]|(),"), _clean_org(org_cand)
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
                return title.strip(" -–—[]|(),"), org
    # "Developer in Capgemini[, Bangalore]" pattern (no Pvt/Ltd cue)
    m = re.search(r"\bin\s+([A-Z][A-Za-z&]*)(?:\s*,\s*[A-Z][A-Za-z&., ]*)?\s*$",
                  text.strip())
    if m and TITLE_CUE.search(text[:m.start()]):
        return _strip_leading_caps(
            text[:m.start()]).strip(" -–—,|[]▪•()"), _clean_org(m.group(1))
    m = COMPANY_HINT.search(text)
    if m:
        tm = re.match(r"^(.*?(?:Engineer|Developer|Analyst|Manager|Consultant|Architect|"
                      r"Tester|Lead|Administrator|Specialist|Owner|Head|Intern|Associate|"
                      r"Designer|Scientist))\s+(.+)$", text.strip(), re.IGNORECASE)
        if tm:
            return _strip_leading_caps(tm.group(1)).strip(" -–—[]|(),"), _clean_org(tm.group(2))
        idx = text.lower().find(m.group(0).lower())
        return _strip_leading_caps(text[:idx]).strip(" -–—,|[]▪•()"), _clean_org(text[idx:])
    return _strip_leading_caps(text).strip(" -–—[]|,▪•()"), ""


def _header_labels(lines, kind):
    """Only use explicit header fields. Never borrow labels from another entry."""
    clean = []
    for line in lines:
        t = line.lstrip("•▪·-* ")
        for mention in reversed(D.find_mentions(t)):
            t = t[:mention['char_start']] + t[mention['char_end']:]
        # Remove parentheses and their content (often left after date removal)
        t = re.sub(r'\([^)]*\)', '', t)
        t = re.sub(r'\[[^\]]*\]', '', t)
        t = re.sub(r"(?i)\b(?:from|to|till|until|and)\s*$", "", t).strip(" –—-|,()[]/")
        t = re.sub(r"(?i)\b(?:from|to|till|until|and)\s*$", "", t).strip(" –—-|,()[]/:")
        t = re.sub(r"^[:\s–—\-]+", "", t)
        clean.append(t)
    if kind == 'EDUCATION':
        parts = [p.strip() for t in clean for p in re.split(r"[,|]|\s+[–—]\s+", t) if p.strip()]
        parts = [p.strip() for t in clean for p in re.split(r"[,|]|\s+[–—]\s+|\s+from\s+", t) if p.strip()]
        degree = next((p for p in parts if DEGREE_CUE.search(p) and not re.search(r'(?i)university|college|institute|school', p)), '')
        institution = next((p for p in parts if re.search(r'(?i)\b(?:university|college|institute|school|bits|iit|nit|iim|iiit)\b', p)), '')
        return degree, institution
    if kind == 'PROJECTS':
        client = next((re.sub(r'(?i)^client(?:\s*name)?\s*:\s*', '', t).strip() for t in clean if re.match(r'(?i)^client(?:\s*name)?\s*:', t)), '')
        title = next((re.sub(r'(?i)^(?:title|project title|project name)\s*:\s*', '', t).strip() for t in clean if re.match(r'(?i)^(?:title|project title|project name)\s*:', t)), '')
        return title or _project_title(clean[0]), _clean_org(client)
    for t in clean:
        match = re.match(r'(?i)^(?:worked|working|employed)\s+at\s+(.+?)(?:\s+as\s+(?:an?\s+)?(.+))?$', t)
        if match:
            return (match.group(2) or ''), match.group(1).strip()
            return (match.group(2) or ''), _clean_org(match.group(1))
    for t in clean:
        m_as = re.match(r'(?i)^(.+?)\s+as\s+(?:an?\s+)?(.+)$', t)
        if m_as:
            left, right = m_as.group(1).strip(), m_as.group(2).strip()
            if TITLE_CUE.search(right) or COMPANY_HINT.search(left) or not TITLE_CUE.search(left):
                org = left.split(',')[0].strip()
                title = right
                return _strip_leading_caps(title).strip(" -–—[]|(),"), _clean_org(org)
            elif TITLE_CUE.search(left):
                title = left
                org = right.split(',')[0].strip()
                return _strip_leading_caps(title).strip(" -–—[]|(),"), _clean_org(org)
    title, org, explicit_employer = '', '', ''
    for t in clean:
        m_comp = re.match(r'(?i)^(?:company|organization|organisation|employer)\s*[:\-–—]\s*(.+)$', t)
        if m_comp and not org:
            comp_val = m_comp.group(1).strip()
            # Stop at project/technology keywords
            comp_val = re.split(r'(?i)\s+(?:project\s+(?:description|desc|details)|technology|tech\s+stack|tools|skills|responsibilities|duties)\b', comp_val)[0]
            org = _clean_org(comp_val.split(',')[0].strip())
        m_pos = re.match(r'(?i)^(?:position|designation|job title|role)\s*[:\-–—]\s*(.+)$', t)
        if m_pos and not title:
            title = m_pos.group(1).split(',')[0].strip()
    for t in clean:
        if re.match(r'(?i)^client\s*:', t):
            continue
        # A Client label identifies a customer, never the employer.
        employer = re.split(r'(?i)\s*[—|,(]\s*client\s*:', t)[0].strip(' ,—|()')
        parts = [p.strip() for p in re.split(r'[,|]|\s+[–—-]\s+', employer) if p.strip()]
        roles = [p for p in parts if TITLE_CUE.search(p)]
        if len(parts)==2 and parts[0] in roles and parts[1] not in roles and re.search(r'\s[–—-]\s', employer):
            explicit_employer = parts[1]
        if roles and not title:
            # Job followed directly by a company with no separator.
            pair = re.match(r'(?i)^(.*?\b(?:engineer|developer|analyst|manager|consultant|architect|trainee))\s+(.+)$', roles[0])
            if pair and COMPANY_HINT.search(pair.group(2)):
                title, org = pair.group(1), pair.group(2).strip(' .')
            else:
                title = roles[0]
        if not org and roles and parts[0] not in roles and any(m['is_range'] for m in D.find_mentions(lines[clean.index(t)])):
            org = parts[0]
        candidates = [p for p in parts if not TITLE_CUE.search(p) and COMPANY_HINT.search(p) and not re.fullmatch(r'(?i)(?:pvt\.?\s*)?(?:ltd|inc|llc|limited)\.?',p)]
        if candidates and not org:
            org = candidates[0].strip(' .')
        # Adjacent employer/date field under a role, or employer before Client:.
        if not org and title and not roles and parts:
            original = lines[clean.index(t)]
            if ('|' in original and D.find_mentions(original)) or re.search(r'(?i)client\s*:', t):
                org = parts[0]
        if not org:
            pair = re.match(r'(?i)^(.+?)\s+(?:at|in)\s+(.+)$', t)
            if pair and TITLE_CUE.search(pair.group(1)):
                title, org = pair.group(1), pair.group(2).split(',')[0].strip()
    if not org and not title and kind == 'EXPERIENCE':
        for t in clean:
            cand = t.strip(" -–—[]|,▪•():")
            if cand and not DESCRIPTION.match(cand) and len(cand.split()) <= 10 and not re.match(r"(?i)^(?:client|responsibilities|tools|technologies|environment|role|project)\b", cand):
                org = _clean_org(cand)
                break
    return title, _clean_org(org or explicit_employer)


def s07_event_classification(ctx):
    """Classify supported entry headers, retaining uncertainty without guessing dates."""
    if not ctx.entries:
        return _sr("event_classification", status="SKIPPED", confidence=0.0,
                   errors=["no entries"])
    sections, blocks = {s.id: s for s in ctx.sections}, ctx.blocks_by_id()
    mentions = ctx.mentions_by_id()
    events, warnings = [], []
    seen = set()
    for entry in ctx.entries:
        sec = sections[entry.section_id]
        aa = [a for a in ctx.assocs if a.entry_id == entry.id]
        ms = [mentions[a.mention_id] for a in aa if a.mention_id in mentions]
        # Header, adjacent employer/date line; descriptions are never labels.
        header_ids = []
        for header_index, bid in enumerate(entry.block_ids[:4]):
            line = blocks[bid].text
            if re.match(r'(?i)^client\s*:', line):
                break
            if sec.kind == "EXPERIENCE" and (PROJECT_HEAD.match(line) or re.match(r"(?i)^\s*project(?:[-#]?\s*\d+|[\s:]|$)", line)):
                break
            if _header_candidate(line, sec.kind):
                header_ids.append(bid)
            elif header_ids and not DESCRIPTION.match(line.lstrip('•●■▪·○◆◇➢✔►▸✓★-*–— ')) and len(line.split()) <= 18:
                if D.find_mentions(line) or (line[0].isupper() and
                        (COMPANY_HINT.search(line) or re.search(r'(?i)client\s*:', line))):
                    header_ids.append(bid)
                elif (header_index + 1 < min(4, len(entry.block_ids))
                      and any(m['is_range'] for m in D.find_mentions(blocks[entry.block_ids[header_index+1]].text))
                      and not TITLE_CUE.search(line) and not line.lstrip().startswith(BULLET_PREFIXES)):
                    # A short domain/location subtitle may separate a role from
                    # its own date line; it is not a title or employer field.
                    continue
                else:
                    break
            else:
                break
        if sec.kind == "PROJECTS":
            header_ids = [entry.block_ids[0]] + [
                bid for bid in entry.block_ids[1:]
                if PROJECT_METADATA.match(blocks[bid].text.strip())]
        if not header_ids:
            continue
        lines = [blocks[bid].text for bid in header_ids]
        title, org = _header_labels(lines, sec.kind)
        # Fallback: if no org found in header lines, search entry text for company patterns
        if sec.kind == "EXPERIENCE" and not org:
            entry_text = entry.text
            # Look for "Company - X" or "Company: X" patterns
            m_comp = re.search(r'(?i)(?:company|employer|organization)\s*[:\-–—]\s*([^.\n]+?)(?:\s+(?:project|technology|tech|tools|skills|responsibilities|duties|description|client)\b|$)', entry_text)
            if m_comp:
                org = _clean_org(m_comp.group(1).strip())
            # Look for "at X" or "in X" after title-like words
            if not org:
                m_at = re.search(r'(?i)\b(?:at|in)\s+([A-Z][A-Za-z0-9&.\-\']*(?:\s+[A-Z][A-Za-z0-9&.\-\']*)*)\b', entry_text)
                if m_at and COMPANY_HINT.search(m_at.group(1)):
                    org = _clean_org(m_at.group(1))
        if not title and not org:
            continue
        etype = {'EXPERIENCE': 'EMPLOYMENT', 'EDUCATION': 'EDUCATION', 'PROJECTS': 'PROJECT'}.get(sec.kind, 'OTHER')
        if etype in ('EMPLOYMENT', 'INTERNSHIP') and not org and not any(m.is_range for m in ms if m.block_id in header_ids):
            if len(title.split()) > 5 or re.match(r'(?i)^\s*role\b', title) or DESCRIPTION.match(title.lstrip('•●■▪·○◆◇➢✔►▸✓★-*–— ')):
                continue
        if etype == 'EMPLOYMENT' and any(INTERNSHIP_RE.search(t) for t in lines):
            etype = 'INTERNSHIP'
        header_mentions = [m for m in ms if m.block_id in header_ids]
        # Deduplicate explicit mentions by mention_id to handle duplicate associations
        seen_mention_ids = set()
        explicit = []
        for m in header_mentions:
            if m.is_range and m.id not in seen_mention_ids:
                explicit.append(m)
                seen_mention_ids.add(m.id)
        
        # For EDUCATION, also accept single dates (graduation dates) as valid
        if etype == 'EDUCATION' and not explicit:
            for m in header_mentions:
                if not m.is_range and m.id not in seen_mention_ids:
                    explicit.append(m)
                    seen_mention_ids.add(m.id)
        
        status, span, precision = 'UNRESOLVED', None, 'month'
        if len(explicit) == 1:
            m = explicit[0]
            if m.is_range:
                span, precision, status = (m.start, m.end), m.precision, 'CONFIRMED'
            elif etype == 'EDUCATION':
                # For education, single date = graduation date (use as end, start = None)
                span, precision, status = (None, m.end), m.precision, 'CONFIRMED'
            else:
                status = 'AMBIGUOUS'
                warnings.append(f'{entry.id}: single date without range')
        elif len(explicit) > 1:
            # Multiple dates - check if they form a range
            ranges = [m for m in explicit if m.is_range]
            if len(ranges) == 1:
                m = ranges[0]
                span, precision, status = (m.start, m.end), m.precision, 'CONFIRMED'
            elif etype == 'EDUCATION' and len(explicit) >= 1:
                # Multiple single dates for education - use earliest as start, latest as end
                dates = sorted([m.end for m in explicit])
                span, precision, status = (dates[0], dates[-1]), explicit[0].precision, 'CONFIRMED'
            else:
                status = 'AMBIGUOUS'
                warnings.append(f'{entry.id}: dates cannot be assigned unambiguously')
        elif header_mentions:
            # Separate date points or completion dates do not establish a tenure.
            status = 'AMBIGUOUS'
            warnings.append(f'{entry.id}: dates cannot be assigned unambiguously')
        reason = 'EVENT_' + ('EMPLOYMENT' if etype == 'EMPLOYMENT' else etype) + '_CUES'
        reasons = [reason]
        if not [m for m in ms if m.block_id in header_ids and m.is_range] and explicit:
            reasons.append('ASSOC_PROJECT_DATES')
        event = M.Event(f'v{len(events)}', entry.id, [a.id for a in aa if a.mention_id in {m.id for m in header_mentions}], etype, title, org,
                        span[0] if span else None, span[1] if span else None,
                        precision, status, EV.event_confidence(status, precision, sec.confidence), reasons)
        event.header_block_ids = header_ids
        event.section = sec.header_text
        if span and len(explicit) > 1 and not [m for m in ms if m.block_id in header_ids and m.is_range]:
            event.date_label = f"{span[0][0]}-{span[0][1]:02d} to {span[1][0]}-{span[1][1]:02d}"
        else:
            event.date_label = ' / '.join(dict.fromkeys(m.raw for m in header_mentions))
        event.is_present = any(m.is_present for m in explicit)
        event.source = SRC.event_source(ctx, event)
        if any(loc.get('method') == 'ocr' for loc in event.source.get('entry', [])):
            event.status = 'AMBIGUOUS'
            event.confidence = min(event.confidence, 0.5)
            event.reasons.append('OCR_REQUIRES_REVIEW')
        # A field without a source span is not a supported field.
        if title and not event.source.get('title'):
            event.title = ''
        if org and not event.source.get('company'):
            event.org = ''
        if not event.title and not event.org:
            continue
        key = (etype, event.title, event.org, event.start, event.end)
        if key in seen:
            continue
        seen.add(key)
        event.id = 'v' + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]
        if not span:
            ctx.unresolved.append(entry.id)
        events.append(event)
    _include_project_periods(ctx, events)
    # Deduplicate repeated facts without discarding overlapping activities.
    events = _deduplicate_events(events)
    ctx.events = events
    return _sr('event_classification', confidence=0.8, warnings=warnings,
               output={'events': len(events), 'unresolved': len(ctx.unresolved)})


# ---------------------------------------------------------------- stage 8

def _deduplicate_events(events):
    """Collapse repeated facts, never distinct roles or merely overlapping dates.

    Empty organizations are not an identity. Type, title, and the complete
    date range must agree; promotions and internships can share a boundary month.
    Also merge events with same title/org where one has dates and one doesn't.
    """
    # First pass: group by (type, title, org) and keep the one with dates
    by_title_org = {}
    for event in events:
        key = (event.type, event.title.strip().casefold(), event.org.strip().casefold())
        if key not in by_title_org:
            by_title_org[key] = []
        by_title_org[key].append(event)
    
    merged = []
    for key, group in by_title_org.items():
        if len(group) == 1:
            merged.append(group[0])
        else:
            # Multiple events with same title/org - prefer one with dates
            with_dates = [e for e in group if e.start and e.end]
            without_dates = [e for e in group if not (e.start and e.end)]
            if with_dates:
                # Keep the one with dates (prefer CONFIRMED over AMBIGUOUS)
                best = max(with_dates, key=lambda e: (e.status == 'CONFIRMED', e.confidence))
                merged.append(best)
            else:
                # All without dates - keep the best one
                best = max(group, key=lambda e: e.confidence)
                merged.append(best)
    
    # Second pass: exact deduplication on full key
    kept, seen = [], set()
    for event in merged:
        key = (event.type, event.title.strip().casefold(),
               event.org.strip().casefold(), event.start, event.end,
               event.precision, event.status)
        if key not in seen:
            kept.append(event)
            seen.add(key)
    return kept


def _strip_project_prefix(name):
    """Strip leading 'Project N:' / 'POC N:' numbering prefixes from project names.

    'Project: 1: Microsoft' -> 'Microsoft'; 'Project 2 - KELLOGS' -> 'KELLOGS'.
    Bare identifiers like 'POC: 1' (no title/client after stripping) are kept
    as-is so the item remains identifiable.
    """
    if not name:
        return name
    stripped = re.sub(r'^\s*(?:project|poc)\s*[-#:]*\s*\d+\s*[:\-–.]?\s*', '', name, flags=re.IGNORECASE).strip()
    return stripped or name


def _find_parent_employment(p_start, p_end, employment_events):
    """Return the employment event with max month-overlap to the project range."""
    best, best_overlap = None, 0
    for e in employment_events:
        if not e.start or not e.end:
            continue
        lo = max(D.month_index(p_start), D.month_index(e.start))
        hi = min(D.month_index(p_end), D.month_index(e.end))
        overlap = max(0, hi - lo + 1)
        if overlap > best_overlap:
            best, best_overlap = e, overlap
    return best


def _detect_date_conflicts(ctx, events):
    """Flag dated PROJECT events extending outside their parent employer tenure.

    Attaches DATE_CONFLICT reason, lowers event confidence, and records
    machine-readable conflict evidence on the event.
    """
    employments = [e for e in events if e.type in ('EMPLOYMENT', 'INTERNSHIP')
                   and e.start and e.end and e.status == 'CONFIRMED']
    for e in events:
        if e.type != 'PROJECT' or not e.start or not e.end or e.status != 'CONFIRMED':
            continue
        parent = _find_parent_employment(e.start, e.end, employments)
        if parent is None:
            continue
        extends_before = D.month_index(e.start) < D.month_index(parent.start)
        extends_after = D.month_index(e.end) > D.month_index(parent.end)
        if extends_before or extends_after:
            if 'DATE_CONFLICT' not in e.reasons:
                e.reasons.append('DATE_CONFLICT')
            e.confidence = round(e.confidence * 0.7, 3)
            e.conflict = {
                'parent_event_id': parent.id,
                'parent_org': parent.org,
                'parent_title': parent.title,
                'employment_start': list(parent.start),
                'employment_end': list(parent.end),
                'project_start': list(e.start),
                'project_end': list(e.end),
                'extends_before_employment': extends_before,
                'extends_after_employment': extends_after,
            }


def _include_project_periods(ctx, events):
    """Bring explicitly dated project blocks into coverage before reconciliation."""
    for project in extract_project_blocks(ctx):
        locs = project.get('source', {}).get('entry', [])
        bids = {loc.get('block_id') for loc in locs}
        # Dedicated project sections already classified by stage 7 retain their IDs —
        # but only if that event is actually dated. UNRESOLVED stubs (title only,
        # no dates) must NOT block the dated project period from being added.
        if any(e.type == 'PROJECT' and e.start and e.end
               and bids.intersection(getattr(e, 'header_block_ids', [])) for e in events):
            continue
        ranges = [m for m in D.find_mentions(project.get('duration', '')) if m['is_range']]
        if len(ranges) != 1:
            continue  # "6 months" alone cannot be placed on a calendar.
        m = ranges[0]
        entry = next((e for e in ctx.entries if bids.intersection(e.block_ids)), None)
        if not entry or not locs:
            continue
        status = 'AMBIGUOUS' if any(loc.get('method') == 'ocr' for loc in locs) else 'CONFIRMED'
        mentions = [mention for mention in ctx.mentions if mention.block_id in bids and mention.raw == m['raw']]
        date_locs = [loc for mention in mentions for loc in SRC.locations(ctx.blocks_by_id()[mention.block_id], mention.char_start, mention.char_end)]
        if not date_locs:
            continue
        event = M.Event('project_' + project['id'], entry.id,
                        [a.id for a in ctx.assocs if a.mention_id in {mention.id for mention in mentions}],
                        'PROJECT', project.get('role') or _strip_project_prefix(project['name']), project.get('client', ''), m['start'], m['end'],
                        m['precision'], status, 0.5 if status == 'AMBIGUOUS' else 0.85, ['EVENT_PROJECT_CUES'])
        event.date_label, event.section, event.is_present = m['raw'], 'PROJECTS', m['is_present']
        event.header_block_ids = list(bids)
        company_locs = []
        for bid in bids:
            block = ctx.blocks_by_id().get(bid)
            span = SRC.entity_span(block.text, project.get('client', '')) if block else None
            if span:
                company_locs.extend(SRC.locations(block, *span))
        event.project_source = {**project['source'], 'dates': date_locs, 'title': locs,
                                'company': company_locs, 'section': 'PROJECTS', 'date_label': m['raw'], 'is_present': m['is_present']}
        event.source = event.project_source
        events.append(event)
    # Drop UNRESOLVED stub PROJECT events whose blocks are covered by a dated
    # (CONFIRMED) project period event. Stubs carry title only and would
    # otherwise duplicate the dated entries in the DTO.
    dated_bids = set()
    for e in events:
        if e.type == 'PROJECT' and e.start and e.end and e.status == 'CONFIRMED':
            dated_bids.update(getattr(e, 'header_block_ids', []))
    if dated_bids:
        events[:] = [e for e in events
                     if not (e.type == 'PROJECT' and not (e.start and e.end)
                             and set(getattr(e, 'header_block_ids', [])).issubset(dated_bids))]
    _detect_date_conflicts(ctx, events)


def s08_timeline_reconciliation(ctx):
    """Input: events. Output: chronological timeline; overlaps kept, never errors."""
    dated = [e for e in ctx.events if e.start and e.end and e.status == "CONFIRMED"]
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
    dated = [e for e in ctx.events if e.start and e.end and e.status == "CONFIRMED"]
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
    core = [e for e in ctx.events if e.type in ('EMPLOYMENT', 'INTERNSHIP', 'EDUCATION', 'PROJECT')]
    uncertain = [e for e in core if (e.status != 'CONFIRMED' and e.type in ('EMPLOYMENT', 'INTERNSHIP'))
                 or (e.type == 'PROJECT' and e.status == 'AMBIGUOUS')]
    coarse = any(e.precision != 'month' for e in core)
    dated = [e for e in core if e.start and e.end and e.status == 'CONFIRMED']
    work_intervals = [(e.start, e.end) for e in dated if e.type in ('EMPLOYMENT', 'INTERNSHIP')]
    # Projects fully inside an employment tenure are considered, but do not
    # change its coverage. A project/education interval filling a hole does.
    employment_only = bool(work_intervals) and I.union(work_intervals) == I.union([(e.start, e.end) for e in dated])
    unplaced = [e.id for e in core if not (e.start and e.end) or e.status != 'CONFIRMED']
    dated.sort(key=lambda e: D.month_index(e.start))
    # Alternate interpretation: employment/education tenures only, ignoring
    # dated project/client work. Reported alongside the primary gap so a
    # project that extends past its parent employer (DATE_CONFLICT) can be
    # judged both ways instead of silently picking one.
    emp_dated = sorted(
        [e for e in dated if e.type in ('EMPLOYMENT', 'INTERNSHIP', 'EDUCATION')],
        key=lambda e: D.month_index(e.start))

    def _ranges(evts):
        out, cur_end, cur_ev = [], None, None
        for b in evts:
            if cur_end is None:
                cur_end, cur_ev = b.end, b
                continue
            gm = max(0, D.months_between(cur_end, b.start) - 1)
            if gm > 0 and cur_ev.precision == "month" and b.precision == "month":
                out.append({
                    "months": gm,
                    "start": list(D.add_months(cur_end, 1)),
                    "end": list(D.add_months(b.start, -1)),
                    "event_before": cur_ev.id,
                    "event_after": b.id,
                })
            if D.month_index(b.end) > D.month_index(cur_end):
                cur_end, cur_ev = b.end, b
        return out

    employment_only_gaps = _ranges(emp_dated)
    ctx.meta["employment_only_gaps"] = employment_only_gaps
    gaps = []
    if len(dated) < 2 or uncertain or ctx.meta.get("reading_incomplete"):
        g = M.Gap("g0", None, None, 0, "INSUFFICIENT_EVIDENCE", 0.4,
                  ["INSUFFICIENT_DATES"],
                  {"note": "insufficient reliable date coverage; no gap inference possible",
                   "uncertain_event_ids": [e.id for e in uncertain]})
        gaps = [g]
    else:
        # Primary gap = no dated activity clearly represented (original rule:
        # dated project/education intervals count as activity). The
        # employment-only reading is reported as an alternate, and only when
        # it actually differs from the primary.
        max_end = dated[0].end
        last_event = dated[0]
        for b in dated[1:]:
            gm = max(0, D.months_between(max_end, b.start) - 1)
            if gm > 0 and last_event.precision == "month" and b.precision == "month":
                gap_start = D.add_months(max_end, 1)
                gap_end = D.add_months(b.start, -1)
                alternates = []
                for r in employment_only_gaps:
                    if ((r["months"], r["start"], r["end"])
                            == (gm, list(gap_start), list(gap_end))):
                        continue  # identical reading: not listed twice
                    emp_end = D.add_months(r["start"], -1)
                    r = dict(r)
                    r["note"] = (
                        "employment-only reading (dated client/project work "
                        "excluded); applies if employer end date "
                        f"{calendar.month_name[emp_end[1]]} {emp_end[0]} is correct"
                    )
                    alternates.append(r)
                evidence = {"event_before": last_event.id, "event_after": b.id,
                            "coverage_scope": "employment" if employment_only else "all_dated_activity",
                            "unplaced_activity_ids": unplaced}
                if alternates:
                    evidence["interpretations"] = {"employment_only": alternates}
                g = M.Gap("g" + hashlib.sha256(f"{last_event.id}:{b.id}:{gap_start}:{gap_end}".encode()).hexdigest()[:16], list(gap_start), list(gap_end), gm, "POTENTIAL_GAP",
                          0.0, ["GAP_NO_COVERAGE"],  # confidence filled in stage 11
                          evidence)
                gaps.append(g)
            if D.month_index(b.end) > D.month_index(max_end):
                max_end = b.end
                last_event = b
        if not gaps:
            g = M.Gap("g0", None, None, 0, "INSUFFICIENT_EVIDENCE" if coarse else "NO_GAP_DETECTED", 0.4 if coarse else 0.9, [],
                      {"note": "year-only dates need verification" if coarse else "no uncovered months between supported entries"})
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
    for event in ctx.events:
        event.source = SRC.event_source(ctx, event)
    SRC.attach_native_fragments(ctx)
    by_ev, by_en = ctx.events_by_id(), ctx.entries_by_id()
    by_a, by_m, by_b = ctx.assocs_by_id(), ctx.mentions_by_id(), ctx.blocks_by_id()
    for g in ctx.gaps:
        if g.state != "POTENTIAL_GAP":
            continue
        cb = by_ev.get(g.evidence.get("event_before"))
        ca = by_ev.get(g.evidence.get("event_after"))
        g.confidence = EV.gap_confidence(cb.confidence if cb else None,
                                         ca.confidence if ca else None, True)
        # A gap bounded by a DATE_CONFLICT project is less certain: the
        # project may or may not count as continuous activity.
        if any("DATE_CONFLICT" in (getattr(ev, "reasons", []) or [])
               for ev in (cb, ca) if ev is not None):
            g.confidence = round(g.confidence * 0.85, 3)
            if "DATE_CONFLICT" not in g.reasons:
                g.reasons.append("DATE_CONFLICT")
        ctx.lineage[g.id] = EV.lineage(g, by_ev, by_en, by_a, by_m, by_b, ctx.doc_id)
    return _sr("confidence_evidence", status="SUCCESS", confidence=0.9,
               output={"gaps_scored": sum(1 for g in ctx.gaps if g.state == "POTENTIAL_GAP"),
                       "lineage_built": len(ctx.lineage)})


# ---------------------------------------------------------------- stage 12

def _attach_project_native_fragments(ctx, projects):
    if not getattr(ctx, 'raw_bytes', b'').startswith(b'%PDF-'):
        return
    try:
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(ctx.raw_bytes) as pdf:
            pages, texts = [], []
            for i in range(len(pdf)):
                page = pdf[i]
                page.set_cropbox(*page.get_mediabox())
                textpage = page.get_textpage()
                pages.append((page, textpage))
                texts.append(' '.join(textpage.get_text_range().split()))
            all_text = '\n'.join(texts)
            for proj in projects:
                for loc in proj.get('source', {}).get('entry', []):
                    if loc.get('kind') != 'pdf' or loc.get('page', 0) > len(pages):
                        continue
                    page, textpage = pages[loc['page'] - 1]
                    x0, top, x1, bottom = loc['bbox']
                    native = ' '.join(textpage.get_text_bounded(
                        left=x0, bottom=page.get_height()-bottom,
                        right=x1, top=page.get_height()-top).split())
                    if native and all_text.count(native) == 1:
                        loc['fragment_text'] = native
            for page, textpage in pages:
                textpage.close()
                page.close()
    except Exception:
        pass


def extract_project_blocks(ctx):
    blocks_by_id = ctx.blocks_by_id()
    projects = []
    proj_idx = 0

    for sec in ctx.sections:
        entries = [e for e in ctx.entries if e.section_id == sec.id]
        if sec.kind == 'PROJECTS':
            for ent in entries:
                lines = [blocks_by_id[b].text for b in ent.block_ids if b in blocks_by_id]
                full_text = '\n'.join(lines)

                client = next((re.sub(r'(?i)^client(?:\s*name)?\s*:\s*', '', t).strip() for t in lines if re.match(r'(?i)^client(?:\s*name)?\s*:', t)), '')
                role = next((re.sub(r'(?i)^(?:role|position|designation|project role)\s*:\s*', '', t).strip() for t in lines if re.match(r'(?i)^(?:role|position|designation|project role)\s*:', t)), '')
                dur = next((re.sub(r'(?i)^(?:duration|period|tenure)\s*[:\-]\s*', '', t).strip() for t in lines if re.match(r'(?i)^(?:duration|period|tenure)\s*[:\-]', t)), '')
                title = next((re.sub(r'(?i)^(?:title|project title|project name)\s*[:\-]\s*', '', t).strip() for t in lines if re.match(r'(?i)^(?:title|project title|project name)\s*:', t)), '')
                head = re.sub(r'^\d+[.)]\s*', '', _project_title(lines[0])) if lines else ''
                if not _explicit_project_heading(head):
                    head = ''

                name = title or (f'{head}: {client}' if head and client else (head or client or (_project_title(lines[0]) if lines else 'Project')))
                name = _strip_project_prefix(name)
                details = [line.strip() for line in lines if line.strip() and not re.match(r'(?i)^(?:client|role|duration|period|tenure|title|project|poc)\b', line.strip())]

                locs = []
                for bid in ent.block_ids:
                    if bid in blocks_by_id:
                        locs.extend(SRC.locations(blocks_by_id[bid]))

                proj_idx += 1
                projects.append({
                    'id': f'proj_{proj_idx}',
                    'name': name,
                    'client': client,
                    'role': role,
                    'duration': dur,
                    'details': details[:8],
                    'raw_text': full_text[:600],
                    'source': {'entry': locs}
                })
        else:
            # Look for nested projects inside EXPERIENCE or OTHER entries
            for ent in entries:
                cur_proj = None
                cur_bids = []
                for bid in ent.block_ids:
                    if bid not in blocks_by_id:
                        continue
                    b = blocks_by_id[bid]
                    raw = b.text.strip()
                    m_head = re.match(r'^(?:[•●■▪·○◆◇➢✔►▸✓★* -]*)\s*(?:project|poc)[-#:\s]+(\d+|[a-zA-Z0-9_-]+)(.*)$', raw, re.IGNORECASE)
                    if m_head:
                        if cur_proj:
                            locs = []
                            for cbid in cur_bids:
                                locs.extend(SRC.locations(blocks_by_id[cbid]))
                            cur_proj['source'] = {'entry': locs}
                            projects.append(cur_proj)
                        proj_idx += 1
                        after = m_head.group(2).strip(' :–-')
                        cur_proj = {
                            'id': f'proj_{proj_idx}',
                            'name': after or f'Project {m_head.group(1)}',
                            'client': '',
                            'role': '',
                            'duration': '',
                            'details': [],
                            'raw_text': raw,
                            'source': {}
                        }
                        cur_bids = [bid]
                        continue
                    if cur_proj:
                        m_dur = re.match(r'^(?:duration|period|tenure)\s*[:\-]\s*(.+)$', raw, re.IGNORECASE)
                        m_client = re.match(r'^(?:client(?:\s*name)?)\s*[:\-]\s*(.+)$', raw, re.IGNORECASE)
                        m_role = re.match(r'^(?:role|position|designation|project role)\s*[:\-]\s*(.+)$', raw, re.IGNORECASE)
                        m_title = re.match(r'^(?:title|project title|project name)\s*[:\-]\s*(.+)$', raw, re.IGNORECASE)
                        if m_dur and not cur_proj['duration']:
                            cur_proj['duration'] = m_dur.group(1).strip()
                        elif m_client and not cur_proj['client']:
                            cur_proj['client'] = m_client.group(1).strip()
                        elif m_role and not cur_proj['role']:
                            cur_proj['role'] = m_role.group(1).strip()
                        elif m_title and not cur_proj['name']:
                            cur_proj['name'] = m_title.group(1).strip()
                        else:
                            if not raw.startswith(('Roles & Responsibilities', 'Details:')):
                                cur_proj['details'].append(raw)
                        cur_bids.append(bid)
                if cur_proj:
                    locs = []
                    for cbid in cur_bids:
                        locs.extend(SRC.locations(blocks_by_id[cbid]))
                    cur_proj['source'] = {'entry': locs}
                    projects.append(cur_proj)

    _attach_project_native_fragments(ctx, projects)
    return projects


def s12_recruiter_output(ctx):
    """Input: everything. Output: extension-facing DTO (timeline, gaps, evidence)."""
    # Include events with at least an end date (for education graduation dates)
    dated = sorted((e for e in ctx.events if e.end), key=lambda e: D.month_index(e.end if e.end else e.start))
    blocks_by_id = ctx.blocks_by_id()
    entries_by_id = ctx.entries_by_id()
    dto_events = []
    for e in dated:
        ent = entries_by_id.get(e.entry_id)
        raw_lines = [blocks_by_id[b].text for b in ent.block_ids if b in blocks_by_id] if ent else []
        anchored = [loc["text"] for loc in getattr(e, "source", {}).get("entry", [])]
        quote = "\n".join(anchored or raw_lines[:3]) if raw_lines else (ent.text[:300] if ent else "")
        dto_events.append({
            "id": e.id, "type": e.type, "title": e.title, "org": e.org,
            "start": f"{e.start[0]:04d}-{e.start[1]:02d}" if e.start else None,
            "end": f"{e.end[0]:04d}-{e.end[1]:02d}" if e.end else None,
            "precision": e.precision, "status": e.status,
            "confidence": e.confidence, "reasons": e.reasons,
            "quote": quote[:300], "source": getattr(e, "source", {}),
            "date_label": e.date_label, "section": e.section, "is_present": e.is_present,
        })
    dto_gaps = []
    for g in ctx.gaps:
        d = g.to_dict()
        if g.start and g.end:
            d["start_label"] = f"{g.start[0]:04d}-{g.start[1]:02d}"
            d["end_label"] = f"{g.end[0]:04d}-{g.end[1]:02d}"
        # attach short evidence quotes for the browser UI
        chain = ctx.lineage.get(g.id, {})
        quotes = []
        details = []
        for link in chain.get("links", []):
            q = link.get("entry_quote", "")
            ev_info = link.get("event", {})
            hdr = f"{ev_info.get('title', '')} at {ev_info.get('org', '')}".strip(" at ")
            if q:
                quotes.append(q[:300])
                details.append({"header": hdr, "quote": q[:300], "event_id": ev_info.get("id"), "source": ev_info.get("source", {})})
        d["evidence_quotes"] = quotes
        d["evidence_details"] = details
        dto_gaps.append(d)
    overall = _overall_status(ctx)
    dto_unresolved = [
        {"id": e.id, "type": e.type, "title": e.title, "org": e.org,
         "entry_text": by_en_text(ctx, e.entry_id), "source": getattr(e, "source", {}),
         "date_label": e.date_label, "section": e.section, "status": e.status}
        for e in ctx.events if not (e.start and e.end)]
    total_ev = len(dto_events) + len(dto_unresolved)
    confs = [e["confidence"] for e in dto_events if e.get("confidence") is not None]
    ambiguous_count = sum(1 for e in dto_events if e.get("status") == "AMBIGUOUS")
    unresolved_work = sum(1 for u in dto_unresolved if u.get("type") in ("EMPLOYMENT", "WORK"))
    base_conf = (sum(confs) / len(confs)) if confs else 0.90
    amb_pen = ((ambiguous_count / total_ev) * 0.08) if total_ev else 0.0
    unres_pen = ((unresolved_work / total_ev) * 0.10) if total_ev else 0.0
    quality = {
        "dated_events": len(dto_events),
        "total_events": total_ev,
        "dated_share": round(len(dto_events) / total_ev, 3) if total_ev else 0.0,
        "unresolved": len(dto_unresolved),
        "ambiguous": ambiguous_count,
        "mean_event_confidence": round(sum(confs) / len(confs), 3) if confs else None,
        "document_accuracy": round(max(0.70, min(0.96, base_conf - amb_pen - unres_pen)), 2) if total_ev else 0.88,
    }
    projects = extract_project_blocks(ctx)
    # Deduplicate projects by name+client
    seen_proj = set()
    unique_projects = []
    for p in projects:
        key = (p['name'].strip().lower(), p['client'].strip().lower())
        if key not in seen_proj and p['name'].strip():
            seen_proj.add(key)
            unique_projects.append(p)
    projects = unique_projects
    dto = {
        "doc_id": ctx.doc_id,
        "filename": ctx.filename,
        "candidate_name": _guess_candidate_name(ctx),
        "status": overall,
        "timeline": dto_events,
        "unresolved_events": dto_unresolved,
        "projects": projects,
        "gaps": dto_gaps,
        "quality": quality,
        "total_represented_months": ctx.total_months,
        "stages": {k: {"status": v.status, "confidence": v.confidence}
                   for k, v in ctx.stage_results.items()},
        "model_versions": dict(ctx.model_versions),
        "disclaimer": ("Potential gaps mark periods with no clearly represented "
                       "activity in the resume. They are not evidence of unemployment. "
                       "The recruiter makes the final decision."),
    }
    from ..periods import analyze_timeline
    dto["period_analysis"] = analyze_timeline(dto_events, dto_unresolved, projects)
    ctx.recruiter_output = dto
    return _sr("recruiter_output", status="SUCCESS", confidence=0.95,
               output={"events": len(dto_events), "gaps": len(dto_gaps), "projects": len(projects)})


# ---------------------------------------------------------------- stage 13: verification

def _verify_event_against_source(event, raw_text, blocks_by_id):
    """Verify an event's fields appear in source text. Returns verification dict."""
    text_lower = raw_text.lower()
    verified = {
        "title_verified": False,
        "org_verified": False,
        "start_verified": False,
        "end_verified": False,
        "source_spans": {}
    }
    
    # Helper to generate month name variants
    MONTH_NAMES = {
        1: ["january", "jan"],
        2: ["february", "feb"],
        3: ["march", "mar"],
        4: ["april", "apr"],
        5: ["may"],
        6: ["june", "jun"],
        7: ["july", "jul"],
        8: ["august", "aug"],
        9: ["september", "sep", "sept"],
        10: ["october", "oct"],
        11: ["november", "nov"],
        12: ["december", "dec"],
    }

    def _date_variants(year, month):
        """Return list of string variants for a (year, month) that may appear in text."""
        variants = []
        # numeric
        variants.append(f"{month}/{year}")
        variants.append(f"{year}-{month:02d}")
        variants.append(f"{month}-{year}")
        # month name
        for name in MONTH_NAMES.get(month, []):
            variants.append(f"{name} {year}")
            variants.append(f"{name}. {year}")
            variants.append(f"{name}-{year}")
        return variants

    # Verify title
    if event.title:
        title_lower = event.title.lower()
        if title_lower in text_lower:
            verified["title_verified"] = True
            idx = text_lower.find(title_lower)
            verified["source_spans"]["title"] = {"pos": idx, "text": event.title}
    
    # Verify org
    if event.org:
        org_lower = event.org.lower()
        if org_lower in text_lower:
            verified["org_verified"] = True
            idx = text_lower.find(org_lower)
            verified["source_spans"]["org"] = {"pos": idx, "text": event.org}
    
    # Verify dates - check if date strings appear
    if event.start:
        y, m = event.start
        found = False
        for fmt in _date_variants(y, m):
            if fmt.lower() in text_lower:
                verified["start_verified"] = True
                verified["source_spans"]["start"] = {"pos": text_lower.find(fmt.lower()), "text": fmt}
                found = True
                break
        # fallback: year only
        if not found:
            year_str = str(y)
            if year_str in raw_text:
                verified["start_verified"] = True
                verified["source_spans"]["start"] = {"pos": raw_text.find(year_str), "text": year_str}
    
    if event.end and not event.is_present:
        y, m = event.end
        found = False
        for fmt in _date_variants(y, m):
            if fmt.lower() in text_lower:
                verified["end_verified"] = True
                verified["source_spans"]["end"] = {"pos": text_lower.find(fmt.lower()), "text": fmt}
                found = True
                break
        if not found:
            year_str = str(y)
            if year_str in raw_text:
                verified["end_verified"] = True
                verified["source_spans"]["end"] = {"pos": raw_text.find(year_str), "text": year_str}
    elif event.is_present:
        for word in ["present", "till date", "current", "ongoing"]:
            if word in text_lower:
                verified["end_verified"] = True
                verified["source_spans"]["end"] = {"pos": text_lower.find(word), "text": word}
                break
    
    return verified


def _compute_verified_gaps(verified_events):
    """Compute gaps from ONLY verified EMPLOYMENT events (both dates verified)."""
    dated = [e for e in verified_events 
             if e["verified"]["start_verified"] and e["verified"]["end_verified"]
             and e["event"].type == "EMPLOYMENT"]
    dated.sort(key=lambda e: (e["event"].end[0] * 12 + e["event"].end[1]) if e["event"].end else 0)
    
    gaps = []
    for i in range(len(dated) - 1):
        curr_end = dated[i]["event"].end
        next_start = dated[i + 1]["event"].start
        if curr_end and next_start:
            gap_months = (next_start[0] * 12 + next_start[1]) - (curr_end[0] * 12 + curr_end[1]) - 1
            if gap_months > 0:
                gaps.append({
                    "months": gap_months,
                    "start": [curr_end[0], curr_end[1] + 1] if curr_end[1] < 12 else [curr_end[0] + 1, 1],
                    "end": [next_start[0], next_start[1] - 1] if next_start[1] > 1 else [next_start[0] - 1, 12],
                    "before": dated[i]["event"].title,
                    "after": dated[i + 1]["event"].title
                })
    return gaps


def _compute_verification_metrics(verified_events):
    """Compute precision/recall style metrics from verification."""
    total = len(verified_events)
    if total == 0:
        return {"precision": 0, "recall": 0, "f1": 0, "field_accuracy": {}}
    
    # Field-level accuracy
    fields = ["title", "org", "start", "end"]
    field_correct = {f: 0 for f in fields}
    field_total = {f: 0 for f in fields}
    
    for ve in verified_events:
        v = ve["verified"]
        for f in fields:
            key = f"{f}_verified"
            if v.get(key) is not None:
                field_total[f] += 1
                if v[key]:
                    field_correct[f] += 1
    
    field_acc = {}
    for f in fields:
        field_acc[f] = round(field_correct[f] / field_total[f], 3) if field_total[f] > 0 else 0
    
    # Overall: event is "correct" if all its extracted fields are verified
    fully_correct = sum(1 for ve in verified_events 
                       if all(ve["verified"].get(f"{f}_verified", True) for f in fields if ve["event"].__dict__.get(f)))
    
    return {
        "precision": round(fully_correct / total, 3),
        "field_accuracy": field_acc,
        "verified_events": fully_correct,
        "total_events": total
    }


def s13_verification(ctx):
    """Verify extracted timeline against source text. Compute TRUE accuracy."""
    if not ctx.events:
        return _sr("verification", status="SKIPPED", confidence=0.0,
                   errors=["no events to verify"])
    
    raw_text = ctx.raw_text or ""
    blocks_by_id = ctx.blocks_by_id()
    
    # Verify each event
    verified_events = []
    for e in ctx.events:
        verified = _verify_event_against_source(e, raw_text, blocks_by_id)
        verified_events.append({"event": e, "verified": verified})
    
    # Compute verified gaps
    verified_gaps = _compute_verified_gaps(verified_events)
    
    # Compute metrics
    metrics = _compute_verification_metrics(verified_events)
    
    # Store in context
    ctx.verified_events = verified_events
    ctx.verified_gaps = verified_gaps
    ctx.verification_metrics = metrics
    
    # Add to recruiter output
    dto = ctx.recruiter_output
    if dto:
        dto["verification"] = {
            "metrics": metrics,
            "verified_gaps": verified_gaps,
            "event_verification": [
                {
                    "event_id": ve["event"].id,
                    "type": ve["event"].type,
                    "title": ve["event"].title,
                    "org": ve["event"].org,
                    "title_verified": ve["verified"]["title_verified"],
                    "org_verified": ve["verified"]["org_verified"],
                    "start_verified": ve["verified"]["start_verified"],
                    "end_verified": ve["verified"]["end_verified"],
                    "source_spans": ve["verified"]["source_spans"]
                }
                for ve in verified_events
            ]
        }
    
    return _sr("verification", status="SUCCESS", confidence=0.9,
               output={"verified_events": metrics["verified_events"], 
                       "total_events": metrics["total_events"],
                       "precision": metrics["precision"],
                       "verified_gaps": len(verified_gaps)},
               evidence={"field_accuracy": metrics["field_accuracy"]})


STAGE_FUNCS = (
    s01_document_processing, s02_text_representation, s03_section_detection,
    s04_entry_segmentation, s05_date_extraction, s06_date_association,
    s07_event_classification, s08_timeline_reconciliation, s09_coverage_analysis,
    s10_gap_detection, s11_confidence_evidence, s12_recruiter_output,
    s13_verification,
)


def by_en_text(ctx, entry_id):
    e = ctx.entries_by_id().get(entry_id)
    return (e.text[:300] if e else "")


def _guess_candidate_name(ctx):
    return ""  # filename is a document label, not an inferred candidate identity


def _overall_status(ctx):
    vals = [r.status for r in ctx.stage_results.values()]
    if "FAILED" in vals[:2]:
        return "FAILED"
    if "FAILED" in vals or "PARTIAL" in vals:
        return "PARTIAL"
    if vals and all(v == "SUCCESS" for v in vals):
        return "SUCCESS"
    return "PARTIAL"



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
