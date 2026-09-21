# Backend — Resume Timeline & Gap Detection API

Stdlib only (`http.server` + `sqlite3`). No framework to install.

## Run

```bash
venv/bin/python backend/server.py [--port 8000] [--db backend/data/store.db]
curl http://127.0.0.1:8000/health
```

## API (extension-facing; internals stay hidden)

| Method | Path | Body → Result |
|---|---|---|
| POST | `/api/documents` | `{filename, content_b64?, text?, source_url?, source?}` → `{doc_id, status}` |
| GET | `/api/documents/{id}/status` | overall + per-stage status/confidence |
| GET | `/api/documents/{id}/timeline` | recruiter DTO: timeline, gaps, unresolved, disclaimer |
| GET | `/api/documents/{id}/evidence?gap_id=G` or `?event_id=E` | lineage chain Gap→Event→Entry→Assoc→Mention→Block→Resume |
| GET | `/api/documents/{id}/stages` | full stage results (input/output/status/evidence/confidence/errors) |
| POST | `/api/documents/{id}/feedback` | `{dismissed_gap_ids[], overrides[], notes?}` → stored, applied on read |
| GET | `/health` | `{ok, model_versions}` |

Overall status: `SUCCESS` / `PARTIAL` (ambiguity, unresolved items) / `FAILED`
(empty/malformed). Gap states: `POTENTIAL_GAP` / `NO_GAP_DETECTED` /
`INSUFFICIENT_EVIDENCE`. A gap means *no clearly represented activity* —
never unemployment (asserted in code, tested).

## Layout

- `datamodel.py` — entities, stage envelope, reason codes, API contracts
- `dates.py` — deterministic date extraction/normalization (precision kept, nothing invented)
- `intervals.py` — union/coverage/gap math (overlaps unioned, never errors)
- `evidence.py` — confidence propagation + lineage builder
- `pipeline/stages.py` — the 12 stages, each `run(ctx) -> StageResult`
- `pipeline/runner.py` — ordering, FAILED→SKIPPED propagation, exception guard
- `pipeline_context.py` — shared artifacts + lookups
- `ml_assist.py` — optional `model_timeline` hints (discounted, recorded, never required)
- `docstore.py` — sqlite: documents, stages, events, gaps, lineage, feedback
- `server.py` — HTTP API + CORS for the extension

## Tuning without code changes

All vocabularies live in `data/cues.json` (sections, company suffixes, title/
degree words, present words, stop words, thresholds) and `data/skills.json`.
Edit the JSON and restart the server — no code edits needed. Override path via
`RT_CUES_PATH` env var (used by tests). Validate with
`venv/bin/python -m unittest tests.test_cues`.

## Monitoring / audit

Every stage result (status, confidence, errors, warnings, output summary) is
persisted per document; recruiter dismissals/overrides are versioned rows in
`feedback`. Evaluate with `venv/bin/python eval/metrics.py` (v1 labels in
`eval/labels.py`).
