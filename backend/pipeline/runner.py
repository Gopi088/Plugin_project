"""Pipeline runner: executes the 12 stages in order with failure handling.

Rules:
  - stages run in STAGES order; each records its StageResult on the context.
  - FAILED stage 1/2 -> all remaining stages are SKIPPED (nothing to process).
  - FAILED elsewhere -> downstream stages that need its output are SKIPPED,
    the rest run (best-effort PARTIAL result, never a crash).
  - unexpected exceptions become FAILED with the error captured.
"""

from .. import datamodel as M
from . import stages as S
from ..routing import decide_route, Route
from ..llm_fallback import get_provider, LLMRequest, _merge_corrections, _validate_llm_output, _identify_low_confidence_fields

# stage -> prerequisite stages whose FAILED status forces a SKIP
_PREREQ = {
    "text_representation": ("document_processing",),
    "section_detection": ("text_representation",),
    "entry_segmentation": ("section_detection",),
    "date_extraction": ("entry_segmentation", "text_representation"),
    "date_association": ("date_extraction",),
    "event_classification": ("date_association",),
    "timeline_reconciliation": ("event_classification",),
    "coverage_analysis": ("timeline_reconciliation",),
    "gap_detection": ("coverage_analysis", "timeline_reconciliation"),
    "confidence_evidence": ("gap_detection",),
    "recruiter_output": ("gap_detection",),
    "verification": ("recruiter_output",),
}


def _skipped(name, reason):
    return M.StageResult(name, status="SKIPPED", confidence=0.0, errors=[reason])


def run(ctx):
    blocked = set()
    for fn in S.STAGE_FUNCS:
        name = fn.__name__[4:]  # s01_document_processing -> document_processing
        prereq_failed = [p for p in _PREREQ.get(name, ())
                         if p in blocked or p not in ctx.stage_results]
        if prereq_failed:
            blocked.add(name)
            ctx.stage_results[name] = _skipped(
                name, f"skipped: prerequisite failed ({', '.join(prereq_failed)})")
            continue
        try:
            res = fn(ctx)
        except Exception as exc:  # last-resort guard; stages handle their own errors
            res = M.StageResult(name, status="FAILED", confidence=0.0,
                                errors=[f"unexpected {type(exc).__name__}: {exc}"])
        ctx.stage_results[name] = res
        if res.status == "FAILED":
            blocked.add(name)
    
    # After all stages, apply confidence-based routing
    _apply_routing(ctx)
    return ctx


def _apply_routing(ctx):
    """Apply confidence-based routing after all pipeline stages."""
    from ..routing import decide_route, Route
    
    decision = decide_route(ctx)
    
    # Log routing decision
    ctx.meta["routing"] = {
        "score": decision.score,
        "route": decision.route.value,
        "reasons": decision.reasons
    }
    
    # Execute routing
    if decision.route == Route.LLM_REVIEW:
        provider = get_provider()
        if provider.is_available():
            low_fields = _identify_low_confidence_fields(ctx.recruiter_output)
            request = LLMRequest(
                resume_text=ctx.raw_text,
                extracted_json=ctx.recruiter_output,
                low_confidence_fields=low_fields,
                overall_score=decision.score
            )
            try:
                llm_response = provider.review(request)

                # Validate LLM output against resume text
                if not _validate_llm_output(llm_response.corrected_json, ctx.raw_text):
                    ctx.meta["routing"]["llm_validation_failed"] = True
                    decision.route = Route.HUMAN_REVIEW
                else:
                    # Merge corrections (only allowlisted low-confidence fields),
                    # tag provenance, keep originals, then re-validate merged DTO.
                    merged, applied = _merge_corrections(
                        ctx.recruiter_output, llm_response.corrected_json, low_fields)
                    if not _validate_llm_output(merged, ctx.raw_text):
                        ctx.meta["routing"]["llm_validation_failed"] = True
                        decision.route = Route.HUMAN_REVIEW
                    else:
                        ctx.recruiter_output = merged
                        ctx.meta["routing"]["llm_applied"] = True
                        ctx.meta["routing"]["llm_changes"] = applied
                        ctx.meta["routing"]["llm_provider_changes"] = llm_response.changes_made
                        ctx.meta["routing"]["llm_confidence"] = llm_response.confidence
            except Exception as e:
                ctx.meta["routing"]["llm_error"] = str(e)
                decision.route = Route.HUMAN_REVIEW
        else:
            ctx.meta["routing"]["llm_unavailable"] = True
            decision.route = Route.HUMAN_REVIEW
    
    if decision.route == Route.HUMAN_REVIEW:
        ctx.meta["routing"]["needs_human_review"] = True
        if isinstance(ctx.recruiter_output, dict):
            ctx.recruiter_output["needs_review"] = True
        ctx.meta["routing"]["route"] = "human_review"
