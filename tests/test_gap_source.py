"""Calendar and original-PDF anchor regressions for Abhishek's resume."""
import tempfile
import unittest
from pathlib import Path

from backend import dates, docstore, source
from backend.pipeline import runner, stages
from backend.pipeline_context import PipelineContext
from scripts.timeline import analyze_resume_timeline

PDF = Path(__file__).resolve().parents[1] / 'dataset/resumes/Abhishek Kumar Singh.pdf'


class TestCalendarGaps(unittest.TestCase):
    def run_text(self, text):
        ctx = PipelineContext('calendar', 'resume.txt', raw_text=text)
        runner.run(ctx)
        return ctx

    def test_numeric_dates_and_exact_offsets(self):
        text = 'Education: 08/2014 – 07/2018 | First job: 10/2018 – 05/2021'
        mentions = dates.find_mentions(text)
        self.assertEqual([(m['start'], m['end']) for m in mentions],
                         [((2014, 8), (2018, 7)), ((2018, 10), (2021, 5))])
        for m in mentions:
            self.assertEqual(text[m['char_start']:m['char_end']], m['raw'])

    def test_gap_boundaries_and_adjacency(self):
        for start, expected in [('08/2018', []), ('07/2018', []), ('10/2018', [2]), ('01/2019', [5])]:
            with self.subTest(start=start):
                c = self.run_text(f'EDUCATION\nB.Tech, College 08/2014 – 07/2018\nWORK EXPERIENCE\nEngineer, Alpha Ltd {start} – 05/2021')
                gaps = [g for g in c.gaps if g.state == 'POTENTIAL_GAP']
                self.assertEqual([g.months for g in gaps], expected)
                for g in gaps:
                    self.assertEqual(g.start, [2018, 8])
                    self.assertEqual(dates.months_between(g.start, g.end) + 1, g.months)

    def test_nested_overlap_does_not_create_gap(self):
        c = self.run_text('WORK EXPERIENCE\nEngineer, Alpha Ltd 01/2018 – 12/2023\nEngineer, Beta Ltd 05/2019 – 07/2019\nEngineer, Gamma Ltd 01/2021 – 12/2022')
        self.assertEqual([g.state for g in c.gaps], ['NO_GAP_DETECTED'])


class TestOriginalSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = PipelineContext('abhishek', PDF.name, raw_bytes=PDF.read_bytes())
        runner.run(cls.ctx)

    def test_real_pdf_gap_and_legacy_cli(self):
        ctx = self.ctx
        self.assertEqual(len(ctx.stage_results), 12)
        self.assertEqual([(g.start, g.end, g.months) for g in ctx.gaps],
                         [([2018, 8], [2018, 9], 2)])
        jobs = [e for e in ctx.events if e.type == 'EMPLOYMENT' and e.start]
        self.assertEqual(sorted(e.start for e in jobs), [(2018, 10), (2021, 6), (2025, 1)])
        edu = next(e for e in ctx.events if e.type == 'EDUCATION')
        self.assertEqual((edu.start, edu.end), ((2014, 8), (2018, 7)))
        cli = analyze_resume_timeline(ctx.raw_text)
        self.assertEqual(cli['graduation_to_first_job_months'], 2)
        self.assertEqual(cli['job_gaps'], [])
        self.assertEqual(cli['total_gap_months'], 2)

    def test_original_pdf_coordinates_contain_exact_evidence(self):
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(self.ctx.raw_bytes)) as pdf:
            for event in self.ctx.events:
                self.assertTrue(event.source['entry'], event.id)
                for field in ('entry', 'dates', 'company'):
                    for loc in event.source[field]:
                        page = pdf.pages[loc['page'] - 1]
                        # Compare original glyphs inside the actual anchor rectangle;
                        # this catches wrong page, wrong entry and normalized-text search.
                        crop = page.crop(tuple(loc['bbox'])).extract_text() or ''
                        # pdfplumber crop includes touching bullet glyphs from a neighboring baseline.
                        compact = lambda s: ''.join(s.replace('•', '').split())
                        self.assertEqual(compact(crop), compact(loc['text']))
            edu = next(e for e in self.ctx.events if e.type == 'EDUCATION')
            self.assertEqual(edu.source['dates'][0]['page'], 2)
            job = next(e for e in self.ctx.events if 'Cavisson' in e.org)
            self.assertEqual(job.source['dates'][0]['page'], 1)
            self.assertEqual(job.source['company'][0]['text'], 'Cavisson Systems')

    def test_storage_roundtrip_and_rendered_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            cx = docstore.connect(str(Path(tmp) / 'test.db'))
            try:
                docstore.save_result(cx, self.ctx, 'SUCCESS')
                dto = docstore.get_timeline(cx, self.ctx.doc_id)
                self.assertEqual(dto['gaps'][0]['months'], 2)
                for event in dto['timeline'] + dto['unresolved_events']:
                    self.assertTrue(event['source']['entry'])
                    evidence = docstore.get_evidence(cx, self.ctx.doc_id, event_id=event['id'])
                    self.assertEqual(evidence['source'], event['source'])
                self.assertEqual(len(dto['gaps'][0]['evidence_details']), 2)
                for detail in dto['gaps'][0]['evidence_details']:
                    self.assertTrue(detail['source']['entry'])
                image = docstore.get_source_page(cx, self.ctx.doc_id, 2)
                self.assertTrue(image['image'].startswith('data:image/png;base64,'))
                with self.assertRaises(ValueError):
                    docstore.get_source_page(cx, self.ctx.doc_id, 3)
            finally:
                cx.close()

    def test_wrapped_range_retains_both_source_lines(self):
        c = PipelineContext('wrapped', 'resume.txt', raw_text='WORK EXPERIENCE\nEngineer, Alpha Ltd January 2020 to\nDecember 2022')
        runner.run(c)
        locs = c.events[0].source['dates']
        self.assertEqual(len(locs), 2)
        for loc in locs:
            self.assertEqual(c.meta['original_text'][loc['start']:loc['end']], loc['text'])

    def test_normalization_preserves_original_offsets(self):
        c = PipelineContext('normalized', 'resume.txt', raw_text='WORK EXPERIENCE\nSo\x00ware Engineer, Alpha Ltd Jan 2020 – Dec 2022')
        runner.run(c)
        loc = c.events[0].source['dates'][0]
        self.assertEqual(c.meta['original_text'][loc['start']:loc['end']], 'Jan 2020 – Dec 2022')
