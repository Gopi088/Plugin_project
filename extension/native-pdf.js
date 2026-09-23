/* Optional, short-lived access to the native viewer in the bound resume tab. */
var RT_NATIVE_PDF = (() => {
  const viewerOrigin='chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai';
  const busy=new Set();
  async function show(binding,locations) {
    if (!await chrome.permissions.contains({permissions:['debugger']})) return {needsPdfPermission:true};
    if (busy.has(binding.tabId)) throw Error('A highlight is already in progress. Try again shortly.');
    if (!locations.every(l=>typeof l.fragment_text==='string' && l.fragment_text.trim()))
      throw Error('This item has no unique native PDF text anchor.');
    busy.add(binding.tabId);
    const target={tabId:binding.tabId};
    let attached=false,timer,listener;
    try {
      const ready=new Promise((resolve,reject)=>{
        timer=setTimeout(()=>reject(Error('The native PDF viewer is not ready. Try again after it finishes loading.')),8000);
        listener=(source,method,params)=>{
          if(source.tabId!==binding.tabId)return;
          if(method==='Target.attachedToTarget' && params.targetInfo.url.startsWith(viewerOrigin+'/')){
            const session={...target,sessionId:params.sessionId};
            chrome.debugger.sendCommand(session,'Runtime.enable').catch(reject);
          }
          if(method==='Runtime.executionContextCreated' && params.context.origin===viewerOrigin && params.context.auxData?.isDefault)
            resolve({session:source,contextId:params.context.id});
        };
        chrome.debugger.onEvent.addListener(listener);
      });
      // Handle a rejected readiness promise even if attaching itself fails first.
      ready.catch(()=>{});
      await chrome.debugger.attach(target,'1.3');attached=true;
      await chrome.debugger.sendCommand(target,'Target.setAutoAttach',{
        autoAttach:true,waitForDebuggerOnStart:false,flatten:true,filter:[{type:'iframe',exclude:false}]
      });
      const {session,contextId}=await ready;
      const tab=await chrome.tabs.get(binding.tabId);
      if(tab.url.split('#')[0]!==binding.tabUrl)throw Error('The resume tab changed. Analyze the open resume again.');
      const anchor=RT_SOURCE.nativeUrl(binding.sourceUrl,locations);
      const expression=`(()=>{
        const viewer=document.querySelector('pdf-viewer');
        if(!viewer?.currentController?.highlightTextFragments || !viewer.paramsParser?.getTextFragments)
          throw Error('This Chrome PDF viewer version does not support live highlighting.');
        if(viewer.originalUrl.split('#')[0]!==${JSON.stringify(binding.sourceUrl)})
          throw Error('The loaded PDF is not the analyzed resume.');
        const fragments=viewer.paramsParser.getTextFragments(${JSON.stringify(anchor)});
        if(!fragments.length)throw Error('No exact PDF evidence anchor is available.');
        viewer.viewport.goToPage(${Number(locations[0].page)-1});
        viewer.currentController.highlightTextFragments(fragments);
        return {highlighted:true,method:'live-native-pdf',page:${Number(locations[0].page)}};
      })()`;
      const result=await chrome.debugger.sendCommand(session,'Runtime.evaluate',{contextId,expression,returnByValue:true});
      if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description || 'The PDF viewer could not highlight this evidence.');
      if(!result.result?.value?.highlighted)throw Error('The PDF viewer did not accept the highlight.');
      return result.result.value;
    } finally {
      clearTimeout(timer);
      if(listener)chrome.debugger.onEvent.removeListener(listener);
      if(attached)await chrome.debugger.detach(target).catch(()=>{});
      busy.delete(binding.tabId);
    }
  }
  return {show};
})();
