import sys
import json
from pathlib import Path

sys.path.insert(0, '.')
from backend.pipeline_context import PipelineContext
from backend.pipeline import runner

if len(sys.argv) < 2:
    print("Usage: python check_resume.py <resume_file>")
    sys.exit(1)

filepath = sys.argv[1]
if filepath.endswith('.json'):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    text = data.get('text', '') if isinstance(data, dict) else ''
    fname = data.get('filename', filepath) if isinstance(data, dict) else filepath
    ctx = PipelineContext('check', fname, raw_text=text)
else:
    with open(filepath, 'rb') as f:
        ctx = PipelineContext('check', filepath, raw_bytes=f.read())

runner.run(ctx)

def format_period(e):
    if e.start and e.end:
        s = f"{e.start[0]}-{e.start[1]:02d}" if len(e.start) >= 2 else str(e.start[0])
        if getattr(e, 'is_present', False):
            end = "Present"
        else:
            end = f"{e.end[0]}-{e.end[1]:02d}" if len(e.end) >= 2 else str(e.end[0])
        return f"{s} to {end}"
    if getattr(e, 'date_label', None):
        return e.date_label
    return "No Date Detected"

print(f"\n{'='*75}")
print(f"  📄 RESUME TIMELINE INSPECTION REPORT: {filepath}")
print(f"{'='*75}")
print(f"Overall Status: {ctx.recruiter_output.get('status', 'UNKNOWN')}\n")

# 1. Work Experience & Internships
work_events = [e for e in ctx.events if e.type in ('EMPLOYMENT', 'INTERNSHIP')]
print(f"💼 WORK EXPERIENCE & INTERNSHIPS ({len(work_events)} entries):")
if not work_events:
    print("   [!] No employment or internship entries detected.")
else:
    for i, e in enumerate(work_events, 1):
        icon = '✓' if e.status == 'CONFIRMED' else ('?' if e.status == 'AMBIGUOUS' else '✗')
        period = format_period(e)
        role = e.title or "(Unspecified Role)"
        company = e.org or "(Unspecified Company)"
        print(f"  {icon} [{e.type[:3]}] {role} @ {company}")
        print(f"       Period: {period} | Status: {e.status}")

# 2. Education
edu_events = [e for e in ctx.events if e.type == 'EDUCATION']
print(f"\n🎓 EDUCATION ({len(edu_events)} entries):")
if not edu_events:
    print("   [!] No education entries detected.")
else:
    for i, e in enumerate(edu_events, 1):
        icon = '✓' if e.status == 'CONFIRMED' else ('?' if e.status == 'AMBIGUOUS' else '✗')
        period = format_period(e)
        degree = e.title or "(Unspecified Degree)"
        inst = e.org or "(Unspecified Institution)"
        print(f"  {icon} {degree} @ {inst}")
        print(f"       Period: {period} | Status: {e.status}")

# 3. Projects
proj_events = [e for e in ctx.events if e.type == 'PROJECT']
raw_projs = ctx.recruiter_output.get('projects', [])
print(f"\n🚀 PROJECTS & RESEARCH ({len(proj_events) or len(raw_projs)} entries):")
if not proj_events and not raw_projs:
    print("   [!] No project entries detected.")
elif proj_events:
    for i, e in enumerate(proj_events, 1):
        icon = '✓' if e.status == 'CONFIRMED' else ('?' if e.status == 'AMBIGUOUS' else '✗')
        period = format_period(e)
        title = e.title or "(Untitled Project)"
        client_org = f" @ {e.org}" if e.org else ""
        print(f"  {icon} {title}{client_org}")
        print(f"       Period: {period} | Status: {e.status}")
else:
    for i, p in enumerate(raw_projs, 1):
        dur = p.get('duration') or "No Date Detected"
        name = p.get('name') or "Project"
        client = f" @ {p.get('client')}" if p.get('client') else ""
        print(f"  ✓ {name}{client}")
        print(f"       Period: {dur} | Status: CONFIRMED")

# Summary
print(f"\n{'-'*75}")
print(f"SUMMARY COUNTS:")
print(f"  • Confirmed Experience: {len([e for e in work_events if e.status == 'CONFIRMED'])}/{len(work_events)}")
print(f"  • Confirmed Education:  {len([e for e in edu_events if e.status == 'CONFIRMED'])}/{len(edu_events)}")
print(f"  • Projects Extracted:   {len(proj_events) or len(raw_projs)}")
print(f"{'='*75}\n")
