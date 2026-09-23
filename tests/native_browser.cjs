const fs=require('node:fs');
const {port,url,locations,screenshot,fixture}=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
async function connect(target) {
 const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
 let id=0;const pending=new Map();
 ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);if(!p)return;pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}};
 const call=(method,params={})=>new Promise((resolve,reject)=>{const mid=++id;const timer=setTimeout(()=>reject(Error('Timed out: '+method)),15000);pending.set(mid,{resolve:r=>{clearTimeout(timer);resolve(r);},reject:e=>{clearTimeout(timer);reject(e);}});ws.send(JSON.stringify({id:mid,method,params}));});
 const evaluate=async expression=>{const r=await call('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
 return {ws,call,evaluate};
}
const targets=async()=>await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
(async()=>{
 const target=(await targets()).find(t=>t.type==='page');const page=await connect(target);let worker,panel;
 try {
  await page.call('Page.enable');await page.call('Page.navigate',{url});await new Promise(r=>setTimeout(r,2200));
  const beforeTree=await page.call('Page.getFrameTree');
  const allTargets = await targets();
  const workerTargets = allTargets.filter(t=>t.type==='service_worker' && t.url.endsWith('/background.js'));
  for (const wt of workerTargets) {
    const candidate = await connect(wt);
    const name = await candidate.evaluate('chrome.runtime?.getManifest?.()?.name').catch(()=>null);
    if (name === 'Resume Timeline & Gap Detection') {
      worker = candidate;
      break;
    }
    candidate.ws.close();
  }
  if (!worker) throw new Error('Could not find Resume Timeline extension service worker');
  const binding=await worker.evaluate(`(async()=>{const tab=(await chrome.tabs.query({})).find(t=>t.url===${JSON.stringify(url)});await bindDocument({source_url:${JSON.stringify(url)}},{tab},undefined,{doc_id:'native'});RT_API.timeline=async()=>(${JSON.stringify(fixture)});RT_API.quality=async()=>({overall_accuracy:0.875,cases:10,generated_at:'2026-09-22T10:00:00Z'});return {tabId:tab.id,origin:location.origin};})()`);
  // Load the real side-panel UI. Its real button sends through the real worker;
  // only timeline data is supplied by the isolated test fixture.
  const created=await page.call('Target.createTarget',{url:binding.origin+'/viewer.html?tab='+binding.tabId});
  panel=await connect((await targets()).find(t=>t.id===created.targetId));
  const wait=async expression=>{for(let i=0;i<100;i++){if(await panel.evaluate(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Panel failed: '+await panel.evaluate('document.documentElement.innerText'));};
  await wait("!!document.querySelector('[data-tab=timeline]')");
  await wait("document.querySelector('#rt-evaluation').textContent.includes('87.5%')");
  await panel.evaluate("document.querySelector('[data-tab=timeline]').click()");
  const countBefore=(await targets()).filter(t=>t.type==='page').length;
  for(let click=0;click<2;click++){
    await panel.evaluate("document.querySelector('#rt-status').textContent='';document.querySelector('#rt-pane-timeline [data-view]').click()");
    await wait("document.querySelector('#rt-status').textContent==='Highlighted the original resume evidence.'");
  }
  if(fixture.gaps.some(g=>g.state==='POTENTIAL_GAP')){
    await panel.evaluate("document.querySelector('[data-tab=overview]').click();document.querySelector('.rt-period').open=true;document.querySelector('#rt-status').textContent='';document.querySelector('.rt-period [data-view]').click()");
    await wait("document.querySelector('#rt-status').textContent==='Highlighted the original resume evidence.'");
  }
  // Reproduce the in-page panel path visible in the reported screenshot too.
  await worker.evaluate(`chrome.tabs.sendMessage(${binding.tabId},{type:'rt-show-doc',docId:'native'})`);
  const inPageAction=fixture.gaps.some(g=>g.state==='POTENTIAL_GAP')
    ? "document.querySelector('[data-tab=overview]').click();document.querySelector('.rt-period').open=true;document.querySelector('.rt-period [data-view]').click()"
    : "document.querySelector('[data-tab=timeline]').click();document.querySelector('#rt-pane-timeline [data-view]').click()";
  await page.evaluate(inPageAction);
  let highlighted=false;
  for(let i=0;i<100;i++){
    highlighted=await page.evaluate("document.querySelector('#rt-status')?.textContent==='Highlighted the original resume evidence.'");
    if(highlighted)break;await new Promise(r=>setTimeout(r,100));
  }
  if(!highlighted)throw Error('In-page native PDF button failed: '+await page.evaluate("document.querySelector('#rt-status')?.textContent"));
  if(!await page.evaluate("document.querySelector('#rt-evaluation').textContent.includes('87.5%')"))throw Error('In-page evaluation percentage missing');
  await page.call('Page.bringToFront');await new Promise(r=>setTimeout(r,1200));
  const shot=await page.call('Page.captureScreenshot');fs.writeFileSync(screenshot,Buffer.from(shot.data,'base64'));
  const afterTree=await page.call('Page.getFrameTree');const pages=(await targets()).filter(t=>t.type==='page');
  const attached=await worker.evaluate(`chrome.debugger.sendCommand({tabId:${binding.tabId}},'Runtime.evaluate',{expression:'void 0'}).then(()=>true,()=>false)`);
  console.log(JSON.stringify({result:{highlighted:true},attached,loaderBefore:beforeTree.frameTree.frame.loaderId,loaderAfter:afterTree.frameTree.frame.loaderId,countBefore,countAfter:pages.length,url:pages.find(t=>t.id===target.id)?.url}));
 }finally{await page.call('Browser.close').catch(()=>{});page.ws.close();worker?.ws.close();panel?.ws.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
