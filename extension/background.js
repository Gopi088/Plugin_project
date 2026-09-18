/* MV3 service worker: detection signals + backend relay (avoids page CSP).
   The worker is event-driven and keeps no analysis state. */
importScripts("./api.js");

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
      if (m.type === "rt-submit") return await RT_API.submit(m.payload);
      if (m.type === "rt-status") return await RT_API.status(m.docId);
      if (m.type === "rt-timeline") return await RT_API.timeline(m.docId);
      if (m.type === "rt-evidence") return await RT_API.evidence(m.docId, m.params);
      if (m.type === "rt-stages") return await RT_API.stages(m.docId);
      if (m.type === "rt-feedback") return await RT_API.feedback(m.docId, m.payload);
      if (m.type === "rt-health") return await RT_API.health();
      throw new Error("unknown message");
    } catch (e) {
      return { _rtError: String(e.message || e) };
    }
  })().then(reply);
  return true; // async reply
});
