import contextlib
import io
import unittest
from backend.periods import analyze_record, period
from backend.pipeline_context import PipelineContext
from backend.pipeline import runner
from scripts.analyze_tiers import diagnose_resume
from scripts.check_resume import display_resume_diagnostic


class TestPeriods(unittest.TestCase):
    def test_all_categories_overlap_union(self):
        result=analyze_record({
            'work_experience':[{'start':'2020-01','end':'2020-12'}],
            'projects':[{'duration':'Jul 2020 - June 2021'}],
            'education':[{'start':'2019-01','end':'2020-06'}]})
        self.assertEqual(result['represented_months'],30)
        self.assertEqual([g['dated_periods'] for g in result['categories'].values()],[1,1,1])
        self.assertEqual(result['categories']['education']['represented_months'],18)

    def test_partial_dates_and_duration_do_not_invent_month_coverage(self):
        for item,state in [({'duration':'6 months'},'duration_only'),
                           ({'duration':'2014 - 2018'},'year_range'),
                           ({'date_label':'2018'},'single_date'),({},'undated'),
                           ({'start':'2024-03','end':'2023-01'},'invalid'),
                           ({'start':'2020-01','end':'2020-12','status':'AMBIGUOUS'},'ambiguous')]:
            with self.subTest(item=item): self.assertEqual(period(item)['state'],state)
        self.assertEqual(analyze_record({'projects':[{'duration':'6 months'}]})['represented_months'],0)

    def test_student_without_jobs_is_not_penalized(self):
        d=diagnose_resume('student',{'education':[{'start':'2020-01','end':'2023-12'}],
                                    'projects':[{'duration':'Jan 2023 - June 2023'}]},'Student')
        self.assertEqual(d['score'],1)
        self.assertEqual(d['education_count'],1)
        self.assertNotIn('HEADING_OR_ASSOCIATION_MISSED',d['category'])

    def test_project_covers_job_gap_even_with_undated_education(self):
        text='''Jane Doe
WORK EXPERIENCE
Engineer, Alpha Ltd, Jan 2020 - Dec 2021
Engineer, Beta Ltd, Jan 2023 - Dec 2024
PROJECTS
Project: Migration
Duration: Jan 2022 - Dec 2022
EDUCATION
B.Tech, University
'''
        ctx=PipelineContext('all','resume.txt',raw_text=text);runner.run(ctx)
        self.assertNotIn('POTENTIAL_GAP',[g.state for g in ctx.gaps])
        self.assertEqual(ctx.recruiter_output['period_analysis']['categories']['projects']['dated_periods'],1)
        self.assertTrue(next(e for e in ctx.events if e.type=='PROJECT').source['dates'])

    def test_education_covers_job_gap(self):
        text='''Jane Doe
WORK EXPERIENCE
Engineer, Alpha Ltd, Jan 2020 - Dec 2021
Engineer, Beta Ltd, Jan 2023 - Dec 2024
EDUCATION
M.Tech, University, Jan 2022 - Dec 2022
'''
        ctx=PipelineContext('education','resume.txt',raw_text=text);runner.run(ctx)
        self.assertNotIn('POTENTIAL_GAP',[g.state for g in ctx.gaps])

    def test_individual_report_includes_education_without_crashing(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            display_resume_diagnostic('student',{'education':[{'title':'B.Tech','start':'2020-01','end':'2024-06'}]})
        self.assertIn('EDUCATION EXTRACTED (1 items)',output.getvalue())
        self.assertIn('education: 1/1 dated',output.getvalue())

    def test_nested_project_dates_do_not_become_employer_tenure(self):
        text='''Jane Doe
WORK EXPERIENCE
Engineer, Alpha Ltd
Project: Portal
Duration: Jan 2020 - Dec 2020
Client: Example Ltd
EDUCATION
B.Tech, University, 2016 - 2019
'''
        ctx=PipelineContext('nested','resume.txt',raw_text=text);runner.run(ctx)
        jobs=[e for e in ctx.events if e.type=='EMPLOYMENT']
        self.assertTrue(jobs)
        self.assertTrue(all(e.start is None for e in jobs))
        projects=[e for e in ctx.events if e.type=='PROJECT' and e.start]
        self.assertEqual(len(projects),1)
        self.assertEqual(projects[0].start,(2020,1))
        self.assertTrue(projects[0].source['dates'])

    def test_present_and_adjacent_periods(self):
        p=period({'start':'2020-01','is_current':True})
        self.assertEqual(p['state'],'month_range')
        result=analyze_record({'education':[{'start':'2020-01','end':'2020-06'}],
                               'projects':[{'duration':'Jul 2020 - Dec 2020'}]})
        self.assertEqual(result['represented_months'],12)

    def test_category_breaks_are_calendar_months_not_employment_claims(self):
        result=analyze_record({'education':[{'start':'2018-10','end':'2020-06'},
                                            {'start':'2014-08','end':'2018-07'}]})
        group=result['categories']['education']
        self.assertEqual(group['unrepresented_periods_in_category'],
                         [{'start':[2018,8],'end':[2018,9],'months':2}])
        uncertain=analyze_record({'education':[{'start':'2014','end':'2018'},{}]})
        self.assertFalse(uncertain['categories']['education']['all_entries_month_precise'])
        self.assertEqual(uncertain['categories']['education']['unrepresented_periods_in_category'],[])
