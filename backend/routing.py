"""Overall confidence scoring & routing decision."""
import yaml
import logging
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Any, Optional
from . import evidence as EV

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

def _compute_stage_score(ctx) -> float:
    """Mean stage confidence."""
    stage_conf = [r.confidence for r in ctx.stage_results.values() if r.confidence > 0]
    return sum(stage_conf) / len(stage_conf) if stage_conf else 0.0

def _compute_event_score(ctx) -> float:
    """Weighted event confidence, penalizing weakest employment event."""
    events = ctx.recruiter_output.get("timeline", []) if isinstance(ctx.recruiter_output, dict) else []
    if not events:
        return 0.0
    
    weights = {"EMPLOYMENT": 1.5, "INTERNSHIP": 1.2, "EDUCATION": 1.0, "PROJECT": 0.8, "OTHER": 0.5}
    weighted_sum = sum(e.get("confidence", 0) * weights.get(e.get("type", "OTHER"), 0.5) for e in events)
    weight_total = sum(weights.get(e.get("type", "OTHER"), 0.5) for e in events)
    mean_event = weighted_sum / weight_total if weight_total else 0.0
    
    # Penalize weakest employment event
    employment_confidences = [e.get("confidence", 1) for e in events if e.get("type") in ("EMPLOYMENT", "INTERNSHIP")]
    if employment_confidences:
        weakest_employment = min(employment_confidences)
        # Blend mean with weakest (70% mean, 30% weakest)
        return 0.7 * mean_event + 0.3 * weakest_employment
    return mean_event

def _compute_gap_score(ctx) -> float:
    """Gap confidence (penalize unresolved gaps)."""
    gaps = ctx.recruiter_output.get("gaps", []) if isinstance(ctx.recruiter_output, dict) else []
    if not gaps:
        return 1.0
    gap_confs = [g.get("confidence", 0) for g in gaps if g.get("state") == "POTENTIAL_GAP"]
    return sum(gap_confs) / len(gap_confs) if gap_confs else 1.0

def _compute_doc_quality(ctx) -> float:
    """Document quality from stage 1."""
    doc_result = ctx.stage_results.get("document_processing")
    if not doc_result:
        return 0.5
    conf = doc_result.confidence
    reading_incomplete = ctx.meta.get("reading_incomplete", False)
    if reading_incomplete:
        conf *= 0.6
    return conf

def _has_ml_hint(ctx) -> bool:
    """Check if any ML hint was used."""
    events = ctx.recruiter_output.get("timeline", []) if isinstance(ctx.recruiter_output, dict) else []
    for e in events:
        for r in e.get("reasons", []):
            if "ML_HINT" in r or "SECTION_ML_HINT" in r:
                return True
    return False


_LOCATION_LIKE = {
    "bangalore", "bengaluru", "pune", "hyderabad", "chennai", "mumbai",
    "delhi", "kolkata", "india", "karnataka", "maharashtra", "telangana",
    "tamil nadu", "noida", "gurgaon", "gurugram", "kochi", "pune/bangalore",
}

_SECTION_WORDS = {"professional", "summary", "objective", "declaration"}


def _employment_field_quality(ctx) -> float:
    """Fraction of CONFIRMED employment events with plausible title AND org.

    Catches over-confident parses where dates are right but entities are
    wrong: empty titles, locations parsed as companies, date fragments or
    section words leaking into title/org. Returns 1.0 when there are no
    confirmed employment events (nothing to judge — e.g. freshers).
    """
    import re
    events = ctx.recruiter_output.get("timeline", []) if isinstance(ctx.recruiter_output, dict) else []
    confirmed = [e for e in events
                 if e.get("type") in ("EMPLOYMENT", "INTERNSHIP")
                 and e.get("status") == "CONFIRMED"]
    if not confirmed:
        return 1.0

    def _org_ok(org):
        o = (org or "").strip()
        if not o:
            return False
        # Must contain at least one letter (rejects glyphs/date fragments).
        if not re.search(r"[A-Za-z]", o):
            return False
        low = o.lower()
        if low in _LOCATION_LIKE:
            return False
        if any(w in low for w in ("education", "contact details")):
            return False
        # Reject verb/preposition leaks from header parsing
        # (e.g. org='Worked' from "... Developer in X ... Worked ...").
        if low in {"worked", "working", "employed", "with", "at", "in", "and",
                   "work", "works", "job", "role", "position"}:
            return False
        return True

    def _title_ok(title):
        t = (title or "").strip()
        if not t:
            return False
        low = t.lower()
        if _SECTION_WORDS & set(low.split()):
            return False
        return True

    good = sum(1 for e in confirmed
               if _title_ok(e.get("title")) and _org_ok(e.get("org")))
    return good / len(confirmed)


def compute_overall_confidence(ctx) -> int:
    """
    Compute 0-100 overall confidence from pipeline artifacts.
    """
    stage_score = _compute_stage_score(ctx)
    event_score = _compute_event_score(ctx)
    field_quality = _employment_field_quality(ctx)
    gap_score = _compute_gap_score(ctx)
    doc_quality = _compute_doc_quality(ctx)
    ml_hint = _has_ml_hint(ctx)

    overall = (
        0.25 * stage_score +
        0.30 * event_score +
        0.15 * field_quality +
        0.10 * gap_score +
        0.15 * doc_quality +
        0.05 * (1.0 if ml_hint else 0.0)
    )
    return round(max(0, min(100, overall * 100)))


def score_components(ctx) -> Dict[str, Any]:
    """Return per-component scores for diagnosis (0-1 each + overall 0-100)."""
    comp = {
        "stage_score": round(_compute_stage_score(ctx), 3),
        "event_score": round(_compute_event_score(ctx), 3),
        "field_quality": round(_employment_field_quality(ctx), 3),
        "gap_score": round(_compute_gap_score(ctx), 3),
        "doc_quality": round(_compute_doc_quality(ctx), 3),
        "ml_hint": _has_ml_hint(ctx),
    }
    comp["overall"] = compute_overall_confidence(ctx)
    return comp

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

    return RoutingDecision(score=score, route=route, reasons=reasons)