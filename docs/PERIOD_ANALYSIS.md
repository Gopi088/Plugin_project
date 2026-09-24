# Work, project and education periods

The existing twelve-stage pipeline and the `check_all_resumes` / `check_resume_score`
commands now assess **work experience (including internships), projects and education**.

For each category, the JSON reports individual source-linked periods, dated-entry
counts, unique represented calendar months, overlapping months, and the states
`month_range`, `year_range`, `single_date`, `duration_only`, `undated`, `ambiguous`
and `invalid`. Category-specific unrepresented periods are calculated only when
all entries in that category have reliable month-level ranges. A break between
projects or education entries does not establish an employment gap.

Calendar months are inclusive: January–March represents three months. Overlapping
work/project/study intervals count once in the combined total. July completion
followed by an October start leaves two intervening months. A single completion
date is not a study tenure; “six months” without dates cannot be located on a
calendar. Year-only dates retain their precision and do not produce exact month
totals. Present/current endpoints use the current calendar month. Reversed periods
and OCR-derived uncertainty are reported rather than treated as confirmed coverage.

Explicitly dated projects are included before timeline reconciliation, including
project blocks nested under work experience. They can cover a period between jobs
without turning project clients into employers or borrowing project dates as an
employer's tenure. Undated education no longer removes dated projects from coverage.
Unplaced activity IDs remain attached to potential-gap evidence. Employment-only
scope is retained when other dated activities add no coverage beyond employment.

## Run

```bash
./check_all_resumes
./check_all_resumes --file "Abhishek" --limit 10
./check_resume_score "Abhishek"
```

The default prediction folder is `model_parsed_periods/` when present, otherwise
`model_parsed_1500_audited/`. Select another folder explicitly:

```bash
./check_all_resumes --model-dir model_parsed_periods
```

Reports: `all_resumes_scores.csv` (separate counts and months for all categories),
`accuracy_tiers.json` (full period diagnostics for every record), and
`docs/ACCURACY_TIERS_AND_DIAGNOSTICS.md` (category totals). Historical report
filenames remain for compatibility; the displayed percentage now means **the
share of extracted entries with usable date ranges**, not extraction accuracy.
A resume without jobs is not automatically downgraded if its education/projects
have dated periods. Missing categories or dates are not automatically parser errors.

New parses include `period_analysis` in batch JSON and recruiter API output.
Saved records calculate the same summary when read. Existing stored timeline/gap
results must be reanalyzed to apply the updated project coverage; reading them does
not rerun the parser. The legacy timeline adapter also exposes education durations,
`activity_gaps`, and the combined period summary.

## Verification

```bash
PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m unittest tests.test_periods
PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m unittest discover -s tests
```

Regression cases cover work/project/education overlap, project or education
coverage between jobs, nested project evidence, student-only profiles, ongoing
periods, adjacency, year-only/completion dates, durations without calendar placement,
reversed periods and category-specific two-month breaks.
