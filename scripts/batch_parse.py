"""Batch Resume to JSON Converter & Pipeline Parser.

Converts resumes (PDF, DOCX, TXT) into clean, standardized JSON format
without needing a browser or side panel. Ideal for batch processing
large collections (e.g. 1,500+ resumes).

Usage:
  # Single resume:
  ./venv/bin/python scripts/batch_parse.py --input resume.pdf --output output.json

  # Batch process a whole directory (parallel):
  ./venv/bin/python scripts/batch_parse.py --input-dir /path/to/resumes --output-dir /path/to/output_json --workers 4
"""

import argparse
import concurrent.futures
import io
import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.pipeline_context import PipelineContext
from backend.pipeline import runner
from backend import docstore as DB


def read_document(file_path):
    path = Path(file_path)
    suffix = path.suffix.lower()
    raw_bytes = path.read_bytes()
    raw_text = ""

    if suffix == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
                raw_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            pass
    elif suffix in (".docx", ".doc"):
        try:
            from docx import Document
            doc = Document(io.BytesIO(raw_bytes))
            raw_text = "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            pass
    elif suffix == ".txt":
        try:
            raw_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = raw_bytes.decode("utf-8-sig", errors="ignore")

    return raw_bytes, raw_text


def parse_resume_to_json(file_path, doc_id=None):
    """Parse a single resume file and return a structured JSON dict."""
    path = Path(file_path)
    filename = path.name
    doc_id = doc_id or path.stem

    raw_bytes, raw_text = read_document(path)
    ctx = PipelineContext(doc_id, filename, raw_bytes=raw_bytes, raw_text=raw_text)
    runner.run(ctx)

    dto = ctx.recruiter_output or {}

    # Format into a clean, intuitive schema for easy comparison
    timeline = dto.get("timeline", [])
    unresolved = dto.get("unresolved_events", [])
    all_events = timeline + unresolved

    work_experience = []
    education = []

    for ev in all_events:
        item = {
            "id": ev.get("id"),
            "title": ev.get("title") or "",
            "company": ev.get("org") or "",
            "start_date": ev.get("start") or "",
            "end_date": ev.get("end") or "",
            "duration": ev.get("duration") or "",
            "is_current": bool(ev.get("is_present")),
            "status": ev.get("status"),
            "confidence": ev.get("confidence"),
            "quote": ev.get("quote", "")[:200]
        }
        if ev.get("type") == "EDUCATION":
            education.append(item)
        else:
            work_experience.append(item)

    projects = []
    for p in dto.get("projects", []):
        projects.append({
            "id": p.get("id"),
            "name": p.get("name") or "",
            "client": p.get("client") or "",
            "role": p.get("role") or "",
            "duration": p.get("duration") or "",
            "details": p.get("details", [])
        })

    gaps = []
    for g in dto.get("gaps", []):
        if g.get("state") == "POTENTIAL_GAP":
            gaps.append({
                "id": g.get("id"),
                "start": g.get("start_label") or g.get("start"),
                "end": g.get("end_label") or g.get("end"),
                "months": g.get("months"),
                "state": g.get("state"),
                "confidence": g.get("confidence")
            })

    output = {
        "file_name": filename,
        "doc_id": doc_id,
        "candidate_name": dto.get("candidate_name") or "",
        "status": dto.get("status", "PARTIAL"),
        "quality": dto.get("quality", {}),
        "work_experience": work_experience,
        "projects": projects,
        "education": education,
        "gaps": gaps,
        "total_work_experience_entries": len(work_experience),
        "total_projects_entries": len(projects),
        "total_gaps_detected": len(gaps),
        "raw_pipeline_dto": dto
    }
    return output


def process_single(file_path, output_dir=None):
    try:
        data = parse_resume_to_json(file_path)
        if output_dir:
            out_file = Path(output_dir) / f"{Path(file_path).stem}.json"
            out_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return Path(file_path).name, True, data
    except Exception as exc:
        return Path(file_path).name, False, str(exc)


def main():
    parser = argparse.ArgumentParser(description="Batch Parse Resumes into JSON")
    parser.add_argument("--input", "-i", help="Single resume file path (.pdf, .docx, .txt)")
    parser.add_argument("--output", "-o", help="Output JSON path (for single file)")
    parser.add_argument("--input-dir", help="Directory containing resumes to parse")
    parser.add_argument("--output-dir", help="Directory where parsed JSONs will be saved")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers (default: 4)")
    args = parser.parse_args()

    if args.input:
        in_path = Path(args.input)
        if not in_path.exists():
            print(f"Error: File {in_path} does not exist.")
            sys.exit(1)
        data = parse_resume_to_json(in_path)
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(json_str)
            print(f"Saved JSON output to {args.output}")
        else:
            print(json_str)
        return

    if args.input_dir:
        in_dir = Path(args.input_dir)
        if not in_dir.is_dir():
            print(f"Error: Directory {in_dir} does not exist.")
            sys.exit(1)

        out_dir = Path(args.output_dir or (in_dir / "parsed_json"))
        out_dir.mkdir(parents=True, exist_ok=True)

        supported = (".pdf", ".docx", ".doc", ".txt")
        files = [p for p in in_dir.iterdir() if p.suffix.lower() in supported and not p.name.startswith("~$")]
        total = len(files)
        print(f"Found {total} resumes to parse in {in_dir}.")
        print(f"Writing parsed JSON files to {out_dir} using {args.workers} workers...")

        start_time = time.time()
        success = 0
        failed = 0

        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(process_single, f, out_dir): f for f in files}
            for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                name, ok, res = fut.result()
                if ok:
                    success += 1
                else:
                    failed += 1
                    print(f"[{i}/{total}] FAILED {name}: {res}")
                if i % 50 == 0 or i == total:
                    elapsed = time.time() - start_time
                    rate = i / max(1, elapsed)
                    print(f"Progress: {i}/{total} ({i*100//total}%) | Success: {success} | Failed: {failed} | Speed: {rate:.1f} resumes/sec")

        total_time = time.time() - start_time
        print(f"\nFinished batch processing {total} resumes in {total_time:.1f} seconds ({total/max(1, total_time):.1f} resumes/sec).")
        print(f"Successfully saved {success} JSON files to: {out_dir}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()

