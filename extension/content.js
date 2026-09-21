/* Content script: detect resume, analyze via backend, render the
   attention-first recruiter UI (see viewmodel.js for the presentation model). */
(() => {
  if (window.__rtInjected) return;
  window.__rtInjected = true;

  const send = (msg) =>
    new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve)).then((r) => {
      if (r && r._rtError) throw new Error(r._rtError);
      return r;
    });

  // ------------------------------------------------ detection (unchanged)
  function detect() {
    const url = location.href;
    if (/\.(pdf|docx?)(\?|#|$)/i.test(url))
      return { kind: "document-url", url };
    const pdfEmbed = document.querySelector(
      'embed[type="application/pdf"], object[type="application/pdf"], embed[src*=".pdf"]'
    );
    if (pdfEmbed?.src || pdfEmbed?.data)
      return { kind: "document-url", url: pdfEmbed.src || pdfEmbed.data };
    const text = (document.body?.innerText || "").slice(0, 60000);
    const hasExp = /professional experience|work experience|employment/i.test(text);
    const hasEdu = /education|academic|qualification/i.test(text);
    const hasDate = /(19|20)\d{2}/.test(text);
    if (hasExp && hasEdu && hasDate && text.length > 1500)
      return { kind: "page-text", text };
    const link = [...document.querySelectorAll("a[href]")].find((a) =>
      /\.(pdf|docx?)(\?|#|$)/i.test(a.href)
    );
    if (link) return { kind: "document-url", url: link.href };
    return null;
  }

  // ------------------------------------------------ helpers
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const setPanel = (html) => { document.getElementById("rt-panel").innerHTML = html; };
  const head = (name, chip) =>
    `<div class="rt-head"><div><div class="rt-title">Resume Timeline</div>` +
    `<div class="rt-candidate">${esc(name || "")}</div></div>` +
    `<div class="rt-head-r">${chip || ""}<button class="rt-x" id="rt-close" aria-label="Close panel">✕</button></div></div>`;
  const body = (inner) => `<div class="rt-body">${inner}</div>`;
  const foot = () => `<div class="rt-disc">Potential gaps indicate periods not clearly represented in the resume. They do not establish unemployment.</div>`;
  const bindClose = () => {
    const b = document.getElementById("rt-close");
    if (b) b.onclick = () => togglePanel(false);
  };

  function ensureUI() {
    if (document.getElementById("rt-pill")) return;
    const pill = document.createElement("button");
    pill.className = "rt-pill";
    pill.id = "rt-pill";
    pill.textContent = "Timeline";
    pill.title = "Resume Timeline & Gap Detection";
    pill.addEventListener("click", () => togglePanel());
    document.documentElement.appendChild(pill);
    const panel = document.createElement("aside");
    panel.className = "rt-panel rt-hidden";
    panel.id = "rt-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Resume timeline panel");
    document.documentElement.appendChild(panel);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") togglePanel(false);
    });
  }

  function togglePanel(force) {
    const p = document.getElementById("rt-panel");
    const show = force !== undefined ? force : p.classList.contains("rt-hidden");
    p.classList.toggle("rt-hidden", !show);
    if (show) start();
  }

  // ------------------------------------------------ state + flow
  let currentDoc = null;
  let vm = null;
  let activeTab = "overview";
  const expanded = new Set();   // "gap:<id>" | "ev:<id>"
  const evCache = {};           // gapId -> chain
  const noteOpen = new Set();   // "note:<kind>:<id>:<decision>"

  const STEPS = ["Reading resume", "Finding dated activities", "Building timeline", "Checking represented periods"];

  let analyzing = false;
  async function start() {
    if (analyzing) return;
    analyzing = true;
    try { await analyzeDetected(); } finally { analyzing = false; }
  }

  async function analyzeDetected() {
    activeTab = "overview";
    expanded.clear();
    let apiBase = "http://127.0.0.1:8000";
    try {
      const s = await chrome.storage.local.get("apiBase");
      if (s.apiBase) apiBase = s.apiBase;
    } catch (e) { /* keep default */ }
    setPanel(head("", "") + body(`<div class="rt-steps" role="status" aria-live="polite">${STEPS.map((s, i) => `<div class="rt-step" data-step="${i}"><span class="rt-spin"></span>${esc(s)}…</div>`).join("")}</div>`));
    bindClose();
    const tick = (i) => {
      const n = document.querySelector(`#rt-panel [data-step="${i}"]`);
      if (n) { n.classList.add("rt-done"); n.innerHTML = `<span class="rt-tick">✓</span>${esc(STEPS[i])}`; }
    };
    try {
      await send({ type: "rt-health" });
    } catch (e) {
      setPanel(head("", "") + body(`<div class="rt-err">Backend not reachable at <code>${esc(apiBase)}</code>.<br>Start it with<br><code>venv/bin/python backend/server.py</code><br>and match the API base in the extension popup.</div>`));
      bindClose();
      return;
    }
    const det = detect();
    if (!det) {
      setPanel(head("", "") + body(`<div class="rt-err">No resume detected on this page.</div>
        <div class="rt-hint">Open a PDF/DOCX resume, an ATS candidate page, or upload a file from the extension popup.</div>`));
      bindClose();
      return;
    }
    tick(0);
    try {
      const payload = await buildPayload(det);
      tick(1);
      const sub = await send({ type: "rt-submit", payload });
      currentDoc = sub.doc_id;
      await chrome.storage.local.set({ lastDocId: currentDoc });
      tick(2);
      const dto = await send({ type: "rt-timeline", docId: currentDoc });
      tick(3);
      show(dto);
    } catch (e) {
      showError(det, e);
    }
  }

  async function buildPayload(det) {
    if (det.kind === "page-text")
      return { filename: "page-resume.txt", text: det.text, source: "extension-text" };
    return send({ type: "rt-read-resume", url: det.url });
  }

  function showError(det, e) {
    const picked = det && det.url && det.url.startsWith("file://");
    setPanel(head("", "") + body(
      `<div class="rt-err">Analysis failed: ${esc(e.message)}</div>` +
      (picked
        ? `<div class="rt-hint">If the file is unavailable, you can select a copy:</div>
           <div class="rt-row"><input type="file" id="rt-file" accept=".pdf,.docx,.txt" aria-label="Resume file"><button id="rt-go">Analyze</button></div>`
        : `<div class="rt-hint">The resume may be scanned or the link may block fetching — try uploading via the popup.</div>`)
    ));
    bindClose();
    const go = document.getElementById("rt-go");
    if (go) go.onclick = panelUpload;
  }

  async function panelUpload() {
    const f = document.getElementById("rt-file")?.files[0];
    if (!f) return;
    setPanel(head("", "") + body(`<div class="rt-loading" role="status">Analyzing resume…</div>`));
    bindClose();
    try {
      const bytes = new Uint8Array(await f.arrayBuffer());
      let bin = "";
      for (let i = 0; i < bytes.length; i += 8192)
        bin += String.fromCharCode(...bytes.subarray(i, i + 8192));
      const sub = await send({ type: "rt-submit", payload: { filename: f.name, content_b64: btoa(bin), source: "extension-file" } });
      currentDoc = sub.doc_id;
      await chrome.storage.local.set({ lastDocId: currentDoc });
      show(await send({ type: "rt-timeline", docId: currentDoc }));
    } catch (e) {
      setPanel(head("", "") + body(`<div class="rt-err">Analysis failed: ${esc(e.message)}</div>`));
      bindClose();
    }
  }

  // ------------------------------------------------ view-model render
  function rules() {
    return (window.RT_VM || {}).attentionRules || {};
  }

  function show(dto) {
    vm = RT_VM.mapTimelineResultToRecruiterViewModel(dto, { ...RT_VM.attentionRules, ...rules() });
    vm._dto = dto;
    render();
    send({ type: "rt-quality" }).then((q) => { evaluation = q; render(); }).catch(() => {});
  }

  function statusChip() {
    const m = {
      ATTENTION: ["rt-chip-high", "⚠", "Attention"],
      REVIEW: ["rt-chip-review", "?", "Review"],
      INSUFFICIENT_EVIDENCE: ["rt-chip-review", "?", "Needs review"],
      CLEAR: ["rt-chip-clear", "✓", "Clear"],
    }[vm.overallStatus] || ["rt-chip-review", "?", ""];
    return `<span class="rt-chip ${m[0]}" aria-label="Status: ${m[2]}"><span aria-hidden="true">${m[1]}</span> ${m[2]}</span>`;
  }

  function summaryCard() {
    const icon = { ATTENTION: "⚠", REVIEW: "?", INSUFFICIENT_EVIDENCE: "?", CLEAR: "✓", FAILED: "✕" }[vm.docStatus === "FAILED" ? "FAILED" : vm.overallStatus];
    if (vm.docStatus === "FAILED")
      return `<section class="rt-sum rt-sum-review" aria-label="Summary"><div class="rt-sum-i" aria-hidden="true">✕</div>
        <div><div class="rt-sum-h">Unable to build timeline</div><div class="rt-sum-s">The resume could not be processed reliably.</div>
        <button data-nav="retry">Retry</button></div></section>`;
    if (vm.overallStatus === "ATTENTION") {
      const g = vm.highGaps[0];
      return `<section class="rt-sum rt-sum-high" aria-label="Summary: attention needed"><div class="rt-sum-i" aria-hidden="true">⚠</div>
        <div><div class="rt-sum-h">Attention needed</div>
        <div class="rt-sum-s">${vm.counts.potentialGaps} potential unrepresented period${vm.counts.potentialGaps > 1 ? "s" : ""}</div>
        <div class="rt-sum-big">${esc(g.range.start)} → ${esc(g.range.end)}</div>
        <div class="rt-sum-dur">${g.months} months</div>
        <div class="rt-sum-s">No activity is clearly represented during this period.</div>
        <button data-nav="overview">Review</button></div></section>`;
    }
    if (vm.overallStatus === "INSUFFICIENT_EVIDENCE")
      return `<section class="rt-sum rt-sum-review" aria-label="Summary: needs review"><div class="rt-sum-i" aria-hidden="true">?</div>
        <div><div class="rt-sum-h">Timeline needs review</div>
        <div class="rt-sum-s">Some dates could not be confidently interpreted.</div>
        <div class="rt-sum-s">${vm.counts.reviewItems} item${vm.counts.reviewItems === 1 ? "" : "s"} need review</div>
        <button data-nav="review">Review items</button></div></section>`;
    if (vm.overallStatus === "REVIEW")
      return `<section class="rt-sum rt-sum-review" aria-label="Summary: review"><div class="rt-sum-i" aria-hidden="true">?</div>
        <div><div class="rt-sum-h">${esc(vm.headline)}</div><div class="rt-sum-s">${esc(vm.summary)}</div>
        <button data-nav="review">Review</button></div></section>`;
    return `<section class="rt-sum rt-sum-clear" aria-label="Summary: clear"><div class="rt-sum-i" aria-hidden="true">✓</div>
      <div><div class="rt-sum-h">Timeline looks continuous</div>
      <div class="rt-sum-s">${vm.counts.events} timeline events · ${vm.counts.potentialGaps} potential periods · ${vm.counts.reviewItems} need review</div>
      <button data-nav="timeline">View timeline</button></div></section>`;
  }

  function gapCard(g) {
    const r = g.range || { start: "?", end: "?" };
    const cls = g.priority === "HIGH" ? "rt-gap-high" : "rt-gap-review";
    const tag = g.priority === "HIGH" ? "POTENTIAL UNREPRESENTED" : "POSSIBLE UNREPRESENTED";
    const key = `gap:${g.id}`;
    const open = expanded.has(key);
    const evKey = `evdrawer:${g.id}`;
    const evOpen = expanded.has(evKey);
    const dec = decisionFor("gap", g.id);
    return `<article class="rt-gap ${cls}" aria-label="${tag}, ${r.start} to ${r.end}, ${g.months} months">
      <div class="rt-gap-tag"><span aria-hidden="true">${g.priority === "HIGH" ? "⚠" : "?"}</span> ${tag}</div>
      <div class="rt-gap-dates">${esc(r.start)} <span class="rt-gap-line" aria-hidden="true">──────</span> ${esc(r.end)}</div>
      <div class="rt-gap-dur">${g.months} month${g.months === 1 ? "" : "s"}</div>
      <div class="rt-gap-sub">No activity clearly shown during this period.</div>
      ${dec ? `<div class="rt-dec">✓ ${esc(decLabel(dec.decision))}${dec.note ? ` — “${esc(dec.note)}”` : ""}</div>` : ""}
      <div class="rt-row"><button data-act="why" data-id="${esc(g.id)}">${open ? "Hide" : "Why?"}</button>
      <button data-act="evidence" data-id="${esc(g.id)}">${evOpen ? "Hide evidence" : "Review evidence"}</button></div>
      ${open ? whyBox(g) : ""}
      <div class="rt-evbox ${evOpen ? "" : "rt-hidden"}" id="rt-ev-${esc(g.id)}">${evOpen ? drawerHtml(g.id) : ""}</div>
      ${actionRow("gap", g.id)}
    </article>`;
  }

  function whyBox(g) {
    const chain = evCache[g.id];
    const before = (chain?.links || [])[0]?.event;
    const after = (chain?.links || [])[1]?.event;
    const line = (ev) => ev ? `<div><strong>${esc(ev.title || "Untitled")}</strong>${ev.org ? ` · ${esc(ev.org)}` : ""}<br><small>${esc(fmtEv(ev))}</small></div>` : "<div><small>—</small></div>";
    return `<div class="rt-why"><div class="rt-why-h">Why was this flagged?</div>
      <div class="rt-why-r"><span>Previous represented activity</span>${line(before)}</div>
      <div class="rt-why-r"><span>Next represented activity</span>${line(after)}</div>
      <div class="rt-why-s">No dated activity was identified between these intervals.</div></div>`;
  }

  function fmtEv(ev) {
    const f = (s) => String(s || "").replace(/^\((\d+), (\d+)\)$/, (_, y, m) => `${y}-${String(m).padStart(2, "0")}`);
    return `${f(ev.start)} → ${f(ev.end)}`;
  }

  function reviewCard(item, idx) {
    const key = `rev:${idx}`;
    const open = expanded.has(key);
    const target = item.gap ? { kind: "gap", id: item.gap.id } : { kind: "event", id: item.event?.id };
    const dec = target.id ? decisionFor(target.kind, target.id) : null;
    return `<article class="rt-rev" aria-label="Needs review: ${esc(item.title)}">
      <div class="rt-rev-tag"><span aria-hidden="true">?</span> ${item.kind === "GAP" ? "PERIOD NEEDS REVIEW" : item.kind === "DATE" ? "DATE NEEDS REVIEW" : "ENTRY NEEDS REVIEW"}</div>
      <div class="rt-rev-t">${esc(item.title)}</div>
      <div class="rt-rev-s">${esc(item.detail)}</div>
      ${dec ? `<div class="rt-dec">✓ ${esc(decLabel(dec.decision))}${dec.note ? ` — “${esc(dec.note)}”` : ""}</div>` : ""}
      <div class="rt-row"><button data-rev="${idx}">${open ? "Hide" : "Review"}</button></div>
      ${open && item.event ? `<div class="rt-why"><blockquote>“${esc((item.event.entry_text || item.event.title || "").slice(0, 300))}”</blockquote>
        <div><small>Confidence: ${esc(item.event.confidenceVerbal?.label || verbal(item.event.confidence))}</small></div></div>` : ""}
      ${open && target.id ? actionRow(target.kind, target.id) : ""}
    </article>`;
  }

  function verbal(c) {
    if (c == null) return "Insufficient evidence";
    if (c >= 0.75) return "High confidence";
    if (c >= 0.5) return "Needs review";
    return "Low confidence";
  }

  function decLabel(d) {
    return { CONFIRMED: "Confirmed", EXPLAINED: "Marked as explained", FOLLOW_UP: "Flagged for follow-up", DISMISSED: "Dismissed" }[d] || d;
  }

  function decisionFor(kind, id) {
    return (vm.decisions || []).filter((d) => d.target === `${kind}:${id}`).slice(-1)[0] || null;
  }

  function actionRow(kind, id) {
    const key = (dec) => `note:${kind}:${id}:${dec}`;
    const btns = [["CONFIRMED", "Confirm"], ["EXPLAINED", "Mark as explained"], ["FOLLOW_UP", "Needs follow-up"]]
      .map(([d, l]) => `<button data-dec="${d}" data-kind="${kind}" data-id="${esc(id)}">${l}</button>`).join("") +
      (kind === "gap" ? `<button data-dec="DISMISSED" data-kind="${kind}" data-id="${esc(id)}">Dismiss</button>` : "");
    const openNote = [...noteOpen].find((k) => k.startsWith(`note:${kind}:${id}:`));
    let noteHtml = "";
    if (openNote) {
      const dec = openNote.split(":").pop();
      noteHtml = `<div class="rt-note"><input id="rt-note-in" placeholder="Note (optional)" aria-label="Decision note">
        <button data-save="${esc(openNote)}">Save</button></div>`;
    }
    return `<div class="rt-actions" role="group" aria-label="Recruiter actions">${btns}</div>${noteHtml}`;
  }

  function eventCard(e) {
    const key = `ev:${e.id}`;
    const open = expanded.has(key);
    const dec = decisionFor("event", e.id);
    return `<li class="rt-tev" aria-label="${esc(e.title)}, ${esc(e.range.start)} to ${esc(e.range.end)}">
      <span class="rt-tdot" aria-hidden="true">${esc(e.icon)}</span>
      <div class="rt-tev-b"><button class="rt-tev-h" data-ev="${esc(e.id)}" aria-expanded="${open}">
        <span class="rt-tev-o">${esc(e.org || e.title || "Untitled")}</span><br>
        <span class="rt-tev-t">${esc(e.org ? e.title : e.type)} · ${esc(e.range.start)} – ${esc(e.range.end)}</span></button>
      ${open ? `<div class="rt-tev-d"><small>Type ${esc(e.type)} · ${esc(e.confidenceVerbal.label)}${e.precision === "year" ? " · year precision" : ""}</small>
        ${dec ? `<div class="rt-dec">✓ ${esc(decLabel(dec.decision))}</div>` : ""}${actionRow("event", e.id)}</div>` : ""}</div></li>`;
  }

  function timelineHtml() {
    const evs = [...vm.timelineEvents].sort((a, b) => (a.start || "") < (b.start || "") ? -1 : 1);
    let html = `<ol class="rt-tl">`, lastYear = "";
    for (const e of evs) {
      const y = (e.start || "").slice(0, 4);
      if (y && y !== lastYear) { html += `<li class="rt-year" aria-hidden="true">${esc(y)}</li>`; lastYear = y; }
      html += eventCard(e);
    }
    return html + "</ol>";
  }

  function render() {
    const tabs = [["overview", "Overview", ""], ["timeline", "Timeline", vm.counts.events], ["review", "Review", vm.counts.reviewItems]]
      .map(([k, l, n]) => `<button role="tab" aria-selected="${activeTab === k}" data-tab="${k}" class="${activeTab === k ? "rt-tab-on" : ""}">${l}${n ? ` <span class="rt-badge">${n}</span>` : ""}</button>`).join("");
    let content = "";
    if (activeTab === "overview") {
      const attn = [...vm.highGaps, ...vm.reviewGaps].map(gapCard).join("");
      const rev = vm.reviewItems.slice(0, 3).map(reviewCard).join("");
      content = (attn || (vm.overallStatus === "INSUFFICIENT_EVIDENCE" || vm.docStatus === "FAILED" ? `<div class="rt-warn">Insufficient evidence to assess represented periods.</div>` : `<div class="rt-clear">✓ No potential unrepresented periods detected</div>`)) +
        (vm.counts.events ? `<div class="rt-counts">${vm.counts.events} timeline events${vm.counts.reviewItems ? ` · ${vm.counts.reviewItems} need review` : ""}</div>` : "") +
        (rev ? `<h4>Needs review</h4>${rev}` : "") +
        (vm.lowGaps.length ? `<details class="rt-more"><summary>Minor periods (${vm.lowGaps.length})</summary>${vm.lowGaps.map(gapCard).join("")}</details>` : "") +
        (vm.dismissedGaps.length ? `<details class="rt-more"><summary>Dismissed (${vm.dismissedGaps.length})</summary>${vm.dismissedGaps.map((g) => `<div class="rt-muted">Dismissed: ${esc(g.start_label || g.start)} → ${esc(g.end_label || g.end)}</div>`).join("")}</details>` : "");
    } else if (activeTab === "timeline") {
      content = vm.timelineEvents.length ? timelineHtml()
        : `<div class="rt-warn">No dated events — timeline cannot be drawn.</div>`;
    } else {
      content = vm.reviewItems.length ? vm.reviewItems.map(reviewCard).join("")
        : `<div class="rt-clear">✓ Nothing needs review.</div>`;
    }
    setPanel(head(vm.candidateName, statusChip()) + body(
      summaryCard() +
      `<div class="rt-counts" aria-label="Counts">${vm.counts.events} events · ${vm.counts.potentialGaps} potential periods · ${vm.counts.reviewItems} to review${qualityLine()}</div>
       <div class="rt-tabs" role="tablist">${tabs}</div>
       <div class="rt-tabbody" role="tabpanel">${content}</div>` + foot()
    ));
    bindClose();
    bindAll();
  }

  let evaluation = null;
  function qualityLine() {
    const q = vm._dto?.quality;
    const pc = (v) => typeof v === "number" && Number.isFinite(v)
      ? `${Math.round(Math.max(0, Math.min(1, v)) * 100)}%` : "Unavailable";
    return `<br><strong>Extraction confidence: ${pc(q?.mean_event_confidence)}</strong>` +
      `<br><small>Heuristic confidence, not verified accuracy for this resume.</small>` +
      `<br>Dated entry completeness: ${pc(q?.dated_share)}` +
      `<br>Measured evaluation accuracy: ${pc(evaluation?.overall_accuracy)}` +
      (evaluation ? `<br><small>${esc(evaluation.cases)} labeled cases · mean job/gap F1 · ${esc((evaluation.generated_at || "").slice(0, 10))}</small>` : "");
  }

  function bindAll() {
    document.querySelectorAll("#rt-panel [data-tab]").forEach((b) => {
      b.onclick = () => { activeTab = b.dataset.tab; render(); };
    });
    document.querySelectorAll("#rt-panel [data-nav]").forEach((b) => {
      b.onclick = () => {
        const t = b.dataset.nav;
        activeTab = t === "retry" ? activeTab : t;
        if (t === "retry") start();
        else render();
      };
    });
    document.querySelectorAll("#rt-panel [data-act]").forEach((b) => {
      b.onclick = () => onGapAction(b.dataset.act, b.dataset.id);
    });
    document.querySelectorAll("#rt-panel [data-rev]").forEach((b) => {
      b.onclick = () => {
        const k = `rev:${b.dataset.rev}`;
        expanded.has(k) ? expanded.delete(k) : expanded.add(k);
        render();
      };
    });
    document.querySelectorAll("#rt-panel [data-ev]").forEach((b) => {
      b.onclick = () => {
        const k = `ev:${b.dataset.ev}`;
        expanded.has(k) ? expanded.delete(k) : expanded.add(k);
        render();
      };
    });
    document.querySelectorAll("#rt-panel [data-dec]").forEach((b) => {
      b.onclick = () => {
        if (b.dataset.dec === "DISMISSED") return decide(b.dataset.kind, b.dataset.id, "DISMISSED", "");
        const k = `note:${b.dataset.kind}:${b.dataset.id}:${b.dataset.dec}`;
        noteOpen.has(k) ? noteOpen.delete(k) : noteOpen.add(k);
        render();
        const inp = document.getElementById("rt-note-in");
        if (inp) inp.focus();
      };
    });
    document.querySelectorAll("#rt-panel [data-save]").forEach((b) => {
      b.onclick = () => {
        // key format: note:<kind>:<id>:<DECISION> (kind/id contain no colons)
        const parts = b.dataset.save.split(":");
        const decision = parts.pop(), eid = parts.pop();
        const ekind = parts.slice(1).join(":");
        const note = document.getElementById("rt-note-in")?.value || "";
        noteOpen.clear();
        decide(ekind, eid, decision, note);
      };
    });
  }

  async function decide(kind, id, decision, note) {
    if (!currentDoc) return;
    const payload = { dismissed_gap_ids: [], overrides: [], notes: "" };
    if (kind === "gap" && decision === "DISMISSED") payload.dismissed_gap_ids = [id];
    else payload.overrides = [{ target: `${kind}:${id}`, decision, note, at: new Date().toISOString() }];
    await send({ type: "rt-feedback", docId: currentDoc, payload });
    show(await send({ type: "rt-timeline", docId: currentDoc }));
  }

  async function onGapAction(act, gapId) {
    if (!currentDoc) return;
    if (act === "evidence") {
      const evKey = `evdrawer:${gapId}`;
      if (!expanded.has(evKey)) {
        if (!evCache[gapId]) {
          const box = document.getElementById(`rt-ev-${gapId}`);
          if (box) { box.classList.remove("rt-hidden"); box.innerHTML = `<small>Loading evidence…</small>`; }
          const ev = await send({ type: "rt-evidence", docId: currentDoc, params: { gap_id: gapId } });
          evCache[gapId] = ev.chain;
        }
        expanded.add(evKey);
      } else {
        expanded.delete(evKey);
      }
      render();
    } else if (act === "why") {
      const key = `gap:${gapId}`;
      expanded.has(key) ? expanded.delete(key) : expanded.add(key);
      render();
    }
  }

  function drawerHtml(gapId) {
    const chain = evCache[gapId];
    if (!chain || !chain.links) return "<small>No chain available.</small>";
    return chain.links.map((l) => {
      const pages = (l.text_blocks || []).map((b) => `p.${b.page}`).join(", ");
      const dates = (l.mentions || []).map((m) => `“${esc(m.raw)}”`).join("; ") || "—";
      const assoc = (l.associations || []).map((a) => `${a.status} (${esc(a.reason)})`).join("; ") || "—";
      return `<div class="rt-link"><div><strong>${esc(l.event?.title || "")}</strong>${l.event?.org ? ` · ${esc(l.event.org)}` : ""}</div>
        <blockquote>“${esc(l.entry_quote || "")}”</blockquote>
        <div><small>Pages: ${esc(pages || "—")} · Dates: ${dates}</small></div>
        <div><small>Association: ${assoc}</small></div>
        <details class="rt-adv"><summary>Advanced</summary>
        <div><small>Event confidence: ${l.event?.confidence ?? "—"} · Reasons: ${esc((l.event?.reasons || []).join(", "))}</small></div></details></div>`;
    }).join("");
  }

  // ------------------------------------------------ boot
  ensureUI();
  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (msg && msg.type === "rt-show-doc" && msg.docId) {
      currentDoc = msg.docId;
      document.getElementById("rt-panel").classList.remove("rt-hidden");
      send({ type: "rt-timeline", docId: msg.docId }).then(
        (dto) => { activeTab = "overview"; show(dto); reply({ ok: true }); },
        (e) => reply({ _rtError: String(e.message || e) })
      );
      return true;
    }
    return undefined;
  });
})();
