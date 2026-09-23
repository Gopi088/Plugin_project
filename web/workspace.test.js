import assert from 'node:assert/strict';
import {parseDateRange,extractTimelineFromResume,detectGapsFromTimeline} from './utils/timelineExtractor.js';
import {normalizeResume} from './utils/resumeData.js';
import {ResumeService,validateFile} from './services/resumeService.js';
const today=new Date(2026,8,21);
for(const [raw,start,end] of [
  ['June2024 –April,2025','2024-06','2025-04'],['April 2023 – Feb,2024','2023-04','2024-02'],
  ['08/2014 – 07/2018','2014-08','2018-07'],['2018-10 – 2021-05','2018-10','2021-05'],
  ['Jan 2020 to Dec 2023','2020-01','2023-12'],['Apr’22-Sep’23','2022-04','2023-09']]){
  const date=parseDateRange(raw,today);assert.equal(date.start?.iso,start,raw);assert.equal(date.end?.iso,end,raw);
}
assert.equal(parseDateRange('2014 - 2018',today).start.iso,'2014');
assert.equal(parseDateRange('2014 - 2018',today).durationText,undefined);
assert.equal(parseDateRange('May 2023',today).dateStatus,'single');
assert.equal(parseDateRange('May 2023',today).durationText,undefined);
for(const raw of ['','nonsense','13/2024 – 02/2025','June 2025 – Feb 2024','Jan 2020 – Dec 2021 / Jan 2023 – Present'])assert.equal(parseDateRange(raw,today).start,null,raw);
const input=normalizeResume({workExperience:[{id:0,title:'Developer',company:'Alpha',years:'Jan 2020 – Present',description:['Built a tool.']},{id:0,title:'Undated',years:''}],education:[{id:1,degree:'B.Tech (3 years)',years:'2015 – 2018'}],personalProjects:[{id:1,name:'Project',years:'Feb 2022 – Now'}]});
const events=extractTimelineFromResume(input,today);
assert.equal(events[0].category,'project');assert.equal(events[1].category,'work');
assert.equal(events.at(-1).startDate,null);assert.equal(events.at(-1).durationText,undefined);
assert.equal(events[1].endDate,null);assert.equal(events[1].durationText,'6 yrs 9 mos');
const eduEvent=events.find(e=>e.category==='education');
assert.equal(eduEvent.durationText,'3 yrs');
const gaps=detectGapsFromTimeline(events,today);
assert.equal(gaps.length,0,'Year-only and undated entries cannot establish exact gaps');
assert.equal(new Set(events.map(e=>e.id)).size,events.length);
assert.deepEqual(extractTimelineFromResume(input,today),events);
const meta=normalizeResume({customSections:{volunteer:{sectionType:'text',text:'Helped'}},sectionMeta:{order:['volunteer','summary'],visible:{summary:false}}});
assert.equal(meta.sectionMeta[0].key,'volunteer');assert.equal(meta.sectionMeta[1].isVisible,false);
for(const file of [{name:'cv.exe',size:20},{name:'cv.pdf',size:0},{name:'cv.pdf',size:4*1024*1024+1}])assert.throws(()=>validateFile(file));
let polls=0,patch,uploaded=false;
const service=new ResumeService('/mock',{pollInterval:1,fetchImpl:async(url,options)=>{
 if(url.endsWith('/upload')){assert.ok(options.body instanceof FormData);uploaded=true;return Response.json({resume_id:'id',processing_status:'processing'});}
 if(options.method==='PATCH'){patch=JSON.parse(options.body);return Response.json({data:{resume_id:'id',processed_resume:patch}});}
 if(url.includes('/pdf?'))return new Response('%PDF-test',{headers:{'Content-Type':'application/pdf'}});
 return Response.json({data:{resume_id:'id',raw_resume:{processing_status:++polls<2?'processing':'ready'},processed_resume:polls<2?null:input}});
}});
const result=await service.uploadAndParse(new File(['Resume'], 'resume.txt'));
assert.ok(uploaded);assert.equal(polls,2);assert.deepEqual(result.resumeData,input);
await service.updateResume('id',meta);assert.deepEqual(patch,meta);
assert.match(service.getPdfDownloadUrl('a b',{marginTop:15,template:'modern'}),/a%20b\/pdf.*template=modern.*marginTop=15/);
assert.equal((await service.downloadPdf('id')).type,'application/pdf');
const failed=new ResumeService('/mock',{fetchImpl:async()=>Response.json({data:{resume_id:'id',raw_resume:{processing_status:'failed'}}})});
await assert.rejects(()=>failed.waitUntilReady('id'),/parsing failed/);
const offline=new ResumeService('/mock',{fetchImpl:async()=>{throw Error('network');}});
await assert.rejects(()=>offline.getResume('id'),/unavailable/);
const aborted=new AbortController();aborted.abort();await assert.rejects(()=>service.waitUntilReady('id',{signal:aborted.signal}),{name:'AbortError'});
console.log('Workspace date, contracts, polling, save, download, validation and failure checks passed.');

const gapEvents=extractTimelineFromResume({education:[{degree:'Degree',years:'08/2014 - 07/2018'}],workExperience:[{title:'Engineer',years:'10/2018 - 05/2021'}]});
const gap=detectGapsFromTimeline(gapEvents)[0];
assert.equal(gap.durationMonths,2);assert.equal(gap.start,'2018-08');assert.equal(gap.end,'2018-09');
assert.equal(detectGapsFromTimeline([...gapEvents,{category:'work',startDate:'2018',endDate:'2019'}]).length,0);
assert.equal(detectGapsFromTimeline([...gapEvents,{category:'project',startDate:'2018-08',endDate:'2018-09'}]).length,0);
