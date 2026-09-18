"""Manually labeled evaluation set (v1).

Fields per case:
  file: repo-relative PDF (or null for inline text)
  text: inline resume text when file is null
  jobs: expected [{title_sub, org_sub, start, end}] (YYYY-MM)
  gaps: expected sorted [months...] for POTENTIAL_GAP only
  gap_state: expected overall set, e.g. ["POTENTIAL_GAP"] or ["INSUFFICIENT_EVIDENCE"]
"""
CASES = [
    {
        "id": "gopal_real",
        "file": "dataset/resumes/GopalPrasad K.pdf",
        "jobs": [
            {"org_sub": "capgemini", "start": "2020-01", "end": "2022-06"},
            {"org_sub": "r1 rcm", "start": "2022-07", "end": "2025-02"},
            {"org_sub": "epam", "start": "2025-05", "end": "2025-09"},
        ],
        "gaps": [1, 3],
    },
    {
        "id": "pardha_fresher",
        "file": None,
        "text": "Pardha Fresher\nPROFESSIONAL SUMMARY\nCS undergraduate.\nPROJECTS\nApp One\n- built x.\nEDUCATION\nB.Tech, Data Science | 9.5 CGPA\n",
        "jobs": [],
        "gaps": [],
        "gap_state": ["INSUFFICIENT_EVIDENCE"],
    },
    {
        "id": "syn_overlap",
        "file": None,
        "text": ("Sam Over\nPROFESSIONAL EXPERIENCE\nDeveloper, Alpha Ltd, Jan 2020 to Dec 2022\n"
                 "Consultant, Beta Inc, June 2021 to June 2023\nEDUCATION\nMCA, Univ X, 2016 - 2019\n"),
        "jobs": [
            {"org_sub": "alpha", "start": "2020-01", "end": "2022-12"},
            {"org_sub": "beta", "start": "2021-06", "end": "2023-06"},
        ],
        "gaps": [1],  # education->first-job only; overlapping jobs => no gap
    },
    {
        "id": "syn_gap",
        "file": None,
        "text": ("Jane Gap\nPROFESSIONAL EXPERIENCE\nEngineer, Acme Pvt Ltd, Jan 2020 to June 2022\n"
                 "Senior Engineer, Beta Inc, Jan 2023 - Present\nEDUCATION\nB.Tech, Univ Y, 2015 - 2019\n"),
        "jobs": [
            {"org_sub": "acme", "start": "2020-01", "end": "2022-06"},
            {"org_sub": "beta", "start": "2023-01", "end": None},
        ],
        "gaps": [1, 7],  # education->job 1m + job->job 7m
    },
]
