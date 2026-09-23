"""Stage-level + pipeline tests on fixture texts.

Covers: dated career with gap, overlapping activities, ambiguous multi-date
entry, fresher without dates, and the never-claim-unemployed invariant.
"""
import unittest

from backend.pipeline_context import PipelineContext
from backend.pipeline import runner


def run_text(text, name="t.txt"):
    ctx = PipelineContext("t", name, raw_text=text, source="test")
    runner.run(ctx)
    return ctx


GAP_TEXT = """Jane Doe
PROFESSIONAL EXPERIENCE
Software Engineer, Acme Systems Pvt Ltd, Jan 2020 to June 2022
- Built APIs.
Senior Engineer, Beta Solutions Inc, Jan 2023 - Present
- Led team.
EDUCATION
B.Tech, Some University, 2015 - 2019
"""

OVERLAP_TEXT = """John Smith
PROFESSIONAL EXPERIENCE
Developer, Alpha Ltd, Jan 2020 to Dec 2022
Consultant, Beta Inc, June 2021 to June 2023
EDUCATION
MCA, Other University, 2016 - 2019
"""

FRESHER_TEXT = """Fresher Name
PROFESSIONAL SUMMARY
Computer Science undergraduate with project experience.
PROJECTS
Cool App
- Did things.
EDUCATION
B.Tech, Data Science | 9.1 CGPA
"""


class TestPipeline(unittest.TestCase):
    def test_gap_detected(self):
        ctx = run_text(GAP_TEXT)
        dto = ctx.recruiter_output
        self.assertEqual(dto["status"], "SUCCESS")
        self.assertEqual(len(dto["timeline"]), 3)  # 2 jobs + education
        gaps = sorted(g["months"] for g in dto["gaps"] if g["state"] == "POTENTIAL_GAP")
        self.assertEqual(gaps, [6])  # July–December; education→job is adjacent

    def test_overlap_preserved_no_gap(self):
        ctx = run_text(OVERLAP_TEXT)
        dto = ctx.recruiter_output
        pot = [g for g in dto["gaps"] if g["state"] == "POTENTIAL_GAP"]
        # Adjacent education/job and overlapping jobs have no uncovered months.
        self.assertEqual([g["months"] for g in pot], [])
        warns = ctx.stage_results["timeline_reconciliation"].warnings
        self.assertTrue(any("overlap" in w for w in warns))

    def test_fresher_insufficient_evidence(self):
        ctx = run_text(FRESHER_TEXT)
        dto = ctx.recruiter_output
        states = {g["state"] for g in dto["gaps"]}
        self.assertIn("INSUFFICIENT_EVIDENCE", states)
        # degree preserved even without a date (never silently dropped)
        self.assertTrue(any("B.Tech" in e.text for e in ctx.entries))

    def test_never_unemployed_vocabulary(self):
        import re
        claim = re.compile(r"(is|was|were|are|currently)\s+unemployed|unemployed\s+candidate", re.I)
        for text in (GAP_TEXT, OVERLAP_TEXT, FRESHER_TEXT):
            ctx = run_text(text)
            import json
            blob = json.dumps(ctx.recruiter_output).lower()
            self.assertIsNone(claim.search(blob))
            # the protective disclaimer must always be present
            self.assertIn("not evidence of unemployment", blob)

    def test_stage_envelopes(self):
        ctx = run_text(GAP_TEXT)
        self.assertEqual(set(ctx.stage_results), set(
            __import__("backend.datamodel", fromlist=["STAGES"]).STAGES))
        for name, res in ctx.stage_results.items():
            self.assertIn(res.status, ("SUCCESS", "PARTIAL", "FAILED", "SKIPPED"), name)

    def test_evidence_lineage(self):
        ctx = run_text(GAP_TEXT)
        self.assertTrue(ctx.lineage)
        for gid, chain in ctx.lineage.items():
            self.assertEqual(chain["doc_id"], "t")
            self.assertTrue(chain["links"])


    def test_employer_inherits_project_dates(self):
        text = """Candidate Name
PROFESSIONAL EXPERIENCE
Company: Infosys Technologies
Position: Software Engineer
Project: Health Portal
Duration: Jan 2021 - Dec 2022
- Built portal features.
Project: Claims Automation
Duration: Jan 2023 - May 2024
- Automated claims processing.
"""
        ctx = run_text(text)
        jobs = [e for e in ctx.events if e.type == "EMPLOYMENT"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "Software Engineer")
        self.assertEqual(jobs[0].org, "Infosys Technologies")
        self.assertEqual(jobs[0].start, (2021, 1))
        self.assertEqual(jobs[0].end, (2024, 5))
        self.assertEqual(jobs[0].status, "CONFIRMED")
        self.assertIn("ASSOC_PROJECT_DATES", jobs[0].reasons)

    def test_no_random_project_career_entries(self):
        text = """Chaitanya Developer
PROFESSIONAL EXPERIENCE
Senior Software Engineer – LTI Mindtree
Duration: June 26, 2025 – Present
Location: Hyderabad, India
Project-1: P&G – SharePoint Site Design
Duration : 1 Month
- Configured workflows.
• Created SharePoint Designer workflows for list-based automation.
Packaged Application Development Analyst - Accenture
Duration: Sept 3, 2021 – June 21, 2025
Location: Hyderabad, India
Project-3: Client – ASIA/Translator
Duration : Nov 2021 – June 2025
- Developed custom web parts.
"""
        ctx = run_text(text)
        jobs = [e for e in ctx.events if e.type == "EMPLOYMENT"]
        self.assertEqual(len(jobs), 2)
        titles = {j.title for j in jobs}
        self.assertIn("Senior Software Engineer", titles)
        self.assertIn("Packaged Application Development Analyst", titles)
        # Ensure project bullets or project headers never became separate employment entries
        self.assertFalse(any("Created SharePoint" in j.title for j in jobs))
        self.assertFalse(any("Project-1" in j.title or "Project-3" in j.title for j in jobs))

    def test_multi_work_experience_and_project_blocks(self):
        text = """A A ASHWINI
WORK EXPERIENCE
• Sonata Software Ltd : Dec 2023- till now
• Tiger Analytics : May 2022 – Nov 2023
• Tech Mahindra : July 2018- May 2019
PROJECTS and POCs:
POC: 1
Title: Intelligent Document Question Answering using RAG
• RAG details.
Project: 1
Client Name: Microsoft
Role: Senior Digital Engineer
Duration: Dec-23 to Dec-24
• Azure cloud services.
Project: 2
Client Name: KELLOGS
Role: Senior Analyst in DS
Duration: Apr-23 to Nov-23
• Analytics insights.
"""
        ctx = run_text(text)
        jobs = [e for e in ctx.events if e.type == "EMPLOYMENT"]
        self.assertEqual(len(jobs), 3)
        orgs = {j.org for j in jobs}
        self.assertIn("Sonata Software Ltd", orgs)
        self.assertIn("Tiger Analytics", orgs)
        self.assertIn("Tech Mahindra", orgs)

        # Projects verification
        projects = ctx.recruiter_output.get("projects", [])
        self.assertEqual(len(projects), 3)
        p1 = next(p for p in projects if p["client"] == "Microsoft")
        self.assertEqual(p1["duration"], "Dec-23 to Dec-24")
        self.assertEqual(p1["role"], "Senior Digital Engineer")
        p2 = next(p for p in projects if p["client"] == "KELLOGS")
        self.assertEqual(p2["duration"], "Apr-23 to Nov-23")

    def test_nested_project_duration_extraction(self):
        text = """Candidate Name
PROFESSIONAL EXPERIENCE
Senior Software Engineer – LTI Mindtree
Duration: June 26, 2025 – Present
Project-1: P&G – SharePoint Site Design
Duration : 1 Month
• Designed pages.
Project-2: SBLI – Modernization
Duration : 3 Months
• Modernized DMS.
"""
        ctx = run_text(text)
        projects = ctx.recruiter_output.get("projects", [])
        self.assertEqual(len(projects), 2)
        durs = [p["duration"] for p in projects]
        self.assertIn("1 Month", durs)
        self.assertIn("3 Months", durs)


if __name__ == "__main__":
    unittest.main()
