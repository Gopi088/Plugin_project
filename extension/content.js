/* Content script: detect resume on the page, inject non-intrusive UI,
   send content to backend via the service worker, render timeline. */
(() => {
  if (window.__rtInjected) return;
  window.__rtInjected = true;

  const send = (msg) =>
    new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve)).then((r) => {
      if (r && r._rtError) throw new Error(r._rtError);
      return r;
    });

  // ------------------------------------------------ detection
  function detect() {
    const url = location.href;
    if (/\.(pdf|docx?)(\?|#|$)/i.test(url))
      return { kind: "document-url", url, note: "Resume file opened in browser" };
    const pdfEmbed = document.querySelector(
      'embed[type="application/pdf"], object[type="application/pdf"], embed[src*=".pdf"]'
    );
    if (pdfEmbed?.src || pdfEmbed?.data)
      return { kind: "document-url", url: pdfEmbed.src || pdfEmbed.data, note: "Embedded resume PDF" };
    // HTML resume (ATS profile / web CV): needs Experience + Education + dates.
    const text = (document.body?.innerText || "").slice(0, 60000);
    const hasExp = /professional experience|work experience|employment/i.test(text);
    const hasEdu = /education|academic|qualification/i.test(text);
    const hasDate = /(19|20)\d{2}/.test(text);
    if (hasExp && hasEdu && hasDate && text.length > 1500)
      return { kind: "page-text", text, note: "Resume content found on page" };
    const link = [...document.querySelectorAll("a[href]")].find((a) =>
      /\.(pdf|docx?)(\?|#|$)/i.test(a.href)
    );
    if (link) return { kind: "document-url", url: link.href, note: "Resume link on page" };
    return null;
  }

  // ------------------------------------------------ UI shell
  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function ensureUI() {
    if (document.getElementById("rt-pill")) return;
    const pill = el("button", "rt-pill", "Timeline");
    pill.id = "rt-pill";
    pill.title = "Resume Timeline & Gap Detection";
    pill.addEventListener("click", () => togglePanel());
    document.documentElement.appendChild(pill);

    const panel = el("aside", "rt-panel rt-hidden");
    panel.id = "rt-panel";
    panel.setAttribute("aria-label", "Resume timeline panel");
    document.documentElement.appendChild(panel);
  }

  function togglePanel(force) {
    const p = document.getElementById("rt-panel");
    const show = force !== undefined ? force : p.classList.contains("rt-hidden");
    p.classList.toggle("rt-hidden", !show);
    if (show) start();
  }

  function setPanel(html) {
    document.getElementById("rt-panel").innerHTML = html;
  }

  // ------------------------------------------------ flow
  let currentDoc = null;

  async function start() {
    setPanel(`<div class="rt-head"><strong>Resume Timeline</strong><button class="rt-x" id="rt-close">✕</button></div>
      <div class="rt-body"><div class="rt-loading">Detecting resume…</div></div>`);
    document.getElementById("rt-close").onclick = () => togglePanel(false);
    let det;
    let apiBase = "http://127.0.0.1:8000";
    try {
      const s = await chrome.storage.local.get("apiBase");
      if (s.apiBase) apiBase = s.apiBase;
    } catch (e) {
      /* storage unavailable; keep default */
    }
    try {
      await send({ type: "rt-health" });
    } catch (e) {
      return setPanel(head() + body(`<div class="rt-err">Backend not reachable at <code>${apiBase.replace(/[<>&"]/g, "")}</code>.<br>Start it with<br><code>venv/bin/python backend/server.py</code><br>and match the API base in the extension popup.</div>`));
    }
    det = detect();
    if (!det) {
      return setPanel(head() + body(`<div class="rt-err">No resume detected on this page.</div>
        <div class="rt-hint">Open a PDF/DOCX resume, an ATS candidate page, or upload a file from the extension popup.</div>`));
    }
    setPanel(head() + body(`<div class="rt-loading">Processing ${esc(det.note.toLowerCase())}…</div>`));
    try {
      let payload;
      if (det.kind === "page-text") {
        payload = { filename: "page-resume.txt", text: det.text, source: "extension-text" };
      } else if (det.url.startsWith("file://")) {
        // Local file: the backend cannot reach this disk, so read the bytes
        // here (works with "Allow access to file URLs") and upload them.
        const resp = await fetch(det.url);
        if (!resp.ok) throw new Error(`cannot read local file (${resp.status})`);
        const bytes = new Uint8Array(await resp.arrayBuffer());
        let bin = "";
        for (let i = 0; i < bytes.length; i += 8192)
          bin += String.fromCharCode(...bytes.subarray(i, i + 8192));
        const name = decodeURIComponent(det.url.split("/").pop().split("?")[0]) || "resume";
        payload = { filename: name, content_b64: btoa(bin), source: "extension-file" };
      } else {
        payload = {
          filename: det.url.split("/").pop().split("?")[0] || "resume",
          source_url: det.url,
          source: "extension-url",
        };
      }
      const sub = await send({ type: "rt-submit", payload });
      currentDoc = sub.doc_id;
      await chrome.storage.local.set({ lastDocId: currentDoc });
      await renderTimeline(currentDoc);
    } catch (e) {
      const picked = det && det.url && det.url.startsWith("file://");
      setPanel(head() + body(`<div class="rt-err">Analysis failed: ${esc(e.message)}</div>
        ${picked ? `<div class="rt-hint">Chrome blocked direct reading of this local file. Pick it below instead — analysis runs the same pipeline:</div>
        <div class="rt-row"><input type="file" id="rt-file" accept=".pdf,.docx,.txt"><button id="rt-go">Analyze</button></div>`
        : `<div class="rt-hint">The resume may be scanned (OCR needed) or the URL may block server-side fetch — try uploading the file via the popup.</div>`}`));
      bindClose();
      const go = document.getElementById("rt-go");
      if (go) go.onclick = panelUpload;
    }
  }

  async function panelUpload() {
    const f = document.getElementById("rt-file")?.files[0];
    if (!f) return;
    setPanel(head() + body(`<div class="rt-loading">Processing ${esc(f.name)}…</div>`));
    bindClose();
    try {
      const bytes = new Uint8Array(await f.arrayBuffer());
      let bin = "";
      for (let i = 0; i < bytes.length; i += 8192)
        bin += String.fromCharCode(...bytes.subarray(i, i + 8192));
      const sub = await send({
        type: "rt-submit",
        payload: { filename: f.name, content_b64: btoa(bin), source: "extension-file" },
      });
      currentDoc = sub.doc_id;
      await chrome.storage.local.set({ lastDocId: currentDoc });
      await renderTimeline(currentDoc);
    } catch (e) {
      setPanel(head() + body(`<div class="rt-err">Analysis failed: ${esc(e.message)}</div>`));
      bindClose();
    }
  }

  const head = () =>
    `<div class="rt-head"><strong>Resume Timeline</strong><button class="rt-x" id="rt-close">✕</button></div>`;
  const body = (inner) => `<div class="rt-body">${inner}</div>`;

  function bindClose() {
    const b = document.getElementById("rt-close");
    if (b) b.onclick = () => togglePanel(false);
  }

  // ------------------------------------------------ render
  async function renderTimeline(docId) {
    const dto = await send({ type: "rt-timeline", docId });
    bindNone();
    const gaps = dto.gaps || [];
    const events = dto.timeline || [];
    const unres = dto.unresolved_events || [];

    let statusBanner = "";
    if (dto.status === "FAILED")
      statusBanner = `<div class="rt-err">Processing failed — see details below. The resume may be scanned or empty.</div>`;
    else if (events.length === 0)
      statusBanner = `<div class="rt-warn">Insufficient evidence: no dated roles found. No gaps inferred.</div>`;

    const evHtml = events
      .map((e) => `<li class="rt-ev"><span class="rt-dot"></span><div>
        <div class="rt-ev-t">${esc(e.title || "Untitled")} ${e.org ? `<span class="rt-org">@ ${esc(e.org)}</span>` : ""}</div>
        <div class="rt-ev-d">${esc(e.start || "?")} → ${esc(e.end || "?")} · ${esc(e.type)} · conf ${e.confidence}</div>
      </div></li>`)
      .join("");

    const gapHtml = gaps
      .map((g) => {
        if (g.state === "NO_GAP_DETECTED")
          return `<div class="rt-ok">No gaps detected — continuous representation.</div>`;
        if (g.state === "INSUFFICIENT_EVIDENCE")
          return `<div class="rt-warn">Gap analysis not possible: ${esc((g.evidence && g.evidence.note) || "not enough dated events")}.</div>`;
        if (g.state === "DISMISSED_GAP")
          return `<div class="rt-muted">Dismissed by recruiter: ${esc(g.start)} → ${esc(g.end)} (${g.months}m).</div>`;
        const quotes = (g.evidence_quotes || []).map((q) => `<blockquote>“${esc(q)}”</blockquote>`).join("");
        return `<div class="rt-gap" data-gap="${esc(g.id)}">
          <div class="rt-gap-t">Potential unrepresented period: ${esc(g.start)} → ${esc(g.end)} (${g.months} mo)</div>
          <div class="rt-gap-c">confidence ${g.confidence} · reasons: ${esc((g.reasons || []).join(", "))}</div>
          ${quotes}
          <div class="rt-row">
            <button data-act="evidence" data-gap="${esc(g.id)}">Evidence</button>
            <button data-act="dismiss" data-gap="${esc(g.id)}">Dismiss</button>
          </div>
          <div class="rt-evbox rt-hidden" id="rt-ev-${esc(g.id)}"></div>
        </div>`;
      })
      .join("");

    const unresHtml = unres.length
      ? `<h4>Needs review (${unres.length})</h4><ul class="rt-unres">${unres
          .map((e) => `<li>${esc(e.title || e.type)} ${e.org ? `@ ${esc(e.org)}` : ""}<br><small>${esc((e.entry_text || "").slice(0, 160))}</small></li>`)
          .join("")}</ul>`
      : "";

    setPanel(head() + body(`
      ${statusBanner}
      <div class="rt-file">${esc(dto.filename)} · <span class="rt-status">${esc(dto.status)}</span></div>
      <h4>Timeline (${events.length})</h4><ul class="rt-tl">${evHtml || "<li>—</li>"}</ul>
      <h4>Unrepresented periods</h4>${gapHtml || "<div>—</div>"}
      ${unresHtml}
      <div class="rt-disc">${esc(dto.disclaimer || "")}</div>`));
    bindClose();
    document.querySelectorAll("#rt-panel [data-act]").forEach((btn) => {
      btn.onclick = () => onGapAction(btn.dataset.act, btn.dataset.gap);
    });
  }

  function bindNone() {
    bindClose();
  }

  async function onGapAction(act, gapId) {
    if (!currentDoc) return;
    if (act === "dismiss") {
      await send({ type: "rt-feedback", docId: currentDoc, payload: { dismissed_gap_ids: [gapId], overrides: [], notes: "dismissed in browser" } });
      await renderTimeline(currentDoc);
    } else if (act === "evidence") {
      const box = document.getElementById(`rt-ev-${gapId}`);
      if (!box) return;
      if (!box.classList.contains("rt-hidden")) return box.classList.add("rt-hidden");
      const ev = await send({ type: "rt-evidence", docId: currentDoc, params: { gap_id: gapId } });
      const links = (ev.chain?.links || [])
        .map((l) => `<div class="rt-link"><div><strong>${esc(l.event?.title || "")}</strong> @ ${esc(l.event?.org || "")}</div>
          <div><small>assoc: ${esc((l.associations || []).map((a) => `${a.status}/${a.reason}`).join("; "))}</small></div>
          <div><small>dates: ${esc((l.mentions || []).map((m) => m.raw).join("; "))}</small></div>
          <blockquote>“${esc(l.entry_quote || "")}”</blockquote></div>`)
        .join("");
      box.innerHTML = links || "<small>No chain available.</small>";
      box.classList.remove("rt-hidden");
    }
  }

  // ------------------------------------------------ boot (non-intrusive: pill only)
  ensureUI();

  // Popup can ask an already-detected page to show a freshly uploaded doc.
  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (msg && msg.type === "rt-show-doc" && msg.docId) {
      currentDoc = msg.docId;
      togglePanel(true);
      renderTimeline(msg.docId).then(
        () => reply({ ok: true }),
        (e) => reply({ _rtError: String(e.message || e) })
      );
      return true;
    }
    return undefined;
  });
})();
