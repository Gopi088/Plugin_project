"""Existing HTML resume -> live API -> evidence -> notes/state -> page reload."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from tests import test_e2e as api_harness

CHROME = shutil.which('google-chrome')
if CHROME:
    try:
        if subprocess.run([CHROME, '--version'], capture_output=True, timeout=5).returncode != 0:
            CHROME = None
    except Exception:
        CHROME = None


@unittest.skipUnless(CHROME, 'Chrome required')
class TestBrowserFlow(unittest.TestCase):
    def test_analysis_notes_and_original_evidence_after_reload(self):
        api_harness.TestAPI.setUpClass()
        try:
            with tempfile.TemporaryDirectory(prefix='.rt-flow-',dir=ROOT,ignore_cleanup_errors=True) as tmp:
                setup = r'''
let receive,failNote=true;
window.open=()=>{throw Error('Unexpected new window');};
window.chrome={storage:{local:{
 get:async keys=>Object.fromEntries(keys.map(k=>[k,JSON.parse(localStorage.getItem(k)||'null')])),
 set:async values=>{for(const [k,v] of Object.entries(values))localStorage.setItem(k,JSON.stringify(v));}
}},runtime:{onMessage:{addListener(fn){receive=fn;}},sendMessage(msg,callback){
 (async()=>{
   let path='/api/documents',body;
   if(msg.type==='rt-submit')body=msg.payload;
   else if(msg.type==='rt-timeline')path+='/'+msg.docId+'/timeline';
   else if(msg.type==='rt-feedback')return {};
   else if(msg.type==='rt-state'){path+='/'+msg.docId+'/state';body=msg.payload;}
   else if(msg.type==='rt-add-note'){
     if(failNote){failNote=false;return {_rtError:'Test connection failure'};}
     path+='/'+msg.docId+'/notes';body=msg.payload;
   }else throw Error('Unexpected message '+msg.type);
   const response=await fetch('http://127.0.0.1:18097'+path,{method:body?'POST':'GET',
     headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
   if(!response.ok)throw Error('HTTP '+response.status);
   return response.json();
 })().then(callback).catch(error=>callback({_rtError:error.message}));
}}};
'''
                checks = r'''
const check=(ok,message)=>{if(!ok)throw Error(message);};
const wait=async fn=>{for(let i=0;i<1000;i++){if(fn())return;await new Promise(r=>setTimeout(r,20));}throw Error('Timeout: '+document.querySelector('#rt-status')?.textContent);};
(async()=>{
 document.querySelector('#rt-pill').click();
 await wait(()=>document.querySelector('.rt-period'));
 check(document.querySelector('.rt-period').textContent.includes('2 months'),'Incorrect gap');
 check(document.querySelector('.rt-sum').textContent.includes('Example University') && document.querySelector('.rt-sum').textContent.includes('Alpha Ltd'),'Gap location missing from top summary');
 check(!document.querySelector('[data-tab=review]'),'Valid dates must not create Needs review');
 const period=document.querySelector('.rt-period');period.open=true;
 await period.querySelector('[data-view]').onclick();
 const highlighted=[...CSS.highlights.get('rt-evidence')].map(r=>r.toString()).join('\n');
 check(highlighted.includes('08/2014 – 07/2018') && highlighted.includes('10/2018 – 05/2021'),'Wrong bounding evidence');
 check(document.querySelectorAll('iframe,embed,img').length===0,'Copied resume');
 if(localStorage.getItem('flow-phase')==='saved'){
   check(document.querySelector('.rt-note').textContent.includes('Recruiter Name'),'Lost author');
   check(document.querySelector('.rt-note').textContent.includes('Verify these dates'),'Lost note');
   check(document.querySelector('.rt-note time')?.dateTime,'Missing date/time');
   check(document.querySelector('#rt-top-reviewed').classList.contains('is-reviewed'),'Lost review state');
   document.body.dataset.testResult='PASS';return;
 }
 document.querySelector('[data-tab=timeline]').click();
 const first=document.querySelector('.rt-entry:not(.rt-period)');
 const id=first.dataset.item;
 await document.querySelector('#rt-top-reviewed').onclick();
 await document.querySelector(`[data-hide="${id}"]`).onclick();
 document.querySelector('#rt-notes').open=true;
 const form=document.querySelector('#rt-note-form');form.author.value='Recruiter Name';form.note.value='Verify these dates';form.oninput();
 await form.onsubmit(new Event('submit',{cancelable:true}));
 check(form.note.value==='Verify these dates','Failed save lost note draft');
 check(document.querySelector('#rt-status').textContent.includes('connection failure'),'Save failure not reported');
 await form.onsubmit(new Event('submit',{cancelable:true}));
 check(document.querySelector('.rt-note'),'Note not saved');
 localStorage.setItem('flow-phase','saved');location.reload();
})().catch(error=>{document.body.dataset.testResult='FAIL: '+error.message;});
'''
                scripts='\n'.join((ROOT/'extension'/f).read_text() for f in ('viewmodel.js','source-viewer.js','content.js'))
                html='<!doctype html><html><head><meta charset="utf-8"><title>Resume test</title><style>'+(ROOT/'extension/sidebar.css').read_text()+'</style></head><body>'
                html+='<div>😀 Test Candidate</div><h2>EDUCATION</h2><p>B.Tech, Example University 08/2014 – 07/2018</p><h2>WORK EXPERIENCE</h2><p>Engineer, Alpha Ltd 10/2018 – 05/2021</p><p>Engineer, Beta Ltd 06/2021 – Present</p>'
                html+='<script>'+setup+scripts+checks+'</script></body></html>'
                path=Path(tmp)/'flow.html';path.write_text(html)
                screenshot=Path(tmp)/'flow.png'
                run=subprocess.run([CHROME,'--headless','--no-sandbox','--disable-gpu','--no-proxy-server',
                    '--allow-file-access-from-files','--user-data-dir='+str(Path(tmp)/'profile'),
                    '--window-size=1440,1000','--virtual-time-budget=30000','--screenshot='+str(screenshot),'--dump-dom',path.as_uri()],capture_output=True,text=True,timeout=60)
                if os.environ.get('RT_FLOW_SCREENSHOT') and screenshot.exists():
                    shutil.copyfile(screenshot,os.environ['RT_FLOW_SCREENSHOT'])
                result=re.search(r'data-test-result="([^"]+)"',run.stdout)
                self.assertEqual(result.group(1) if result else run.stdout[-2500:]+run.stderr[-500:],'PASS')
        finally:
            api_harness.TestAPI.tearDownClass()
