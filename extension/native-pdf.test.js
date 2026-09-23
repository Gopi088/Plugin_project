const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let permission=false,listener,attaches=0,detaches=0,fail=false;
const binding={tabId:7,tabUrl:'file:///resume.pdf',sourceUrl:'file:///resume.pdf'};
const locations=[{kind:'pdf',page:2,fragment_text:'Bachelor of Technology'}];
const origin='chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai';
const context={setTimeout,clearTimeout,RT_SOURCE:require('./source-viewer'),chrome:{
 permissions:{contains:async()=>permission},tabs:{get:async()=>({url:binding.tabUrl})},
 debugger:{onEvent:{addListener:f=>listener=f,removeListener:()=>listener=null},
 attach:async()=>{attaches++;},detach:async()=>{detaches++;},
 sendCommand:async(s,method)=>{
   if(method==='Target.setAutoAttach')listener(s,'Target.attachedToTarget',{sessionId:'pdf',targetInfo:{url:origin+'/index.html'}});
   if(method==='Runtime.enable')listener(s,'Runtime.executionContextCreated',{context:{id:1,origin,auxData:{isDefault:true}}});
   if(method==='Runtime.evaluate')return fail?{exceptionDetails:{exception:{description:'Unsupported viewer'}}}:{result:{value:{highlighted:true}}};
 }
}}};
vm.runInNewContext(fs.readFileSync(__dirname+'/native-pdf.js','utf8'),context);
(async()=>{
 assert.equal((await context.RT_NATIVE_PDF.show(binding,locations)).needsPdfPermission,true);assert.equal(attaches,0);
 permission=true;
 await assert.rejects(()=>context.RT_NATIVE_PDF.show(binding,[{page:1,text:'ambiguous'}]),/unique/);assert.equal(attaches,0);
 assert.equal((await context.RT_NATIVE_PDF.show(binding,locations)).highlighted,true);assert.equal(detaches,1);assert.equal(listener,null);
 fail=true;await assert.rejects(()=>context.RT_NATIVE_PDF.show(binding,locations),/Unsupported viewer/);assert.equal(detaches,2);assert.equal(listener,null);
 fail=false;assert.equal((await context.RT_NATIVE_PDF.show(binding,locations)).highlighted,true);assert.equal(detaches,3);
 console.log('Native PDF permission and cleanup regressions passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
