/** Deterministic dates from structured resume fields; never infer missing dates. */
const MONTHS={jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};
const MONTH='(?:January|February|March|April|May|June|July|August|September|October|November|December|Sept|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)';
const CURRENT='(?:present|current|now|ongoing|till date|to date)';
const DATE=`(?:${MONTH}\\.?[\\s,./-]*\\d{4}|${MONTH}\\.?\\s*[’']\\d{2}|(?:0?[1-9]|1[0-2])[/.-](?:19|20)\\d{2}|(?:19|20)\\d{2}[-/](?:0?[1-9]|1[0-2])|(?:19|20)\\d{2})`;
const RANGE=new RegExp(`^\\s*[([]?\\s*(${DATE})\\s*(?:[-–—]|to|till|until|through)\\s*(${DATE}|${CURRENT})\\s*[)\\]]?\\s*$`,'i');
export function parseMonthYear(text) {
  const value=String(text||'').trim();let match;
  if((match=value.match(new RegExp(`^(${MONTH})\\.?[\\s,./-]*(\\d{4})$`,'i'))))return stamp(+match[2],MONTHS[match[1].slice(0,3).toLowerCase()]);
  if((match=value.match(new RegExp(`^(${MONTH})\\.?\\s*[’'](\\d{2})$`,'i'))))return stamp(+match[2]+(+match[2]<=39?2000:1900),MONTHS[match[1].slice(0,3).toLowerCase()]);
  if((match=value.match(/^(0?[1-9]|1[0-2])[/.-]((?:19|20)\d{2})$/)))return stamp(+match[2],+match[1]);
  if((match=value.match(/^((?:19|20)\d{2})[-/](0?[1-9]|1[0-2])$/)))return stamp(+match[1],+match[2]);
  if(/^(19|20)\d{2}$/.test(value))return stamp(+value,null);
  return null;
}
function stamp(year,month) {return {year,month,iso:month?`${year}-${String(month).padStart(2,'0')}`:String(year),precision:month?'month':'year'};}
export function calculateDuration(startYear,startMonth,endYear,endMonth) {
  if(!startMonth||!endMonth)return undefined;
  const total=(endYear-startYear)*12+endMonth-startMonth+1;
  if(total<=0)return undefined;
  const years=Math.floor(total/12),months=total%12;
  return [years?`${years} yr${years===1?'':'s'}`:'',months?`${months} mo${months===1?'':'s'}`:''].filter(Boolean).join(' ');
}
export function parseDateRange(raw,today=new Date()) {
  const text=String(raw||'').trim(),match=text.match(RANGE);
  const missing={start:null,end:null,isCurrent:false,dateStatus:text?'invalid':'missing',precision:'unknown'};
  if(!match){const single=parseMonthYear(text);return single?{...missing,start:single,precision:single.precision,dateStatus:'single'}:missing;}
  const start=parseMonthYear(match[1]);
  const isCurrent=new RegExp(`^${CURRENT}$`,'i').test(match[2]);
  const end=isCurrent?stamp(today.getFullYear(),today.getMonth()+1):parseMonthYear(match[2]);
  if(!start||!end||start.year>end.year||(start.year===end.year&&start.month&&end.month&&start.month>end.month))return missing;
  const precision=start.month&&end.month?'month':'year';
  return {start,end,isCurrent,dateStatus:'range',precision,
    durationText:precision==='month'?calculateDuration(start.year,start.month,end.year,end.month):undefined};
}
export function extractTimelineFromResume(data,today=new Date()) {
  const events=[],seen=new Set();
  for(const [key,category,titleKey,orgKey] of [['workExperience','work','title','company'],['education','education','degree','institution'],['personalProjects','project','name','role']]){
    for(const [index,item] of (data[key]||[]).entries()){
      const rawDateString=String(item.years||'');const dates=parseDateRange(rawDateString,today);
      let id=category+'-'+(item.id??index);if(seen.has(id))id+='-'+index;seen.add(id);
      let durationText=dates.durationText;
      if (!durationText) {
        const descText = Array.isArray(item.description) ? item.description.join(' ') : String(item.description || '');
        const combined = `${rawDateString} ${item[titleKey] || ''} ${item[orgKey] || ''} ${descText}`;
        const explicit = combined.match(/\b(\d+)\s*-?\s*(?:years?|yrs?)\b/i);
        if (explicit) {
          const y = +explicit[1];
          durationText = `${y} yr${y === 1 ? '' : 's'}`;
        } else if (dates.start?.year && dates.end?.year && dates.end.year > dates.start.year) {
          const diff = dates.end.year - dates.start.year;
          durationText = `${diff} yr${diff === 1 ? '' : 's'}`;
        }
      }
      events.push({id,category,title:item[titleKey]||'',organization:item[orgKey]||'',location:item.location||'',rawDateString,
        startDate:dates.start?.iso||null,endDate:dates.isCurrent?null:dates.end?.iso||null,isCurrent:dates.isCurrent,
        parsedStartYear:dates.start?.year||null,parsedEndYear:dates.end?.year||null,
        precision:dates.precision,dateStatus:dates.dateStatus,durationText,
        description:Array.isArray(item.description)?item.description:item.description?[item.description]:[]});
    }
  }
  return events.sort((a,b)=>Number(b.isCurrent)-Number(a.isCurrent)||(b.startDate||'').localeCompare(a.startDate||'')||a.id.localeCompare(b.id));
}

export function detectGapsFromTimeline(events, today = new Date()) {
  if (!Array.isArray(events) || events.length < 2) return [];

  const eligible = events.filter(e =>
    ['work','education','project'].includes(e.category)
  );

  function parseYM(iso, isCurrent) {
    if (isCurrent) return { year: today.getFullYear(), month: today.getMonth() + 1 };
    if (!iso) return null;
    const parts = String(iso).split('-').map(Number);
    if (parts.length >= 2 && !isNaN(parts[0]) && !isNaN(parts[1])) return { year: parts[0], month: parts[1] };
    // A year alone cannot establish month-level coverage.
    return null;
  }

  if(eligible.some(e=>!parseYM(e.startDate,false)||!parseYM(e.endDate,e.isCurrent)))return [];
  const sorted = [...eligible].sort((a, b) => {
    const da = parseYM(a.startDate, false);
    const db = parseYM(b.startDate, false);
    if (!da && !db) return 0;
    if (!da) return 1;
    if (!db) return -1;
    return (da.year * 12 + da.month) - (db.year * 12 + db.month);
  });

  const gaps = [];
  let maxEnd = null;
  let lastEvent = null;

  for (const ev of sorted) {
    const start = parseYM(ev.startDate, false);
    const end = parseYM(ev.endDate, ev.isCurrent);
    if (!start) continue;

    if (maxEnd && lastEvent) {
      const gapMonths = (start.year * 12 + start.month) - (maxEnd.year * 12 + maxEnd.month) - 1;
      if (gapMonths >= 1) {
        const iso=n=>`${Math.floor(n/12)}-${String(n%12+1).padStart(2,'0')}`;
        const startIso=iso(maxEnd.year*12+maxEnd.month);
        const endIso=iso(start.year*12+start.month-2);
        const y = Math.floor(gapMonths / 12);
        const m = gapMonths % 12;
        let durText = '';
        if (y > 0 && m > 0) durText = `${y} yr${y > 1 ? 's' : ''} ${m} mo${m > 1 ? 's' : ''}`;
        else if (y > 0) durText = `${y} yr${y > 1 ? 's' : ''}`;
        else durText = `${m} mo${m > 1 ? 's' : ''}`;

        const isGradGap = lastEvent.category === 'education' && ev.category === 'work';
        gaps.push({
          id: `gap-${gaps.length}`,
          start: startIso,
          end: endIso,
          durationMonths: gapMonths,
          durationText: durText,
          type: 'Potential unrepresented period',
          fromEvent: lastEvent,
          toEvent: ev,
          fromLabel: `${lastEvent.title || 'Role'} at ${lastEvent.organization || 'Organization'}`,
          toLabel: `${ev.title || 'Role'} at ${ev.organization || 'Organization'}`,
          quote: [
            lastEvent.rawDateString ? `${lastEvent.rawDateString} ${lastEvent.title}` : lastEvent.title,
            ev.rawDateString ? `${ev.rawDateString} ${ev.title}` : ev.title
          ].filter(Boolean).join(' ... ')
        });
      }
    }

    if (end) {
      if (!maxEnd || (end.year * 12 + end.month) > (maxEnd.year * 12 + maxEnd.month)) {
        maxEnd = end;
        lastEvent = ev;
      }
    }
  }

  return gaps;
}
