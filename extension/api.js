/* Shared backend client (classic script: loaded before content.js,
   imported via importScripts in the service worker). */
var RT_API = (() => {
  const DEFAULT_BASE = "http://127.0.0.1:8000";

  async function base() {
    try {
      const s = await chrome.storage.local.get("apiBase");
      return (s.apiBase || DEFAULT_BASE).replace(/\/$/, "");
    } catch (e) {
      return DEFAULT_BASE;
    }
  }

  async function req(path, opts = {}) {
    const b = await base();
    const res = await fetch(b + path, {
      ...opts,
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    });
    if (!res.ok) {
      const t = await res.text().catch(() => "");
      throw new Error(`backend ${res.status}: ${t.slice(0, 200)}`);
    }
    return res.json();
  }

  return {
    addNote: (id, payload) => req(`/api/documents/${id}/notes`, {method:'POST',body:JSON.stringify(payload)}),
    saveState: (id, payload) => req(`/api/documents/${id}/state`, {method:'POST',body:JSON.stringify(payload)}),
    health: () => req("/health"),
    submit: (payload) =>
      req("/api/documents", { method: "POST", body: JSON.stringify(payload) }),
    status: (id) => req(`/api/documents/${id}/status`),
    timeline: (id) => req(`/api/documents/${id}/timeline`),
    evidence: (id, params) =>
      req(`/api/documents/${id}/evidence?${new URLSearchParams(params)}`),
    sourcePage: (id, page) => req(`/api/documents/${encodeURIComponent(id)}/source-page?page=${encodeURIComponent(page)}`),
    stages: (id) => req(`/api/documents/${id}/stages`),
    feedback: (id, payload) =>
      req(`/api/documents/${id}/feedback`, { method: "POST", body: JSON.stringify(payload) }),
    quality: () => req("/api/quality"),
  };
})();
