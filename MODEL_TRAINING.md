# Model Training — resume timeline NER

## 1. Why a second model
Existing `model/` only knows `NAME / SKILL / EMAIL / PHONE` and is overwritten by three
competing trainers. Timeline needs `DEGREE, GRAD_DATE, JOB_DATE, COMPANY, JOB_TITLE, PROJECT`.
A separate `model_timeline/` keeps the old parser working while the timeline model learns
date/entity spotting from the 423 texts in `dataset/text/`.

## 2. Labels
| Label | Meaning | Weak-supervision source |
|---|---|---|
| `DEGREE` | education credential phrase | regex: `B.E / B.Tech / Bachelor / M.Tech / Master / MCA / MBA / BCA / Diploma / Ph.D / BE …` |
| `GRAD_DATE` | date/range inside EDUCATION window | date regex scoped to `EDUCATION…(EXPERIENCE|PROJECTS|SKILLS|$)` |
| `JOB_DATE` | date/range inside EXPERIENCE window | date regex scoped to `EXPERIENCE…(PROJECTS|EDUCATION|$)` + `Present|till date|current` |
| `COMPANY` | employer name | cue regex: `Worked at X`, `X Pvt|Ltd|Inc|Technologies|Solutions|…`, `Company:` lines |
| `JOB_TITLE` | role phrase | cue regex: `Engineer|Developer|Analyst|Manager|Consultant|Architect|Tester|Lead|…` bigrams |
| `PROJECT` | project header | lines under `PROJECTS` section that are short, title-case, non-bullet |

Overlaps are resolved by priority `GRAD_DATE > JOB_DATE > DEGREE > COMPANY > JOB_TITLE > PROJECT`
(keep earliest-starting, longest span on tie). This is weak supervision: expect noise, the
deterministic extractor in `scripts/timeline.py` owns the final gap math.

## 3. Data
- Source: all `dataset/text/*.txt` (423 files) — the converted `dataset/resumes/` corpus.
- Artefact: `dataset/timeline_training_data.json` (`{text, entities:[[start,end,label]]}`).
- Script logs per-label counts so you can see e.g. `JOB_DATE: 1200, GRAD_DATE: 300`.

## 4. Training
```
./venv/bin/python scripts/train_timeline.py --epochs 30 --out model_timeline
```
- Architecture: `spacy.blank("en")` + `ner` pipe, `begin_training`, `drop=0.3`, shuffle per epoch.
- Default 30 epochs is enough for weak labels; use `--epochs 10` for a smoke test.
- Saves spaCy model to `model_timeline/` (`config.cfg`, `ner/`, `vocab/` …).
- Existing `model/` is never touched.

## 5. How it is evaluated
1. **Entity spot-check**: `scripts/analyze_timeline.py <resume> --show-entities` prints model entities.
2. **Timeline fixtures** (deterministic, must pass):
   - `Sep 2012 – May 2016` + `JUN 2023 to JAN 2026` → graduation `2016-05`, job 31 months.
   - `Mar 2024` → `July 2024` job gap = `4` months.
   - `worked on 4 projects` + 1 described project → `claimed=4, described=1, unexplained=3`.
3. **Corpus sweep**: `analyze_timeline.py --sweep dataset/text` reports % resumes with graduation / ≥1 job.

## 6. Inference
```
./venv/bin/python scripts/analyze_timeline.py dataset/resumes/"A Suribhotla.pdf"
./venv/bin/python scripts/analyze_timeline.py dataset/text/A_suribhotla.txt --show-entities
```
Output = JSON from `TIMELINE_REQUIREMENTS.md §3` (graduation, jobs, gaps, totals, project coverage, warnings).
Dates → `(year, month)` month resolution; `Present` = today. Gap = month-index difference.

## 7. Limitations & next steps
- Weak labels inherit regex errors (e.g. a university name containing "Solutions" tagged COMPANY).
- `.doc` (old Word) files in `dataset/resumes/` are skipped — need `antiword`/`libreoffice` to convert.
- Recommended: hand-label ~100 spans with Prodigy/Doccano, add train/dev split + F1, then distil date parsing into the model instead of regex assist.
