/* MV3 service worker: detection signals + backend relay (avoids page CSP).
   The worker is event-driven and keeps no analysis state. */
importScripts("./api.js");

async function readResume(url) {
  const parsed = new URL(url);
  if (!["file:", "http:", "https:"].includes(parsed.protocol))
    throw new Error("Open the original PDF/DOCX file or upload this resume.");
  if (parsed.protocol === "file:" && !await chrome.extension.isAllowedFileSchemeAccess())
    throw new Error("Enable Allow access to file URLs in extension Details, then reopen the resume.");
  const response = await fetch(parsed.href, { credentials: "include" });
  if (!response.ok) throw new Error(`Cannot read resume (${response.status}).`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.length > 25000000) throw new Error("Resume exceeds the 25 MB limit.");
  let bin = "";
  for (let i = 0; i < bytes.length; i += 8192)
    bin += String.fromCharCode(...bytes.subarray(i, i + 8192));
  const filename = decodeURIComponent(parsed.pathname.split("/").pop()) || "resume";
  return { filename, content_b64: btoa(bin), source: "extension-browser" };
}

const RESUME_URL = /\.(pdf|docx?)(\?|#|$)/i;

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "rt-analyze-link",
    title: "Analyze resume timeline",
    contexts: ["link"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "rt-analyze-link" && info.linkUrl) {
    await chrome.storage.local.set({ pendingUrl: info.linkUrl });
    if (tab?.id) chrome.action.openPopup?.().catch(() => {});
  }
});

// Badge when the recruiter lands on a likely resume document.
chrome.webNavigation.onCompleted.addListener(
  async (details) => {
    if (details.frameId !== 0) return;
    if (!RESUME_URL.test(details.url)) return;
    try {
      await chrome.action.setBadgeText({ text: "CV", tabId: details.tabId });
      await chrome.action.setBadgeBackgroundColor({ color: "#1d4ed8", tabId: details.tabId });
      await chrome.storage.local.set({ detectedResumeUrl: details.url });
    } catch (e) {
      /* tab may be gone; nothing to do */
    }
  },
  { url: [{ schemes: ["http", "https"] }] }
);

// Relay: content script / popup ask the worker to call the backend so page
// Content-Security-Policy never blocks analysis traffic.
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (async () => {
    try {
      const m = msg || {};
      if (m.type === "rt-read-resume") return await readResume(m.url);
      if (m.type === "rt-submit") return await RT_API.submit(m.payload);
      if (m.type === "rt-status") return await RT_API.status(m.docId);
      if (m.type === "rt-timeline") return await RT_API.timeline(m.docId);
      if (m.type === "rt-evidence") return await RT_API.evidence(m.docId, m.params);
      if (m.type === "rt-stages") return await RT_API.stages(m.docId);
      if (m.type === "rt-feedback") return await RT_API.feedback(m.docId, m.payload);
      if (m.type === "rt-quality") return await RT_API.quality();
      if (m.type === "rt-health") return await RT_API.health();
      throw new Error("unknown message");
    } catch (e) {
      return { _rtError: String(e.message || e) };
    }
  })().then(reply);
  return true; // async reply
});
