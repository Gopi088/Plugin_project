#!/usr/bin/env python3
"""Generate score vs accuracy table for labeled cases."""
import sys, os
sys.path.insert(0, '.')

from backend.pipeline_context import PipelineContext
from backend.pipeline import runner
from backend.routing import compute_overall_confidence, decide_route, Route
from eval.labels import CASES

BASE = os.path.dirname(os.path.abspath(__file__))

print("Case\t\tScore\tRoute\t\tExpectedJobs\tFoundJobs\tAcc")
for case in CASES:
    if case.get('file'):
        path = os.path.join(os.path.dirname(BASE), case['file'])
        if not os.path.exists(path):
            # fallback
            path = os.path.join(BASE, 'dataset', os.path.basename(case['file']))
        with open(path, 'rb') as f:
            ctx = PipelineContext(case['id'], case['file'], raw_bytes=f.read())
    else:
        ctx = PipelineContext(case['id'], 'inline.txt', raw_text=case.get('text',''))
    runner.run(ctx)
    
    score = compute_overall_confidence(ctx)
    decision = decide_route(ctx)
    
    expected = case.get('jobs', [])
    found = [(e.org, e.title, e.start, e.end) for e in ctx.events if e.type in ('EMPLOYMENT','INTERNSHIP')]
    matched = 0
    for exp in expected:
        exp_org = exp.get('org_sub','').lower()
        for f in found:
            if exp_org in (f[0] or '').lower():
                matched += 1
                break
    acc = matched / len(expected) if expected else 1.0
    
    print(f'{case["id"]}\t{score}\t{decision.route.value}\t{len(expected)}\t{len(found)}\t{acc:.2f}')