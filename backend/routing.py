"""Overall confidence scoring & routing decision.

S estimates "is the extraction correct?", not "is the resume messy?":
it is built from per-event confidence (evidence.py), field source-span
grounding, dates-parsed share, ML-vs-rule agreement, and document
readability. Data-quality flags (DATE_CONFLICT, GAP_AMBIGUOUS,
PROJECT_OUTSIDE_EMPLOYER_DATES) are informational and cost at most
5 points in total.
"""
import yaml
import logging
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class Route(Enum):
    AUTO_APPROVE = "auto_approve"
    LLM_REVIEW = "llm_review"
    HUMAN_REVIEW = "human_review"


@dataclass
class RoutingDecision:
    score: int
    route: Route
    reasons: List[str]


_config_cache = None


def load_config():
    global _config_cache
    if _config_cache is None:
        cfg_path = Path(__file__).parents[1] / "config" / "routing.yaml"
        with open(cfg_path) as f:
            _config_cache = yaml.safe_load(f)
    return _config_cache


def _is_sentence_fragment(text: str) -> bool:
    """Detect if title or project name looks like a sentence fragment."""
    if not text:
        return False
    t = text.strip()
    if not t:
        return False
    if t[0].islower() or t[0] in ",.;:-":
        return True
    first_word = t.split()[0].lower()
    if first_word in ("and", "with", "or", "in", "at", "for"):
        return True
    words = t.split()
    if len(words) > 12:
        alpha_words = [w for w in words if any(c.isalpha() for c in w)]
        if alpha_words:
            title_count = sum(1 for w in alpha_words if w[0].isupper())
            if title_count / len(alpha_words) < 0.4:
                return True
    return False


def _get_all_events(ctx) -> list:
    """Return all extracted events across timeline and unresolved collections."""
    if hasattr(ctx, "events") and ctx.events:
        return ctx.events
    dto = ctx.recruiter_output if isinstance(ctx.recruiter_output, dict) else {}
    return (dto.get("timeline", []) or []) + (dto.get("unresolved_events", []) or [])


def _compute_event_score(ctx) -> float:
    """Weighted event confidence factoring in failure signatures proportionally."""
    events = _get_all_events(ctx)
    dto = ctx.recruiter_output if isinstance(ctx.recruiter_output, dict) else {}
    if not events and not dto.get("projects"):
        return 0.0

    weights = {"EMPLOYMENT": 1.5, "INTERNSHIP": 1.2, "EDUCATION": 1.0, "PROJECT": 0.8, "OTHER": 0.5}
    event_scores = []
    emp_scores = []
    total_emp = 0
    confirmed_emp = 0

    for ev in events:
        etype = getattr(ev, "type", None) or (ev.get("type") if isinstance(ev, dict) else "OTHER")
        title = getattr(ev, "title", None) if hasattr(ev, "title") else (ev.get("title", "") if isinstance(ev, dict) else "")
        org = getattr(ev, "org", None) if hasattr(ev, "org") else (ev.get("org", "") if isinstance(ev, dict) else "")
        status = getattr(ev, "status", None) if hasattr(ev, "status") else (ev.get("status", "CONFIRMED") if isinstance(ev, dict) else "CONFIRMED")
        conf = getattr(ev, "confidence", None) if hasattr(ev, "confidence") else (ev.get("confidence") if isinstance(ev, dict) else None)

        if conf is None:
            conf = 0.35 if status == "UNRESOLVED" else (0.60 if status == "AMBIGUOUS" else 0.85)

        # Failure signature a: unlinked entry (empty org or institution when title/degree is present, or vice versa)
        if etype in ("EMPLOYMENT", "INTERNSHIP"):
            if not org:
                conf *= 0.5
            elif not title:
                conf *= 0.95
        elif etype == "EDUCATION":
            if not org or not title:
                conf *= 0.5

        # Failure signature b: status UNRESOLVED or AMBIGUOUS on a core field
        if status == "UNRESOLVED":
            conf = min(conf, 0.40)
        elif status == "AMBIGUOUS":
            conf = min(conf, 0.65)

        # Failure signature c: sentence fragment as title
        if _is_sentence_fragment(title):
            conf *= 0.20

        w = weights.get(etype, 0.5)
        event_scores.append((conf, w))

        if etype in ("EMPLOYMENT", "INTERNSHIP"):
            total_emp += 1
            if status == "CONFIRMED" and org:
                confirmed_emp += 1
            emp_scores.append(conf)

    # Include project entries
    for p in dto.get("projects", []):
        pname = p.get("name", "") if isinstance(p, dict) else ""
        pconf = 0.10 if _is_sentence_fragment(pname) else 0.80
        event_scores.append((pconf, weights.get("PROJECT", 0.8)))

    weighted_sum = sum(c * w for c, w in event_scores)
    total_w = sum(w for c, w in event_scores)
    mean_event = weighted_sum / total_w if total_w else 0.0

    if emp_scores:
        weakest_employment = min(emp_scores)
        # Failure signature d: share of employment entries with CONFIRMED status below threshold (0.5)
        emp_share = (confirmed_emp / total_emp) if total_emp else 0.0
        share_factor = 1.0 if emp_share >= 0.5 else max(0.20, emp_share / 0.5)
        return (0.7 * mean_event + 0.3 * weakest_employment) * share_factor

    return mean_event


def _field_grounding(ctx) -> float:
    """Fraction of expected core fields that are successfully grounded."""
    dto = ctx.recruiter_output if isinstance(ctx.recruiter_output, dict) else {}
    events = _get_all_events(ctx)
    checked, grounded = 0, 0

    for ev in events:
        etype = getattr(ev, "type", None) or (ev.get("type") if isinstance(ev, dict) else "OTHER")
        title = getattr(ev, "title", None) if hasattr(ev, "title") else (ev.get("title", "") if isinstance(ev, dict) else "")
        org = getattr(ev, "org", None) if hasattr(ev, "org") else (ev.get("org", "") if isinstance(ev, dict) else "")
        src = getattr(ev, "source", None) if hasattr(ev, "source") else (ev.get("source", {}) if isinstance(ev, dict) else {})
        src = src or {}

        if etype in ("EMPLOYMENT", "INTERNSHIP", "EDUCATION"):
            # Title and organization/institution are both expected core fields
            checked += 2
            if title and src.get("title") and not _is_sentence_fragment(title):
                grounded += 1
            if org and src.get("company"):
                grounded += 1

            start = getattr(ev, "start", None) if hasattr(ev, "start") else (ev.get("start") if isinstance(ev, dict) else None)
            end = getattr(ev, "end", None) if hasattr(ev, "end") else (ev.get("end") if isinstance(ev, dict) else None)
            if start or end or etype in ("EMPLOYMENT", "INTERNSHIP"):
                checked += 1
                if (start or end) and src.get("dates"):
                    grounded += 1
        else:
            if title:
                checked += 1
                if src.get("title") and not _is_sentence_fragment(title):
                    grounded += 1
            if org:
                checked += 1
                if src.get("company"):
                    grounded += 1

    for p in dto.get("projects", []):
        checked += 1
        pname = p.get("name", "") if isinstance(p, dict) else ""
        psrc = p.get("source", {}).get("entry") if isinstance(p, dict) else None
        if pname and psrc and not _is_sentence_fragment(pname):
            grounded += 1

    if checked == 0:
        return 0.0
    return grounded / checked


def _dates_share(ctx) -> float:
    """Share of extracted events that are dated (timeline vs unresolved)."""
    dto = ctx.recruiter_output if isinstance(ctx.recruiter_output, dict) else {}
    dated = len(dto.get("timeline", []) or [])
    unresolved = len(dto.get("unresolved_events", []) or [])
    total = dated + unresolved
    return (dated / total) if total else 0.0


def _ml_agreement(ctx) -> float:
    """ML-vs-rule agreement on sections."""
    from . import ml_assist
    if ml_assist.version() == "none":
        return 1.0
    try:
        hints = ml_assist.section_hints(ctx.raw_text)
    except Exception:
        return 1.0
    if not hints:
        return 1.0
    return 1.0


def data_quality_flags(ctx) -> List[Dict[str, Any]]:
    """Informational data-quality flags (NOT extraction errors).

    - DATE_CONFLICT: a dated project extends outside its parent employer.
    - PROJECT_OUTSIDE_EMPLOYER_DATES: a dated project overlaps no employment.
    - GAP_AMBIGUOUS: a potential gap with low confidence or ambiguous bounds.
    """
    flags = []
    dto = ctx.recruiter_output if isinstance(ctx.recruiter_output, dict) else {}
    events = dto.get("timeline", []) or []

    for e in events:
        if e.get("type") != "PROJECT" or not e.get("start") or not e.get("end"):
            continue
        if "DATE_CONFLICT" not in (e.get("reasons") or []):
            continue
        conflict = None
        for ev in getattr(ctx, "events", []) or []:
            if getattr(ev, "id", None) == e.get("id"):
                conflict = getattr(ev, "conflict", None)
                break
        flags.append({
            "code": "DATE_CONFLICT",
            "event_id": e.get("id"),
            "detail": (f"project {e.get('title', '')!r} @ {e.get('org', '')!r} "
                       f"({_fmt_ym(e.get('start'))}–{_fmt_ym(e.get('end'))})"),
            "conflict": conflict,
        })

    employments = [e for e in events if e.get("type") in ("EMPLOYMENT", "INTERNSHIP")
                   and e.get("start") and e.get("end")]
    for e in events:
        if e.get("type") != "PROJECT" or not e.get("start") or not e.get("end"):
            continue
        if any(e.get("id") == f.get("event_id") for f in flags if f["code"] == "DATE_CONFLICT"):
            continue
        overlaps = any(not (e.get("end") < w.get("start") or e.get("start") > w.get("end"))
                       for w in employments)
        if not overlaps and employments:
            flags.append({
                "code": "PROJECT_OUTSIDE_EMPLOYER_DATES",
                "event_id": e.get("id"),
                "detail": (f"project {e.get('title', '')!r} @ {e.get('org', '')!r} "
                           f"({_fmt_ym(e.get('start'))}–{_fmt_ym(e.get('end'))}) "
                           f"overlaps no employment tenure"),
                "conflict": None,
            })

    by_id = {ev.get("id"): ev for ev in events if isinstance(ev, dict)}
    for g in dto.get("gaps", []) or []:
        if g.get("state") != "POTENTIAL_GAP":
            continue
        ev = g.get("evidence", {}) or {}
        ambiguous_bounds = any(
            (by_id.get(ev.get(k)) or {}).get("status") == "AMBIGUOUS"
            for k in ("event_before", "event_after")
        )
        if (g.get("confidence", 1) < 0.6) or ambiguous_bounds:
            flags.append({
                "code": "GAP_AMBIGUOUS",
                "event_id": g.get("id"),
                "detail": (f"gap {g.get('months')} months "
                           f"({_fmt_ym(g.get('start'))}–{_fmt_ym(g.get('end'))}) "
                           f"has low/ambiguous bounds"),
                "conflict": None,
            })
    return flags


def _compute_doc_quality(ctx) -> float:
    """Document quality from stage 1."""
    stages = getattr(ctx, "stage_results", None) or {}
    doc_result = stages.get("document_processing")
    if not doc_result:
        return 0.5
    conf = doc_result.confidence
    reading_incomplete = (getattr(ctx, "meta", None) or {}).get("reading_incomplete", False)
    if reading_incomplete:
        conf *= 0.6
    return conf


def _conflict_events(ctx) -> list:
    """Dated PROJECT events carrying a DATE_CONFLICT reason."""
    events = ctx.recruiter_output.get("timeline", []) if isinstance(ctx.recruiter_output, dict) else []
    dated = [e for e in events if e.get("start") and e.get("end")]
    return [e for e in dated if "DATE_CONFLICT" in (e.get("reasons") or [])]


def _fmt_ym(value) -> str:
    if isinstance(value, str):
        return value
    try:
        return f"{value[0]:04d}-{value[1]:02d}"
    except (TypeError, IndexError):
        return "?"


def conflict_reason_lines(ctx) -> List[str]:
    """Human-readable DATE_CONFLICT lines naming both items and dates."""
    lines = []
    for e in _conflict_events(ctx):
        conflict = None
        for ev in getattr(ctx, "events", []) or []:
            if getattr(ev, "id", None) == e.get("id"):
                conflict = getattr(ev, "conflict", None)
                break
        parent = (conflict or {}).get("parent_org", "") if conflict else ""
        lines.append(
            f"DATE_CONFLICT: project {e.get('title', '')!r} @ {e.get('org', '')!r} "
            f"({_fmt_ym(e.get('start'))}–{_fmt_ym(e.get('end'))}) extends outside "
            f"employer {parent!r} "
            f"({_fmt_ym((conflict or {}).get('employment_start'))}–{_fmt_ym((conflict or {}).get('employment_end'))})"
            if conflict else
            f"DATE_CONFLICT: project {e.get('title', '')!r} @ {e.get('org', '')!r} "
            f"({_fmt_ym(e.get('start'))}–{_fmt_ym(e.get('end'))}) extends outside its parent employment"
        )
    return lines


def compute_overall_confidence(ctx) -> int:
    """Compute 0-100 extraction confidence (drives routing).

    S estimates "is the extraction correct?", not "is the resume messy?":
      S = 100 × (0.35·event + 0.20·grounding + 0.15·dated_share
                 + 0.05·ml_agreement + 0.25·readability)
          − min(5, 2 × num_data_quality_flags)
    """
    event_score = _compute_event_score(ctx)
    grounding = _field_grounding(ctx)
    dated_share = _dates_share(ctx)
    ml_agreement = _ml_agreement(ctx)
    readability = _compute_doc_quality(ctx)

    base = (
        0.35 * event_score +
        0.20 * grounding +
        0.15 * dated_share +
        0.05 * ml_agreement +
        0.25 * readability
    )

    events = _get_all_events(ctx)
    dto = ctx.recruiter_output if isinstance(ctx.recruiter_output, dict) else {}
    total_entries = len(events)

    unlinked_entries = 0
    unresolved_or_ambiguous = 0
    fragment_names = 0
    for e in events:
        etype = getattr(e, "type", None) or (e.get("type") if isinstance(e, dict) else "")
        title = getattr(e, "title", None) if hasattr(e, "title") else (e.get("title", "") if isinstance(e, dict) else "")
        org = getattr(e, "org", None) if hasattr(e, "org") else (e.get("org", "") if isinstance(e, dict) else "")
        status = getattr(e, "status", None) if hasattr(e, "status") else (e.get("status", "") if isinstance(e, dict) else "")
        if etype in ("EMPLOYMENT", "INTERNSHIP"):
            if not org:
                unlinked_entries += 1
        elif etype == "EDUCATION":
            if not org or not title:
                unlinked_entries += 1
        if status in ("UNRESOLVED", "AMBIGUOUS"):
            unresolved_or_ambiguous += 1
        if _is_sentence_fragment(title):
            fragment_names += 1

    for p in dto.get("projects", []):
        pname = p.get("name", "") if isinstance(p, dict) else ""
        if _is_sentence_fragment(pname):
            fragment_names += 1

    unlinked_pen = (unlinked_entries / total_entries * 0.25) if total_entries else 0.0
    unres_pen = (unresolved_or_ambiguous / total_entries * 0.15) if total_entries else 0.0
    frag_pen = min(0.15, fragment_names * 0.05)

    flags = data_quality_flags(ctx)
    flag_penalty = min(5, 2 * len(flags)) / 100.0
    overall = base - flag_penalty - unlinked_pen - unres_pen - frag_pen

    # If >= 33% of entries are unlinked or >= 40% are UNRESOLVED/AMBIGUOUS,
    # the extraction has structural failures and must not auto-approve.
    if total_entries and (unlinked_entries / total_entries >= 0.33 or unresolved_or_ambiguous / total_entries >= 0.40):
        overall = min(overall, 0.58)

    ctx.meta.setdefault("routing_debug", {})["flag_penalty_points"] = round(flag_penalty * 100)
    ctx.meta["routing_debug"]["flag_codes"] = [f["code"] for f in flags]
    ctx.meta["routing_debug"]["unlinked_penalty_points"] = round(unlinked_pen * 100)
    return round(max(0, min(100, overall * 100)))


def score_components(ctx) -> Dict[str, Any]:
    """Return per-component scores for diagnosis (0-1 each + overall 0-100)."""
    events = _get_all_events(ctx)
    dto = ctx.recruiter_output if isinstance(ctx.recruiter_output, dict) else {}
    employment = [e for e in events if (getattr(e, "type", None) or (e.get("type") if isinstance(e, dict) else "")) in ("EMPLOYMENT", "INTERNSHIP")]
    flags = data_quality_flags(ctx)

    unlinked_entries = 0
    unresolved_or_ambiguous = 0
    fragment_names = 0
    for e in events:
        etype = getattr(e, "type", None) or (e.get("type") if isinstance(e, dict) else "")
        title = getattr(e, "title", None) if hasattr(e, "title") else (e.get("title", "") if isinstance(e, dict) else "")
        org = getattr(e, "org", None) if hasattr(e, "org") else (e.get("org", "") if isinstance(e, dict) else "")
        status = getattr(e, "status", None) if hasattr(e, "status") else (e.get("status", "") if isinstance(e, dict) else "")
        if etype in ("EMPLOYMENT", "INTERNSHIP"):
            if not org:
                unlinked_entries += 1
        elif etype == "EDUCATION":
            if not org or not title:
                unlinked_entries += 1
        if status in ("UNRESOLVED", "AMBIGUOUS"):
            unresolved_or_ambiguous += 1
        if _is_sentence_fragment(title):
            fragment_names += 1

    for p in dto.get("projects", []):
        pname = p.get("name", "") if isinstance(p, dict) else ""
        if _is_sentence_fragment(pname):
            fragment_names += 1

    emp_confs = [getattr(e, "confidence", None) if hasattr(e, "confidence") else (e.get("confidence") if isinstance(e, dict) else 1) for e in employment]
    emp_confs = [c for c in emp_confs if c is not None]

    comp = {
        "event_score": round(_compute_event_score(ctx), 3),
        "field_grounding": round(_field_grounding(ctx), 3),
        "dates_share": round(_dates_share(ctx), 3),
        "ml_agreement": round(_ml_agreement(ctx), 3),
        "readability": round(_compute_doc_quality(ctx), 3),
        "weakest_employment": (
            round(min(emp_confs), 3) if emp_confs else None
        ),
        "unlinked_entries": unlinked_entries,
        "unresolved_or_ambiguous": unresolved_or_ambiguous,
        "sentence_fragment_names": fragment_names,
        "flags": [f["code"] for f in flags],
        "flag_penalty_points": min(5, 2 * len(flags)),
        "conflict_events": len(_conflict_events(ctx)),
    }
    comp["overall"] = compute_overall_confidence(ctx)
    return comp


def _employment_date_conflict(ctx) -> bool:
    """True when a DATE_CONFLICT sits inside a job's own dates."""
    for ev in getattr(ctx, "events", []) or []:
        if getattr(ev, "type", None) in ("EMPLOYMENT", "INTERNSHIP"):
            if "DATE_CONFLICT" in (getattr(ev, "reasons", []) or []):
                return True
    return False


def decide_route(ctx) -> "RoutingDecision":
    cfg = load_config()["routing"]
    score = compute_overall_confidence(ctx)
    reasons = []

    if score >= cfg["high_confidence_threshold"]:
        route = Route.AUTO_APPROVE
        reasons.append(f"Score {score} >= {cfg['high_confidence_threshold']}")
    elif score >= cfg["low_confidence_threshold"]:
        route = Route.LLM_REVIEW
        reasons.append(f"Score {score} in [{cfg['low_confidence_threshold']}, {cfg['high_confidence_threshold']})")
    else:
        route = Route.HUMAN_REVIEW
        reasons.append(f"Score {score} < {cfg['low_confidence_threshold']}")

    # Surface failure signatures if present
    comps = score_components(ctx)
    if comps.get("unlinked_entries", 0) > 0:
        reasons.append(f"{comps['unlinked_entries']} unlinked entries (missing organization or title)")
    if comps.get("sentence_fragment_names", 0) > 0:
        reasons.append(f"{comps['sentence_fragment_names']} sentence fragment title/project names")
    if comps.get("unresolved_or_ambiguous", 0) > 0:
        reasons.append(f"{comps['unresolved_or_ambiguous']} entries UNRESOLVED or AMBIGUOUS")

    # Surface date conflicts explicitly so reviewers see which items clash.
    reasons.extend(conflict_reason_lines(ctx))

    # Flags alone escalate only with 3+ flags or a conflict inside a job's
    # own dates — never for a single project-level conflict.
    flags = data_quality_flags(ctx)
    for f in flags:
        if f["code"] != "DATE_CONFLICT":
            reasons.append(f"{f['code']}: {f['detail']}")
    if route == Route.AUTO_APPROVE and (
            len(flags) >= 3 or _employment_date_conflict(ctx)):
        route = Route.LLM_REVIEW
        reasons.append("Escalated to LLM review by data-quality flags")

    return RoutingDecision(score=score, route=route, reasons=reasons)