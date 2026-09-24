# Batch evaluation and accuracy audit

The September 23, 2026 audit matched **1,554 saved reference records to 1,554 fresh predictions**. These references contain extracted text, not human-reviewed career labels. Therefore, the previous **91.43% overall accuracy** and **87.5% document accuracy** were not valid measurements. See [the corrected report](../accuracy_report.md) and [manager summary](PROJECT_MANAGER_SUMMARY.md).

## What the two projects do

- `~/resume-timeline-test/test_resumes.py` extracts PDF/DOCX/TXT text. Its JSON is useful for text diagnostics, but does not establish correct employment, date associations, education, or gaps.
- `scripts/batch_parse.py` runs this application's existing twelve-stage timeline pipeline. `parse_to_json.py` and `./parse_to_json` call the same implementation.
- `scripts/compare_accuracy.py` either compares independently annotated structured labels or runs explicitly limited source-text diagnostics. It never converts the pipeline's own confidence into measured accuracy.

The existing `~/resume-timeline-test/json_results/` directory is preserved. The corrected external script defaults to `json_results_v2/`. Its previous implementation is backed up as `test_resumes.py.pre-audit`.

## Reproduce the saved-text audit

Run from `~/resume_parser-app`:

```bash
PYTHONDONTWRITEBYTECODE=1 venv/bin/python scripts/batch_parse.py \
  --input-dir /home/gopal/resume-timeline-test/json_results \
  --originals-dir "/mnt/c/Users/Gopi Gedar/Eragina Digital Solutions Private Limited/Eragina Digital - Documents/RESUMES/resume/RESUMES_FLAT" \
  --output-dir model_parsed_1500_audited --workers 4

PYTHONDONTWRITEBYTECODE=1 venv/bin/python scripts/compare_accuracy.py \
  --pred-dir model_parsed_1500_audited \
  --gt-dir /home/gopal/resume-timeline-test/json_results \
  --report accuracy_report.md --summary-json accuracy_summary.json \
  --issues-json accuracy_issues.json
```

The batch command returns exit code **1 when any resume fails** while retaining each failure record and writing the summary. Continue to the comparator to inspect all results. Do not interpret the exit code as a missing batch output.

After recovering the 18 empty snapshots from the supplied originals: 789 `SUCCESS`, 765 `PARTIAL`, **0 `FAILED`**. Thirteen DOCX files supply text omitted by the old reference extractor; five PDFs use OCR and remain uncertain. The source check finds 6,357 of 6,459 normalized company/project/education phrases somewhere in the source text (98.42%). **This is phrase occurrence, not accuracy, recall, date correctness, or gap correctness.** The diagnostics identify 20 empty normalized reference texts and 62 records with diagnostic issues. An issue is a review lead, not automatically a parser error.

The user subsequently supplied the original Windows folder. It contains a different set of **1,541 files** (1,082 PDF, 453 DOCX, six DOC). A direct run plus recovery retries produced **806 SUCCESS, 735 PARTIAL, zero FAILED**; see `model_parsed_originals_audited/batch_summary.json`. Snapshot mode only reopens originals for empty snapshots when `--originals-dir` is supplied. Nonempty snapshots still use their saved extraction. The 20 empty reference texts are excluded from the phrase-occurrence denominator and reported separately; they are not human-reviewed answers.

## Test original files

Use a fresh output directory for each run, to avoid stale records from an earlier batch:

```bash
# Reference extraction, using that project's environment:
/home/gopal/resume-timeline-test/venv/bin/python \
  /home/gopal/resume-timeline-test/test_resumes.py \
  --input-dir /path/to/original/resumes \
  --output-dir /home/gopal/resume-timeline-test/json_results_v2

# Production parser: uses original files, including PDF source coordinates.
venv/bin/python scripts/batch_parse.py \
  --input-dir /path/to/original/resumes \
  --output-dir /path/to/fresh_predictions --workers 4

# Single document:
./parse_to_json /path/to/resume.pdf --output /tmp/resume_prediction.json
```

Both scripts process files directly within the supplied input directory. PDF, DOCX and UTF-8 TXT are supported. The application batch parser additionally supports legacy DOC with local `antiword` and image-only PDF pages with local `tesseract`. OCR entries preserve word rectangles, are marked uncertain, and cannot generate automatic gap claims. Broken DOCX relationships can fall back to original body XML with PARTIAL status. The external reference-text script remains a text extractor, not an OCR/label generator. The scripts preserve failures, retain extensions in output filenames, and preserve DOCX table order. For example, `Alex.pdf.json` and `Alex.docx.json` cannot overwrite each other.

Predictions include the original filename, input hash, input mode, pipeline status, stage statuses, errors, evidence sources, work entries (including internships), education, projects and potential gaps. Project events are not exported as employment.

## Establish actual accuracy

Create independent, human-reviewed labels from the original resumes. Do not generate the supposed answers with the parser being tested or with another text extractor. Define a representative held-out set including different layouts, scanned documents, tables, incomplete dates, overlapping jobs, and resumes without employment.

Example reference record:

```json
{
  "filename": "example.pdf",
  "work_experience": [
    {"company": "Alpha Ltd", "title": "Engineer", "start_date": "2020-01", "end_date": "2022-06"},
    {"company": "Beta Inc", "title": "Senior Engineer", "start_date": "2023-01", "end_date": "present", "is_current": true}
  ],
  "education": [],
  "projects": [],
  "gaps": [{"start": "2022-07", "end": "2022-12", "months": 6}]
}
```

An explicit empty list means the category was reviewed and contains no entries. An absent category means **unannotated**, so it is excluded from that category's metrics. Keep year-only dates year-only; never invent January. A missing end date is not `present`. Label gaps as unrepresented calendar months between supported events, not unemployment. For July 2018 completion and October 2018 employment, the intervening months are August and September: **2 months**.

```bash
venv/bin/python scripts/compare_accuracy.py \
  --pred-dir /path/to/fresh_predictions --gt-dir /path/to/reviewed_labels \
  --report /tmp/labeled_report.md --summary-json /tmp/labeled_summary.json \
  --issues-json /tmp/labeled_issues.json
```

Combined lists/maps are accepted with `--pred-file` and `--gt-file`. Every list item needs `filename`, `file_name`, or `resume_id`; list position is never used for pairing. Directory records may fall back to their JSON filename. Names are case-insensitive but punctuation and original extensions are preserved. Duplicate identities cause an error. Missing predictions remain in the evaluation and contribute missed labels; predictions without references are listed separately and cannot be scored as correct or incorrect without labels.

## Metric definitions and limits

| Result | Meaning |
|---|---|
| Category precision | Matched labeled identities / all predicted identities in annotated categories |
| Category recall | Matched labeled identities / all annotated identities |
| Category F1 | `2 TP / (2 TP + FP + FN)` |
| Date endpoint accuracy | Correct annotated start/end endpoints / all annotated endpoints, including missed entries |
| Project duration accuracy | Exact normalized duration matches / annotated project durations, including missed projects |
| Gap precision/recall/F1 | Match requires start month, end month **and** duration |

Employer identity requires the full normalized company name, project identity its full name, education identity its institution and degree. Case, punctuation and whitespace are normalized; generic shared words are insufficient. Repeated employer names are paired one-to-one, preferring matching dates. Employer aliases such as `Ltd` versus `Limited` require consistent reviewed labels; this conservative evaluator does not guess aliases. Job titles are used as a pairing tie-breaker, not separately scored. Dates normalize equivalent month formats, preserving precision; both endpoints are checked. `3 months` cannot match `13 months`. Categories with no applicable denominator return `null`, not an invented 100%.

No arbitrary weighted overall percentage is produced. Report the category metrics and their denominators. The separate `eval/metrics.py` checks ten existing regression cases; its headline is the mean of employment F1 and **gap-duration** F1. Its gap labels do not independently verify boundary locations, and its perfect current result is not evidence of 100% accuracy on 1,554 resumes. UI benchmark percentages are explicitly separate from individual-resume accuracy.

The archived invalid reports in `docs/audit/previous_*.json` exist only for audit history. Legacy predictions in `model_parsed_1500/` are superseded by `model_parsed_1500_audited/`; their old `document_accuracy` fields must not be used.


## Fixing the wrong Python environment

The reported `ModuleNotFoundError: pdfplumber/pypdfium2` failures came from a copied
activation script pointing to `/home/gopal/resume-parser/venv`, not this project.
The local activation scripts and executable launchers have been repaired. In an
already-open terminal, reactivate; the `(venv)` prompt alone does not prove which
Python is running:

```bash
cd /home/gopal/resume_parser-app
source venv/bin/activate
python scripts/check_environment.py
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 python eval/metrics.py
```

The environment checker prints the interpreter and checks all document libraries.
The benchmark prints an explicit percentage and exits nonzero if a case cannot be
processed. If dependencies are missing in a fresh environment, install them with
`venv/bin/python -m pip install -r requirements.txt`. Optional Ubuntu/WSL tools:
`sudo apt install tesseract-ocr tesseract-ocr-eng antiword`.

`--originals-dir` searches for an exact filename (case-insensitive), refuses
ambiguous duplicates, leaves reference files unchanged, and records the original
path and hash when recovering an empty snapshot. Without available readable
originals, empty records remain failed; they are never replaced by invented text.
