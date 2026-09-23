"""Regression excerpts from the reported resume; no contact/personal fields."""
import unittest
from backend.pipeline_context import PipelineContext
from backend.pipeline import runner

from pathlib import Path
EXCERPT = (Path(__file__).resolve().parents[1]/'eval/fixtures/business_analyst_excerpt.txt').read_text()


def analyze(text):
    ctx = PipelineContext('business', 'business.txt', raw_text=text)
    runner.run(ctx)
    return ctx


class TestBusinessAnalyst(unittest.TestCase):
    def test_real_headers_and_precise_gap(self):
        ctx = analyze(EXCERPT)
        jobs = [e for e in ctx.events if e.type == 'EMPLOYMENT']
        self.assertEqual([(e.title,e.org) for e in jobs], [
            ('Senior Business Analyst / Product Owner','Emids'),
            ('Senior Business Analyst','Quess Corp Ltd'),
            ('Senior Business Analyst','Saksoft Ltd'),
            ('IT Business Analyst','Wipro'),
            ('System Analyst','Wipro Ltd')])
        self.assertTrue(all(e.status=='CONFIRMED' for e in jobs))
        self.assertEqual((jobs[1].start,jobs[1].end),((2024,6),(2025,4)))
        self.assertEqual((jobs[2].start,jobs[2].end),((2023,4),(2024,2)))
        self.assertEqual(len(ctx.events),6)
        education = next(e for e in ctx.events if e.type=='EDUCATION')
        self.assertEqual((education.title,education.org),('Master Software Engineering','BITS Pilani'))
        self.assertIsNone(education.start)
        self.assertEqual(len(ctx.gaps),1)
        gap = ctx.gaps[0]
        self.assertEqual((gap.start,gap.end,gap.months),([2024,3],[2024,5],3))
        self.assertEqual(gap.evidence['coverage_scope'],'employment')
        self.assertEqual(gap.evidence['event_before'],jobs[2].id)
        self.assertEqual(gap.evidence['event_after'],jobs[1].id)
        for event in jobs:
            self.assertTrue(event.source['dates'])
            for field in ('entry','company','dates'):
                for location in event.source[field]:
                    self.assertEqual(EXCERPT[location['start']:location['end']],location['text'])

    def test_description_dates_do_not_override_job_dates(self):
        ctx = analyze('WORK EXPERIENCE\nLead Engineer, Alpha Ltd Jan 2020 – Dec 2022\nImplemented migration for records from Jan 2010 – Dec 2012\nTechnical Lead, Beta Ltd Jan 2023 – Present')
        self.assertEqual(len(ctx.events),2)
        self.assertTrue(all(e.status=='CONFIRMED' for e in ctx.events))
        self.assertEqual(ctx.events[0].date_label,'Jan 2020 – Dec 2022')
        self.assertEqual(ctx.gaps[0].state,'NO_GAP_DETECTED')
