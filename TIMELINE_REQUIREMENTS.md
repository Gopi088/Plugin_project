# Timeline Requirements — graduation, jobs, gaps, project coverage

## 1. Objective
From **any** resume (pdf/docx/txt) in `dataset/resumes/`, extract a career timeline:

1. **Graduation date** (end of highest/latest education).
2. **Each job** with `title / company / start / end`.
3. **Graduation → first-job gap** (months).
4. **Job-to-job gaps** (months between job N end and job N+1 start; negative = overlap).
5. **Totals**: total experience, total gap time, unexplained time.
6. **Project coverage**: how many projects the candidate *claims to have worked on* vs. how many are *actually described*. Rule requested by owner: **if a resume says "worked on 4 projects" but describes only 1, we count all 4 and flag 3 as unexplained.**

## 2. Definitions
| Term | Definition | Example |
|---|---|---|
| Graduation date | End date of the latest education entry (year, or month+year if present) | `May 2016` from `Sep 2012 – May 2016`; `2017` from `2013-2017` |
| Job start/end | Normalised to month resolution `(year, month)`; `Present / till date / current` → run date | `Feb 2025 – Present` → start `(2025,2)`, end = today |
| Gap (months) | `(start2.year*12+start2.month) - (end1.year*12+end1.month)`; `0` = back-to-back, negative = overlap | end `Mar 2024`, next start `July 2024` → gap `4` |
| Total experience | Sum of job durations (overlaps counted twice; reported alongside overlap warning) | — |
| Total gap | Sum of positive job-to-job gaps + graduation→first-job gap (if graduation known) | — |
| Claimed projects | Integer parsed from phrases like `worked on 4 projects`, `handled 5+ projects`, `3 projects` near experience/summary | `claimed=4` |
| Described projects | Entries parsed from PROJECTS section (name + bullets) | `described=1` |
| Unexplained projects | `max(0, claimed - described)` → flagged for recruiter follow-up | `4-1=3` |

## 3. Inputs / outputs
- Input: one resume file. Text via pdfplumber (pdf), python-docx (docx), plain read (txt).
- Output (JSON, see `scripts/timeline.py::analyze_resume_timeline`):
```json
{
  "graduation": {"label": "Bachelor of Technology", "date": "2016-05", "year": 2016, "month": 5},
  "jobs": [{"title": "...", "company": "...", "start": "2022-06", "end": "2024-03", "duration_months": 21}],
  "graduation_to_first_job_months": 74,
  "job_gaps": [{"from": "Job A", "to": "Job B", "gap_months": 2}],
  "total_experience_months": 60,
  "total_gap_months": 76,
  "projects": {"claimed": 4, "described": 1, "unexplained": 3, "items": [...]},
  "warnings": ["OVERLAP: ...", "UNEXPLAINED_PROJECTS: claimed 4, described 1"]
}
```

## 4. Date coverage (from real corpus)
Must parse: `2013-2017`, `Sep 2012 – May 2016`, `July 2024 – Present`, `Feb 2025 - Present`,
`05/2025 – Present`, `07/2023 – 10/2025`, `JUN 2023 to JAN 2026`, `April 2016 to till date`,
`2024 - 2025`, `May-2019 to May 2025`, `Nov-Present`, `2019–2020`, year-only `2015`.
Normalise en-dash/em-dash/`to`/`till`/`until`/`since`; month names full + 3-letter, case-insensitive.

## 5. Acceptance criteria
- [x] Fixtures pass: `Sep 2012 – May 2016` + job → graduation + gap math exact;
  `worked on 4 projects` + 1 described → `claimed=4, described=1, unexplained=3` + warning.
- [x] Corpus sweep (`analyze_timeline.py --sweep dataset/text`, 423 files, measured 2026-09-17):
  graduation found on 275 files (**65.0%**), ≥1 dated job on 309 files (**73.0%**).
  (Corpus contains offer letters/job descriptions without EDUCATION/WORK sections, so 100% is not expected.)
- [x] CLI `analyze_timeline.py <resume>` works for pdf/docx/txt without touching `model/`.

## 6. Non-goals
- No change to existing `model/` or `output.json` schema.
- No external date APIs; stdlib + regex only (offline training).
- NER model assists entity spotting; **gap arithmetic is deterministic**, never hallucinated by the model.
