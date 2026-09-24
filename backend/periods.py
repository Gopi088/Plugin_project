"""Calendar period diagnostics shared by all resume categories."""
import re
from datetime import date
from . import dates as D, intervals as I

CATEGORIES = ('work_experience', 'projects', 'education')


def endpoint(value):
    if isinstance(value, (tuple, list)) and len(value) == 2:
        value = f'{value[0]}-{value[1]:02d}'
    value = str(value or '').strip()
    if value.lower() in ('present', 'current', 'now', 'ongoing'):
        today = date.today()
        return (today.year, today.month), 'month'
    if re.fullmatch(r'(19|20)\d{2}', value):
        return (int(value), 1), 'year'
    match = re.fullmatch(r'((?:19|20)\d{2})-(\d{1,2})', value)
    if match and 1 <= int(match[2]) <= 12:
        return (int(match[1]), int(match[2])), 'month'
    mentions = D.find_mentions(value)
    if len(mentions) == 1 and not mentions[0]['is_range']:
        m = mentions[0]
        return m['start'], m['precision']
    return None, None


def period(item):
    raw = item.get('date_label') or item.get('duration') or ''
    mentions = D.find_mentions(raw)
    ranges = [m for m in mentions if m['is_range']]
    start_value = item.get('start_date') or item.get('start')
    end_value = 'present' if item.get('is_current') or item.get('is_present') else item.get('end_date') or item.get('end')
    start, sp = endpoint(start_value)
    end, ep = endpoint(end_value)
    precision = item.get('precision') or ('year' if 'year' in (sp, ep) else 'month')
    result = {'id': item.get('id'), 'label': item.get('name') or item.get('title') or item.get('company') or item.get('org') or '',
              'state': 'undated', 'start': None, 'end': None, 'months': None,
              'raw': raw, 'source': item.get('source', {})}
    if any(loc.get('method') == 'ocr' for loc in item.get('source', {}).get('entry', [])):
        result['state'] = 'ambiguous'
        return result
    if item.get('status') in ('AMBIGUOUS', 'UNRESOLVED') and len(mentions) == 1 and not ranges:
        result['state'] = 'single_date'
        return result
    if item.get('status') in ('AMBIGUOUS', 'UNRESOLVED'):
        result['state'] = 'ambiguous' if item['status'] == 'AMBIGUOUS' else 'undated'
        return result
    if len(ranges) > 1:
        result['state'] = 'ambiguous'
        return result
    if len(ranges) == 1 and not (start and end):
        m = ranges[0]
        start, end, precision = m['start'], m['end'], m['precision']
    # A graduation/single date is evidence of a point, not a study tenure.
    if mentions and not ranges and len(mentions) == 1 and (not start or not end or start == end or precision == 'year'):
        result['state'] = 'single_date'
        return result
    if start and end:
        if D.month_index(end) < D.month_index(start):
            result['state'] = 'invalid'
            return result
        result.update(start=list(start), end=list(end), state='year_range' if precision == 'year' else 'month_range')
        if precision == 'month':
            result['months'] = D.month_index(end) - D.month_index(start) + 1
        return result
    duration = re.fullmatch(r'\s*(\d+)\s*(months?|years?)\s*', str(raw), re.I)
    if duration:
        result.update(state='duration_only', months=int(duration[1]) * (12 if duration[2].lower().startswith('year') else 1))
    elif start or end or mentions:
        result['state'] = 'single_date'
    return result


def analyze_record(record):
    categories = {}
    all_intervals = []
    timeline = {e.get('id'): e for e in record.get('raw_pipeline_dto', {}).get('timeline', []) if e.get('id')}
    for category in CATEGORIES:
        entries = []
        for item in record.get(category, []):
            # Older batch exports omitted precision/date_label; restore from DTO.
            original = timeline.get(item.get('id'), {})
            entries.append(period({**original, **item}))
        intervals = [(tuple(e['start']), tuple(e['end'])) for e in entries if e['state'] == 'month_range']
        merged = I.union(intervals)
        all_intervals.extend(intervals)
        precise = bool(entries) and all(e['state'] == 'month_range' for e in entries)
        category_breaks = I.uncovered(merged, merged[0][0], merged[-1][1]) if precise and merged else []
        categories[category] = {
            'all_entries_month_precise': precise,
            'unrepresented_periods_in_category': [{'start': list(a), 'end': list(b), 'months': D.month_index(b)-D.month_index(a)+1} for a,b in category_breaks],
            'entries': len(entries), 'dated_periods': sum(e['state'] in ('month_range', 'year_range') for e in entries),
            'represented_months': I.total_months(merged),
            'overlap_months': sum(e['months'] for e in entries if e['state'] == 'month_range') - I.total_months(merged),
            'states': {state: sum(e['state'] == state for e in entries) for state in
                       ('month_range', 'year_range', 'single_date', 'duration_only', 'undated', 'ambiguous', 'invalid')},
            'periods': entries,
        }
    return {'categories': categories, 'represented_months': I.total_months(I.union(all_intervals)),
            'definition': 'Inclusive calendar months, overlaps counted once. Year-only/single dates and unplaced durations do not establish precise monthly coverage.'}


def analyze_timeline(timeline, unresolved, projects):
    events = timeline + unresolved
    return analyze_record({
        'work_experience': [e for e in events if e.get('type') in ('EMPLOYMENT', 'INTERNSHIP')],
        'education': [e for e in events if e.get('type') == 'EDUCATION'],
        'projects': projects,
    })
