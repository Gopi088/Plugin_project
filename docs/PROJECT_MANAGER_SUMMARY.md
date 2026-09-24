# Resume Timeline & Gap Detection — manager briefing

Reviewed September 23, 2026.

## Purpose

The system helps recruiters reconstruct a candidate's career from a resume, identify potential unrepresented periods, and verify the supporting evidence in the original document. A potential gap means the resume does not clearly represent activity for those months. It does not establish unemployment or dishonesty.

## Technology and components

| Component | Implementation | Responsibility |
|---|---|---|
| Timeline engine | Python, deterministic rules, regular expressions, calendar-month intervals | Recognize career entries, associate dates, reconcile overlaps, calculate potential gaps |
| Document extraction | pdfplumber / pdfminer.six; python-docx; optional Tesseract / antiword | Read PDF, DOCX, DOC and TXT; recover scanned pages and retain original evidence locations |
| Optional NLP assistance | spaCy and the local `model_timeline` model when available | Supply recorded hints; deterministic logic makes timeline decisions |
| Local API and storage | Python `http.server`, SQLite | Run analysis, store results, evidence, review state and resume notes |
| Recruiter interface | Chrome Manifest V3 extension, JavaScript, HTML and CSS | Timeline cards, gap overview, eye/review controls, source verification and notes |
| Native PDF integration | Source-coordinate mapping and optional Chrome debugger permission | Highlight evidence in the already-open PDF without opening another copy or reloading it |
| Batch processing | Python process workers, JSON output | Run the same pipeline across a folder of resumes |
| Validation | Python unittest, Node assertions, Chrome browser tests | Check calendar logic, evidence, persistence, API and browser flows |
| Separate resume editor | Browser ES modules / IndexedDB; adapter to local Resume Matcher service | Upload, edit structured resumes, preserve drafts and export PDFs |

The core twelve-stage timeline engine does **not** use an LLM. The separate resume-editor integration can use Resume Matcher's configured model and PDF renderer; it is not the engine evaluated by the 1,554-record batch run. Its service must be configured and running separately. The timeline API normally runs on port 8000; the Matcher adapter defaults to port 8001.

## How an analysis works

The extension sends the opened document or extracted source text to the local API. The original twelve stages remain:

| Stage | Work performed |
|---|---|
| 1. Document processing | Extract text and document/source information; detect unreadable input |
| 2. Text representation | Build normalized blocks and source links |
| 3. Section detection | Identify employment, education, projects and other sections |
| 4. Entry segmentation | Separate individual candidate activities |
| 5. Date extraction | Parse dates while retaining month/year precision |
| 6. Date association | Link dates to the entries they describe |
| 7. Event classification | Distinguish employment, internships, education and projects |
| 8. Timeline reconciliation | Resolve supported ordering and timeline relationships |
| 9. Coverage analysis | Combine overlapping dated intervals |
| 10. Gap detection | Identify supported unrepresented calendar months |
| 11. Confidence and evidence | Record uncertainty and evidence lineage |
| 12. Recruiter output | Produce timeline, gaps, unresolved items and quality information |

Results and evidence are saved in SQLite. Recruiters can inspect the existing timeline cards, hide items, mark items reviewed, and save a general resume note with author and timestamp. “View in Resume” follows the original evidence location. Missing or ambiguous information is retained as uncertainty rather than automatically completed.

For example, education ending in July 2018 followed by a job beginning in October 2018 leaves August and September unrepresented: **two months**, not 22 months. Adjacent calendar months do not create a gap.

## Audit findings and fixes

| Problem found | Correction |
|---|---|
| Reported 91.43% overall accuracy against raw extracted text | Separated source-text diagnostics from genuine labeled evaluation; overall accuracy is now explicitly unmeasured |
| Per-document “accuracy” derived from heuristic confidence, with positive defaults even for empty output | Removed fabricated document percentages; UI distinguishes the labeled benchmark from individual-resume accuracy |
| All 1,554 records counted as successful | Count actual `SUCCESS`, `PARTIAL` and `FAILED` statuses; retain failure records and return a failing batch exit status when needed |
| Loose word/year matching, ignored end dates and forced recall | Require normalized identity matches, compare both annotated endpoints, preserve date precision and score missed labels |
| Filename normalization lost nine comparisons; same-stem outputs could collide | Preserve filename identity and extensions; reject duplicates; report missing/unmatched records |
| Project activities exported as employment | Keep projects separate; retain genuine internship entries in work experience |
| Two different implementations of the batch adapter | Route CLI entry points through the same batch implementation and existing pipeline |
| Failure propagation could resume downstream after a failed prerequisite | Propagate blocked dependencies while allowing legitimate no-entry stages to produce insufficient-evidence output |
| DOCX tables extracted after all ordinary paragraphs | Preserve document order so table entries remain under their original section |
| External test script used hardcoded paths, omitted DOCX tables and failed files | Added input/output arguments, table extraction, distinct output names, input hashes and explicit status records |
| Two browser tests had missing root-path definitions | Repaired the test fixtures and executed the browser flows successfully |
| Activated Python pointed to an obsolete project path | Repaired environment launchers and added dependency preflight with interpreter diagnostics |
| Empty saved extractions despite readable originals | Added explicit original-file recovery with hashes and duplicate-name checks |
| Scanned PDFs and damaged DOCX packages | Local OCR with source rectangles; original body-XML recovery; uncertain output retained as PARTIAL |
| Workspace test accessed DOM before reload completed | Wait for the element to exist before asserting its text |

Original invalid summary reports are archived under `docs/audit/` for traceability. The old external script is preserved as `~/resume-timeline-test/test_resumes.py.pre-audit`.

## What the evaluation actually proves

The external project contained **1,554 saved text-extraction records**, not independently reviewed career answers. A fresh run of the corrected application produced:

| Measurement | Result |
|---|---:|
| Saved text records processed and paired | 1,554 |
| Pipeline `SUCCESS` | 789 |
| Pipeline `PARTIAL` | 765 |
| Pipeline `FAILED` | 0 |
| Missing predictions / unmatched predictions | 0 / 0 |
| Exported work entries, including internships | 4,721 |
| Exported education entries | 1,453 |
| Exported project blocks | 1,295 |
| Potential gaps produced | 597 |

These are operational counts, **not counts of independently verified correct answers**. The initial 18 empty records have now been recovered from supplied originals: 13 DOCX and five scanned PDFs. OCR-based entries remain uncertain. Partial status indicates ambiguity, incomplete reading or unresolved information; it must not be counted as either automatically correct or automatically wrong.

The diagnostic phrase check found 6,357 of 6,459 normalized phrases somewhere in source text, or **98.42% phrase occurrence**. This only measures whether a phrase appears. It cannot establish that a company was an employer, that dates belong to that company, that a gap is correct, or that the parser found every entry. There are 20 empty normalized reference texts and 62 records with diagnostic issues available for investigation.

The existing ten labeled regression cases currently achieve employment F1 = 1.0 and gap-duration F1 = 1.0, with zero failed cases. This is a small known regression set, not a representative production accuracy estimate. Its gap labels check duration rather than independently annotated gap locations. The separate batch evaluator supports matching both gap boundaries and duration when those labels are provided.

**The correct conclusion is that overall accuracy on the 1,554 resumes is not yet established.** The previous 91.43% and 87.5% values should not be presented as model accuracy to stakeholders.

## Validation and remaining limits

The complete **95-test regression suite passed** after repairing the environment, extraction recovery and browser reload race; details are in `docs/FAILURE_RECOVERY_REPORT.md`. It includes calendar-gap regressions, source mapping, actual Chrome PDF highlighting without navigation, notes persistence, API behavior, batch-evaluation regressions and the resume workspace flow. The external extractor was also exercised on PDF, DOCX with a table, TXT, empty input and malformed PDF; filenames did not collide and failures were retained.

The original folder was subsequently supplied. It contains **1,541 files**, a different set from the 1,554 snapshots. A direct original-file run with recovery retries produced **806 SUCCESS, 735 PARTIAL, zero FAILED**, including six legacy DOC files. Five scanned PDFs use local OCR; two damaged DOCX packages use original body XML recovery. These recovered documents remain uncertain. Browser tests cover local fixtures rather than every original; workspace tests use a controlled Matcher service fixture.

Image-only PDF pages now use local Tesseract OCR when installed; OCR results require verification and cannot generate automatic gap claims. Ambiguous layouts and incomplete dates still need recruiter judgment. Confidence values remain heuristics, not calibrated probabilities of correctness. Source-phrase mismatches may reflect extraction/normalization differences and require document review.

To publish a defensible production accuracy figure, independently label a representative held-out sample from the original files (or all 1,554 if claiming performance on the complete set). Record employers, both date endpoints, education, projects and both boundaries of each supported gap. Measure category precision, recall, F1 and date correctness with denominators; include missing predictions and failures. Review false positives and false negatives before adjusting rules, and keep a separate holdout to measure improvement.

## Suggested explanation to your manager

> We built a Python-based resume timeline engine with a Chrome recruiter interface. It uses twelve deterministic stages to extract career events, associate dates and identify potential unrepresented periods, with evidence linked back to the opened resume. Results, review state and notes persist in SQLite. We audited 1,554 saved resume records and fixed parsing, export and evaluation bugs. The previous accuracy percentage was misleading because its comparison data contained extracted text rather than verified answers. Our regression tests pass, but a defensible production accuracy percentage requires independently reviewed labels. The corrected reports make that distinction explicit.

See [batch evaluation instructions](BATCH_EVALUATION_GUIDE.md), [audit report](../accuracy_report.md), [all diagnostic issues](../accuracy_issues.json), and [fresh batch summary](../model_parsed_1500_audited/batch_summary.json).
