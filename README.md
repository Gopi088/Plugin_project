# Resume Timeline & Gap Detection

Browser extension + backend that reconstructs a candidate's career timeline from a resume and flags **potential unrepresented periods** — never unemployment claims. Recruiters get an attention-first side panel: summary card → tabs (Overview / Timeline / Review) → evidence on demand.

## Architecture

| Part | Path | Stack |
|---|---|---|
| 12-stage pipeline | `backend/` | stdlib only (`http.server` + `sqlite3`), spaCy assist optional |
| Browser extension (MV3) | `extension/` | vanilla JS, no build step |
| Legacy resume CLI | `scripts/`, `test_resume.py` | same venv |
| Tests + eval | `tests/`, `eval/` | `unittest`, node for JS checks |

Pipeline: document → text blocks → sections → entries → dates → association → events → reconciliation → coverage → gaps → confidence/evidence → recruiter DTO. Gap states are only `POTENTIAL_GAP` / `NO_GAP_DETECTED` / `INSUFFICIENT_EVIDENCE`.

## Setup (fresh laptop)

Prerequisites: **Python 3.12**, **Git**, **Chrome/Edge**, **Node 18+** (only for JS syntax tests).

```bash
git clone <repo-url> resume_parser-app
cd resume_parser-app

python3 -m venv venv
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt
```

> On Debian/Ubuntu, never use bare `pip install` (PEP 668 system error) — always `venv/bin/python -m pip`.

Verify:

```bash
venv/bin/python -m unittest discover -s tests
```

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
2. **Popup upload:** extension icon → Choose File → Analyze file → summary inline + *Open in page sidebar*.
3. **CLI (no browser):** `venv/bin/python test_resume.py "dataset/resumes/GopalPrasad K.pdf"`

Try the bundled samples in `dataset/resumes/` (e.g. `GopalPrasad K.pdf` → 3 jobs, gaps 1m + 3m).

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

Results show **extraction confidence** (the mean heuristic confidence of dated
entries) and **dated entry completeness**. These are not verified accuracy for
an individual resume. **Measured evaluation accuracy** is the mean of job and
gap F1 on the labeled evaluation set, with case count/date displayed. The bundled
report contains only four cases; its percentage is not a guarantee on new resumes.

The extension reads local and online resume bytes in its background worker and
sends them to the configured backend after you click Timeline or open its popup
on a resume. HTTP/HTTPS host permissions also support signed download links and
browser credentials. Local file access still requires Chrome’s file-URL toggle.
