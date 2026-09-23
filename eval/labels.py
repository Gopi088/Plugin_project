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
        "id": "abhishek_real",
        "file": "dataset/resumes/Abhishek Kumar Singh.pdf",
        "jobs": [
            {"org_sub": "Cavisson", "start": "2018-10", "end": "2021-05"},
            {"org_sub": "Impetus", "start": "2021-06", "end": "2024-12"},
            {"org_sub": "SLK", "start": "2025-01", "end": None},
        ],
        "gaps": [2],  # August–September 2018 after education ended in July
    },
    {
        "id": "gopal_real",
        "file": "dataset/resumes/GopalPrasad K.pdf",
        "jobs": [
            {"org_sub": "capgemini", "start": "2020-01", "end": "2022-06"},
            {"org_sub": "r1 rcm", "start": "2022-07", "end": "2025-02"},
            {"org_sub": "epam", "start": "2025-05", "end": "2025-09"},
        ],
        "gaps": [2],
        "gap_state": ["POTENTIAL_GAP"],  # gap in listed employment; education undated
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
        "gaps": [],
        "gap_state": ["INSUFFICIENT_EVIDENCE"],  # year-only education
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
        "gaps": [6],  # July–December; education→job is adjacent
    },
]

# Additional resumes manually checked for direct employer/date evidence.
CASES.extend([
    {"id":"hanashi_real","file":"dataset/resumes/Abhishek Hanashi.pdf",
     "jobs":[{"org_sub":"STARLITE","start":"2023-06","end":"2026-01"},
             {"org_sub":"CAPGEMINI","start":"2021-07","end":"2023-06"},
             {"org_sub":"ZEEL","start":"2020-06","end":"2021-05"}],
     "gaps":[1],"gap_state":["POTENTIAL_GAP"]},
    {"id":"jha_real","file":"dataset/resumes/Naukri_AbhishekkumarJha[5y_0m].pdf",
     "jobs":[{"org_sub":"Publicis","start":"2025-02","end":None},
             {"org_sub":"Mirafra","date_label":"2024 – 2025","precision":"year"},
             {"org_sub":"Chetu","date_label":"2022 – 2024","precision":"year"}],
     "gaps":[],"gap_state":["INSUFFICIENT_EVIDENCE"]},
    {"id":"tejesh_real","file":"dataset/resumes/K. Sai Tejesh.pdf",
     "jobs":[{"org_sub":"Wells Fargo","start":"2025-02","end":None},
             {"org_sub":"Genpact","start":"2023-11","end":"2025-01"},
             {"org_sub":"Accenture","start":"2021-05","end":"2023-11"},
             {"org_sub":"VASA","start":"2020-01","end":"2021-02"}],
     "gaps":[2],"gap_state":["POTENTIAL_GAP"]},
    {"id":"ayushi_real","file":"dataset/resumes/Ayushi Jain.pdf",
     "jobs":[],"gaps":[],"gap_state":["INSUFFICIENT_EVIDENCE"]},
])

from pathlib import Path
CASES.append({
    "id":"business_analyst_reported", "file":None,
    "text":(Path(__file__).parent/'fixtures/business_analyst_excerpt.txt').read_text(),
    "jobs":[
        {"org_sub":"Emids","start":"2025-04","end":None},
        {"org_sub":"Quess Corp Ltd","start":"2024-06","end":"2025-04"},
        {"org_sub":"Saksoft Ltd","start":"2023-04","end":"2024-02"},
        {"org_sub":"Wipro","start":"2020-12","end":"2023-03"},
        {"org_sub":"Wipro Ltd","start":"2018-07","end":"2020-12"}],
    "gaps":[3],"gap_state":["POTENTIAL_GAP"],
})
