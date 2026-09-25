"""Entry identity and project boundaries must not depend on one CV template."""
import pytest

from tests.test_stages import run_text


SAP_ROLES = """Jul 2022-Jan 2024: SAP Labs, Bengaluru as Software Developer Associate in AI
Feb 2022-Jul 2022: SAP Labs as Intern"""


@pytest.mark.parametrize('heading', ['', 'WORK EXPERIENCE\n'])
def test_same_employer_distinct_roles_with_shared_boundary_month(heading):
    ctx = run_text(heading + SAP_ROLES)
    work = [e for e in ctx.events if e.type in {'EMPLOYMENT', 'INTERNSHIP'}]
    assert {(e.type, e.org, e.title, e.start, e.end) for e in work} == {
        ('EMPLOYMENT', 'SAP Labs', 'Software Developer Associate in AI', (2022, 7), (2024, 1)),
        ('INTERNSHIP', 'SAP Labs', 'Intern', (2022, 2), (2022, 7)),
    }
    assert len(work) == 2
    assert all(e.source['title'] and e.source['company'] and e.source['dates'] for e in work)


def test_same_title_separate_tenures_and_overlapping_different_roles_survive():
    ctx = run_text('''WORK EXPERIENCE
Developer, Alpha Ltd, Jan 2020 - Dec 2021
Developer, Alpha Ltd, Dec 2021 - Dec 2022
Consultant, Alpha Ltd, Jan 2021 - Nov 2022
Developer, Alpha Ltd, Jan 2020 - Dec 2021
''')
    work = [e for e in ctx.events if e.type == 'EMPLOYMENT']
    assert len(work) == 3  # Only the repeated identical fact is a duplicate.


@pytest.mark.parametrize('heading', ['Projects & Research', 'Personal Projects', 'Open Source Contributions'])
@pytest.mark.parametrize('markup', ['', '**', '### '])
def test_title_and_bullet_projects_without_optional_fields(heading, markup):
    names = ['Document Search', 'Forecast Explorer', 'Tiny Compiler',
             'Sensor Dashboard', 'Graph Toolkit', 'Image Catalog']
    def title(name):
        return markup + name + ('**' if markup == '**' else '')
    text = heading + '\n' + '\n'.join(
        title(name) + '\n• Built and tested the implementation.\n'
        '  Continued the description on a wrapped line.\n- Published documentation.'
        for name in names)
    text += '\nEDUCATION\nB.Tech, Example University, 2018 - 2022\n'
    ctx = run_text(text)
    projects = ctx.recruiter_output['projects']
    assert [p['name'] for p in projects] == names
    assert all(p['client'] == p['role'] == p['duration'] == '' for p in projects)
    assert all(p['source']['entry'] for p in projects)
    events = [e for e in ctx.events if e.type == 'PROJECT']
    assert len(events) == 6
    assert all(e.org == '' and e.start is None and e.end is None for e in events)
    assert not any(e.type in {'EMPLOYMENT', 'INTERNSHIP'} for e in ctx.events)


def test_labeled_and_unlabeled_projects_share_one_section():
    ctx = run_text('''PROJECTS
Project: 1
Client Name: Example Inc
Role: Developer
Duration: Jan 2021 - Dec 2021
Details:
• Built services.
**Search Toolkit**
• Built indexing in 2022.
Features:
• Supports several file types.
Project: 2
Client Name: Another Ltd
Role: Analyst
Duration: Jan 2022 - Dec 2022
• Analyzed data.
''')
    projects = ctx.recruiter_output['projects']
    assert len(projects) == 3
    assert [(p['client'], p['role'], p['duration']) for p in projects] == [
        ('Example Inc', 'Developer', 'Jan 2021 - Dec 2021'),
        ('', '', ''),
        ('Another Ltd', 'Analyst', 'Jan 2022 - Dec 2022'),
    ]
    assert projects[1]['name'] == 'Search Toolkit'
    assert 'Features:' in projects[1]['details']
    assert not any(e.type in {'EMPLOYMENT', 'INTERNSHIP'} for e in ctx.events)


def test_project_subheadings_and_bullets_do_not_create_projects():
    ctx = run_text('''PROJECTS
Project: Portal
Details:
• Built APIs.
Roles & Responsibilities:
1. Developer coordination
2. Reviewed code
Outcome:
• Improved latency.
''')
    assert len(ctx.entries) == 1
    assert len(ctx.recruiter_output['projects']) == 1


def test_description_subheadings_do_not_replace_titles_or_split_wrapped_bullets():
    ctx = run_text("""Personal Projects
**Translation Toolkit**
Technologies: Python
Project Description:
A tool that supports document conversion.
Key Contributions:
• Built support for multiple file formats and
continued the same bullet here
• Published documentation.
**Search Portal**
Project Overview:
• Built search.
""")
    assert [p['name'] for p in ctx.recruiter_output['projects']] == [
        'Translation Toolkit', 'Search Portal']
    assert all(p['client'] == p['role'] == p['duration'] == ''
               for p in ctx.recruiter_output['projects'])


def test_dated_project_headings_remain_in_project_section():
    ctx = run_text("""PROJECTS
**Developer Tools | Jan 2021 - Dec 2021**
• Built testing utilities.
**Research Platform | Jan 2022 - Dec 2022**
• Built an analysis pipeline.
""")
    assert len(ctx.recruiter_output['projects']) == 2
    assert not any(e.type in {'EMPLOYMENT', 'INTERNSHIP'} for e in ctx.events)
    assert all(p['duration'] == '' for p in ctx.recruiter_output['projects'])


@pytest.mark.parametrize('body', [
    'Built a reusable tool for analyzing source code.',
    'Currently developing a reusable analysis library.',
    'Mentoring a student on evaluation methods.',
    'This application collects measurements and makes them available to a team of researchers through a searchable catalog and reporting interface.',
])
def test_styled_project_headings_can_introduce_prose(body):
    ctx = run_text('Personal Projects\n**Analysis Tool**\n' + body +
                   '\n**Data Catalog**\n' + body)
    assert [p['name'] for p in ctx.recruiter_output['projects']] == ['Analysis Tool', 'Data Catalog']
    assert all(p['client'] == p['role'] == p['duration'] == ''
               for p in ctx.recruiter_output['projects'])


def test_aakriti_pdf_expected_roles_and_six_projects():
    import json
    from pathlib import Path
    from backend.pipeline_context import PipelineContext
    from backend.pipeline import runner

    fixture = Path(__file__).resolve().parents[1] / 'dataset/test_samples/AakritiAggarwal.pdf'
    expected = json.loads(fixture.with_suffix('.expected.json').read_text())
    ctx = runner.run(PipelineContext('aakriti-regression', fixture.name, raw_bytes=fixture.read_bytes()))
    work = [e for e in ctx.events if e.type in {'EMPLOYMENT', 'INTERNSHIP'}]
    assert len(work) == expected['work_count']
    sap = [e for e in work if e.org == 'SAP Labs']
    assert sorted((e.type, e.title, list(e.start), list(e.end)) for e in sap) == [
        (e['type'], e['title'], e['start'], e['end']) for e in expected['sap_roles']]
    assert any(e.org == 'IBM Watsonx' and e.is_present for e in work)
    projects = ctx.recruiter_output['projects']
    assert [p['name'] for p in projects] == expected['project_names']
    assert len([e for e in ctx.events if e.type == 'PROJECT']) == 6
    assert all(p['client'] == p['role'] == p['duration'] == '' for p in projects)
    assert all(p['source']['entry'] for p in projects)
    assert all(e.source['dates'] and e.source['company'] for e in sap)
