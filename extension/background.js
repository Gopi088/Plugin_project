/* MV3 service worker: detection signals + backend relay (avoids page CSP).
   The worker is event-driven and keeps no analysis state. */
importScripts("./api.js", "./source-viewer.js", "./native-pdf.js");

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
  return { filename, content_b64: btoa(bin), source: "extension-browser", source_url: parsed.href.split("#")[0] };
}

const canonical = url => String(url || '').split('#')[0];
const sessionStore = () => chrome.storage.session || chrome.storage.local;
async function currentTab(tabId) {
  if (tabId !== undefined) return chrome.tabs.get(tabId);
  return (await chrome.tabs.query({active:true,currentWindow:true}))[0];
}
async function bindDocument(payload, sender, tabId, result) {
  const tab = sender.tab || await currentTab(tabId);
  if(!tab?.id) return;
  const binding = {docId:result.doc_id,tabId:tab.id,tabUrl:canonical(tab.url),
    sourceUrl:canonical(payload.source_url || payload.viewer_url || '')};
  await sessionStore().set({['rt:tab:'+tab.id]:binding, latestTabId:tab.id, latestDocId:result.doc_id});
  if (chrome.storage?.local?.set) await chrome.storage.local.set({ latestTabId: tab.id, lastDocId: result.doc_id }).catch(() => {});
  await chrome.sidePanel.setOptions({tabId:tab.id,path:'viewer.html?tab='+tab.id,enabled:true});
}
globalThis.bindDocument = bindDocument;
async function getCurrentDocument(tabId) {
  const tab = await currentTab(tabId);
  if(!tab?.id)return null;
  const value=(await sessionStore().get('rt:tab:'+tab.id))['rt:tab:'+tab.id];
  return value && value.tabUrl===canonical(tab.url) ? value : null;
}
async function highlightExisting(msg, sender) {
  const binding=await getCurrentDocument(msg.tabId ?? sender.tab?.id);
  if(!binding || binding.docId!==msg.docId || !binding.sourceUrl)
    throw new Error('Open and analyze this resume in the current tab before viewing its evidence.');
  if (!Array.isArray(msg.locations) || !msg.locations.length)
    throw new Error('No exact source location is available for this item.');
  let result;
  try {
    result=await chrome.tabs.sendMessage(binding.tabId,{
      type:'rt-highlight-source',docId:msg.docId,locations:msg.locations
    });
  } catch (error) { result={nativePdf:true}; }
  // Native PDFs can return a generic source error from an older or outer-frame
  // content script. Decide from the bound document, not that script's marker.
  if(!result?.highlighted && binding.sourceUrl===binding.tabUrl && msg.locations.every(l=>l.kind==='pdf'))
    return RT_NATIVE_PDF.show(binding,msg.locations);
  if (result?._rtError) throw new Error(result._rtError);
  if (!result?.highlighted) throw new Error('The viewer could not highlight this source.');
  return result;
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
      if (m.type === "rt-submit") {
        const result=await RT_API.submit(m.payload);
        await bindDocument(m.payload,_sender,m.tabId,result);
        return result;
      }
      if(m.type==='rt-current-document')return await getCurrentDocument(m.tabId);
      if(m.type==='rt-highlight')return await highlightExisting(m,_sender);
      if(m.type==='rt-add-note')return await RT_API.addNote(m.docId,m.payload);
      if(m.type==='rt-state')return await RT_API.saveState(m.docId,m.payload);
      if (m.type === "rt-status") return await RT_API.status(m.docId);
      if (m.type === "rt-timeline") return await RT_API.timeline(m.docId);
      if (m.type === "rt-evidence") return await RT_API.evidence(m.docId, m.params);
      if (m.type === "rt-source-page") return await RT_API.sourcePage(m.docId, m.page);
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
