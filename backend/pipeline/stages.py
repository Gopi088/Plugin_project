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


COMPANY_HINT = re.compile(
    r"Pvt\.?\s*Ltd\.?|Pvt Ltd|Ltd\.?|Inc\.?|LLP|Technolog|Solutions|Systems|"
    r"Services|Consulting|Digital|Engineering|Labs|Group|Bank|Infotech|"
    r"Client\s*:|Company\s*:|Organization\s*", re.IGNORECASE)
TITLE_CUE = re.compile(
    r"Engineer|Developer|Analyst|Manager|Consultant|Architect|Tester|Lead|"
    r"Administrator|Specialist|Owner|Head|Intern|Associate|Designer|Scientist",
    re.IGNORECASE)
DEGREE_CUE = re.compile(
    r"B\.?\s*E\.?|B\.?\s*Tech|Bachelor|M\.?\s*Tech|Master|MCA|MBA|BCA|Diploma|"
    r"Ph\.?\s*D|B\.?\s*Sc|M\.?\s*Sc|B\.?\s*Com|SSC|HSC|CGPA|University|College|"
    r"Institute|School", re.IGNORECASE)
PROJECT_HEAD = re.compile(r"^\s*PROJECT\s*#?\s*\d+\s*[:\-–.]?\s*(.+?)\s*$", re.IGNORECASE)
NAV_PAT = re.compile(
    r"leetcode|hackerrank|codechef|github\.com|linkedin|transformed\s+by|"
    r"references|declaration|^https?://|www\.", re.IGNORECASE)

SECTION_KINDS = (
    ("EXPERIENCE", ("PROFESSIONAL EXPERIENCE", "WORK EXPERIENCE", "EMPLOYMENT HISTORY", "EXPERIENCE", "INTERNSHIP", "INTERNSHIPS")),
    ("EDUCATION", ("EDUCATION", "ACADEMIC", "QUALIFICATION")),
    ("PROJECTS", ("KEY PROJECTS", "PROJECT PROFILE", "PROJECTS PROFILE", "PROJECTS")),
    ("SKILLS", ("TECHNICAL SKILLS", "SKILLS")),
)


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
    name = (ctx.filename or "").lower()
    try:
        if ctx.raw_bytes and name.endswith(".pdf"):
            import pdfplumber
            import io
            pages_list = []
            with pdfplumber.open(io.BytesIO(ctx.raw_bytes)) as pdf:
                pages = len(pdf.pages)
                for p in pdf.pages:
                    pages_list.append(p.extract_text() or "")
            text = "\n".join(pages_list)
        elif ctx.raw_bytes and name.endswith(".docx"):
            from docx import Document
            import io
            doc = Document(io.BytesIO(ctx.raw_bytes))
            text = "\n".join(p.text for p in doc.paragraphs)
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

def s02_text_representation(ctx):
    """Input: clean text. Output: ordered TextBlocks (page/position/format)."""
    if not ctx.raw_text.strip():
        return _sr("text_representation", status="FAILED", confidence=0.0,
                   errors=["no text to represent"])
    lines = [ln for ln in ctx.raw_text.split("\n")]
    # crude page split: source had no page map in text mode; keep page=1
    # (submit path with bytes could map pages; extension-text path is page-less)
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
    words = s.split()
    if len(words) <= 12 and (COMPANY_HINT.search(s) or TITLE_CUE.search(s)
                             or DEGREE_CUE.search(s) or s.isupper()):
        return True
    return False


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
        cur_lines, cur_bids, pending, pending_ids = [], [], [], []

        def flush():
            if cur_lines:
                eid = f"e{len(entries)}"
                entries.append(M.Entry(eid, sec.id, " ".join(cur_lines),
                                       list(cur_bids), len(entries)))

        for bid in sec.block_ids:
            b = by_id.get(bid)
            if b is None:
                continue
            line = b.text.strip()
            if not line or line.strip(":").upper() == sec.header_text.strip(":").upper():
                continue
            if NAV_PAT.search(line):
                if cur_lines:
                    flush()
                    cur_lines, cur_bids = [], []
                continue
            if _looks_like_entry_start(line):
                if cur_lines:
                    flush()
                cur_lines = pending + [line]
                cur_bids = pending_ids + [bid]
                pending, pending_ids = [], []
            elif line.startswith("•") and cur_lines:
                cur_lines.append(line)
                cur_bids.append(bid)
            elif cur_lines:
                cur_lines[-1] += " " + line
            else:
                pending.append(line)
                pending_ids.append(bid)
        if cur_lines:
            flush()
        elif pending:
            eid = f"e{len(entries)}"
            entries.append(M.Entry(eid, sec.id, " ".join(pending), list(pending_ids), len(entries)))
            warnings.append(f"section {sec.kind}: entry without dated header preserved as-is")
    # fix placeholder bids: entries store real block ids only
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
        ms = sorted(by_entry.get(e.id, []), key=lambda m: (m.block_id, m.raw))
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
            singles = [m for m in ms if not m.is_range and m.precision == "month"]
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

def _split_title_org(text):
    # "Title, Company, Date..." or "Company | Title | Date" first
    for sep in ("|", ","):
        if sep in text:
            parts = [p.strip(" -–—") for p in text.split(sep) if p.strip(" -–—")]
            orgs = [p for p in parts if COMPANY_HINT.search(p)]
            if orgs:
                org = orgs[0]
                rest = [p for p in parts if p != org and not D.find_mentions(p)]
                title = next((p for p in rest if TITLE_CUE.search(p)), rest[0] if rest else "")
                return title.strip(), org.strip()
    m = COMPANY_HINT.search(text)
    if m:
        tm = re.match(r"^(.*?(?:Engineer|Developer|Analyst|Manager|Consultant|Architect|"
                      r"Tester|Lead|Administrator|Specialist|Owner|Head|Intern|Associate|"
                      r"Designer|Scientist))\s+(.+)$", text.strip(), re.IGNORECASE)
        if tm:
            return tm.group(1).strip(), tm.group(2).strip()
        idx = text.lower().find(m.group(0).lower())
        return text[:idx].strip(" -–—,|"), text[idx:].strip(" -–—,|")
    return text.strip(), ""


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
    for e in ctx.entries:
        kind = sec_kind.get(e.section_id, "OTHER")
        low = e.text.lower()
        if "intern" in low and kind == "EXPERIENCE":
            etype, reason = "INTERNSHIP", "EVENT_INTERNSHIP_CUES"
        elif kind == "EDUCATION":
            etype, reason = "EDUCATION", "EVENT_EDUCATION_CUES"
        elif kind == "PROJECTS":
            etype, reason = "PROJECT", "EVENT_PROJECT_CUES"
        elif kind == "EXPERIENCE":
            etype, reason = "EMPLOYMENT", "EVENT_EMPLOYMENT_CUES"
        else:
            etype, reason = "OTHER", "EVENT_UNCLASSIFIED"
        title, org = _split_title_org(e.text.split("•")[0][:160])
        # date span from best assoc
        aa = assoc_by_entry.get(e.id, [])
        confirmed = [a for a in aa if a.status == "CONFIRMED"]
        ambig = [a for a in aa if a.status == "AMBIGUOUS"]
        status, span, precision, conf = "UNRESOLVED", None, "month", 0.3
        aids = [a.id for a in aa]
        by_mid = {m.id: m for m in ctx.mentions}
        best_mention = None
        if confirmed and confirmed[0].mention_id in by_mid:
            best_mention = by_mid[confirmed[0].mention_id]
        elif ambig and ambig[0].mention_id in by_mid:
            best_mention = by_mid[ambig[0].mention_id]
        if best_mention is not None:
            # strip the matched date text so it never leaks into title/org
            first = e.text.split("•")[0].replace(best_mention.raw, " ", 1)
            first = re.sub(r"\s+", " ", first).strip(" -–—,|")
            title, org = _split_title_org(first[:160])
        if confirmed and confirmed[0].mention_id in by_mid:
            m_ = by_mid[confirmed[0].mention_id]
            span, precision = (m_.start, m_.end), m_.precision
            status = "CONFIRMED"
            conf = EV.event_confidence("CONFIRMED", precision, sec_conf.get(e.section_id, 1.0))
        elif ambig and ambig[0].mention_id in by_mid:
            m_ = by_mid[ambig[0].mention_id]
            span, precision = (m_.start, m_.end), m_.precision
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
        for i, (a, b) in enumerate(zip(dated, dated[1:])):
            gm = D.months_between(a.end, b.start)
            if gm <= 0:
                continue  # overlap/adjacency: represented, not a gap
            g = M.Gap(f"g{i}", list(a.end), list(b.start), gm, "POTENTIAL_GAP",
                      0.0, ["GAP_NO_COVERAGE"],  # confidence filled in stage 11
                      {"event_before": a.id, "event_after": b.id})
            gaps.append(g)
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
