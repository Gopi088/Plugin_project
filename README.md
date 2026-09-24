# Resume Timeline & Gap Detection

Browser extension + backend that reconstructs a candidate's career timeline from a resume and flags **potential unrepresented periods** — never unemployment claims. Recruiters get a year-grouped timeline with cards, original-resume evidence, and persistent notes.

## Full resume workspace (Resume Matcher integration)

Open **[Resume workspace](http://127.0.0.1:8000/workspace/)** after starting this
project's backend, or use **Resume editor & PDF export** in the extension popup.
The workspace adds drag-and-drop upload, full resume editing, dynamic custom
sections, category-filtered career timelines, persistent drafts and PDF export.

The configured local Matcher service is `http://localhost:8001/api/v1` (set
`RESUME_PARSER_API_URL` in `.env.local` or the environment). It handles model-based
structuring and month restoration. The existing recruiter pipeline and exact
original-resume evidence remain available. See [workspace setup and contracts](web/README.md).

## Architecture

| Part | Path | Stack |
|---|---|---|
| 12-stage pipeline | `backend/` | Python, PDF/DOCX extraction, stdlib HTTP/SQLite, optional spaCy hints |
| Browser extension (MV3) | `extension/` | vanilla JS, no build step |
| Legacy resume CLI | `scripts/`, `test_resume.py` | same venv |
| Tests + eval | `tests/`, `eval/` | `unittest`, node for JS checks |

Pipeline: document → text blocks → sections → entries → dates → association → events → reconciliation → coverage → gaps → confidence/evidence → recruiter DTO. Gap states are only `POTENTIAL_GAP` / `NO_GAP_DETECTED` / `INSUFFICIENT_EVIDENCE`.

## Setup (fresh laptop)

Prerequisites: **Python 3.12**, **Git**, **Chrome/Edge**, **Node 22+** (JS and real-browser tests).

```bash
git clone <repo-url> resume_parser-app
cd resume_parser-app

python3 -m venv venv
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt
```

> On Debian/Ubuntu, never use bare `pip install` (PEP 668 system error) — always `venv/bin/python -m pip`.

Verify using the explicit project interpreter (a copied virtual environment's
activation script may still point to its old folder):

```bash
venv/bin/python scripts/check_environment.py
PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 venv/bin/python eval/metrics.py
```

For scanned PDFs and legacy Word files, the extractor uses local optional tools:
`sudo apt install tesseract-ocr tesseract-ocr-eng antiword` on Ubuntu/WSL.
OCR-derived entries retain page rectangles, are marked uncertain, and do not
produce automatic gap claims. Missing tools are reported explicitly. Never
reuse a virtual environment from a different machine/path; create it at the
project path using the setup commands above.

## Run the backend

```bash
venv/bin/python backend/server.py
# → Resume Timeline API on http://0.0.0.0:8000
```

Check `http://127.0.0.1:8000/health` → `{"ok": true, ...}`. **Keep this terminal open.** After any `backend/` code change, restart it (`Ctrl+C`, run again) — Python loads code once at startup.

## Install the extension

1. `chrome://extensions` → **Developer mode ON** → **Load unpacked** → select the `extension/` folder.
2. Extension **Details** → turn **Allow access to file URLs** ON (needed for local PDFs).
3. Pin it. Open its popup → set **API base** (`http://127.0.0.1:8000` normally) → Save → Backend: **reachable**.

## Use it (3 ways)

1. **Auto (recommended):** open a resume PDF in Chrome → **Timeline** pill → panel analyzes automatically. If Chrome’s built-in PDF viewer hides the pill, click the pinned **Resume Timeline** extension icon: its popup analyzes the open file automatically.
2. **Popup upload:** extension icon → Choose File → Analyze file → summary inline + **Open timeline**.
3. **CLI (no browser):** `venv/bin/python test_resume.py "dataset/resumes/GopalPrasad K.pdf"`

Try the bundled samples in `dataset/resumes/` (e.g. `Abhishek Kumar Singh.pdf` → 3 jobs, 1 education entry, and a potential 2-month unrepresented period).

## Evaluate

```bash
venv/bin/python eval/metrics.py          # extraction, association, gap P/R, FPR, calibration
venv/bin/python scripts/analyze_timeline.py <resume> [--show-entities]
venv/bin/python scripts/analyze_profile.py <resume> --jd "<job-desc.pdf>"
```

Retrain the assist model: `venv/bin/python scripts/train_timeline.py --epochs 8` → `model_timeline/` (optional; pipeline works without it).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ERR_CONNECTION_REFUSED` at `127.0.0.1:8000` | Backend isn't running — start it and keep the terminal open |
| Windows Chrome + WSL backend refused | Admin PowerShell: `netsh interface portproxy add v4tov4 listenport=8000 listenaddress=127.0.0.1 connectport=8000 connectaddress=<WSL-IP>` (`hostname -I` in WSL); or set popup API base to `http://<WSL-IP>:8000` |
| Pill missing on local PDF | Enable **Allow access to file URLs**; reload extension; reopen file |
| Local file cannot be read | Reload the extension, enable **Allow access to file URLs** in its Details, and reopen the PDF. The extension reads the open file directly. |
| `table documents has N columns but M values` | Stale server — `Ctrl+C` and restart it (DB migrates itself) |
| `externally-managed-environment` on pip | Use `venv/bin/python -m pip ...`, never bare `pip` |
| `Manifest file is missing` on load unpacked | Select the `extension/` folder (the one containing `manifest.json`), not the project root |

## Layout

```
backend/          12-stage pipeline, API server, sqlite store
extension/        MV3 extension (api, background, viewmodel, content, popup, css)
scripts/          legacy parser/timeline CLI tools
model/            resume NER model (legacy CLI)
model_timeline/   timeline assist model (optional hints)
dataset/          sample resumes + texts
tests/            unittest suite (backend, API, extension checks)
eval/             hand-labeled cases + metrics
```

## Result percentages

**Evaluation accuracy** in the popup reports the mean of job and gap F1 on ten
labeled cases (six full resumes and four text cases, including the reported business-analyst excerpt), with the case
count and evaluation date. It is not verified accuracy for an individual resume.
No percentage is presented as a guarantee that the current resume is correct.

The extension reads local and online resume bytes in its background worker and
sends them to the configured backend after you click Timeline or open its popup
on a resume. HTTP/HTTPS host permissions also support signed download links and
browser credentials. Local file access still requires Chrome’s file-URL toggle.

## Calendar gaps and original evidence

Resume month ranges include both endpoint months. A July 2018 end followed by an
October 2018 start leaves **August–September 2018 (2 months)** uncovered. Adjacent
months, such as May–June, and overlapping activities do not create gaps. The
12-stage pipeline and CLI use this convention; gap labels show the uncovered
months rather than the occupied boundary months.

Each timeline card shows the role and dates, **View in Resume**, a
**✓ reviewed / ✕ not reviewed** checkbox, and an eye control to hide/show it.
Overview and Timeline tabs separate the views; Needs review appears only when an entry
has ambiguous dates or an actual employment entry lacks dates. Source details expand on demand.
Ambiguous dates remain visible as needing verification; dates are displayed as
written, including year-only ranges. Valid month/year formatting and an undated
degree are not date errors. Missing or ambiguous employment dates prevent
unsupported gap conclusions. When education is undated, job-to-job periods are
explicitly labeled as gaps in listed employment, not an absence of all activity.
The top summary gives each detected period, its duration and its bounding employers. Skills, client names and narrative project
achievements are not inferred employment.

**View in Resume** highlights the existing document without opening a duplicate.
HTML uses a snapshot of original DOM text nodes and Unicode offsets; accessible
PDF.js pages use preserved page coordinates. The action never navigates or
reloads the resume. For Chrome's built-in PDF viewer, click **Enable live PDF
highlighting** once and accept Chrome's optional debugging permission. The extension
briefly connects only to the bound resume tab, applies its unique original-text
anchors using the loaded PDF viewer, then disconnects. Chrome may show a temporary
debugging banner. This requires Chrome 125 or newer; unsupported viewer versions
show an error rather than navigating or selecting approximate text. Results stay in Chrome's side panel. Missing or
stale source locations produce an explicit message rather than an approximate match. Scanned pages without extractable text require OCR; the
pipeline marks incomplete reading instead of inventing evidence.

One collapsed **Resume notes** section stores author, text and a server-generated UTC date
and time, displayed in local time. Notes and review/visibility state persist in
SQLite across refresh and reanalysis of the same file contents. Earlier notes
for identical PDF/text sources are retained; missing historical authors are
grouped under collapsed Earlier notes, with their original dates retained. Unsaved note drafts are retained in extension storage.

Restart the backend, reload the extension, and **reanalyze existing documents**
after updating. Older stored results have neither corrected gap calculations nor
source anchors. Saved notes are preserved during reanalysis. Regression coverage includes the bundled Abhishek Kumar Singh PDF,
API persistence, and real headless Chrome review clicks and scrolling:

```bash
PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m unittest discover -s tests
```


## Batch audit and manager briefing

See [the manager briefing](docs/PROJECT_MANAGER_SUMMARY.md) for the architecture,
technology stack, audit fixes and validation limits, and [the batch guide](docs/BATCH_EVALUATION_GUIDE.md)
for reproducible commands and label requirements. The 1,554 saved extraction records
are source text, not independent ground truth: the previous 91.43% overall accuracy
claim was invalid. [The corrected report](accuracy_report.md) separates processing
statuses and source diagnostics from measured labeled metrics.
