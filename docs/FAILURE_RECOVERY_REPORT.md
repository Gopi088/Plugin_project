# Failure recovery — September 23, 2026

The pasted terminal output showed nine failures and five errors because the activated Python was not the project's Python. `venv/bin/activate` still referred to `/home/gopal/resume-parser/venv`. In this session that fell back to `/usr/bin/python`, which lacked PDF dependencies. The local activation files and executable launchers now point to `/home/gopal/resume_parser-app/venv`.

## Verified results

| Run | Success | Partial | Failed |
|---|---:|---:|---:|
| 1,554 saved records, with original-file recovery | 789 | 765 | 0 |
| 1,541 original PDF/DOCX/DOC files | 806 | 735 | 0 |

The original folder contains 1,082 PDFs, 453 DOCX files and six legacy DOC files. This is a different collection from the 1,554 saved reference records, so their counts must not be treated as identical datasets. The first original-file pass processed 1,535 PDF/DOCX files; recovery retries repaired seven failures and added the six DOC files. Final counts were recomputed from all saved per-document outputs.

The complete regression suite finished with **95 tests, zero failures and zero errors**, including browser tests. The ten labeled benchmark cases have zero failed cases and employment/gap-duration F1 = **100%**. This benchmark is not a representative estimate of accuracy on the larger collection.

## What was fixed

- Wrong interpreter after activation: repaired stale environment paths, declared rendering dependencies explicitly, and added `scripts/check_environment.py`.
- Missing dependencies now report the module, interpreter and installation command instead of causing unexplained empty timeline results.
- All 18 empty saved records were recovered from uniquely matched originals: 13 DOCX files and five scanned PDFs. Their reference records remain unchanged. Original path/hash is recorded in recovered predictions.
- Scanned PDFs use local Tesseract OCR inside the existing document-processing stage. Original page rectangles are preserved; OCR-derived entries are uncertain and cannot create automatic gap claims.
- `Arpitakhunntia.docx` and `lakshmikurmam.docx` have broken package relationships pointing at `NULL`. Their original body XML can be read without changing the source files. Output remains PARTIAL, and gap inference is suppressed for incomplete extraction.
- Six legacy DOC files are read with local `antiword`.
- The workspace browser regression now waits for DOM elements after reload, avoiding a null-element race.
- The evaluator now accepts the pipeline's `[year, month]` gap endpoints when comparing against ISO month labels. Empty reference text cannot verify recovered predictions and is excluded from phrase-occurrence denominators.

PARTIAL means uncertainty remains; it is not a synonym for either wrong or verified correct. Fixing file-processing failures does not prove every extracted career entry is correct. The 62 source-diagnostic records remain available for review in `accuracy_issues.json`; they are not failing unit tests.

## Commands to run now

```bash
cd /home/gopal/resume_parser-app
source venv/bin/activate
python scripts/check_environment.py
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 python eval/metrics.py
```

The benchmark prints `Labeled benchmark F1: 100.0% on 10 regression cases` for the currently passing fixtures. If parsing fails, it prints the errors and returns a nonzero exit status rather than claiming a percentage.

Reproduce the repaired 1,554-record batch:

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

Reproduce processing directly from all original files:

```bash
PYTHONDONTWRITEBYTECODE=1 venv/bin/python scripts/batch_parse.py \
  --input-dir "/mnt/c/Users/Gopi Gedar/Eragina Digital Solutions Private Limited/Eragina Digital - Documents/RESUMES/resume/RESUMES_FLAT" \
  --output-dir model_parsed_originals_audited --workers 4
```

The installed local Tesseract and antiword tools are used for scans and DOC files. On another Ubuntu/WSL machine install `tesseract-ocr`, `tesseract-ocr-eng` and `antiword`, plus the Python requirements. Restart any already-running backend after changing its code or environment.

## Why large-batch accuracy remains null

The comparison data has extracted text, not independently verified employers, dates and gaps. Its **98.42% source phrase occurrence** is not a correctness score. Recovery cannot turn that data into ground truth. The larger dataset's actual accuracy requires human-reviewed structured labels; the evaluator will report category precision, recall, F1 and date correctness when those labels are supplied. No per-resume accuracy is invented.

Reports: [comparison](../accuracy_report.md), [saved-record batch](../model_parsed_1500_audited/batch_summary.json), [original-file batch](../model_parsed_originals_audited/batch_summary.json), [small benchmark](../eval/latest.json).
