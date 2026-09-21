const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let listener, submitted, allowed = true, requested;
const context = {
  URL, Uint8Array, btoa, importScripts() {},
  RT_API: { submit: async p => { submitted = p; return { doc_id: 'test' }; } },
  fetch: async (url, options) => { requested = { url, options }; return { ok: true, arrayBuffer: async () => new TextEncoder().encode('%PDF-test').buffer }; },
  chrome: {
    extension: { isAllowedFileSchemeAccess: async () => allowed },
    runtime: { onInstalled: { addListener() {} }, onMessage: { addListener(f) { listener = f; } } },
    contextMenus: { onClicked: { addListener() {} } },
    webNavigation: { onCompleted: { addListener() {} } },
  },
};
vm.runInNewContext(fs.readFileSync(__dirname + '/background.js', 'utf8'), context);
const send = msg => new Promise(resolve => listener(msg, {}, resolve));
(async () => {
  const payload = await send({ type: 'rt-read-resume', url: 'file:///tmp/My%20Resume.pdf#page=2' });
  assert.equal(payload.filename, 'My Resume.pdf');
  assert.equal(atob(payload.content_b64), '%PDF-test');
  await send({ type: 'rt-submit', payload });
  assert.equal(submitted, payload);
  allowed = false;
  assert.match((await send({ type: 'rt-read-resume', url: 'file:///tmp/cv.pdf' }))._rtError, /Allow access/);
  assert.match((await send({ type: 'rt-read-resume', url: 'chrome://settings' }))._rtError, /original/);
  await send({ type: 'rt-read-resume', url: 'https://example.com/cv.pdf?token=abc' });
  assert.equal(requested.options.credentials, 'include');
  assert.equal(requested.url, 'https://example.com/cv.pdf?token=abc');
  console.log('Browser document relay tests passed');
})().catch(e => { console.error(e); process.exitCode = 1; });
