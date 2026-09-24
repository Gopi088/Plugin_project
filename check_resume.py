#!/usr/bin/env python3
"""Check a single resume through the 12-stage pipeline with routing.

Shows evidence-backed output:
- experience with date-label proof quotes
- projects from the DTO (client / role / duration as written in the resume)
- gaps with bounding events + month arithmetic
"""
import sys
sys.path.insert(0, '.')
from backend.pipeline_context import PipelineContext
from backend.pipeline import runner
import os

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
    ctx = PipelineContext('check', filepath, raw_bytes=f.read())

runner.run(ctx)
dto = ctx.recruiter_output or {}

routing = ctx.meta.get('routing', {})
score = routing.get('score', 0)
route = routing.get('route', 'unknown')
reasons = routing.get('reasons', [])

print(f"\n{'='*60}")
print(f"FILE: {os.path.basename(filepath)}")
print(f"SCORE: {score}/100")
print(f"ROUTE: {route}")
print(f"REASONS: {reasons}")
print(f"{'='*60}")

print(f"\nSTATUS: {dto.get('status')}")

print(f"\nEXPERIENCE (title empty = no title in source line; never invented):")
for e in ctx.events:
    if e.type in ('EMPLOYMENT', 'INTERNSHIP'):
        icon = '✓' if e.status == 'CONFIRMED' else '✗'
        print(f"  {icon} org={e.org!r} | title={e.title!r} | {e.start}–{e.end} [{e.status}] conf={e.confidence:.2f} label={e.date_label!r}")

print(f"\nEDUCATION:")
for e in ctx.events:
    if e.type == 'EDUCATION':
        icon = '✓' if e.status == 'CONFIRMED' else '✗'
        print(f"  {icon} {e.org} | {e.title} | {e.start}–{e.end} [{e.status}] conf={e.confidence:.2f}")

print(f"\nPROJECTS (from resume text, with client/role/duration as written):")
for pr in dto.get('projects', []):
    print(f"  {pr['id']}: name={pr['name'][:65]!r} client={pr['client']!r} role={pr['role'][:32]!r} duration={pr['duration']!r}")

print(f"\nGAPS (with bounding-event proof):")
by_ev = ctx.events_by_id()
for g in dto.get('gaps', []):
    print(f"  {g.get('state')} | {g.get('months')} months | {g.get('start_label', g.get('start'))}..{g.get('end_label', g.get('end'))} | conf={g.get('confidence')}")
    ev = g.get('evidence', {}) or {}
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
