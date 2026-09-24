#!/usr/bin/env python3
"""Period Coverage Tiers & Diagnostic Engine for 1,554 Resumes.

Categorizes resumes into High, Medium, and Low tiers, diagnoses the exact
failure modes for lower-scoring resumes, and discovers non-standard
headings (e.g. 'my story', 'career journey', 'history') across the dataset.

Usage:
    ./scripts/analyze_tiers.py
    ./diagnose_accuracy_tiers
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = BASE_DIR / "model_parsed_periods"
if not MODEL_DIR.is_dir():
    MODEL_DIR = BASE_DIR / "model_parsed_1500_audited"
LOCAL_RAW = BASE_DIR / "reference_raw_json"
RAW_DIR = LOCAL_RAW if LOCAL_RAW.is_dir() else Path("/home/gopal/resume-timeline-test/json_results")


sys.path.insert(0, str(BASE_DIR))
from backend.periods import analyze_record
from scripts.compare_accuracy import load_records

def normalize_key(name):
    s = str(name).lower().strip()
    s = re.sub(r"\.(pdf|docx|txt|doc|rtf|json)$", "", s)
    s = re.sub(r"\.(pdf|docx|txt|doc|rtf)$", "", s)
    return re.sub(r"[_\-\s\(\)\[\]]+", "_", s).strip("_")


def find_candidate_headings(raw_text):
    """Discover candidate-written section headings and uppercase lines."""
    headings = []
    lines = raw_text.splitlines()
    for line in lines:
        s = line.strip().strip(":").strip()
        if not s:
            continue
        # Check for headings: 3-50 chars, uppercase or title case, <= 6 words, no pure numbers
        if 3 <= len(s) <= 50 and len(s.split()) <= 6:
            if (s.isupper() or s.istitle()) and not any(c.isdigit() for c in s):
                headings.append(s)
            elif re.match(r"(?i)^(my\s+story|history|career\s+journey|work\s+summary|background|experience|path)", s):
                headings.append(s)
    return headings


def diagnose_resume(name, model_data, raw_text):
    """Measure period availability across all categories, not model accuracy."""
    analysis = analyze_record(model_data)
    groups = analysis['categories']
    total = sum(g['entries'] for g in groups.values())
    dated = sum(g['dated_periods'] for g in groups.values())
    score = dated / total if total else 0.0
    tier = 'HIGH' if score >= .85 else 'MEDIUM' if score >= .60 else 'LOW'
    counts = ', '.join(f"{key}: {g['dated_periods']}/{g['entries']} periods dated" for key,g in groups.items())
    return {
        'tier': tier, 'category': 'NO_ENTRIES' if not total else 'PERIODS_AVAILABLE' if dated == total else 'INCOMPLETE_PERIODS',
        'score': round(score, 4), 'score_definition': 'Share of extracted entries with usable date ranges across work, projects and education; not accuracy.',
        'candidate_name': model_data.get('candidate_name', ''),
        'problem': counts + '. Missing dates or categories do not establish a parser error.',
        'headings_found': find_candidate_headings(raw_text)[:8],
        'work_exp_count': groups['work_experience']['entries'],
        'projects_count': groups['projects']['entries'],
        'education_count': groups['education']['entries'],
        'dates_found_in_text': len(re.findall(r"\b(?:19|20)\d{2}\b", raw_text)),
        'period_analysis': analysis,
    }


def run_tier_analysis(tier_filter="all", show_headings=False, file_filter=None, limit=25):
    if not MODEL_DIR.is_dir():
        print(f"Error: Directory {MODEL_DIR} not found. Run ./parse_to_json first.", file=sys.stderr)
        sys.exit(1)

    models, _ = load_records(directory=MODEL_DIR)
    references, _ = load_records(directory=RAW_DIR) if RAW_DIR.is_dir() else ({}, [])
    total = len(models)
    if not total:
        raise ValueError('No prediction records found')
    high_tier, med_tier, low_tier = [], [], []
    category_counts, all_unusual_headings = Counter(), Counter()
    for key, model in sorted(models.items()):
        raw_text = references.get(key, {}).get('text', '')
        diag = diagnose_resume(key, model, raw_text)
        diag.update(filename=model.get('file_name', key), key=key)
        category_counts[diag['category']] += 1
        all_unusual_headings.update(diag['headings_found'])
        {'HIGH': high_tier, 'MEDIUM': med_tier, 'LOW': low_tier}[diag['tier']].append(diag)

    high_pct = round(len(high_tier) * 100 / max(1, total), 1)
    med_pct = round(len(med_tier) * 100 / max(1, total), 1)
    low_pct = round(len(low_tier) * 100 / max(1, total), 1)

    # Handle file filter
    if file_filter:
        matches = [d for d in (low_tier + med_tier + high_tier) if file_filter.lower() in d["filename"].lower()]
        if not matches:
            print(f"No resume matching '{file_filter}' found.")
            return
        for m in matches:
            print("\n" + "=" * 68)
            print(f"  RESUME DIAGNOSTIC: {m['filename']}")
            print("=" * 68)
            print(f"  Tier:             {m['tier']}")
            print(f"  Score:            {int(m['score']*100)}%")
            print(f"  Category:         {m['category']}")
            print(f"  Work Exp Count:   {m['work_exp_count']}")
            print(f"  Projects Count:   {m['projects_count']}")
            print(f"  Education Count:  {m['education_count']}")
            print(json.dumps(m['period_analysis'], indent=2))
            print(f"  Dates In Text:    {m['dates_found_in_text']}")
            print(f"  Diagnosed Issue:  {m['problem']}")
            print(f"  Headings Found:   {', '.join(m['headings_found']) or 'None'}")
            print("=" * 68 + "\n")
        return

    # Handle headings only
    if show_headings:
        print("\n" + "=" * 68)
        print("  ALL CANDIDATE HEADINGS DISCOVERED ACROSS 1,500+ RESUMES")
        print("=" * 68)
        for h, cnt in all_unusual_headings.most_common(50):
            print(f"   • {h:<35} (found in {cnt:3d} resumes)")
        print("=" * 68 + "\n")
        return

    print("\n" + "=" * 68)
    print("      RESUME PERIOD COVERAGE TIERS & ROOT CAUSE DIAGNOSTIC REPORT")
    print("=" * 68)
    print(f"  Total Resumes Analyzed: {total}\n")
    print("  Percentages measure date-range availability, NOT accuracy.")
    for category in ('work_experience', 'projects', 'education'):
        groups = [d['period_analysis']['categories'][category] for d in high_tier + med_tier + low_tier]
        print(f"  {category}: {sum(g['dated_periods'] for g in groups)} dated / {sum(g['entries'] for g in groups)} entries")
    print(f"  🟢 HIGH PERIOD COVERAGE TIER  (>= 85%):    {len(high_tier):4d} resumes ({high_pct}%)")
    print(f"  🟡 MEDIUM PERIOD COVERAGE TIER (60% - 84%): {len(med_tier):4d} resumes ({med_pct}%)")
    print(f"  🔴 LOW / PROBLEMATIC TIER (< 60%):   {len(low_tier):4d} resumes ({low_pct}%)")
    print("=" * 68)
    print("  ROOT CAUSE BREAKDOWN (Why Resumes Fall Into Lower Tiers):")
    for cat, cnt in category_counts.most_common():
        pct = round(cnt * 100 / max(1, total), 1)
        print(f"   • {cat:<32}: {cnt:4d} resumes ({pct}%)")

    print("\n" + "-" * 68)
    print("  TOP NON-STANDARD HEADINGS DISCOVERED IN LOWER-TIER RESUMES:")
    for h, cnt in all_unusual_headings.most_common(12):
        print(f"   • \"{h}\" (found in {cnt} resumes)")
    print("=" * 68)

    # If tier filter is applied, display list
    if tier_filter.lower() in ("low", "medium", "high"):
        target_list = low_tier if tier_filter.lower() == "low" else (med_tier if tier_filter.lower() == "medium" else high_tier)
        print(f"\n  LIST OF {tier_filter.upper()} TIER RESUMES (Showing up to {limit}):")
        print(f"  {'Filename':<35} {'Score':<8} {'Diagnosed Issue'}")
        print("  " + "-" * 66)
        for r in target_list[:limit]:
            print(f"  {r['filename'][:34]:<35} {int(r['score']*100)}%     {r['problem'][:50]}")
        print("=" * 68 + "\n")

    # Generate JSON summary
    summary_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_resumes": total,
        "tiers": {
            "high": {"count": len(high_tier), "pct": high_pct},
            "medium": {"count": len(med_tier), "pct": med_pct},
            "low": {"count": len(low_tier), "pct": low_pct}
        },
        "root_causes": dict(category_counts),
        "discovered_headings": dict(all_unusual_headings.most_common(30)),
        "score_definition": "Date-range availability across all three categories; not accuracy.",
        "resumes": high_tier + med_tier + low_tier,
        "problematic_resumes_sample": (low_tier + med_tier)[:50]
    }
    out_json = BASE_DIR / "accuracy_tiers.json"
    out_json.write_text(json.dumps(summary_data, indent=2))
    print(f"Saved machine-readable tier diagnostics to: {out_json}")

    # Export complete CSV of all 1,500+ resumes
    import csv
    csv_file = BASE_DIR / "all_resumes_scores.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Filename", "Candidate Name", "Tier", "Dated periods (%)",
            "Work Exp Count", "Projects Count", "Education Count", "Work Dated", "Projects Dated", "Education Dated", "Represented Months", "Work Months", "Project Months", "Education Months", "Root Cause Category",
            "Diagnosed Issue", "Discovered Headings"
        ])
        for r in sorted(high_tier + med_tier + low_tier, key=lambda x: (x["score"], x["filename"])):
            writer.writerow([
                r["filename"],
                r.get("candidate_name", ""),
                r["tier"],
                f"{int(r['score']*100)}%",
                r.get("work_exp_count", 0),
                r.get("projects_count", 0), r.get("education_count", 0),
                *[r['period_analysis']['categories'][c]['dated_periods'] for c in ('work_experience','projects','education')],
                r['period_analysis']['represented_months'],
                *[r['period_analysis']['categories'][c]['represented_months'] for c in ('work_experience','projects','education')], r["category"],
                r["problem"],
                "; ".join(r.get("headings_found", []))
            ])
    print(f"Saved complete 1,500+ resume spreadsheet to:  {csv_file}")

    # Generate Markdown Report
    generate_markdown_report(total, high_tier, med_tier, low_tier, category_counts, all_unusual_headings)


def generate_markdown_report(total, high_tier, med_tier, low_tier, category_counts, unusual_headings):
    rows = high_tier + med_tier + low_tier
    md = '# Resume period diagnostics\n\nDate-range availability is not accuracy. Education and projects count equally with employment.\n\n'
    md += '| Category | Entries | Dated periods |\n|---|---:|---:|\n'
    for c in ('work_experience', 'projects', 'education'):
        groups = [r['period_analysis']['categories'][c] for r in rows]
        md += f"| {c} | {sum(g['entries'] for g in groups)} | {sum(g['dated_periods'] for g in groups)} |\n"
    md += '\nCalendar overlaps count once. Completion dates, year-only precision, undated entries, and unplaced durations are reported separately in accuracy_tiers.json.\n'
    (BASE_DIR / 'docs' / 'ACCURACY_TIERS_AND_DIAGNOSTICS.md').write_text(md)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Resume Period Coverage Tiers & Root Cause Diagnostic Engine")
    parser.add_argument("--tier", choices=["high", "medium", "low", "all"], default="all", help="Filter and display resumes in a specific tier")
    parser.add_argument("--headings", action="store_true", help="Print all discovered candidate headings across the dataset")
    parser.add_argument("--file", type=str, help="Diagnose a specific resume by filename")
    parser.add_argument("--limit", type=int, default=25, help="Number of resumes to list in console")
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR, help="Prediction JSON directory")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR, help="Source extraction JSON directory")
    args = parser.parse_args()
    MODEL_DIR, RAW_DIR = args.model_dir, args.raw_dir

    run_tier_analysis(
        tier_filter=args.tier,
        show_headings=args.headings,
        file_filter=args.file,
        limit=args.limit
    )
