import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from backend import docstore, server

TEXT = 'WORK EXPERIENCE\nEngineer, Alpha Ltd Jan 2020 – Dec 2021\nEngineer, Beta Ltd Jan 2023 – Present'


class TestPersistentReview(unittest.TestCase):
    def test_reanalysis_and_reopen_preserve_notes_and_state(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'DB_PATH', str(Path(tmp)/'notes.db')):
            doc_id, _ = server._process('cv.txt', b'', TEXT, 'test')
            cx = docstore.connect(server.DB_PATH)
            dto = docstore.get_timeline(cx, doc_id)
            target = dto['timeline'][0]['id']
            data = {'id': 'request1', 'author': 'Recruiter One', 'text': 'Follow up about this role.'}
            notes = docstore.add_note(cx, doc_id, data)
            self.assertEqual(notes[0]['author'], 'Recruiter One')
            self.assertIsNotNone(datetime.fromisoformat(notes[0]['created_at']).tzinfo)
            self.assertEqual(len(docstore.add_note(cx, doc_id, data)), 1)
            docstore.save_item_state(cx, doc_id, {'target_id': target,'reviewed': True,'hidden': True})
            cx.close()
            again, _ = server._process('renamed.txt', b'', TEXT, 'test')
            self.assertEqual(doc_id, again)
            cx = docstore.connect(server.DB_PATH)
            try:
                dto = docstore.get_timeline(cx, doc_id)
                self.assertEqual(dto['notes'], notes)
                self.assertEqual(dto['item_state'][target], {'reviewed': True, 'hidden': True})
                self.assertEqual(len(dto['timeline']), 2)
            finally: cx.close()
            other, _ = server._process('cv.txt', b'', TEXT+'\nDifferent content', 'test')
            self.assertNotEqual(other, doc_id)

    def test_note_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cx = docstore.connect(str(Path(tmp)/'notes.db'))
            try:
                for data in ({'text':'x'}, {'author':'A','text':''}, {'author':2,'text':'x'}):
                    with self.assertRaises(ValueError): docstore.add_note(cx,'test',data)
            finally: cx.close()

    def test_notes_from_old_document_ids_remain_accessible(self):
        from backend.pipeline_context import PipelineContext
        from backend.pipeline import runner
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'DB_PATH', str(Path(tmp)/'notes.db')):
            cx = docstore.connect(server.DB_PATH)
            old = PipelineContext('old-random-id', 'cv.txt', raw_text=TEXT)
            runner.run(old)
            docstore.save_result(cx, old, 'SUCCESS')
            docstore.add_note(cx, old.doc_id, {'id':'old-note','author':'Jane','text':'Keep this note'})
            docstore.save_feedback(cx, old.doc_id, [], [], 'Older general note')
            cx.close()
            doc_id, _ = server._process('renamed.txt', b'', TEXT, 'test')
            server._process('renamed.txt', b'', TEXT, 'test')
            cx = docstore.connect(server.DB_PATH)
            try:
                notes = docstore.get_notes(cx, doc_id)
                self.assertEqual(len(notes), 2)
                self.assertEqual({n['text'] for n in notes}, {'Keep this note','Older general note'})
                self.assertTrue(all(n['created_at'] for n in notes))
            finally:
                cx.close()
