"""Batch the existing twelve-stage pipeline; parsing success is not accuracy."""
import argparse
import concurrent.futures
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from functools import partial

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.pipeline_context import PipelineContext
from backend.pipeline import runner


def parse_resume_to_json(file_path, doc_id=None, originals_dir=None):
    path = Path(file_path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    filename, text, mode = path.name, '', 'original_document'
    recovered_from = None
    if path.suffix.lower() == '.json':
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get('text'), str):
            raise ValueError('JSON input must be a text-extraction record')
        text = data['text']
        filename = data.get('filename') or path.name
        raw, mode = b'', 'text_snapshot'
        if not text.strip() and originals_dir:
            # Exact filename only. Never silently choose among duplicate originals.
            matches = [p for p in Path(originals_dir).rglob('*')
                       if p.is_file() and p.name.casefold() == str(filename).casefold()]
            if len(matches) > 1:
                raise ValueError(f'Ambiguous original file for {filename}: {len(matches)} matches')
            if matches:
                original = matches[0]
                if original.suffix.lower() not in {'.pdf', '.docx', '.doc', '.txt'}:
                    raise ValueError(f'Unsupported original file: {original.name}')
                raw = original.read_bytes()
                recovered_from = str(original.resolve())
                mode = 'recovered_original_document'
    elif path.suffix.lower() not in {'.pdf', '.docx', '.doc', '.txt'}:
        raise ValueError('Supported: PDF, DOCX, DOC (antiword required), UTF-8 TXT, text-extraction JSON.')
    ctx = PipelineContext(doc_id or digest[:24], filename, raw_bytes=raw, raw_text=text)
    runner.run(ctx)
    dto = ctx.recruiter_output or {}
    status = dto.get('status') or ('FAILED' if not ctx.raw_text.strip() else 'PARTIAL')
    work, education = [], []
    for event in dto.get('timeline', []) + dto.get('unresolved_events', []):
        if event.get('type') not in {'EMPLOYMENT', 'INTERNSHIP', 'EDUCATION'}:
            continue
        item = {
            'id': event.get('id'), 'type': event.get('type'),
            'company': event.get('org') or '', 'title': event.get('title') or '',
            'start_date': event.get('start') or '', 'end_date': event.get('end') or '',
            'is_current': bool(event.get('is_present')), 'status': event.get('status'),
            'confidence': event.get('confidence'), 'source': event.get('source', {}),
            'precision': event.get('precision'), 'date_label': event.get('date_label', ''),
        }
        (education if event['type'] == 'EDUCATION' else work).append(item)
    projects = dto.get('projects', [])
    gaps = [gap for gap in dto.get('gaps', []) if gap.get('state') == 'POTENTIAL_GAP']
    result = {
        'file_name': filename, 'input_mode': mode, 'input_sha256': digest,
        'doc_id': ctx.doc_id, 'candidate_name': dto.get('candidate_name', ''),
        'status': status, 'quality': dto.get('quality', {}),
        'work_experience': work, 'education': education, 'projects': projects, 'gaps': gaps,
        'total_work_experience_entries': len(work),
        'total_projects_entries': len(projects), 'total_gaps_detected': len(gaps),
        'stage_statuses': {key: value.status for key, value in ctx.stage_results.items()},
        'errors': [error for result in ctx.stage_results.values() for error in result.errors],
        'warnings': [warning for result in ctx.stage_results.values() for warning in result.warnings],
        'raw_pipeline_dto': dto,
    }
    if recovered_from:
        result['recovered_from'] = recovered_from
        result['original_sha256'] = hashlib.sha256(raw).hexdigest()
    if status == 'FAILED' and mode == 'text_snapshot' and not text.strip():
        result['errors'].insert(0, 'Reference extraction contains no text. Supply the original document with --originals-dir; use OCR if it is image-only.')
    from backend.periods import analyze_record
    result["period_analysis"] = analyze_record(result)
    return result


def process_single(file_path, output_dir=None, originals_dir=None):
    try:
        data = parse_resume_to_json(file_path, originals_dir=originals_dir)
    except Exception as exc:
        data = {
            'file_name': Path(file_path).name, 'status': 'FAILED', 'errors': [str(exc)],
            'work_experience': [], 'projects': [], 'education': [], 'gaps': [],
        }
    if output_dir:
        # Retain the original extension: Alice.pdf and Alice.docx never overwrite.
        destination = Path(output_dir) / (Path(file_path).name + '.json')
        destination.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    return Path(file_path).name, data['status'] != 'FAILED', data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?')
    parser.add_argument('--input', '-i')
    parser.add_argument('--input-dir')
    parser.add_argument('--output', '-o')
    parser.add_argument('--output-dir')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--originals-dir', type=Path, help='Recover empty text snapshots from uniquely matched original filenames')
    args = parser.parse_args()
    if args.originals_dir and not args.originals_dir.is_dir():
        parser.error('Originals directory does not exist')
    target = Path(args.input_dir or args.input or args.path or '.')
    if not (args.input_dir or args.input or args.path):
        parser.error('Provide a file or input directory')
    if args.workers < 1:
        parser.error('--workers must be positive')
    if target.is_file():
        _, _, data = process_single(target, originals_dir=args.originals_dir)
        result = json.dumps(data, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(result, encoding='utf-8')
        else:
            print(result)
        return 1 if data['status'] == 'FAILED' else 0
    if not target.is_dir():
        parser.error('Input directory does not exist')
    out = Path(args.output_dir or target / 'parsed_json')
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(
        path for path in target.iterdir()
        if path.is_file() and path.suffix.lower() in {'.pdf', '.docx', '.doc', '.txt', '.json'}
        and not path.name.startswith('~$')
        and path.name not in {'batch_summary.json', 'batch_accuracy_summary.json', 'all_results.json'}
    )
    if not files:
        parser.error('No supported input files')
    start = time.monotonic()
    statuses, counts = Counter(), Counter()
    recovered = 0
    process = partial(process_single, originals_dir=args.originals_dir)
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, (_, _, data) in enumerate(pool.map(process, files, [out] * len(files)), 1):
            statuses[data['status']] += 1
            recovered += int(data.get('input_mode') == 'recovered_original_document' and data['status'] != 'FAILED')
            for key in ('work_experience', 'education', 'projects', 'gaps'):
                counts[key] += len(data.get(key, []))
            if index % 100 == 0:
                print(f'{index}/{len(files)} processed')
    summary = {
        'total_resumes': len(files), 'status_counts': {key: statuses[key] for key in ('SUCCESS', 'PARTIAL', 'FAILED')},
        'recovered_from_originals': recovered,
        'elapsed_seconds': round(time.monotonic() - start, 2), 'extracted_counts': dict(counts),
        'overall_accuracy_pct': None,
        'accuracy_explanation': 'Parsing alone cannot measure accuracy. Independent reviewed labels are required.',
    }
    (out / 'batch_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 1 if statuses['FAILED'] else 0


if __name__ == '__main__':
    sys.exit(main())
