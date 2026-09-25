#!/usr/bin/env python3
"""Batch evaluation across dataset/resumes with route and component statistics."""
import sys
import os
import json
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.pipeline_context import PipelineContext
from backend.pipeline import runner
from backend.routing import score_components


def parse_one(file_path):
    path = Path(file_path)
    try:
        raw = path.read_bytes()
        ctx = PipelineContext("corpus", path.name, raw_bytes=raw)
        runner.run(ctx)
        dto = ctx.recruiter_output or {}
        routing = ctx.meta.get("routing", {})
        score = routing.get("score", 0)
        route = routing.get("route", "unknown")
        reasons = routing.get("reasons", [])
        comps = score_components(ctx)
        
        emp_count = sum(1 for e in ctx.events if e.type in ("EMPLOYMENT", "INTERNSHIP"))
        edu_count = sum(1 for e in ctx.events if e.type == "EDUCATION")
        proj_count = len(dto.get("projects", []))
        gap_count = len(dto.get("gaps", []))
        
        # Check column spread
        col_type = "single-column"
        raw_lines = ctx.raw_text.splitlines() if ctx.raw_text else []
        
        return {
            "name": path.name,
            "status": "OK",
            "score": score,
            "route": route,
            "reasons": reasons,
            "emp_count": emp_count,
            "edu_count": edu_count,
            "proj_count": proj_count,
            "gap_count": gap_count,
            "unlinked": comps.get("unlinked_entries", 0),
            "unresolved": comps.get("unresolved_or_ambiguous", 0),
            "fragments": comps.get("sentence_fragment_names", 0),
            "flags": comps.get("flags", []),
        }
    except Exception as exc:
        return {
            "name": path.name,
            "status": f"ERROR: {exc}",
            "score": 0,
            "route": "human_review",
            "reasons": [str(exc)],
            "emp_count": 0,
            "edu_count": 0,
            "proj_count": 0,
            "gap_count": 0,
            "unlinked": 0,
            "unresolved": 0,
            "fragments": 0,
            "flags": [],
        }


def main():
    resumes_dir = ROOT / "dataset" / "resumes"
    files = sorted([f for f in resumes_dir.rglob('*') if f.is_file()])
    print(f"Total files in {resumes_dir} (recursive): {len(files)}")
    
    t0 = time.time()
    results = []
    # Use ProcessPoolExecutor for speed
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(parse_one, f): f for f in files}
        for future in as_completed(futures):
            results.append(future.result())
            
    elapsed = time.time() - t0
    print(f"Parsed {len(results)} resumes in {elapsed:.2f}s ({elapsed/len(results):.2f}s/doc)")
    
    # Analyze results
    route_counts = Counter()
    total_emp = sum(r["emp_count"] for r in results)
    total_edu = sum(r["edu_count"] for r in results)
    total_proj = sum(r["proj_count"] for r in results)
    total_gaps = sum(r["gap_count"] for r in results)
    
    score_bins = {"<40 (Human)": 0, "40-59 (LLM)": 0, ">=60 (Auto)": 0}
    for r in results:
        s = r["score"]
        if s < 40:
            score_bins["<40 (Human)"] += 1
        elif s < 60:
            score_bins["40-59 (LLM)"] += 1
        else:
            score_bins[">=60 (Auto)"] += 1
        route_counts[r["route"]] += 1
        
    print("\n--- RESULTS SUMMARY ---")
    print(f"Total Resumes: {len(results)}")
    print(f"Total Employment Entries: {total_emp}")
    print(f"Total Education Entries: {total_edu}")
    print(f"Total Projects: {total_proj}")
    print(f"Total Gaps: {total_gaps}")
    print(f"\nScore Distribution:")
    for k, v in score_bins.items():
        print(f"  {k}: {v} ({v*100/len(results):.1f}%)")
    print(f"\nRoute Breakdown (with no live API key):")
    for k, v in route_counts.items():
        print(f"  {k}: {v} ({v*100/len(results):.1f}%)")
        
    out_file = ROOT / "corpus_verification_results.json"
    out_file.write_text(json.dumps(results, indent=2))
    print(f"\nDetailed results saved to {out_file}")


if __name__ == "__main__":
    main()
