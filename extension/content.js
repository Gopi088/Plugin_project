/* Existing in-page timeline and side panel; factual summary first. */
(() => {
  if (window.__rtInjected || document.body?.hasAttribute('data-resume-workspace')) return;
  window.__rtInjected = true;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const send = msg => new Promise((resolve, reject) => chrome.runtime.sendMessage(msg, response => {
    const error = chrome.runtime.lastError;
    if (error) reject(new Error(error.message));
    else if (response?._rtError) reject(new Error(response._rtError));
    else resolve(response);
  }));
  const extensionPage = location.protocol === 'chrome-extension:';
  let activeTab='overview';
  let evaluation=null;
  const version=chrome.runtime.getManifest?.().version || '';
  const qualityLine=()=>RT_VM.formatEvaluation(evaluation, dto);
  let sourceTabId=Number(new URL(location.href).searchParams.get('tab')) || undefined;
  let docId = null, dto = null, vm = null, busy = false, draft = {author:'',text:''};
  const pill = document.createElement('button'); pill.id='rt-pill'; pill.textContent='Timeline';
  const panel = document.createElement('aside'); panel.id='rt-panel'; panel.hidden=!extensionPage;
  panel.setAttribute('aria-label','Resume timeline');
  document.documentElement.append(pill,panel);
  if (extensionPage) pill.hidden = true;
  const status = text => { const el=document.getElementById('rt-status'); if(el) el.textContent=text; };
  function shell(html) {
    const isRev = !!vm?.isReviewed;
    panel.innerHTML=`<header class="rt-head"><div><strong>Resume timeline</strong><small>${esc(vm?.filename || '')}${version?' · v'+esc(version):''}</small></div><div style="display:flex;align-items:center;gap:6px;"><button id="rt-reanalyze" type="button" title="Re-analyze resume from file" style="background:#fff;border:1px solid #cbd5e1;border-radius:20px;padding:4px 10px;font-size:11px;font-weight:600;cursor:pointer;color:#334155;display:inline-flex;align-items:center;gap:4px;"><span>↺</span><span>Re-analyze</span></button>${docId?`<button id="rt-top-reviewed" class="btn-review-toggle ${isRev?'is-reviewed':'unreviewed'}" type="button" title="Click to toggle reviewed status"><span class="tick-circle">✓</span><span class="review-status-text">${isRev?'✓ Reviewed':'Mark Reviewed'}</span></button>`:''}<button id="rt-close" aria-label="Close timeline">×</button></div></header><div id="rt-status" role="status"></div><p id="rt-evaluation" class="rt-foot" style="padding:0 16px" title="Measured on labeled test cases, not verified accuracy for this candidate.">${esc(qualityLine())}</p>${html}`;
    document.getElementById('rt-close').onclick=()=>{panel.hidden=true;RT_SOURCE.close();};
    const reBtn = document.getElementById('rt-reanalyze');
    if (reBtn) {
      reBtn.onclick = () => {
        dto = null; vm = null; docId = null;
        analyze();
      };
    }
    const revBtn = document.getElementById('rt-top-reviewed');
    if (revBtn && docId) {
      revBtn.onclick = async () => {
        const nextState = !vm?.isReviewed;
        if (dto) dto.is_reviewed = nextState;
        if (vm) vm.isReviewed = nextState;
        await chrome.storage.local.set({ [`reviewed:${docId}`]: nextState });
        send({ type: 'rt-feedback', docId, payload: { overrides: [{ type: 'document_reviewed', reviewed: nextState }] } }).catch(() => {});
        render();
      };
    }
  }
  function detect() {
    const embed=document.querySelector('embed[type="application/pdf"],object[type="application/pdf"]');
    if (/\.(pdf|docx?)([?#]|$)/i.test(location.href)) return {url:location.href};
    if (embed?.src || embed?.data) return {url:embed.src || embed.data};
    const snapshot=RT_SOURCE.captureText();
    if (/experience|employment|education/i.test(snapshot.text)) return snapshot;
    return null;
  }
  async function analyze() {
    if(busy) return;
    busy=true; docId=null; dto=null; vm=null; RT_SOURCE.bind(null);
    panel.hidden=false; shell('<p>Reading resume…</p>');
    try {
      const detected=detect();
      if(!detected) throw new Error('No resume is available in this page. Open the resume first.');
      const payload=detected.url ? await send({type:'rt-read-resume',url:detected.url})
        : {filename:document.title || 'page-resume.txt',text:detected.text,source:'extension-text',viewer_url:location.href};
      const result=await send({type:'rt-submit',payload}); docId=result.doc_id;
      RT_SOURCE.bind({docId,nodes:detected.nodes,inPage:true,sourceUrl:detected.url});
      dto=await send({type:'rt-timeline',docId});
      const savedRev = await chrome.storage.local.get([`reviewed:${docId}`]);
      if (savedRev[`reviewed:${docId}`] !== undefined) dto.is_reviewed = savedRev[`reviewed:${docId}`];
      await loadDraft(); render();
    } catch(error) {status(error.message);} finally {busy=false;}
  }
  async function loadDraft() {
    refreshEvaluation();
    const saved=await chrome.storage.local.get(['recruiterName',`draft:${docId}`]);
    draft=saved[`draft:${docId}`] || {author:saved.recruiterName || '',text:''};
  }
  const eye = hidden => `<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z" fill="none" stroke="currentColor"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor"/>${hidden?'<path d="m3 3 18 18" stroke="currentColor"/>':''}</svg>`;
  function controls(item) {
    return `<button class="rt-eye" data-hide="${esc(item.id)}" aria-label="${item.hidden?'Show':'Hide'} ${esc(item.label)}" title="${item.hidden?'Show item':'Hide item'}">${eye(item.hidden)}</button>`;
  }
  function evidence(item) {
    const quotes=item.source?.entry?.map(l=>l.text) || (item.evidence_details||[]).map(d=>d.quote);
    return `<details id="rt-evidence-${esc(item.id)}" class="rt-evidence"><summary>Source details</summary>${(quotes||[]).map(q=>`<blockquote>${esc(q)}</blockquote>`).join('')}</details>`;
  }
  function actions(item) {
    return `<div class="rt-actions"><button class="rt-view" data-view="${esc(item.id)}">View in Resume</button>${controls(item)}</div>`;
  }
  function eventRow(item) {
    return `<article class="rt-entry rt-event-card" data-item="${esc(item.id)}"><div class="rt-card-kind">${item.type==='EDUCATION'?'Education':item.type==='INTERNSHIP'?'Internship':'Career entry'}${item.uncertain?' · Needs review':''}</div><strong class="rt-card-title">${esc(item.org || item.title || 'Entry with unclear label')}</strong>${item.org&&item.title?`<div class="rt-card-role">${esc(item.title)}</div>`:''}<div class="rt-card-date">${esc(item.dateLabel)}${item.duration?` · <strong>${esc(item.duration)}</strong>`:''}</div>${actions(item)}${evidence(item)}</article>`;
  }
  function periodRow(item) {
    return `<article class="rt-entry rt-period rt-gap" data-item="${esc(item.id)}"><div class="rt-gap-tag">${item.scope==='employment'?'Gap in listed employment':'Unrepresented period'}</div><div class="rt-gap-dates">${esc(item.start_label || item.start)} <span aria-hidden="true">→</span> ${esc(item.end_label || item.end)}</div><div class="rt-gap-dur">${item.months} month${item.months===1?'':'s'}</div><p class="rt-gap-between">${esc(item.between)}</p>${actions(item)}${evidence(item)}</article>`;
  }
  function timelineHtml() {
    let previousYear='',html='';
    for(const item of [...vm.visibleEvents].sort((a,b)=>(a.start||'9999').localeCompare(b.start||'9999'))) {
      const year=item.start?.slice(0,4) || 'Dates unclear';
      if(year!==previousYear){html+=`<li class="rt-year">${esc(year)}</li>`;previousYear=year;}
      html+=`<li class="rt-tev"><span class="rt-tdot" aria-hidden="true">${item.type==='EDUCATION'?'◇':'●'}</span>${eventRow(item)}</li>`;
    }
    return `<ol class="rt-tl">${html}</ol>`;
  }
  function notesHtml() {
    const current=vm.notes.filter(n=>n.author && n.author!=='Author not recorded');
    const history=[...vm.notes.filter(n=>!n.author || n.author==='Author not recorded'),...vm.legacyNotes.map(text=>({text}))];
    const groups=new Map();
    for(const note of history){
      const text=String(note.text||'').replace(/^\[(?:gap|event):[^\]]+\]\s*/,'');
      if(!groups.has(text))groups.set(text,[]);
      groups.get(text).push(note);
    }
    const time=n=>n.created_at?`<time datetime="${esc(n.created_at)}">${esc(new Date(n.created_at).toLocaleString())}</time>`:'Date not recorded';
    return `<details id="rt-notes" class="rt-notes"><summary>Resume notes <small>${current.length+history.length?`(${current.length+history.length})`:''}</small></summary><div id="rt-note-list">${current.map(n=>`<article class="rt-note"><small><strong>${esc(n.author)}</strong> · ${time(n)}</small><p>${esc(n.text)}</p></article>`).join('')}${history.length?`<details id="rt-note-history" class="rt-note-history"><summary>Earlier notes (${history.length})</summary><small>These older entries have no recorded author.</small>${[...groups].map(([text,notes])=>`<article class="rt-note"><p>${esc(text)}</p><details><summary>${notes.length} saved entr${notes.length===1?'y':'ies'} · dates</summary>${notes.map(n=>`<div><small>${time(n)}</small></div>`).join('')}</details></article>`).join('')}</details>`:''}</div><form id="rt-note-form"><label>Your name<input id="rt-author" name="author" required maxlength="200" value="${esc(draft.author)}" autocomplete="name"></label><label>General note<textarea id="rt-note" name="note" required maxlength="10000" rows="3">${esc(draft.text)}</textarea></label><button type="submit">Save note</button></form></details>`;
  }
  function projectsHtml() {
    const list = vm.projects || [];
    return `<div class="rt-projects-list">${list.map(p => `
      <article class="rt-project-card" id="rt-item-${esc(p.id)}">
        <header class="rt-entry-head">
          <div class="rt-entry-title"><strong>${esc(p.name)}</strong>${p.duration ? ` · <span class="rt-dur">${esc(p.duration)}</span>` : ''}</div>
          ${p.client || p.role ? `<small class="rt-entry-sub" style="display:block;margin-top:2px;color:#64748b;">${[p.role, p.client].filter(Boolean).map(esc).join(' · ')}</small>` : ''}
        </header>
        ${p.details && p.details.length ? `<ul class="rt-project-details">${p.details.slice(0, 4).map(d => `<li>${esc(d)}</li>`).join('')}</ul>` : ''}
        <div class="rt-actions" style="margin-top:8px;">
          <button type="button" class="rt-action-view" data-view="${esc(p.id)}">View in resume</button>
        </div>
      </article>
    `).join('')}</div>`;
  }
  function render() {
    vm=RT_VM.mapTimelineResultToRecruiterViewModel(dto);
    const open=new Set([...panel.querySelectorAll('details[open][id]')].map(e=>e.id));
    const periods=vm.periods.filter(g=>!g.hidden), review=vm.visibleEvents.filter(e=>e.uncertain);
    const projects=vm.projects || [];
    if(activeTab==='review' && !review.length)activeTab='overview';
    const tabs=[['overview','Overview'],['timeline','Timeline'],...(projects.length?[['projects',`Projects (${projects.length})`]]:[]),...(review.length?[['review','Needs review']]:[])];
    const summaryTitle=vm.status==='FAILED'?'Resume could not be read':periods.length?`${periods.length} ${periods.every(g=>g.scope==='employment')?'gap'+(periods.length===1?'':'s')+' detected in listed employment':'unrepresented period'+(periods.length===1?'':'s')+' detected'}`:review.length?'Dates need verification':'Timeline summary';
    const summaryDetail=periods.length?periods.map(g=>g.label+(g.between?' · '+g.between:'')).join('\n'):vm.assessment;
    shell(`<section class="rt-sum"><strong>${esc(summaryTitle)}</strong>${summaryDetail?`<p>${esc(summaryDetail)}</p>`:''}<small>${vm.events.length} timeline entries${projects.length?` · ${projects.length} projects`:''}${review.length?` · ${review.length} need review`:''}</small></section><div class="rt-tabs" role="tablist" aria-label="Resume results">${tabs.map(([key,label])=>`<button id="rt-tab-${key}" role="tab" aria-controls="rt-pane-${key}" aria-selected="${activeTab===key}" tabindex="${activeTab===key?'0':'-1'}" data-tab="${key}">${label}</button>`).join('')}</div><section id="rt-pane-overview" role="tabpanel" aria-labelledby="rt-tab-overview" ${activeTab!=='overview'?'hidden':''}>${periods.map(periodRow).join('') || '<p class="rt-empty">No potential periods to display.</p>'}${review.length?`<p class="rt-review-count">${review.length} entr${review.length===1?'y needs':'ies need'} date verification. See Needs review.</p>`:''}</section><section id="rt-pane-timeline" role="tabpanel" aria-labelledby="rt-tab-timeline" ${activeTab!=='timeline'?'hidden':''}>${vm.visibleEvents.length?timelineHtml():'<p>No supported entries to show.</p>'}</section><section id="rt-pane-projects" role="tabpanel" aria-labelledby="rt-tab-projects" ${activeTab!=='projects'?'hidden':''}>${projects.length?projectsHtml():'<p class="rt-empty">No projects detected.</p>'}</section><section id="rt-pane-review" role="tabpanel" aria-labelledby="rt-tab-review" ${activeTab!=='review'?'hidden':''}>${review.map(item=>`<div class="rt-review-link"><strong>${esc(item.label)}</strong><small>${esc(item.dateLabel)}</small>${actions(item)}</div>`).join('') || '<p>No entries need date review.</p>'}</section>${vm.hiddenItems.length?`<details id="rt-hidden-items" class="rt-hidden-items"><summary>Hidden items (${vm.hiddenItems.length})</summary>${vm.hiddenItems.map(item=>item.months?periodRow(item):eventRow(item)).join('')}</details>`:''}${notesHtml()}<small class="rt-foot">An unrepresented period does not establish unemployment.</small>`);
    panel.querySelectorAll('details[id]').forEach(e=>{e.open=open.has(e.id);});
    bindEvents();
  }
  async function updateItem(id, changes) {
    try {
      const state=await send({type:'rt-state',docId,payload:{target_id:id,...changes}});
      dto.item_state={...(dto.item_state||{}),[id]:state}; render();
    } catch(error) {status(error.message); renderStateControls();}
  }
  async function highlightInPage(msg) {
    if (extensionPage) throw new Error('Select evidence in the original resume tab.');
    if (msg.locations?.every(l=>l.kind==='pdf') && !document.querySelector('.pdfViewer .page'))
      return {nativePdf:true};
    return RT_SOURCE.show(msg.docId, msg.locations);
  }

  function renderStateControls() {panel.querySelectorAll('[data-reviewed]').forEach(input=>{input.checked=!!dto.item_state?.[input.dataset.reviewed]?.reviewed;});}
  async function getTargetTabId() {
    if (sourceTabId) return sourceTabId;
    try {
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      const cand = tabs.find(t => t.id && !t.url?.startsWith('chrome-extension:'));
      if (cand?.id) { sourceTabId = cand.id; return cand.id; }
    } catch (e) {}
    try {
      const all = await chrome.tabs.query({});
      const cand = all.find(t => t.id && !t.url?.startsWith('chrome-extension:'));
      if (cand?.id) { sourceTabId = cand.id; return cand.id; }
    } catch (e) {}
    return undefined;
  }

  function bindEvents() {
    panel.querySelectorAll('[data-tab]').forEach(button=>{
      button.onclick=()=>{activeTab=button.dataset.tab;render();document.getElementById('rt-tab-'+activeTab).focus();};
      button.onkeydown=event=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
        event.preventDefault();const tabs=[...panel.querySelectorAll('[data-tab]')].map(b=>b.dataset.tab);
        activeTab=event.key==='Home'?tabs[0]:event.key==='End'?tabs[tabs.length-1]:tabs[(tabs.indexOf(activeTab)+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length];
        render();document.getElementById('rt-tab-'+activeTab).focus();
      };
    });
    panel.querySelectorAll('[data-hide]').forEach(button=>{button.onclick=()=>updateItem(button.dataset.hide,{hidden:!dto.item_state?.[button.dataset.hide]?.hidden});});
    panel.querySelectorAll('[data-view]').forEach(button=>{button.onclick=async()=>{
      try {
        const item=[...vm.events,...vm.periods,...(vm.projects||[])].find(e=>e.id===button.dataset.view);
        if (!item) return;
        const locations=RT_SOURCE.locationsFor(item);
        const nativePdf=locations.every(l=>l.kind==='pdf') && !document.querySelector('.pdfViewer .page');
        const targetTab = sourceTabId || (await getTargetTabId());
        const result = extensionPage || nativePdf
          ? await send({type:'rt-highlight',docId,locations,tabId:targetTab})
          : await RT_SOURCE.show(docId,locations);
        const pageNum = result?.page || locations[0]?.page || 1;
        const itemLabel = item.org || item.title || item.between || item.label || 'entry';
        if (result?.needsPdfPermission) {
          if (targetTab) {
            try {
              const tab = await chrome.tabs.get(targetTab);
              const targetUrl = RT_SOURCE.nativeUrl(tab.url, locations);
              await chrome.tabs.update(targetTab, { url: targetUrl });
              status('Highlighted the original resume evidence.');
              return;
            } catch(e) {}
          }
          RT_SOURCE.offerPdfPermission(document.getElementById('rt-status'),button.onclick);return;
        }
        if (!result?.highlighted) throw new Error('The viewer could not highlight this source.');
        status('Highlighted the original resume evidence.');
      } catch(error) {status(error.message);}
    };});
    const form=document.getElementById('rt-note-form');
    form.oninput=()=>{draft={author:form.author.value,text:form.note.value};chrome.storage.local.set({[`draft:${docId}`]:draft}).catch(()=>{});};
    form.onsubmit=async event=>{
      event.preventDefault(); if(!form.reportValidity())return;
      const button=form.querySelector('button'); button.disabled=true;
      try {
        const notes=await send({type:'rt-add-note',docId,payload:{id:crypto.randomUUID(),author:form.author.value,text:form.note.value}});
        draft={author:form.author.value,text:''}; dto.notes=notes;
        await chrome.storage.local.set({recruiterName:draft.author,[`draft:${docId}`]:draft}); render(); status('Note saved.');
      } catch(error) {button.disabled=false;status(error.message);}
    };
  }
  function refreshEvaluation() {
    send({type:'rt-quality'}).then(value=>{evaluation=value;const el=document.getElementById('rt-evaluation');if(el)el.textContent=qualityLine();}).catch(()=>{});
  }
  pill.onclick=()=>{panel.hidden=!panel.hidden;if(!panel.hidden){if(dto)render();else analyze();}};
  document.addEventListener('keydown',event=>{if(event.key==='Escape')RT_SOURCE.close();});
  chrome.runtime.onMessage.addListener((msg,_sender,reply)=>{
    if(msg?.type==='rt-toggle-and-analyze') {
      panel.hidden=false;
      if(dto){render();reply({doc_id:docId});}
      else{analyze().then(()=>reply(docId?{doc_id:docId}:{_rtError:'No readable resume found.'}));}
      return true;
    }
    if(msg?.type==='rt-analyze-current') {
      analyze().then(()=>reply(docId?{doc_id:docId}:{_rtError:'No readable resume found.'}));
      return true;
    }
    if(msg?.type==='rt-highlight-source') {
      highlightInPage(msg).then(reply).catch(error=>reply({_rtError:error.message}));
      return true;
    }
    if(msg?.type!=='rt-show-doc')return;
    (async()=>{docId=msg.docId;dto=await send({type:'rt-timeline',docId});RT_SOURCE.bind({docId,inPage:true});await loadDraft();panel.hidden=false;render();reply({ok:true});})().catch(error=>reply({_rtError:error.message}));
    return true;
  });
  if(extensionPage) {
    shell('<p>Detecting resume…</p>');
    const tabId=Number(new URL(location.href).searchParams.get('tab')) || undefined;
    send({type:'rt-current-document',tabId}).then(async current=>{
      if(current?.docId){
        sourceTabId=current.tabId;docId=current.docId;RT_SOURCE.bind({docId});dto=await send({type:'rt-timeline',docId});await loadDraft();render();
      }else{
        const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
        if(tab?.id){
          const res=await chrome.tabs.sendMessage(tab.id,{type:'rt-analyze-current'}).catch(()=>null);
          if(res?.doc_id){
            sourceTabId=tab.id;
            docId=res.doc_id;RT_SOURCE.bind({docId});dto=await send({type:'rt-timeline',docId});await loadDraft();render();
            return;
          }
        }
        status('Open a resume in the active tab to detect its timeline.');
      }
    }).catch(error=>status(error.message));
  }
})();
