#!/usr/bin/env python3
"""
Comprehensive Comparison Pipeline for Resume Extraction Validation

Compares main project (resume_parser-app) structured extraction against
validation project (resume-timeline-test) source text.

Since validation project only provides source text (not structured ground truth),
this performs source-text diagnostics + hand-labeled case evaluation.
"""

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


# ============================================================
# NORMALIZATION UTILITIES
# ============================================================

def clean_text(value: Any) -> str:
    """Normalize text for comparison: lowercase, remove punctuation, collapse whitespace."""
    if value is None:
        return ""
    return " ".join(re.sub(r"[^\w\s]", " ", str(value).casefold()).split())


def normalize_phone(phone: str) -> str:
    """Extract 10-digit Indian phone number."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) > 10:
        digits = digits[-10:]
    return digits if len(digits) == 10 and digits[0] in "6789" else ""


def normalize_email(email: str) -> str:
    """Normalize email to lowercase."""
    return email.strip().lower() if email else ""


def normalize_url(url: str) -> str:
    """Normalize URL."""
    if not url:
        return ""
    url = url.strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    url = url.rstrip("/")
    return url


def normalize_date(date_str: str) -> str:
    """Normalize date to YYYY-MM format."""
    if not date_str:
        return ""
    date_str = date_str.strip().lower()
    if date_str in {"present", "current", "now", "till now", "till date", "ongoing"}:
        return "present"
    # YYYY-MM (already normalized)
    m = re.fullmatch(r"((?:19|20)\d{2})[-/.](\d{1,2})", date_str)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    # YYYY
    m = re.fullmatch(r"((?:19|20)\d{2})", date_str)
    if m:
        return m.group(1)
    # Month YYYY
    months = {m: i+1 for i, m in enumerate(['january','february','march','april','may','june',
                                              'july','august','september','october','november','december'])}
    months.update({m[:3]: n for m, n in list(months.items())})
    months['sept'] = 9
    m = re.fullmatch(r"([a-z]+)[\s,./-]*((?:19|20)\d{2})", date_str)
    if m and m.group(1) in months:
        return f"{m.group(2)}-{months[m.group(1)]:02d}"
    return "invalid:" + date_str


def normalize_skill(skill: str) -> str:
    """Normalize skill name."""
    if not skill:
        return ""
    skill = skill.strip().lower()
    # Common aliases
    aliases = {
        "nodejs": "node.js",
        "node js": "node.js",
        "reactjs": "react",
        "react js": "react",
        "vuejs": "vue",
        "vue js": "vue",
        "nextjs": "next.js",
        "next js": "next.js",
        "restapi": "rest api",
        "rest apis": "rest api",
        "postgresql": "postgres",
        "postgressql": "postgres",
        "mongodb": "mongo",
        "k8s": "kubernetes",
        "gcp": "google cloud",
        "aws": "amazon web services",
    }
    skill = aliases.get(skill, skill)
    # Remove version numbers
    skill = re.sub(r"\s+\d+(\.\d+)*$", "", skill)
    return skill


def normalize_list(items: List[str]) -> List[str]:
    """Normalize and deduplicate a list of strings."""
    if not items:
        return []
    normalized = [normalize_skill(x) for x in items if x]
    normalized = [x for x in normalized if x]
    # Deduplicate preserving order
    seen = set()
    result = []
    for x in normalized:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


def normalize_company(company: str) -> str:
    """Normalize company name."""
    if not company:
        return ""
    company = company.strip().lower()
    # Remove common suffixes
    company = re.sub(r"\b(pvt\.?\s*ltd\.?|ltd\.?|inc\.?|llc|limited|corp\.?|corporation|technologies|solutions|systems|services|consulting|digital|labs|group|bank|infotech)\b", "", company, flags=re.IGNORECASE)
    company = re.sub(r"[^\w\s]", " ", company)
    company = " ".join(company.split())
    return company


def normalize_title(title: str) -> str:
    """Normalize job title."""
    if not title:
        return ""
    title = title.strip().lower()
    title = re.sub(r"[^\w\s]", " ", title)
    title = " ".join(title.split())
    return title


# ============================================================
# SCHEMA NORMALIZATION
# ============================================================

def extract_main_fields(main_record: Dict) -> Dict:
    """Extract normalized fields from main project output."""
    work_exp = []
    for w in main_record.get("work_experience", []):
        work_exp.append({
            "company": normalize_company(w.get("company", "")),
            "title": normalize_title(w.get("title", "")),
            "start_date": normalize_date(w.get("start_date", "")),
            "end_date": normalize_date(w.get("end_date", "")),
            "is_current": w.get("is_current", False),
            "status": w.get("status", ""),
            "confidence": w.get("confidence"),
        })
    
    education = []
    for e in main_record.get("education", []):
        education.append({
            "institution": normalize_company(e.get("company", "")),
            "degree": normalize_title(e.get("title", "")),
            "start_date": normalize_date(e.get("start_date", "")),
            "end_date": normalize_date(e.get("end_date", "")),
            "status": e.get("status", ""),
            "confidence": e.get("confidence"),
        })
    
    projects = []
    for p in main_record.get("projects", []):
        projects.append({
            "name": clean_text(p.get("name", "")),
            "client": clean_text(p.get("client", "")),
            "role": clean_text(p.get("role", "")),
            "duration": clean_text(p.get("duration", "")),
            "details": [clean_text(d) for d in p.get("details", [])],
        })
    
    gaps = []
    for g in main_record.get("gaps", []):
        gaps.append({
            "start": g.get("start"),
            "end": g.get("end"),
            "months": g.get("months"),
            "state": g.get("state", ""),
        })
    
    candidate_name = clean_text(main_record.get("candidate_name", ""))
    
    return {
        "file_name": main_record.get("file_name", ""),
        "doc_id": main_record.get("doc_id", ""),
        "candidate_name": candidate_name,
        "status": main_record.get("status", ""),
        "work_experience": work_exp,
        "education": education,
        "projects": projects,
        "gaps": gaps,
        "total_work_experience": len(work_exp),
        "total_projects": len(projects),
        "total_gaps": len(gaps),
    }


def extract_reference_fields(ref_record: Dict) -> Dict:
    """Extract fields from validation project (source text only)."""
    text = ref_record.get("text", "")
    filename = ref_record.get("filename", "")
    file_hash = ref_record.get("sha256", "")
    status = ref_record.get("status", "")
    
    return {
        "filename": filename,
        "file_hash": file_hash,
        "status": status,
        "text": text,
        "text_normalized": clean_text(text),
        "char_count": len(text),
        "word_count": len(text.split()),
    }


# ============================================================
# MATCHING LOGIC
# ============================================================

def match_work_experience(main_items: List[Dict], ref_text: str) -> Dict:
    """Match work experience entries against source text."""
    results = {
        "total_main": len(main_items),
        "matched": 0,
        "partial": 0,
        "missing": 0,
        "details": [],
    }
    
    ref_lower = ref_text.lower()
    
    for item in main_items:
        company = item.get("company", "")
        title = item.get("title", "")
        start = item.get("start_date", "")
        end = item.get("end_date", "")
        
        # Check if company appears in text
        company_found = bool(company and company in ref_lower)
        title_found = bool(title and title in ref_lower)
        start_found = bool(start and start != "present" and start[:4] in ref_lower)  # year only
        end_found = bool(end and end != "present" and end[:4] in ref_lower)
        
        # Count non-empty fields
        non_empty = sum([bool(company), bool(title), bool(start), bool(end)])
        if non_empty == 0:
            results["missing"] += 1
            result = "MISSING"
            results["details"].append({
                "company": company, "title": title, "start_date": start, "end_date": end,
                "result": result, "company_found": False, "title_found": False,
                "start_found": False, "end_found": False,
            })
            continue
        
        # Count matches among non-empty fields
        match_score = sum([company_found, title_found, start_found, end_found])
        
        # MATCH if all non-empty fields found, PARTIAL if at least half
        if match_score == non_empty:
            result = "MATCH"
            results["matched"] += 1
        elif match_score >= max(1, non_empty // 2):
            result = "PARTIAL"
            results["partial"] += 1
        else:
            result = "MISSING"
            results["missing"] += 1
        
        results["details"].append({
            "company": company,
            "title": title,
            "start_date": start,
            "end_date": end,
            "result": result,
            "company_found": company_found,
            "title_found": title_found,
            "start_found": start_found,
            "end_found": end_found,
            "non_empty_fields": non_empty,
            "matched_fields": match_score,
        })
    
    return results


def match_projects(main_items: List[Dict], ref_text: str) -> Dict:
    """Match projects against source text."""
    results = {
        "total_main": len(main_items),
        "matched": 0,
        "partial": 0,
        "missing": 0,
        "details": [],
    }
    
    ref_lower = ref_text.lower()
    
    for item in main_items:
        name = item.get("name", "")
        client = item.get("client", "")
        role = item.get("role", "")
        duration = item.get("duration", "")
        
        # Check key phrases
        name_words = [w for w in name.split() if len(w) > 3]
        client_words = [w for w in client.split() if len(w) > 3]
        
        name_found = any(w in ref_lower for w in name_words[:3]) if name_words else False
        client_found = any(w in ref_lower for w in client_words[:3]) if client_words else False
        
        non_empty = sum([bool(name_words), bool(client_words)])
        match_score = sum([name_found, client_found])
        
        if non_empty == 0:
            result = "MISSING"
            results["missing"] += 1
        elif match_score == non_empty:
            result = "MATCH"
            results["matched"] += 1
        elif match_score >= 1:
            result = "PARTIAL"
            results["partial"] += 1
        else:
            result = "MISSING"
            results["missing"] += 1
        
        results["details"].append({
            "name": name,
            "client": client,
            "role": role,
            "duration": duration,
            "result": result,
            "name_found": name_found,
            "client_found": client_found,
        })
    
    return results


def match_education(main_items: List[Dict], ref_text: str) -> Dict:
    """Match education entries against source text."""
    results = {
        "total_main": len(main_items),
        "matched": 0,
        "partial": 0,
        "missing": 0,
        "details": [],
    }
    
    ref_lower = ref_text.lower()
    
    for item in main_items:
        institution = item.get("institution", "")
        degree = item.get("degree", "")
        start = item.get("start_date", "")
        end = item.get("end_date", "")
        
        inst_found = bool(institution and institution in ref_lower)
        degree_found = bool(degree and degree in ref_lower)
        year_found = False
        for d in [start, end]:
            if d and d != "present":
                year = d[:4]
                if year.isdigit() and year in ref_lower:
                    year_found = True
                    break
        
        non_empty = sum([bool(institution), bool(degree), bool(start) or bool(end)])
        match_score = sum([inst_found, degree_found, year_found])
        
        if non_empty == 0:
            result = "MISSING"
            results["missing"] += 1
        elif match_score == non_empty:
            result = "MATCH"
            results["matched"] += 1
        elif match_score >= max(1, non_empty // 2):
            result = "PARTIAL"
            results["partial"] += 1
        else:
            result = "MISSING"
            results["missing"] += 1
        
        results["details"].append({
            "institution": institution,
            "degree": degree,
            "start_date": start,
            "end_date": end,
            "result": result,
            "inst_found": inst_found,
            "degree_found": degree_found,
            "year_found": year_found,
            "non_empty_fields": non_empty,
            "matched_fields": match_score,
        })
    
    return results


def match_gaps(main_items: List[Dict], ref_text: str) -> Dict:
    """Match gaps against source text (limited - can only check if gap months mentioned)."""
    results = {
        "total_main": len(main_items),
        "details": [],
    }
    
    for item in main_items:
        months = item.get("months", 0)
        state = item.get("state", "")
        results["details"].append({
            "months": months,
            "state": state,
            "note": "Gap validation requires labeled ground truth; source text cannot confirm gaps"
        })
    
    return results


# ============================================================
# MAIN COMPARISON PIPELINE
# ============================================================

def load_main_records(main_dir: Path) -> Dict[str, Dict]:
    """Load all main project output records."""
    records = {}
    for path in main_dir.glob("*.json"):
        if path.name in {"batch_summary.json", "batch_accuracy_summary.json", "accuracy_summary.json"}:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            key = path.stem.replace(".json", "").casefold()
            records[key] = data
        except Exception as e:
            print(f"Error loading {path}: {e}", file=sys.stderr)
    return records


def load_reference_records(ref_dir: Path) -> Dict[str, Dict]:
    """Load all validation project records."""
    records = {}
    for path in ref_dir.glob("*.json"):
        if path.name in {"batch_summary.json", "batch_accuracy_summary.json", "accuracy_summary.json"}:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            key = path.stem.replace(".json", "").casefold()
            records[key] = data
        except Exception as e:
            print(f"Error loading {path}: {e}", file=sys.stderr)
    return records


def normalize_key(key: str) -> str:
    """Normalize filename for matching across projects."""
    key = key.lower().strip()
    key = re.sub(r"\.(pdf|docx|txt|doc|rtf|json)$", "", key)
    key = re.sub(r"[_\-\s\(\)\[\]]+", "_", key).strip("_")
    return key


def pair_records(main_records: Dict, ref_records: Dict) -> List[Tuple[str, Dict, Dict]]:
    """Pair main and reference records by normalized filename."""
    main_by_key = {normalize_key(k): (k, v) for k, v in main_records.items()}
    ref_by_key = {normalize_key(k): (k, v) for k, v in ref_records.items()}
    
    pairs = []
    for key in set(main_by_key.keys()) & set(ref_by_key.keys()):
        main_k, main_v = main_by_key[key]
        ref_k, ref_v = ref_by_key[key]
        pairs.append((key, main_v, ref_v))
    
    return sorted(pairs, key=lambda x: x[0])


def compute_resume_accuracy(main_norm: Dict, ref_norm: Dict) -> Dict:
    """Compute per-resume accuracy metrics."""
    ref_text = ref_norm.get("text_normalized", "")
    
    work_results = match_work_experience(main_norm["work_experience"], ref_text)
    proj_results = match_projects(main_norm["projects"], ref_text)
    edu_results = match_education(main_norm["education"], ref_text)
    gap_results = match_gaps(main_norm["gaps"], ref_text)
    
    # Overall score: weighted average
    total_fields = (work_results["total_main"] * 4 +  # company, title, start, end
                    proj_results["total_main"] * 2 +  # name, client
                    edu_results["total_main"] * 3 +   # institution, degree, year
                    gap_results["total_main"])
    
    matched_fields = (work_results["matched"] * 4 +
                      work_results["partial"] * 2 +
                      proj_results["matched"] * 2 +
                      edu_results["matched"] * 3 +
                      edu_results["partial"] * 1)
    
    overall_pct = round(100 * matched_fields / max(1, total_fields), 1) if total_fields > 0 else 100.0
    
    return {
        "file_name": main_norm["file_name"],
        "overall_accuracy_pct": overall_pct,
        "work_experience": work_results,
        "projects": proj_results,
        "education": edu_results,
        "gaps": gap_results,
        "main_status": main_norm["status"],
        "ref_status": ref_norm["status"],
    }


def aggregate_metrics(all_results: List[Dict]) -> Dict:
    """Aggregate metrics across all resumes."""
    totals = {
        "resumes_total": len(all_results),
        "resumes_success": 0,
        "resumes_partial": 0,
        "resumes_failed": 0,
        "work_experience": {"total": 0, "matched": 0, "partial": 0, "missing": 0},
        "projects": {"total": 0, "matched": 0, "partial": 0, "missing": 0},
        "education": {"total": 0, "matched": 0, "partial": 0, "missing": 0},
        "gaps": {"total": 0},
    }
    
    accuracy_sum = 0.0
    
    for r in all_results:
        if r["main_status"] == "SUCCESS":
            totals["resumes_success"] += 1
        elif r["main_status"] == "PARTIAL":
            totals["resumes_partial"] += 1
        else:
            totals["resumes_failed"] += 1
        
        accuracy_sum += r["overall_accuracy_pct"]
        
        for field in ["work_experience", "projects", "education"]:
            totals[field]["total"] += r[field]["total_main"]
            totals[field]["matched"] += r[field]["matched"]
            totals[field]["partial"] += r[field]["partial"]
            totals[field]["missing"] += r[field]["missing"]
        
        totals["gaps"]["total"] += r["gaps"]["total_main"]
    
    mean_accuracy = round(accuracy_sum / max(1, len(all_results)), 1)
    
    # Compute precision/recall/F1 for each field
    for field in ["work_experience", "projects", "education"]:
        tp = totals[field]["matched"]
        fp = totals[field]["missing"]  # items in main but not in source
        precision = round(tp / max(1, tp + fp), 3) if tp + fp > 0 else 0
        totals[field]["precision"] = precision
        totals[field]["match_rate_pct"] = round(100 * tp / max(1, totals[field]["total"]), 1)
    
    return {
        "summary": totals,
        "mean_resume_accuracy_pct": mean_accuracy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def run_hand_labeled_evaluation(main_records: Dict) -> Dict:
    """Evaluate against hand-labeled test cases from eval/labels.py."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from eval.labels import CASES
    from backend.pipeline_context import PipelineContext
    from backend.pipeline import runner
    
    results = []
    for case in CASES:
        if case.get("file"):
            file_path = Path(case["file"])
            if not file_path.exists():
                # Try relative to project root
                file_path = Path(__file__).resolve().parents[1] / case["file"]
            if file_path.exists():
                with open(file_path, "rb") as fh:
                    ctx = PipelineContext(case["id"], case["file"], raw_bytes=fh.read())
            else:
                print(f"Warning: {case['file']} not found for {case['id']}", file=sys.stderr)
                continue
        else:
            ctx = PipelineContext(case["id"], "inline.txt", raw_text=case["text"])
        
        runner.run(ctx)
        dto = ctx.recruiter_output or {"timeline": [], "gaps": [], "status": "FAILED"}
        
        # Match jobs
        pred_jobs = [e for e in dto["timeline"] if e["type"] in ("EMPLOYMENT", "INTERNSHIP")]
        exp_jobs = case.get("jobs", [])
        
        matched = set()
        job_tp = job_fp = job_fn = 0
        
        for ej in exp_jobs:
            hit = [p for i, p in enumerate(pred_jobs)
                   if i not in matched and ej["org_sub"].lower() in (p["org"] or "").lower()
                   and (p.get("date_label") == ej["date_label"] and p.get("precision") == ej["precision"]
                        if "date_label" in ej else p["start"] == ej["start"]
                        and (bool(p.get("is_present")) if ej["end"] is None else p["end"] == ej["end"]))]
            if hit:
                job_tp += 1
                matched.add(pred_jobs.index(hit[0]))
            else:
                job_fn += 1
        
        job_fp += len(pred_jobs) - len(matched)
        
        # Match gaps
        pred_gaps = sorted(g["months"] for g in dto["gaps"] if g["state"] == "POTENTIAL_GAP")
        exp_gaps = sorted(case.get("gaps", []))
        
        gap_tp = gap_fp = gap_fn = 0
        pg, eg = list(pred_gaps), list(exp_gaps)
        for g in pg:
            if g in eg:
                gap_tp += 1
                eg.remove(g)
            else:
                gap_fp += 1
        gap_fn += len(eg)
        
        results.append({
            "case_id": case["id"],
            "job_tp": job_tp, "job_fp": job_fp, "job_fn": job_fn,
            "gap_tp": gap_tp, "gap_fp": gap_fp, "gap_fn": gap_fn,
            "pred_jobs": len(pred_jobs), "exp_jobs": len(exp_jobs),
            "pred_gaps": pred_gaps, "exp_gaps": exp_gaps,
        })
    
    # Aggregate
    total_tp = sum(r["job_tp"] for r in results)
    total_fp = sum(r["job_fp"] for r in results)
    total_fn = sum(r["job_fn"] for r in results)
    gap_tp = sum(r["gap_tp"] for r in results)
    gap_fp = sum(r["gap_fp"] for r in results)
    gap_fn = sum(r["gap_fn"] for r in results)
    
    def prf(tp, fp, fn):
        p = tp / (tp + fp) if tp + fp else 1.0
        r = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        return round(p, 3), round(r, 3), round(f1, 3)
    
    jp, jr, jf = prf(total_tp, total_fp, total_fn)
    gp, gr, gf = prf(gap_tp, gap_fp, gap_fn)
    
    return {
        "labeled_cases": len(CASES),
        "evaluated": len(results),
        "job_extraction": {"precision": jp, "recall": jr, "f1": jf},
        "gap_detection": {"precision": gp, "recall": gr, "f1": gf},
        "per_case": results,
    }


def find_duplicates(records: Dict, key_field: str = "file_hash") -> List[List[str]]:
    """Find duplicate records by hash or content."""
    by_hash = defaultdict(list)
    for key, record in records.items():
        hash_val = record.get(key_field) or record.get("input_sha256") or record.get("sha256")
        if hash_val:
            by_hash[hash_val].append(key)
    
    duplicates = [v for v in by_hash.values() if len(v) > 1]
    return duplicates


def find_content_duplicates(ref_dir: Path, main_dir: Path) -> Dict:
    """Find content-based duplicates in both projects."""
    import hashlib
    
    # Reference project
    ref_hashes = defaultdict(list)
    for path in ref_dir.glob("*.json"):
        if path.name in {"batch_summary.json", "batch_accuracy_summary.json", "accuracy_summary.json", "all_results.json"}:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            text = data.get("text", "")
            if text.strip():
                h = hashlib.sha256(text.encode()).hexdigest()
                ref_hashes[h].append(path.name)
        except Exception:
            pass
    
    # Main project
    main_hashes = defaultdict(list)
    for path in main_dir.glob("*.json"):
        if path.name in {"batch_summary.json", "batch_accuracy_summary.json", "accuracy_summary.json"}:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            text = data.get("raw_pipeline_dto", {}).get("text", "")
            if not text:
                text = " ".join([w.get("title","") + " " + w.get("company","") for w in data.get("work_experience", [])])
            if text.strip():
                h = hashlib.sha256(text.encode()).hexdigest()
                main_hashes[h].append(path.name)
        except Exception:
            pass
    
    ref_dupes = {k: v for k, v in ref_hashes.items() if len(v) > 1}
    main_dupes = {k: v for k, v in main_hashes.items() if len(v) > 1}
    
    return {
        "reference_project": {
            "total_files": sum(len(v) for v in ref_hashes.values()),
            "unique_content_hashes": len(ref_hashes),
            "duplicate_groups": len(ref_dupes),
            "duplicate_files": sum(len(v) - 1 for v in ref_dupes.values()),
            "duplication_rate_pct": round(100 * sum(len(v) - 1 for v in ref_dupes.values()) / max(1, sum(len(v) for v in ref_hashes.values())), 1),
            "top_duplicate_groups": [v for v in list(ref_dupes.values())[:20]],
        },
        "main_project": {
            "total_files": sum(len(v) for v in main_hashes.values()),
            "unique_content_hashes": len(main_hashes),
            "duplicate_groups": len(main_dupes),
            "duplicate_files": sum(len(v) - 1 for v in main_dupes.values()),
            "duplication_rate_pct": round(100 * sum(len(v) - 1 for v in main_dupes.values()) / max(1, sum(len(v) for v in main_hashes.values())), 1),
            "top_duplicate_groups": [v for v in list(main_dupes.values())[:20]],
        },
    }


def analyze_errors(all_results: List[Dict]) -> Dict:
    """Analyze common error patterns."""
    errors = {
        "missing_company": [],
        "missing_title": [],
        "wrong_dates": [],
        "missing_education": [],
        "missing_projects": [],
        "extra_items": [],
    }
    
    for r in all_results:
        fname = r["file_name"]
        for detail in r["work_experience"]["details"]:
            if detail["result"] == "MISSING":
                if not detail["company_found"]:
                    errors["missing_company"].append(fname)
                if not detail["title_found"]:
                    errors["missing_title"].append(fname)
                if not detail["start_found"] or not detail["end_found"]:
                    errors["wrong_dates"].append(fname)
        
        for detail in r["education"]["details"]:
            if detail["result"] == "MISSING":
                errors["missing_education"].append(fname)
        
        for detail in r["projects"]["details"]:
            if detail["result"] == "MISSING":
                errors["missing_projects"].append(fname)
    
    # Count frequencies
    error_counts = {k: Counter(v) for k, v in errors.items()}
    return error_counts


def main():
    parser = argparse.ArgumentParser(description="Comprehensive resume extraction comparison")
    parser.add_argument("--main-dir", type=Path, default=Path("/home/gopal/resume_parser-app/model_parsed_1500"),
                        help="Main project output directory")
    parser.add_argument("--ref-dir", type=Path, default=Path("/home/gopal/resume-timeline-test/json_results"),
                        help="Validation project output directory")
    parser.add_argument("--output", type=Path, default=Path("/home/gopal/resume_parser-app/comparison_report.json"),
                        help="Output report file")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    args = parser.parse_args()
    
    print("Loading main project records...")
    main_records = load_main_records(args.main_dir)
    print(f"  Loaded {len(main_records)} records")
    
    print("Loading validation project records...")
    ref_records = load_reference_records(args.ref_dir)
    print(f"  Loaded {len(ref_records)} records")
    
    print("Pairing records...")
    pairs = pair_records(main_records, ref_records)
    print(f"  Paired {len(pairs)} records")
    
    # Check for duplicates
    print("\nChecking for duplicates...")
    main_dupes = find_duplicates(main_records, "input_sha256")
    ref_dupes = find_duplicates(ref_records, "sha256")
    print(f"  Main project duplicates (by hash): {len(main_dupes)} groups")
    print(f"  Reference project duplicates (by hash): {len(ref_dupes)} groups")
    
    print("\nChecking for content-based duplicates...")
    content_dupes = find_content_duplicates(args.ref_dir, args.main_dir)
    print(f"  Reference: {content_dupes['reference_project']['duplicate_groups']} groups, {content_dupes['reference_project']['duplicate_files']} duplicate files ({content_dupes['reference_project']['duplication_rate_pct']}%)")
    print(f"  Main: {content_dupes['main_project']['duplicate_groups']} groups, {content_dupes['main_project']['duplicate_files']} duplicate files ({content_dupes['main_project']['duplication_rate_pct']}%)")
    
    print("\nRunning comparison...")
    start_time = time.time()
    
    all_results = []
    for key, main_rec, ref_rec in pairs:
        main_norm = extract_main_fields(main_rec)
        ref_norm = extract_reference_fields(ref_rec)
        result = compute_resume_accuracy(main_norm, ref_norm)
        all_results.append(result)
    
    elapsed = time.time() - start_time
    print(f"  Completed in {elapsed:.1f}s")
    
    print("\nRunning hand-labeled evaluation...")
    labeled_results = run_hand_labeled_evaluation(main_records)
    
    print("\nAggregating metrics...")
    aggregated = aggregate_metrics(all_results)
    
    print("\nAnalyzing errors...")
    error_analysis = analyze_errors(all_results)
    
    # Build final report
    report = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "main_project_dir": str(args.main_dir),
            "reference_project_dir": str(args.ref_dir),
            "main_records_loaded": len(main_records),
            "ref_records_loaded": len(ref_records),
            "records_paired": len(pairs),
            "processing_time_seconds": round(elapsed, 1),
        },
        "duplicate_analysis": {
            "main_project_duplicate_groups": len(main_dupes),
            "main_project_duplicates": main_dupes[:10],
            "reference_project_duplicate_groups": len(ref_dupes),
            "reference_project_duplicates": ref_dupes[:10],
            "content_based_duplicates": content_dupes,
        },
        "dataset_metrics": aggregated,
        "labeled_evaluation": labeled_results,
        "error_analysis": {k: dict(v.most_common(20)) for k, v in error_analysis.items()},
        "per_resume_results": all_results,
    }
    
    # Save report
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport saved to {args.output}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total resumes compared: {aggregated['summary']['resumes_total']}")
    print(f"  SUCCESS: {aggregated['summary']['resumes_success']}")
    print(f"  PARTIAL: {aggregated['summary']['resumes_partial']}")
    print(f"  FAILED:  {aggregated['summary']['resumes_failed']}")
    print(f"Mean resume accuracy: {aggregated['mean_resume_accuracy_pct']}%")
    print(f"\nWork Experience:")
    print(f"  Total entries: {aggregated['summary']['work_experience']['total']}")
    print(f"  Matched: {aggregated['summary']['work_experience']['matched']} ({aggregated['summary']['work_experience']['match_rate_pct']}%)")
    print(f"  Precision: {aggregated['summary']['work_experience']['precision']}")
    print(f"\nProjects:")
    print(f"  Total entries: {aggregated['summary']['projects']['total']}")
    print(f"  Matched: {aggregated['summary']['projects']['matched']} ({aggregated['summary']['projects']['match_rate_pct']}%)")
    print(f"  Precision: {aggregated['summary']['projects']['precision']}")
    print(f"\nEducation:")
    print(f"  Total entries: {aggregated['summary']['education']['total']}")
    print(f"  Matched: {aggregated['summary']['education']['matched']} ({aggregated['summary']['education']['match_rate_pct']}%)")
    print(f"  Precision: {aggregated['summary']['education']['precision']}")
    print(f"\nHand-labeled evaluation ({labeled_results['labeled_cases']} cases):")
    print(f"  Job extraction F1: {labeled_results['job_extraction']['f1']}")
    print(f"  Gap detection F1: {labeled_results['gap_detection']['f1']}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())