#!/usr/bin/env python3
r"""Check individual resume accuracy score, extracted timeline, projects, and diagnostics.

Usage:
    ./check_resume_score "Abhishek Barnwa"
    ./check_resume_score "A.Bhargava"
    ./check_resume_score dataset/resumes/resumes/Abhishek\ Barnwa.pdf
"""

import json
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = BASE_DIR / "model_parsed_periods"
if not MODEL_DIR.is_dir():
    MODEL_DIR = BASE_DIR / "model_parsed_1500_audited"
LOCAL_RAW = BASE_DIR / "reference_raw_json"
RAW_DIR = LOCAL_RAW if LOCAL_RAW.is_dir() else Path("/home/gopal/resume-timeline-test/json_results")

# Import diagnostic logic from analyze_tiers
sys.path.insert(0, str(BASE_DIR))
from scripts.analyze_tiers import diagnose_resume, normalize_key


def format_date_range(event):
    start = event.get("start_date") or event.get("start") or "?"
    end = event.get("end_date") or event.get("end") or ("Present" if event.get("is_current") else "?")
    if isinstance(start, list):
        start = f"{start[0]}-{start[1]:02d}" if len(start) >= 2 else str(start[0])
    if isinstance(end, list):
        end = f"{end[0]}-{end[1]:02d}" if len(end) >= 2 else str(end[0])
    return f"{start} to {end}"


def display_resume_diagnostic(filename, model_data, raw_text=""):
    diag = diagnose_resume(filename, model_data, raw_text)
    score_pct = int(diag["score"] * 100)
    tier = diag["tier"]
    
    tier_badge = "🟢 HIGH TIER" if tier == "HIGH" else ("🟡 MEDIUM TIER" if tier == "MEDIUM" else "🔴 LOW TIER")
    
    work_exp = model_data.get("work_experience", [])
    projects = model_data.get("projects", [])
    education = model_data.get("education", [])
    gaps = model_data.get("gaps", [])
    unresolved = model_data.get("raw_pipeline_dto", {}).get("unresolved_events", [])
    cand_name = model_data.get("candidate_name") or model_data.get("raw_pipeline_dto", {}).get("candidate_name", "")

    print("\n" + "=" * 72)
    print(f"  📄 RESUME PERIOD COVERAGE REPORT")
    print("=" * 72)
    print(f"  Candidate Name:    {cand_name or 'N/A'}")
    print(f"  File Name:         {filename}")
    print(f"  Dated periods:    {score_pct}%  [{tier_badge}]")
    print(f"  Category:          {diag['category']}")
    print(f"  Status:            {model_data.get('status', 'N/A')}")
    print("=" * 72)

    print("\n  🔍 DIAGNOSTIC ASSESSMENT:")
    print(f"  • Issue Diagnosed: {diag['problem']}")
    if diag.get("dates_found_in_text") > 0 and not (work_exp or projects or education):
        print(f"  • ⚠️  Alert: {diag['dates_found_in_text']} calendar years found in text, but no timeline entries segmented!")
    if diag.get("headings_found"):
        print(f"  • Headings in text: {', '.join(diag['headings_found'][:5])}")

    print("\n  💼 WORK EXPERIENCE TIMELINE EXTRACTED (" + str(len(work_exp)) + " items):")
    if not work_exp:
        print("    [!] No employment entries extracted.")
    else:
        for i, w in enumerate(work_exp, 1):
            title = w.get("title") or "Unknown Title"
            company = w.get("company") or "Unknown Company"
            date_range = format_date_range(w)
            status = w.get("status") or ("CURRENT" if w.get("is_current") else "CONFIRMED")
            conf = w.get("confidence")
            conf_str = f"(Conf: {int(conf*100)}%)" if conf else ""
            print(f"    {i:2d}. {title} @ {company}")
            print(f"        Dates: {date_range} | Status: {status} {conf_str}")

    print("\n  🎓 EDUCATION EXTRACTED (" + str(len(education)) + " items):")
    if not education:
        print("    [!] No education entries extracted.")
    else:
        for i, ed in enumerate(education, 1):
            deg = ed.get("title") or ed.get("degree") or "Unspecified Degree"
            inst = ed.get("company") or ed.get("institution") or "Unspecified Institution"
            date_range = format_date_range(ed)
            st = ed.get("status") or "CONFIRMED"
            print(f"    {i:2d}. {deg} @ {inst}")
            print(f"        Dates: {date_range} | Status: {st}")

    if projects:
        print(f"\n  🚀 PROJECTS EXTRACTED ({len(projects)} items):")
        for i, p in enumerate(projects, 1):
            p_name = p.get("name") or "Unnamed Project"
            p_dur = p.get("duration") or ""
            dur_str = f" | Period: {p_dur}" if p_dur else " | Period: No Date Detected"
            client_str = f" @ {p.get('client')}" if p.get('client') else ""
            print(f"    {i:2d}. {p_name}{client_str}")
            print(f"       {dur_str}")

    print("\n  PERIOD CHECKS (date availability, not accuracy):")
    for category, group in diag['period_analysis']['categories'].items():
        print(f"    {category}: {group['dated_periods']}/{group['entries']} dated; {group['represented_months']} precise calendar months")
        for item in group['periods']:
            print(f"      {item['label']}: {item['state']}; months={item['months']}")

    if gaps:
        print(f"\n  ⏱️  TIMELINE GAPS DETECTED ({len(gaps)} items):")
        for i, g in enumerate(gaps, 1):
            start = g.get("start")
            end = g.get("end")
            months = g.get("months") or g.get("duration_months")
            print(f"    {i:2d}. Gap: {start} to {end} ({months} months) - State: {g.get('state')}")

    if unresolved:
        print(f"\n  ❓ UNRESOLVED / AMBIGUOUS ITEMS ({len(unresolved)} items):")
        for i, u in enumerate(unresolved[:4], 1):
            title = u.get("title") or "Unknown"
            org = u.get("org") or "Unknown"
            print(f"    {i:2d}. {title} @ {org} | Reason: {u.get('status')}")

    print("\n" + "=" * 72 + "\n")


def check_individual_resume(query):
    query_str = query.strip()
    query_path = Path(query_str)

    # 1. Direct file path to a PDF, DOCX, or TXT
    if query_path.is_file() and query_path.suffix.lower() in {".pdf", ".docx", ".doc", ".txt"}:
        print(f"Parsing raw resume file: {query_path.name}...")
        from scripts.batch_parse import parse_resume_to_json
        data = parse_resume_to_json(str(query_path))
        raw_text = ""
        display_resume_diagnostic(query_path.name, data, raw_text)
        return

    # 2. Search in pre-parsed dataset
    norm_q = normalize_key(query_str)
    all_json = list(MODEL_DIR.glob("*.json"))
    
    # Exact or substring match
    matches = []
    for p in all_json:
        if p.name == "batch_accuracy_summary.json":
            continue
        key = normalize_key(p.name)
        if norm_q == key or norm_q in key:
            matches.append(p)

    if not matches:
        print(f"\n❌ No resume found matching: '{query_str}'")
        print("Tip: Provide part of the candidate's name or filename, or an exact file path.")
        print("Example: ./check_resume_score \"Abhishek\" or ./check_resume_score \"dataset/resumes/resumes/Abhishek Barnwa.pdf\"\n")
        return

    print(f"\nFound {len(matches)} resume(s) matching '{query_str}':")
    for m in matches[:5]:
        m_data = json.loads(m.read_text())
        k = normalize_key(m.name)
        raw_text = ""
        if RAW_DIR.is_dir():
            g_path = RAW_DIR / (m.name if (RAW_DIR / m.name).exists() else f"{k}.json")
            if g_path.exists():
                try:
                    raw_text = json.loads(g_path.read_text()).get("text", "")
                except Exception:
                    pass
        display_resume_diagnostic(m_data.get("file_name", m.name), m_data, raw_text)

    if len(matches) > 5:
        print(f"... and {len(matches) - 5} other matches. Specify a more exact name to narrow down.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: ./check_resume_score <candidate_name_or_filepath>")
        print("Examples:")
        print("  ./check_resume_score \"Abhishek Barnwa\"")
        print("  ./check_resume_score \"A.Bhargava\"")
        print("  ./check_resume_score dataset/resumes/resumes/Abhishek\\ Barnwa.pdf")
        sys.exit(1)

    check_individual_resume(" ".join(sys.argv[1:]))
