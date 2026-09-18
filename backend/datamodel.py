"""Data models + API contracts for the Resume Timeline & Gap Detection system.

All models are JSON-serializable via ``to_dict()``. The browser extension only
ever sees the Recruiter Output DTO (stage 12) plus the item endpoints below.

API contracts (backend/server.py implements these):
    POST /api/documents            {filename, content_b64?, text?, source_url?} -> {doc_id, status}
    GET  /api/documents/{id}/status    -> overall status + per-stage status/confidence
    GET  /api/documents/{id}/timeline  -> recruiter output DTO (stage 12)
    GET  /api/documents/{id}/evidence?gap_id=G / ?event_id=E -> evidence lineage chain
    GET  /api/documents/{id}/stages    -> full per-stage results (input/output/status/evidence/confidence/errors)
    POST /api/documents/{id}/feedback  {dismissed_gap_ids[], overrides[], notes?} -> stored
    GET  /health -> {ok, model_versions}

Vocabulary rules enforced here:
  - gaps are POTENTIAL_GAP / NO_GAP_DETECTED / INSUFFICIENT_EVIDENCE only;
    the system must never label a candidate as unemployed (the standard
    disclaimer instead states gaps are *not* evidence of unemployment).
"""

STAGE_STATUSES = ("SUCCESS", "PARTIAL", "FAILED", "SKIPPED")
GAP_STATES = ("NO_GAP_DETECTED", "POTENTIAL_GAP", "INSUFFICIENT_EVIDENCE")
ASSOC_STATUSES = ("CONFIRMED", "AMBIGUOUS", "UNRESOLVED")
EVENT_TYPES = ("EMPLOYMENT", "EDUCATION", "INTERNSHIP", "PROJECT", "OTHER")

# 12 pipeline stages in order.
STAGES = (
    "document_processing",
    "text_representation",
    "section_detection",
    "entry_segmentation",
    "date_extraction",
    "date_association",
    "event_classification",
    "timeline_reconciliation",
    "coverage_analysis",
    "gap_detection",
    "confidence_evidence",
    "recruiter_output",
)

# Machine-readable reason codes attached to results.
REASONS = (
    "DATE_EXPLICIT_RANGE", "DATE_SINGLE_MONTH_YEAR", "DATE_SINGLE_YEAR",
    "DATE_PRESENT_AS_TODAY", "DATE_AMBIGUOUS", "DATE_INVALID",
    "ASSOC_SAME_LINE", "ASSOC_NEXT_LINE", "ASSOC_PROXIMITY",
    "ASSOC_AMBIGUOUS_MULTI", "ASSOC_UNRESOLVED_NO_DATE",
    "SECTION_HEADER_MATCH", "SECTION_ML_HINT", "SECTION_MISSING",
    "ENTRY_BULLET_PARSE", "ENTRY_HEADER_PARSE",
    "EVENT_EMPLOYMENT_CUES", "EVENT_EDUCATION_CUES", "EVENT_INTERNSHIP_CUES",
    "EVENT_PROJECT_CUES", "EVENT_UNCLASSIFIED",
    "OVERLAP_PRESERVED", "CONFLICT_PRESERVED", "DATE_TRUNCATED_TO_MONTH",
    "GAP_NO_COVERAGE", "GAP_AFTER_LAST_EVENT_EXCLUDED",
    "INSUFFICIENT_DATES", "DOC_SCANNED_OCR_NEEDED", "DOC_EMPTY",
    "DOC_MALFORMED", "RECRUITER_OVERRIDE", "RECRUITER_DISMISSED",
)


def _d(obj):
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, (list, tuple)):
        return [_d(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _d(v) for k, v in obj.items()}
    return obj


class TextBlock:
    def __init__(self, bid, page, order, text, bold=False, size=0.0):
        self.id = bid
        self.page = page
        self.order = order
        self.text = text
        self.bold = bold
        self.size = size

    def to_dict(self):
        return vars(self)


class Section:
    def __init__(self, sid, kind, header_text, block_ids, confidence, reason):
        self.id = sid
        self.kind = kind  # EXPERIENCE/EDUCATION/PROJECTS/SKILLS/OTHER
        self.header_text = header_text
        self.block_ids = block_ids
        self.confidence = confidence
        self.reason = reason

    def to_dict(self):
        return vars(self)


class Entry:
    def __init__(self, eid, section_id, text, block_ids, order):
        self.id = eid
        self.section_id = section_id
        self.text = text
        self.block_ids = block_ids
        self.order = order

    def to_dict(self):
        return vars(self)


class DateMention:
    def __init__(self, mid, block_id, entry_id, raw, char_start, char_end,
                 precision, start, end, is_range, is_present):
        self.id = mid
        self.block_id = block_id
        self.entry_id = entry_id  # may be None if found outside an entry
        self.raw = raw            # original text, never rewritten
        self.char_start = char_start
        self.char_end = char_end
        self.precision = precision  # 'month' | 'year'
        self.start = start          # (year, month)
        self.end = end              # (year, month); year-only => Jan..Dec
        self.is_range = is_range
        self.is_present = is_present  # end == today ("Present"/"till date"...)

    def to_dict(self):
        return vars(self)


class DateAssoc:
    def __init__(self, aid, entry_id, mention_id, status, confidence, reason):
        assert status in ASSOC_STATUSES
        self.id = aid
        self.entry_id = entry_id
        self.mention_id = mention_id
        self.status = status
        self.confidence = confidence
        self.reason = reason

    def to_dict(self):
        return vars(self)


class Event:
    def __init__(self, eid, entry_id, assoc_ids, etype, title, org,
                 start, end, precision, status, confidence, reasons):
        assert etype in EVENT_TYPES
        self.id = eid
        self.entry_id = entry_id
        self.assoc_ids = assoc_ids
        self.type = etype
        self.title = title
        self.org = org
        self.start = start  # (year, month)
        self.end = end
        self.precision = precision
        self.status = status  # CONFIRMED | AMBIGUOUS | UNRESOLVED
        self.confidence = confidence
        self.reasons = reasons

    def to_dict(self):
        return vars(self)


class Gap:
    def __init__(self, gid, start, end, months, state, confidence, reasons, evidence):
        assert state in GAP_STATES
        self.id = gid
        self.start = start
        self.end = end
        self.months = months
        self.state = state
        self.confidence = confidence
        self.reasons = reasons
        self.evidence = evidence  # {"event_before": id|None, "event_after": id|None, ...}

    def to_dict(self):
        return vars(self)


class StageResult:
    """Uniform envelope every one of the 12 stages must return."""

    def __init__(self, stage, status="SUCCESS", confidence=1.0,
                 errors=None, warnings=None, output=None, evidence=None):
        assert status in STAGE_STATUSES
        self.stage = stage
        self.status = status
        self.confidence = confidence
        self.errors = errors or []
        self.warnings = warnings or []
        self.output = output or {}
        self.evidence = evidence or {}

    def to_dict(self):
        return {"stage": self.stage, "status": self.status,
                "confidence": self.confidence, "errors": self.errors,
                "warnings": self.warnings, "output": _d(self.output),
                "evidence": _d(self.evidence)}
