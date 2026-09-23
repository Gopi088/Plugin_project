/* Popup: Instant in-extension resume detection, gaps & timeline display. */
const $ = (id) => document.getElementById(id);
const via = (msg) =>
  new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve)).then((r) => {
    if (r && r._rtError) throw new Error(r._rtError);
    return r;
  });

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

let activeTabId = null;
let currentDocId = null;
let currentDto = null;
let currentVm = null;

function setStatus(text, type = "info") {
  const el = $("status-banner");
  if (!el) return;
  el.textContent = text;
  el.className = type === "error" ? "error" : type === "success" ? "success" : "";
  el.hidden = !text;
}

async function renderViewModel(dto) {
  currentDto = dto;
  const evaluation=$('evaluation-accuracy');
  evaluation.textContent=RT_VM.formatEvaluation(null, dto);
  via({type:'rt-quality'}).then(report=>{evaluation.textContent=RT_VM.formatEvaluation(report, dto);}).catch(()=>{});
  currentVm = RT_VM.mapTimelineResultToRecruiterViewModel(dto);
  const vm = currentVm;

  $("results-view").hidden = false;
  $("candidate-name").textContent = dto.candidate_name || dto.filename || "Candidate Resume";
  $("candidate-sub").textContent = `${vm.events.length} timeline entries · ${dto.filename || ''}`;

  const revBtn = $("btn-doc-reviewed");
  const revText = $("review-status-text");
  const savedState = await chrome.storage.local.get([`reviewed:${currentDocId}`]);
  let isRev = savedState[`reviewed:${currentDocId}`] !== undefined ? !!savedState[`reviewed:${currentDocId}`] : (dto.is_reviewed || vm.isReviewed);
  function updateReviewButtonUI(reviewed) {
    if (!revBtn || !revText) return;
    if (reviewed) {
      revBtn.className = 'btn-review-toggle is-reviewed';
      revText.textContent = '✓ Reviewed';
      revBtn.title = 'Marked as reviewed. Click to mark unreviewed.';
    } else {
      revBtn.className = 'btn-review-toggle unreviewed';
      revText.textContent = 'Mark Reviewed';
      revBtn.title = 'Click to mark resume as reviewed.';
    }
  }
  updateReviewButtonUI(isRev);
  if (revBtn) {
    revBtn.onclick = async () => {
      isRev = !isRev;
      updateReviewButtonUI(isRev);
      await chrome.storage.local.set({ [`reviewed:${currentDocId}`]: isRev });
      via({
        type: 'rt-feedback',
        docId: currentDocId,
        payload: { overrides: [{ type: 'document_reviewed', reviewed: isRev }] }
      }).catch(() => {});
      setStatus(isRev ? '✓ Marked resume as Reviewed' : 'Marked resume as Unreviewed', 'info');
    };
  }

  const gapsContainer = $("gaps-container");
  const periods = vm.periods || [];
  $("gap-count").textContent = periods.length ? `(${periods.length})` : "(0)";

  if (!periods.length) {
    gapsContainer.innerHTML = `<div class="verified-continuous">${esc(vm.assessment)}</div>`;
  } else {
    gapsContainer.innerHTML = periods.map(g => `
      <div class="gap-card" id="gap-${esc(g.id)}">
        <div>
          <span class="gap-badge">${esc(g.months)} mo${g.months === 1 ? '' : 's'} gap</span>
          <span class="gap-dates">${esc(g.start_label || g.start)} → ${esc(g.end_label || g.end)}</span>
        </div>
        <div class="gap-context">Between <strong>${esc(g.between || 'documented entries')}</strong></div>
        <button type="button" class="btn-verify" data-item-id="${esc(g.id)}">📍 View in resume</button>
      </div>
    `).join('');
  }

  const timelineContainer = $("timeline-container");
  const visible = vm.visibleEvents || [];
  $("event-count").textContent = `(${visible.length})`;

  timelineContainer.innerHTML = `<ul class="timeline-list">${
    visible.map(e => `
      <li class="timeline-item ${e.type === 'EDUCATION' ? 'edu' : 'work'}">
        <div class="item-head">
          <span class="item-title">${esc(e.org || e.title || 'Role')}</span>
          ${e.duration ? `<span class="duration-pill">${esc(e.duration)}</span>` : ''}
        </div>
        ${e.title && e.org ? `<div class="item-org">${esc(e.title)}</div>` : ''}
        <div class="item-dates">${esc(e.dateLabel || e.rawDateString || '')}</div>
        <button type="button" class="btn-verify" data-item-id="${esc(e.id)}">📍 View in resume</button>
      </li>
    `).join('')
  }</ul>`;

  const projectsContainer = $("projects-container");
  const projects = vm.projects || [];
  $("project-count").textContent = `(${projects.length})`;
  if (projectsContainer) {
    if (!projects.length) {
      projectsContainer.innerHTML = `<p style="font-size:12px;color:#64748b;margin:6px 0;">No projects detected.</p>`;
    } else {
      projectsContainer.innerHTML = `<ul class="timeline-list">${
        projects.map(p => `
          <li class="timeline-item" style="border-left:3px solid #8b5cf6;">
            <div class="item-head">
              <span class="item-title">${esc(p.name)}</span>
              ${p.duration ? `<span class="duration-pill" style="background:#ede9fe;color:#6d28d9;">${esc(p.duration)}</span>` : ''}
            </div>
            ${p.client || p.role ? `<div class="item-org">${[p.role, p.client].filter(Boolean).map(esc).join(' · ')}</div>` : ''}
            <button type="button" class="btn-verify" data-item-id="${esc(p.id)}">📍 View in resume</button>
          </li>
        `).join('')
      }</ul>`;
    }
  }

  document.querySelectorAll('.btn-verify').forEach(btn => {
    btn.onclick = async () => {
      const id = btn.dataset.itemId;
      const item = [...vm.events, ...vm.periods, ...(vm.projects || [])].find(x => x.id === id);
      if (!item) return;
      try {
        const locations = RT_SOURCE.locationsFor(item);
        const result = await via({
          type: 'rt-highlight', docId: currentDocId,
          locations, tabId: activeTabId
        });
        const pageNum = result?.page || locations[0]?.page || 1;
        const itemLabel = item.org || item.title || item.between || item.label || 'entry';
        if (result?.needsPdfPermission) {
          if (activeTabId) {
            try {
              const tab = await chrome.tabs.get(activeTabId);
              const targetUrl = RT_SOURCE.nativeUrl(tab.url, locations);
              await chrome.tabs.update(activeTabId, { url: targetUrl });
              setStatus('Highlighted the original resume evidence.', 'success');
              return;
            } catch(e) {}
          }
          RT_SOURCE.offerPdfPermission($('status-banner'),btn.onclick);return;
        }
        if (!result?.highlighted) throw Error('The viewer could not highlight this source.');
        setStatus('Highlighted the original resume evidence.', 'success');
      } catch (err) {
        setStatus(`Highlight error: ${err.message}`, 'error');
      }
    };
  });

  setStatus(periods.length ? `⚠️ Detected ${periods.length} gap${periods.length === 1 ? '' : 's'}. Review cards below.` : vm.assessment, periods.length ? 'error' : 'success');
}

async function detectResumeOnActiveTab(force = false) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) {
    setStatus("No active tab found.", "error");
    return;
  }
  activeTabId = tab.id;
  setStatus("🔍 Scanning active tab for resume…");

  // If tab URL is a direct PDF or DOCX file
  if (tab.url && /\.(pdf|docx?)(\?|#|$)/i.test(tab.url)) {
    try {
      setStatus("Reading resume document…");
      const payload = await via({ type: "rt-read-resume", url: tab.url });
      const sub = await via({ type: "rt-submit", payload });
      currentDocId = sub.doc_id;
      await chrome.storage.local.set({ lastDocId: sub.doc_id });
      const dto = await via({ type: "rt-timeline", docId: currentDocId });
      await renderViewModel(dto);
      return;
    } catch (e) {
      // Fall through to in-page analysis
    }
  }

  // Ask content script in active tab to analyze the resume on screen
  try {
    const result = await chrome.tabs.sendMessage(tab.id, { type: 'rt-analyze-current' });
    if (result?.doc_id) {
      currentDocId = result.doc_id;
      await chrome.storage.local.set({ lastDocId: result.doc_id });
      const dto = await via({ type: "rt-timeline", docId: currentDocId });
      await renderViewModel(dto);
      return;
    }
    if (result?._rtError) throw new Error(result._rtError);
  } catch (err) {
    // If not analyzed yet, check if we have a last analyzed document
    if (!force) {
      const current = await via({type:'rt-current-document',tabId:tab.id}).catch(()=>null);
      if (current?.docId) {
        try {
          currentDocId = current.docId;
          const dto = await via({ type: "rt-timeline", docId: currentDocId });
          await renderViewModel(dto);
          setStatus("Showing the analysis linked to this resume tab.", "info");
          return;
        } catch (e) {}
      }
    }
    setStatus("No resume detected in the current tab. Open a resume or upload one below.", "error");
  }
}

const reanalyzeBtn = $("btn-reanalyze");
if (reanalyzeBtn) {
  reanalyzeBtn.onclick = async () => {
    currentDocId = null;
    currentDto = null;
    currentVm = null;
    await detectResumeOnActiveTab(true);
  };
}

// Side panel and in-page toggle buttons
$("btn-sidepanel").onclick = async () => {
  if (!activeTabId) return;
  try {
    if (chrome.sidePanel?.open) {
      await chrome.sidePanel.open({ tabId: activeTabId });
      window.close();
    }
  } catch (e) {
    setStatus(e.message, "error");
  }
};

$("btn-inpage").onclick = async () => {
  if (!activeTabId) return;
  try {
    await chrome.tabs.sendMessage(activeTabId, { type: 'rt-toggle-and-analyze' });
    window.close();
  } catch (e) {
    setStatus(e.message, "error");
  }
};

// Fallback manual file upload
$("upload").onclick = async () => {
  const f = $("file").files[0];
  if (!f) return setStatus("Choose a file first.", "error");
  setStatus("Uploading & parsing resume…");
  const buf = await f.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 8192)
    bin += String.fromCharCode(...bytes.subarray(i, i + 8192));
  try {
    const r = await via({
      type: "rt-submit",
      payload: { filename: f.name, content_b64: btoa(bin), source: "extension-upload" },
    });
    currentDocId = r.doc_id;
    await chrome.storage.local.set({ lastDocId: r.doc_id });
    const dto = await via({ type: "rt-timeline", docId: r.doc_id });
    await renderViewModel(dto);
  } catch (e) {
    setStatus(`Failed: ${e.message}`, "error");
  }
};

// Fallback manual URL submit
$("sendUrl").onclick = async () => {
  const url = $("url").value.trim();
  if (!url) return setStatus("Enter a URL first.", "error");
  setStatus("Reading resume from URL…");
  try {
    const r = await via({
      type: "rt-submit",
      payload: await via({ type: "rt-read-resume", url }),
    });
    currentDocId = r.doc_id;
    await chrome.storage.local.set({ lastDocId: r.doc_id });
    const dto = await via({ type: "rt-timeline", docId: r.doc_id });
    await renderViewModel(dto);
  } catch (e) {
    setStatus(`Failed: ${e.message}`, "error");
  }
};

$("save").onclick = async () => {
  await chrome.storage.local.set({ apiBase: $("apiBase").value.trim() });
  setStatus("Saved API base.", "success");
};

$('extension-version').textContent='v'+chrome.runtime.getManifest().version;

// Start detection as soon as popup is clicked
detectResumeOnActiveTab();
