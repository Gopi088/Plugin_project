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
  if (s.lastDocId) $("out").innerHTML = `<small>Last document: <code>${s.lastDocId}</code></small>`;
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
    `<small>${esc(dto.timeline.map((e) => `${e.start}→${e.end} ${e.title}`).join("<br>")) || "No dated roles."}` +
    (gaps.length ? `<br>Gaps: ${esc(gaps.map((g) => `${g.start}→${g.end} (${g.months}m)`).join("; "))}` : "") +
    `</small>`;
  $("view").disabled = false;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

$("view").onclick = async () => {
  if (!lastDoc) return;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
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
      payload: { filename: url.split("/").pop().split("?")[0], source_url: url, source: "extension-url" },
    });
    await chrome.storage.local.set({ lastDocId: r.doc_id, pendingUrl: "" });
    await summarize(r.doc_id, url);
  } catch (e) {
    $("out").textContent = `Failed: ${e.message}`;
  }
};

refresh();
