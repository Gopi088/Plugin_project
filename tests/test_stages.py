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
        self.assertEqual(gaps, [1, 7])  # graduation->job 1m + job->job 7m

    def test_overlap_preserved_no_gap(self):
        ctx = run_text(OVERLAP_TEXT)
        dto = ctx.recruiter_output
        pot = [g for g in dto["gaps"] if g["state"] == "POTENTIAL_GAP"]
        # only the 1-month education->first-job gap; nothing between the
        # two overlapping employments
        self.assertEqual([g["months"] for g in pot], [1])
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


if __name__ == "__main__":
    unittest.main()
