"""False-positive regression set: assertions are against original resume evidence."""
from pathlib import Path
import unittest
from backend.pipeline_context import PipelineContext
from backend.pipeline import runner

ROOT = Path(__file__).resolve().parents[1]


def analyze(text):
    ctx = PipelineContext('grounding', 'resume.txt', raw_text=text)
    runner.run(ctx)
    return ctx


class TestGrounding(unittest.TestCase):
    def test_descriptions_and_skills_are_not_jobs(self):
        ctx = analyze('''WORK EXPERIENCE
Engineer, Alpha Ltd Jan 2020 – Dec 2022
Implemented services using multiple technologies.
TOOLS
Operating Systems: Linux
SPECIALIZED SKILLS
Led engineers to improve systems.
ENGINEERING INITIATIVES
Designed automation services in 2015 – 2018
''')
        self.assertEqual([(e.title, e.org) for e in ctx.events], [('Engineer', 'Alpha Ltd')])
        self.assertFalse(any(g.state == 'POTENTIAL_GAP' for g in ctx.gaps))

    def test_no_global_employment_inference(self):
        ctx = analyze('John Doe\nSKILLS\nEngineer at Alpha Ltd 2015 – 2018\nPROJECTS\nProject: App\nClient: Beta Ltd\n2019 – 2021')
        self.assertFalse(any(e.type in ('EMPLOYMENT','INTERNSHIP') for e in ctx.events))

    def test_ambiguous_dates_are_not_synthetic_intervals(self):
        for line in ['Jan 2020 and Jun 2022', 'Jan 2020 – Dec 2021 / Jan 2023 – Dec 2024']:
            ctx = analyze('WORK EXPERIENCE\nEngineer, Alpha Ltd '+line+'\nEngineer, Beta Ltd Jan 2025 – Present')
            event = next(e for e in ctx.events if e.org == 'Alpha Ltd')
            self.assertIsNone(event.start)
            self.assertIsNone(event.end)
            self.assertEqual(event.status, 'AMBIGUOUS')
            self.assertTrue(event.source['dates'])
            self.assertEqual([g.state for g in ctx.gaps], ['INSUFFICIENT_EVIDENCE'])

    def test_year_or_mixed_precision_does_not_invent_monthly_gaps(self):
        for dates in ['2020 – 2022', 'Jan 2020 – 2022', '2020 – June 2022']:
            ctx = analyze('WORK EXPERIENCE\nEngineer, Alpha Ltd '+dates+'\nEngineer, Beta Ltd Jan 2024 – Present')
            event = next(e for e in ctx.events if e.org == 'Alpha Ltd')
            self.assertEqual(event.precision, 'year')
            self.assertEqual(event.date_label, dates)
            self.assertFalse(any(g.state == 'POTENTIAL_GAP' for g in ctx.gaps))

    def test_unknown_activity_prevents_definite_gap(self):
        ctx = analyze('WORK EXPERIENCE\nEngineer, Alpha Ltd Jan 2020 – Dec 2021\nEngineer, Unknown Ltd\nEngineer, Beta Ltd Jan 2023 – Present')
        self.assertTrue(any(e.org == 'Unknown Ltd' and e.start is None for e in ctx.events))
        self.assertEqual([g.state for g in ctx.gaps], ['INSUFFICIENT_EVIDENCE'])

    def test_specialization_and_clients_are_not_employers(self):
        ctx = analyze('WORK EXPERIENCE\nSenior Software Engineer – AI & Java Full Stack 2024 – 2025\nMirafra Technologies (Client: Cisco Systems, USA), Bangalore\nBuilt applications.')
        self.assertEqual(len(ctx.events), 1)
        self.assertEqual(ctx.events[0].org, 'Mirafra Technologies')
        self.assertEqual(ctx.events[0].title, 'Senior Software Engineer')

    def test_actual_resumes_conservative_output(self):
        expected = {
            'Abhishek Kumar Singh': ['SLK Software','Impetus Technologies','Cavisson Systems'],
            'GopalPrasad K': ['EPAM Systems India Pvt Ltd','R1 RCM Global Pvt Ltd','Capgemini India Pvt Ltd'],
            'Abhishek Hanashi': ['STARLITE INFOTECH LIMITED','CAPGEMINI INDIA','ZEEL CODE LABS'],
            'Naukri_AbhishekkumarJha[5y_0m]': ['Publicis Sapient','Mirafra Technologies','Chetu India Pvt. Ltd'],
            'K. Sai Tejesh': ['Wells Fargo','Genpact','Accenture','VASA Services'],
            'Ayushi Jain': [],
        }
        for name, employers in expected.items():
            with self.subTest(resume=name):
                p = ROOT / 'dataset/resumes' / (name+'.pdf')
                ctx = PipelineContext('real', p.name, raw_bytes=p.read_bytes())
                runner.run(ctx)
                jobs = [e for e in ctx.events if e.type in ('EMPLOYMENT','INTERNSHIP')]
                self.assertEqual([e.org for e in jobs], employers)
                for event in ctx.events:
                    self.assertTrue(event.source['entry'])
                    if event.title: self.assertTrue(event.source['title'])
                    if event.org: self.assertTrue(event.source['company'])
                if name == 'Abhishek Kumar Singh':
                    self.assertEqual(len(ctx.events), 4)
                    self.assertEqual([(g.start,g.end,g.months) for g in ctx.gaps], [([2018,8],[2018,9],2)])
                elif name in ('GopalPrasad K','Abhishek Hanashi','K. Sai Tejesh'):
                    expected_months={'GopalPrasad K':2,'Abhishek Hanashi':1,'K. Sai Tejesh':2}
                    self.assertEqual([g.months for g in ctx.gaps], [expected_months[name]])
                    self.assertTrue(all(g.evidence['coverage_scope']=='employment' for g in ctx.gaps))
                else:
                    self.assertEqual([g.state for g in ctx.gaps], ['INSUFFICIENT_EVIDENCE'])
