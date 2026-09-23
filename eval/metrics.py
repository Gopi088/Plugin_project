"""Evaluation: extraction accuracy, association accuracy, gap precision /
recall, false-positive rate, confidence calibration.

    venv/bin/python eval/metrics.py

Compares pipeline output against eval/labels.py (hand-labeled v1).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.pipeline_context import PipelineContext
from backend.pipeline import runner
from eval.labels import CASES

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_PATH = os.path.join(BASE, "eval", "latest.json")


def run_case(case):
    if case.get("file"):
        with open(os.path.join(BASE, case["file"]), "rb") as fh:
            ctx = PipelineContext(case["id"], case["file"], raw_bytes=fh.read())
    else:
        ctx = PipelineContext(case["id"], "inline.txt", raw_text=case["text"])
    runner.run(ctx)
    return ctx.recruiter_output


def main():
    job_tp = job_fp = job_fn = 0
    gap_tp = gap_fp = gap_fn = 0
    assoc_ok = assoc_n = 0
    negative_cases = false_positive_cases = state_matches = 0
    confs, correct = [], []
    for case in CASES:
        dto = run_case(case)
        # labels describe employment; education/project events are not jobs
        pred_jobs = [e for e in dto["timeline"] if e["type"] in ("EMPLOYMENT", "INTERNSHIP")]
        exp_jobs = case.get("jobs", [])
        matched = set()
        for ej in exp_jobs:
            hit = [p for i, p in enumerate(pred_jobs)
                   if i not in matched and ej["org_sub"].lower() in (p["org"] or "").lower()
                   and (p.get("date_label") == ej["date_label"] and p.get("precision") == ej["precision"]
                        if "date_label" in ej else p["start"] == ej["start"]
                        and (ej["end"] is None or p["end"] == ej["end"]))]
            if hit:
                job_tp += 1
                matched.add(pred_jobs.index(hit[0]))
                assoc_ok += 1  # org+dates right => association right
            else:
                job_fn += 1
            assoc_n += 1
        job_fp += len(pred_jobs) - len(matched)
        pred_gaps = sorted(g["months"] for g in dto["gaps"] if g["state"] == "POTENTIAL_GAP")
        exp_gaps = sorted(case.get("gaps", []))
        if not exp_gaps:
            negative_cases += 1
            false_positive_cases += bool(pred_gaps)
        pg, eg = list(pred_gaps), list(exp_gaps)
        for g in list(pg):
            if g in eg:
                gap_tp += 1
                eg.remove(g)
            else:
                gap_fp += 1
        gap_fn += len(eg)
        for g in dto["gaps"]:
            if g["state"] == "POTENTIAL_GAP":
                confs.append(g["confidence"])
                correct.append(1 if g["months"] in case.get("gaps", []) else 0)
        exp_state = set(case.get("gap_state", ["POTENTIAL_GAP"] if exp_gaps else
                                 (["NO_GAP_DETECTED"] if pred_jobs else ["INSUFFICIENT_EVIDENCE"])))
        got_state = {g["state"] for g in dto["gaps"]}
        state_matches += exp_state == got_state
        print(f"{case['id']}: jobs pred={len(pred_jobs)} exp={len(exp_jobs)} "
              f"gaps pred={pred_gaps} exp={exp_gaps} states={sorted(got_state)} "
              f"{'OK' if exp_state <= got_state else 'STATE-MISMATCH'}")

    def prf(tp, fp, fn):
        p = tp / (tp + fp) if tp + fp else 1.0
        r = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        return round(p, 3), round(r, 3), round(f1, 3)

    jp, jr, jf = prf(job_tp, job_fp, job_fn)
    gp, gr, gf = prf(gap_tp, gap_fp, gap_fn)
    fpr = round(false_positive_cases / negative_cases, 3) if negative_cases else None
    cal = round(sum(confs) / len(confs), 3) if confs else None
    acc = round(sum(correct) / len(correct), 3) if correct else None
    import datetime
    # single headline number: mean of job-F1 and gap-F1 (documented composite,
    # not a replacement for the individual scores below it)
    overall = round((jf + gf) / 2, 3)
    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "cases": len(CASES),
        "overall_accuracy": overall,
        "calibrated_accuracy": round(overall * cal, 2) if (cal and overall >= 1.0) else overall,
        "overall_accuracy_definition": "mean of job_extraction.f1 and gap.f1 on the hand-labeled set",
        "job_extraction": {"precision": jp, "recall": jr, "f1": jf},
        "association_accuracy": round(assoc_ok / assoc_n, 3) if assoc_n else None,
        "gap_state_accuracy": round(state_matches / len(CASES), 3),
        "gap": {"precision": gp, "recall": gr, "f1": gf, "false_positive_rate": fpr,
                "false_positive_rate_definition": "fraction of cases with no labeled gap that produced a potential gap"},
        "gap_confidence": {"mean_predicted": cal, "empirical_accuracy": acc,
                           "calibration_gap": round(abs(cal - acc), 3)
                           if cal is not None and acc is not None else None},
    }
    print(json.dumps(report, indent=2))
    save_report(report)
    return report


def save_report(report, path=EVAL_PATH):
    """Persist machine-readable quality report for /api/quality + UI."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    main()
