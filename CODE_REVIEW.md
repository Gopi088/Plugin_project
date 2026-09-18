# Code Review — resume_parser-app

Date: 2026-09-17 | Corpus inspected: `dataset/resumes/` (144 files: pdf/docx/doc), `dataset/text/` (423 .txt)

## What the project does today
- `scripts/extract_text.py`: pdf/docx → `dataset/text/*.txt`
- `scripts/generate_annotations.py` / `create_training_data.py` / `fix_annotations.py`: regex weak-labels → `annotations.json` / `training_data.json`
- `train_spacy.py` + `scripts/train.py` + `scripts/train_model.py`: three competing spaCy blank-`en` NER trainers → `model/`
- `scripts/resume_parser.py` (used by `test_resume.py`) and `scripts/parse_resume.py` (unused): two competing parsers → `output.json`
- `scripts/evaluate.py`: compares `output.json` vs `dataset/ground_truth.json`

## Findings (ordered by impact on your timeline goal)

### 1. No timeline capability exists (blocks your requirement)
- Education extraction is a stub (`resume_parser.py:269-274`): if `"bachelor"` in text → hardcoded `Bachelor of Technology`, institution/year always `""`. Graduation date is never extracted, so **graduation → first-job gap cannot be computed**.
- Experience date regex (`resume_parser.py:136-139`) only matches `YYYY - YYYY|Present` with optional 3-letter month:
  `r"(Jan|Feb|...)?\s*\d{4}\s*-\s*(Present|\d{4})"`. Real corpus needs more:
  - `July 2024 – Present`, `Feb 2025 - Present`, `05/2025 – Present`, `07/2023 – 10/2025`
  - `JUN 2023 to JAN 2026`, `April 2016 to till date`, `2014 – 2017`, `Sep 2012 – May 2016`
  - `Nov-Present`, `2023-2025 April`, `since June-2025 to Sep 2025`
  → most jobs are missed or durations are truncated.
- Job-to-job gaps, total experience, total gap time are never computed.
- Project logic (`extract_projects`, `resume_parser.py:180-234`) uses a fragile heuristic (≤6 words, capitalised, no trailing period). There is **no project-coverage signal** (e.g. "worked on 4 projects but described 1"). Your rule — *count every project mentioned, flagged explained vs. name-only* — is not implemented.

### 2. Two parsers, three trainers (pick one)
| File | Input | Output | Status |
|---|---|---|---|
| `scripts/resume_parser.py` | pdf only (pdfplumber) | name/email/phone/summary/skills/experience/education/projects | **used** by `test_resume.py`, richer but date logic broken |
| `scripts/parse_resume.py` | pdf/docx/txt | name/email/phone/linkedin/github/skills only | unused, no experience/education/projects |
| `train_spacy.py` | `dataset/train_data.py` (NAME/SKILL from filenames?) | `model/` | 50 epochs, `drop=0.3`, no eval |
| `scripts/train.py` | `dataset/annotations.json` (EMAIL/PHONE/SKILL) | `model/` | 40 epochs, bare `except: continue` hides errors |
| `scripts/train_model.py` | `dataset/training_data.json` (NAME/SKILL) | `model/` | 15 epochs, best-structured of the three |

All three overwrite the same `model/` directory with incompatible label sets. There is no train/test split, no precision/recall, no model versioning.

### 3. Weak labels are noisy
- `generate_annotations.py:15-19` skills list (15 items) vs `create_training_data.py:13-17` (21 items) vs `resume_parser.py:18-28` (28 items) — three vocabularies, model and parser disagree.
- Only the **first** occurrence of each skill is labelled (`generate_annotations.py:44`), so recall is artificially low.
- Overlapping spans (`spring` inside `spring boot`) handled in `create_training_data.py` but **not** in `generate_annotations.py`; `train.py` strips overlaps silently.
- `NAME = first line` assumption breaks on headers like `PROFILE / Backend Developer with 8 years...` (see `dataset/training_data.json[0]`).
- Phone regex (`\+?\d[\d -]{8,12}\d` and `\+?\d{10,15}`) also matches years (`2014 – 2017`), pincodes, IDs.

### 4. Robustness / portability bugs
- `resume_parser.py:5` `spacy.load("model")` at import time with a relative path — breaks when cwd differs; no `en_core_web_sm` fallback.
- `extract_text.py` has **two** copy-pasted main loops (lines 38-76 and 77-100): every file is converted twice; second loop re-introduces the `.doc`/textract path the first loop skipped. Hardcoded Windows path `input_folder = "/mnt/c/Users/Gopi Gedar/Desktop/resume"`; `import textract` is not in `requirements.txt` (fails on Linux).
- `create_training_data.py:62-87` dead code after `return` (second labelling block unreachable).
- `fix_annotations.py` phone regex `\+?\d{10,15}` matches digit runs inside emails/years.
- `evaluate.py` only checks one resume (`output.json`), exact-matches name/email/phone, substring-matches roles/companies — no timeline or date scoring.

## What was kept vs. changed for the timeline feature
- Kept: pdfplumber/txt extraction, spaCy NER approach, existing `model/` untouched.
- Added (new, non-breaking): `scripts/timeline.py` (deterministic timeline extractor), `scripts/train_timeline.py` (weak-supervision NER trainer → `model_timeline/`), `scripts/analyze_timeline.py` (CLI). See `TIMELINE_REQUIREMENTS.md` and `MODEL_TRAINING.md`.
