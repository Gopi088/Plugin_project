import unittest
from pathlib import Path
from backend.pipeline_context import PipelineContext
from backend.pipeline.stages import s01_document_processing


class TestDocumentInput(unittest.TestCase):
    def test_text_upload(self):
        text = 'WORK EXPERIENCE\nDeveloper at Example Ltd January 2020 to December 2022\n' * 4
        ctx = PipelineContext('test', 'resume.txt', raw_bytes=text.encode('utf-8-sig'))
        s01_document_processing(ctx)
        self.assertIn('Developer at Example', ctx.raw_text)
        self.assertNotIn('\ufeff', ctx.raw_text)

    def test_pdf_download_names(self):
        raw = Path('dataset/resumes/GopalPrasad K.pdf').read_bytes()
        for name in ('resume.pdf?token=123', 'download'):
            with self.subTest(name=name):
                ctx = PipelineContext('test', name, raw_bytes=raw)
                result = s01_document_processing(ctx)
                self.assertNotEqual(result.status, 'FAILED')
                self.assertGreater(len(ctx.raw_text), 100)
