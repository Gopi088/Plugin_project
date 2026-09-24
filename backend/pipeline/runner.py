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
    return ctx
