"""Auditable label evaluation or source-text diagnostics (never invented accuracy)."""
import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

GROUPS = {'work_experience': ('work_experience','experience','employment','jobs'),
          'projects': ('projects','personalProjects','project_entries'),
          'education': ('education',), 'gaps': ('gaps',)}
MONTHS={m:i+1 for i,m in enumerate(('january','february','march','april','may','june','july','august','september','october','november','december'))}
MONTHS.update({m[:3]:n for m,n in list(MONTHS.items())})
MONTHS['sept']=9


def clean_text(value):
    return ' '.join(re.sub(r'[^\w\s]', ' ', str(value or '').casefold()).split())


def normalize_date(value):
    if isinstance(value,(list,tuple)) and len(value)==2:
        year,month=value
        if type(year) is int and type(month) is int and 1900<=year<=2099 and 1<=month<=12:
            return f'{year:04d}-{month:02d}'
        return 'invalid:'+str(value)
    s=str(value or '').strip().lower()
    if s in {'present','current','now','till now','till date','ongoing'}:return 'present'
    if re.fullmatch(r'(19|20)\d{2}',s):return s
    m=re.fullmatch(r'((?:19|20)\d{2})[-/.](\d{1,2})',s)
    if m and 1<=int(m[2])<=12:return f'{m[1]}-{int(m[2]):02}'
    m=re.fullmatch(r'(\d{1,2})[-/.]((?:19|20)\d{2})',s)
    if m and 1<=int(m[1])<=12:return f'{m[2]}-{int(m[1]):02}'
    m=re.fullmatch(r'([a-z]+)[\s,./-]*((?:19|20)\d{2})',s)
    if m and m[1] in MONTHS:return f'{m[2]}-{MONTHS[m[1]]:02}'
    return 'invalid:'+s if s else ''


def field(item,*names):
    for name in names:
        if item.get(name) is not None:return str(item[name]).strip()
    return ''


def dates(item):
    start=next((item[k] for k in ('start_date','start','from') if item.get(k) is not None),'')
    end=next((item[k] for k in ('end_date','end','to') if item.get(k) is not None),'')
    return normalize_date(start), 'present' if item.get('is_current') is True else normalize_date(end)


def items(record,group):
    for key in GROUPS[group]:
        if key in record:
            value=record[key]
            if not isinstance(value,list) or any(not isinstance(x,dict) for x in value):
                raise ValueError(f'{key} must be a list of objects')
            return value
    return None


def identity(item,group):
    if group=='work_experience':return clean_text(field(item,'company','company_name','employer','org'))
    if group=='projects':return clean_text(field(item,'name','projectName','title','project_title'))
    if group=='education':return (clean_text(field(item,'institution','company','org')),clean_text(field(item,'degree','title')))
    return (*dates(item),str(item.get('months','')))


def compute_metrics(tp,fp,fn):
    precision=tp/(tp+fp) if tp+fp else None
    recall=tp/(tp+fn) if tp+fn else None
    f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
    return tuple(round(x,4) if x is not None else None for x in (precision,recall,f1))


def structured_compare(pred,truth):
    result={};mismatches=[]
    for group in GROUPS:
        gold=items(truth,group)
        if gold is None:continue  # Unannotated is not the same as labeled empty.
        guessed=items(pred,group) or []
        edges=[]
        for pi,p in enumerate(guessed):
            for gi,g in enumerate(gold):
                key=identity(g,group)
                if key and key!=('','') and identity(p,group)==key:
                    score=sum(a==b for a,b in zip(dates(p),dates(g)))
                    score+=int(clean_text(field(p,'title','role'))==clean_text(field(g,'title','role')))
                    edges.append((-score,pi,gi))
        used_p=set();used_g=set();matched=[]
        for _,pi,gi in sorted(edges):
            if pi not in used_p and gi not in used_g:
                used_p.add(pi);used_g.add(gi);matched.append((guessed[pi],gold[gi]))
        counts={'tp':len(matched),'fp':len(guessed)-len(matched),'fn':len(gold)-len(matched),
                'date_matches':0,'date_total':0,'duration_matches':0,'duration_total':0,'documents':1}
        for p,g in matched:
            if group in {'work_experience','education'}:
                for index,aliases in enumerate((('start_date','start','from'),('end_date','end','to'))):
                    if any(k in g for k in aliases) or (index==1 and 'is_current' in g):
                        counts['date_total']+=1
                        correct=dates(p)[index]==dates(g)[index] and not dates(g)[index].startswith('invalid:')
                        counts['date_matches']+=int(correct)
                        if not correct:mismatches.append({'type':'date_mismatch','group':group,'field':aliases[0],'predicted':dates(p)[index],'expected':dates(g)[index]})
            if group=='projects' and any(k in g for k in ('duration','project_duration','period')):
                counts['duration_total']+=1
                correct=clean_text(field(p,'duration','project_duration','period'))==clean_text(field(g,'duration','project_duration','period'))
                counts['duration_matches']+=int(correct)
                if not correct:mismatches.append({'type':'duration_mismatch','group':group})
        for pi,p in enumerate(guessed):
            if pi not in used_p:mismatches.append({'type':'extra_item','group':group,'identity':identity(p,group)})
        for gi,g in enumerate(gold):
            if gi not in used_g:
                mismatches.append({'type':'missed_item','group':group,'identity':identity(g,group)})
                if group in {'work_experience','education'}:
                    counts['date_total']+=sum(any(k in g for k in aliases) for aliases in (('start_date','start','from'),('end_date','end','to','is_current')))
                if group=='projects':counts['duration_total']+=int(any(k in g for k in ('duration','project_duration','period')))
        result[group]=counts
    if not result:raise ValueError('Reference has neither source text nor recognized labeled fields')
    return result,mismatches


def source_compare(pred,reference):
    """Literal phrase occurrence only: not identity, dates association, recall or F1."""
    if not isinstance(reference.get('text'), str):
        raise ValueError('Source text must be a string')
    text=' '+clean_text(reference['text'])+' '
    counts=Counter();issues=[]
    counts['empty_source_documents']=int(not text.strip())
    if not text.strip():
        return counts,[{'type':'empty_source_text','note':'Cannot verify predictions against an empty reference; excluded from phrase occurrence denominator.'}]
    for group in ('work_experience','projects','education'):
        for item in items(pred,group) or []:
            key=identity(item,group)
            phrases=[x for x in key if x] if isinstance(key,tuple) else [key] if key else []
            for phrase in phrases:
                counts['checked_phrases']+=1
                found=' '+phrase+' ' in text
                counts['phrases_found']+=int(found)
                if not found:issues.append({'type':'phrase_not_found','group':group,'phrase':phrase})
    counts['empty_source_documents']=int(not text.strip())
    if not text.strip():issues.append({'type':'empty_source_text'})
    return counts,issues


def record_key(record,fallback=None):
    name=record.get('file_name') or record.get('filename') or record.get('resume_id') or fallback
    if not name:raise ValueError('Each list record needs filename/file_name/resume_id; positional pairing is forbidden')
    return str(name).replace('\\','/').casefold()


def load_records(directory=None,filename=None):
    records={};ignored=[]
    def add(record,fallback=None):
        if not isinstance(record,dict):raise ValueError('Resume records must be objects')
        key=record_key(record,fallback)
        if key in records:raise ValueError(f'Duplicate resume identity: {key}')
        records[key]=record
    def consume(data,fallback=None):
        if isinstance(data,list):
            for value in data:add(value)
        elif isinstance(data,dict) and any(k in data for k in ('file_name','filename','resume_id','text',*GROUPS)):
            add(data,fallback)
        elif isinstance(data,dict):
            for key,value in data.items():add(value,key)
        else:raise ValueError('Input must contain resume records')
    if directory:
        for path in sorted(Path(directory).glob('*.json')):
            data=json.loads(path.read_text(encoding='utf-8'))
            if path.name in {'batch_accuracy_summary.json','batch_summary.json','accuracy_summary.json'}:
                ignored.append(path.name);continue
            consume(data,path.name.removesuffix('.json'))
    else:consume(json.loads(Path(filename).read_text(encoding='utf-8')))
    return records,ignored


def run_evaluation(pred_dir=None,gt_dir=None,pred_file=None,gt_file=None):
    predictions,pignored=load_records(pred_dir,pred_file);references,gignored=load_records(gt_dir,gt_file)
    if not references:raise ValueError('No reference records')
    raw={k for k,r in references.items() if 'text' in r and not any(key in r for keys in GROUPS.values() for key in keys)}
    if raw and len(raw)!=len(references):raise ValueError('Mixed raw text and structured labels: evaluate separately')
    common=predictions.keys() & references.keys()
    if not common:raise ValueError('No records share the same filename identity')
    source_totals=Counter();totals={};issues={}
    for key in sorted(references):
        pred=predictions.get(key,{})
        if key not in predictions:issues[key]=[{'type':'missing_prediction'}]
        if pred.get('status') in {'FAILED','ERROR'}:issues.setdefault(key,[]).append({'type':'failed_prediction'})
        if raw:
            counts,problems=source_compare(pred,references[key]);source_totals.update(counts)
        else:
            categories,problems=structured_compare(pred,references[key])
            for category,counts in categories.items():totals.setdefault(category,Counter()).update(counts)
        if problems:issues.setdefault(key,[]).extend(problems)
    metrics={}
    for category,c in totals.items():
        p,r,f=compute_metrics(c['tp'],c['fp'],c['fn'])
        metrics[category]={**c,'precision':p,'recall':r,'f1':f,
            'date_endpoint_accuracy_pct':round(100*c['date_matches']/c['date_total'],2) if c['date_total'] else None,
            'duration_accuracy_pct':round(100*c['duration_matches']/c['duration_total'],2) if c['duration_total'] else None}
    summary={'generated_at':datetime.now(timezone.utc).isoformat(),
        'evaluation_mode':'SOURCE_TEXT_DIAGNOSTICS' if raw else 'STRUCTURED_LABEL_EVALUATION',
        'overall_accuracy_pct':None,
        'accuracy_explanation':'Raw extraction is not labeled ground truth; accuracy, recall, F1 and gap correctness cannot be measured.' if raw else 'Use separately reported labeled-category metrics; no arbitrary weighted overall accuracy.',
        'reference_records':len(references),'prediction_records':len(predictions),'resumes_evaluated':len(common),
        'missing_predictions':sorted(references.keys()-predictions.keys()),'predictions_without_reference':sorted(predictions.keys()-references.keys()),
        'ignored_metadata_files':pignored+gignored,
        'failed_predictions':sum(r.get('status') in {'FAILED','ERROR'} for r in predictions.values()),
        'prediction_status_counts':dict(Counter(r.get('status','UNSPECIFIED') for r in predictions.values())),
        'resumes_with_diagnostic_issues':len(issues),'metrics':metrics}
    if raw:
        summary['source_text_diagnostics']={**source_totals,'literal_phrase_occurrence_pct':round(100*source_totals['phrases_found']/source_totals['checked_phrases'],2) if source_totals['checked_phrases'] else None,
            'definition':'Whole normalized phrase occurs somewhere in extraction. Does NOT establish employment, correct dates/association, completeness, or accuracy.'}
    return summary,issues


def generate_markdown_report(summary,mismatches,out_path='accuracy_report.md'):
    lines=['# Resume evaluation audit','', '**Overall accuracy: not established.**',summary['accuracy_explanation'],'',
           f"Reference records: {summary['reference_records']}; predictions: {summary['prediction_records']}; matched: {summary['resumes_evaluated']}.",
           f"Missing predictions: {len(summary['missing_predictions'])}; predictions without reference: {len(summary['predictions_without_reference'])}.",
           '', '## Measured results','', '```json',json.dumps(summary,indent=2),'```','', '## Diagnostic examples','']
    for name,entries in list(mismatches.items())[:10]:lines.extend([f'### {name}','', '```json',json.dumps(entries[:10],indent=2),'```',''])
    Path(out_path).write_text('\n'.join(lines),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    p=parser.add_mutually_exclusive_group(required=True);p.add_argument('--pred-dir');p.add_argument('--pred-file')
    g=parser.add_mutually_exclusive_group(required=True);g.add_argument('--gt-dir');g.add_argument('--gt-file')
    parser.add_argument('--report',default='accuracy_report.md');parser.add_argument('--summary-json',default='accuracy_summary.json')
    parser.add_argument('--issues-json',default='accuracy_issues.json')
    args=parser.parse_args()
    try:summary,issues=run_evaluation(args.pred_dir,args.gt_dir,args.pred_file,args.gt_file)
    except (ValueError,OSError) as exc:parser.error(str(exc))
    Path(args.summary_json).write_text(json.dumps(summary,indent=2),encoding='utf-8')
    Path(args.issues_json).write_text(json.dumps(issues,indent=2),encoding='utf-8')
    generate_markdown_report(summary,issues,args.report)
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
