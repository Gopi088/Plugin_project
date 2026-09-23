const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let reply={highlighted:true,method:'existing-pdf-coordinates'}; let delivered;
let listener, submitted, allowed = true, requested, updated, reloaded;
const stored={};
const tab={id:7,url:'file:///tmp/My%20Resume.pdf'};
const context = {
  URL, Uint8Array, btoa, setTimeout, clearTimeout, importScripts() {},
  RT_SOURCE: require('./source-viewer'),
  RT_NATIVE_PDF:{show:async()=>({needsPdfPermission:true})},
  RT_API: { submit: async p => { submitted = p; return { doc_id: 'test' }; } },
  fetch: async (url, options) => { requested = { url, options }; return { ok: true, arrayBuffer: async () => new TextEncoder().encode('%PDF-test').buffer }; },
  chrome: {
    tabs: {query:async()=>[tab],get:async()=>tab,
      update:async()=>{throw Error('Must not navigate');},reload:async()=>{throw Error('Must not reload');},
      sendMessage:async(id,msg)=>{delivered={id,msg};if(reply instanceof Error)throw reply;return reply;}},
    storage:{session:{set:async value=>Object.assign(stored,value),get:async()=>stored}},
    sidePanel:{setOptions:async()=>{}},
    extension: { isAllowedFileSchemeAccess: async () => allowed },
    runtime: { onInstalled: { addListener() {} }, onMessage: { addListener(f) { listener = f; } } },
    contextMenus: { onClicked: { addListener() {} } },
    webNavigation: { onCompleted: { addListener() {} } },
  },
};
vm.runInNewContext(fs.readFileSync(__dirname + '/background.js', 'utf8'), context);
const send = (msg,sender={}) => new Promise(resolve => listener(msg, sender, resolve));
(async () => {
  const payload = await send({ type: 'rt-read-resume', url: 'file:///tmp/My%20Resume.pdf#page=2' });
  assert.equal(payload.filename, 'My Resume.pdf');
  assert.equal(atob(payload.content_b64), '%PDF-test');
  await send({ type: 'rt-submit', payload });
  assert.equal(submitted, payload);
  const result=await send({type:'rt-highlight',docId:'test',locations:[{page:2,fragment_text:'Exact original evidence'}]});
  assert.equal(result.method,'existing-pdf-coordinates');
  await send({type:'rt-highlight',docId:'test',tabId:7,locations:[{page:2}]},{tab:{id:99}});
  assert.equal(delivered.id,7,'The explicit resume tab must win over the extension UI tab');
  assert.equal(result.highlighted,true);assert.equal(delivered.id,7);
  assert.equal(delivered.msg.docId,'test');
  assert.equal(tab.url,'file:///tmp/My%20Resume.pdf');
  reply={highlighted:false};
  assert.match((await send({type:'rt-highlight',docId:'test',locations:[{page:2}]}))._rtError,/could not highlight/);
  reply={_rtError:'This viewer does not expose the original source location for live highlighting.'};
  assert.equal((await send({type:'rt-highlight',docId:'test',locations:[{kind:'pdf',page:2}]})).needsPdfPermission,true,'Native fallback must handle the screenshot error');
  reply=new Error('Receiving end does not exist');
  assert.equal((await send({type:'rt-highlight',docId:'test',locations:[{kind:'pdf',page:2}]})).needsPdfPermission,true);
  assert.match((await send({type:'rt-highlight',docId:'test',locations:[{kind:'text',start:0,end:4}]}))._rtError,/could not highlight/);
  assert.match((await send({type:'rt-highlight',docId:'test',locations:[]}))._rtError,/exact source/);
  tab.url='https://example.com/different.pdf';
  assert.match((await send({type:'rt-highlight',docId:'test',locations:[]}))._rtError,/current tab/);
  allowed = false;
  assert.match((await send({ type: 'rt-read-resume', url: 'file:///tmp/cv.pdf' }))._rtError, /Allow access/);
  assert.match((await send({ type: 'rt-read-resume', url: 'chrome://settings' }))._rtError, /original/);
  await send({ type: 'rt-read-resume', url: 'https://example.com/cv.pdf?token=abc' });
  assert.equal(requested.options.credentials, 'include');
  assert.equal(requested.url, 'https://example.com/cv.pdf?token=abc');
  console.log('Browser document relay tests passed');
})().catch(e => { console.error(e); process.exitCode = 1; });
