/* Popup: health, settings, manual file/URL submit (via background relay). */
const $ = (id) => document.getElementById(id);
const via = (msg) =>
  new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve)).then((r) => {
    if (r && r._rtError) throw new Error(r._rtError);
    return r;
  });

async function refresh() {
  try {
    const h = await via({ type: "rt-health" });
    $("health").textContent = h.ok ? "reachable" : "unknown";
    $("health").className = h.ok ? "ok" : "bad";
  } catch (e) {
    $("health").textContent = "not reachable — start backend/server.py";
    $("health").className = "bad";
  }
  const s = await chrome.storage.local.get(["apiBase", "pendingUrl", "lastDocId"]);
  if (s.apiBase) $("apiBase").value = s.apiBase;
  if (s.pendingUrl) $("url").value = s.pendingUrl;
  if (s.lastDocId && !lastDoc) $("out").innerHTML = `<small>Last document: <code>${s.lastDocId}</code></small>`;
  try {
    const q = await via({ type: "rt-quality" });
    const pc = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
    $("quality").innerHTML =
      `<div style="font-size:20px;font-weight:800;">${pc(q.overall_accuracy)} <small style="font-weight:400;">evaluation mean F1</small></div>` +
      `<small>Jobs F1 <strong>${pc(q.job_extraction?.f1)}</strong> (P ${pc(q.job_extraction?.precision)} / R ${pc(q.job_extraction?.recall)})<br>` +
      `Gaps F1 <strong>${pc(q.gap?.f1)}</strong> (P ${pc(q.gap?.precision)} / R ${pc(q.gap?.recall)}, FPR ${pc(q.gap?.false_positive_rate)})<br>` +
      `Cases: ${q.cases ?? "—"} · evaluated: ${esc((q.generated_at || "").slice(0, 10))}</small>`;
  } catch (e) {
    $("quality").innerHTML = `<small>Not evaluated yet — run <code>venv/bin/python eval/metrics.py</code>.</small>`;
  }
}

$("save").onclick = async () => {
  await chrome.storage.local.set({ apiBase: $("apiBase").value.trim() });
  await refresh();
};

let lastDoc = null;

async function summarize(docId, label) {
  lastDoc = docId;
  const dto = await via({ type: "rt-timeline", docId });
  const gaps = (dto.gaps || []).filter((g) => g.state === "POTENTIAL_GAP");
  $("out").innerHTML =
    `<small>Analyzed <code>${docId}</code> (${dto.status}): ` +
    `${dto.timeline.length} dated events, ${gaps.length} potential unrepresented period(s).</small>`;
  $("summary").innerHTML =
    `<small>${dto.timeline.map((e) => esc(`${e.start}→${e.end} ${e.title}`)).join("<br>") || "No dated roles."}` +
    (gaps.length ? `<br>Gaps: ${esc(gaps.map((g) => `${g.start}→${g.end} (${g.months}m)`).join("; "))}` : "") +
    `<br><strong>Extraction confidence: ${typeof dto.quality?.mean_event_confidence === "number" ? Math.round(dto.quality.mean_event_confidence * 100) + "%" : "Unavailable"}</strong>` +
    `<br>Heuristic confidence; measured evaluation accuracy is shown below.</small>`;
  $("view").disabled = false;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

$("view").onclick = async () => {
  if (!lastDoc) return;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) throw new Error("No active tab found");
    await chrome.tabs.sendMessage(tab.id, { type: "rt-show-doc", docId: lastDoc });
    window.close();
  } catch (e) {
    $("out").textContent =
      "Cannot reach this tab (local files need 'Allow access to file URLs' in extension Details). Result above is complete already.";
  }
};

$("upload").onclick = async () => {
  const f = $("file").files[0];
  if (!f) return ($("out").textContent = "Choose a file first.");
  const buf = await f.arrayBuffer();
  // file -> base64 in chunks (avoid stack limits on large PDFs)
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 8192)
    bin += String.fromCharCode(...bytes.subarray(i, i + 8192));
  try {
    const r = await via({
      type: "rt-submit",
      payload: { filename: f.name, content_b64: btoa(bin), source: "extension-upload" },
    });
    await chrome.storage.local.set({ lastDocId: r.doc_id });
    await summarize(r.doc_id, f.name);
  } catch (e) {
    $("out").textContent = `Failed: ${e.message}`;
  }
};

$("sendUrl").onclick = async () => {
  const url = $("url").value.trim();
  if (!url) return ($("out").textContent = "Enter a URL first.");
  try {
    const r = await via({
      type: "rt-submit",
      payload: await via({ type: "rt-read-resume", url }),
    });
    await chrome.storage.local.set({ lastDocId: r.doc_id, pendingUrl: "" });
    await summarize(r.doc_id, url);
  } catch (e) {
    $("out").textContent = `Failed: ${e.message}`;
  }
};

async function analyzeOpenResume() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/\.(pdf|docx?|txt)(\?|#|$)/i.test(tab.url)) return;
  $("out").textContent = "Analyzing the open resume…";
  try {
    const payload = await via({ type: "rt-read-resume", url: tab.url });
    const sub = await via({ type: "rt-submit", payload });
    await chrome.storage.local.set({ lastDocId: sub.doc_id });
    await summarize(sub.doc_id);
  } catch (e) { $("out").textContent = `Analysis failed: ${e.message}`; }
}

refresh().then(analyzeOpenResume).catch((e) => { $("out").textContent = e.message; });
