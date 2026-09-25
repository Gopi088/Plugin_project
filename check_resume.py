#!/usr/bin/env python3
"""Check a single resume through the parsing pipeline with routing.

Shows evidence-backed output:
- experience with date-label proof quotes
- projects from the DTO (client / role / duration as written in the resume)
- gaps with bounding events + month arithmetic
"""
import sys
import os
import re
import json
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

MONTH_MAP = {
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
    variants.append(f"{month}/{year}")
    variants.append(f"{year}-{month:02d}")
    variants.append(f"{month}-{year}")
    for name in MONTH_MAP.get(month, []):
        variants.append(f"{name} {year}")
        variants.append(f"{name}. {year}")
        variants.append(f"{name}-{year}")
    return variants

def _date_verified(raw_text, year, month):
    """Return True if any variant of the date appears in raw_text (case‑insensitive)."""
    text_lower = raw_text.lower()
    for fmt in _date_variants(year, month):
        if fmt.lower() in text_lower:
            return True
    # fallback: year only
    if str(year) in raw_text:
        return True
    return False

def parse_period(period_str):
    """Parse period strings like 'Dec 2023 - Present' or 'May 2022 - Nov 2023' into (start_year,start_month,end_year,end_month). Returns None if cannot parse."""
    if not period_str:
        return None
    period_str = period_str.strip()
    # Split by dash or 'to'
    parts = re.split(r'\s*[-–—]\s*|\s+to\s+', period_str, maxsplit=1)
    if len(parts) != 2:
        return None
    start_s, end_s = parts[0].strip(), parts[1].strip()
    month_map = {'jan':1,'january':1,'feb':2,'february':2,'mar':3,'march':3,'apr':4,'april':4,'may':5,'jun':6,'june':6,'jul':7,'july':7,'aug':8,'august':8,'sep':9,'sept':9,'september':9,'oct':10,'october':10,'nov':11,'november':11,'dec':12,'december':12}
    def parse_one(s):
        s = s.strip().lower()
        # handle 'present', 'till now', etc.
        if s in ('present','till now','current','ongoing','till date'):
            now = datetime.now()
            return now.year, now.month
        # try "Mon YYYY" or "Month YYYY"
        tokens = s.split()
        if len(tokens) >= 2:
            mon = tokens[0][:3]
            yr = tokens[1]
            if mon in month_map and yr.isdigit():
                return int(yr), month_map[mon]
        # try "YYYY"
        if s.isdigit() and len(s)==4:
            return int(s), 1
        return None
    start = parse_one(start_s)
    end = parse_one(end_s)
    if start and end:
        return (start[0], start[1], end[0], end[1])
    return None

def compute_gaps_from_experience(exp_list):
    """Given list of experience dicts with 'years' field, compute gaps in months between consecutive jobs."""
    intervals = []
    for exp in exp_list:
        period = exp.get('years') or exp.get('duration') or ''
        parsed = parse_period(period)
        if parsed:
            intervals.append(parsed)
    # sort by start date
    intervals.sort(key=lambda x: (x[0], x[1]))
    gaps = []
    for i in range(len(intervals)-1):
        _, _, end_y, end_m = intervals[i]
        next_sy, next_sm, _, _ = intervals[i+1]
        # compute months difference
        months = (next_sy - end_y)*12 + (next_sm - end_m) - 1
        if months > 0:
            gaps.append({
                'months': months,
                'before': intervals[i],
                'after': intervals[i+1]
            })
    return gaps

def compute_verified_gaps_from_experience(exp_list, raw_text):
    """Compute gaps using only experience entries whose start and end dates are both verified in raw_text."""
    verified_intervals = []
    for exp in exp_list:
        period = exp.get('years') or exp.get('duration') or ''
        parsed = parse_period(period)
        if not parsed:
            continue
        sy, sm, ey, em = parsed
        start_ok = _date_verified(raw_text, sy, sm)
        end_ok = _date_verified(raw_text, ey, em)
        if start_ok and end_ok:
            verified_intervals.append(parsed)
    verified_intervals.sort(key=lambda x: (x[0], x[1]))
    gaps = []
    for i in range(len(verified_intervals)-1):
        _, _, end_y, end_m = verified_intervals[i]
        next_sy, next_sm, _, _ = verified_intervals[i+1]
        months = (next_sy - end_y)*12 + (next_sm - end_m) - 1
        if months > 0:
            gaps.append({
                'months': months,
                'before': verified_intervals[i],
                'after': verified_intervals[i+1]
            })
    return gaps

sys.path.insert(0, '.')
from backend.pipeline_context import PipelineContext
from backend.pipeline import runner
from backend.routing import score_components, conflict_reason_lines
from backend.resume_matcher import parse_with_api, is_available, api_base

if len(sys.argv) < 2:
    print("Usage: python check_resume.py <resume_file>")
    print("Example: python check_resume.py dataset/resumes/M\\ Lipsa.docx")
    sys.exit(1)

filepath = sys.argv[1]
if not os.path.exists(filepath):
    print(f"File not found: {filepath}")
    sys.exit(1)

print(f"Processing: {filepath}")
with open(filepath, 'rb') as f:
    raw_bytes = f.read()

# Track parsing source for logging
parsing_log = {
    "ml_model_used": False,
    "ml_model_confidence": 0.0,
    "llm_used": False,
    "llm_confidence": 0.0,
    "pipeline_used": False,
    "pipeline_score": 0,
    "fallback_reason": None
}

# Try local API (ML model) first
ml_result = None
if is_available():
    logger.info(f"Local API available at {api_base()}, attempting ML parsing...")
    ml_result = parse_with_api(raw_bytes, filepath)
    if ml_result:
        parsing_log["ml_model_used"] = True
        parsing_log["ml_model_confidence"] = ml_result.get('confidence', 0.9)
        logger.info(f"ML model parsing succeeded with confidence {parsing_log['ml_model_confidence']}")
    else:
        parsing_log["fallback_reason"] = "ML model returned no result"
        logger.warning("ML model returned no result, falling back to pipeline")
else:
    parsing_log["fallback_reason"] = "Local API not available"
    logger.warning(f"Local API not available at {api_base()}, falling back to pipeline")

# If ML model succeeded with high confidence, use it
if ml_result and parsing_log["ml_model_confidence"] >= 0.75:
    dto = ml_result
    parsing_log["pipeline_used"] = False
    logger.info("Using ML model result (high confidence)")
    
    # Run verification on ML result for true accuracy
    logger.info("Running verification on ML result...")
    ctx = PipelineContext('check', filepath, raw_bytes=raw_bytes)
    from backend.pipeline import stages as S
    S.s01_document_processing(ctx)
    S.s02_text_representation(ctx)
    S.s03_section_detection(ctx)
    S.s04_entry_segmentation(ctx)
    S.s05_date_extraction(ctx)
    S.s06_date_association(ctx)
    S.s07_event_classification(ctx)
    S.s08_timeline_reconciliation(ctx)
    S.s09_coverage_analysis(ctx)
    S.s10_gap_detection(ctx)
    S.s11_confidence_evidence(ctx)
    S.s12_recruiter_output(ctx)
    S.s13_verification(ctx)
    
    # Merge ML result with verification
    dto['verification'] = ctx.recruiter_output.get('verification', {})
    parsing_log["verification_metrics"] = ctx.verification_metrics
    parsing_log["verified_gaps"] = ctx.verified_gaps
    parsing_log["verified_events"] = ctx.verified_events
    # Compute verified gaps from ML experience for consistent reporting
    ml_exp = dto.get('workExperience', [])
    parsing_log["verified_gaps_ml"] = compute_verified_gaps_from_experience(ml_exp, ctx.raw_text)
    parsing_log["pipeline_score"] = int(parsing_log["ml_model_confidence"] * 100)
else:
    # Fall back to 12-stage pipeline
    logger.info("Running 12-stage deterministic pipeline...")
    ctx = PipelineContext('check', filepath, raw_bytes=raw_bytes)
    runner.run(ctx)
    dto = ctx.recruiter_output or {}
    parsing_log["pipeline_used"] = True
    parsing_log["pipeline_score"] = dto.get('quality', {}).get('document_accuracy', 0) * 100
    
    # Check if we need LLM fallback
    routing = ctx.meta.get('routing', {})
    score = routing.get('score', 0)
    route = routing.get('route', 'unknown')
    
    if score < 60 and score >= 40:
        parsing_log["llm_used"] = True
        parsing_log["llm_confidence"] = routing.get('llm_confidence', 0.7)
        logger.info(f"Score {score} < 60, LLM fallback used (confidence: {parsing_log['llm_confidence']})")
    elif score < 40:
        parsing_log["fallback_reason"] = f"Score {score} < 40, human review required"
        logger.warning(f"Score {score} < 40, human review required")

# Log parsing breakdown
logger.info(f"Parsing breakdown: ML={parsing_log['ml_model_used']}({parsing_log['ml_model_confidence']:.0%}), "
           f"Pipeline={parsing_log['pipeline_used']}({parsing_log['pipeline_score']:.0f}), "
           f"LLM={parsing_log['llm_used']}({parsing_log['llm_confidence']:.0%})")

# Print parsing log (for debugging)
print(f"\n{'='*60}")
print(f"PARSING LOG (ML vs LLM vs Pipeline):")
print(f"  ML Model Used: {parsing_log['ml_model_used']} (confidence: {parsing_log['ml_model_confidence']:.0%})")
print(f"  Pipeline Used: {parsing_log['pipeline_used']} (score: {parsing_log['pipeline_score']:.0f})")
print(f"  LLM Used: {parsing_log['llm_used']} (confidence: {parsing_log['llm_confidence']:.0%})")
if parsing_log['fallback_reason']:
    print(f"  Fallback Reason: {parsing_log['fallback_reason']}")
print(f"{'='*60}")

# Get routing info (from pipeline or defaults)
routing = {}
# If we have verification metrics, base score on true accuracy
if parsing_log.get('verification_metrics'):
    vm = parsing_log['verification_metrics']
    field_avg = sum(vm['field_accuracy'].values())/len(vm['field_accuracy']) if vm['field_accuracy'] else 0
    score = int((vm['precision']*0.7 + field_avg*0.3)*100)
    route = 'auto_approve' if score >= 60 else ('llm_review' if score >= 40 else 'human_review')
    reasons = [f"Verification precision {vm['precision']:.0%}", f"Field accuracy {field_avg:.0%}"]
    routing = {'llm_unavailable': False, 'llm_validation_failed': False}
elif parsing_log['pipeline_used']:
    routing = ctx.meta.get('routing', {})
    score = routing.get('score', 0)
    route = routing.get('route', 'unknown')
    reasons = routing.get('reasons', [])
else:
    # ML model path without verification (should not happen now)
    ml_score = int(parsing_log['ml_model_confidence'] * 100)
    score = ml_score
    route = 'auto_approve' if ml_score >= 60 else ('llm_review' if ml_score >= 40 else 'human_review')
    reasons = ['ML model confidence']
    routing = {'llm_unavailable': False, 'llm_validation_failed': False}

print(f"\nFILE: {os.path.basename(filepath)}")
print(f"SCORE: {score}/100")
print(f"ROUTE: {route}")
print(f"REASONS: {reasons}")

print(f"\nSTATUS: {dto.get('status', 'SUCCESS' if not parsing_log['pipeline_used'] else 'PARTIAL')}")

# Display results based on source
if not parsing_log['pipeline_used'] and 'workExperience' in dto:
    # ML model result format
    print(f"\nEXPERIENCE (from ML Model):")
    for exp in dto.get('workExperience', []):
        years = exp.get('years', '')
        print(f"  ✓ {exp.get('title')} @ {exp.get('company')} ({years})")
    
    print(f"\nEDUCATION (from ML Model):")
    for edu in dto.get('education', []):
        years = edu.get('years', '')
        print(f"  ✓ {edu.get('degree')} @ {edu.get('institution')} ({years})")
    
    print(f"\nPROJECTS (from ML Model):")
    projects = dto.get('personalProjects', [])
    if projects:
        for pr in projects:
            print(f"  - {pr.get('name')}: {pr.get('description', '')[:80]}")
    else:
        print("  None")
    
else:
    # Pipeline result format (existing code)
    # Score components (without readability for manager view)
    if parsing_log['pipeline_used']:
        comp = score_components(ctx)
    print(f"\nSCORE COMPONENTS (0-1 each, overall 0-100):")
    for key in ("event_score", "field_grounding", "dates_share",
                "ml_agreement", "weakest_employment",
                "flags", "flag_penalty_points", "conflict_events", "overall"):
        print(f"  {key}: {comp.get(key)}")
    dbg = ctx.meta.get("routing_debug") or {}
    if dbg.get("flag_penalty_points"):
        print(f"  flag_penalty: {dbg['flag_penalty_points']}pts (cap: 5)")

    conflicts = conflict_reason_lines(ctx)
    if conflicts:
        print(f"\nDATE CONFLICTS:")
        for line in conflicts:
            print(f"  {line}")

    print(f"\nEXPERIENCE:")
    # Show from DTO timeline (cleaner, deduplicated)
    for event in dto.get('timeline', []):
        if event.get('type') in ('EMPLOYMENT', 'INTERNSHIP'):
            icon = '✓' if event.get('status') == 'CONFIRMED' else '✗'
            print(f"  {icon} org={event.get('org','')!r} | title={event.get('title','')!r} | {event.get('start')}–{event.get('end')} [{event.get('status')}] conf={event.get('confidence'):.2f}")

    print(f"\nEDUCATION:")
    for event in dto.get('timeline', []):
        if event.get('type') == 'EDUCATION':
            icon = '✓' if event.get('status') == 'CONFIRMED' else '✗'
            print(f"  {icon} org={event.get('org','')} | title={event.get('title','')} | {event.get('start')}–{event.get('end')} [{event.get('status')}] conf={event.get('confidence'):.2f}")

    print(f"\nPROJECTS:")
    for pr in dto.get('projects', []):
        print(f"  {pr['id']}: name={pr['name'][:65]!r} client={pr['client']!r} role={pr['role'][:32]!r} duration={pr['duration']!r}")

    print(f"\nGAPS:")
    by_ev = ctx.events_by_id() if parsing_log['pipeline_used'] else {}
    for g in dto.get('gaps', []):
        print(f"  {g.get('state')} | {g.get('months')} months | {g.get('start_label', g.get('start'))}..{g.get('end_label', g.get('end'))} | conf={g.get('confidence')} | reasons={g.get('reasons')}")
        ev = g.get('evidence', {}) or {}
        print(f"    coverage_scope: {ev.get('coverage_scope')}")
        for key in ('event_before', 'event_after'):
            eid = ev.get(key)
            if eid and eid in by_ev:
                evinfo = by_ev[eid]
                print(f"    {key}: {evinfo.title!r} @ {evinfo.org!r} ({evinfo.start}-{evinfo.end}) [{evinfo.status}] label={evinfo.date_label!r}")

print(f"\nROUTING DECISION:")
print(f"  Score: {score}/100")
print(f"  Route: {route}")
if routing.get('llm_unavailable'):
    print(f"  Note: LLM unavailable, fell back to human review")
if routing.get('llm_validation_failed'):
    print(f"  Note: LLM output failed validation")

# Verification results (true accuracy)
verification_metrics = parsing_log.get('verification_metrics') or (ctx.verification_metrics if hasattr(ctx, 'verification_metrics') else None)
verified_events_list = parsing_log.get('verified_events') or (ctx.verified_events if hasattr(ctx, 'verified_events') else None)

# Compute verified gaps from verified events (employment only, both dates verified)
def compute_verified_gaps_from_verified_events(verified_events):
    """Compute gaps from verified employment events (both start and end verified)."""
    dated = []
    for ve in verified_events:
        e = ve['event']
        v = ve['verified']
        if e.type == 'EMPLOYMENT' and v.get('start_verified') and v.get('end_verified') and e.start and e.end:
            dated.append(e)
    dated.sort(key=lambda e: (e.end[0]*12 + e.end[1]) if e.end else 0)
    gaps = []
    for i in range(len(dated)-1):
        curr = dated[i]
        nxt = dated[i+1]
        if curr.end and nxt.start:
            months = (nxt.start[0]*12 + nxt.start[1]) - (curr.end[0]*12 + curr.end[1]) - 1
            if months > 0:
                gaps.append({
                    'months': months,
                    'before_end': curr.end,
                    'after_start': nxt.start,
                    'before_title': curr.title,
                    'after_title': nxt.title,
                })
    return gaps

verified_gaps = compute_verified_gaps_from_verified_events(verified_events_list) if verified_events_list else []

if verification_metrics:
    vm = verification_metrics
    print(f"\n{'='*60}")
    print(f"VERIFICATION (True Accuracy vs Source Text):")
    print(f"  Precision: {vm['precision']:.0%} ({vm['verified_events']}/{vm['total_events']} events fully verified)")
    print(f"  Field Accuracy:")
    for field, acc in vm['field_accuracy'].items():
        print(f"    {field}: {acc:.0%}")
    
    # Show event verification details
    if verified_events_list:
        print(f"\n  Event Verification:")
        for ve in verified_events_list:
            v = ve['verified']
            e = ve['event']
            status = []
            if v['title_verified']: status.append('title✓')
            else: status.append('title✗')
            if v['org_verified']: status.append('org✓')
            else: status.append('org✗')
            if v['start_verified']: status.append('start✓')
            else: status.append('start✗')
            if v['end_verified']: status.append('end✓')
            else: status.append('end✗')
            print(f"    {e.title} @ {e.org}: {' '.join(status)}")
    
    # Verified gaps
    if verified_gaps:
        print(f"\n  Verified Gaps (from verified timeline):")
        for g in verified_gaps:
            before_end = g['before_end']
            after_start = g['after_start']
            # ensure ints
            try:
                b_month = int(before_end[1])
                b_year = int(before_end[0])
                a_month = int(after_start[1])
                a_year = int(after_start[0])
            except Exception:
                b_month = b_year = a_month = a_year = 0
            print(f"    {g['months']} months gap between {b_month:02d}/{b_year} – {a_month:02d}/{a_year}")
    elif verified_gaps is not None:
        print(f"\n  Verified Gaps: None (continuous verified employment)")
    
print(f"{'='*60}")

# GAPS (use verified gaps if available)
if verification_metrics and verified_gaps:
    gaps_to_show = verified_gaps
    source_label = " (verified)"
else:
    ml_exp = dto.get('workExperience', [])
    gaps_to_show = compute_gaps_from_experience(ml_exp)
    source_label = ""
if gaps_to_show:
    print(f"\nGAPS{source_label}:")
    for g in gaps_to_show:
        if 'before_end' in g:
            before_end = g['before_end']
            after_start = g['after_start']
            b_month = int(before_end[1]); b_year = int(before_end[0])
            a_month = int(after_start[1]); a_year = int(after_start[0])
        else:
            before = g['before']; after = g['after']
            b_month = int(before[3]); b_year = int(before[2])
            a_month = int(after[1]); a_year = int(after[0])
        print(f"  {g['months']} months gap between {b_month:02d}/{b_year} – {a_month:02d}/{a_year}")
else:
    print(f"\nGAPS: None (continuous employment)")

print(f"\nROUTING DECISION:")
