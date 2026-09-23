import {ResumeService,validateFile} from './services/resumeService.js';
import {ResumeStore} from './services/resumeStore.js';
import {extractTimelineFromResume, detectGapsFromTimeline} from './utils/timelineExtractor.js';
import {normalizeResume,nextId,SECTIONS} from './utils/resumeData.js';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api=new ResumeService(),store=new ResumeStore();
let resumeId=null,data=null,saved=null,source='',dirty=false,revision=0,activeSection='personalInfo',category='all',saving=false,operation=null,isReviewed=false;
const notice=text=>{$('message').textContent=text;};
function updateReviewedBtn() {
  const btn=$('btn-workspace-reviewed'), text=$('workspace-review-text');
  if(!btn||!text)return;
  if(isReviewed){
    btn.classList.remove('unreviewed');
    btn.classList.add('is-reviewed');
    text.textContent='✓ Reviewed';
    btn.title='Marked as reviewed by recruiter. Click to unmark.';
  }else{
    btn.classList.remove('is-reviewed');
    btn.classList.add('unreviewed');
    text.textContent='Mark Reviewed';
    btn.title='Click to mark resume as reviewed';
  }
}
const labels={name:'Name',title:'Title',email:'Email',phone:'Phone',location:'Location',website:'Website',linkedin:'LinkedIn',github:'GitHub',company:'Company',years:'Dates as written',description:'Description',institution:'Institution',degree:'Degree',role:'Role',subtitle:'Subtitle',technicalSkills:'Technical skills',languages:'Languages',certificationsTraining:'Certifications & training',awards:'Awards'};
const itemFields={workExperience:['title','company','location','years','description'],education:['institution','degree','years','description'],personalProjects:['name','role','years','description','github','website'],custom:['title','subtitle','location','years','description']};
const pathValue=path=>path.reduce((v,key)=>v?.[key],data);
function setValue(path,value) {
  if(path.some(k=>['__proto__','constructor','prototype'].includes(k)))throw Error('This section key cannot be edited.');
  let target=data;for(const key of path.slice(0,-1))target=target[key];target[path.at(-1)]=value;
}
function updateState() {
  if ($('save-state')) $('save-state').textContent=dirty?'Unsaved changes · draft stored in this browser':'Saved in Resume Matcher';
  if ($('save')) $('save').disabled=!data||!dirty||saving||!!operation;
  if ($('discard')) $('discard').disabled=!dirty||saving||!!operation;
  if ($('download')) $('download').disabled=!data||dirty||saving||!!operation;
  if ($('resume-title')) $('resume-title').textContent=data?.personalInfo?.name||'Resume';
}
async function persist() {
  if(!resumeId||!data)return;
  try {await store.put({id:resumeId,data,saved,source,dirty,isReviewed});}
  catch {notice('Browser draft storage is unavailable. Save changes to Resume Matcher before leaving this page.');}
}
function changed() {dirty=true;revision++;updateState();persist();}
function setBusy(value) {
  $('file').disabled=value;$('new-resume').disabled=value;$('resume-list').disabled=value;
  $('open-form').querySelector('button').disabled=value;
  $('progress').hidden=!value;$('cancel-upload').hidden=!value;updateState();
}
async function refreshList() {
  try {
    const response=await api.listResumes();
    $('resume-list').innerHTML='<option value="">Choose a resume</option>'+(response.data||[]).map(r=>`<option value="${esc(r.resume_id)}">${esc(r.filename||r.title||r.resume_id)}${r.processing_status!=='ready'?' · '+esc(r.processing_status):''}</option>`).join('');
    if(resumeId)$('resume-list').value=resumeId;
  }catch(error){notice(error.message);}
}
async function connect() {
  try {await api.health({signal:AbortSignal.timeout(5000)});$('connection').textContent='Resume Matcher connected';await refreshList();}
  catch(error){$('connection').textContent='Resume Matcher offline';notice(error.message);}
}
async function adopt(record,id) {
  resumeId=id;revision=0;category='all';activeSection='personalInfo';
  const cached=await store.get(id).catch(()=>null);
  const reviewedKey='resume_reviewed_'+id;
  isReviewed=!!cached?.isReviewed || (typeof localStorage!=='undefined' && localStorage.getItem(reviewedKey)==='true');
  updateReviewedBtn();
  saved=normalizeResume(record.processed_resume);data=cached?.dirty?normalizeResume(cached.data):structuredClone(saved);
  dirty=!!cached?.dirty;
  source=cached?.source||(record.raw_resume?.content_type==='md'?record.raw_resume.content:record.raw_resume?.content||'');
  $('raw-source').textContent=source||'Original parser text is not available in this browser. Saved JSON is not treated as original evidence.';
  $('workspace').hidden=false;$('upload-panel').hidden=true;
  $('resume-id').value=id;$('resume-list').value=id;history.replaceState(null,'','#'+encodeURIComponent(id));
  updateState();renderTimeline();if($('editor-fields'))renderEditor();await persist();
  if(dirty)notice('Restored your unsaved draft. Saving will update the resume in Resume Matcher.');
}
async function openResume(id) {
  if(!id||operation||saving)return;
  await persist();notice('Loading resume…');operation=new AbortController();setBusy(true);
  try {const result=await api.waitUntilReady(id,{signal:operation.signal});notice('');await adopt(result.record,id);}
  catch(error){
    const cached=await store.get(id).catch(()=>null);
    if(cached?.data && error.name!=='AbortError'){
      await adopt({processed_resume:cached.saved||cached.data,raw_resume:{}},id);
      notice(error.message+' Showing your local draft.');
    }else notice(error.name==='AbortError'?'Stopped waiting. You can reopen the resume by its ID.':error.message);
  }finally{operation=null;setBusy(false);}
}
async function upload(file) {
  if(!file||operation||saving)return;
  try{validateFile(file);}catch(error){notice(error.message);return;}
  await persist();notice('Uploading and parsing resume…');operation=new AbortController();setBusy(true);
  try {
    const result=await api.uploadAndParse(file,file.name,{signal:operation.signal,
      onUploaded:id=>{$('resume-id').value=id;history.replaceState(null,'','#'+encodeURIComponent(id));},
      onStatus:status=>notice(status==='ready'?'Resume ready.':'Parsing resume…')});
    await adopt(result.record,result.resumeId);notice('Resume parsed. Review the extracted fields before saving or exporting.');await refreshList();
  }catch(error){notice(error.name==='AbortError'?'Stopped waiting. Parsing may continue; reopen the resume by its ID.':error.message);await refreshList();}
  finally{operation=null;setBusy(false);$('file').value='';}
}
function jumpToSourceText(query) {
  if(!query)return;
  const panel=$('source-panel');
  if(panel)panel.open=true;
  const rawEl=$('raw-source');
  if(!rawEl)return;
  const rawContent=source||rawEl.textContent||'';
  if(!rawContent){notice('Cached parser text is not available.');return;}
  // Parser text is a cached extraction, not a live original-document viewer.
  // Only an exact, unique match may be marked; never split a query into fragments.
  const term=query.trim();
  const matchIndex=rawContent.indexOf(term),matchLength=term.length;
  if(!term || matchIndex<0 || rawContent.indexOf(term,matchIndex+1)!==-1){
    notice('No unique exact match in the cached parser text. Use the extension on the original resume to verify its source.');
    return;
  }
  const foundMatch=rawContent.slice(matchIndex,matchIndex+matchLength);
  if(matchIndex!==-1){
    const before=esc(rawContent.slice(0,matchIndex));
    const matched=esc(rawContent.slice(matchIndex,matchIndex+matchLength));
    const after=esc(rawContent.slice(matchIndex+matchLength));
    rawEl.innerHTML=`${before}<mark class="rt-resume-highlight" id="active-source-match">${matched}</mark>${after}`;
    const highlight=$('active-source-match');
    if(highlight)highlight.scrollIntoView({behavior:'smooth',block:'center'});
    notice(`📍 Matched cached parser text: "${foundMatch}"`);
  }else{
    panel.scrollIntoView({behavior:'smooth',block:'start'});
    notice(`Showing cached parser text for "${query.slice(0,35)}"`);
  }
}
function renderTimeline() {
  if(!data)return;
  const events=extractTimelineFromResume(data);
  const gaps=detectGapsFromTimeline(events);
  const gapsContainer=$('gaps-container');
  if(gapsContainer){
    if(!gaps.length){
      gapsContainer.innerHTML=`<div class="gap-card verified-continuous"><span class="check-icon">✓</span><div><strong>No potential periods displayed</strong><div class="muted">Incomplete dates can prevent assessment. Parsed fields do not verify continuity or unemployment.</div></div></div>`;
    }else{
      gapsContainer.innerHTML=`<div class="gap-header"><h3 class="gap-heading">⚠️ Detected Gaps (${gaps.length})</h3><span class="muted">Chronological analysis of dates between education &amp; employment</span></div><div class="gap-list">${gaps.map(g=>`<div class="gap-card" id="${esc(g.id)}"><div class="gap-badge-col"><span class="gap-badge ${g.durationMonths>=6?'badge-alert':'badge-warn'}">${esc(g.durationText)} gap</span><span class="gap-dates">${esc(g.start)} → ${esc(g.end)}</span></div><div class="gap-body"><div class="gap-type">${esc(g.type)}</div><div class="gap-context">Between <strong>${esc(g.fromLabel)}</strong> and <strong>${esc(g.toLabel)}</strong></div><div class="gap-actions"><button type="button" class="btn-verify" data-quote="${esc(g.quote||g.fromLabel)}">View parser text</button></div></div></div>`).join('')}</div>`;
      gapsContainer.querySelectorAll('.btn-verify').forEach(btn=>{
        btn.onclick=()=>jumpToSourceText(btn.dataset.quote);
      });
    }
  }
  const categories=[['all','All'],['work','Experience'],['education','Education'],['project','Projects']];
  $('filters').innerHTML=categories.map(([key,label])=>`<button data-category="${key}" aria-pressed="${category===key}">${label} (${key==='all'?events.length:events.filter(e=>e.category===key).length})</button>`).join('');
  $('filters').querySelectorAll('button').forEach(b=>b.onclick=()=>{category=b.dataset.category;renderTimeline();});
  const visible=events.filter(e=>category==='all'||e.category===category);
  $('timeline-events').innerHTML=visible.map(e=>`<li class="${e.category}"><article><div class="muted">${{work:'Experience',education:'Education',project:'Project'}[e.category]}</div><h3>${esc(e.title||'Title not stated')}</h3>${e.organization?`<div class="organization">${esc(e.organization)}</div>`:''}${e.location?`<span class="badge">${esc(e.location)}</span>`:''}<div><span class="badge">${esc(e.rawDateString||'Dates not stated')}</span>${e.isCurrent?'<span class="badge active">Current</span>':''}${e.durationText?`<span class="badge duration-badge">${esc(e.durationText)}</span>`:''}${e.dateStatus==='invalid'?'<span class="badge">Date format not resolved</span>':''}</div><div class="event-actions"><button type="button" class="btn-verify-event" data-query="${esc([e.rawDateString,e.title,e.organization].filter(Boolean).join(' '))}" data-title="${esc(e.title)}" data-org="${esc(e.organization)}">View parser text</button></div>${e.description.length?`<details><summary>${e.description.length} detail${e.description.length===1?'':'s'}</summary><ul>${e.description.map(d=>`<li>${esc(d)}</li>`).join('')}</ul></details>`:''}</article></li>`).join('')||'<li>No entries in this category.</li>';
  $('timeline-events').querySelectorAll('.btn-verify-event').forEach(btn=>{
    btn.onclick=()=>jumpToSourceText(btn.dataset.query||btn.dataset.title||btn.dataset.org);
  });
}
function field(path,key,value,{list=false,long=false}={}) {
  const id='field-'+path.map(String).join('-');
  const attrs=`id="${esc(id)}" data-path="${esc(JSON.stringify(path))}" data-list="${list}"`;
  return `<label class="${long||list?'wide':''}" for="${esc(id)}">${esc(labels[key]||key)}${list?' (one per line)':''}${long||list?`<textarea ${attrs}>${esc(list?(value||[]).join('\n'):value)}</textarea>`:`<input ${attrs} value="${esc(value)}">`}</label>`;
}
function entryEditor(item,path,fields,index,listDescription) {
  return `<article class="entry-editor"><header><h3>${esc(item.title||item.name||item.degree||'Entry '+(index+1))}</h3><button data-remove-item="${index}" type="button">Remove entry</button></header><div class="fields">${fields.map(key=>field([...path,index,key],key,item[key]??'',{list:key==='description'&&listDescription,long:key==='description'})).join('')}</div></article>`;
}
function activePath() {return SECTIONS[activeSection]?[activeSection]:['customSections',activeSection];}
function renderEditor() {
  if(!data||!$('section-nav')||!$('editor-fields'))return;
  const metadata=data.sectionMeta;
  $('section-nav').innerHTML=[{key:'personalInfo',displayName:'Personal information'},...metadata.filter(m=>m.key!=='personalInfo')].map(m=>`<button data-section="${esc(m.key)}" aria-current="${activeSection===m.key}">${esc(m.displayName||m.key)}${m.isVisible===false?' · hidden':''}</button>`).join('');
  $('section-nav').querySelectorAll('button').forEach(button=>button.onclick=()=>{activeSection=button.dataset.section;renderEditor();});
  let html='';
  if(activeSection==='personalInfo')html=`<h2>Personal information</h2><div class="fields">${['name','title','email','phone','location','website','linkedin','github'].map(key=>field(['personalInfo',key],key,data.personalInfo[key]||'')).join('')}</div>`;
  else {
    const meta=metadata.find(m=>m.key===activeSection);if(!meta){activeSection='personalInfo';return renderEditor();}
    html=`<h2>${esc(meta.displayName)}</h2><div class="section-settings"><label><input id="section-visible" type="checkbox" ${meta.isVisible?'checked':''}> Include in exported resume</label><button id="section-up">Move up</button><button id="section-down">Move down</button>${!meta.isDefault?'<button id="remove-section">Remove section</button>':''}</div>`;
    const path=activePath(),value=pathValue(path);
    if(activeSection==='summary')html+=field(path,'Summary',value,{long:true});
    else if(activeSection==='additional')html+=`<div class="fields">${Object.keys(labels).filter(k=>['technicalSkills','languages','certificationsTraining','awards'].includes(k)).map(key=>field([...path,key],key,value[key],{list:true})).join('')}</div>`;
    else if(Array.isArray(value))html+=value.map((item,i)=>entryEditor(item,path,itemFields[activeSection],i,activeSection!=='education')).join('')+'<button id="add-entry">Add entry</button>';
    else if(value?.sectionType==='text')html+=field([...path,'text'],'Text',value.text||'',{long:true});
    else if(value?.sectionType==='stringList')html+=field([...path,'strings'],'Items',value.strings||[],{list:true});
    else if(value?.sectionType==='itemList')html+=(value.items||[]).map((item,i)=>entryEditor(item,[...path,'items'],itemFields.custom,i,true)).join('')+'<button id="add-entry">Add entry</button>';
  }
  $('editor-fields').innerHTML='<section class="editor-section">'+html+'</section>';
  $('editor-fields').querySelectorAll('[data-path]').forEach(input=>input.oninput=()=>{
    const path=JSON.parse(input.dataset.path),value=input.dataset.list==='true'?input.value.split('\n').map(s=>s.trim()).filter(Boolean):input.value;
    setValue(path,value);changed();renderTimeline();
  });
  const meta=metadata.find(m=>m.key===activeSection);
  if($('section-visible'))$('section-visible').onchange=e=>{meta.isVisible=e.target.checked;changed();renderEditor();};
  for(const [id,delta] of [['section-up',-1],['section-down',1]])if($(id)){
    const index=metadata.indexOf(meta);$(id).disabled=index+delta<0||index+delta>=metadata.length;
    $(id).onclick=()=>{[metadata[index],metadata[index+delta]]=[metadata[index+delta],metadata[index]];metadata.forEach((m,i)=>m.order=i);changed();renderEditor();};
  }
  if($('remove-section'))$('remove-section').onclick=()=>{if(!confirm('Remove this custom section from the draft?'))return;delete data.customSections[activeSection];data.sectionMeta=metadata.filter(m=>m.key!==activeSection);activeSection='personalInfo';changed();renderEditor();};
  function items() {const value=pathValue(activePath());return Array.isArray(value)?value:(value.items||=[]);}
  if($('add-entry'))$('add-entry').onclick=()=>{const list=items(),fields=itemFields[activeSection]||itemFields.custom;list.push(Object.fromEntries([['id',nextId(list)],...fields.map(key=>[key,key==='description'&&activeSection!=='education'?[]:''])]));changed();renderEditor();renderTimeline();};
  $('editor-fields').querySelectorAll('[data-remove-item]').forEach(button=>button.onclick=()=>{if(!confirm('Remove this entry from the draft?'))return;items().splice(+button.dataset.removeItem,1);changed();renderEditor();renderTimeline();});
}
if($('add-section'))$('add-section').onclick=()=>{
  const name=prompt('Section name');if(!name?.trim())return;
  const type=prompt('Section type: text, itemList, or stringList','text');if(!['text','itemList','stringList'].includes(type)){notice('Choose text, itemList, or stringList.');return;}
  const key='custom_'+crypto.randomUUID();
  data.customSections[key]={sectionType:type,...(type==='text'?{text:''}:type==='itemList'?{items:[]}:{strings:[]})};
  data.sectionMeta.push({id:key,key,displayName:name.trim(),sectionType:type,isDefault:false,isVisible:true,order:data.sectionMeta.length});
  activeSection=key;changed();renderEditor();
};
if($('save'))$('save').onclick=async()=>{
  if(!dirty||saving)return;saving=true;updateState();const version=revision,snapshot=structuredClone(data),id=resumeId;
  try {
    const result=await api.updateResume(id,snapshot);saved=normalizeResume(result.processed_resume);
    if(revision===version){data=structuredClone(saved);dirty=false;if($('editor-fields'))renderEditor();renderTimeline();}
    await persist();notice('Resume saved.');await refreshList();
  }catch(error){notice(error.message);}
  finally{saving=false;updateState();}
};
if($('discard'))$('discard').onclick=()=>{if(!confirm('Discard your unsaved changes and restore the last fetched saved version?'))return;data=structuredClone(saved);dirty=false;revision++;persist();updateState();if($('editor-fields'))renderEditor();renderTimeline();notice('Draft discarded.');};
$('file').onchange=e=>upload(e.target.files[0]);
const drop=$('dropzone');
drop.ondragover=e=>{e.preventDefault();drop.classList.add('dragging');};drop.ondragleave=()=>drop.classList.remove('dragging');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('dragging');upload(e.dataTransfer.files[0]);};
drop.onkeydown=e=>{if(e.target===drop&&(e.key==='Enter'||e.key===' ')){e.preventDefault();$('file').click();}};
$('new-resume').onclick=()=>{$('upload-panel').hidden=false;$('file').click();};
$('cancel-upload').onclick=()=>operation?.abort();
$('reconnect').onclick=connect;$('refresh-list').onclick=refreshList;
$('resume-list').onchange=e=>openResume(e.target.value);
$('open-form').onsubmit=e=>{e.preventDefault();openResume($('resume-id').value.trim());};
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{
  for(const tab of document.querySelectorAll('[data-tab]'))tab.setAttribute('aria-pressed',String(tab===button));
  for(const view of document.querySelectorAll('.tab-view'))view.hidden=view.id!==button.dataset.tab;
});
const pdfSettings=[['marginTop','Top margin (mm)',5,25,10],['marginBottom','Bottom margin (mm)',5,25,10],['marginLeft','Left margin (mm)',5,25,10],['marginRight','Right margin (mm)',5,25,10],['sectionSpacing','Section spacing',1,5,3],['itemSpacing','Item spacing',1,5,3],['lineHeight','Line height',1,5,3],['fontSize','Font size',1,5,3]];
if($('pdf-controls'))$('pdf-controls').innerHTML=pdfSettings.map(([key,label,min,max,value])=>`<label>${label}<input name="${key}" type="number" min="${min}" max="${max}" value="${value}" required></label>`).join('');
if($('pdf-form'))$('pdf-form').onsubmit=async event=>{
  event.preventDefault();if(dirty){notice('Save your changes before exporting.');return;}
  const exportId=resumeId;
  if($('download'))$('download').disabled=true;notice('Rendering PDF…');
  try {
    const blob=await api.downloadPdf(exportId,Object.fromEntries(new FormData(event.target)));
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='resume-'+exportId+'.pdf';link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);notice('PDF downloaded.');
  }catch(error){notice(error.message);}finally{updateState();}
};
if($('btn-workspace-reviewed'))$('btn-workspace-reviewed').onclick=async()=>{
  isReviewed=!isReviewed;
  if(resumeId){
    try{localStorage.setItem('resume_reviewed_'+resumeId,String(isReviewed));}catch{}
  }
  updateReviewedBtn();
  await persist();
  notice(isReviewed?'✓ Marked resume as reviewed.':'Unmarked reviewed status.');
};
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
connect().then(()=>{const id=decodeURIComponent(location.hash.slice(1));if(id)openResume(id);});

