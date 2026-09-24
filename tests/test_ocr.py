import io
import unittest
from unittest.mock import patch
from PIL import Image
from backend.ocr import lines_from_tsv
from backend.pipeline import runner
from backend.pipeline_context import PipelineContext
from backend import source


class TestOCR(unittest.TestCase):
    def lines(self):
        header = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        texts = ['WORK EXPERIENCE', 'Engineer, Alpha Ltd, Jan 2020 - Dec 2021',
                 'Engineer, Beta Ltd, Jan 2023 - Dec 2024']
        tsv = header + '\n'.join(f'5\t1\t1\t1\t{i+1}\t1\t30\t{60+i*60}\t900\t30\t90\t{text}' for i,text in enumerate(texts))
        return lines_from_tsv(tsv, lambda s:s, 1, 600, 800, 3)

    def image_pdf(self):
        out = io.BytesIO()
        Image.new('RGB', (600, 800), 'white').save(out, format='PDF')
        return out.getvalue()

    def test_ocr_coordinates_preserve_original_page_scale(self):
        line = self.lines()[0]
        self.assertEqual(line['chars'][0], {'x0':10, 'top':20, 'x1':310, 'bottom':30})
        self.assertEqual(line['method'], 'ocr')

    def test_ocr_events_are_uncertain_and_cannot_create_gaps(self):
        ctx = PipelineContext('ocr', 'scan.pdf', raw_bytes=self.image_pdf())
        with patch('backend.ocr.extract_page', return_value=self.lines()):
            runner.run(ctx)
        self.assertEqual(len(ctx.events), 2)
        self.assertTrue(all(e.status == 'AMBIGUOUS' for e in ctx.events))
        self.assertEqual(ctx.recruiter_output['status'], 'PARTIAL')
        self.assertEqual([g.state for g in ctx.gaps], ['INSUFFICIENT_EVIDENCE'])
        self.assertEqual(ctx.events[0].source['entry'][0]['method'], 'ocr')
        self.assertEqual(ctx.events[0].source['entry'][0]['kind'], 'pdf')

    def test_missing_ocr_tool_is_reported_without_inventing_text(self):
        ctx = PipelineContext('ocr', 'scan.pdf', raw_bytes=self.image_pdf())
        with patch('backend.ocr.shutil.which', return_value=None):
            runner.run(ctx)
        self.assertEqual(ctx.stage_results['document_processing'].status, 'FAILED')
        self.assertIn('Tesseract', ctx.stage_results['document_processing'].warnings[0])
        self.assertFalse(ctx.events)
