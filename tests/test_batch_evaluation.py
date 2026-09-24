import json
import tempfile
import unittest
from pathlib import Path
from scripts.compare_accuracy import run_evaluation,structured_compare,normalize_date,compute_metrics
from scripts.batch_parse import process_single

class BatchEvaluationTests(unittest.TestCase):
    def test_exact_calendar_dates_and_both_endpoints(self):
        for s in ['Jan 2020','01/2020','2020-01']:self.assertEqual(normalize_date(s),'2020-01')
        self.assertNotEqual(normalize_date('2020'),normalize_date('Jan 2020'))
        self.assertNotEqual(normalize_date('13/2020'),'2020-13')
        p={'work_experience':[{'company':'Alpha','start_date':'2020-01','end_date':'2021-12'}]}
        g={'work_experience':[{'company':'Alpha','start_date':'Jan 2020','end_date':'Dec 2022'}]}
        c,issues=structured_compare(p,g)
        self.assertEqual((c['work_experience']['date_matches'],c['work_experience']['date_total']),(1,2))
        self.assertTrue(issues)
    def test_generic_words_and_durations_do_not_match(self):
        c,_=structured_compare({'projects':[{'name':'Cloud migration','duration':'13 Months'}]}, {'projects':[{'name':'Cloud migration','duration':'3 Months'}]})
        self.assertEqual(c['projects']['duration_matches'],0)
        c,_=structured_compare({'work_experience':[{'company':'Alpha Technologies'}]}, {'work_experience':[{'company':'Beta Technologies'}]})
        self.assertEqual(c['work_experience']['tp'],0)
    def test_same_employer_multiple_tenures(self):
        jobs=[{'company':'Alpha','start_date':'2020-01','end_date':'2021-12'},{'company':'Alpha','start_date':'2023-01','end_date':'2024-01'}]
        c,_=structured_compare({'work_experience':jobs[::-1]},{'work_experience':jobs})
        self.assertEqual(c['work_experience']['date_matches'],4)
    def test_missing_labels_are_not_perfect_scores(self):
        self.assertEqual(compute_metrics(0,0,0),(None,None,None))
        c,_=structured_compare({}, {'work_experience':[]})
        self.assertNotIn('projects',c)
    def test_pairing_and_raw_text_never_claim_accuracy(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'p.json';g=Path(t)/'g.json'
            p.write_text(json.dumps([{'filename':'a.pdf','work_experience':[{'company':'Invented Corp','title':'Engineer'}],'quality':{'document_accuracy':.99}}]))
            g.write_text(json.dumps([{'filename':'b.pdf','text':'Nothing'}, {'filename':'a.pdf','text':'Engineer at Real Company'}]))
            s,issues=run_evaluation(pred_file=p,gt_file=g)
            self.assertIsNone(s['overall_accuracy_pct']);self.assertEqual(s['missing_predictions'],['b.pdf'])
            self.assertEqual(s['source_text_diagnostics']['phrases_found'],0);self.assertTrue(issues)
            p.write_text(json.dumps([{'text':'no identity'}]))
            with self.assertRaises(ValueError):run_evaluation(pred_file=p,gt_file=g)
    def test_duplicate_identities_fail_loudly(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'p.json';p.write_text(json.dumps([{'filename':'a.pdf'},{'filename':'a.pdf'}]))
            with self.assertRaisesRegex(ValueError,'Duplicate'):run_evaluation(pred_file=p,gt_file=p)
    def test_failed_parse_and_filename_collision(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);p=root/'same.pdf';q=root/'same.txt';p.write_bytes(b'not PDF');q.write_text('')
            self.assertFalse(process_single(p,root)[1]);self.assertFalse(process_single(q,root)[1])
            self.assertTrue((root/'same.pdf.json').exists());self.assertTrue((root/'same.txt.json').exists())
            result=json.loads((root/'same.pdf.json').read_text());self.assertEqual(result['status'],'FAILED')
            self.assertEqual(result['stage_statuses']['gap_detection'],'SKIPPED')
            self.assertNotIn('document_accuracy',result['quality'])

    def test_no_events_still_produces_insufficient_evidence(self):
        from backend.pipeline_context import PipelineContext
        from backend.pipeline import runner
        ctx=PipelineContext('empty-career','resume.txt',raw_text='Jane Doe\nSKILLS\nPython, SQL\n')
        runner.run(ctx)
        self.assertTrue(ctx.recruiter_output)
        self.assertEqual(ctx.recruiter_output['gaps'][0]['state'],'INSUFFICIENT_EVIDENCE')

    def test_export_preserves_internships_and_excludes_projects_from_work(self):
        from unittest.mock import patch
        from scripts.batch_parse import parse_resume_to_json
        def fake_run(ctx):
            ctx.recruiter_output={'status':'SUCCESS','timeline':[
                {'id':'i','type':'INTERNSHIP','org':'Alpha'},
                {'id':'p','type':'PROJECT','org':'Project client'}]}
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'r.txt';p.write_text('Jane Doe')
            with patch('scripts.batch_parse.runner.run',side_effect=fake_run):
                data=parse_resume_to_json(p)
            self.assertEqual([e['type'] for e in data['work_experience']],['INTERNSHIP'])

    def test_equal_gap_duration_at_wrong_location_does_not_match(self):
        pred={'gaps':[{'start':'2024-03','end':'2024-05','months':3}]}
        gold={'gaps':[{'start':'2023-03','end':'2023-05','months':3}]}
        counts,_=structured_compare(pred,gold)
        self.assertEqual((counts['gaps']['tp'],counts['gaps']['fp'],counts['gaps']['fn']),(0,1,1))

    def test_failed_benchmark_case_cannot_display_perfect_score(self):
        import contextlib
        import io
        from unittest.mock import patch
        from eval import metrics
        case={'id':'unreadable', 'jobs':[], 'gaps':[]}
        with patch.object(metrics,'CASES',[case]), patch.object(metrics,'run_case',return_value={'status':'FAILED','timeline':[],'gaps':[]}), patch.object(metrics,'save_report'), contextlib.redirect_stdout(io.StringIO()):
            report=metrics.main()
        self.assertIsNone(report['overall_accuracy'])
        self.assertEqual(report['failed_cases'],['unreadable'])

    def test_empty_snapshot_recovers_only_from_unique_original(self):
        from scripts.batch_parse import parse_resume_to_json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            originals=root/'originals';originals.mkdir()
            snapshot=root/'resume.json'
            snapshot.write_text(json.dumps({'filename':'resume.txt','text':''}))
            (originals/'resume.txt').write_text('Jane Doe\nWORK EXPERIENCE\nEngineer, Alpha Ltd, Jan 2020 - Dec 2022\n')
            result=parse_resume_to_json(snapshot,originals_dir=originals)
            self.assertNotEqual(result['status'],'FAILED')
            self.assertEqual(result['input_mode'],'recovered_original_document')
            self.assertIn('original_sha256',result)
            self.assertEqual(json.loads(snapshot.read_text())['text'],'')
            nested=originals/'other';nested.mkdir()
            (nested/'resume.txt').write_text('different candidate')
            with self.assertRaisesRegex(ValueError,'Ambiguous original'):
                parse_resume_to_json(snapshot,originals_dir=originals)

    def test_empty_snapshot_without_original_stays_failed(self):
        from scripts.batch_parse import parse_resume_to_json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);snapshot=root/'missing.json'
            snapshot.write_text(json.dumps({'filename':'missing.pdf','text':''}))
            result=parse_resume_to_json(snapshot,originals_dir=root)
            self.assertEqual(result['status'],'FAILED')
            self.assertIn('--originals-dir',result['errors'][0])

    def test_empty_reference_cannot_verify_recovered_prediction(self):
        from scripts.compare_accuracy import source_compare
        counts,issues=source_compare({'work_experience':[{'company':'Alpha Ltd'}]}, {'text':''})
        self.assertEqual(counts['empty_source_documents'],1)
        self.assertEqual(counts['checked_phrases'],0)
        self.assertEqual(issues[0]['type'],'empty_source_text')

    def test_pipeline_gap_arrays_match_calendar_label_strings(self):
        pred={'gaps':[{'start':[2018,8],'end':[2018,9],'months':2}]}
        gold={'gaps':[{'start':'2018-08','end':'2018-09','months':2}]}
        counts,_=structured_compare(pred,gold)
        self.assertEqual(counts['gaps']['tp'],1)
        self.assertTrue(normalize_date([2020,13]).startswith('invalid:'))
